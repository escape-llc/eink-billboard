"""
The clock: hand angles, the catalogue and its assets (read through the configuration manager, by name), the artwork, digital and word faces, and the
route that lists the faces. Most tests use a synthetic face in a temporary source root; the shipped catalogue is checked on its own.
"""
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from ..datasources.clock import clock_face as cf
from ..datasources.clock.clock_face import Face, TypeFace, available_faces, face_choices, faces_of, hand_angles, load_face, render_clock, render_type_face
from ..datasources.clock.digital import digital_text
from ..datasources.clock.words import GRID, WORDS, lit_cells, phrase
from ..model.configuration_manager import ConfigurationManager, DatasourceAssetsManager, StaticConfigurationManager
from ..model.theme import DEFAULT_INPUTS
from ..plugins.plugin_base import PermanentError
from .test_web_api import WebApiTestBase

PYTHON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(PYTHON, "static")
DAY = datetime(2026, 10, 28)


def _png(draw: Any = None) -> bytes:
	"""A 64 px layer: transparent, with whatever `draw` puts on it."""
	im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
	if draw is not None:
		draw(ImageDraw.Draw(im))
	b = io.BytesIO()
	im.save(b, "PNG")
	return b.getvalue()


class SyntheticClock(unittest.TestCase):
	"""A source root of our own with a clock render folder: a catalogue and three layers (a grey disc, and two hands pointing at 12)."""
	def setUp(self):
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.render = os.path.join(tmp.name, "datasources", "clock", "render")
		os.makedirs(self.render)
		self.layers = {
			"dial": _png(lambda d: d.ellipse((0, 0, 63, 63), fill=(200, 200, 200, 255))),
			"hour": _png(lambda d: d.rectangle((30, 16, 33, 32), fill=(0, 0, 0, 255))),
			"minute": _png(lambda d: d.rectangle((31, 4, 32, 32), fill=(255, 0, 0, 255))),
		}
		for name, data in self.layers.items():
			with open(os.path.join(self.render, f"{name}.png"), "wb") as f:
				f.write(data)
		self.write_catalogue([
			{ "id": "plain", "name": "Plain", "size": 64, "dial": "dial", "hour": { "image": "hour" }, "minute": { "image": "minute" } },
			{ "id": "day", "name": "Day", "size": 64, "hours": 24, "dial": "dial", "hour": { "image": "hour" }, "minute": { "image": "minute" } },
			{ "id": "digits", "name": "Digits", "kind": "digital", "unlit": "outline" },
			{ "id": "letters", "name": "Letters", "kind": "words", "unlit": "secondary" },
		])
		self.cm = ConfigurationManager(source_path=tmp.name, storage_path=os.path.join(tmp.name, ".storage"))
		self.faces = faces_of(self.cm)

	def write_catalogue(self, entries: list) -> None:
		with open(os.path.join(self.render, "faces.json"), "w", encoding="utf-8") as f:
			json.dump({ "faces": entries }, f)


class TestHandAngles(unittest.TestCase):
	def test_the_hands_at_the_quarters(self):
		for (h, m), angles in {(12, 0): (0, 0), (3, 0): (90, 0), (6, 30): (195, 180), (9, 45): (292.5, 270)}.items():
			with self.subTest(time=f"{h}:{m:02d}"):
				self.assertEqual(hand_angles(DAY.replace(hour=h, minute=m)), angles)

	def test_a_24_hour_dial_goes_round_once_a_day(self):
		self.assertEqual(hand_angles(DAY.replace(hour=18), 24), (270, 0))
		self.assertEqual(hand_angles(DAY.replace(hour=6), 24), (90, 0))


class TestAssets(SyntheticClock):
	def test_a_name_is_never_a_path(self):
		for name in ("../dial", "a/b", "dial.png", "", ".hidden"):
			with self.subTest(name=name), self.assertRaises(ValueError):
				self.faces.read_png(name)

	def test_what_is_not_there_is_none(self):
		self.assertIsNone(self.faces.read_png("missing"))
		self.assertFalse(self.faces.has_png("missing"))
		self.assertIsNone(self.faces.read_json("missing"))
		self.assertEqual(self.faces.read_png("dial"), self.layers["dial"])

	def test_two_managers_of_one_folder_are_one_cache_key(self):
		self.assertEqual(faces_of(self.cm), faces_of(self.cm))
		self.assertEqual(hash(faces_of(self.cm)), hash(faces_of(self.cm)))
		self.assertNotEqual(faces_of(self.cm), DatasourceAssetsManager(os.path.join(self.render, "x")))


