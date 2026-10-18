"""NWS archive contracts, atomic history isolation, and optional GUI workflow."""
import csv
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

import requests

from alert_history import AlertHistory
from historical_alerts import ArchiveQuery, DownloadCancelled, download_recent
from history_store import HistoryFilter
from main import StormwatchApp
from WeatherService import WeatherService


def feature(identifier='old-tornado', event='Tornado Warning', sent=None, **extra):
    sent = sent or (datetime.now(timezone.utc)-timedelta(hours=12)).isoformat()
    props = dict(id=identifier,event=event,status='Actual',sent=sent,
                 expires=sent,areaDesc='Oklahoma',headline='Archived weather alert',
                 web='https://www.weather.gov/',messageType='Alert')
    props.update(extra)
    return dict(id=identifier,type='Feature',properties=props,geometry=None)


def parse(value):
    return WeatherService.parse_alert(None,value)


def response(data, status=200):
    reply = MagicMock(status_code=status)
    reply.__enter__.return_value = reply
    reply.json.return_value = data
    return reply


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = AlertHistory(Path(self.directory.name)/'alerts.db')
        self.now = datetime.now(timezone.utc)
        today = self.now.astimezone().date()
        self.query = ArchiveQuery(str(today-timedelta(days=1)),str(today),'OK','Tornado Warning,Tornado Watch')
        self.session = MagicMock()

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def download(self, **kwargs):
        return download_recent(self.query,self.store,parse,session=self.session,now=self.now,**kwargs)

    def test_documented_request_pagination_sources_export_and_duplicate_import(self):
        older = feature('watch','Tornado Watch',sent=(self.now-timedelta(hours=18)).isoformat())
        newer = feature('warning',sent=(self.now-timedelta(hours=4)).isoformat())
        second_url = 'https://api.weather.gov/alerts?cursor=next'
        self.session.get.side_effect = [response(dict(features=[newer],pagination=dict(next=second_url))),
                                       response(dict(features=[older]))]
        result = self.download()
        self.assertEqual(result,dict(received=2,imported=2,duplicates=0,skipped=0))
        first, second = self.session.get.call_args_list
        self.assertEqual(first.args,('https://api.weather.gov/alerts',))
        self.assertEqual(first.kwargs['params']['event'],'Tornado Warning,Tornado Watch')
        self.assertEqual(first.kwargs['params']['area'],'OK')
        self.assertEqual(first.kwargs['params']['status'],'actual')
        self.assertFalse(first.kwargs['allow_redirects'])
        self.assertEqual(second.args,(second_url,))
        self.assertIsNone(second.kwargs['params'])
        rows = self.store.search_history(HistoryFilter(event='tornado'))
        self.assertEqual([r['id'] for r in rows],['warning','watch'])
        self.assertTrue(all(r['source']=='NWS API archive' for r in rows))
        self.assertTrue(all(r['time_basis']=='Issued (NWS archive)' for r in rows))
        self.assertTrue(all(r['locations']=='NWS archive · OK' for r in rows))
        self.session.get.side_effect = None
        self.session.get.return_value = response(dict(features=[newer,older]))
        self.assertEqual(self.download()['duplicates'],2)
        self.assertEqual(self.store.history_count(),2)
        target = Path(self.directory.name)/'archive.csv'
        self.assertEqual(self.store.export_history(target,HistoryFilter(event='tornado')),2)
        with target.open(encoding='utf-8-sig',newline='') as source:
            exported = list(csv.DictReader(source))
        self.assertEqual({r['source'] for r in exported},{'NWS API archive'})
        self.store.close()
        self.store = AlertHistory(self.store.path)
        self.assertEqual(self.store.history_count(),2)
        self.assertEqual(self.store.search_history()[0]['source'],'NWS API archive')

    def test_import_never_mutates_live_state_or_receipts_and_does_not_suppress_later_live_alert(self):
        value = feature(expires=(self.now+timedelta(days=1)).isoformat())
        self.session.get.return_value = response(dict(features=[value]))
        self.download()
        for table in ('alerts','versions','processed_alerts','deliveries','channel_submissions','notification_decisions'):
            self.assertEqual(self.store.connection.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)
        alert = parse(value)
        version,kind,_ = self.store.observe(alert)
        self.assertEqual(kind,'New')
        self.assertFalse(self.store.displayed(alert['id'],version))
        self.assertEqual(len(self.store.rows(active_only=True)),1)

    def test_existing_local_versions_are_preserved(self):
        value = feature()
        self.store.observe(parse(value))
        self.session.get.return_value = response(dict(features=[value]))
        self.assertEqual(self.download()['duplicates'],1)
        self.assertEqual(self.store.history_count(),1)
        self.assertEqual(self.store.search_history()[0]['source'],'Stormwatch')

    def test_all_us_omits_area_filter_and_keeps_nationwide_source_label(self):
        query = ArchiveQuery(self.query.start,self.query.end,'US',self.query.events)
        self.session.get.return_value = response(dict(features=[feature()]))
        result = download_recent(query,self.store,parse,session=self.session,now=self.now)
        self.assertEqual(result['imported'],1)
        self.assertNotIn('area',self.session.get.call_args.kwargs['params'])
        self.assertEqual(self.session.get.call_args.kwargs['params']['event'],self.query.events)
        self.assertEqual(self.store.search_history()[0]['locations'],'NWS archive · US')

    def test_existing_history_schema_migrates_without_losing_records(self):
        self.store.observe(parse(feature()))
        self.store.connection.execute('ALTER TABLE history_events DROP COLUMN source')
        self.store.connection.commit()
        self.store.close()
        self.store = AlertHistory(self.store.path)
        self.assertEqual(self.store.history_count(),1)
        self.assertEqual(self.store.search_history()[0]['source'],'Stormwatch')

    def test_old_future_invalid_dates_and_missing_state_are_rejected_before_http(self):
        today = self.now.astimezone().date()
        for query in (ArchiveQuery('2020-01-01',str(today),'OK'),
                      ArchiveQuery(str(today),str(today+timedelta(days=1)),'OK'),
                      ArchiveQuery(str(today),str(today),'Choose state'),
                      ArchiveQuery('bad',str(today),'OK'),
                      ArchiveQuery(str(today),str(today-timedelta(days=1)),'OK'),
                      ArchiveQuery(str(today),str(today),'OK',"Tornado Warning&status=test")):
            with self.subTest(query=query),self.assertRaises(ValueError):
                download_recent(query,self.store,parse,session=self.session,now=self.now)
        self.session.get.assert_not_called()
        earliest = ArchiveQuery(str((self.now-timedelta(days=7)).astimezone().date()),str(today),'OK')
        self.assertEqual(datetime.fromisoformat(earliest.parameters(self.now)['start']),self.now-timedelta(days=7))

    def test_cancel_mid_download_and_bad_second_page_keep_no_partial_history(self):
        cancel = threading.Event()
        self.session.get.return_value = response(dict(features=[feature()],pagination=dict(next='https://api.weather.gov/alerts?cursor=2')))
        with self.assertRaises(DownloadCancelled):
            self.download(cancel=cancel,progress=lambda _:cancel.set())
        self.assertEqual(self.store.history_count(),0)
        self.session.get.side_effect = [response(dict(features=[feature()],pagination=dict(next='https://api.weather.gov/alerts?cursor=2'))),
                                       requests.Timeout('NWS timed out')]
        with self.assertRaises(requests.Timeout):
            self.download()
        self.assertEqual(self.store.history_count(),0)

    def test_untrusted_cycles_redirects_invalid_json_and_page_budget_fail_without_import(self):
        for next_url in ('https://evil.example/alerts','http://api.weather.gov/alerts',
                         'https://api.weather.gov/other','https://api.weather.gov/alerts'):
            with self.subTest(next_url=next_url):
                self.session.get.return_value = response(dict(features=[feature()],pagination=dict(next=next_url)))
                with self.assertRaises(ValueError):
                    self.download()
                self.assertEqual(self.store.history_count(),0)
        for value in (dict(features=None),dict(features=[None]),[],dict(features=[],pagination=['bad'])):
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.session.get.return_value = response(value)
                self.download()
        self.session.get.return_value = response({},status=302)
        with self.assertRaises(ValueError):
            self.download()
        self.session.get.side_effect = [response(dict(features=[feature()],pagination=dict(next=f'https://api.weather.gov/alerts?cursor={i}'))) for i in range(10)]
        with self.assertRaisesRegex(ValueError,'5,000'):
            self.download()
        self.assertEqual(self.store.history_count(),0)

    def test_test_messages_and_unsupported_events_are_skipped_and_update_kind_is_honest(self):
        self.session.get.return_value = response(dict(features=[feature(status='Test'),feature(event='Administrative Message'),
            feature('update',messageType='Update'),feature('cancel',messageType='Cancel')]))
        result = self.download()
        self.assertEqual(result['skipped'],2)
        self.assertEqual({r['kind'] for r in self.store.search_history()},{'Updated','Cancelled'})

    def test_invalid_issue_time_and_cancellation_roll_back_the_whole_import(self):
        valid = parse(feature())
        bad = dict(valid,id='bad',sent='Unknown')
        with self.assertRaises(ValueError):
            self.store.import_archive([valid,bad],'OK',threading.Event())
        self.assertEqual(self.store.history_count(),0)
        cancel = threading.Event()
        original = self.store._archive_event
        def archive(*args,**kwargs):
            result = original(*args,**kwargs)
            cancel.set()
            return result
        with patch.object(self.store,'_archive_event',side_effect=archive),self.assertRaises(DownloadCancelled):
            self.store.import_archive([valid],'OK',cancel)
        self.assertEqual(self.store.history_count(),0)


