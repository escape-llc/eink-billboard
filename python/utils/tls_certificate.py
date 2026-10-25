"""
The device's own TLS certificate (`--ssl` without a certificate of the person's own): a self-signed one for the names the device answers to, made when
there is none, when it no longer names them all, or when it is close to its end. Only bytes here: the configuration manager keeps the files (`tls/`).

A self-signed certificate encrypts the connection but proves nothing about whose device it is, so a browser warns until it is trusted; the log gives its
SHA-256 fingerprint to compare with what the browser shows. A certificate of one's own (`--ssl-certfile`, `--ssl-keyfile`) has no warning.
"""
import datetime
import ipaddress
import ssl
from typing import Iterable

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

# how long a certificate the device makes is valid: what browsers accept for a certificate at all (398 days), less a day
VALID_DAYS = 397
# made again this long before its end, so a device that is never restarted for a while does not run past it
RENEW_DAYS = 30

def _general_name(name: str) -> x509.GeneralName:
	try:
		return x509.IPAddress(ipaddress.ip_address(name))
	except ValueError:
		return x509.DNSName(name)

def clean_names(names: Iterable[str|None]) -> list[str]:
	"""The names and addresses a certificate is for: each once, in order, lower case; an empty one, or one with a space or a slash, is left out."""
	kept: list[str] = []
	for name in names:
		text = (name or "").strip().lower().strip("[]")
		if text and not any(c in text for c in " /\\") and text not in kept:
			kept.append(text)
	return kept

def make_self_signed(names: list[str], now: datetime.datetime) -> tuple[bytes, bytes]:
	"""A new key (EC P-256) and a certificate for `names` (DNS names and IP addresses), valid from a day before `now` for VALID_DAYS: (certificate PEM, key PEM)."""
	if not names:
		raise ValueError("A certificate needs a name.")
	key = ec.generate_private_key(ec.SECP256R1())
	subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0][:64]), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "eInk Billboard")])
	start = now.astimezone(datetime.timezone.utc) - datetime.timedelta(days=1)
	certificate = (x509.CertificateBuilder()
		.subject_name(subject)
		.issuer_name(subject)
		.public_key(key.public_key())
		.serial_number(x509.random_serial_number())
		.not_valid_before(start)
		.not_valid_after(start + datetime.timedelta(days=VALID_DAYS))
		.add_extension(x509.SubjectAlternativeName([_general_name(n) for n in names]), critical=False)
		.add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
		.add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
		.sign(key, hashes.SHA256()))
	key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
	return certificate.public_bytes(serialization.Encoding.PEM), key_pem

def _names_of(certificate: x509.Certificate) -> set[str]:
	try:
		alternative = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
	except x509.ExtensionNotFound:
		return set()
	return {str(n).lower() for n in alternative.get_values_for_type(x509.DNSName)} | {str(a) for a in alternative.get_values_for_type(x509.IPAddress)}

def still_good(certificate_pem: bytes|None, names: list[str], now: datetime.datetime) -> bool:
	"""Whether a certificate the device made can be used again: it reads, names every one of `names`, and is not within RENEW_DAYS of its end."""
	if not certificate_pem:
		return False
	try:
		certificate = x509.load_pem_x509_certificate(certificate_pem)
	except ValueError:
		return False
	wanted = {str(ipaddress.ip_address(n)) if _is_address(n) else n for n in names}
	ends = certificate.not_valid_after_utc
	return wanted <= _names_of(certificate) and ends - now.astimezone(datetime.timezone.utc) > datetime.timedelta(days=RENEW_DAYS)

def _is_address(name: str) -> bool:
	try:
		ipaddress.ip_address(name)
		return True
	except ValueError:
		return False

def fingerprint(certificate_pem: bytes) -> str:
	"""The certificate's SHA-256 fingerprint as a browser shows it (`AB:CD:...`)."""
	digest = x509.load_pem_x509_certificate(certificate_pem).fingerprint(hashes.SHA256())
	return ":".join(f"{b:02X}" for b in digest)

def expires(certificate_pem: bytes) -> datetime.datetime:
	"""When the (first) certificate in the PEM ends, in UTC."""
	return x509.load_pem_x509_certificate(certificate_pem).not_valid_after_utc

def check_pair(certificate_file: str, key_file: str) -> None:
	"""
	Whether a certificate file and a key file can serve HTTPS together (the way uvicorn loads them): raises ValueError in our words when a file cannot be
	read, is not PEM, or the key is not the certificate's. Never the files' contents or OpenSSL's text.
	"""
	context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
	try:
		context.load_cert_chain(certificate_file, key_file)
	except FileNotFoundError:
		raise ValueError("The certificate or its key is not there.") from None
	except PermissionError:
		raise ValueError("The certificate or its key cannot be read by the app (its user needs to read both).") from None
	except ssl.SSLError:
		raise ValueError("The certificate and the key do not go together, or one of them is not a PEM file (a key with a passphrase cannot be used).") from None
	except OSError:
		raise ValueError("The certificate or its key cannot be read.") from None