class TestCatalogue(SyntheticClock):
	def test_the_faces_in_order(self):
		self.assertEqual(available_faces(self.faces), ["plain", "day", "digits", "letters"])
		self.assertEqual(face_choices(self.faces)[0], { "name": "Plain", "value": "plain" })

	def test_each_kind_loads(self):
		self.assertIsInstance(load_face(self.faces, "plain"), Face)
		self.assertEqual(load_face(self.faces, "day").hours, 24)  # type: ignore[union-attr]
		self.assertEqual(load_face(self.faces, "digits"), TypeFace("digits", "Digits", "digital", "outline"))

	def test_what_cannot_be_drawn_is_permanent(self):
		hand = { "image": "hour" }
		bad = {
			"unknown": None,
			"no-layer": { "id": "no-layer", "size": 64, "dial": "nothing", "hour": hand, "minute": hand },
			"a-path": { "id": "a-path", "size": 64, "dial": "../dial", "hour": hand, "minute": hand },
			"hours": { "id": "hours", "size": 64, "hours": 7, "dial": "dial", "hour": hand, "minute": hand },
			"shadow": { "id": "shadow", "size": 64, "dial": "dial", "hour": hand, "minute": hand, "shadow": { "style": "blurry" } },
			"no-size": { "id": "no-size", "dial": "dial", "hour": hand, "minute": hand },
			"kind": { "id": "kind", "kind": "sundial" },
			"unlit": { "id": "unlit", "kind": "words", "unlit": "outline" },
		}
		self.write_catalogue([e for e in bad.values() if e is not None])
		for face_id in bad:
			with self.subTest(face=face_id), self.assertRaises(PermanentError):
				load_face(self.faces, face_id)

	def test_a_catalogue_that_cannot_be_read_is_permanent(self):
		with open(os.path.join(self.render, "faces.json"), "w", encoding="utf-8") as f:
			f.write("{ not json")
		with self.assertRaises(PermanentError):
			available_faces(self.faces)