@unittest.skipUnless(os.environ.get('DISPLAY'),'GUI tests require DISPLAY')
class DownloadGuiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.service = Mock(interval=60)
        self.service.parse_alert.side_effect = parse
        self.ui = StormwatchApp(self.service,AlertHistory(Path(self.directory.name)/'alerts.db'))
        self.panel = self.ui.history_panel
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

    def open(self):
        self.panel.download_button.invoke()
        dialog = self.panel.downloader
        dialog.state.set('OK')
        return dialog

    def test_optional_download_runs_off_gui_thread_updates_history_and_sends_no_notifications(self):
        session = MagicMock()
        worker_threads = []
        def get(*args,**kwargs):
            worker_threads.append(threading.get_ident())
            return response(dict(features=[feature()]))
        session.get.side_effect = get
        with patch('historical_alerts.requests.Session',return_value=session):
            dialog = self.open()
            dialog.download_button.invoke()
            self.pump(lambda:not dialog.busy)
        self.assertTrue(all(t!=threading.get_ident() for t in worker_threads))
        self.assertEqual(self.panel.rows[0]['source'],'NWS API archive')
        self.assertIn('Source: NWS API archive',self.panel.details.get())
        self.assertIn('Imported 1',dialog.message.get())
        self.assertEqual(self.ui.count,0)
        self.assertFalse(self.ui.snapshot)
        self.service.deliver_sound.assert_not_called()
        self.service.deliver_desktop.assert_not_called()
        session.close.assert_called_once()
        self.ui.app.root.update()
        self.assertLess(dialog.download_button.widget.winfo_rooty()+dialog.download_button.widget.winfo_height(),
                        dialog.window.root.winfo_rooty()+dialog.window.root.winfo_height())

    def test_bad_dates_show_error_without_starting_worker(self):
        dialog = self.open()
        dialog.start.set('2001-01-01')
        dialog.download_button.invoke()
        self.assertIsNone(self.panel.download_future)
        self.assertIn('seven-day',dialog.message.get())
        self.assertFalse(dialog.busy)

    def test_all_us_selection_requests_nationwide_history(self):
        session = MagicMock()
        session.get.return_value = response(dict(features=[feature()]))
        with patch('historical_alerts.requests.Session',return_value=session):
            dialog = self.open()
            dialog.state.set('All US')
            dialog.download_button.invoke()
            self.pump(lambda:not dialog.busy)
        self.assertNotIn('area',session.get.call_args.kwargs['params'])
        self.assertEqual(self.panel.rows[0]['locations'],'NWS archive · US')

    def test_close_while_http_request_is_pending_cancels_without_blocking_gui(self):
        started, release = threading.Event(), threading.Event()
        session = MagicMock()
        def get(*args,**kwargs):
            started.set()
            self.assertTrue(release.wait(5))
            return response(dict(features=[feature()]))
        session.get.side_effect = get
        try:
            with patch('historical_alerts.requests.Session',return_value=session):
                dialog = self.open()
                dialog.download_button.invoke()
                self.assertTrue(started.wait(3))
                heartbeat = []
                self.ui.app.after(0,lambda:heartbeat.append(True))
                self.ui.app.root.update()
                self.assertTrue(heartbeat)
                dialog.close()
                self.assertTrue(dialog.cancel.is_set())
                release.set()
                self.pump(lambda:not dialog.busy)
                self.assertEqual(self.ui.history.history_count(),0)
                self.assertIn('cancelled',self.panel.message.get())
        finally:
            release.set()

    def test_quitting_cancels_before_database_cleanup(self):
        started, release = threading.Event(), threading.Event()
        session = MagicMock()
        def get(*args,**kwargs):
            started.set()
            self.assertTrue(release.wait(5))
            return response(dict(features=[feature()]))
        session.get.side_effect = get
        try:
            with patch('historical_alerts.requests.Session',return_value=session):
                dialog = self.open()
                dialog.download_button.invoke()
                self.assertTrue(started.wait(3))
                self.ui.close()
                self.assertTrue(dialog.cancel.is_set())
                self.assertTrue(self.ui.app._closed)
                self.assertTrue(self.ui.cleanup_thread.is_alive())
                release.set()
                self.ui.cleanup_thread.join(timeout=5)
                self.assertFalse(self.ui.cleanup_thread.is_alive())
                self.assertIsInstance(self.panel.download_future.exception(),DownloadCancelled)
            store = AlertHistory(self.ui.history.path)
            try:
                self.assertEqual(store.history_count(),0)
            finally:
                store.close()
        finally:
            release.set()
