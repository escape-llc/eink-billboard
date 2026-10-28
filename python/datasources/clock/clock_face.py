"""
The clock data source: the time on a clock face made of artwork.

A face is a folder under `faces/` (read through the configuration manager's assets) with a `face.json` and transparent PNG layers, all drawn on one square canvas:
the dial, and an hour and a minute hand drawn pointing at 12 that turn about the pivot (the canvas centre unless
`face.json` says otherwise). A hand may have a shadow layer drawn centred under it; the shadow turns with its hand
and is then moved by a fixed offset, so the light falls from the same side at every hour.

On a panel, the dial's shading dithers like a photo, which suits it. The hands' edges are made hard (each pixel
fully drawn or not), so the quantizer does not fringe them; a shadow is drawn soft as painted, solid black, or not at all.
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Mapping

import numpy as np
from PIL import Image

from ...model.configuration_manager import AssetsConfigurationManager, ConfigurationManager, SettingsConfigurationManager
from ...model.theme import current_palette
from ...plugins.plugin_base import PermanentError
from ..data_source import DataSource, DataSourceExecutionContext, MediaItemAsync, MediaRenderAsync, MediaRenderResult, target_dimensions

SHADOW_STYLES = ("soft", "solid", "none")
DIAL_FILL = 0.92  # the share of the page's shorter side the dial spans
EDGE_ALPHA = 128  # a hand pixel at least this opaque is drawn, any other is not
SHADOW_ALPHA = 64  # the same for a solid shadow, lower so the shadow keeps its shape


@dataclass(frozen=True)
class Hand:
	image: str
	shadow: str | None


@dataclass(frozen=True)
class Face:
	id: str
	name: str
	size: int
	pivot: tuple[float, float]
	dial: str  # the layers are paths, from the faces' assets manager
	hour: Hand
	minute: Hand
	hours: int
	shadow_style: str
	shadow_offset: tuple[float, float]  # as a share of the dial's size, so it scales with the panel
	white_cutoff: int | None  # dial pixels whose every channel is at least this become white (cleans off-white paper)
	credit: str


def faces_of(cm: ConfigurationManager) -> AssetsConfigurationManager:
	"""The installed faces: this data source's `faces` folder."""
	return cm.datasource_assets("clock", "faces")


def available_faces(faces: AssetsConfigurationManager) -> list[str]:
	"""The ids of the installed faces: the folders that hold a face.json."""
	return [f for f in faces.items() if faces.file_path(f, "face.json") is not None]


def load_face(faces: AssetsConfigurationManager, face_id: str) -> Face:
	"""Reads and checks one face; a face that is missing or malformed is a PermanentError (trying again cannot fix it)."""
	if face_id not in available_faces(faces):
		raise PermanentError(f"Clock face {face_id!r} is not installed")
	spec = faces.read_json(face_id, "face.json")
	if spec is None:
		raise PermanentError(f"Clock face {face_id!r}: face.json could not be read")

	def layer(name: Any) -> str:
		path = faces.file_path(face_id, str(name))
		if path is None:
			raise PermanentError(f"Clock face {face_id!r}: layer {name!r} is missing")
		return path

	def hand(entry: Any) -> Hand:
		return Hand(image=layer(entry["image"]), shadow=None if entry.get("shadow") is None else layer(entry["shadow"]))

	try:
		size = int(spec["size"])
		pivot = spec.get("pivot") or [size / 2, size / 2]
		shadow = spec.get("shadow") or {}
		style = str(shadow.get("style", "none"))
		hours = int(spec.get("hours", 12))
		face = Face(
			id=face_id,
			name=str(spec.get("name") or face_id),
			size=size,
			pivot=(float(pivot[0]), float(pivot[1])),
			dial=layer(spec["face"]),
			hour=hand(spec["hour"]),
			minute=hand(spec["minute"]),
			hours=hours,
			shadow_style=style,
			shadow_offset=_pair(shadow.get("offset", [0.0, 0.0])),
			white_cutoff=None if spec.get("whiteCutoff") is None else int(spec["whiteCutoff"]),
			credit=str(spec.get("credit") or ""),
		)
	except (ValueError, KeyError, TypeError, IndexError) as e:
		raise PermanentError(f"Clock face {face_id!r}: face.json is not valid ({e})") from e
	if hours not in (12, 24):
		raise PermanentError(f"Clock face {face_id!r}: hours must be 12 or 24, not {hours}")
	if style not in SHADOW_STYLES:
		raise PermanentError(f"Clock face {face_id!r}: shadow style must be one of {', '.join(SHADOW_STYLES)}")
	return face


def _pair(value: Any) -> tuple[float, float]:
	return (float(value[0]), float(value[1]))


def hand_angles(t: datetime, hours: int = 12) -> tuple[float, float]:
	"""Clockwise degrees from 12 of the hour and the minute hand at `t`; `hours` is 24 for a dial that goes round once a day."""
	minutes = t.minute + t.second / 60
	hour = (t.hour % hours) + minutes / 60
	return (hour * 360 / hours) % 360, (minutes * 6) % 360


