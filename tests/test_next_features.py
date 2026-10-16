import csv
import gc
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from alert_changes import summarize_change
from alert_history import AlertHistory
from desktop import configure_identity
from locations import LocationProfile
from main import StormwatchApp
from radar import MAX_FRAMES, MAX_TILES, RadarService, Viewport, mercator_y, parse_frames, tile_layout
from test_dashboard import alert


class ChangeSummaryTests(unittest.TestCase):
    def test_extension_severity_and_removed_county_are_explicit(self):
        old = alert(expires='2099-01-01T01:00:00Z',severity='Severe',geocode={'UGC':['ILC031','ILC043']})
        new = dict(old,expires='2099-01-01T01:30:00Z',severity='Extreme',geocode={'UGC':['ILC031','ILC097']})
        summary = summarize_change(old,new,'Extended')
        self.assertIn('Extended by 30 minutes',summary)
        self.assertIn('Severity increased from Severe to Extreme',summary)
        self.assertIn('Removed affected counties/zones: ILC043',summary)
        self.assertIn('Added affected counties/zones: ILC097',summary)

    def test_disappearance_is_distinguished_from_confirmed_cancellation(self):
        self.assertIn('cancellation was not confirmed',summarize_change(None,alert(),'No longer active'))
        self.assertIn('issuing agency cancelled',summarize_change(None,alert(),'Cancelled'))

    def test_unknown_severity_does_not_imply_escalation(self):
        summary = summarize_change(alert(severity='Unknown'),alert(severity='Extreme'),'Updated')
        self.assertIn('Severity changed from Unknown to Extreme',summary)
        self.assertNotIn('increased',summary)

    def test_summaries_survive_reopen_and_follow_referenced_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'history.db'
            store = AlertHistory(path)
            old = alert(expires='2099-01-01T01:00:00Z')
            new = alert(id='replacement',expires='2099-01-01T01:30:00Z',message_type='Update',references=[{'identifier':old['id']}])
            store.observe(old)
            store.observe(new)
            store.observe(new)
            self.assertEqual(store.history_count(),2)
            store.close()
            store = AlertHistory(path)
            try:
                self.assertIn('Extended by 30 minutes',store.change_summary(new))
                self.assertIn('Extended by 30 minutes',store.rows(active_only=True)[0]['summary'])
                self.assertIn('New alert issued',store.change_summary(old))
                output = Path(directory)/'history.csv'
                store.export_history(output)
                with output.open(encoding='utf-8-sig') as source:
                    rows = list(csv.DictReader(source))
                self.assertIn('Extended by 30 minutes',rows[0]['change_summary'])
            finally:
                store.close()


class RadarDataTests(unittest.TestCase):
    def setUp(self):
        # Prior GUI tests create/destroy Tk interpreters. Collect their cycles on
        # the main thread before the Pillow tile workers can trigger Python GC.
        gc.collect()

    def metadata(self, now):
        return dict(host='https://tilecache.rainviewer.com',radar=dict(
            past=[dict(time=now-i*600,path=f'/v2/radar/{now-i*600}') for i in range(13)],
            nowcast=[dict(time=now+600,path=f'/v2/radar/{now+600}')]))

    def test_only_recent_observed_frames_and_trusted_paths_are_used(self):
        now = int(time.time())
        data = self.metadata(now)
        frames = parse_frames(data,now)
        self.assertEqual(len(frames),MAX_FRAMES)
        self.assertEqual(frames[-1][0],now)
        self.assertEqual(frames,sorted(frames))
        data['host'] = 'https://example.com'
        with self.assertRaises(ValueError):
            parse_frames(data,now)
        data = self.metadata(now-20000)
        with self.assertRaises(ValueError):
            parse_frames(data,now)
        data = dict(host='https://tilecache.rainviewer.com',radar=dict(past=[dict(time=now,path='/../../file')]))
        with self.assertRaises(ValueError):
            parse_frames(data,now)

    def test_tile_budget_holds_for_world_and_close_views(self):
        for scale in (1,8,50,2000):
            zoom,x0,y0,x1,y1 = tile_layout(Viewport(1600,1000,-98,39,scale))
            self.assertLessEqual((x1-x0+1)*(y1-y0+1),MAX_TILES)
            self.assertGreaterEqual(x0,0)
            self.assertLess(x1,2**zoom)
            self.assertGreaterEqual(y0,0)
            self.assertLess(y1,2**zoom)

    def test_mercator_tiles_align_with_geographic_map_and_cache_is_reused(self):
        now = int(time.time())
        service = RadarService()
        view = Viewport(400,300,-98,39,8)
        def gradient(key):
            _,zoom,tx,ty = key
            world = 256*2**zoom
            image = Image.new('RGBA',(256,256))
            image.putdata([(int((tx*256+x)/world*255),int((ty*256+y)/world*255),0,255)
                           for y in range(256) for x in range(256)])
            return image
        with patch('radar._read',return_value=json.dumps(self.metadata(now)).encode()),patch.object(service,'_tile',side_effect=gradient) as load:
            result_view,frames = service.load(view)
            first_calls = load.call_count
            self.assertEqual(result_view,view)
            self.assertEqual(len(frames),MAX_FRAMES)
            for lon,lat in ((-98,39),(-110,45),(-90,30)):
                pixel = frames[-1][1].getpixel((int(view.width/2+(lon+98)*8),int(view.height/2-(lat-39)*8)))
                self.assertAlmostEqual(pixel[0],(lon+180)/360*255,delta=2)
                self.assertAlmostEqual(pixel[1],mercator_y(lat,256)/256*255,delta=2)
                self.assertEqual(pixel[3],183)
            service.load(view)
            self.assertEqual(load.call_count,first_calls)
            service.close()
            with self.assertRaises(RuntimeError):
                service.load(view)

    def test_invalid_tile_size_is_rejected(self):
        source = BytesIO()
        Image.new('RGBA',(1,1)).save(source,format='PNG')
        with patch('radar._read',return_value=source.getvalue()),self.assertRaises(ValueError):
            RadarService()._tile(('/v2/radar/123',1,0,0))


