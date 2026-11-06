"""
The outputs (#867, #891): what the device says back, at once, while the panel takes half a minute. The GPIO settings list each piece of hardware once (`outputs`: a name, a kind and the
kind's own settings) and what each says (a feedback section per kind, `FEEDBACK`: rows of an event, an output of that kind by name and a cue); the quiet hours (`quietFrom`, `quietTo`) apply to every output alike.

Each output that is connected plays through a `Player` of its own (python/device/player.py), drawn by its kind's renderer: `gpio` (python/device/gpio_output.py), `haptic` (python/device/haptic.py) and `audio` (python/device/audio.py).
An output whose hardware is not there (no chip on the bus, no sound card) is said, in our words (`problems`), and the others play: one missing part does not take the buttons or the other
outputs down with it. A GPIO output with no pin is not connected, and nothing is opened for it.

Hardware that comes and goes (#906): a haptic or audio output whose hardware was not there is tried again every `RETRY_SECONDS`, and said when it opens; one whose hardware goes
while it is open (a sound stick pulled out) is said once by its player. The states that are on are kept here, so an output opened later shows them.
"""
from datetime import datetime
import logging
import threading
from typing import Any, Callable, Mapping

from .cues import FEEDBACK, KIND_CUES, KIND_EVENTS, KINDS
from .audio import AudioRenderer
from .gpio_output import GpioRenderer
from .haptic import HapticRenderer
from .player import Player, Renderer
from ..plugins.plugin_base import PermanentError

logger = logging.getLogger(__name__)

# the header's I2C lines, which a haptic output's driver chip is on (the Impression's Qw/ST sockets are on the Pi's I2C bus)
I2C_PINS: Mapping[str, int] = { "i2c-data": 2, "i2c-clock": 3 }

def output_rows(config: Mapping[str, Any]) -> list[Mapping[str, Any]]:
	"""The `outputs` rows that have a name and a kind we know."""
	rows = config.get("outputs")
	return [row for row in (rows if isinstance(rows, list) else []) if isinstance(row, dict) and isinstance(row.get("name"), str) and row.get("kind") in KINDS]

def output_pin(row: Mapping[str, Any]) -> int|None:
	pin = row.get("pin")
	return pin if row.get("kind") == "gpio" and isinstance(pin, int) and not isinstance(pin, bool) else None

def connected(row: Mapping[str, Any]) -> bool:
	"""An output asks for hardware: a GPIO one with its pin set, any haptic or audio one."""
	return output_pin(row) is not None or row.get("kind") in ("haptic", "audio")

def cues_for(config: Mapping[str, Any], output: str, kind: str) -> dict[str, str]:
	"""What an output of `kind` plays for each event: the rows of its kind's feedback section that name it (the first row of an event wins)."""
	cues: dict[str, str] = {}
	rows = config.get(FEEDBACK[kind]) if kind in FEEDBACK else None
	for row in rows if isinstance(rows, list) else []:
		if isinstance(row, dict) and row.get("output") == output and row.get("event") in KIND_EVENTS[kind] and row.get("cue") in KIND_CUES[kind]:
			cues.setdefault(row["event"], row["cue"])
	return cues

def make_gpio(row: Mapping[str, Any]) -> Renderer:
	pin = output_pin(row)
	assert pin is not None
	return GpioRenderer(pin, row.get("speed"))

def make_haptic(row: Mapping[str, Any]) -> Renderer:
	return HapticRenderer()

def make_audio(row: Mapping[str, Any]) -> Renderer:
	return AudioRenderer(row.get("volume"), card=row.get("card"))

# the kinds whose hardware can be plugged in after the outputs opened (a GPIO output's pin is there or refused)
RETRIED = ("haptic", "audio")

