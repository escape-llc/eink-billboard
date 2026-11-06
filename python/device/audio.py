"""
An audio output (#867, #891): a USB sound card (a sound stick and a small speaker), found by itself. It does not hold: every cue plays once, as a tone made here (`TONES`), so no sound
file ships with the app. The output's `volume` (0 to 100) scales the samples themselves; the card's own playback control is set full and unmuted when the card is found (some sticks
start muted), so the output's Volume is the one volume.

The card is found and opened for each cue, and closed after it (#906): no stream sits idle between cues (a write after an idle stream can underrun: a clipped or silent first cue), a
stick pulled out holds nothing open, and one plugged in again (its number can change) is found by the next cue. A cue whose card is gone raises our `PermanentError`, which the player
says once.

ALSA is reached with `pyalsaaudio` (the device dependency group, Linux; built in the device image against the ALSA library), imported only when the output is opened. The container is given
`/dev/snd` (deploy/eink-container.sh).
"""
from array import array
from functools import lru_cache
import logging
import math
import threading
from typing import Any, Mapping

from ..plugins.plugin_base import PermanentError

logger = logging.getLogger(__name__)

RATE = 48000
# how much is written at a time: a cue cut short stops within this
CHUNK_FRAMES = 1024
# the controls of a card that are its output (a USB stick's, the Pi's own), set full when it is found
OUTPUT_CONTROLS = ("PCM", "Speaker", "Master", "Headphone")
# a note's edges are faded this long, so it starts and ends without a click
FADE_SECONDS = 0.005

# a note: its pitch (Hz), how long it sounds (s), the silence after it (s), and whether it rings out (a bell) or holds level
type Note = tuple[float, float, float, bool]
# each cue as notes: a tick, a two-tone "bee-doop", three beeps, a chime, a low chime, an alert, a heartbeat
TONES: Mapping[str, tuple[Note, ...]] = {
	"off": (),
	"one": ((1760.0, 0.04, 0.0, False),),
	"two": ((988.0, 0.12, 0.02, False), (659.0, 0.16, 0.0, False)),
	"three": ((1319.0, 0.08, 0.06, False), (1319.0, 0.08, 0.06, False), (1319.0, 0.08, 0.0, False)),
	"steady": ((1047.0, 0.6, 0.0, True),),
	"slow": ((523.0, 0.7, 0.0, True),),
	"fast": ((1568.0, 0.07, 0.05, False), (1568.0, 0.07, 0.05, False), (1568.0, 0.07, 0.05, False), (1568.0, 0.07, 0.0, False)),
	"heartbeat": ((220.0, 0.09, 0.12, True), (220.0, 0.09, 0.0, True)),
}

def level(volume: object) -> float:
	"""A volume (0 to 100; anything else is 70) as the samples' scale, on a curve that sounds even: half the number is about half as loud."""
	value = volume if isinstance(volume, int) and not isinstance(volume, bool) and 0 <= volume <= 100 else 70
	return (value / 100) ** 2

@lru_cache(maxsize=64)
def tone(cue: str, volume: object) -> bytes:
	"""A cue's notes as 16-bit mono samples at `RATE`, at `volume` (kept: a Pi 3 takes a moment to make the longer ones, and a press should sound at once)."""
	samples = array("h")
	scale = 32767 * 0.9 * level(volume)
	fade = int(FADE_SECONDS * RATE)
	for pitch, seconds, gap, bell in TONES.get(cue, ()):
		count = int(seconds * RATE)
		for i in range(count):
			edge = min(1.0, i / fade, (count - 1 - i) / fade) if fade else 1.0
			# a bell rings out; a beep holds its level
			envelope = math.exp(-4.0 * i / count) if bell else 1.0
			samples.append(int(scale * edge * envelope * math.sin(2 * math.pi * pitch * i / RATE)))
		samples.extend([0] * int(gap * RATE))
	return samples.tobytes()

def load_alsa() -> Any:
	"""pyalsaaudio's `alsaaudio`, or a `PermanentError` that says, in our words, what to do."""
	try:
		import alsaaudio
	except ImportError as e:
		raise PermanentError("An audio output needs the device libraries (`uv sync --group device`, Raspberry Pi only).") from e
	return alsaaudio

