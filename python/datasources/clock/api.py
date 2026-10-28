"""The clock's routes: the faces of its catalogue (`render/faces.json`), the choices of a task's Face field."""
from fastapi import APIRouter

from ...plugins.plugin_base import PermanentError
from ...web.deps import CM
from ...web.errors import ApiError
from ...web.openapi import Choice, answers
from .clock_face import face_choices, faces_of

# mounted under /api by the web application
clock_router = APIRouter(prefix="/datasource/clock")

@clock_router.get('/faces', **answers(list[Choice]))
def face_list(cm: CM):
	"""The clock faces, in the catalogue's order (the first is the default)."""
	try:
		return face_choices(faces_of(cm))
	except PermanentError:
		raise ApiError(500, "The clock's faces could not be read.") from None
