"""
Press a button for the app, from software, on a Raspberry Pi. The app holds the button's pin as an input, and nothing else can drive that same pin, so this needs a jumper wire from a second, free
GPIO pin (the "driver" pin) to the button's pin. Pulling the driver pin low pulls the button's pin low through the wire: the app sees an ordinary press (its pull-up holds the pin high until then).
The driver pin is only ever driven low and is then let go (an input again), never driven high, so it cannot fight the app's pull-up or a real button wired to the same pin.

	# wire GPIO 12 to GPIO 5 (the app's Next button), then:
	uv run python -m scripts.gpio_press --pin 12                  # a press: low for 0.1 s
	uv run python -m scripts.gpio_press --pin 12 --hold 1.5       # a long press (the app counts one second)
	uv run python -m scripts.gpio_press --pin 12 --count 3        # three presses, 0.5 s apart
"""
import argparse
import time

from python.device.pins import FIRST_PIN, LAST_PIN, Panel, check_pins
from python.plugins.plugin_base import PermanentError

def main() -> int:
	parser = argparse.ArgumentParser(description="Pull a GPIO pin low for a moment, to press a button whose pin is wired to it.")
	parser.add_argument("--pin", type=int, required=True, help="BCM number of the driver pin, wired to the button's pin")
	parser.add_argument("--hold", type=float, default=0.1, help="seconds to hold it low (default 0.1; over 1 is a long press)")
	parser.add_argument("--count", type=int, default=1, help="how many presses")
	parser.add_argument("--gap", type=float, default=0.5, help="seconds between presses")
	parser.add_argument("--panel", choices=["inky", "waveshare"], help="the panel's display type, to refuse its pins")
	args = parser.parse_args()

	problems = check_pins({ "driver": args.pin }, Panel(args.panel, 0, 0) if args.panel else None)
	if problems:
		for problem in problems:
			print(problem)
		return 2
	if not FIRST_PIN <= args.pin <= LAST_PIN:
		return 2

	try:
		from gpiozero import OutputDevice
	except ImportError:
		print(PermanentError("This needs the device libraries (`uv sync --group device`, Raspberry Pi only).").args[0])
		return 1

	for n in range(args.count):
		if n:
			time.sleep(args.gap)
		# active_high False: "on" is low. Closing the device lets the pin go (an input again), so it is never driven high.
		driver = OutputDevice(args.pin, active_high=False, initial_value=False)
		try:
			driver.on()
			time.sleep(args.hold)
		finally:
			driver.close()
		print(f"pressed {n + 1} of {args.count}", flush=True)
	return 0

if __name__ == "__main__":
	raise SystemExit(main())
