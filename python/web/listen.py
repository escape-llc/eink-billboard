"""
The listening socket for `--host ::`: every address, IPv4 and IPv6, on one socket. uvicorn alone binds `::` for IPv6 only (asyncio sets IPV6_V6ONLY), and a
browser that prefers IPv6 (Windows 11 for a `.local` name) then cannot reach the device. On a Pi the kit runs the app on the host's network with `--host ::` (#860).
"""
import errno
import socket
import sys

EVERY_ADDRESS = "::"

# IPv6 turned off: in the kernel (no IPv6 socket at all) or by sysctl (no address to bind)
NO_IPV6 = (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL)

def dual_stack_socket(port: int) -> socket.socket|None:
	"""A TCP socket bound to every IPv6 and IPv4 address on `port`, or None when this machine has no IPv6 (the caller listens on 0.0.0.0 instead).
	A port already in use raises, as uvicorn's own bind does."""
	try:
		sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
	except OSError as e:
		if e.errno in NO_IPV6:
			return None
		raise
	try:
		sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
		# as asyncio does: a restart binds again while the last one's connections are in TIME_WAIT (on Windows the option lets another program take the port)
		if sys.platform != "win32":
			sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		sock.bind((EVERY_ADDRESS, port))
	except OSError as e:
		sock.close()
		if e.errno in NO_IPV6:
			return None
		raise
	return sock
