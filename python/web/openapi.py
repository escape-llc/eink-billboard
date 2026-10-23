"""
What the OpenAPI document says of a route (#590). The web app's types are generated from that document (scripts/export_openapi.py), so a route that
declares its answer and its body is typed in the app.

- A route's **answer** is a `response_model`: FastAPI then checks it and drops any field the model does not name, so a model is for an answer whose fields
  are ours and fixed. A settings document, a schedule or a descriptor has keys only its descriptor knows: never a closed model there.
- A route's **body** is described with `json_body(Model)`, while the route goes on reading it itself: its checks keep their own words and paths (`password`,
  not `["body", "password"]`), which a body parameter of the model's type would replace with pydantic's.
"""
from typing import Any

from pydantic import BaseModel

def json_body(model: type[BaseModel]) -> dict[str, Any]:
	"""`openapi_extra` for a route that reads its JSON body itself: the document describes the body by the model, and nothing checks it but the route."""
	return { "requestBody": { "required": True, "content": { "application/json": { "schema": model.model_json_schema() } } } }

class Done(BaseModel):
	"""The answer of a change that worked and has nothing else to say."""
	success: bool
