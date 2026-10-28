import socket

def local_address() -> str|None:
	"""The address of this machine on the network it uses to reach others (nothing is sent), or None when it has none."""
	try:
		with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
			probe.connect(("10.255.255.255", 1))
			address = probe.getsockname()[0]
		return None if address.startswith("127.") or address == "0.0.0.0" else address
	except OSError:
		return None
