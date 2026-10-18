import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

import requests

from alert_history import AlertHistory
from locations import LocationProfile
from main import StormwatchApp
from TkFlow import Form
from radar import METADATA_URL, RadarError, _read, connection_error
from test_dashboard import alert


class SoundRuleTests(unittest.TestCase):
    def test_sound_allowlist_does_not_filter_display_or_desktop(self):
        profile = LocationProfile(sound_events=['Tornado Warning','Hurricane Watch'])
        for event in ('Tornado Warning','Hurricane Watch'):
            self.assertTrue(profile.allows(event,'sound'))
        for event in ('Tornado Watch','Severe Thunderstorm Warning'):
            self.assertFalse(profile.allows(event,'sound'))
            self.assertTrue(profile.allows(event,'desktop'))
            self.assertTrue(profile.matches(alert(event=event)))
        profile.watch_sound = False
        self.assertFalse(profile.allows('Hurricane Watch','sound'))
        profile.sound = False
        self.assertFalse(profile.allows('Tornado Warning','sound'))

    def test_legacy_all_none_and_exact_selection_survive_json_and_database(self):
        legacy = LocationProfile.from_json(json.dumps({'name':'Legacy'}))
        self.assertIsNone(legacy.sound_events)
        self.assertTrue(legacy.allows('Flood Warning','sound'))
        with tempfile.TemporaryDirectory() as directory:
            store = AlertHistory(Path(directory)/'history.db')
            try:
                for selection in (None,[],['Tornado Warning','Hurricane Watch']):
                    profile = LocationProfile(sound_events=selection)
                    store.save_profile(profile)
                    restored = next(p for p in store.profiles() if p.id == profile.id)
                    self.assertEqual(restored.sound_events,sorted(selection) if selection else selection)
                    self.assertEqual(restored.allows('Tornado Warning','sound'),selection is None or 'Tornado Warning' in selection)
            finally:
                store.close()

    def test_invalid_allowlists_are_rejected(self):
        for invalid in ('Tornado Warning',[3],['Tornado']):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                LocationProfile(sound_events=invalid).validate()


class RadarConnectionTests(unittest.TestCase):
    def response(self,status=200,body=b'fixture',location=None):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = status
        response.headers = {'Location':location} if location else {}
        response.iter_content.return_value = [body]
        return response

    def test_proxy_rejection_is_actionable_without_exposing_raw_proxy_details(self):
        raw = requests.exceptions.ProxyError('proxy-user:secret@internal-proxy CONNECT 403 Forbidden')
        with patch('radar.requests.get',side_effect=raw),self.assertRaises(RadarError) as caught:
            _read(METADATA_URL,100,threading.Event())
        message = str(caught.exception)
        self.assertIn('api.rainviewer.com',message)
        self.assertIn('CONNECT HTTP 403',message)
        self.assertNotIn('secret',message)
        self.assertNotIn('internal-proxy',message)

    def test_http_failures_are_distinguished_from_proxy_and_tls_errors(self):
        for status,reason in ((403,'access denied'),(429,'rate limit'),(503,'unavailable')):
            with self.subTest(status=status),patch('radar.requests.get',return_value=self.response(status)),self.assertRaises(RadarError) as caught:
                _read(METADATA_URL,100,threading.Event())
            self.assertIn(str(status),str(caught.exception))
            self.assertIn(reason,str(caught.exception))
        self.assertIn('certificate',str(connection_error(requests.exceptions.SSLError(),'api.rainviewer.com')))
        self.assertIn('timed out',str(connection_error(requests.exceptions.Timeout(),'api.rainviewer.com')))

    def test_trusted_redirects_are_followed_but_other_hosts_are_not_contacted(self):
        with patch('radar.requests.get',side_effect=[self.response(302,location='/public/new.json'),self.response()]) as request:
            self.assertEqual(_read(METADATA_URL,100,threading.Event()),b'fixture')
            self.assertEqual(request.call_args.args[0],'https://api.rainviewer.com/public/new.json')
        for target in ('http://api.rainviewer.com/new','https://untrusted.example/new','https://api.rainviewer.com:8443/new'):
            with self.subTest(target=target),patch('radar.requests.get',return_value=self.response(302,location=target)) as request,self.assertRaises(RadarError):
                _read(METADATA_URL,100,threading.Event())
            self.assertEqual(request.call_count,1)

    def test_limits_and_redirect_loops_remain_bounded(self):
        with patch('radar.requests.get',return_value=self.response(body=b'large')),self.assertRaises(RadarError):
            _read(METADATA_URL,2,threading.Event())
        with patch('radar.requests.get',return_value=self.response(302,location=METADATA_URL)) as request,self.assertRaises(RadarError):
            _read(METADATA_URL,100,threading.Event())
        self.assertEqual(request.call_count,4)


