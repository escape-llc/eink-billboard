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

class Done(Answer):
	"""The answer of a change that worked and has nothing else to say."""
	success: bool