class Outputs:
	"""
	`makers` makes each kind's renderer from its row (a test gives fakes); by default the hardware's. `clock` says the time for the quiet hours; `on_play` is told each cue that starts
	(the output's name, the cue's title, why), from the output's own thread; `on_tell` is told, in our words, an output that opened late or whose hardware went (any thread).
	"""
	id = "outputs"
	# how often hardware that was not there is looked for again
	RETRY_SECONDS = 30.0

	def __init__(self, makers: Mapping[str, Callable[[Mapping[str, Any]], Renderer]]|None = None):
		self._makers = dict(makers) if makers is not None else { "gpio": make_gpio, "haptic": make_haptic, "audio": make_audio }
		self.clock: Callable[[], datetime] = lambda: datetime.now().astimezone()
		self.on_play: Callable[[str, str, str], None]|None = None
		self.on_tell: Callable[[str], None]|None = None
		self._players: dict[str, Player] = {}
		# the states that are on (an output opened later shows them), the settings opened with, the rows whose hardware was not there, and the retry's thread and stop
		self._states: set[str] = set()
		self._config: Mapping[str, Any] = {}
		self._missing: list[Mapping[str, Any]] = []
		self._lock = threading.Lock()
		self._stop = threading.Event()
		self._retry: threading.Thread|None = None
		# what could not be opened, in our words, one sentence each
		self.problems: list[str] = []

	def wanted(self, config: Mapping[str, Any]) -> bool:
		return any(connected(row) for row in output_rows(config))

	def pins(self, config: Mapping[str, Any]) -> dict[str, int]:
		found: dict[str, int] = {}
		rows = output_rows(config)
		for row in rows:
			pin = output_pin(row)
			if pin is not None:
				found[f"output-{row['name']}"] = pin
		if any(row.get("kind") == "haptic" for row in rows):
			found.update(I2C_PINS)
		return found

	def labels(self, config: Mapping[str, Any]) -> dict[str, str]:
		"""What each of `pins` is called to a person."""
		return { name: (f"output {name.removeprefix('output-')}" if name.startswith("output-") else "haptic output's I²C bus") for name in self.pins(config) }

	@property
	def names(self) -> tuple[str, ...]:
		"""The outputs that are open (a read of a dict that is replaced whole: any thread)."""
		return tuple(self._players)

	def open(self, emit: Any, config: Mapping[str, Any]) -> None:
		players: dict[str, Player] = {}
		self.problems = []
		self._config = config
		missing: list[Mapping[str, Any]] = []
		for row in output_rows(config):
			name = row["name"]
			if not connected(row) or name in players:
				continue
			player = self._make(row)
			if isinstance(player, str):
				self.problems.append(f"The output {name}: {player}")
				logger.warning(f"The output '{name}' could not be opened: {player}")
				if row["kind"] in RETRIED:
					missing.append(row)
				continue
			players[name] = player
		for player in players.values():
			player.start()
		with self._lock:
			self._players = players
			self._missing = missing
		if players:
			logger.info(f"The outputs {', '.join(players)} are open.")
		if missing:
			self._stop.clear()
			self._retry = threading.Thread(target=self._retry_missing, name="outputs-retry", daemon=True)
			self._retry.start()

	def _make(self, row: Mapping[str, Any]) -> Player|str:
		"""A player for the row, with the states that are on; or why its hardware cannot be opened, in our words."""
		name = row["name"]
		try:
			renderer = self._makers[row["kind"]](row)
		except PermanentError as e:
			return str(e)
		def told(title: str, why: str, name: str = name) -> None:
			if self.on_play is not None:
				self.on_play(name, title, why)
		def fault(message: str, name: str = name) -> None:
			self._tell(f"The output {name}: {message}")
		player = Player(name, renderer, cues_for(self._config, name, row["kind"]), self._config, self.clock, told)
		player.on_fault = fault
		with self._lock:
			for state in self._states:
				player.state(state, True)
		return player

	def _retry_missing(self) -> None:
		"""On its own thread: the hardware that was not there, looked for again until it is all open or the outputs close."""
		while not self._stop.wait(self.RETRY_SECONDS):
			with self._lock:
				missing = list(self._missing)
			if not missing:
				return
			for row in missing:
				player = self._make(row)
				if isinstance(player, str):
					logger.debug(f"The output '{row['name']}' is still not there: {player}")
					continue
				with self._lock:
					if self._stop.is_set():
						player.close()
						return
					self._missing = [r for r in self._missing if r is not row]
					self._players = { **self._players, row["name"]: player }
					self.problems = [p for p in self.problems if not p.startswith(f"The output {row['name']}: ")]
				player.start()
				logger.info(f"The output '{row['name']}' is open.")
				self._tell(f"The output {row['name']} is open.")

	def _tell(self, message: str) -> None:
		if self.on_tell is None:
			return
		try:
			self.on_tell(message)
		except Exception:
			logger.debug("An output's news could not be told", exc_info=True)

	def close(self) -> None:
		self._stop.set()
		retry, self._retry = self._retry, None
		if retry is not None and retry is not threading.current_thread():
			retry.join(timeout=2.0)
		with self._lock:
			players, self._players = self._players, {}
			self._missing = []
		for player in players.values():
			player.close()

	# ---- what the DeviceIO task tells them (any thread) ---------------------------------------------------------------------------------------------------

	def gesture(self, gesture: str) -> None:
		for player in self._players.values():
			player.gesture(gesture)

	def state(self, name: str, on: bool) -> None:
		with self._lock:
			if on:
				self._states.add(name)
			else:
				self._states.discard(name)
			players = list(self._players.values())
		for player in players:
			player.state(name, on)

	def test(self, output: str, cue: str, options: Mapping[str, Any]|None = None) -> bool:
		"""Play a cue on one output now (a Test). False: no such output is open."""
		player = self._players.get(output)
		if player is None:
			return False
		player.test(cue, options)
		return True
