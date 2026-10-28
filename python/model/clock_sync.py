"""
Whether the system clock has been set (#785). A Pi has no clock of its own that runs while it is off: until the network sets it, it reads the time it last saved,
which can be hours or days old, and every page that shows the time (and every timer that counts from it) is wrong.

Raspberry Pi OS sets the clock with `systemd-timesyncd`, which creates `/run/systemd/timesync/synchronized` once it has synced. The kit mounts that folder
read-only into the container (`deploy/eink-container.sh start`), so a sync after the start is seen too.

- `synced`: the file is there.
- `unsynced`: the folder is there and the file is not (yet).
- `unknown`: there is no such folder (another time service such as chrony, a development machine, Windows): nothing says the clock is wrong.
"""
import os
from typing import Literal

TIMESYNC_FOLDER = "/run/systemd/timesync"
SYNCED_FLAG = "synchronized"

ClockState = Literal["synced", "unsynced", "unknown"]

class ClockSync:
	"""The state of the system clock, read each time it is asked (a stat of one file). `folder` is timesyncd's, or a test's."""
	def __init__(self, folder: str = TIMESYNC_FOLDER):
		self.folder = folder
	def state(self) -> ClockState:
		if not os.path.isdir(self.folder):
			return "unknown"
		return "synced" if os.path.exists(os.path.join(self.folder, SYNCED_FLAG)) else "unsynced"
