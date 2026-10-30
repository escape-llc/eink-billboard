"""The web app's restart (#839): what waits for one, who may ask, and that nothing is stopped where nothing would start the app again."""
import os
from unittest.mock import patch

from ..task.application import Application
from .test_web_api import WebApiTestBase

class TestRestart(WebApiTestBase):
	def setUp(self):
		super().setUp()
		self.application = Application("TestApp")
		self.application.cm = self.cm
		self.application.setup_notice = None
		root = self.app.state.root_container
		root.add_service(Application, self.application)
		self.stopped: list[bool] = []
		self.app.state.stop = lambda: self.stopped.append(True)

	def display_started(self) -> None:
		"""What the Display task's start leaves in the application."""
		self.application.display_loaded = self.application._display_keys()

	def choose(self, **changes) -> None:
		doc = self.client.get("/api/settings/display").json()
		self.assertEqual(self.client.put("/api/settings/display", json={ **doc, **changes }).status_code, 200)

	def test_nothing_waits_until_a_display_setting_that_is_read_once_is_saved_differently(self):
		self.assertEqual(self.client.get("/api/system/restart").json()["waiting"], [])
		self.display_started()
		self.assertEqual(self.client.get("/api/system/restart").json()["waiting"], [])
		kind = "waveshare" if self.client.get("/api/settings/display").json()["display_type"] != "waveshare" else "mock"
		self.choose(display_type=kind)
		[words] = self.client.get("/api/system/restart").json()["waiting"]
		self.assertIn("display type", words.lower())
		# put back, nothing waits any more
		self.choose(display_type=self.application.display_loaded["display_type"])
		self.assertEqual(self.client.get("/api/system/restart").json()["waiting"], [])

	def test_it_is_offered_only_where_the_container_starts_the_app_again(self):
		with patch.dict(os.environ, { "EINK_RESTARTABLE": "" }):
			self.assertFalse(self.client.get("/api/system/restart").json()["available"])
		with patch.dict(os.environ, { "EINK_RESTARTABLE": "1" }):
			self.assertTrue(self.client.get("/api/system/restart").json()["available"])

	def test_a_restart_that_nothing_would_undo_is_refused_and_stops_nothing(self):
		with patch.dict(os.environ, { "EINK_RESTARTABLE": "" }):
			answer = self.client.post("/api/system/restart")
		self.assertEqual(answer.status_code, 409)
		self.assertEqual(self.stopped, [])

	def test_the_app_stops_after_the_answer_is_sent(self):
		with patch.dict(os.environ, { "EINK_RESTARTABLE": "1" }):
			answer = self.client.post("/api/system/restart")
		self.assertEqual(answer.status_code, 202)
		self.assertEqual(self.stopped, [True])

	def test_an_unclaimed_device_has_no_owner_to_ask(self):
		self.application.setup_notice = lambda: "Set up this device"
		with patch.dict(os.environ, { "EINK_RESTARTABLE": "1" }):
			answer = self.client.post("/api/system/restart")
		self.assertEqual(answer.status_code, 403)
		self.assertEqual(self.stopped, [])