def usb_card(alsa: Any) -> int|None:
	"""The first sound card that is a USB one (its long name says so), by its index; the Pi's own HDMI and headphone outputs are not chosen."""
	for index in alsa.card_indexes():
		_, long_name = alsa.card_name(index)
		if "USB" in long_name:
			return index
	return None

class AudioRenderer:
	"""`alsa` is the `alsaaudio` module (a test gives a fake one)."""
	holds = False

	def __init__(self, volume: object = None, alsa: Any = None):
		self._alsa = alsa or load_alsa()
		self._volume = volume
		# the card whose playback control was last set full (a stick plugged in again is set again)
		self._card: int|None = None
		self._find()
		# each cue's tone at the output's volume, made in the background: the first press sounds at once
		threading.Thread(target=self._prepare, name="audio-tones", daemon=True).start()

	def _prepare(self) -> None:
		for cue in TONES:
			tone(cue, self._volume)

	def _find(self) -> int:
		"""The USB card now, its playback control set full and unmuted when it is new; else our `PermanentError`."""
		try:
			card = usb_card(self._alsa)
		except Exception as e:
			raise PermanentError("The sound cards could not be listed: check that the app is given /dev/snd.") from e
		if card is None:
			self._card = None
			raise PermanentError("No USB sound card was found: plug one in (a USB sound stick), and check that the app is given /dev/snd.")
		if card != self._card:
			self._full(card)
			self._card = card
			logger.info(f"The sound card {card} is found.")
		return card

	def _full(self, card: int) -> None:
		"""
		The card's output controls full and unmuted: a stick that starts muted or low would make the Volume setting do nothing. Only these (`OUTPUT_CONTROLS`): a stick's `Mic`
		control has a playback volume too, which would send the microphone to the speaker. A card without them is left as it is.
		"""
		try:
			for name in self._alsa.mixers(cardindex=card):
				if name not in OUTPUT_CONTROLS:
					continue
				mixer = self._alsa.Mixer(name, cardindex=card)
				try:
					caps = mixer.volumecap()
					if "Volume" in caps or "Playback Volume" in caps:
						mixer.setvolume(100)
					switches = mixer.switchcap()
					if "Mute" in switches or "Playback Mute" in switches:
						mixer.setmute(0)
				finally:
					mixer.close()
		except Exception as e:
			logger.debug(f"The sound card {card}'s playback control could not be set ({type(e).__name__}).")

	def play(self, cue: str, stop: threading.Event, seconds: float, options: Mapping[str, Any]|None = None) -> bool:
		"""The cue's tone, once, on the card found now, written a chunk at a time; True when `stop` was set before it ended. A Test's `volume` replaces the output's."""
		volume = options.get("volume") if options is not None and options.get("volume") is not None else self._volume
		data = tone(cue, volume)
		if not data:
			return False
		card = self._find()
		try:
			# plughw: ALSA converts our 48 kHz mono to what the card takes
			pcm = self._alsa.PCM(type=self._alsa.PCM_PLAYBACK, mode=self._alsa.PCM_NORMAL, device=f"plughw:{card},0", channels=1, rate=RATE,
				format=self._alsa.PCM_FORMAT_S16_LE, periodsize=CHUNK_FRAMES)
		except Exception as e:
			logger.error(f"The sound card {card} could not be opened: {e}", exc_info=True)
			raise PermanentError("The USB sound card could not be opened: is another program using it? The log has the detail.") from e
		step = CHUNK_FRAMES * 2
		try:
			for start in range(0, len(data), step):
				if stop.is_set():
					pcm.drop()
					return True
				pcm.write(data[start:start + step])
			# what is still in the card's buffer plays out before it is closed
			pcm.drain()
			return False
		except Exception as e:
			# pulled out while it played: found again (or said missing) by the next cue
			self._card = None
			raise PermanentError("The USB sound card stopped while it played: is it still plugged in?") from e
		finally:
			pcm.close()

	def off(self) -> None:
		pass

	def close(self) -> None:
		pass
