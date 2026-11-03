"""
The listening socket for `--host ::` (python/web/listen.py, #860): one socket that IPv4 and IPv6 both reach, and IPv4 alone when the machine has no IPv6.
"""
import errno
import socket
import unittest
from unittest import mock

from ..web.listen import dual_stack_socket

def answers(family: int, address: str, port: int) -> bool:
	with socket.socket(family, socket.SOCK_STREAM) as client:
		client.settimeout(2)
		try:
			client.connect((address, port))
			return True
		except OSError:
			return False

class TestDualStack(unittest.TestCase):
	def test_ipv4_and_ipv6_reach_the_one_socket(self):
		sock = dual_stack_socket(0)
		if sock is None:
			self.skipTest("this machine has no IPv6")
		with sock:
			sock.listen()
			port = sock.getsockname()[1]
			self.assertEqual(sock.family, socket.AF_INET6)
			self.assertTrue(answers(socket.AF_INET, "127.0.0.1", port))
			self.assertTrue(answers(socket.AF_INET6, "::1", port))

	def test_no_ipv6_in_the_kernel_is_none(self):
		with mock.patch("python.web.listen.socket.socket", side_effect=OSError(errno.EAFNOSUPPORT, "Address family not supported by protocol")):
			self.assertIsNone(dual_stack_socket(0))

	def test_no_ipv6_address_is_none(self):
		fake = mock.MagicMock()
		fake.bind.side_effect = OSError(errno.EADDRNOTAVAIL, "Cannot assign requested address")
		with mock.patch("python.web.listen.socket.socket", return_value=fake):
			self.assertIsNone(dual_stack_socket(0))
		fake.close.assert_called_once()

	def test_a_port_in_use_raises(self):
		fake = mock.MagicMock()
		fake.bind.side_effect = OSError(errno.EADDRINUSE, "Address already in use")
		with mock.patch("python.web.listen.socket.socket", return_value=fake):
			with self.assertRaises(OSError):
				dual_stack_socket(0)
		fake.close.assert_called_once()

if __name__ == "__main__":
	unittest.main()
