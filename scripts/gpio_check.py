"""
Try the buttons on a Raspberry Pi without the app: opens the same `Buttons` device the DeviceIO task does, on the pins given, and prints every press and long press until Ctrl+C.
Stop the app first (or have no buttons in its GPIO settings): two programs cannot hold one pin.

	uv run python -m scripts.gpio_check --pin 5 6 13
	uv run python -m scripts.gpio_check --pin 5 --panel inky          # also refuse the panel's pins
	podman exec -it eink-billboard python -m scripts.gpio_check --pin 5   # inside the container, where the devices are passed in

Wire each button between its GPIO number (BCM, not the header position) and ground.
"""
import argparse
import logging
import time

from python.device.buttons import Buttons
from python.device.pins import Panel, check_pins
from python.plugins.plugin_base import PermanentError

def main() -> int:
	parser = argparse.ArgumentParser(description="Print the presses of buttons wired to GPIO pins.")
	parser.add_argument("--pin", type=int, nargs="+", metavar="PIN", default=[], help="the BCM pins of the buttons")
	parser.add_argument("--panel", choices=["inky", "waveshare"], help="the panel's display type, to refuse its pins")
	args = parser.parse_args()
	logging.basicConfig(level=logging.INFO, format="%(message)s")

	config = { "triggers": [{ "pin": pin } for pin in args.pin] }
	buttons = Buttons()
	pins = buttons.pins(config)
	if not pins:
		parser.error("give at least one pin, e.g. --pin 5")
	problems = check_pins(pins, Panel(args.panel, 0, 0) if args.panel else None)
	if problems:
		for problem in problems:
			print(problem)
		return 2

	started = time.monotonic()
	def emit(name: str, gesture: str) -> None:
		print(f"{time.monotonic() - started:8.2f}s  {name}  {gesture}", flush=True)

	try:
		buttons.open(emit, config)
	except PermanentError as e:
		print(e)
		return 1
	print("Listening. Press a button (Ctrl+C to stop).")
	try:
		while True:
			time.sleep(1)
	except KeyboardInterrupt:
		pass
	finally:
		buttons.close()
	return 0

if __name__ == "__main__":
	raise SystemExit(main())
