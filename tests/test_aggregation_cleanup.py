"""Speech batches, terminal lifecycle cleanup, ordering and scroll clipping."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from alert_history import AlertHistory, expiration_of
from dashboard_views import active_sort_key
from main import StormwatchApp
from speech import SpeechCancelled, batch_announcement
from test_dashboard import alert


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = AlertHistory(Path(self.directory.name)/'history.db')
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_earliest_message_expiry_or_hazard_end_controls_active_lifetime(self):
        a = alert(expires=(self.now+timedelta(minutes=1)).isoformat(),ends=(self.now+timedelta(hours=2)).isoformat())
        self.assertEqual(expiration_of(a),self.now+timedelta(minutes=1))
        version,_,_ = self.store.observe(a,self.now)
        self.assertTrue(self.store.is_active(a['id'],version,self.now))
        self.assertFalse(self.store.is_active(a['id'],version,self.now+timedelta(minutes=2)))
        changes = self.store.reconcile(now=self.now+timedelta(minutes=2))
        self.assertEqual(changes[0][1],'Expired')
        self.assertFalse(self.store.rows(active_only=True))
        self.assertEqual(self.store.observe(a,self.now)[1],'Expired')
        self.assertEqual(self.store.get_alert(a['id'])['status'],'Expired')

    def test_cancelled_and_superseded_messages_do_not_return_from_stale_polls(self):
        a = alert(id='original')
        self.store.observe(a)
        self.store.observe(dict(a,headline='Updated instructions'))
        self.store.cancel_references(alert(message_type='Cancel',references=[{'identifier':a['id']}]))
        self.assertEqual(self.store.observe(a)[1],'Cancelled')
        self.assertEqual(self.store.get_alert(a['id'])['status'],'Cancelled')
        b = alert(id='superseded')
        self.store.observe(b)
        self.store.observe(alert(id='replacement',message_type='Update',references=[{'identifier':b['id']}]))
        self.assertEqual(self.store.observe(b)[1],'Superseded')
        self.assertNotIn('superseded',self.store.active_ids())
        self.assertTrue(self.store.search_history())

    def test_existing_expiry_index_is_migrated_to_message_validity(self):
        a = alert(expires=(self.now+timedelta(minutes=1)).isoformat(),ends=(self.now+timedelta(hours=2)).isoformat())
        self.store.observe(a)
        self.store.connection.execute('UPDATE alerts SET expires_at=?',(a['ends'],))
        self.store.connection.execute("DELETE FROM settings WHERE name='expiry_basis_v2'")
        self.store.connection.commit()
        self.store.close()
        self.store = AlertHistory(self.store.path)
        self.assertEqual(self.store.reconcile(now=self.now+timedelta(minutes=2))[0][1],'Expired')

    def test_active_order_is_category_then_severity_then_longest_expiration(self):
        def row(key,event,severity,hours):
            return dict(id=key,alert=alert(id=key,event=event,severity=severity,
                expires=(self.now+timedelta(hours=hours)).isoformat()))
        rows = [row('watch','Tornado Watch','Extreme',10),
                row('minor','Gale Warning','Minor',20),row('short','Gale Warning','Severe',1),
                row('long','Flood Warning','Severe',8),row('extreme','Tornado Warning','Extreme',1),
                row('advisory','Heat Advisory','Extreme',30)]
        self.assertEqual([r['id'] for r in sorted(rows,key=active_sort_key)],
                         ['extreme','long','short','minor','watch','advisory'])

    def test_batch_locations_are_deduplicated_paused_and_use_latest_expiration(self):
        first = alert(event='Gale Warning',area='North coast; South coast',expires=(self.now+timedelta(hours=1)).isoformat())
        last = alert(event='Gale Warning',area='South coast; Outer waters',expires=(self.now+timedelta(hours=5)).isoformat())
        text = batch_announcement([first,last])
        self.assertIn('Gale Warning for North coast; South coast; Outer waters.',text)
        self.assertEqual(text.count('South coast'),1)
        expected = (self.now+timedelta(hours=5)).astimezone().strftime('%I:%M %p').lstrip('0').replace(':00','')
        self.assertIn(expected,text)
        self.assertIn('local time',text)
        self.assertNotIn('Central Daylight Time',text)
        self.assertNotIn('United States',text)

    def test_long_location_lists_are_concise_and_do_not_hide_unknown_expirations(self):
        values = [alert(event='Gale Warning',area='Coastal sector '+str(i),expires='Unknown') for i in range(100)]
        text = batch_announcement(values)
        self.assertLess(len(text),650)
        self.assertIn('additional affected areas',text)
        self.assertIn('Expiration time unavailable',text)


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'),'GUI tests require a desktop display')
class AggregationGuiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.ui = StormwatchApp(Mock(interval=60),AlertHistory(Path(self.directory.name)/'history.db'))
        for event in ('Gale Warning','Flood Warning','Tornado Watch','Heat Advisory'):
            self.ui.choices[event].set(True)
        self.ui.profile.sound = self.ui.profile.desktop = False
        self.ui.profile.speech = True
        self.ui.profile.speech_events = None
        self.ui.speech_started_at = datetime.now(timezone.utc)-timedelta(seconds=10)
        self.ui.initialized = True
        self.ui.app.root.update()
        self.voice = patch.object(self.ui.speaker,'speak').start()
        self.addCleanup(patch.stopall)
        self.release = threading.Event()

    def tearDown(self):
        self.release.set()
        self.ui.close()
        self.ui.cleanup_thread.join(timeout=5)
        self.directory.cleanup()

    def pump(self,condition):
        deadline = time.monotonic()+6
        while not condition() and time.monotonic()<deadline:
            self.ui.app.root.update()
            time.sleep(.005)
        self.assertTrue(condition())

    def receive(self,items,wait_voice=True):
        self.ui.running = True
        self.ui.received(self.ui.generation,({a['id']:a for a in items},''))
        self.pump(lambda:not self.ui.busy)
        if wait_voice:
            self.pump(lambda:not self.ui.speech_busy and not self.ui.speech_pending)
        if self.ui.timer:
            self.ui.app.root.after_cancel(self.ui.timer)
            self.ui.timer = None

    def gale(self,i,**extra):
        now = datetime.now(timezone.utc)
        return alert(id='gale-'+str(i),event='Gale Warning',area='Coastal sector '+str(i),
                     sent=now.isoformat(),expires=(now+timedelta(hours=i+1)).isoformat(),**extra)

    def test_one_refresh_with_a_dozen_gales_is_one_report_with_independent_receipts(self):
        values = [self.gale(i) for i in range(12)]
        self.receive(values)
        self.voice.assert_called_once()
        text = self.voice.call_args.args[0]
        self.assertEqual(text.count('Gale Warning for'),1)
        for i in range(12):
            self.assertIn('Coastal sector '+str(i),text)
        self.assertIn('; ',text)
        rows = [r for r in self.ui.history.delivery_rows(limit=100) if r['channel']=='speech']
        self.assertEqual(len(rows),12)
        self.assertTrue(all(r['state']=='sent' and r['attempts']==1 for r in rows))
        self.receive(values)
        self.voice.assert_called_once()

    def test_aggregation_waits_for_every_processing_chunk_and_separates_types(self):
        values = [self.gale(i) for i in range(45)]
        values.append(alert(id='watch',event='Tornado Watch',area='Inland counties',sent=datetime.now(timezone.utc).isoformat()))
        self.receive(values)
        self.assertEqual(self.voice.call_count,2)
        spoken = [call.args[0] for call in self.voice.call_args_list]
        self.assertEqual(sum('Gale Warning for' in text for text in spoken),1)
        self.assertEqual(sum('Tornado Watch for' in text for text in spoken),1)
        self.assertIn('additional affected areas',next(t for t in spoken if t.startswith('Gale')))

    def test_failed_batch_retries_once_per_type_without_repeating_successful_members(self):
        values = [self.gale(i) for i in range(5)]
        self.voice.side_effect = RuntimeError('voice unavailable')
        self.receive(values)
        self.voice.assert_called_once()
        rows = [r for r in self.ui.history.delivery_rows() if r['channel']=='speech']
        self.assertEqual(len(rows),5)
        self.assertTrue(all(r['state']=='failed' and r['attempts']==1 for r in rows))
        self.voice.side_effect = None
        self.receive(values)
        self.assertEqual(self.voice.call_count,2)
        self.receive(values)
        self.assertEqual(self.voice.call_count,2)

    def test_cancellations_and_expirations_never_enter_spoken_batches(self):
        valid = self.gale(0)
        old = dict(self.gale(1),expires=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
        cancelled = dict(self.gale(2),message_type='Cancel')
        self.receive([valid,old,cancelled])
        self.voice.assert_called_once()
        text = self.voice.call_args.args[0]
        self.assertIn('Coastal sector 0',text)
        self.assertNotIn('Coastal sector 1',text)
        self.assertNotIn('Coastal sector 2',text)
        self.assertNotIn('Cancelled',text)
        self.assertNotIn('Expired',text)
        self.assertEqual(set(self.ui.snapshot),{valid['id']})

    def test_expiration_removes_polygons_and_cards_without_another_nws_refresh(self):
        self.ui.profile.speech = False
        self.ui.tabs.widget.select(self.ui.map.parent.widget)
        now = datetime.now(timezone.utc)
        polygon = dict(type='Polygon',coordinates=[[[-92,36],[-90,36],[-90,39],[-92,36]]])
        a = alert(id='short',expires=(now+timedelta(seconds=1.2)).isoformat(),
                  ends=(now+timedelta(hours=2)).isoformat(),geometry=polygon)
        self.receive([a])
        self.pump(lambda:bool(self.ui.map.items))
        self.pump(lambda:'short' not in self.ui.snapshot)
        self.ui.app.root.update()
        self.assertFalse(self.ui.cards.rows)
        self.assertFalse(self.ui.map.rows)
        self.assertFalse(self.ui.map.items)
        self.assertEqual(self.ui.history.get_alert('short')['status'],'Expired')
        self.assertGreater(self.ui.history.history_count(),1)
        self.ui.service.fetch_alerts.assert_not_called()

    def test_cancelled_display_is_cleaned_and_a_stale_snapshot_cannot_restore_it(self):
        self.ui.profile.speech = False
        a = self.gale(0)
        self.receive([a])
        self.ui.history.cancel_references(alert(message_type='Cancel',references=[{'identifier':a['id']}]))
        self.ui.app.root.after_cancel(self.ui.health_timer)
        self.ui.tick()
        self.assertFalse(self.ui.snapshot)
        self.assertFalse(self.ui.cards.rows)
        self.assertFalse(self.ui.map.rows)
        self.receive([a])
        self.assertFalse(self.ui.snapshot)
        self.assertEqual(self.ui.history.get_alert(a['id'])['status'],'Cancelled')
        self.voice.assert_not_called()

    def test_active_cards_use_requested_sort_order(self):
        self.ui.profile.speech = False
        now = datetime.now(timezone.utc)
        values = [alert(id='watch',event='Tornado Watch',severity='Extreme',expires=(now+timedelta(hours=8)).isoformat()),
                  alert(id='short',event='Gale Warning',severity='Severe',expires=(now+timedelta(hours=1)).isoformat()),
                  alert(id='long',event='Flood Warning',severity='Severe',expires=(now+timedelta(hours=4)).isoformat()),
                  alert(id='minor',event='Gale Warning',severity='Minor',expires=(now+timedelta(hours=6)).isoformat())]
        self.receive(values)
        self.assertEqual([row['id'] for row in self.ui.cards.rows],['long','short','minor','watch'])

    def test_a_hundred_same_type_alerts_wait_as_one_batch_not_a_hundred_reports(self):
        self.ui.speech_busy = True
        values = [self.gale(i) for i in range(100)]
        self.receive(values,wait_voice=False)
        self.assertEqual(len(self.ui.speech_pending),1)
        _,members = next(iter(self.ui.speech_pending.values()))
        self.assertEqual(len(members),100)
        self.voice.assert_not_called()
        self.ui.speech_busy = False
        self.ui.start_speech()
        self.pump(lambda:not self.ui.speech_busy and not self.ui.speech_pending)
        self.voice.assert_called_once()
        self.assertEqual(sum(r['state']=='sent' for r in self.ui.history.delivery_rows(limit=200)),100)

    def test_cancellation_stops_current_batch_and_requeues_only_remaining_active_members(self):
        entered = threading.Event()
        def speak(text,should_continue):
            if self.voice.call_count==1:
                entered.set()
                self.release.wait(3)
                if not should_continue():
                    raise SpeechCancelled('Batch changed')
        self.voice.side_effect = speak
        values = [self.gale(0),self.gale(1)]
        with patch.object(self.ui.speaker,'stop',side_effect=self.release.set) as stop:
            self.receive(values,wait_voice=False)
            self.pump(entered.is_set)
            cancel = alert(id='cancel',event='Gale Warning',message_type='Cancel',references=[{'identifier':values[0]['id']}])
            self.receive(values+[cancel])
            stop.assert_called()
        self.assertEqual(self.voice.call_count,2)
        second = self.voice.call_args_list[1].args[0]
        self.assertIn('Coastal sector 1',second)
        self.assertNotIn('Coastal sector 0',second)
        rows = {r['id']:r for r in self.ui.history.delivery_rows()}
        self.assertEqual(rows[values[1]['id']]['state'],'sent')
        self.assertNotEqual(rows[values[0]['id']]['state'],'sent')

    def test_scroll_content_is_clipped_below_event_section_heading(self):
        form = self.ui.filters
        self.assertEqual(form.body.widget.winfo_parent(),str(form.canvas))
        for fraction in (0,.2,.5,.9,1):
            form.canvas.yview_moveto(fraction)
            self.ui.app.root.update()
            at_title = self.ui.app.root.winfo_containing(form.widget.winfo_rootx()+20,form.widget.winfo_rooty()+5)
            self.assertEqual(at_title,form.widget)
        last = list(self.ui.choices.values())[-1].widget
        self.assertEqual(self.ui.app.root.winfo_containing(last.winfo_rootx()+8,last.winfo_rooty()+8),last)
