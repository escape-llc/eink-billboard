"""Running a task now (#653, #671): a stored timer task by Run now, and the task a button carries (the GPIO settings' Trigger Task)."""
import unittest
from types import SimpleNamespace
from typing import Any

from ..task.application import Application
from ..task.messages import RunTask, RunTrigger
from .test_schedule_api import BASE, ScheduleApiBase
from .test_timer_validation import GOOD, NOW, TimerValidationCase, entry, task
from .test_web_api import WebApiTestBase, _error_shape

class FakePool:
	def __init__(self) -> None:
		self.submitted: list[Any] = []
	def submit(self, fn, *args, **kwargs):
		self.submitted.append((fn, args, kwargs))

class TestInTheLayer(TimerValidationCase):
	def setUp(self):
		super().setUp()
		self.pool = FakePool()
		self.layer.task_pool = self.pool  # type: ignore[assignment]
		self.layer._create_container = lambda: object()  # type: ignore

	def test_a_good_task_is_run_on_its_own_job(self):
		self.layer.tasks = [entry(task("a"))]
		self.layer._run_task(RunTask(NOW, "a"))
		self.assertEqual(len(self.pool.submitted), 1)

	def test_an_unknown_or_disabled_task_is_not_run(self):
		self.layer.tasks = [entry(task("a", enabled=False))]
		self.layer._run_task(RunTask(NOW, "a"))
		self.layer._run_task(RunTask(NOW, "zzz"))
		self.assertEqual(self.pool.submitted, [])

	def test_a_buttons_task_is_run_without_being_in_a_schedule(self):
		self.layer._run_trigger(RunTrigger(NOW, "Button on pin 16", "priority-update", GOOD))
		self.assertEqual(len(self.pool.submitted), 1)

	def test_nothing_runs_before_the_layer_is_configured(self):
		self.layer.state = "uninitialized"
		self.layer._run_trigger(RunTrigger(NOW, "Button on pin 16", "priority-update", GOOD))
		self.assertEqual(self.pool.submitted, [])

class TestRunNowApi(ScheduleApiBase):
	def setUp(self):
		super().setUp()
		self.asked: list[str] = []
		self.ready = True
		self.application = SimpleNamespace(playlist_layer=object(), run_task=lambda task_id: self.asked.append(task_id) or self.ready)
		self.app.state.root_container.add_service(Application, self.application)

	def test_a_stored_task_is_run_by_id(self):
		resp = self.client.post(f"{BASE}/doc-a/items/a1/run")
		self.assertEqual((resp.status_code, resp.json()), (202, { "success": True }), resp.text)
		self.assertEqual(self.asked, ["a1"])

	def test_a_disabled_task_is_refused(self):
		self.client.patch(f"{BASE}/doc-a/items/a2", json={ "enabled": False, "_rev": self.rev_of_item("a2") })
		_error_shape(self, self.client.post(f"{BASE}/doc-a/items/a2/run"), 409)
		self.assertEqual(self.asked, [])

	def test_an_unknown_task_is_a_404(self):
		_error_shape(self, self.client.post(f"{BASE}/doc-a/items/zzz/run"), 404)

	def test_a_device_that_is_not_ready_is_a_503(self):
		self.ready = False
		_error_shape(self, self.client.post(f"{BASE}/doc-a/items/a1/run"), 503)

class TestButtonTasks(WebApiTestBase):
	"""The GPIO settings' rows that run a task: the task follows Priority Update's own rules, and only a task's row keeps them."""
	def put(self, rows: list[dict[str, Any]]):
		doc = self.client.get("/api/settings/devices").json()
		return self.client.put("/api/settings/devices", json={ **doc, "triggers": rows })

	def test_a_task_row_with_good_settings_is_saved(self):
		resp = self.put([{ "pin": 16, "action": "task", "content": GOOD }])
		self.assertEqual(resp.status_code, 200, resp.text)
		self.assertEqual(self.client.get("/api/settings/devices").json()["triggers"][0]["content"]["dataSource"], "clock")

	def test_a_task_row_needs_its_settings(self):
		errors = _error_shape(self, self.put([{ "pin": 16, "action": "task" }]), 422)["errors"]
		self.assertEqual(errors, [{ "path": ["triggers", "0", "content"], "message": "Required" }])

	def test_the_settings_follow_the_plugins_rules_at_their_own_path(self):
		errors = _error_shape(self, self.put([{ "pin": 16, "action": "task", "content": { **GOOD, "slideMinutes": 0 } }]), 422)["errors"]
		self.assertEqual([e["path"] for e in errors], [["triggers", "0", "content", "slideMinutes"]])

	def test_a_data_source_the_plugin_cannot_use_is_refused(self):
		errors = _error_shape(self, self.put([{ "pin": 16, "action": "task", "content": { **GOOD, "dataSource": "rss" } }]), 422)["errors"]
		self.assertEqual([e["path"] for e in errors], [["triggers", "0", "content", "dataSource"]])

	def test_a_row_that_is_not_a_task_keeps_no_settings(self):
		resp = self.put([{ "pin": 5, "action": "next", "content": GOOD }])
		self.assertEqual(resp.status_code, 200, resp.text)
		self.assertEqual(self.client.get("/api/settings/devices").json()["triggers"], [{ "pin": 5, "action": "next", "playlist": None }])

	def test_a_task_can_be_on_more_than_one_button(self):
		resp = self.put([{ "pin": 16, "action": "task", "content": GOOD }, { "pin": 24, "action": "task", "content": GOOD }])
		self.assertEqual(resp.status_code, 200, resp.text)

class TestRunButtonApi(WebApiTestBase):
	def setUp(self):
		super().setUp()
		self.reason = "ok"
		self.asked: list[int] = []
		self.application = SimpleNamespace(playlist_layer=object(), run_trigger=lambda pin: self.asked.append(pin) or self.reason)
		self.app.state.root_container.add_service(Application, self.application)

	def test_the_button_is_asked_to_run(self):
		resp = self.client.post("/api/devices/triggers/16/run")
		self.assertEqual((resp.status_code, resp.json()), (202, { "success": True }), resp.text)
		self.assertEqual(self.asked, [16])

	def test_a_reason_it_cannot_is_a_409_in_our_words(self):
		self.reason = "That button does not run a task: save it as a task first."
		body = _error_shape(self, self.client.post("/api/devices/triggers/5/run"), 409)
		self.assertEqual(body["message"], self.reason)

	def test_a_pin_that_is_not_a_number_is_a_422(self):
		self.assertEqual(self.client.post("/api/devices/triggers/x/run").status_code, 422)

if __name__ == '__main__':
	unittest.main()
