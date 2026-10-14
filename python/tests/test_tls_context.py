import os
import re
import ssl
import unittest

from ..task.async_http_worker_pool import tls_context

PYTHON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class TestTlsContext(unittest.TestCase):
	def test_it_verifies_like_the_platform_does_and_is_one_shared_context(self):
		context = tls_context()
		self.assertEqual((context.verify_mode, context.check_hostname), (ssl.CERT_REQUIRED, True))
		self.assertIs(tls_context(), context)

	def test_every_http_client_of_ours_is_made_with_it(self):
		"""A client made with httpx's own context offers OpenSSL 3.5's post-quantum group, which some hosts answer by dropping the connection (webcomicname.com)."""
		found = []
		for folder, _, names in os.walk(PYTHON):
			if os.sep + "tests" in folder:
				continue
			for name in names:
				if name.endswith(".py"):
					with open(os.path.join(folder, name), encoding="utf-8") as f:
						found += [(name, line.strip()) for line in f if re.search(r"httpx\.AsyncClient\(", line) and "verify=tls_context()" not in line]
		self.assertEqual(found, [], "make an httpx.AsyncClient with verify=tls_context()")

if __name__ == "__main__":
	unittest.main()
