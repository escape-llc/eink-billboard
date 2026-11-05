"""
The outputs (#867, #891): what the device says back, at once, while the panel takes half a minute. The GPIO settings list each piece of hardware once (`outputs`: a name, a kind and the
kind's own settings) and what each says (`feedback`: rows of an event, an output by name and a cue); the quiet hours (`quietFrom`, `quietTo`) apply to every output alike.

Each output that is connected plays through a `Player` of its own (python/device/player.py), drawn by its kind's renderer: `gpio` (python/device/gpio_output.py), `haptic` (python/device/haptic.py) and `audio`.
An output whose hardware is not there (no chip on the bus, no sound card) is said, in our words (`problems`), and the others play: one missing part does not take the buttons or the other
outputs down with it. A GPIO output with no pin is not connected, and nothing is opened for it.
"""
from datetime import datetime
import logging
from typing import Any, Callable, Mapping

from .cues import CUES, EVENTS
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
	return [row for row in (rows if isinstance(rows, list) else []) if isinstance(row, dict) and isinstance(row.get("name"), str) and row.get("kind") in ("gpio", "haptic", "audio")]

def output_pin(row: Mapping[str, Any]) -> int|None:
	pin = row.get("pin")
	return pin if row.get("kind") == "gpio" and isinstance(pin, int) and not isinstance(pin, bool) else None

def connected(row: Mapping[str, Any]) -> bool:
	"""An output asks for hardware: a GPIO one with its pin set, any haptic or audio one."""
	return output_pin(row) is not None or row.get("kind") in ("haptic", "audio")

def cues_for(config: Mapping[str, Any], output: str) -> dict[str, str]:
	"""What an output plays for each event: the `feedback` rows that name it (the first row of an event wins)."""
	cues: dict[str, str] = {}
	rows = config.get("feedback")
	for row in rows if isinstance(rows, list) else []:
		if isinstance(row, dict) and row.get("output") == output and row.get("event") in EVENTS and row.get("cue") in CUES:
			cues.setdefault(row["event"], row["cue"])
	return cues

def make_gpio(row: Mapping[str, Any]) -> Renderer:
	pin = output_pin(row)
	assert pin is not None
	return GpioRenderer(pin, row.get("speed"))

def make_haptic(row: Mapping[str, Any]) -> Renderer:
	return HapticRenderer()

def make_audio(row: Mapping[str, Any]) -> Renderer:
	raise PermanentError("An audio output is not built yet.")

class Outputs:
	"""
	`makers` makes each kind's renderer from its row (a test gives fakes); by default the hardware's. `clock` says the time for the quiet hours; `on_play` is told each cue that starts
	(the output's name, the cue's title, why), from the output's own thread.
	"""
	id = "outputs"

	def __init__(self, makers: Mapping[str, Callable[[Mapping[str, Any]], Renderer]]|None = None):
		self._makers = dict(makers) if makers is not None else { "gpio": make_gpio, "haptic": make_haptic, "audio": make_audio }
		self.clock: Callable[[], datetime] = lambda: datetime.now().astimezone()
		self.on_play: Callable[[str, str, str], None]|None = None
		self._players: dict[str, Player] = {}
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
		for row in output_rows(config):
			name = row["name"]
			if not connected(row) or name in players:
				continue
			try:
				renderer = self._makers[row["kind"]](row)
			except PermanentError as e:
				self.problems.append(f"The output {name}: {e}")
				logger.warning(f"The output '{name}' could not be opened: {e}")
				continue
			def told(title: str, why: str, name: str = name) -> None:
				if self.on_play is not None:
					self.on_play(name, title, why)
			players[name] = Player(name, renderer, cues_for(config, name), config, self.clock, told)
		for player in players.values():
			player.start()
		self._players = players
		if players:
			logger.info(f"The outputs {', '.join(players)} are open.")

	def close(self) -> None:
		players, self._players = self._players, {}
		for player in players.values():
			player.close()

	# ---- what the DeviceIO task tells them (any thread) ---------------------------------------------------------------------------------------------------

	def gesture(self, gesture: str) -> None:
		for player in self._players.values():
			player.gesture(gesture)

	def state(self, name: str, on: bool) -> None:
		for player in self._players.values():
			player.state(name, on)

	def test(self, output: str, cue: str, options: Mapping[str, Any]|None = None) -> bool:
		"""Play a cue on one output now (a Test). False: no such output is open."""
		player = self._players.get(output)
		if player is None:
			return False
		player.test(cue, options)
		return True
