"""
The audio output (#867): a USB sound card found by itself, each cue a tone made here at the output's volume; on a Pi without one it is said, in our words. ALSA here is a fake (no test
needs the hardware).
"""
from array import array
import threading
import time
import unittest
from typing import Any

from ..device.audio import CARDS, RATE, TONES, AudioRenderer, card_of, level, tone, usb_card
from ..device.cues import PLAYABLE
from ..plugins.plugin_base import PermanentError

class FakePcm:
	def __init__(self, alsa: "FakeAlsa", **kwargs: Any):
		self.alsa = alsa
		self.kwargs = kwargs
		self.written = bytearray()
		self.closed = False
		self.drained = False
		self.dropped = False
	def write(self, data: bytes) -> int:
		if self.alsa.pulled:
			raise OSError(19, "No such device")
		self.written += data
		return len(data) // 2
	def drain(self) -> None:
		self.drained = True
	def drop(self) -> None:
		self.dropped = True
	def close(self) -> None:
		self.closed = True

class FakeMixer:
	def __init__(self, alsa: "FakeAlsa", name: str, cardindex: int):
		self.alsa, self.name, self.card = alsa, name, cardindex
	def volumecap(self) -> list[str]:
		return ["Volume", "Joined Volume"]
	def switchcap(self) -> list[str]:
		return ["Mute", "Joined Mute"]
	def setvolume(self, volume: int) -> None:
		self.alsa.set.append((self.card, self.name, "volume", volume))
	def setmute(self, mute: int) -> None:
		self.alsa.set.append((self.card, self.name, "mute", mute))
	def close(self) -> None:
		pass

class FakeAlsa:
	"""`alsaaudio` with these cards (index: long name), each with these mixer controls; `pulled`: the card went while a cue played."""
	PCM_PLAYBACK, PCM_NORMAL, PCM_FORMAT_S16_LE = 0, 0, 2
	def __init__(self, cards: dict[int, str], busy: bool = False, controls: tuple[str, ...] = ("PCM",)):
		self.cards = cards
		self.busy = busy
		self.controls = controls
		self.pulled = False
		self.pcms: list[FakePcm] = []
		self.set: list[tuple[int, str, str, int]] = []
	@property
	def pcm(self) -> FakePcm|None:
		return self.pcms[-1] if self.pcms else None
	def card_indexes(self) -> list[int]:
		return list(self.cards)
	def card_name(self, index: int) -> tuple[str, str]:
		return (f"card{index}", self.cards[index])
	def mixers(self, cardindex: int) -> list[str]:
		return list(self.controls)
	def Mixer(self, name: str, cardindex: int) -> FakeMixer:
		return FakeMixer(self, name, cardindex)
	def PCM(self, **kwargs: Any) -> FakePcm:
		if self.busy:
			raise OSError(16, "Device or resource busy")
		self.pcms.append(FakePcm(self, **kwargs))
		return self.pcms[-1]

PI = { 0: "vc4-hdmi-0", 1: "bcm2835 Headphones" }
WITH_STICK = { **PI, 2: "USB Audio Device at usb-3f980000.usb-1.2, full speed" }

def peak(data: bytes) -> int:
	samples = array("h")
	samples.frombytes(data)
	return max(abs(s) for s in samples)

