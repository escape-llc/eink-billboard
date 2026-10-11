"""
Fetching an address somebody typed into a settings page, without letting the page reach what it should not.

The Test button of a settings field asks the server to open an address the signed-in user gave. The server may sit on the user's home
network, so the address must not be a way to reach this device itself or the platform's metadata service. The rules:
- only `http` and `https`, and a host;
- the host's addresses (all of them) must not be loopback, link-local (this includes the cloud metadata address 169.254.169.254),
  unspecified, multicast or reserved. Addresses on the home network (192.168.x.x, 10.x.x.x, unique-local IPv6) are allowed: a feed on
  a server at home is a use the device exists for;
- the check is made again for every redirect, which is followed here, not by the HTTP client.

Limit: the client resolves the name again when it connects, so a name that answers differently the second time (DNS rebinding) is not
caught. The caller is signed in and the answer carries no content, only a verdict, which keeps what that could gain small.
"""
import asyncio
import ipaddress
import socket
from typing import Mapping
from urllib.parse import urljoin, urlsplit

import httpx

class UrlRefused(Exception):
	"""The address may not be fetched; the message is ours and safe to show (it never holds the address)."""

MAX_REDIRECTS = 5

async def _resolve(host: str, port: int) -> list[str]:
	"""The addresses of a name (replaced by the tests: they have no DNS)."""
	infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
	return [str(info[4][0]) for info in infos]

def refused_reason(address: str) -> str|None:
	"""Why an IP address may not be fetched, or None when it may."""
	ip = ipaddress.ip_address(address.split("%", 1)[0])
	if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
		ip = ip.ipv4_mapped
	if ip.is_loopback or ip.is_unspecified:
		return "this device"
	if ip.is_link_local:
		return "a link-local address"
	if ip.is_multicast or ip.is_reserved:
		return "a reserved address"
	return None

async def check_url(url: str) -> None:
	"""Raise UrlRefused unless `url` is an http(s) address whose host resolves only to addresses that may be fetched."""
	parts = urlsplit(url)
	if parts.scheme not in ("http", "https") or not parts.hostname:
		raise UrlRefused("Only http and https addresses can be tested.")
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
			raise UrlRefused(f"That address is {reason}, which cannot be tested here.")

def _is_ip(host: str) -> bool:
	try:
		ipaddress.ip_address(host.split("%", 1)[0])
		return True
	except ValueError:
		return False

async def fetch_checked(client: httpx.AsyncClient, url: str, headers: Mapping[str, str]|None = None, max_bytes: int = 2 * 1024 * 1024) -> bytes:
	"""
	GET `url` (checked with `check_url`, and again at every redirect, at most MAX_REDIRECTS) and return the body.
	More than `max_bytes` is a RuntimeError; an error status raises httpx.HTTPStatusError.
	"""
	for _ in range(MAX_REDIRECTS + 1):
		await check_url(url)
		async with client.stream("GET", url, headers=headers, follow_redirects=False) as resp:
			if resp.is_redirect and resp.headers.get("location"):
				url = urljoin(url, resp.headers["location"])
				continue
			resp.raise_for_status()
			body = bytearray()
			async for chunk in resp.aiter_bytes():
				body.extend(chunk)
				if len(body) > max_bytes:
					raise RuntimeError(f"Download too large: more than {max_bytes} bytes.")
			return bytes(body)
	raise UrlRefused("The address redirects too many times.")
