"""
Which `Host` the web server answers to.

A web page the user has open can reach a server on the same machine or network by **DNS rebinding**: the page's own name first resolves to the
attacker, then to this device. The browser then treats the device as the page's own origin, so CORS does not apply, and a device without a token
can be read and changed. What the attacker cannot do is make the browser send a `Host` this device does not expect, so a request for any other
name is refused. An address (IP literal) cannot be rebound, so it is always accepted.

Accepted: `localhost`, any IP address, this machine's name and `<name>.local`, and the names given with `--allow-host` or `EINK_ALLOW_HOSTS`
(comma separated; for a device reached by a name of the user's own, or behind a proxy that changes the `Host`).
"""
import ipaddress
import os
import socket

ALLOW_ENV = "EINK_ALLOW_HOSTS"

def host_of(header: str|None) -> str|None:
	"""The name or address of a `Host` header, lower case, without the port. None when it has none."""
	if not header:
		return None
	value = header.strip().lower()
	if value.startswith("["):
		# an IPv6 address: [::1]:8080
		end = value.find("]")
		return value[1:end] if end > 0 else None
	return value.rsplit(":", 1)[0] if value.count(":") == 1 else value

def _is_ip(host: str) -> bool:
	try:
		ipaddress.ip_address(host.split("%", 1)[0])
		return True
	except ValueError:
		return False

class HostPolicy:
	def __init__(self, extra: tuple[str, ...] = ()):
		names = {"localhost"}
		try:
			machine = socket.gethostname().strip().lower()
		except OSError:
			machine = ""
		if machine:
			names.update({machine, f"{machine}.local"})
		listed = [*extra, *(os.environ.get(ALLOW_ENV) or "").split(",")]
		names.update(n.strip().lower() for n in listed if n and n.strip())
		self.names = frozenset(names)

	def allows(self, header: str|None) -> bool:
		host = host_of(header)
		if not host:
			return False
		return _is_ip(host) or host in self.names or host.endswith(".localhost")
