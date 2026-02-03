from typing import Tuple, Dict

class ColorTheme:
	"""Represent a simple HSL-based color theme.

	Constructor takes three values representing the base H, S and L of the
	primary color. H is number [0..360] S and L are numbers [0..100].

	The `colors()` method returns a tuple of three CSS HSL color strings:
	(primary, secondary1, secondary2). The primary color is based on the
	scheme: 'triadic', 'analogous', 'split-complementary' and 'monochrome'.

	Use `to_css_vars()` to produce a mapping of CSS variables that mirror
	the variables used by `themes.css` so the theme can be initialized in
	the stylesheet (e.g. set `--theme-h`, `--theme-s`, `--theme-param-1`).
	"""

	def __init__(self, scheme: str, hue: float, sat: float = 85, light: float = 50, angle_adj:float = 30):
		if scheme is None:
			raise ValueError("scheme cannot be None")
		if scheme not in ['triadic', 'analogous', 'split-complementary', 'monochrome']:
			raise ValueError(f"unknown scheme: {scheme}")
		if hue is None:
			raise ValueError("hue (h) cannot be None")
		# validate ranges
		if not (0.0 <= sat <= 100.0):
			raise ValueError("saturation must be between 0 and 100")
		if not (0.0 <= light <= 100.0):
			raise ValueError("lightness must be between 0 and 100")
		self.scheme = scheme
		self.hue = float(hue) % 360
		self.sat = sat
		self.light = light
		self.angle_adj = angle_adj

	def __repr__(self) -> str:
		return f"ColorTheme(scheme={self.scheme}, h={self.hue:.0f}, s={self.sat:.0f}%, l={self.light:.0f}%, angle_adj={self.angle_adj})"

	def _hsl_str(self, hue: float) -> str:
		return f"hsl({hue:.0f}, {self.sat:.0f}%, {self.light:.0f}%)"

	def colors(self) -> Tuple[str, str, str]:
		"""Return (primary, secondary1, secondary2) as CSS `hsl(...)` strings.

		scheme: 'triadic'|'analogous'|'split-complementary'|'monochrome'
		angle_adj: used by analogous and split-complementary schemes (degrees)
		"""
		base = self.hue
		adj = float(self.angle_adj)
		if self.scheme == "triadic":
			h1 = (base + 120) % 360
			h2 = (base + 240) % 360
		elif self.scheme == "analogous":
			h1 = (base - adj) % 360
			h2 = (base + adj) % 360
		elif self.scheme == "split-complementary":
			h1 = (base + 180 - adj) % 360
			h2 = (base + 180 + adj) % 360
		elif self.scheme == "monochrome":
			h1 = base
			h2 = base
		else:
			raise ValueError(f"unknown scheme: {self.scheme}")

		return (self._hsl_str(base), self._hsl_str(h1), self._hsl_str(h2))

	def to_css_vars(self, text_h: float | None = None) -> Dict[str, str]:
		"""Return a dict of CSS variable names -> values to initialize the
		theme in CSS. Variables are aligned with `themes.css`.

		Example return:
			{
				'--theme-h': '10',
				'--theme-s': '85%',
				'--theme-param-1': '30',
				'--theme-text-h': '10'
			}
		"""
		vars: Dict[str, str] = {}
		vars["--theme-h"] = f"{self.hue:.0f}"
		vars["--theme-s"] = f"{self.sat:.0f}%"
		vars["--theme-param-1"] = f"{float(self.angle_adj)}"
		# Provide a text hue if requested; default to theme hue
		vars["--theme-text-h"] = f"{(text_h if text_h is not None else self.hue):.0f}"

		# Also expose the calculated hues for convenience (matches computed CSS vars)
		primary, s1, s2 = self.colors()
		# parse out hues as integers for the color-*-hue vars
		def _h_from_hsl(hsl: str) -> str:
			# expected format: 'hsl(H, S%, L%)'
			return hsl.split("(", 1)[1].split(",", 1)[0]

		vars["--color-primary-hue"] = _h_from_hsl(primary)
		vars["--color-secondary-1-hue"] = _h_from_hsl(s1)
		vars["--color-secondary-2-hue"] = _h_from_hsl(s2)

		return vars

	def css_vars_string(self, text_h: float | None = None) -> str:
		"""Return a string suitable for embedding inside a `style` attribute
		or a `:root { ... }` block with the CSS variable assignments.
		"""
		vars = self.to_css_vars(text_h)
		return "; ".join(f"{k}: {v}" for k, v in vars.items())
