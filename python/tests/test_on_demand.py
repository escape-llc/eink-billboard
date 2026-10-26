"""A task with no time of its own (#653): it is valid only for Priority Update, never planned, and runs when asked."""
import unittest
from types import SimpleNamespace

from ..model.schedule import is_on_demand, validate_trigger
from ..model.schedule_store import check_item_shape
from ..task.application import Application
from ..task.messages import RunTask
from .test_schedule_api import BASE, ScheduleApiBase
from .test_timer_validation import GOOD, NOW, TimerValidationCase, entry, task
from .test_web_api import _error_shape

ON_DEMAND = { "on_demand": True }

class TestOnDemandTrigger(unittest.TestCase):
	def test_only_true_is_on_demand(self):
		self.assertTrue(is_on_demand(ON_DEMAND))
		self.assertFalse(is_on_demand({ "on_demand": False }))
		self.assertFalse(is_on_demand(None))

	def test_valid_for_priority_update_only(self):
		self.assertEqual(validate_trigger(ON_DEMAND, "priority-update"), [])
		self.assertEqual(validate_trigger(ON_DEMAND), [])
		self.assertEqual(validate_trigger(ON_DEMAND, "slide-show"), ["only Priority Update can run on demand"])

	def test_it_has_no_time_or_startup(self):
		self.assertEqual(validate_trigger({ **ON_DEMAND, "day": {} }, "priority-update"), ["an on-demand trigger has no day, time or startup"])
		self.assertEqual(validate_trigger({ **ON_DEMAND, "on_startup": True }, "priority-update"), ["an on-demand trigger has no day, time or startup"])

	def test_the_write_routes_check_the_plugin(self):
		item = { "title": "T", "enabled": True, "trigger": ON_DEMAND, "task": { "plugin_name": "slide-show", "content": {} } }
		self.assertEqual([e["message"] for e in check_item_shape(item) if e["path"] == ["trigger"]], ["only Priority Update can run on demand"])
		item["task"]["plugin_name"] = "priority-update"
		self.assertEqual(check_item_shape(item), [])

class TestOnDemandInTheLayer(TimerValidationCase):
	def test_it_is_never_planned(self):
		items = [task("a", trigger=ON_DEMAND), task("b")]
		planned = self.layer._next_scheduled_playlist(NOW.replace(hour=0), items)
		self.assertTrue(all(item.id == "b" for _, item in planned))

	def test_it_passes_the_check(self):
		self.assertEqual(self.layer._check_tasks([entry(task("a", trigger=ON_DEMAND))]), {})

	def test_a_good_task_is_run_on_its_own_job(self):
		submitted = []
		self.layer.task_pool = type("Pool", (), { "submit": lambda _s, fn, *a, **k: submitted.append((fn, a, k)) })()  # type: ignore
		self.layer.tasks = [entry(task("a", trigger=ON_DEMAND))]
		self.layer._create_container = lambda: object()  # type: ignore
		self.layer._run_task(RunTask(NOW, "a"))
		self.assertEqual(len(submitted), 1)

	def test_an_unknown_or_disabled_task_is_not_run(self):
		submitted = []
		self.layer.task_pool = type("Pool", (), { "submit": lambda _s, fn, *a, **k: submitted.append(fn) })()  # type: ignore
		self.layer.tasks = [entry(task("a", trigger=ON_DEMAND, enabled=False))]
		self.layer._run_task(RunTask(NOW, "a"))
		self.layer._run_task(RunTask(NOW, "zzz"))
		self.assertEqual(submitted, [])

class TestRunNowApi(ScheduleApiBase):
	def setUp(self):
		super().setUp()
		self.asked: list[str] = []
		self.ready = True
		self.application = SimpleNamespace(playlist_layer=object(), run_task=lambda task_id: self.asked.append(task_id) or self.ready)
		self.app.state.root_container.add_service(Application, self.application)

	def add(self, **over) -> str:
		body = { "title": "Alert", "enabled": True, "trigger": ON_DEMAND, "task": { "plugin_name": "priority-update", "content": GOOD }, **over }
		resp = self.client.post(f"{BASE}/doc-a/items", json=body)
		self.assertEqual(resp.status_code, 201, resp.text)
		return resp.json()["task"]["id"]

	def test_an_on_demand_task_is_saved_and_run_by_id(self):
		ident = self.add()
		resp = self.client.post(f"{BASE}/doc-a/items/{ident}/run")
		self.assertEqual((resp.status_code, resp.json()), (202, { "success": True }), resp.text)
		self.assertEqual(self.asked, [ident])

	def test_a_timed_task_can_be_run_now_too(self):
		self.assertEqual(self.client.post(f"{BASE}/doc-a/items/a1/run").status_code, 202)
		self.assertEqual(self.asked, ["a1"])

	def test_only_priority_update_may_have_no_time(self):
		resp = self.client.post(f"{BASE}/doc-a/items", json={ "trigger": ON_DEMAND, "task": { "plugin_name": "slide-show", "content": {} } })
		self.assertIn({ "path": ["trigger"], "message": "only Priority Update can run on demand" }, _error_shape(self, resp, 422)["errors"])

	def test_it_is_in_the_render_as_not_rendered_and_never_given_a_time(self):
		ident = self.add()
		body = self.client.get("/api/schedule/tasks/render?days=2").json()
		self.assertIn({ "schedule": "doc-a", "id": ident }, body["not_render"])
		self.assertEqual([r for r in body["render"] if r["id"] == ident], [] if "render" in body else [])

	def test_a_disabled_task_is_refused(self):
		ident = self.add(enabled=False)
		_error_shape(self, self.client.post(f"{BASE}/doc-a/items/{ident}/run"), 409)
		self.assertEqual(self.asked, [])

	def test_an_unknown_task_is_a_404(self):
		_error_shape(self, self.client.post(f"{BASE}/doc-a/items/zzz/run"), 404)

	def test_a_device_that_is_not_ready_is_a_503(self):
		ident = self.add()
		self.ready = False
		_error_shape(self, self.client.post(f"{BASE}/doc-a/items/{ident}/run"), 503)

if __name__ == '__main__':
	unittest.main()
