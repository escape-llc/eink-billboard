"""
What the OpenAPI document says of a route (#590). The web app's types are generated from that document (scripts/export_openapi.py), so a route that
declares its answer and its body is typed in the app.

- A route's **answer** is an `Answer` model, given with `**answers(Model)`: FastAPI drops any field a response model does not name, so a model is for an
  answer whose fields are ours and fixed. A settings document, a schedule or a descriptor has keys only its descriptor knows: never a closed model there.
  An `Answer` refuses a field it does not name (a 500 in the route's own tests) rather than drop it, and a field the route left out stays out (not `null`).
  An answer that carries what a person may have written by hand (a schedule file) is `described(Model)` instead: in the document, never checked at run time.
- A route's **body** is described with `json_body(Model)`, while the route goes on reading it itself: its checks keep their own words and paths (`password`,
  not `["body", "password"]`), which a body parameter of the model's type would replace with pydantic's.
"""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

def json_body(model: type[BaseModel], required: bool = True) -> dict[str, Any]:
	"""`openapi_extra` for a route that reads its JSON body itself: the document describes the body by the model, and nothing checks it but the route."""
	return { "requestBody": { "required": required, "content": { "application/json": { "schema": model.model_json_schema() } } } }

class Answer(BaseModel):
	"""A route's answer: every field named, and no other (a field the code adds and the model lacks fails the route, never vanishes)."""
	model_config = ConfigDict(extra="forbid")

def answers(model: Any) -> dict[str, Any]:
	"""A route's `response_model` (an `Answer`, or a list of them), keeping out what the route left out: an optional reading a machine cannot give is absent, not `null`."""
	return { "response_model": model, "response_model_exclude_unset": True }

def described(model: Any, status: int = 200) -> dict[str, Any]:
	"""
	The answer's model in the document only: nothing is checked or dropped. For an answer that carries what a person may have written into a file by hand (a schedule):
	one odd value must not fail the whole answer. Tests validate the real answers against the model, so the document cannot drift from the code unseen.
	"""
	return { "responses": { status: { "model": model } } }

class Choice(Answer):
	"""One entry of a drop-down: what it shows and what it stores."""
	name: str
	value: str

class Document(BaseModel):
	"""A settings document: its `_id` and `_rev`, and keys only its schema or descriptor knows. Open: every key is passed on, none is checked here."""
	model_config = ConfigDict(extra="allow")
	id_: str = Field(alias="_id")
	rev: str = Field(alias="_rev")

class Descriptor(BaseModel):
	"""An installed plugin, data source or display's descriptor (its `*-info.json`): open, its keys are the descriptor's (the web app reads them as `FormDefs.ts`'s `Descriptor`)."""
	model_config = ConfigDict(extra="allow")
	id: str
	name: str

class Saved(Answer):
	"""A document that was stored: its id and its new revision."""
	success: bool
	message: str
	id: str
	rev: str

class TestBody(BaseModel):
	"""A Test button's question: the field's value as typed (a write-only field's mask, or nothing, means the saved one)."""
	value: Any = None

class TestAnswer(Answer):
	"""A Test button's answer, always 200 and in our words: whether it worked, and what to show beside the field."""
	ok: bool
	message: str

def test_route() -> dict[str, Any]:
	"""What a Test route of a descriptor's `test.url` declares: its body and its answer."""
	return { **answers(TestAnswer), "openapi_extra": json_body(TestBody) }

class RowActionBody(BaseModel):
	"""A row action's step: `key` names the saved row (start); `session` the run, and `value` what the person typed (continue, poll)."""
	key: str | None = None
	session: str | None = None
	value: Any = None

class RowStep(Answer):
	"""
	A row action's answer, always 200: what to show next (`message`, a `link` to open, a `code` to enter, an `input` to fill, or a wait of `poll` seconds) and the run's `session`,
	until it is `done` with `ok` and its last `message`. Each field only when the step has it.
	"""
	done: bool | None = None
	ok: bool | None = None
	message: str | None = None
	session: str | None = None
	link: str | None = None
	code: str | None = None
	input: str | None = None
	poll: int | None = None
	# a connected account's calendars, named so a row's calendar can be filled in
	calendars: list[dict[str, Any]] | None = None

def row_step_route() -> dict[str, Any]:
	"""What a step of a row action (`items.action.url`) declares: its body and its answer."""
	return { **answers(RowStep), "openapi_extra": json_body(RowActionBody) }

class Done(Answer):
	"""The answer of a change that worked and has nothing else to say."""
	success: bool
