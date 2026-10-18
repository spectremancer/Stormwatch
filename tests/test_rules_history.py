import csv
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
from history_store import HistoryFilter
from locations import LocationProfile
from main import StormwatchApp
from test_dashboard import alert


class RuleTests(unittest.TestCase):
    def test_legacy_preferences_are_preserved(self):
        old = LocationProfile.from_json(json.dumps({'name':'Home','sound':False,'desktop':True}))
        self.assertFalse(old.allows('Tornado Warning','sound'))
        self.assertFalse(old.allows('Tornado Watch','sound'))
        self.assertTrue(old.allows('Tornado Watch','desktop'))

    def test_warning_sound_watch_desktop_rules(self):
        profile = LocationProfile(warning_sound=True,watch_sound=False,warning_desktop=False,watch_desktop=True)
        self.assertTrue(profile.allows('Tornado Warning','sound'))
        self.assertFalse(profile.allows('Tornado Watch','sound'))
        self.assertFalse(profile.allows('Tornado Warning','desktop'))
        self.assertTrue(profile.allows('Tornado Watch','desktop'))
        restored = LocationProfile.from_json(profile.to_json())
        self.assertFalse(restored.watch_sound)
        with self.assertRaises(ValueError):
            LocationProfile(watch_sound='yes').validate()


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)/'history.db'
        self.store = AlertHistory(self.path)
        self.home = LocationProfile(name='Home')
        self.store.save_profile(self.home)
        self.now = datetime(2026,10,16,12).astimezone(timezone.utc)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_filters_include_date_location_event_kind_and_delivery_outcome(self):
        a = alert(headline='Shelter instructions for Cook County')
        version,_,_ = self.store.observe(a, self.now, [self.home])
        self.store.schedule(a['id'],version,self.home.id,'desktop')
        self.store.receipt(a['id'],version,self.home.id,'desktop','Offline')
        self.store.observe(alert(id='flood',event='Flood Watch',headline='River rising'),self.now+timedelta(days=1),[])
        filters = HistoryFilter(text='shelter cook',location='Home',event='Tornado Warning',kind='New',
                                outcome='Failed',start='2026-10-16',end='2026-10-16')
        rows = self.store.search_history(filters)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['locations'],'Home')
        self.assertEqual(self.store.history_count(HistoryFilter(outcome='No notifications')),1)
        self.assertEqual(self.store.history_count(HistoryFilter(text='%')),0)
        self.assertEqual(self.store.history_count(HistoryFilter(location="' OR 1=1 --")),0)

    def test_lifecycle_location_snapshots_and_restart(self):
        a = alert()
        self.store.observe(a, locations=[self.home])
        self.store.observe(a, locations=[self.home])
        self.assertEqual(self.store.history_count(),1)
        self.home.name = 'Renamed Home'
        self.store.save_profile(self.home)
        self.store.observe(a, locations=[self.home])
        self.assertEqual(self.store.search_history()[0]['locations'],'Home')
        self.store.reconcile(set())
        self.assertEqual(self.store.search_history(HistoryFilter(kind='No longer active'))[0]['locations'],'Home')
        self.store.close()
        self.store = AlertHistory(self.path)
        self.assertEqual(self.store.history_count(),2)
        self.store.delete_profile(self.home.id)
        self.assertEqual(self.store.history_count(HistoryFilter(location='Home')),2)

    def test_tornado_search_matches_event_names_in_text_and_typed_event_filter(self):
        for identifier, event in (('warning','Tornado Warning'), ('watch','Tornado Watch'),
                                  ('flood','Flood Warning')):
            self.store.observe(alert(id=identifier,event=event,headline='Take action',
                                     description='',instruction=''),locations=[self.home])
        for filters in (HistoryFilter(text='TORNADO'), HistoryFilter(event='tornado'),
                        HistoryFilter(event='  ToRnAdO  ')):
            with self.subTest(filters=filters):
                self.assertEqual({r['id'] for r in self.store.search_history(filters)}, {'warning','watch'})
                self.assertEqual(self.store.history_count(filters),2)
        self.assertEqual([r['id'] for r in self.store.search_history(HistoryFilter(event='tornado warning'))],
                         ['warning'])
        target = Path(self.directory.name)/'tornado.csv'
        self.assertEqual(self.store.export_history(target,HistoryFilter(event='tornado')),2)
        with target.open(encoding='utf-8-sig',newline='') as source:
            self.assertEqual({r['alert_id'] for r in csv.DictReader(source)}, {'warning','watch'})

    def test_typed_event_search_treats_wildcards_and_sql_as_literal_text(self):
        self.store.observe(alert(),locations=[self.home])
        for query in ('%', '_', '\\', "' OR 1=1 --"):
            with self.subTest(query=query):
                self.assertEqual(self.store.history_count(HistoryFilter(event=query)),0)

    def test_export_includes_all_filtered_pages_and_quotes_external_text(self):
        for i in range(115):
            self.store.observe(alert(id=str(i),headline='=HYPERLINK("bad")',instruction='line one\nline two, quoted'),
                               locations=[self.home])
        self.assertEqual(len(self.store.search_history()),50)
        target = Path(self.directory.name)/'export.csv'
        self.assertEqual(self.store.export_history(target,HistoryFilter(location='Home')),115)
        with target.open(encoding='utf-8-sig',newline='') as source:
            rows = list(csv.DictReader(source))
        self.assertEqual(len(rows),115)
        self.assertEqual(len({r['alert_id'] for r in rows}),115)
        self.assertTrue(rows[0]['headline'].startswith("'="))
        self.assertEqual(rows[0]['instruction'],'line one\nline two, quoted')

    def test_export_cannot_overwrite_database(self):
        self.store.observe(alert())
        with self.assertRaises(ValueError):
            self.store.export_history(self.path)
        self.assertEqual(self.store.history_count(),1)

    def test_export_snapshot_is_consistent_while_monitoring_writes(self):
        versions = {}
        for key in ('one','two'):
            v,_,_ = self.store.observe(alert(id=key),locations=[self.home])
            versions[key] = v
            self.store.schedule(key,v,self.home.id,'desktop')
            self.store.receipt(key,v,self.home.id,'desktop','Offline')
        original_writer = csv.writer
        changed = False
        def factory(target):
            writer = original_writer(target)
            def write(row):
                nonlocal changed
                if not changed:
                    changed = True
                    self.store.receipt('one',versions['one'],self.home.id,'desktop')
                    v,_,_ = self.store.observe(alert(id='late'),locations=[self.home])
                    self.store.schedule('late',v,self.home.id,'desktop')
                    self.store.receipt('late',v,self.home.id,'desktop','Offline')
                return writer.writerow(row)
            return Mock(writerow=write)
        target = Path(self.directory.name)/'snapshot.csv'
        with patch('history_store.csv.writer',side_effect=factory):
            self.store.export_history(target,HistoryFilter(outcome='Failed'))
        with target.open(encoding='utf-8-sig',newline='') as source:
            rows = list(csv.DictReader(source))
        self.assertEqual({r['alert_id'] for r in rows},{'one','two'})
        self.assertTrue(all('desktop:failed' in r['channel_results'] for r in rows))

    def test_invalid_dates_are_rejected(self):
        for filters in (HistoryFilter(start='October 16'),HistoryFilter(start='2026-10-17',end='2026-10-16'),HistoryFilter(end='9999-12-31')):
            with self.assertRaises(ValueError):
                self.store.history_count(filters)

    def test_older_versions_are_imported_once_with_honest_time_basis(self):
        # Emulate a pre-history installation while keeping its original versions/receipts.
        a=alert()
        version,_,_ = self.store.observe(a, locations=[self.home])
        self.store.schedule(a['id'],version,self.home.id,'desktop')
        self.store.connection.execute('DELETE FROM history_locations')
        self.store.connection.execute('DELETE FROM history_events')
        self.store.connection.execute("DELETE FROM settings WHERE name='archive_initialized'")
        self.store.connection.commit()
        self.store.close()
        self.store=AlertHistory(self.path)
        rows=self.store.search_history()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['time_basis'],'Issued (imported)')
        self.assertEqual(rows[0]['locations'],'Home')
        self.store.close();self.store=AlertHistory(self.path)
        self.assertEqual(self.store.history_count(),1)