class TestArtwork(SyntheticClock):
	def test_the_page_at_both_orientations(self):
		face = load_face(self.faces, "plain")
		assert isinstance(face, Face)
		for size in ((800, 480), (480, 800)):
			with self.subTest(size=size):
				page = render_clock(face, size, DAY.replace(hour=3), (255, 255, 255))
				self.assertEqual(page.size, size)
				# the dial is centred: its top-left and bottom-right corners are the page's color, its middle is not
				a = np.asarray(page)
				self.assertEqual(tuple(a[0, 0]), (255, 255, 255))
				self.assertEqual(tuple(a[-1, -1]), (255, 255, 255))
				self.assertNotEqual(tuple(a[size[1] // 2, size[0] // 2]), (255, 255, 255))

	def test_the_hands_have_hard_edges(self):
		face = load_face(self.faces, "plain")
		assert isinstance(face, Face)
		dial = cf.draw_dial(face, 300, DAY.replace(hour=1, minute=10))
		alpha = np.asarray(dial)[..., 3]
		# the dial is a disc (its rim is soft as drawn); inside it, where the hands are, every pixel is opaque
		self.assertTrue((alpha[100:200, 100:200] == 255).all())
		red = np.asarray(dial)[..., :3]
		self.assertTrue(((red[..., 0] == 255) & (red[..., 1] == 0)).any(), "the minute hand is drawn")


class TestWords(unittest.TestCase):
	def test_the_grid_is_rectangular_and_every_word_is_spelled_where_it_says(self):
		self.assertTrue(all(len(row) == len(GRID[0]) for row in GRID))
		for word, (row, start, length) in WORDS.items():
			with self.subTest(word=word):
				self.assertEqual(GRID[row][start:start + length], word.split("-")[-1])

	def test_every_five_minutes_of_a_day(self):
		hours = ["TWELVE", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN"]
		minutes = { 5: "FIVE", 10: "TEN", 15: "QUARTER", 20: "TWENTY", 25: "TWENTY FIVE", 30: "HALF" }
		for step in range(24 * 12):
			t = DAY + timedelta(minutes=5 * step)
			if t.minute == 0:
				expected = f"IT IS {hours[t.hour % 12]} OCLOCK"
			elif t.minute <= 30:
				expected = f"IT IS {minutes[t.minute]} PAST {hours[t.hour % 12]}"
			else:
				expected = f"IT IS {minutes[60 - t.minute]} TO {hours[(t.hour + 1) % 12]}"
			with self.subTest(time=f"{t:%H:%M}"):
				self.assertEqual(phrase(t), expected)
				# the lit letters, read in order, spell the phrase and nothing else
				self.assertEqual("".join(GRID[r][c] for r, c in sorted(lit_cells(t))), expected.replace(" ", ""))

	def test_a_time_between_steps_is_the_step_before(self):
		self.assertEqual(phrase(DAY.replace(hour=7, minute=24, second=59)), "IT IS TWENTY PAST SEVEN")
		self.assertEqual(phrase(DAY.replace(hour=23, minute=59)), "IT IS FIVE TO TWELVE")


class TestDigital(unittest.TestCase):
	def test_twelve_and_twenty_four_hours(self):
		cases = {
			(0, 5): (("00:05", ""), ("12:05", "AM")),
			(7, 5): (("07:05", ""), ("!7:05", "AM")),
			(12, 30): (("12:30", ""), ("12:30", "PM")),
			(23, 59): (("23:59", ""), ("11:59", "PM")),
		}
		for (h, m), (twenty_four, twelve) in cases.items():
			with self.subTest(time=f"{h}:{m:02d}"):
				t = DAY.replace(hour=h, minute=m)
				self.assertEqual(digital_text(t, False), twenty_four)
				self.assertEqual(digital_text(t, True), twelve)


class TestTypeFaces(SyntheticClock):
	def test_drawn_in_the_palettes_inks_only_at_both_orientations(self):
		palette = DEFAULT_INPUTS.palette
		inks = { palette.rgb(role.replace("-", "_")) for role in palette.roles() }
		stm = StaticConfigurationManager(STATIC)
		for face_id, unlit in (("digits", "outline"), ("digits", "none"), ("letters", "secondary"), ("letters", "none")):
			for size in ((800, 480), (480, 800)):
				with self.subTest(face=face_id, unlit=unlit, size=size):
					face = TypeFace(face_id, face_id, "digital" if face_id == "digits" else "words", unlit)
					page = render_type_face(face, size, DAY.replace(hour=16, minute=40), palette, stm, DEFAULT_INPUTS.font_heading, True)
					self.assertEqual(page.size, size)
					colors = { c for _, c in page.getcolors(1 << 16) or [] }
					self.assertLessEqual(colors, inks, "a color that is not an ink is dithered on a panel")
					self.assertIn(palette.rgb("text_primary"), colors)


class TestShippedCatalogue(unittest.TestCase):
	"""The faces we ship: every entry loads, every layer is there, and the descriptor's default is the first."""
	def test_every_shipped_face_loads(self):
		faces = faces_of(ConfigurationManager())
		ids = available_faces(faces)
		self.assertEqual(len(ids), len(set(ids)), "face ids are unique")
		for face_id in ids:
			with self.subTest(face=face_id):
				face = load_face(faces, face_id)
				if isinstance(face, Face):
					for layer in (face.dial, face.hour.image, face.minute.image, face.hour.shadow, face.minute.shadow):
						if layer is not None:
							self.assertIsNotNone(faces.read_png(layer))

	def test_the_descriptors_default_is_the_first_face(self):
		with open(os.path.join(PYTHON, "datasources", "clock", "datasource-info.json"), encoding="utf-8") as f:
			descriptor = json.load(f)
		face = next(p for p in descriptor["instanceSettings"]["schema"]["properties"] if p["name"] == "face")
		self.assertEqual(face["default"], available_faces(faces_of(ConfigurationManager()))[0])


class TestFacesRoute(WebApiTestBase):
	def test_the_faces_are_the_catalogue_in_order(self):
		resp = self.client.get("/api/datasource/clock/faces")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.json(), face_choices(faces_of(self.cm)))
		self.assertEqual(resp.json()[0], { "name": "Brass", "value": "brass" })
