"""
The audio output (#867): a USB sound card found by itself, each cue a tone made here at the output's volume; on a Pi without one it is said, in our words. ALSA here is a fake (no test
needs the hardware).
"""
from array import array
import threading
import unittest
from typing import Any

from ..device.audio import RATE, TONES, AudioRenderer, level, tone, usb_card
from ..device.cues import CUES
from ..plugins.plugin_base import PermanentError

class FakePcm:
	def __init__(self, **kwargs: Any):
		self.kwargs = kwargs
		self.written = bytearray()
		self.closed = False
	def write(self, data: bytes) -> int:
		self.written += data
		return len(data) // 2
	def close(self) -> None:
		self.closed = True

class FakeAlsa:
	"""`alsaaudio` with these cards (index: long name)."""
	PCM_PLAYBACK, PCM_NORMAL, PCM_FORMAT_S16_LE = 0, 0, 2
	def __init__(self, cards: dict[int, str], busy: bool = False):
		self.cards = cards
		self.busy = busy
		self.pcm: FakePcm|None = None
	def card_indexes(self) -> list[int]:
		return list(self.cards)
	def card_name(self, index: int) -> tuple[str, str]:
		return (f"card{index}", self.cards[index])
	def PCM(self, **kwargs: Any) -> FakePcm:
		if self.busy:
			raise OSError(16, "Device or resource busy")
		self.pcm = FakePcm(**kwargs)
		return self.pcm

PI = { 0: "vc4-hdmi-0", 1: "bcm2835 Headphones" }
WITH_STICK = { **PI, 2: "USB Audio Device at usb-3f980000.usb-1.2, full speed" }

def peak(data: bytes) -> int:
	samples = array("h")
	samples.frombytes(data)
	return max(abs(s) for s in samples)

class TestTones(unittest.TestCase):
	def test_every_cue_has_a_tone_and_off_is_silence(self):
		self.assertEqual(set(TONES), set(CUES))
		self.assertEqual(tone("off", 70), b"")
		for cue in CUES:
			if cue != "off":
				self.assertGreater(len(tone(cue, 70)), 0, cue)

	def test_a_tone_is_as_long_as_its_notes_and_never_clips(self):
		data = tone("two", 100)
		self.assertEqual(len(data) // 2, int(0.12 * RATE) + int(0.02 * RATE) + int(0.16 * RATE))
		self.assertLessEqual(peak(data), 32767)

	def test_the_volume_scales_the_samples_and_starts_and_ends_quietly(self):
		loud, quiet = peak(tone("one", 100)), peak(tone("one", 50))
		self.assertAlmostEqual(quiet / loud, 0.25, delta=0.02, msg="half the number is about half as loud: a quarter of the amplitude")
		self.assertEqual(peak(tone("one", 0)), 0)
		self.assertEqual(level("loud"), level(70), "anything that is not a volume is the default")
		samples = array("h")
		samples.frombytes(tone("steady", 100))
		self.assertLess(abs(samples[0]), 500, "faded in: no click")
		self.assertLess(abs(samples[-1]), 500, "faded out: no click")

class TestAudio(unittest.TestCase):
	def test_the_usb_card_is_chosen_and_the_pis_own_outputs_are_not(self):
		self.assertEqual(usb_card(FakeAlsa(WITH_STICK)), 2)
		self.assertIsNone(usb_card(FakeAlsa(PI)))

	def test_it_opens_the_usb_card_at_our_rate_and_plays_a_cue_at_its_volume(self):
		alsa = FakeAlsa(WITH_STICK)
		renderer = AudioRenderer(40, alsa)
		assert alsa.pcm is not None
		self.assertEqual((alsa.pcm.kwargs["device"], alsa.pcm.kwargs["rate"], alsa.pcm.kwargs["channels"]), ("plughw:2,0", RATE, 1))
		self.assertFalse(renderer.play("two", threading.Event(), 0.0))
		self.assertEqual(bytes(alsa.pcm.written), tone("two", 40))
		alsa.pcm.written.clear()
		renderer.play("one", threading.Event(), 0.0, { "volume": 90 })
		self.assertEqual(bytes(alsa.pcm.written), tone("one", 90), "a Test's volume")
		renderer.close()
		self.assertTrue(alsa.pcm.closed)

	def test_a_cue_cut_short_stops_writing(self):
		alsa = FakeAlsa(WITH_STICK)
		renderer = AudioRenderer(70, alsa)
		stop = threading.Event()
		stop.set()
		self.assertTrue(renderer.play("slow", stop, 0.0))
		assert alsa.pcm is not None
		self.assertEqual(len(alsa.pcm.written), 0)

	def test_with_no_usb_card_it_says_what_to_plug_in(self):
		with self.assertRaises(PermanentError) as raised:
			AudioRenderer(70, FakeAlsa(PI))
		self.assertEqual(str(raised.exception), "No USB sound card was found: plug one in (a USB sound stick), and check that the app is given /dev/snd.")

	def test_a_card_that_cannot_be_opened_says_so_in_our_words(self):
		with self.assertLogs("python.device.audio", "ERROR"), self.assertRaises(PermanentError) as raised:
			AudioRenderer(70, FakeAlsa(WITH_STICK, busy=True))
		self.assertNotIn("resource busy", str(raised.exception))

if __name__ == "__main__":
	unittest.main()