@unittest.skipUnless(os.environ.get('DISPLAY'),'GUI tests require DISPLAY')
class SoundRadarGuiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.ui = StormwatchApp(Mock(interval=60),AlertHistory(Path(self.directory.name)/'history.db'))
        self.ui.app.root.update()

    def tearDown(self):
        self.ui.close()
        self.ui.cleanup_thread.join(timeout=5)
        self.directory.cleanup()

    def receive(self,items):
        self.ui.running = True
        self.ui.received(self.ui.generation,({a['id']:a for a in items},''))
        deadline = time.monotonic()+3
        while self.ui.delivery_busy and time.monotonic()<deadline:
            self.ui.app.root.update()
            time.sleep(.005)
        self.assertFalse(self.ui.delivery_busy)
        if self.ui.timer:
            self.ui.app.root.after_cancel(self.ui.timer)
            self.ui.timer = None

    def test_tornado_hurricane_preset_is_saved_and_other_events_still_display(self):
        self.ui.edit_sound_events()
        editor = self.ui.sound_preferences
        editor.critical_only()
        editor.save()
        self.assertEqual(set(self.ui.profile.sound_events),{'Tornado Warning','Tornado Watch','Hurricane Warning','Hurricane Watch'})
        self.assertTrue(editor.window._closed)
        self.ui.initialized = True
        self.receive([alert(),alert(event='Severe Thunderstorm Warning')])
        self.assertEqual(len(self.ui.snapshot),2)
        self.assertEqual(self.ui.count,2)
        self.ui.service.deliver_sound.assert_called_once()
        self.assertEqual(self.ui.service.deliver_desktop.call_count,2)

    def test_no_event_sounds_and_manual_test_are_independent(self):
        self.ui.edit_sound_events()
        self.ui.sound_preferences.none()
        self.ui.sound_preferences.save()
        self.receive([alert()])
        self.ui.service.deliver_sound.assert_not_called()
        self.ui.play_test()
        self.ui.service.deliver_sound.assert_called_once()
        self.ui.edit_sound_events()
        self.ui.sound_preferences.all_events()
        self.ui.sound_preferences.save()
        self.assertIsNone(self.ui.profile.sound_events)

    def test_failed_sound_retry_respects_new_event_filter(self):
        self.ui.service.deliver_sound.side_effect = RuntimeError('device offline')
        self.receive([alert()])
        sound = next(r for r in self.ui.history.delivery_rows() if r['channel'] == 'sound')
        self.ui.profile.sound_events = []
        self.ui.retry_delivery(sound)
        self.assertIn('disabled',self.ui.status.get())
        self.ui.service.deliver_sound.assert_called_once()

    def test_saving_an_already_open_location_editor_preserves_new_sound_preferences(self):
        self.ui.edit_profile()
        window = self.ui.app._windows[-1]
        form = next(child for child in window._children if isinstance(child,Form))
        self.ui.edit_sound_events()
        self.ui.sound_preferences.critical_only()
        self.ui.sound_preferences.save()
        expected = list(self.ui.profile.sound_events)
        save = next(child for child in form.actions._children if child.widget.cget('text') == 'Save location')
        save.widget.invoke()
        self.assertTrue(window._closed)
        self.assertEqual(self.ui.profile.sound_events,expected)

    def test_radar_failure_is_visible_in_status_and_connection_details(self):
        self.ui.tabs.widget.select(self.ui.map.parent.widget)
        self.ui.app.root.update()
        panel = self.ui.radar
        panel.enabled.set(True)
        reason = RadarError('Proxy refused HTTPS access to api.rainviewer.com (CONNECT HTTP 403). Allow this host.')
        panel.failed(panel.generation,self.ui.map.viewport(),reason)
        self.assertIn('CONNECT HTTP 403',panel.status.get())
        panel.tick()
        self.assertIn('CONNECT HTTP 403',panel.status.get())
        panel.show_details()
        window = self.ui.app._windows[-1]
        text = next(child for child in window._children if hasattr(child,'text'))
        self.assertIn('CONNECT HTTP 403',text.get())
        self.assertIn('tilecache.rainviewer.com',text.get())
        self.assertNotIn('Proxy refused',self.ui.feed.get())

    def test_map_connection_details_share_zoom_toolbar_and_removed_legend_frees_space(self):
        self.ui.tabs.widget.select(self.ui.map.parent.widget)
        self.ui.app.root.geometry('1000x760')
        self.ui.app.root.update()
        panel = self.ui.radar
        labels = [str(child.widget.cget('text')) for child in panel.details_button.parent._children]
        self.assertIn('Fit',labels)
        self.assertIn('+',labels)
        self.assertIn('Connection details',labels)
        texts = []
        def collect(parent):
            for child in getattr(parent,'_children',[]):
                if 'text' in child.widget.keys():
                    texts.append(str(child.widget.cget('text')))
                collect(child)
        collect(self.ui.map.parent)
        self.assertFalse(any('Universal Blue radar palette' in text for text in texts))
        self.assertNotIn('RainViewer',texts)
        button = panel.details_button.widget
        self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),
                             self.ui.map.parent.widget.winfo_rootx()+self.ui.map.parent.widget.winfo_width())
