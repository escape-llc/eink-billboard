"""
HTTPS served by uvicorn itself (`--ssl`, python/web/https.py, python/utils/tls_certificate.py): a certificate of one's own, or the device's own self-signed
one, kept in its storage and made again when it no longer names the device or nears its end; and uvicorn really serves it.
"""
import datetime
import importlib
import os
import socket
import ssl
import tempfile
import threading
import time
import unittest

import httpx
import uvicorn
from cryptography import x509

from ..utils.tls_certificate import RENEW_DAYS, VALID_DAYS, check_pair, clean_names, expires, fingerprint, make_self_signed, still_good
from ..web.https import device_names, https_files, ssl_wanted
from .utils import temp_configuration_manager

NOW = datetime.datetime(2026, 10, 25, 12, 0, tzinfo=datetime.timezone.utc)
NAMES = ["localhost", "127.0.0.1", "::1", "pi", "pi.local", "192.168.1.20"]

class TestCertificate(unittest.TestCase):
	def test_names_are_cleaned_once_each(self):
		self.assertEqual(clean_names(["Pi.Local", "pi.local", None, "", " x ", "[::1]", "a b", "a/b"]), ["pi.local", "x", "::1"])

	def test_a_self_signed_certificate_names_the_device_by_name_and_address(self):
		cert, key = make_self_signed(NAMES, NOW)
		loaded = x509.load_pem_x509_certificate(cert)
		alternative = loaded.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
		self.assertEqual(alternative.get_values_for_type(x509.DNSName), ["localhost", "pi", "pi.local"])
		self.assertEqual([str(a) for a in alternative.get_values_for_type(x509.IPAddress)], ["127.0.0.1", "::1", "192.168.1.20"])
		self.assertEqual(expires(cert) - (NOW - datetime.timedelta(days=1)), datetime.timedelta(days=VALID_DAYS))
		self.assertIn(b"PRIVATE KEY", key)
		self.assertRegex(fingerprint(cert), r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")

	def test_it_is_used_again_while_it_names_the_device_and_is_not_near_its_end(self):
		cert, _ = make_self_signed(NAMES, NOW)
		self.assertTrue(still_good(cert, NAMES, NOW))
		self.assertTrue(still_good(cert, NAMES[:2], NOW))
		# a name it does not have (the Pi was renamed, a new address)
		self.assertFalse(still_good(cert, NAMES + ["kitchen.local"], NOW))
		# near its end
		self.assertFalse(still_good(cert, NAMES, expires(cert) - datetime.timedelta(days=RENEW_DAYS)))
		self.assertFalse(still_good(None, NAMES, NOW))
		self.assertFalse(still_good(b"not a certificate", NAMES, NOW))

	def test_a_pair_that_does_not_go_together_is_refused_in_our_words(self):
		cert, key = make_self_signed(NAMES, NOW)
		_, other_key = make_self_signed(NAMES, NOW)
		with tempfile.TemporaryDirectory() as folder:
			def write(name, data):
				path = os.path.join(folder, name)
				with open(path, "wb") as fx:
					fx.write(data)
				return path
			cert_path, key_path, other_path, junk = write("c.pem", cert), write("k.pem", key), write("o.pem", other_key), write("j.pem", b"junk")
			check_pair(cert_path, key_path)
			for args, words in (((cert_path, other_path), "do not go together"), ((junk, key_path), "not a PEM"), ((cert_path, os.path.join(folder, "none.pem")), "is not there")):
				with self.assertRaises(ValueError) as caught:
					check_pair(*args)
				self.assertIn(words, str(caught.exception))
				# our words only: never a path or OpenSSL's text
				self.assertNotIn(folder, str(caught.exception))

class TestHttpsFiles(unittest.TestCase):
	def test_ssl_is_a_flag_or_the_environment(self):
		self.assertTrue(ssl_wanted(True, None))
		for text in ("1", "true", "YES", "on "):
			self.assertTrue(ssl_wanted(False, text), text)
		for text in (None, "", "0", "off", "no"):
			self.assertFalse(ssl_wanted(False, text), text)

	def test_the_device_makes_its_own_certificate_keeps_it_and_uses_it_again(self):
		cm = temp_configuration_manager(self)
		first = https_files(cm, None, None, NAMES, NOW)
		self.assertEqual((first.certfile, first.keyfile), cm.tls_paths())
		self.assertIn("self-signed", first.description)
		cert, key = cm.read_tls()
		assert cert is not None and key is not None
		self.assertIn(fingerprint(cert), first.description)
		# the next start uses it as it is
		https_files(cm, None, None, NAMES, NOW + datetime.timedelta(days=10))
		self.assertEqual(cm.read_tls(), (cert, key))
		# a new name: a new one
		https_files(cm, None, None, NAMES + ["kitchen.local"], NOW)
		self.assertNotEqual(cm.read_tls()[0], cert)
		# it is the device's own bookkeeping, never in a backup
		self.assertFalse(any(name.startswith("tls/") for name in cm.backup_files()))
		self.assertEqual(cm.area_of(cm.tls_paths()[0]), "tls")

	def test_a_certificate_of_ones_own_needs_both_files_and_is_checked(self):
		cm = temp_configuration_manager(self)
		cert, key = make_self_signed(NAMES, NOW)
		with tempfile.TemporaryDirectory() as folder:
			cert_path, key_path = os.path.join(folder, "c.pem"), os.path.join(folder, "k.pem")
			with open(cert_path, "wb") as fx:
				fx.write(cert)
			with open(key_path, "wb") as fx:
				fx.write(key)
			own = https_files(cm, cert_path, key_path, NAMES, NOW)
			self.assertEqual((own.certfile, own.keyfile, own.description), (cert_path, key_path, "your own certificate"))
			# the device made none of its own
			self.assertEqual(cm.read_tls(), (None, None))
			with self.assertRaisesRegex(ValueError, "needs both files"):
				https_files(cm, cert_path, None, NAMES, NOW)

	def test_the_device_is_named_by_its_name_address_and_what_it_answers_to(self):
		names = device_names(("kitchen", "kitchen.local"), "https://192.168.1.20:8080")
		host = socket.gethostname().lower()
		for name in ("localhost", "127.0.0.1", "::1", host, f"{host}.local", "kitchen", "kitchen.local", "192.168.1.20"):
			self.assertIn(name, names)

class TestServedByUvicorn(unittest.TestCase):
	def test_uvicorn_serves_https_with_the_devices_certificate(self):
		cm = temp_configuration_manager(self)
		files = https_files(cm, None, None, ["localhost", "127.0.0.1"], datetime.datetime.now(datetime.timezone.utc))
		async def answer(scope, receive, send):
			await send({ "type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")] })
			await send({ "type": "http.response.body", "body": scope["scheme"].encode() })
		with socket.socket() as probe:
			probe.bind(("127.0.0.1", 0))
			port = probe.getsockname()[1]
		server = uvicorn.Server(uvicorn.Config(answer, host="127.0.0.1", port=port, log_config=None, ssl_certfile=files.certfile, ssl_keyfile=files.keyfile))
		thread = threading.Thread(target=server.run, daemon=True)
		thread.start()
		self.addCleanup(thread.join, 5)
		self.addCleanup(setattr, server, "should_exit", True)
		for _ in range(100):
			if server.started:
				break
			time.sleep(0.05)
		trust = ssl.create_default_context(cafile=files.certfile)
		answered = httpx.get(f"https://127.0.0.1:{port}/", verify=trust)
		# the app sees https, so its session cookie is Secure
		self.assertEqual((answered.status_code, answered.text), (200, "https"))
		# a client that does not trust it is refused: it is not a certificate anyone vouches for
		with self.assertRaises(httpx.ConnectError):
			httpx.get(f"https://127.0.0.1:{port}/", verify=ssl.create_default_context())

class TestSetupAddress(unittest.TestCase):
	def test_the_address_says_https_and_leaves_out_its_default_port(self):
		main = importlib.import_module("python.eink-billboard")
		self.assertTrue(main.setup_address(443, None, "https").startswith("https://"))
		self.assertNotIn(":443", main.setup_address(443, None, "https"))
		self.assertTrue(main.setup_address(8080, None, "https").endswith(":8080"))
		self.assertEqual(main.setup_address(8080, "https://pi.local:8080", "https"), "https://pi.local:8080")
		args = main.parse_args(["--ssl", "--ssl-certfile", "c.pem", "--ssl-keyfile", "k.pem"])
		self.assertEqual((args.ssl, args.ssl_certfile, args.ssl_keyfile), (True, "c.pem", "k.pem"))

if __name__ == "__main__":
	unittest.main()
