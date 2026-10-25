"""
HTTPS served by uvicorn itself (`--ssl`): no proxy in front. The certificate is the person's own (`--ssl-certfile` and `--ssl-keyfile`, or EINK_SSL_CERTFILE
and EINK_SSL_KEYFILE; on a Pi, Podman secrets the kit mounts), or else the device's own, a self-signed one for the names it answers to, kept in its storage
(`tls/`, through the configuration manager) and made again when a name is missing from it or it nears its end.

A certificate that cannot be used stops the start with our words: the device never falls back to plain HTTP when HTTPS was asked for.
"""
import datetime
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..model.configuration_manager import ConfigurationManager
from ..utils.tls_certificate import check_pair, clean_names, expires, fingerprint, make_self_signed, still_good
from ..utils.utils import local_address

logger = logging.getLogger(__name__)

SSL_ENV = "EINK_SSL"
CERTFILE_ENV = "EINK_SSL_CERTFILE"
KEYFILE_ENV = "EINK_SSL_KEYFILE"

def ssl_wanted(flag: bool, env: str|None) -> bool:
	"""`--ssl`, or EINK_SSL set to 1, true, yes or on."""
	return flag or (env or "").strip().lower() in ("1", "true", "yes", "on")

def device_names(allowed_hosts: tuple[str, ...], public_url: str|None) -> list[str]:
	"""What the device's own certificate is for: this machine (by name, `.local` and address), the names it is told it answers to, and its public address."""
	host = socket.gethostname()
	public_host = urlsplit(public_url).hostname if public_url else None
	return clean_names(["localhost", "127.0.0.1", "::1", host, f"{host}.local", local_address(), public_host, *allowed_hosts])

@dataclass(frozen=True)
class HttpsFiles:
	certfile: str
	keyfile: str
	# for the log: whose certificate, and what to compare with the browser
	description: str

def https_files(cm: ConfigurationManager, certfile: str|None, keyfile: str|None, names: list[str], now: datetime.datetime) -> HttpsFiles:
	"""The certificate and key to serve HTTPS with; ValueError in our words when they cannot be used."""
	if certfile or keyfile:
		if not (certfile and keyfile):
			raise ValueError("A certificate of your own needs both files: --ssl-certfile and --ssl-keyfile (or EINK_SSL_CERTFILE and EINK_SSL_KEYFILE).")
		check_pair(certfile, keyfile)
		return HttpsFiles(certfile, keyfile, "your own certificate")
	cert_pem, key_pem = cm.read_tls()
	cert_path, key_path = cm.tls_paths()
	if not (key_pem and still_good(cert_pem, names, now)):
		cert_pem, key_pem = make_self_signed(names, now)
		cm.write_tls(cert_pem, key_pem)
		logger.info(f"Made the device's own certificate for {', '.join(names)}")
	check_pair(cert_path, key_path)
	assert cert_pem is not None
	return HttpsFiles(cert_path, key_path,
		f"the device's own certificate (self-signed: a browser warns until it is trusted), SHA-256 {fingerprint(cert_pem)}, until {expires(cert_pem):%Y-%m-%d}")
