"""
Migrations of stored documents (#391). A document carries the `_schema` of its source (`schema_versions.py`); when the source's number is raised, a **migration** says what a document of
the older number becomes. A step is a pure function, `dict -> dict`, from version `n` to `n + 1`, written by a person who knows what the change meant: it is hard-coded on purpose (a rename,
a split, a new unit). Everything around it is generic: the numbers, running the steps in order, filling the keys a newer source added, stamping, and refusing a document that is newer than the code.

Adding a step (the rule in docs/tasks-and-storage.md): raise the source's number (in its schema file, descriptor or constant), register the step here with `@migration`, record the new shape in
`python/tests/fixtures/schema_shapes.json`, and add a fixture of the old shape; `test_schema_versions` fails until all four agree. A new key with a default needs none of it (it is filled in).
"""
import copy
import logging
from typing import Any, Callable, Mapping

from pydantic import BaseModel, ConfigDict

from .schema_versions import FIRST_VERSION, SCHEMA_KEY, SchemaId, file_version, schema_id_of, stamped

logger = logging.getLogger(__name__)

type Step = Callable[[dict], dict]

class Migration(BaseModel):
	"""One registered step: the family it belongs to and the version it starts from (it makes `source + 1`)."""
	model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
	family: str
	source: int
	step: Step

# family -> { starting version: step }; filled by `@migration` when the module that owns the change is imported (this one, for settings)
MIGRATIONS: dict[str, dict[int, Step]] = {}

def migration(family: str, source: int) -> Callable[[Step], Step]:
	"""Register `step` as the migration of `family` from version `source` to `source + 1`."""
	def register(step: Step) -> Step:
		steps = MIGRATIONS.setdefault(family, {})
		if source in steps:
			raise ValueError(f"A migration of {family} from version {source} is already registered.")
		steps[source] = step
		return step
	return register

class TooNew(Exception):
	"""A document written by newer code than this: it is not changed and not trusted. `found` is its number, `known` the newest this code knows. (The message is ours: no value from the document.)"""
	def __init__(self, family: str, found: int, known: int):
		super().__init__(f"A document of a newer version ({found}; this version knows {known}).")
		self.family, self.found, self.known = family, found, known

class MigrationGap(Exception):
	"""There is no step from `version` to the next: a source's number was raised without its migration."""
	def __init__(self, family: str, version: int):
		super().__init__(f"No migration of {family} from version {version}.")
		self.family, self.version = family, version

def _fill(document: dict, defaults: Mapping[str, Any]|None) -> dict:
	"""The keys a newer source added, from its defaults: only keys that are missing (a value the person set is never changed; `null` is a default too, so the field is there to fill)."""
	if not isinstance(defaults, Mapping):
		return document
	missing = { k: copy.deepcopy(v) for k, v in defaults.items() if k not in document and not k.startswith("_") }
	return { **document, **missing } if missing else document

def migrate(current: str, document: dict, defaults: Mapping[str, Any]|None = None, steps: Mapping[str, Mapping[int, Step]]|None = None) -> tuple[dict, list[str]]:
	"""
	Bring `document` to the source's version: `(document, the steps taken)`. `current` is the source's own `_schema`; the document's is its own (none: the first version). The steps run in
	order; a missing one is a `MigrationGap`; a document above `current` is `TooNew` (left to the caller: it is neither changed nor trusted); a `_schema` of another family is a `ValueError`.
	After the steps the keys the source's `defaults` add are filled in, and the document is stamped with `current`. The input is not changed.
	"""
	target = SchemaId.parse(current)
	if target is None:
		raise ValueError("The source has no usable _schema.")
	found = schema_id_of(document)
	if document.get(SCHEMA_KEY) is not None and found is None:
		raise ValueError("The document's _schema is not one of ours.")
	if found is not None and found.family != target.family:
		raise ValueError("The document's _schema is another kind of document's.")
	version = found.version if found is not None else FIRST_VERSION
	if version > target.version:
		raise TooNew(target.family, version, target.version)
	registry = MIGRATIONS if steps is None else steps
	taken: list[str] = []
	result = copy.deepcopy(document)
	while version < target.version:
		step = registry.get(target.family, {}).get(version)
		if step is None:
			raise MigrationGap(target.family, version)
		result = step(result)
		taken.append(f"{version} to {version + 1}")
		version += 1
	result = _fill(result, defaults)
	return { SCHEMA_KEY: str(target), **{ k: v for k, v in result.items() if k != SCHEMA_KEY } }, taken

def migrate_file(document: Any, current: int, steps: Mapping[int, Step]|None = None) -> tuple[dict|None, str]:
	"""
	The same for a document that has no source schema, by its integer `_version` (a kept list, the refresh state): `(document, what happened)`. What happened is `current` (nothing to do),
	`upgraded`, `newer` (written by newer code: the document is None, to be treated as not there, and the file left as it is) or `unusable` (a step failed or is missing: None as well).
	"""
	if not isinstance(document, dict):
		return None, "unusable"
	version = file_version(document)
	if version > current:
		return None, "newer"
	result = copy.deepcopy(document)
	table = steps or {}
	while version < current:
		step = table.get(version)
		if step is None:
			return None, "unusable"
		try:
			result = step(result)
		except Exception:
			logger.warning("A stored file could not be upgraded.", exc_info=True)
			return None, "unusable"
		version += 1
	return stamped(result, current), ("current" if file_version(document) == current and document.get("_version") == current else "upgraded")
