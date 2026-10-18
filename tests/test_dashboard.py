"""Integration tests using real Tk widgets and simulated NWS responses."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock

from main import StormwatchApp
from alert_history import AlertHistory
from WeatherService import WeatherService
from locations import LocationProfile


def alert(event="Tornado Warning", headline="Take shelter", **extra):
    return dict(dict(id=event, event=event, headline=headline, area="Cook County",
                     severity="Extreme", urgency="Immediate", sent="2026-10-16T10:00:00Z",
                     expires="2099-10-16T11:00:00Z", ends="", instruction="Seek shelter indoors.",
                     url="https://weather.gov", geocode={"UGC": ["ILC031"]}, references=[],
                     message_type="Alert", geometry=None), **extra)


@unittest.skipUnless(os.environ.get("DISPLAY"), "GUI tests require DISPLAY")
class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.service = Mock(interval=60, base_dir=Path(__file__).resolve().parents[1])
        self.service.parse_alert.side_effect = lambda feature: WeatherService.parse_alert(None, feature)
        self.service.fetch_alerts.return_value = []
        self.service.fetch_cancellations.return_value = []
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "alerts.sqlite3"
        self.ui = StormwatchApp(self.service, AlertHistory(self.path))
        self.ui.app.root.update()

    def tearDown(self):
        if not self.ui.app._closed:
            self.ui.close()
        # Join cleanup to exercise database/session shutdown, not just request it.
        self.ui.cleanup_thread.join(timeout=5)
        self.temp.cleanup()

    def receive(self, alerts, warning=""):
        self.ui.running = True
        self.ui.received(self.ui.generation, ({a["id"]: a for a in alerts}, warning))
        if self.ui.timer:
            self.ui.app.root.after_cancel(self.ui.timer)
            self.ui.timer = None
        if self.ui.delivery_future:
            self.ui.delivery_future.result(timeout=3)
            self.pump(lambda: not self.ui.delivery_busy)

    def pump(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.ui.app.root.update()
            time.sleep(.01)
        self.assertTrue(predicate())

    def test_filter_cards_deduplication_and_versions(self):
        a = alert()
        self.receive([a, alert("Flood Watch")])
        self.assertEqual(self.ui.count, 1)
        self.assertEqual(len(self.ui.snapshot), 1)
        self.receive([a])
        self.assertEqual(self.ui.count, 1)
        self.service.deliver_desktop.assert_called_once()
        self.receive([alert(headline="Updated instructions")])
        self.assertIn("UPDATED", self.ui.feed.get())
        self.assertEqual(self.ui.count, 2)
        self.assertEqual(self.ui.snapshot[a["id"]]["headline"], "Updated instructions")
        self.assertEqual(self.service.deliver_desktop.call_count, 2)

    def test_failed_desktop_retries_without_replaying_sound(self):
        self.service.deliver_desktop.side_effect = RuntimeError("desktop offline")
        for _ in range(4):
            self.receive([alert()])
        self.assertEqual(self.service.deliver_desktop.call_count, 3)
        self.service.deliver_sound.assert_called_once()
        self.assertEqual(self.ui.count, 1)
        self.assertNotIn("offline", self.ui.feed.get())

    def test_history_survives_restart_but_cards_stay_current(self):
        a = alert()
        self.receive([a])
        self.ui.clear_feed()
        self.receive([a])
        self.assertEqual(self.ui.count, 0)
        self.ui.close()
        self.ui.cleanup_thread.join(timeout=3)
        self.ui = StormwatchApp(self.service, AlertHistory(self.path))
        self.receive([a])
        self.assertEqual(self.ui.count, 0)
        self.assertEqual(len(self.ui.snapshot), 1)
        self.service.deliver_sound.assert_called_once()

    def test_location_profiles_and_separate_channels(self):
        self.ui.profile.states = ["IL"]
        self.ui.profile.sound = False
        self.ui.history.save_profile(self.ui.profile)
        family = LocationProfile(name="Family", states=["TX"], desktop=False)
        self.ui.history.save_profile(family)
        self.ui.refresh_profiles()
        self.receive([alert(), alert(id="tx", geocode={"UGC": ["TXC201"]}),
                      alert(id="ca", geocode={"UGC": ["CAC037"]})])
        self.assertEqual(len(self.ui.snapshot), 2)
        self.service.deliver_sound.assert_called_once()
        self.service.deliver_desktop.assert_called_once()

    def test_expiration_and_explicit_cancellation(self):
        a = alert()
        self.receive([a])
        self.receive([alert(id="cancel", message_type="Cancel", references=[{"identifier": a["id"]}])])
        self.assertIn("CANCELLED", self.ui.feed.get())
        self.assertEqual(len(self.ui.snapshot), 0)
        expired = alert(id="expired", expires="2020-01-01T00:00:00Z")
        self.receive([expired])
        self.assertEqual(len(self.ui.snapshot), 0)
        self.assertIn("EXPIRED", self.ui.feed.get())

    def test_pause_and_connection_health(self):
        self.receive([alert()])
        self.ui.toggle_monitoring()
        self.assertIn("STALE", self.ui.health.get())
        self.ui.received(self.ui.generation - 1, ({"other": alert(id="other")}, ""))
        self.assertEqual(self.ui.count, 1)
        self.ui.running = True
        self.ui.failed(self.ui.generation, RuntimeError("Offline"))
        self.assertIn("Offline", self.ui.status.get())
        self.assertNotIn("Offline", self.ui.feed.get())
        self.assertEqual(len(self.ui.snapshot), 1)

    def test_checkbox_visibility_and_scroll(self):
        box = next(iter(self.ui.choices.values())).widget
        self.assertEqual(self.ui.app.root.winfo_containing(box.winfo_rootx()+8, box.winfo_rooty()+8), box)
        self.ui.filters.canvas.yview_moveto(1)
        self.ui.app.root.update()
        last = list(self.ui.choices.values())[-1].widget
        self.assertEqual(self.ui.app.root.winfo_containing(last.winfo_rootx()+8, last.winfo_rooty()+8), last)

    def test_background_poll_and_sound_test(self):
        self.service.fetch_alerts.return_value = [{"id": "a", "properties": {"event": "Tornado Warning", "headline": "Live fixture"}}]
        self.ui.toggle_monitoring()
        self.pump(lambda: self.ui.count == 1)
        self.assertIn("Live fixture", self.ui.feed.get())
        self.ui.test_sound()
        self.pump(lambda: "Sound test started" in self.ui.status.get())
        self.assertNotIn("Sound test", self.ui.feed.get())

    def test_map_zoom_pan_and_profile_marker(self):
        self.ui.profile.latitude, self.ui.profile.longitude = 41.9, -87.6
        self.ui.profile.zones = ["ILC031"]
        a = alert(geometry={"type": "Polygon", "coordinates": [[[-88,41],[-87,41],[-87,42],[-88,42],[-88,41]]]})
        self.receive([a])
        self.ui.tabs.widget.select(self.ui.map.parent.widget)
        self.ui.app.root.update()
        self.ui.map.fit()
        self.assertTrue(self.ui.map.items)
        scale = self.ui.map.scale
        self.ui.map.zoom(1.5)
        self.assertGreater(self.ui.map.scale, scale)
        self.ui.map.start_drag(Mock(x=100, y=100))
        center = self.ui.map.center
        self.ui.map.move(Mock(x=130, y=110))
        self.assertNotEqual(center, self.ui.map.center)

    def test_large_dashboard_is_paginated(self):
        rows = [{"id":str(i), "alert":alert(id=str(i)), "locations":["Home"]} for i in range(500)]
        self.ui.cards.render(rows)
        self.ui.app.root.update()
        self.assertEqual(len(self.ui.cards.labels), 20)
        self.ui.cards.change_page(1)
        self.ui.app.root.update()
        self.assertEqual(self.ui.cards.labels[0][1]["id"], "20")
        self.assertEqual(len(self.ui.cards.labels), 20)

    def test_tray_failure_preserves_window(self):
        self.ui.tray_failed(RuntimeError("Unavailable"))
        self.assertFalse(self.ui.hidden)
        self.assertFalse(self.ui.tray_mode.get())
        self.assertIn("Unavailable", self.ui.status.get())
