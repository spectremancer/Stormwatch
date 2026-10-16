"""GUI integration checks. Run with a display (or a virtual X server)."""
import os
from pathlib import Path
import time
import tempfile
import unittest
from unittest.mock import Mock

from main import StormwatchApp
from alert_history import AlertHistory
from WeatherService import WeatherService


@unittest.skipUnless(os.environ.get("DISPLAY"), "GUI tests require DISPLAY")
class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.service = Mock(interval=60, base_dir=Path(__file__).resolve().parents[1],
                            WATCHED_EVENTS=WeatherService.WATCHED_EVENTS)
        self.service.get_fingerprint.side_effect = lambda alert: WeatherService.get_fingerprint(None, alert)
        self.service.parse_alert.side_effect = lambda feature: WeatherService.parse_alert(None, feature)
        self.service.fetch_alerts.return_value = []
        self.temp = tempfile.TemporaryDirectory()
        self.history_path = Path(self.temp.name) / "alerts.sqlite3"
        self.ui = StormwatchApp(self.service, AlertHistory(self.history_path))
        self.ui.app.root.update()

    def tearDown(self):
        if not self.ui.app._closed:
            self.ui.close()
        self.temp.cleanup()

    def alert(self, event="Tornado Warning", headline="Take shelter"):
        return dict(id=event, event=event, headline=headline, area="Test County",
                    severity="Extreme", urgency="Immediate", sent="now",
                    expires="later", instruction="Seek shelter indoors.", url="https://weather.gov")

    def receive(self, alerts, previous=None):
        self.ui.running = True
        self.ui.received(self.ui.generation, self.ui.selected_events(),
                         ({a["id"]: a for a in alerts}, previous or {}))
        if self.ui.timer:
            self.ui.app.root.after_cancel(self.ui.timer)
            self.ui.timer = None

    def pump(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.ui.app.root.update()
            time.sleep(.01)
        self.assertTrue(predicate())

    def test_selected_alerts_only_and_duplicates(self):
        tornado, flood = self.alert(), self.alert("Flood Watch")
        self.receive([tornado, flood])
        self.assertIn("Take shelter", self.ui.feed.get())
        self.assertNotIn("Flood Watch", self.ui.feed.get())
        self.assertEqual(self.ui.count, 1)
        self.receive([tornado], self.ui.snapshot)
        self.assertEqual(self.ui.count, 1)
        self.pump(lambda: self.service.notify.called)
        self.assertEqual(self.service.notify.call_count, 1)

    def test_new_alert_after_empty_snapshot_notifies(self):
        self.receive([])
        self.receive([self.alert()])
        self.pump(lambda: self.service.notify.called)
        self.assertEqual(self.ui.count, 1)

    def test_same_id_is_processed_once_even_if_content_changes(self):
        alert = self.alert()
        self.receive([alert])
        self.receive([self.alert(headline="Updated instructions")], self.ui.snapshot)
        self.assertEqual(self.ui.count, 1)
        self.assertNotIn("Updated instructions", self.ui.feed.get())

    def test_history_survives_restart_and_filter_changes(self):
        alert = self.alert()
        self.receive([alert])
        self.receive([])
        self.ui.clear_feed()
        self.receive([alert])
        self.assertEqual(self.ui.count, 0)
        self.ui.close()
        self.ui = StormwatchApp(self.service, AlertHistory(self.history_path))
        self.receive([alert])
        self.assertEqual(self.ui.count, 0)

    def test_checkboxes_are_above_canvas_and_scroll(self):
        box = self.ui.choices["Tornado Warning"].widget
        self.ui.app.root.update()
        x, y = box.winfo_rootx() + 8, box.winfo_rooty() + 8
        self.assertEqual(self.ui.app.root.winfo_containing(x, y), box)
        self.ui.filters.canvas.yview_moveto(1)
        self.ui.app.root.update()
        last = self.ui.choices["Tsunami Watch"].widget
        self.assertTrue(last.winfo_ismapped())
        self.assertEqual(self.ui.app.root.winfo_containing(
            last.winfo_rootx() + 8, last.winfo_rooty() + 8), last)

    def test_hurricane_notifies_on_first_refresh(self):
        self.receive([self.alert("Hurricane Watch")])
        self.pump(lambda: self.service.notify.called)
        self.service.notify.assert_called_once_with(self.alert("Hurricane Watch"), updated=False)

    def test_pause_discards_inflight_result(self):
        self.ui.running = True
        generation = self.ui.generation
        self.ui.toggle_monitoring()
        self.ui.received(generation, {"Tornado Warning"}, ({"x": self.alert()}, {}))
        self.assertEqual(self.ui.feed.get(), "")
        self.service.notify.assert_not_called()

    def test_error_and_sound_test_stay_out_of_feed(self):
        self.ui.running = True
        self.ui.failed(self.ui.generation, RuntimeError("Offline"))
        self.assertIn("Offline", self.ui.status.get())
        self.assertEqual(self.ui.feed.get(), "")
        self.ui.test_sound()
        self.pump(lambda: "Sound test started" in self.ui.status.get())
        self.assertEqual(self.ui.feed.get(), "")

    def test_background_poll_and_selection_validation(self):
        self.ui.select_all(False)
        self.ui.toggle_monitoring()
        self.assertFalse(self.ui.running)
        self.ui.choices["Tornado Warning"].set(True)
        self.service.fetch_alerts.return_value = [{"id": "a", "properties": {
            "event": "Tornado Warning", "headline": "Live fixture"}}]
        self.ui.toggle_monitoring()
        self.pump(lambda: self.ui.count == 1)
        self.assertIn("Live fixture", self.ui.feed.get())
        self.ui.clear_feed()
        self.assertEqual(self.ui.feed.get(), "")
        self.assertEqual(self.ui.count, 0)


if __name__ == "__main__":
    unittest.main()