@unittest.skipUnless(os.environ.get('DISPLAY'),'GUI tests require DISPLAY')
class NextFeatureGuiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.ui = StormwatchApp(Mock(interval=60),AlertHistory(Path(self.directory.name)/'history.db'))
        self.ui.profile.name = 'Home'
        self.ui.profile.states = ['IL']
        self.ui.profile.events = ['Tornado Warning','Tornado Watch']
        self.ui.profile.sound = self.ui.profile.desktop = False
        self.ui.app.root.update()

    def tearDown(self):
        self.ui.close()
        self.ui.cleanup_thread.join(timeout=5)
        self.directory.cleanup()

    def labels(self, widget):
        result = []
        for child in widget.winfo_children():
            if 'text' in child.keys():
                result.append(str(child.cget('text')))
            result.extend(self.labels(child))
        return result

    def receive(self, items):
        self.ui.running = True
        self.ui.received(self.ui.generation,({a['id']:a for a in items},''))
        self.ui.app.root.update()
        if self.ui.timer:
            self.ui.app.root.after_cancel(self.ui.timer)
            self.ui.timer = None

    def test_location_status_respects_filters_disabled_profiles_and_freshness(self):
        self.ui.profiles += [LocationProfile(name='Family',states=['TX'],sound=False,desktop=False),
                             LocationProfile(name='Work',enabled=False)]
        self.receive([alert(id='warning',severity='Severe'),alert(event='Tornado Watch',id='watch',severity='Extreme')])
        text = self.labels(self.ui.overview.body)
        self.assertIn('Home',text)
        self.assertIn('Family',text)
        self.assertIn('Work',text)
        self.assertIn('Tornado Warning',text)
        self.assertNotIn('Tornado Watch',text)
        self.assertIn('No selected active alerts',text)
        self.assertIn('Disabled',text)
        self.assertEqual(self.ui.overview.freshness,'LIVE')
        self.ui.toggle_monitoring()
        self.assertIn('STALE',self.ui.overview.freshness)
        self.assertTrue(all('STALE' in label.cget('text') for label in self.ui.overview.health_labels))

    def test_change_summary_is_visible_in_feed_cards_and_history(self):
        self.receive([alert(expires='2099-01-01T01:00:00Z')])
        self.receive([alert(expires='2099-01-01T01:30:00Z')])
        self.assertIn('Extended by 30 minutes',self.ui.feed.get())
        self.assertTrue(any('Extended by 30 minutes' in text for text in self.labels(self.ui.cards.body)))
        self.assertIn('Extended by 30 minutes',self.ui.history.search_history()[0]['summary'])

    def test_replacement_that_removes_home_is_logged_and_clears_active_overview(self):
        old = alert()
        self.receive([old])
        replacement = alert(id='replacement',message_type='Update',references=[{'identifier':old['id']}],
                            geocode={'UGC':['TXC201']},area='Harris County')
        self.receive([replacement])
        self.assertIn('Removed affected counties/zones: ILC031',self.ui.feed.get())
        self.assertIn('Home (previously affected)',self.ui.feed.get())
        self.assertFalse(self.ui.snapshot)
        self.assertIn('No selected active alerts',self.labels(self.ui.overview.body))

    def test_radar_frames_are_under_boundaries_and_pan_hides_old_view(self):
        self.ui.tabs.widget.select(self.ui.map.parent.widget)
        self.ui.app.root.update()
        panel = self.ui.radar
        view = self.ui.map.viewport()
        now = int(time.time())
        image = Image.new('RGBA',(view.width,view.height),(0,180,0,100))
        panel.enabled.set(True)
        panel.loaded(panel.generation,(view,[(now-600,image),(now,image)]))
        self.assertIn('Observed radar',panel.status.get())
        radar = self.ui.map.canvas.find_withtag('radar')
        self.assertEqual(len(radar),1)
        stacking = self.ui.map.canvas.find_all()
        self.assertLess(stacking.index(radar[0]),len(stacking)-1)
        panel.toggle_play()
        self.assertTrue(panel.playing)
        panel.step(1)
        self.assertFalse(panel.playing)
        self.ui.map.zoom(1.5)
        self.ui.app.root.update()
        self.assertFalse(self.ui.map.canvas.find_withtag('radar'))
        self.assertIn('disabled',panel.play_button.widget.state())
        # A result for the old view must not replace new-view imagery.
        panel.loaded(panel.generation,(view,[(now,image)]))
        self.assertFalse(self.ui.map.canvas.find_withtag('radar'))

    def test_radar_failed_refresh_retains_original_time_and_marks_stale(self):
        self.ui.tabs.widget.select(self.ui.map.parent.widget)
        self.ui.app.root.update()
        panel = self.ui.radar
        view = self.ui.map.viewport()
        old = int(time.time())-3600
        image = Image.new('RGBA',(view.width,view.height))
        panel.enabled.set(True)
        panel.loaded(panel.generation,(view,[(old,image)]))
        self.assertIn('STALE RADAR',panel.status.get())
        panel.failed(panel.generation,view,RuntimeError('offline'))
        panel.tick()
        self.assertIn('STALE RADAR',panel.status.get())
        self.assertIn('Radar refresh failed',panel.status.get())
        self.assertEqual(panel.frames[0][0],old)
        panel.enabled.set(False)
        panel.toggle()
        self.assertFalse(self.ui.map.canvas.find_withtag('radar'))
        self.assertEqual(panel.frames,[])

    def test_radar_loading_runs_off_gui_thread_and_completes_through_dispatcher(self):
        self.ui.tabs.widget.select(self.ui.map.parent.widget)
        self.ui.app.root.update()
        panel = self.ui.radar
        view = self.ui.map.viewport()
        threads = []
        def load(requested):
            threads.append(threading.get_ident())
            return requested,[(int(time.time()),Image.new('RGBA',(view.width,view.height))) ]
        with patch.object(panel.service,'load',side_effect=load):
            panel.enabled.set(True)
            panel.refresh(force=True)
            self.assertTrue(panel.busy)
            deadline = time.monotonic()+3
            while panel.busy and time.monotonic()<deadline:
                self.ui.app.root.update()
                time.sleep(.005)
        self.assertFalse(panel.busy)
        self.assertNotEqual(threads,[threading.get_ident()])
        self.assertEqual(panel.loaded_view,view)
        self.assertTrue(self.ui.map.canvas.find_withtag('radar'))
        self.assertNotIn('Observed radar',self.ui.feed.get())

    def test_actual_ico_is_loaded_and_windows_taskbar_identity_is_set(self):
        self.assertEqual([i.width() for i in self.ui.app.root._stormwatch_icons],[16,32,48,64])
        windows = Mock()
        root = self.ui.app.root
        with patch('desktop.sys.platform','win32'),patch('ctypes.windll',windows,create=True),patch.object(root,'iconbitmap') as bitmap:
            configure_identity(root)
        windows.shell32.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with('Stormwatch.WeatherIntelligence')
        self.assertEqual(Path(bitmap.call_args.kwargs['default']).name,'icon.ico')