@unittest.skipUnless(os.environ.get('DISPLAY'),'GUI tests require DISPLAY')
class CombinedNotificationTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.path=Path(self.directory.name)/'live.db'
        self.service=Mock(interval=60)
        self.owner=StormwatchApp(self.service,AlertHistory(self.path))
        self.owner.app.root.update()
        self.owner.profile.name='Home'
        self.owner.history.save_profile(self.owner.profile)
        self.work=LocationProfile(name='Work')
        self.owner.history.save_profile(self.work)
        self.owner.refresh_profiles()

    def tearDown(self):
        self.owner.close();self.owner.cleanup_thread.join(timeout=5)
        self.directory.cleanup()

    def pump(self, condition):
        deadline=time.monotonic()+4
        while not condition() and time.monotonic()<deadline:
            self.owner.app.root.update();time.sleep(.01)
        self.assertTrue(condition())

    def receive(self,a=None):
        a=a or alert()
        self.owner.running=True
        self.owner.received(self.owner.generation,({a['id']:a},''))
        if self.owner.timer:
            self.owner.app.root.after_cancel(self.owner.timer);self.owner.timer=None
        if self.owner.delivery_future:
            self.owner.delivery_future.result(timeout=3)
            self.pump(lambda:not self.owner.delivery_busy)

    def test_overlaps_submit_once_with_both_names_and_receipts(self):
        self.receive()
        self.service.deliver_sound.assert_called_once()
        self.service.deliver_desktop.assert_called_once()
        self.assertEqual(self.service.deliver_desktop.call_args.args[2],'Home, Work')
        self.assertEqual(self.owner.history.delivery_count(),4)
        self.assertTrue(all(r['state']=='sent' for r in self.owner.history.delivery_rows()))
        self.assertEqual(self.owner.history.history_count(),1)
        self.assertEqual(set(self.owner.history.search_history()[0]['locations'].split(',')),{'Home','Work'})

    def test_history_panel_finds_tornado_watch_and_warning_by_typed_event(self):
        for identifier,event in (('warning','Tornado Warning'),('watch','Tornado Watch'),('flood','Flood Warning')):
            self.owner.history.observe(alert(id=identifier,event=event),locations=[self.owner.profile])
        panel = self.owner.history_panel
        panel.refresh()
        self.assertIn('Tornado Warning',panel.event.values)
        self.assertIn('Tornado Watch',panel.event.values)
        panel.event.set('ToRnAdO')
        panel.apply()
        self.assertEqual({r['id'] for r in panel.rows},{'warning','watch'})
        self.assertEqual(panel.event.get(),'ToRnAdO')
        self.assertEqual(panel.counter.get(),'1–2 of 2 changes')
        panel.clear()
        self.assertEqual(len(panel.rows),3)
        panel.text.set('TORNADO')
        panel.apply()
        self.assertEqual({r['id'] for r in panel.rows},{'warning','watch'})

    def test_rules_are_applied_before_grouping_and_do_not_hide_cards(self):
        home=next(p for p in self.owner.profiles if p.name=='Home')
        work=next(p for p in self.owner.profiles if p.name=='Work')
        home.warning_desktop=False
        work.warning_sound=False
        self.receive()
        self.service.deliver_sound.assert_called_once()
        self.assertEqual(self.service.deliver_desktop.call_args.args[2],'Work')
        self.assertEqual(len(self.owner.snapshot),1)
        self.assertEqual(self.owner.history.delivery_count(),2)

    def test_shared_retries_do_not_multiply_with_number_of_locations(self):
        self.service.deliver_desktop.side_effect=RuntimeError('Offline')
        for _ in range(4):self.receive()
        self.service.deliver_sound.assert_called_once()
        self.assertEqual(self.service.deliver_desktop.call_count,3)
        failures=[r for r in self.owner.history.delivery_rows() if r['channel']=='desktop']
        self.assertTrue(all(r['attempts']==3 for r in failures))
        self.service.deliver_desktop.side_effect=None
        self.owner.retry_delivery(failures[0])
        self.owner.delivery_future.result(timeout=3)
        self.pump(lambda:not self.owner.delivery_busy)
        self.assertEqual(self.service.deliver_desktop.call_count,4)
        self.service.deliver_sound.assert_called_once()
        self.assertTrue(all(r['state']=='sent' for r in self.owner.history.delivery_rows()))

    def test_late_overlapping_profile_does_not_repeat_an_already_submitted_channel(self):
        self.receive()
        family=LocationProfile(name='Family')
        self.owner.history.save_profile(family);self.owner.refresh_profiles()
        self.receive()
        self.service.deliver_sound.assert_called_once()
        self.service.deliver_desktop.assert_called_once()
        self.assertEqual(self.owner.history.delivery_count(),6)
        self.assertTrue(all(r['state']=='sent' for r in self.owner.history.delivery_rows()))

    def test_shared_submission_survives_restart(self):
        self.receive()
        self.owner.close();self.owner.cleanup_thread.join(timeout=5)
        self.owner=StormwatchApp(self.service,AlertHistory(self.path))
        family=LocationProfile(name='Family')
        self.owner.history.save_profile(family);self.owner.refresh_profiles()
        self.receive()
        self.service.deliver_sound.assert_called_once()
        self.service.deliver_desktop.assert_called_once()
        self.assertTrue(all(r['state']=='sent' for r in self.owner.history.delivery_rows()))

    def test_legacy_sent_receipt_suppresses_a_new_overlapping_notification(self):
        a=alert()
        v,_,_=self.owner.history.observe(a,locations=[self.owner.profile])
        home=next(p for p in self.owner.profiles if p.name=='Home')
        for channel in ('sound','desktop'):
            self.owner.history.schedule(a['id'],v,home.id,channel)
            self.owner.history.receipt(a['id'],v,home.id,channel)
        self.receive()
        self.service.deliver_sound.assert_not_called()
        self.service.deliver_desktop.assert_not_called()
        work_rows=[r for r in self.owner.history.delivery_rows() if r['location']['name']=='Work']
        self.assertTrue(all(r['state']=='sent' for r in work_rows))
        self.assertTrue(all('Home' in r['reason'] for r in work_rows))

    def test_history_is_visible_at_minimum_window_size(self):
        self.receive()
        self.owner.app.root.geometry('1000x760')
        self.owner.tabs.widget.select(self.owner.history_panel.table.parent.widget)
        self.owner.app.root.update()
        self.assertGreaterEqual(self.owner.history_panel.table.tree.winfo_height(),80)

    def test_watch_rules_and_history_remain_after_feed_is_cleared(self):
        for p in self.owner.profiles:
            p.watch_sound=False
        self.owner.initialized=True
        self.receive(alert(event='Tornado Watch'))
        self.service.deliver_sound.assert_not_called()
        self.service.deliver_desktop.assert_called_once()
        self.owner.clear_feed()
        self.assertEqual(self.owner.history.history_count(),1)
        self.owner.history_panel.text.set('Cook')
        self.owner.history_panel.apply()
        self.assertEqual(len(self.owner.history_panel.rows),1)
        self.owner.history_panel.start.set('wrong')
        self.owner.history_panel.apply()
        self.assertIn('YYYY-MM-DD',self.owner.history_panel.message.get())

    def test_gui_export_uses_all_applied_matches(self):
        self.receive()
        target=Path(self.directory.name)/'selected.csv'
        panel=self.owner.history_panel
        panel.text.set('Cook');panel.apply()
        with patch('history_panel.filedialog.asksaveasfilename',return_value=str(target)):
            panel.export()
        self.pump(lambda:not panel.exporting)
        with target.open(encoding='utf-8-sig',newline='') as source:
            rows=list(csv.DictReader(source))
        self.assertEqual(len(rows),1)
        self.assertIn('Exported 1',panel.message.get())

    def test_wizard_rules_persist(self):
        self.service.resolve_location.return_value=['ILC031']
        self.owner.add_location()
        wizard=self.owner.location_wizard
        from place_search import search_places
        wizard.searched(0,search_places('60601'))
        wizard.results.tree.selection_set('0');wizard.selection_changed();wizard.next();wizard.next()
        wizard.form.set({'name':'Family','warning_sound':True,'watch_sound':False,'warning_desktop':False,'watch_desktop':True})
        wizard.save();self.pump(lambda:wizard.window._closed)
        family=next(p for p in self.owner.profiles if p.name=='Family')
        self.assertTrue(family.allows('Tornado Warning','sound'))
        self.assertFalse(family.allows('Tornado Watch','sound'))
        self.assertTrue(family.allows('Tornado Watch','desktop'))
