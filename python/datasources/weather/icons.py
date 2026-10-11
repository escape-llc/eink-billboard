"""
The weather icons: our own line drawings (nothing is fetched while a page renders), in the page's text color.
OpenWeatherMap names a condition with a code such as `10d` (the group, then day or night); `icon_svg` draws the one for a code.
The drawings are constants of ours, so a page may put them in as markup.
"""

_CLOUD = "M20 46h26a10 10 0 0 0 1-19.9A14 14 0 0 0 20.6 22 12 12 0 0 0 20 46z"
_CLOUD_HIGH = "M20 38h26a10 10 0 0 0 1-19.9A14 14 0 0 0 20.6 14 12 12 0 0 0 20 38z"
_SUN = '<circle cx="32" cy="32" r="10"/>' + "".join(
	f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>'
	for x1, y1, x2, y2 in ((32, 9, 32, 15), (32, 49, 32, 55), (9, 32, 15, 32), (49, 32, 55, 32), (16, 16, 20, 20), (44, 44, 48, 48), (16, 48, 20, 44), (44, 20, 48, 16)))
_MOON = '<path d="M40 10a22 22 0 1 0 14 34A18 18 0 0 1 40 10z"/>'
# a small sun or moon behind a cloud
_SUN_SMALL = '<circle cx="21" cy="21" r="6"/><line x1="21" y1="7" x2="21" y2="10"/><line x1="7" y1="21" x2="10" y2="21"/><line x1="11" y1="11" x2="13" y2="13"/><line x1="31" y1="11" x2="29" y2="13"/><line x1="11" y1="31" x2="13" y2="29"/>'
_MOON_SMALL = '<path d="M24 6a12 12 0 1 0 8 20A9.5 9.5 0 0 1 24 6z"/>'
_RAIN = '<line x1="24" y1="50" x2="21" y2="58"/><line x1="34" y1="50" x2="31" y2="58"/><line x1="44" y1="50" x2="41" y2="58"/>'
_BOLT = '<polyline points="34,44 28,54 36,54 30,62"/>'
_FLAKES = "".join(f'<circle cx="{x}" cy="{y}" r="1.6"/>' for x, y in ((24, 52), (34, 56), (44, 52)))
_MIST = "".join(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}"/>' for x1, x2, y in ((12, 52, 22), (18, 56, 32), (12, 48, 42)))

def _svg(body: str) -> str:
	return ('<svg class="wx-icon" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" '
		f'aria-hidden="true">{body}</svg>')

_GROUPS = {
	"02": lambda night: _svg((_MOON_SMALL if night else _SUN_SMALL) + f'<path d="{_CLOUD}" transform="translate(5 8)"/>'),
	"03": lambda night: _svg(f'<path d="{_CLOUD_HIGH}" transform="translate(0 6)"/>'),
	"04": lambda night: _svg(f'<path d="{_CLOUD_HIGH}" transform="translate(0 4)"/><path d="{_CLOUD}" transform="translate(6 2)"/>'),
	"09": lambda night: _svg(f'<path d="{_CLOUD_HIGH}" transform="translate(0 4)"/>{_RAIN}'),
	"10": lambda night: _svg(f'<path d="{_CLOUD_HIGH}" transform="translate(0 4)"/>{_RAIN}'),
	"11": lambda night: _svg(f'<path d="{_CLOUD_HIGH}" transform="translate(0 2)"/>{_BOLT}'),
	"13": lambda night: _svg(f'<path d="{_CLOUD_HIGH}" transform="translate(0 4)"/>{_FLAKES}'),
	"50": lambda night: _svg(_MIST),
}

def icon_svg(code: object) -> str:
	"""The drawing for an OpenWeatherMap icon code (`01d`, `10n`, ...); a code we do not know gets the plain cloud."""
	text = str(code or "")
	group, night = text[:2], text[2:3] == "n"
	if group == "01":
		return _svg(_MOON if night else _SUN)
	draw = _GROUPS.get(group)
	return draw(night) if draw else _GROUPS["03"](night)
