"""
A QR code for a page the panel draws (#491): the setup page carries one that opens the web app with the setup code in it.

It is drawn as a PNG of whole pixels per module, black on white, so no edge is a grey one that the panel would dither; the page shows it at its own size (`image-rendering: pixelated`).
"""
import segno

QUIET_ZONE = 4  # modules of white around the code, which scanners need

def qr_data_uri(text: str, box: int) -> str:
	"""The code of `text` as a `data:` PNG at most `box` pixels on a side, a whole number of pixels to a module (at least 2, so a small panel's code can still be read)."""
	code = segno.make(text, error="m")
	modules, _ = code.symbol_size(scale=1, border=QUIET_ZONE)
	scale = max(2, box // modules)
	return code.png_data_uri(scale=scale, border=QUIET_ZONE, dark="#000000", light="#ffffff")
