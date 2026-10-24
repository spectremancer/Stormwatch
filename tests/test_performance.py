"""Load regressions: bounded UI work, indexed expiry, and readable inputs."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from alert_history import AlertHistory
from main import StormwatchApp
from test_dashboard import alert


class StorePerformanceTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.store=AlertHistory(Path(self.directory.name)/'store.db')

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_nested_batch_rolls_back_alert_and_history_together(self):
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.observe(alert(id='one'))
                self.store.observe(alert(id='two'))
                raise RuntimeError('Aborted processing batch')
        self.assertEqual(self.store.known_ids(['one','two']),set())
        self.assertEqual(self.store.history_count(),0)

    def test_unchanged_observation_does_not_rewrite_alerts_or_history(self):
        now=datetime.now(timezone.utc)
        a=alert()
        self.store.observe(a,now)
        changes=self.store.connection.total_changes
        self.store.observe(a,now+timedelta(minutes=1))
        self.assertEqual(self.store.connection.total_changes,changes)
        self.assertEqual(self.store.history_count(),1)

    def test_idle_expiry_and_id_lookup_do_not_decode_unrelated_alerts(self):
        self.store.observe(alert(id='future'))
        with patch('alert_history.json.loads',side_effect=AssertionError('Unnecessary JSON decode')):
            self.assertEqual(self.store.known_ids(['future','unknown']),{'future'})
            self.assertEqual(self.store.reconcile(),[])

    def test_legacy_active_expiry_is_backfilled_and_remains_correct(self):
        self.store.close()
        path=Path(self.directory.name)/'old.db'
        connection=sqlite3.connect(path)
        connection.execute('CREATE TABLE alerts (id TEXT PRIMARY KEY,version TEXT,data TEXT,status TEXT,updated TEXT)')
        connection.execute('INSERT INTO alerts VALUES (?,?,?,?,?)',
                           ('old','version',json.dumps(alert(id='old',expires='2020-01-01T00:00:00Z')),'Active','2020'))
        connection.commit();connection.close()
        self.store=AlertHistory(path)
        self.assertEqual(self.store.reconcile()[0][1],'Expired')
        self.assertEqual(self.store.reconcile(),[])


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'),'GUI tests require a desktop display')
class GuiPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.service=Mock(interval=60)
        self.owner=StormwatchApp(self.service,AlertHistory(Path(self.directory.name)/'live.db'))
        self.owner.profile.sound=self.owner.profile.desktop=False
        self.owner.app.root.update()

    def tearDown(self):
        self.owner.close();self.owner.cleanup_thread.join(timeout=5)
        self.directory.cleanup()

    def pump(self, condition):
        deadline=time.monotonic()+10
        while not condition() and time.monotonic()<deadline:
            self.owner.app.root.update();time.sleep(.001)
        self.assertTrue(condition())

    def test_editable_form_and_combobox_text_is_black_on_white(self):
        style=self.owner.app.style
        for state in ((),('focus',),('readonly',)):
            self.assertEqual(style.lookup('TEntry','foreground',state),'#000000')
            self.assertEqual(style.lookup('TEntry','fieldbackground',state),'#ffffff')
            self.assertEqual(style.lookup('Input.TCombobox','foreground',state),'#000000')
        self.assertEqual(self.owner.history_panel.event.widget.cget('style'),'Input.TCombobox')

    def test_large_burst_yields_to_gui_and_repeated_snapshot_does_not_rebuild_cards(self):
        data={str(i):alert(id=str(i)) for i in range(1000)}
        heartbeat=[]
        self.owner.running=True
        self.owner.app.after(0,lambda:heartbeat.append(self.owner.count))
        self.owner.received(self.owner.generation,(data,''))
        self.assertTrue(self.owner.busy)
        self.assertLess(self.owner.count,1000)
        self.pump(lambda:not self.owner.busy and self.owner.active_query.future is None and self.owner.active_query.pending is None)
        self.assertTrue(heartbeat)
        self.assertLess(heartbeat[0],1000)
        self.assertEqual(self.owner.count,1000)
        self.assertEqual(len(self.owner.snapshot),1000)
        self.assertLessEqual(int(self.owner.feed.text.index('end-1c').split('.')[0]),4001)
        widgets=self.owner.cards.body.winfo_children()
        changes=self.owner.history.connection.total_changes
        if self.owner.timer:self.owner.app.root.after_cancel(self.owner.timer)
        self.owner.received(self.owner.generation,(data,''))
        self.pump(lambda:not self.owner.busy and self.owner.active_query.future is None and self.owner.active_query.pending is None)
        self.assertEqual(self.owner.count,1000)
        self.assertEqual(self.owner.cards.body.winfo_children(),widgets)
        self.assertEqual(self.owner.history.connection.total_changes,changes)
        self.assertEqual(self.owner.history.history_count(),1000)

    def test_pause_mid_burst_does_not_reconcile_an_incomplete_snapshot(self):
        self.owner.history.observe(alert(id='prior-active'))
        data={str(i):alert(id=str(i)) for i in range(100)}
        self.owner.running=True
        self.owner.received(self.owner.generation,(data,''))
        processed=self.owner.count
        self.owner.toggle_monitoring()
        self.pump(lambda:not self.owner.busy and self.owner.active_query.future is None and self.owner.active_query.pending is None)
        self.assertEqual(self.owner.count,processed)
        self.assertEqual(self.owner.history.get_alert('prior-active')['status'],'Active')
        self.service.deliver_desktop.assert_not_called()
        self.service.deliver_sound.assert_not_called()

    def test_unchanged_map_is_cached_and_drag_redraws_are_coalesced(self):
        self.owner.tabs.widget.select(self.owner.map.parent.widget)
        self.owner.app.root.update()
        rows=[dict(id='one',version='one',alert=alert(geometry={'type':'Polygon','coordinates':[[[-88,41],[-87,41],[-87,42],[-88,41]]]}))]
        self.owner.map.render(rows,self.owner.profiles)
        self.owner.app.root.update()
        items=self.owner.map.canvas.find_all()
        self.owner.map.render(rows,self.owner.profiles)
        self.owner.app.root.update()
        self.assertEqual(self.owner.map.canvas.find_all(),items)
        with patch.object(self.owner.map,'draw',wraps=self.owner.map.draw) as draw:
            self.owner.map.start_drag(Mock(x=100,y=100))
            self.owner.map.move(Mock(x=110,y=110))
            self.owner.map.move(Mock(x=120,y=120))
            self.owner.map.move(Mock(x=130,y=130))
            self.owner.app.root.update()
            self.assertEqual(draw.call_count,1)
