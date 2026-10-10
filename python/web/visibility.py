"""
Conditional visibility of schema properties: the same rules as `app/src/components/FormVisibility.ts`
(the cases both must pass are in `python/tests/form_visibility.json`).

A property may carry `visibleIf`, a small JSON predicate over the other properties' values:
	{ "field": "randomizeDate", "eq": false }       eq | ne | in | set (true: has a value, false: has none)
	{ "all": [ ... ] }   { "any": [ ... ] }   { "not": { ... } }
An unset value (missing, null, "") reads as null. A hidden property is not applicable: it is not validated and is stored as null.
"""
from typing import Any, Iterable

_OPERATORS = ("eq", "ne", "in", "set")

def _read(values: dict, name: str) -> Any:
	v = values.get(name)
	return None if v == "" else v

def _same(a: Any, b: Any) -> bool:
	"""Equal values of the same kind: `1` equals `1.0` (JSON has one number type), but `True` is not `1`."""
	if isinstance(a, bool) or isinstance(b, bool):
		return type(a) is type(b) and a == b
	if isinstance(a, (int, float)) and isinstance(b, (int, float)):
		return a == b
	return type(a) is type(b) and a == b

def evaluate(p: Any, values: dict) -> bool:
	"""True when the predicate holds. One this code does not understand holds (the property stays visible); `find_problems` reports it."""
	if not isinstance(p, dict):
		return True
	if isinstance(p.get("all"), list):
		return all(evaluate(x, values) for x in p["all"])
	if isinstance(p.get("any"), list):
		return any(evaluate(x, values) for x in p["any"])
	if "not" in p:
		return not evaluate(p["not"], values)
	if isinstance(p.get("field"), str):
		v = _read(values, p["field"])
		if "eq" in p:
			return _same(v, p["eq"])
		if "ne" in p:
			return not _same(v, p["ne"])
		if isinstance(p.get("in"), list):
			return any(_same(v, x) for x in p["in"])
		if isinstance(p.get("set"), bool):
			return (v is not None) == p["set"]
	return True

def hidden_names(properties: Iterable[dict], values: dict) -> set[str]:
	"""Names of the properties that are hidden for these values."""
	hidden: set[str] = set()
	for prop in properties or []:
		name = prop.get("name") if isinstance(prop, dict) else None
		if name and prop.get("type") != "header" and not evaluate(prop.get("visibleIf"), values):
			hidden.add(name)
	return hidden

def null_hidden(document: dict, properties: Iterable[dict]) -> dict:
	"""A copy of the document with every hidden property set to null."""
	hidden = hidden_names(properties, document)
	return { k: (None if k in hidden else v) for k, v in document.items() } | { n: None for n in hidden }

def _referenced(p: Any) -> list[str]:
	if not isinstance(p, dict):
		return []
	for key in ("all", "any"):
		if isinstance(p.get(key), list):
			return [r for x in p[key] for r in _referenced(x)]
	if "not" in p:
		return _referenced(p["not"])
	return [p["field"]] if isinstance(p.get("field"), str) else []

def _shape_problem(p: Any) -> str|None:
	if not isinstance(p, dict):
		return "is not an object"
	for key in ("all", "any"):
		if isinstance(p.get(key), list):
			return next((m for m in (_shape_problem(x) for x in p[key]) if m), None)
	if "not" in p:
		return _shape_problem(p["not"])
	if not isinstance(p.get("field"), str):
		return "needs a field, all, any or not"
	return None if any(op in p for op in _OPERATORS) else "needs eq, ne, in or set"

def find_problems(properties: Iterable[dict]) -> list[str]:
	"""What is wrong with the `visibleIf` of these properties: a malformed predicate, a name that is no property, or a cycle."""
	props = [p for p in properties or [] if isinstance(p, dict)]
	names = { p["name"] for p in props if p.get("type") != "header" and "name" in p }
	problems: list[str] = []
	edges: dict[str, list[str]] = {}
	for p in props:
		if "visibleIf" not in p:
			continue
		shape = _shape_problem(p["visibleIf"])
		if shape:
			problems.append(f"{p.get('name')}: visibleIf {shape}")
		refs = _referenced(p["visibleIf"])
		problems.extend(f"{p.get('name')}: visibleIf refers to unknown field '{r}'" for r in refs if r not in names)
		edges[p["name"]] = [r for r in refs if r in names]
	state: dict[str, int] = {}
	def visit(n: str, path: list[str]) -> None:
		if state.get(n) == 2:
			return
		if state.get(n) == 1:
			problems.append("visibleIf cycle: " + " -> ".join(path[path.index(n):] + [n]))
			return
		state[n] = 1
		for m in edges.get(n, []):
			visit(m, path + [n])
		state[n] = 2
	for n in list(edges):
		visit(n, [])
	return problems
