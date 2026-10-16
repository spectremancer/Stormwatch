import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from alert_history import AlertHistory
from WeatherService import WeatherService


class AlertHistoryTests(unittest.TestCase):
    def test_atomic_claim_across_connections_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.sqlite3"
            first, second = AlertHistory(path), AlertHistory(path)
            try:
                self.assertTrue(first.claim("alert-one"))
                self.assertFalse(second.claim("alert-one"))
                self.assertTrue(second.claim("alert-two"))
            finally:
                first.close()
                second.close()
            reopened = AlertHistory(path)
            try:
                self.assertFalse(reopened.claim("alert-one"))
                self.assertFalse(reopened.claim("alert-two"))
            finally:
                reopened.close()


class WindowsNotificationTests(unittest.TestCase):
    @patch("WeatherService.notification.notify")
    @patch("WeatherService.platform.system", return_value="Windows")
    def test_tornado_and_hurricane_push_notifications(self, system, notify):
        service = WeatherService.__new__(WeatherService)
        service.play_sound = Mock()
        service.play_tornado_alert = Mock()
        service.logger = Mock()
        for event in ("Tornado Warning", "Tornado Watch", "Hurricane Warning", "Hurricane Watch"):
            with self.subTest(event=event):
                service.notify(dict(event=event, area="County " * 100,
                                    headline="Emergency", url="https://weather.gov"))
                args = notify.call_args.kwargs
                self.assertIn(event, args["title"])
                self.assertLessEqual(len(args["title"]), 63)
                self.assertLessEqual(len(args["message"]), 255)
                self.assertEqual(args["app_name"], "US Storm Monitor")
        self.assertEqual(notify.call_count, 4)
        self.assertEqual(service.play_tornado_alert.call_count, 4)
