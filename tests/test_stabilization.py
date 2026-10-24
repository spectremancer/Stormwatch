"""Regression coverage for the stabilization release's concurrency and data guarantees."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from alert_history import AlertHistory
from archive_analysis import analyze_archive, coverage_text
from history_store import HistoryFilter
from monitoring_runtime import connection_health
from single_instance import InstanceLock
from storage_tools import backup_database, stage_restore, apply_pending_restore, prune_archive, validate_backup
from test_dashboard import alert


class StorageAndAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)/'history.sqlite3'
        self.store = AlertHistory(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_backup_restores_settings_and_receipts_and_keeps_pre_restore_copy(self):
        profile = self.store.profiles()
        from locations import LocationProfile
        profile = LocationProfile(name='Home')
        self.store.save_profile(profile)
        a=alert()
        version,_,_=self.store.observe(a)
        self.store.schedule(a['id'],version,profile.id,'sound')
        self.store.receipt(a['id'],version,profile.id,'sound')
        backup = Path(self.directory.name)/'backup.sqlite3'
        backup_database(self.path,backup)
        self.store.save_setting('after_backup',True)
        stage_restore(self.path,backup)
        self.assertTrue(self.store.setting('after_backup',False))
        self.store.close()
        apply_pending_restore(self.path)
        self.store = AlertHistory(self.path)
        self.assertFalse(self.store.setting('after_backup',False))
        self.assertEqual(self.store.delivery(a['id'],version,profile.id,'sound')['state'],'sent')
        self.assertTrue(self.path.with_suffix('.before-restore.sqlite3').exists())
        self.assertFalse(self.path.with_suffix('.restore.sqlite3').exists())

    def test_valid_staged_restore_can_recover_a_corrupt_database(self):
        self.store.observe(alert(id='preserved'))
        backup=Path(self.directory.name)/'valid.sqlite3'
        backup_database(self.path,backup)
        stage_restore(self.path,backup)
        self.store.close()
        self.path.write_bytes(b'corrupt database bytes')
        apply_pending_restore(self.path)
        self.store=AlertHistory(self.path)
        self.assertIsNotNone(self.store.get_alert('preserved'))
        self.assertEqual(self.path.with_suffix('.before-restore.corrupt.sqlite3').read_bytes(),b'corrupt database bytes')

    def test_bad_restore_and_live_backup_target_are_rejected(self):
        invalid=Path(self.directory.name)/'not-a-database.sqlite3'
        invalid.write_text('invalid')
        with self.assertRaises(sqlite3.DatabaseError):
            stage_restore(self.path,invalid)
        with self.assertRaises(ValueError):
            backup_database(self.path,self.path)
        self.assertFalse(self.path.with_suffix('.restore.sqlite3').exists())

    def test_retention_keeps_deduplication_and_active_data(self):
        old=alert(id='ended',expires='2020-01-01T00:00:00Z')
        version,_,_=self.store.observe(old)
        self.store.observe(alert(id='active'))
        self.store.connection.execute("UPDATE history_events SET recorded_at='2020-01-01T00:00:00+00:00'")
        self.store.connection.commit()
        self.assertEqual(prune_archive(self.path,30),1)
        self.assertEqual(self.store.history_count(),1)
        self.assertEqual(self.store.get_alert('ended')['version'],version)
        self.assertEqual(self.store.observe(old)[1],'Expired')
        self.assertEqual(self.store.search_history(HistoryFilter(text='Cook'))[0]['id'],'active')

    def test_independent_reader_does_not_wait_for_uncommitted_import(self):
        self.store.observe(alert(id='committed'))
        acquired,release = threading.Event(),threading.Event()
        def importer():
            with self.store.transaction():
                self.store.observe(alert(id='uncommitted'))
                acquired.set()
                release.wait(3)
        worker=threading.Thread(target=importer)
        worker.start()
        self.assertTrue(acquired.wait(2))
        try:
            start=time.monotonic()
            with self.store.read_snapshot() as reader:
                self.assertEqual(reader.history_count(),1)
            self.assertLess(time.monotonic()-start,.5)
        finally:
            release.set();worker.join(3)
        self.assertEqual(self.store.history_count(),2)

    def test_search_keeps_literal_substring_semantics_and_fts_delete_consistency(self):
        self.store.observe(alert(headline='Odd_name 100% tornado warning'))
        for term in ('ornado','Odd_name','100%','tornado warning','Co'):
            self.assertEqual(self.store.history_count(HistoryFilter(text=term)),1,term)
        self.assertEqual(self.store.history_count(HistoryFilter(text='missing')),0)

    def test_coverage_distinguishes_versions_counties_and_message_duration(self):
        now=datetime.now(timezone.utc)
        a=alert(sent=now.isoformat(),expires=(now+timedelta(hours=1)).isoformat(),geocode={'UGC':['ILC031']})
        self.store.observe(a)
        self.store.observe(dict(a,expires=(now+timedelta(hours=2)).isoformat(),message_type='Update'))
        result=analyze_archive(self.store)
        self.assertEqual(result['counties'],[('ILC031',1)])
        self.assertEqual(result['duration_count'],1)
        self.assertEqual(result['mean_duration'],2)
        self.assertEqual(sum(result['sources'].values()),2)
        self.assertIn('not a climatological dataset',coverage_text(result))

    def test_single_instance_lock_is_released_cleanly(self):
        first=InstanceLock(Path(self.directory.name))
        try:
            with self.assertRaises(RuntimeError):InstanceLock(Path(self.directory.name))
        finally:first.close()
        second=InstanceLock(Path(self.directory.name));second.close()

    def test_health_distinguishes_running_degraded_stale_and_paused(self):
        now=datetime.now(timezone.utc)
        self.assertEqual(connection_health(True,True,None,60).state,'CONNECTING')
        self.assertEqual(connection_health(True,False,now,60).state,'LIVE')
        self.assertEqual(connection_health(True,False,now,60,coverage='missing').state,'DEGRADED')
        self.assertEqual(connection_health(True,False,now,60,error='offline').state,'STALE')
        self.assertEqual(connection_health(False,False,now,60).state,'PAUSED')


@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'Requires a desktop')
class StabilizationGuiTests(unittest.TestCase):
    def setUp(self):
        from main import StormwatchApp
        self.directory=tempfile.TemporaryDirectory()
        self.service=Mock(interval=60)
        self.ui=StormwatchApp(self.service,AlertHistory(Path(self.directory.name)/'history.db'))
        self.ui.app.root.update()

    def tearDown(self):
        self.ui.close();self.ui.cleanup_thread.join(10)
        self.assertFalse(self.ui.cleanup_thread.is_alive())
        self.directory.cleanup()

    def pump(self,condition):
        limit=time.monotonic()+6
        while not condition() and time.monotonic()<limit:
            self.ui.app.root.update();time.sleep(.001)
        self.assertTrue(condition())

    def test_fetch_returns_alerts_without_waiting_for_boundary_enrichment(self):
        self.service.fetch_alerts.return_value=[{}]
        self.service.fetch_cancellations.return_value=[]
        self.service.parse_alert.return_value=alert()
        result=self.ui.fetch()
        self.assertEqual(len(result[0]),1)
        self.service.enrich_boundaries.assert_not_called()
        self.assertTrue(self.ui.sound_lock.acquire(blocking=False))
        self.ui.sound_lock.release()

    def test_gui_yields_and_ingestion_resumes_after_atomic_import_lock(self):
        acquired,release=threading.Event(),threading.Event()
        def hold():
            with self.ui.history.transaction():
                acquired.set();release.wait(3)
        worker=threading.Thread(target=hold);worker.start()
        self.assertTrue(acquired.wait(2))
        try:
            self.ui.running=True
            self.ui.profile.sound=self.ui.profile.desktop=False
            pulse=[]
            self.ui.app.after(1,lambda:pulse.append(True))
            self.ui.received(self.ui.generation,({'one':alert(id='one')},''))
            self.pump(lambda:bool(pulse))
            self.assertEqual(self.ui.count,0)
        finally:release.set();worker.join(3)
        self.pump(lambda:self.ui.count==1 and not self.ui.busy)

    def test_history_coalesces_newer_filters_and_does_not_refresh_while_hidden(self):
        from gui_support import wait_view
        self.ui.history.observe(alert(id='tornado'))
        self.ui.history.observe(alert(id='flood',event='Flood Warning'))
        panel=self.ui.history_panel
        panel.text.set('tornado');panel.apply()
        panel.text.set('flood');panel.apply()
        wait_view(self.ui,panel,False)
        self.assertEqual([row['id'] for row in panel.rows],['flood'])
        with patch.object(panel,'refresh') as refresh:
            self.ui.commands.show_tab('Active Alerts')
            self.ui.refresh_records()
            refresh.assert_not_called()

    def test_notification_center_persists_rules_and_previews_channel_eligibility(self):
        from workspace_tools import NotificationCenter
        center=NotificationCenter(self.ui)
        center.preset('sound',{'Tornado Warning'})
        center.preview_event.set('Hurricane Warning')
        center.preview()
        self.assertIn('Sound: Disabled',center.report.get())
        center.save()
        saved=self.ui.history.profiles()[0]
        self.assertEqual(saved.sound_events,['Tornado Warning'])
        self.assertTrue(saved.desktop)

    def test_collapsible_workspace_filter_presets_card_view_and_map_context(self):
        self.ui.event_search.set('tornado')
        self.ui.app.root.update()
        self.assertTrue(self.ui.choices['Tornado Warning'].widget.winfo_ismapped())
        self.assertFalse(self.ui.choices['Hurricane Warning'].widget.winfo_ismapped())
        self.ui.apply_event_preset('Winter')
        self.assertIn('Winter Storm Warning',self.ui.selected_events())
        self.assertNotIn('Tornado Warning',self.ui.selected_events())
        self.ui.toggle_sidebar()
        self.assertFalse(self.ui.sidebar_visible)
        self.ui.toggle_sidebar()
        self.assertTrue(self.ui.sidebar_visible)
        self.ui.set_card_view(True)
        self.assertTrue(self.ui.history.setting('compact_cards',False))
        from map_context import read_layer
        self.assertTrue(read_layer('states'))
        self.assertGreater(len(read_layer('counties')),3000)

    def test_small_snapshot_invalidates_older_background_view_and_expiry_stays_local(self):
        acquired,release=threading.Event(),threading.Event()
        self.ui.active_query.request(lambda:(release.wait(3),[dict(id='old',alert=alert(id='old'),locations=[])])[1],
                                     self.ui.apply_active_rows,lambda error:None)
        self.ui.render_active()  # Empty synchronous snapshot invalidates that result.
        release.set()
        self.pump(lambda:self.ui.active_query.future is None)
        self.assertFalse(self.ui.snapshot)
        a=alert(id='expired-local',expires=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
        self.ui.cards.render([dict(id=a['id'],alert=a,locations=[])])
        self.ui.snapshot={a['id']:a}
        release.clear()
        def hold():
            with self.ui.history.transaction():
                acquired.set();release.wait(3)
        worker=threading.Thread(target=hold);worker.start();self.assertTrue(acquired.wait(2))
        try:
            self.ui.app.root.after_cancel(self.ui.health_timer)
            self.ui.tick()
            self.assertFalse(self.ui.snapshot)
            self.assertFalse(self.ui.map.rows)
        finally:release.set();worker.join(3)

    def test_small_workspace_keeps_all_views_accessible_at_large_font_size(self):
        self.ui.commands.set_text_size(14)
        self.ui.app.root.geometry('800x560')
        if not self.ui.sidebar_visible:self.ui.toggle_sidebar()
        self.ui.app.root.update()
        self.assertTrue(self.ui.tabs.switcher.widget.winfo_ismapped())
        self.ui.tabs.switcher.set('History')
        self.ui.tabs.switcher.widget.event_generate('<<ComboboxSelected>>')
        self.ui.app.root.update()
        self.assertEqual(self.ui.tabs.widget.tab(self.ui.tabs.widget.select(),'text'),'History')
        self.ui.commands.show_tab('Map')
        self.ui.app.root.update()
        self.assertEqual(self.ui.tabs.switcher.get(),'Map')

    def test_storage_failure_during_expiration_does_not_stop_local_cleanup(self):
        a=alert(id='expiring',expires=(datetime.now(timezone.utc)+timedelta(milliseconds=10)).isoformat())
        self.ui.history.observe(a)
        self.ui.render_active()
        self.ui.history.connection.execute("CREATE TRIGGER expire_disk_full BEFORE UPDATE ON alerts BEGIN SELECT RAISE(ABORT,'disk full'); END")
        self.ui.history.connection.commit()
        time.sleep(.03)
        self.ui.app.root.after_cancel(self.ui.health_timer)
        self.ui.tick()
        self.assertFalse(self.ui.snapshot)
        self.assertIn('Storage unavailable',self.ui.status.get())
        self.assertIn(self.ui.health_timer,self.ui.app.root.tk.call('after','info'))

    def test_duplicate_outlines_are_drawn_once_without_losing_message_selection(self):
        geometry={'type':'Polygon','coordinates':[[[-100,35],[-99,35],[-99,36],[-100,35]]]}
        rows=[dict(id=str(i),version=str(i),alert=alert(id=str(i),geometry=geometry)) for i in range(20)]
        self.ui.commands.show_tab('Map')
        self.ui.app.root.update()
        self.ui.map.render(rows,self.ui.profiles)
        self.ui.app.root.update()
        self.assertEqual(len(self.ui.map.plan),1)
        self.assertEqual(len(self.ui.map.items),1)
        self.assertEqual(len(next(iter(self.ui.map.overlapping.values()))),20)
        self.assertEqual(geometry['coordinates'][0],[[-100,35],[-99,35],[-99,36],[-100,35]])
        x,y=self.ui.map.project(-100,35)
        with patch('map_picker.overlapping_alerts') as picker:
            self.ui.map.start_drag(Mock(x=x,y=y))
            self.ui.map.release(Mock(x=x,y=y))
            picker.assert_called_once()
            self.assertEqual(len(picker.call_args.args[1]),20)

    def test_pause_stops_immediately_during_an_archive_transaction(self):
        acquired,release=threading.Event(),threading.Event()
        def hold():
            with self.ui.history.transaction():
                acquired.set();release.wait(3)
        worker=threading.Thread(target=hold);worker.start();self.assertTrue(acquired.wait(2))
        self.ui.running=True
        try:
            with patch.object(self.ui.speaker,'stop') as stop:
                self.ui.toggle_monitoring()
                self.assertFalse(self.ui.running)
                stop.assert_called_once()
        finally:release.set();worker.join(3)

    def test_projection_uses_cached_view_dimensions_for_each_vertex(self):
        self.ui.map.resized(Mock(width=800,height=600))
        self.ui.map.center=(-100,35)
        self.ui.map.scale=10
        with patch.object(self.ui.map.canvas,'winfo_width',side_effect=AssertionError('Per-vertex Tk lookup')):
            for _ in range(1000):
                self.assertEqual(self.ui.map.project(-100,35),(400,300))

    def test_exit_preserves_event_edits_deferred_by_an_import(self):
        acquired,release=threading.Event(),threading.Event()
        def hold():
            with self.ui.history.transaction():
                acquired.set();release.wait(3)
        worker=threading.Thread(target=hold);worker.start();self.assertTrue(acquired.wait(2))
        path=self.ui.history.path
        try:
            self.ui.choices['Tornado Watch'].set(False)
            self.ui.update_selection()
            self.assertIn('update_selection',self.ui._store_waiters)
            self.ui.close()
        finally:release.set();worker.join(3)
        self.ui.cleanup_thread.join(5)
        self.assertFalse(self.ui.cleanup_thread.is_alive())
        reopened=AlertHistory(path)
        try:self.assertNotIn('Tornado Watch',reopened.profiles()[0].events)
        finally:reopened.close()

    def test_explicit_notification_save_and_event_edits_survive_exit_during_import(self):
        from workspace_tools import NotificationCenter
        center=NotificationCenter(self.ui)
        center.preset('sound',{'Tornado Warning'})
        acquired,release=threading.Event(),threading.Event()
        def hold():
            with self.ui.history.transaction():
                acquired.set();release.wait(3)
        worker=threading.Thread(target=hold);worker.start();self.assertTrue(acquired.wait(2))
        path=self.ui.history.path
        try:
            center.save()
            self.ui.choices['Tornado Watch'].set(False)
            self.ui.update_selection()
            self.ui.close()
        finally:release.set();worker.join(3)
        self.ui.cleanup_thread.join(8)
        self.assertFalse(self.ui.cleanup_thread.is_alive())
        reopened=AlertHistory(path)
        try:
            profile=reopened.profiles()[0]
            self.assertEqual(profile.sound_events,['Tornado Warning'])
            self.assertNotIn('Tornado Watch',profile.events)
        finally:reopened.close()

    def test_overlap_picker_search_opens_the_selected_message(self):
        from map_picker import overlapping_alerts,PickerTable
        from TkFlow import Button,TextInput
        messages=[alert(id='one'),alert(id='two',event='Hurricane Warning')]
        opened=Mock()
        window=overlapping_alerts(self.ui.app,messages,opened)
        field=next(child for child in window._children if isinstance(child,TextInput))
        table=next(child for child in window._children if isinstance(child,PickerTable))
        field.set('hurricane')
        self.assertEqual(table.tree.get_children(),('1',))
        next(child for child in window._children if isinstance(child,Button) and child.widget.cget('text')=='View selected alert').invoke()
        opened.assert_called_once_with(messages[1])
        window.close()

    def test_unchanged_visible_archive_views_are_not_rebuilt_on_every_poll(self):
        self.ui.commands.show_tab('History')
        self.ui.refresh_records()
        with patch.object(self.ui.history_panel,'refresh') as refresh:
            self.ui.refresh_records()
            refresh.assert_not_called()
            self.ui.history.observe(alert(id='new-data'))
            self.ui.refresh_records()
            refresh.assert_called_once()

    def test_reserved_workers_run_when_background_pool_is_saturated(self):
        release=threading.Event()
        try:
            futures=[self.ui.app.run_in_thread(release.wait,3) for _ in range(4)]
            urgent=self.ui.app.run_in_thread(lambda:'urgent',critical=True)
            self.assertEqual(urgent.result(timeout=1),'urgent')
        finally:
            release.set()
            for future in futures:future.result(3)
    def test_provider_retry_after_and_disk_failure_keep_current_data(self):
        import requests
        response=Mock(headers={'Retry-After':'180'})
        self.ui.running=True
        self.ui.failed(self.ui.generation,requests.HTTPError('limited',response=response))
        remaining=(self.ui.next_refresh-datetime.now(timezone.utc)).total_seconds()
        self.assertGreater(remaining,178)
        self.ui.history.observe(alert(id='previous'))
        self.ui.history.connection.execute("CREATE TRIGGER simulate_disk_full BEFORE INSERT ON alerts WHEN NEW.id='new' BEGIN SELECT RAISE(ABORT,'database or disk is full'); END")
        self.ui.history.connection.commit()
        self.ui.received(self.ui.generation,({'new':alert(id='new')},''))
        self.assertIn('Could not save alert history',self.ui.status.get())
        self.assertEqual(self.ui.history.get_alert('previous')['status'],'Active')
        self.assertIsNone(self.ui.history.get_alert('new'))


class ProviderRegressionTests(unittest.TestCase):
    def test_conditional_nws_fetch_reuses_only_a_valid_cached_response(self):
        from WeatherService import WeatherService
        service=WeatherService.__new__(WeatherService)
        service.session=Mock()
        first=Mock(status_code=200,headers={'ETag':'"revision-one"'})
        first.json.return_value={'features':[{'id':'one'}]}
        unchanged=Mock(status_code=304)
        service.session.get.side_effect=[first,unchanged]
        one=service.fetch_alerts()
        one[0]['id']='changed by caller'
        self.assertEqual(service.fetch_alerts(),[{'id':'one'}])
        self.assertEqual(service.session.get.call_args.kwargs['headers'],{'If-None-Match':'"revision-one"'})
        unchanged.json.assert_not_called()

    def test_large_radar_view_loads_bounded_images_for_the_original_extent(self):
        import json
        from PIL import Image
        from radar import RadarService, Viewport
        service=RadarService()
        original=Viewport(3000,1600,-98,38,30)
        metadata=json.dumps({'host':'https://tilecache.rainviewer.com'}).encode()
        with patch.object(service,'_fetch',return_value=metadata),patch('radar.parse_frames',return_value=[(1,'/v2/radar/sample')]),\
             patch.object(service,'_tile',return_value=Image.new('RGBA',(256,256),(0,0,0,0))):
            returned,frames=service.load(original)
        self.assertEqual(returned,original)
        self.assertEqual(len(frames),1)
        self.assertLessEqual(frames[0][1].width,1800)
        self.assertLessEqual(frames[0][1].height,1200)

    def test_spoken_reports_use_profile_budget_and_differing_expiration_range(self):
        from locations import LocationProfile
        from speech import batch_announcement
        now=datetime.now(timezone.utc)
        samples=[alert(id=str(i),area='County '+str(i),expires=(now+timedelta(hours=i+1)).isoformat()) for i in range(8)]
        text=batch_announcement(samples,[LocationProfile(speech_max_areas=4,speech_max_chars=180)])
        self.assertIn('Expirations range from',text)
        self.assertIn('4 additional affected areas',text)
        self.assertNotIn('County 4',text)
