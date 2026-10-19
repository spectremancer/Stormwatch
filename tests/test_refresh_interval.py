from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from alert_history import AlertHistory
from main import REFRESH_INTERVALS, StormwatchApp


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'),'GUI tests require a desktop display')
class RefreshIntervalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)/'history.db'
        self.ui = StormwatchApp(Mock(interval=60),AlertHistory(self.path))
        self.ui.app.root.update()

    def tearDown(self):
        self.ui.close()
        self.ui.cleanup_thread.join(timeout=5)
        self.ui = None
        self.directory.cleanup()

    def test_all_choices_apply_on_start_and_schedule_correct_delay(self):
        self.assertEqual(self.ui.refresh_interval_picker.values,('30 seconds','60 seconds','90 seconds','120 seconds'))
        for seconds in REFRESH_INTERVALS:
            with self.subTest(seconds=seconds):
                self.ui.refresh_interval_picker.set(f'{seconds} seconds')
                self.ui.refresh_interval_picker.widget.event_generate('<<ComboboxSelected>>')
                self.ui.app.root.update()
                with patch.object(self.ui,'poll') as poll:
                    self.ui.toggle_monitoring()
                    poll.assert_called_once()
                    self.assertTrue(self.ui.refresh_interval_picker.widget.instate(['disabled']))
                    self.assertEqual(self.ui.service.interval,seconds)
                    with patch.object(self.ui.app,'after',return_value=None) as timer:
                        before = datetime.now(timezone.utc)
                        self.ui.schedule_next()
                        timer.assert_called_once_with(seconds*1000,poll)
                        self.assertAlmostEqual((self.ui.next_refresh-before).total_seconds(),seconds,delta=.1)
                self.assertFalse(self.ui.set_refresh_interval('60 seconds'))
                self.assertEqual(self.ui.service.interval,seconds)
                self.ui.toggle_monitoring()
                self.assertTrue(self.ui.refresh_interval_picker.widget.instate(['readonly','!disabled']))

    def test_saved_interval_is_restored_and_invalid_saved_value_falls_back(self):
        self.ui.set_refresh_interval('90 seconds')
        self.ui.close();self.ui.cleanup_thread.join(timeout=5)
        self.ui = None
        self.ui = StormwatchApp(Mock(interval=60),AlertHistory(self.path))
        self.assertEqual(self.ui.service.interval,90)
        self.assertEqual(self.ui.refresh_interval_picker.get(),'90 seconds')
        self.ui.history.save_setting('nws_refresh_interval',45)
        self.ui.close();self.ui.cleanup_thread.join(timeout=5)
        self.ui = None
        self.ui = StormwatchApp(Mock(interval=60),AlertHistory(self.path))
        self.assertEqual(self.ui.service.interval,60)
        self.assertEqual(self.ui.refresh_interval_picker.get(),'60 seconds')

    def test_invalid_selection_and_save_failure_do_not_change_active_interval(self):
        self.assertFalse(self.ui.set_refresh_interval('15 seconds'))
        self.assertEqual(self.ui.service.interval,60)
        with patch.object(self.ui.history,'save_setting',side_effect=sqlite3.OperationalError('disk full')):
            self.ui.refresh_interval_picker.set('30 seconds')
            with patch.object(self.ui,'poll') as poll:
                self.ui.toggle_monitoring()
                poll.assert_not_called()
        self.assertFalse(self.ui.running)
        self.assertEqual(self.ui.refresh_interval_picker.get(),'60 seconds')

    def test_failure_retry_and_freshness_follow_selected_interval(self):
        self.ui.set_refresh_interval('120 seconds')
        self.ui.running = True
        self.ui.last_success = datetime.now(timezone.utc)-timedelta(seconds=150)
        self.ui.update_health()
        self.assertTrue(self.ui.health.get().startswith('LIVE'))
        with patch.object(self.ui.app,'after',return_value=None) as timer:
            self.ui.failed(self.ui.generation,RuntimeError('offline'))
            timer.assert_called_once_with(120000,self.ui.poll)
        self.ui.running = False
        self.ui.last_error = ''
        self.ui.set_refresh_interval('30 seconds')
        self.ui.running = True
        self.ui.update_health()
        self.assertTrue(self.ui.health.get().startswith('STALE'))
