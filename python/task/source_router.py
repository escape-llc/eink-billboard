"""
Who made the image: a router a track or a timer task gets in place of the real one, which marks every image the plugin sends to the display
with where it came from (`origin`: the kind, the playlist or task, the plugin). The display carries the mark to the telemetry, so the web app can say
which track or task produced what is on the panel.
"""
from dataclasses import replace
from typing import Any, Mapping

from .message_router import MessageRouter, Route
from .messages import BasicMessage

type ImageSource = Mapping[str, str]

class SourceRouter(MessageRouter):
	def __init__(self, inner: MessageRouter, source: ImageSource):
		super().__init__()
		self._inner = inner
		self._origin = dict(source)

	def addRoute(self, route: Route):
		self._inner.addRoute(route)

	def send(self, route: str, msg: BasicMessage):
		# only an image that has no mark yet (a plugin that already says where it is from keeps its own)
		if route == "display" and getattr(msg, "origin", False) is None:
			msg = replace(msg, origin=self._origin)  # type: ignore[call-arg]
		self._inner.send(route, msg)

def image_source(kind: str, title: str, plugin: Any, name: str|None = None) -> dict[str, str]:
	"""The mark of a track (`kind` playlist, `name` the playlist's) or a timer task, in words that are safe to show."""
	source = { "kind": kind, "title": str(title), "plugin": str(plugin) }
	if name:
		source["name"] = str(name)
	return source