@lru_cache(maxsize=48)
def _layer(path: str, size: int, white_cutoff: int | None = None) -> Image.Image:
	"""A layer scaled to `size` (cached: a face is drawn again every refresh, its artwork never changes)."""
	with Image.open(path) as im:
		layer = im.convert("RGBA")
	if layer.size != (size, size):
		layer = layer.resize((size, size), Image.Resampling.LANCZOS)
	if white_cutoff is not None:
		a = np.asarray(layer).copy()
		paper = (a[..., :3].min(axis=2) >= white_cutoff) & (a[..., 3] > 0)
		a[paper, :3] = 255
		layer = Image.fromarray(a)
	return layer


def _hard_edges(layer: Image.Image, threshold: int, color: tuple[int, int, int] | None = None) -> Image.Image:
	"""Each pixel fully drawn or not drawn at all; with `color`, every drawn pixel takes that color."""
	a = np.asarray(layer).copy()
	drawn = a[..., 3] >= threshold
	a[..., 3] = np.where(drawn, 255, 0).astype(np.uint8)
	if color is not None:
		a[drawn, :3] = color
	return Image.fromarray(a)


def _turn(layer: Image.Image, degrees: float, pivot: tuple[float, float]) -> Image.Image:
	"""Turns clockwise about `pivot`. Premultiplied (RGBa): turning straight RGBA blends the transparent pixels' black into the
	edges, a dark rim the quantizer then draws. Bilinear: bicubic overshoots at a hard edge, a bright rim."""
	turned = layer.convert("RGBa").rotate(-degrees, resample=Image.Resampling.BILINEAR, center=pivot)
	return turned.convert("RGBA")


def _shifted(canvas: Image.Image, layer: Image.Image, dx: int, dy: int) -> None:
	"""Composites `layer` onto `canvas` moved by (dx, dy), clipping what falls off an edge."""
	canvas.alpha_composite(layer, dest=(max(dx, 0), max(dy, 0)), source=(max(-dx, 0), max(-dy, 0)))


def draw_dial(face: Face, size: int, t: datetime, shadow_style: str | None = None) -> Image.Image:
	"""The face at `t` as a transparent `size` x `size` image."""
	style = shadow_style or face.shadow_style
	scale = size / face.size
	pivot = (face.pivot[0] * scale, face.pivot[1] * scale)
	dx, dy = round(face.shadow_offset[0] * size), round(face.shadow_offset[1] * size)
	dial = Image.new("RGBA", (size, size), (0, 0, 0, 0))
	dial.alpha_composite(_layer(face.dial, size, face.white_cutoff))
	hour_deg, minute_deg = hand_angles(t, face.hours)
	for hand, degrees in ((face.hour, hour_deg), (face.minute, minute_deg)):
		if hand.shadow is not None and style != "none":
			shadow = _turn(_layer(hand.shadow, size), degrees, pivot)
			if style == "solid":
				shadow = _hard_edges(shadow, SHADOW_ALPHA, (0, 0, 0))
			_shifted(dial, shadow, dx, dy)
		dial.alpha_composite(_hard_edges(_turn(_layer(hand.image, size), degrees, pivot), EDGE_ALPHA))
	return dial


def render_clock(face: Face, dimensions: tuple[int, int], t: datetime, page: tuple[int, int, int], shadow_style: str | None = None) -> Image.Image:
	"""The page: the dial centred on the page color, spanning DIAL_FILL of the shorter side."""
	width, height = dimensions
	size = max(1, int(min(width, height) * DIAL_FILL))
	canvas = Image.new("RGBA", (width, height), (*page, 255))
	canvas.alpha_composite(draw_dial(face, size, t, shadow_style), dest=((width - size) // 2, (height - size) // 2))
	return canvas.convert("RGB")


class ClockAsync(DataSource, MediaItemAsync, MediaRenderAsync):
	"""The time on an artwork clock face (see the module docstring for the face format)."""
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.logger = logging.getLogger(__name__)

	async def open_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any]) -> Any:
		faces = faces_of(dsec.provider.required(ConfigurationManager))
		installed = available_faces(faces)
		face_id = str(params.get("face") or (installed[0] if installed else ""))
		load_face(faces, face_id)  # a face that is not there fails the track now, not at every refresh
		shadow = str(params.get("shadow") or "face")
		if shadow != "face" and shadow not in SHADOW_STYLES:
			raise PermanentError(f"Clock shadow must be face, {', '.join(SHADOW_STYLES)}; not {shadow!r}")
		return {"face": face_id, "shadow": None if shadow == "face" else shadow}

	async def render_async(self, dsec: DataSourceExecutionContext, params: Mapping[str, Any], state: Any) -> MediaRenderResult | None:
		face = load_face(faces_of(dsec.provider.required(ConfigurationManager)), state["face"])
		dimensions = target_dimensions(dsec)
		page = current_palette(dsec.provider.required(SettingsConfigurationManager)).bg_page.rgb
		t = dsec.timestamp
		image = await asyncio.to_thread(render_clock, face, dimensions, t, page, state.get("shadow"))
		return MediaRenderResult(image=image, title=f"{face.name} {t:%H:%M}")
