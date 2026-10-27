"""
Fetching an address somebody typed into a settings page, without letting the page reach what it should not.

The Test button of a settings field asks the server to open an address the signed-in user gave. The server may sit on the user's home
network, so the address must not be a way to reach this device itself or the platform's metadata service. The rules:
- only `http` and `https`, and a host;
- the host's addresses (all of them) must not be loopback, link-local (this includes the cloud metadata address 169.254.169.254),
  unspecified, multicast or reserved. Addresses on the home network (192.168.x.x, 10.x.x.x, unique-local IPv6) are allowed: a feed on
  a server at home is a use the device exists for;
- the check is made again for every redirect, which is followed here, not by the HTTP client;
- credentials do not follow a redirect to another origin (#456): from the first hop whose scheme, host or port differs from the one before, or that goes
  from https to http, `Authorization`, `Proxy-Authorization` and `Cookie` are not sent again (the HTTP client does the same when it follows redirects itself).
  They must be the request's own headers: a client's default headers are the client's to send.

- the connection goes to an address that was checked, not to one the client looks up again (#477): a name that answers a public address to the check and
  `127.0.0.1` to the connect (DNS rebinding) is not followed. `stream_checked` hands the checked addresses to the request (the `vetted_addresses` extension)
  and `PinnedTransport` connects to them, one after the other as the lookup's order has it. The request's `Host` header and the TLS handshake (SNI and the
  certificate check, through the `sni_hostname` extension) keep the name, so only the address the socket is opened to changes. A connection kept alive is
  one to the checked address (the pool keys by it). This holds for the clients made with `AsyncHttpWorkerPool.make_transport()`; a client with a transport of
  its own (a test's) connects as it chooses.
"""
import asyncio
import contextlib
import ipaddress
import socket
from typing import AsyncIterator, Mapping
from urllib.parse import urljoin, urlsplit

import httpx

class UrlRefused(Exception):
	"""The address may not be fetched; the message is ours and safe to show (it never holds the address)."""

MAX_REDIRECTS = 5

async def _resolve(host: str, port: int) -> list[str]:
	"""The addresses of a name (replaced by the tests: they have no DNS)."""
	infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
	return [str(info[4][0]) for info in infos]

# NAT64's well-known prefix (RFC 6052): the IPv4 address is the last 32 bits
NAT64 = ipaddress.ip_network("64:ff9b::/96")

def embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address|None:
	"""The IPv4 address an IPv6 address stands for, when it is one of the forms that reach an IPv4 host: mapped (`::ffff:a.b.c.d`), 6to4 (`2002::/16`) or NAT64 (`64:ff9b::/96`)."""
	if ip.ipv4_mapped is not None:
		return ip.ipv4_mapped
	if ip.sixtofour is not None:
		return ip.sixtofour
	if ip in NAT64:
		return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
	return None

def refused_reason(address: str) -> str|None:
	"""
	Why an IP address may not be fetched, or None when it may. An IPv6 address that stands for an IPv4 one (mapped, 6to4, NAT64) is judged by that IPv4 address:
	on a network that translates them, `2002:7f00:1::` is this device and `64:ff9b::a9fe:a9fe` is the metadata address. Teredo is refused outright (a tunnel nothing
	on a home network needs, whose embedded address is the server's, not the destination's).
	"""
	ip: ipaddress.IPv4Address|ipaddress.IPv6Address = ipaddress.ip_address(address.split("%", 1)[0])
	if isinstance(ip, ipaddress.IPv6Address):
		if ip.teredo is not None:
			return "a reserved address"
		ip = embedded_ipv4(ip) or ip
	if ip.is_loopback or ip.is_unspecified:
		return "this device"
	if ip.is_link_local:
		return "a link-local address"
	if ip.is_multicast or ip.is_reserved:
		return "a reserved address"
	return None

async def check_url(url: str) -> list[str]:
	"""The addresses of `url`'s host, all of which may be fetched; raise UrlRefused unless `url` is an http(s) address and every address of its host may be."""
	parts = urlsplit(url)
	if parts.scheme not in ("http", "https") or not parts.hostname:
		raise UrlRefused("Only http and https addresses can be used.")
	port = parts.port or (443 if parts.scheme == "https" else 80)
	try:
		addresses = [parts.hostname] if _is_ip(parts.hostname) else await _resolve(parts.hostname, port)
	except OSError:
		raise UrlRefused("The host name could not be found.") from None
	if not addresses:
		raise UrlRefused("The host name could not be found.")
	for address in addresses:
		reason = refused_reason(address)
		if reason is not None:
			raise UrlRefused(f"That address is {reason}, which cannot be used here.")
	return addresses

# the request's extension that names the addresses the guard checked for its host
VETTED = "vetted_addresses"

