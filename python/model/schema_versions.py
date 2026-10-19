"""
The version of a stored document (#391). A document that has a **source** (a device schema file, a plugin's or data source's descriptor, a schedule kind) carries the source's `_schema`, a URN whose
last number is the version: `urn:inky:storage:schema:system:2`. A document that has no source (a kept list, the panel's refresh state, the Calendar's sign-ins) carries an integer `_version`, which
the code that writes it owns. A document with neither is the first version: every shape that existed before versions did is version 1.

This module only reads and writes those marks; what a newer version means for a document is `migrations.py`'s.
"""
import re
from typing import Any

from pydantic import BaseModel, ConfigDict

SCHEMA_KEY = "_schema"
VERSION_KEY = "_version"
FIRST_VERSION = 1

_URN = re.compile(r"^(?P<family>urn:inky:storage:[a-z]+(?::[A-Za-z0-9_-]+)+):(?P<version>[1-9][0-9]{0,5})$")

class SchemaId(BaseModel):
	"""A `_schema` value taken apart: the `family` (everything before the number: it names the kind of document) and its `version`."""
	model_config = ConfigDict(frozen=True)
	family: str
	version: int

	@classmethod
	def parse(cls, urn: Any) -> "SchemaId|None":
		"""The parts of a URN, or None when it is not one of ours (not text, no number, a number that is not positive)."""
		match = _URN.match(urn) if isinstance(urn, str) else None
		return cls(family=match["family"], version=int(match["version"])) if match else None

	def __str__(self) -> str:
		return f"{self.family}:{self.version}"

	def with_version(self, version: int) -> "SchemaId":
		return SchemaId(family=self.family, version=version)

def schema_id_of(document: Any) -> SchemaId|None:
	"""The `_schema` a document carries, or None when it carries none (or one that is not ours)."""
	return SchemaId.parse(document.get(SCHEMA_KEY)) if isinstance(document, dict) else None

def file_version(document: Any) -> int:
	"""The integer `_version` of a document that has no source schema: absent (or anything but a positive whole number) is the first version."""
	value = document.get(VERSION_KEY) if isinstance(document, dict) else None
	return value if isinstance(value, int) and not isinstance(value, bool) and value >= FIRST_VERSION else FIRST_VERSION

def stamped(document: dict, version: int) -> dict:
	"""The document with its `_version` first (a document that has no source schema), whatever it carried before."""
	return { VERSION_KEY: version, **{ k: v for k, v in document.items() if k != VERSION_KEY } }