class TestTones(unittest.TestCase):
	def test_every_cue_has_a_tone_and_off_is_silence(self):
		self.assertEqual(set(TONES), set(PLAYABLE))
		self.assertEqual(tone("off", 70), b"")
		for cue in PLAYABLE:
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

	def test_each_cue_opens_the_usb_card_at_our_rate_plays_at_its_volume_and_closes_it(self):
		alsa = FakeAlsa(WITH_STICK)
		renderer = AudioRenderer(40, alsa)
		self.assertIsNone(alsa.pcm, "nothing is held open between cues")
		self.assertFalse(renderer.play("two", threading.Event(), 0.0))
		first = alsa.pcm
		assert first is not None
		self.assertEqual((first.kwargs["device"], first.kwargs["rate"], first.kwargs["channels"]), ("plughw:2,0", RATE, 1))
		self.assertEqual(bytes(first.written), tone("two", 40))
		self.assertTrue(first.drained and first.closed, "what is in the card's buffer plays out, then it is closed")
		renderer.play("one", threading.Event(), 0.0, { "volume": 90 })
		assert alsa.pcm is not None
		self.assertIsNot(alsa.pcm, first)
		self.assertEqual(bytes(alsa.pcm.written), tone("one", 90), "a Test's volume")
		self.assertFalse(renderer.play("off", threading.Event(), 0.0))
		self.assertEqual(len(alsa.pcms), 2, "Off opens nothing")

	def test_the_cards_output_controls_are_set_full_and_unmuted_once_and_its_microphone_is_left_alone(self):
		alsa = FakeAlsa(WITH_STICK, controls=("Speaker", "Mic", "Auto Gain Control"))
		renderer = AudioRenderer(70, alsa)
		self.assertEqual(alsa.set, [(2, "Speaker", "volume", 100), (2, "Speaker", "mute", 0)])
		renderer.play("one", threading.Event(), 0.0)
		self.assertEqual(len(alsa.set), 2, "a card already found is not set again")

	def test_a_cue_cut_short_stops_writing(self):
		alsa = FakeAlsa(WITH_STICK)
		renderer = AudioRenderer(70, alsa)
		stop = threading.Event()
		stop.set()
		self.assertTrue(renderer.play("slow", stop, 0.0))
		assert alsa.pcm is not None
		self.assertEqual(len(alsa.pcm.written), 0)
		self.assertTrue(alsa.pcm.dropped and alsa.pcm.closed)

	def test_a_stick_pulled_out_is_said_and_one_plugged_in_again_is_found_by_the_next_cue(self):
		alsa = FakeAlsa(WITH_STICK)
		renderer = AudioRenderer(70, alsa)
		alsa.pulled = True
		with self.assertRaises(PermanentError) as raised:
			renderer.play("two", threading.Event(), 0.0)
		self.assertEqual(str(raised.exception), "The USB sound card stopped while it played: is it still plugged in?")
		assert alsa.pcm is not None
		self.assertTrue(alsa.pcm.closed)
		alsa.pulled, alsa.cards = False, dict(PI)
		with self.assertRaises(PermanentError) as missing:
			renderer.play("two", threading.Event(), 0.0)
		self.assertTrue(str(missing.exception).startswith("No USB sound card was found"))
		# plugged in again, as another card number: found, and its controls set again
		alsa.cards = { **PI, 3: "USB Audio Device at usb-3f980000.usb-1.3, full speed" }
		self.assertFalse(renderer.play("two", threading.Event(), 0.0))
		self.assertEqual(alsa.pcm.kwargs["device"], "plughw:3,0")
		self.assertIn((3, "PCM", "volume", 100), alsa.set)

	def test_with_no_usb_card_it_says_what_to_plug_in(self):
		with self.assertRaises(PermanentError) as raised:
			AudioRenderer(70, FakeAlsa(PI))
		self.assertEqual(str(raised.exception), "No USB sound card was found: plug one in (a USB sound stick), and check that the app is given /dev/snd.")

	def test_a_card_that_cannot_be_opened_says_so_in_our_words(self):
		renderer = AudioRenderer(70, FakeAlsa(WITH_STICK, busy=True))
		with self.assertLogs("python.device.audio", "ERROR"), self.assertRaises(PermanentError) as raised:
			renderer.play("one", threading.Event(), 0.0)
		self.assertNotIn("resource busy", str(raised.exception))

	def test_the_tones_are_made_when_it_opens(self):
		tone.cache_clear()
		AudioRenderer(37, FakeAlsa(WITH_STICK))
		self.assertTrue(wait_for(lambda: tone.cache_info().currsize >= len(TONES)), "each cue at the output's volume, before the first press")

class TestCards(unittest.TestCase):
	def test_the_headphone_jack_and_hdmi_are_found_by_name_and_opened_as_each_takes(self):
		alsa = FakeAlsa(WITH_STICK)
		AudioRenderer(70, alsa, "headphones").play("one", threading.Event(), 0.0)
		assert alsa.pcm is not None
		self.assertEqual(alsa.pcm.kwargs["device"], "plughw:1,0")
		AudioRenderer(70, alsa, "hdmi").play("one", threading.Event(), 0.0)
		self.assertEqual(alsa.pcm.kwargs["device"], "plug:'hdmi:CARD=0,DEV=0'", "the hdmi device makes the frames the Pi's HDMI takes; plug turns mono into what it takes")
		AudioRenderer(70, alsa, "usb").play("one", threading.Event(), 0.0)
		self.assertEqual(alsa.pcm.kwargs["device"], "plughw:2,0")

	def test_anything_else_is_usb(self):
		for choice in (None, "", "bluetooth", 3):
			self.assertIs(card_of(choice), CARDS["usb"], choice)

	def test_each_card_says_in_our_words_when_it_is_missing_or_refused(self):
		with self.assertRaises(PermanentError) as raised:
			AudioRenderer(70, FakeAlsa({ 0: "vc4-hdmi-0" }), "headphones")
		self.assertIn("a Pi 5 or a Zero has none", str(raised.exception))
		renderer = AudioRenderer(70, FakeAlsa(PI, busy=True), "hdmi")
		with self.assertLogs("python.device.audio", "ERROR"), self.assertRaises(PermanentError) as refused:
			renderer.play("one", threading.Event(), 0.0)
		self.assertTrue(str(refused.exception).startswith("HDMI audio needs a display that plays sound connected and on"))

def wait_for(test, seconds: float = 5.0) -> bool:
	end = time.monotonic() + seconds
	while time.monotonic() < end:
		if test():
			return True
		time.sleep(0.01)
	return test()

if __name__ == "__main__":
	unittest.main()
