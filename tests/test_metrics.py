"""Metrics count the complete archive and current monitored snapshot separately."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from alert_history import AlertHistory
from history_store import HistoryFilter
from main import StormwatchApp
from metrics import summarize
from test_dashboard import alert


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = AlertHistory(Path(self.directory.name)/'history.db')

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_all_history_versions_downloads_and_active_only_types_are_distinguished(self):
        self.store.observe(alert(id='tornado'))
        self.store.observe(alert(id='tornado',headline='Updated instructions'))
        self.store.reconcile(set())
        self.store.import_archive([alert(id='hurricane',event='Hurricane Warning')],'FL',threading.Event())
        # Neither a History search nor a page limit restricts the aggregates.
        self.assertEqual(self.store.history_count(HistoryFilter(event='Flood')),0)
        now = datetime.now(timezone.utc)
        with patch('history_store.json.loads',side_effect=AssertionError('History JSON should not be decoded')):
            result = summarize(self.store,[('thunder','Severe Thunderstorm Warning',(now+timedelta(hours=1)).isoformat()),
                                            ('expired','Tornado Watch',(now-timedelta(seconds=1)).isoformat())],now)
        rows = {row['event']:row for row in result['rows']}
        self.assertEqual(rows['Tornado Warning'],dict(event='Tornado Warning',alert_ids=1,changes=3,downloaded=0,active=0))
        self.assertEqual(rows['Hurricane Warning']['downloaded'],1)
        self.assertEqual(rows['Hurricane Warning']['active'],0)
        self.assertEqual(rows['Severe Thunderstorm Warning']['alert_ids'],0)
        self.assertEqual(rows['Severe Thunderstorm Warning']['active'],1)
        self.assertNotIn('Tornado Watch',rows)
        self.assertEqual(result['history']['alert_ids'],2)
        self.assertEqual(result['history']['changes'],4)
        self.assertEqual(result['active'],1)
        self.assertEqual(result['active_types'],1)

    def test_empty_archive_and_snapshot_have_zero_totals(self):
        result = summarize(self.store,[])
        self.assertEqual(result['rows'],[])
        self.assertEqual(result['history'],dict(types=[],alert_ids=0,changes=0,downloaded=0))
        self.assertEqual(result['active'],0)

    def test_counts_include_every_history_page(self):
        for i in range(65):
            self.store.observe(alert(id=str(i)))
        result = summarize(self.store,[])
        self.assertEqual(result['rows'][0]['alert_ids'],65)
        self.assertEqual(result['history']['changes'],65)

    def test_summary_is_consistent_while_live_monitoring_writes(self):
        self.store.observe(alert(id='before'))
        reader = sqlite3.connect(self.store.path)
        reader.row_factory = sqlite3.Row
        proxy = Mock(wraps=reader)
        def execute(sql,*args):
            cursor = reader.execute(sql,*args)
            if 'GROUP BY event' in sql:
                self.store.observe(alert(id='during',event='Tornado Watch'))
            return cursor
        proxy.execute.side_effect = execute
        with patch('history_store.sqlite3.connect',return_value=proxy):
            result = self.store.history_metrics()
        self.assertEqual(result['alert_ids'],1)
        self.assertEqual(result['changes'],1)
        self.assertEqual(len(result['types']),1)
        self.assertEqual(self.store.history_count(),2)


@unittest.skipUnless(os.environ.get('DISPLAY'),'GUI tests require DISPLAY')
class MetricsGuiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.service = Mock(interval=60)
        self.ui = StormwatchApp(self.service,AlertHistory(Path(self.directory.name)/'history.db'))
        self.ui.app.root.update()

    def tearDown(self):
        self.ui.close()
        self.ui.cleanup_thread.join(timeout=5)
        self.directory.cleanup()

    def pump(self, condition):
        deadline = time.monotonic()+5
        while not condition() and time.monotonic()<deadline:
            self.ui.app.root.update()
            time.sleep(.01)
        self.assertTrue(condition())

    def test_menu_opens_reusable_metrics_and_manual_refresh_includes_new_history(self):
        self.assertEqual(self.ui.menu.widget.entrycget(0,'label'),'Data')
        self.assertEqual(self.ui.data_menu.widget.entrycget(0,'label'),'metrics')
        self.ui.history.observe(alert())
        self.ui.render_active()
        self.ui.history_panel.text.set('Flood')
        self.ui.history_panel.apply()
        self.assertFalse(self.ui.history_panel.rows)
        self.ui.data_menu.widget.invoke(0)
        panel = self.ui.metrics
        self.pump(lambda:not panel.busy)
        values = panel.table.tree.item(panel.table.tree.get_children()[0],'values')
        self.assertEqual(tuple(values),('Tornado Warning','1','1','0','1'))
        self.assertIn('1 historical types',panel.total.get())
        self.assertIn('1 active types',panel.total.get())
        self.assertIn('NO LIVE DATA',panel.message.get())
        panel.hide()
        self.ui.history.observe(alert(id='watch',event='Tornado Watch'))
        self.ui.render_active()
        self.ui.data_menu.widget.invoke(0)
        self.assertIs(self.ui.metrics,panel)
        self.pump(lambda:not panel.busy)
        self.assertEqual(len(panel.table.tree.get_children()),2)
        self.assertEqual(panel.window.root.state(),'normal')
        self.service.fetch_alerts.assert_not_called()
        self.service.deliver_sound.assert_not_called()
        self.service.deliver_desktop.assert_not_called()

    def test_archive_query_runs_off_gui_thread_and_closing_during_refresh_is_safe(self):
        started, release = threading.Event(),threading.Event()
        original = self.ui.history.history_metrics
        threads = []
        def query():
            threads.append(threading.get_ident())
            started.set()
            self.assertTrue(release.wait(5))
            return original()
        try:
            with patch.object(self.ui.history,'history_metrics',side_effect=query):
                self.ui.open_metrics()
                self.assertTrue(started.wait(3))
                self.ui.app.root.update()
                self.ui.close()
                release.set()
                self.ui.cleanup_thread.join(timeout=5)
                self.assertFalse(self.ui.cleanup_thread.is_alive())
                self.assertNotEqual(threads[0],threading.get_ident())
                self.assertIsNone(self.ui.metrics.future.exception())
        finally:
            release.set()

    def test_error_keeps_previous_summary_and_allows_retry(self):
        self.ui.open_metrics()
        self.pump(lambda:not self.ui.metrics.busy)
        panel = self.ui.metrics
        before = panel.total.get()
        with patch.object(self.ui.history,'history_metrics',side_effect=RuntimeError('unavailable')):
            panel.refresh()
            self.pump(lambda:not panel.busy)
        self.assertEqual(panel.total.get(),before)
        self.assertIn('unavailable',panel.message.get())
        self.assertFalse(panel.refresh_button.widget.instate(['disabled']))