class PinnedTransport(httpx.AsyncBaseTransport):
	"""
	Wraps the transport that talks to the network: a request that carries `VETTED` is sent to one of those addresses (the first that connects), with the host name
	kept for the `Host` header and for TLS (`sni_hostname`: the server name sent and the name its certificate is checked against). A request without it goes as it is.
	"""
	def __init__(self, inner: httpx.AsyncBaseTransport):
		self._inner = inner

	async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
		addresses = request.extensions.get(VETTED)
		if not addresses:
			return await self._inner.handle_async_request(request)
		failure: Exception|None = None
		for address in addresses:
			pinned = httpx.Request(request.method, request.url.copy_with(host=address), headers=request.headers, stream=request.stream,
				extensions={ **request.extensions, "sni_hostname": request.url.host })
			try:
				return await self._inner.handle_async_request(pinned)
			except (httpx.ConnectError, httpx.ConnectTimeout) as e:
				failure = e
		raise failure if failure is not None else httpx.ConnectError("No address to connect to.", request=request)

	async def aclose(self) -> None:
		await self._inner.aclose()

def _is_ip(host: str) -> bool:
	try:
		ipaddress.ip_address(host.split("%", 1)[0])
		return True
	except ValueError:
		return False

# what a request says about who is asking: never sent to another origin than the one it was written for
CREDENTIAL_HEADERS = frozenset({ "authorization", "proxy-authorization", "cookie" })
# what describes a body: dropped with the body when a redirect turns the request into a GET
BODY_HEADERS = frozenset({ "content-type", "content-length", "content-encoding", "transfer-encoding" })

def _origin(url: str) -> tuple[str, str, int]:
	parts = urlsplit(url)
	scheme = parts.scheme.lower()
	return (scheme, (parts.hostname or "").lower(), parts.port or (443 if scheme == "https" else 80))

def _redirect_method(status: int, method: str) -> str:
	"""The method of the next hop, as the HTTP client decides it when it follows redirects itself: a 303 is a GET (a HEAD stays one), and so is a POST on a 301 or 302."""
	if status == 303 and method != "HEAD":
		return "GET"
	if status in (301, 302) and method == "POST":
		return "GET"
	return method

@contextlib.asynccontextmanager
async def stream_checked(client: httpx.AsyncClient, method: str, url: str, headers: Mapping[str, str]|None = None, content: bytes|None = None) -> AsyncIterator[httpx.Response]:
	"""
	Open `url` for streaming as `client.stream` does, but with the address checked first and again at every redirect (followed here, not by the client).
	Use it for every address that is not our own constant: one typed in a settings page, or taken from a feed, an answer or a redirect.
	A redirect is followed as the HTTP client would: a 307 or 308 keeps the method and the body, a 303 (and a POST on a 301 or 302) becomes a GET with no body,
	any other method keeps itself on a 301 or 302 (a CalDAV REPORT to a collection that moved). Credentials are dropped from the first hop to another origin on.
	"""
	sent = dict(headers or {})
	for _ in range(MAX_REDIRECTS + 1):
		addresses = await check_url(url)
		async with client.stream(method, url, headers=sent, content=content, follow_redirects=False, extensions={ VETTED: addresses }) as resp:
			if resp.is_redirect and resp.headers.get("location"):
				target = urljoin(url, resp.headers["location"])
				# another origin, or the same host without TLS: the credentials stay behind, for this hop and every later one
				if _origin(target) != _origin(url) or (_origin(url)[0] == "https" and _origin(target)[0] == "http"):
					sent = { k: v for k, v in sent.items() if k.lower() not in CREDENTIAL_HEADERS }
				following = _redirect_method(resp.status_code, method)
				if following != method:
					content = None
					sent = { k: v for k, v in sent.items() if k.lower() not in BODY_HEADERS }
				method, url = following, target
				continue
			yield resp
			return
	raise UrlRefused("The address redirects too many times.")

async def fetch_checked(client: httpx.AsyncClient, url: str, headers: Mapping[str, str]|None = None, max_bytes: int = 2 * 1024 * 1024) -> bytes:
	"""
	GET `url` (checked with `check_url`, and again at every redirect, at most MAX_REDIRECTS: `stream_checked`'s rules) and return the body.
	More than `max_bytes` is a RuntimeError; an error status raises httpx.HTTPStatusError.
	"""
	async with stream_checked(client, "GET", url, headers) as resp:
		resp.raise_for_status()
		body = bytearray()
		async for chunk in resp.aiter_bytes():
			body.extend(chunk)
			if len(body) > max_bytes:
				raise RuntimeError(f"Download too large: more than {max_bytes} bytes.")
		return bytes(body)
