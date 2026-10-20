"""Exercise real menu callbacks, shared preferences, exports, and archive isolation."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from alert_history import AlertHistory
from locations import LocationProfile
from main import StormwatchApp
from WeatherService import WeatherService


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'GUI tests require a desktop display')
class ApplicationMenuTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.service = Mock(interval=60)
        self.service.parse_alert.side_effect = lambda feature: WeatherService.parse_alert(self.service, feature)
        self.ui = StormwatchApp(self.service, AlertHistory(Path(self.directory.name) / 'history.db'))
        self.root = self.ui.app.root
        self.root.update()
        self.commands = self.ui.commands

    def tearDown(self):
        self.ui.close()
        self.ui.cleanup_thread.join(timeout=5)
        self.assertFalse(self.ui.cleanup_thread.is_alive())
        self.directory.cleanup()

    def test_all_groups_and_navigation_reach_existing_pages(self):
        bar = self.ui.menu.widget
        self.assertEqual([bar.entrycget(i, 'label') for i in range(bar.index('end')+1)],
                         ['File','Monitoring','Alerts','Data','Tools','Settings','Help'])
        for page in ('Active Alerts','Map','History','Notifications'):
            self.commands.show_tab(page)
            self.assertEqual(self.ui.tabs.widget.tab(self.ui.tabs.widget.select(), 'text'), page)
        self.commands.groups['Tools'].widget.invoke('Demo Mode')
        self.assertEqual(self.ui.demo_window.root.state(), 'normal')
        self.assertEqual(self.ui.tabs.widget.tab(self.ui.tabs.widget.select(),'text'), 'Notifications')
        self.service.fetch_alerts.assert_not_called()

    def test_six_tabs_and_demo_popup_reopen_preserve_isolated_simulation(self):
        notebook = self.ui.tabs.widget
        self.assertEqual([notebook.tab(tab,'text') for tab in notebook.tabs()],
                         ['Locations','Active Alerts','Alert Feed','Map','Notifications','History'])
        self.assertIsNone(self.ui.demo)
        self.commands.groups['Tools'].widget.invoke('Demo Mode')
        window, panel = self.ui.demo_window, self.ui.demo
        panel.run_scenario('new')
        self.assertEqual(len(panel.model.store.rows(active_only=True)),1)
        self.root.tk.call(window.root.protocol('WM_DELETE_WINDOW'))
        self.assertEqual(window.root.state(),'withdrawn')
        self.commands.groups['Tools'].widget.invoke('Demo Mode')
        self.assertIs(self.ui.demo,panel)
        self.assertIs(self.ui.demo_window,window)
        self.assertEqual(window.root.state(),'normal')
        self.assertEqual(len(panel.model.store.rows(active_only=True)),1)
        self.assertEqual(self.ui.history.history_count(),0)
        self.assertEqual(notebook.tab(notebook.select(),'text'),'Locations')

    def test_redundant_controls_are_removed_and_menu_sound_test_is_guarded(self):
        alerts = self.commands.groups['Alerts'].widget
        labels = [alerts.entrycget(i,'label') for i in range(alerts.index('end')+1)
                  if alerts.type(i) != 'separator']
        self.assertNotIn('Event Types…',labels)
        self.assertNotIn('Notification Rules…',labels)
        self.assertIn('Sound Settings…',labels)
        self.assertIn('Speech Settings…',labels)
        def buttons(widget):
            result = []
            for child in widget.winfo_children():
                if child.winfo_class() == 'TButton':
                    result.append(child.cget('text'))
                result.extend(buttons(child))
            return result
        visible_buttons = buttons(self.root)
        for label in ('Minimize to tray','Quit','Sound events','Spoken alerts','Test sound'):
            self.assertNotIn(label,visible_buttons)
        with patch.object(self.ui.app,'run_in_thread') as worker:
            self.ui.test_sound()
            self.ui.test_sound()
            worker.assert_called_once()
        self.ui.sound_finished()
        self.assertFalse(self.ui.sound_testing)
        with patch.object(self.ui.app,'run_in_thread',side_effect=RuntimeError('queue full')):
            self.ui.test_sound()
        self.assertFalse(self.ui.sound_testing)

    def test_interval_and_monitoring_commands_share_existing_state(self):
        self.commands.interval_menu.widget.invoke('90 seconds')
        self.assertEqual(self.service.interval,90)
        self.assertEqual(self.ui.history.setting('nws_refresh_interval'),90)
        self.assertEqual(self.ui.refresh_interval_picker.get(),'90 seconds')
        menu = self.commands.groups['Monitoring'].widget
        self.assertEqual(menu.entrycget('Pause Monitoring','state'),'disabled')
        self.assertEqual(str(self.ui.state.widget.cget('foreground')),'#ff6b6b')
        with patch.object(self.ui,'poll') as poll:
            menu.invoke('Start Monitoring')
            self.assertTrue(self.ui.running)
            self.assertEqual(str(self.ui.state.widget.cget('foreground')),'#7ce3bf')
            self.assertEqual(menu.entrycget('Start Monitoring','state'),'disabled')
            self.assertEqual(menu.entrycget('Refresh Interval','state'),'disabled')
            timer = self.ui.app.after(60000, lambda: None)
            self.ui.timer = timer
            menu.invoke('Refresh Now')
            self.assertEqual(poll.call_count,2)
            self.assertIsNone(self.ui.timer)
            self.assertNotIn(timer,self.root.tk.call('after','info'))
            self.ui.busy = True
            self.commands.sync()
            self.assertEqual(menu.entrycget('Refresh Now','state'),'disabled')
            menu.invoke('Pause Monitoring')
            self.assertFalse(self.ui.running)
            self.assertEqual(str(self.ui.state.widget.cget('foreground')),'#ff6b6b')
            self.ui.busy = False

    def test_sidebar_picker_updates_and_switches_selected_profile(self):
        profile = LocationProfile(name='Work',events=['Gale Warning'])
        self.ui.history.save_profile(profile)
        self.ui.refresh_profiles()
        self.commands.sync()
        self.ui.profile_picker.set('Work')
        self.ui.profile_picker.widget.event_generate('<<ComboboxSelected>>')
        self.assertEqual(self.ui.profile.id,profile.id)
        self.assertEqual(self.ui.profile_picker.get(),'Work')
        self.assertEqual(self.ui.selected_events(),{'Gale Warning'})
        profile.name = 'Office'
        self.ui.history.save_profile(profile)
        self.ui.refresh_profiles(profile)
        self.commands.sync()
        self.assertIn('Office',self.ui.profile_picker.values)

    def test_tray_and_login_are_only_in_general_popup_and_save_preferences(self):
        self.assertFalse(self.ui.tray_mode.widget.winfo_ismapped())
        self.assertFalse(self.ui.login.widget.winfo_ismapped())
        settings = self.commands.groups['Settings'].widget
        labels = [settings.entrycget(i,'label') for i in range(settings.index('end')+1)]
        self.assertEqual(labels,['General…','Appearance…','Time & Units…'])
        window = self.commands.general()
        self.root.update()
        tray = next(child for child in window._children
                    if child.widget.winfo_class() == 'TCheckbutton'
                    and child.widget.cget('text') == 'Close window to tray')
        tray.widget.invoke()
        self.assertTrue(self.ui.tray_mode.get())
        self.assertTrue(self.ui.history.setting('close_to_tray'))
        window.close()
        window = self.commands.general()
        tray = next(child for child in window._children
                    if child.widget.winfo_class() == 'TCheckbutton'
                    and child.widget.cget('text') == 'Close window to tray')
        self.assertTrue(tray.widget.instate(['selected']))
        tray.widget.invoke()
        self.assertFalse(self.ui.history.setting('close_to_tray'))
        window.close()

    def test_export_uses_existing_history_filters_and_shortcut_focuses_search(self):
        self.commands.search_history()
        self.root.update()
        self.assertEqual(self.ui.tabs.widget.tab(self.ui.tabs.widget.select(),'text'),'History')
        with patch.object(self.ui.history_panel,'export') as export:
            self.commands.groups['File'].widget.invoke('Export Alert History…')
            self.commands.groups['Data'].widget.invoke('Export Matching History CSV…')
            self.assertEqual(export.call_count,2)
        self.ui.history_panel.exporting = True
        self.commands.sync()
        self.assertEqual(self.commands.groups['File'].widget.entrycget('Export Alert History…','state'),'disabled')

    def test_visible_map_png_export(self):
        path = Path(self.directory.name)/'map.png'
        with patch('application_menu.filedialog.asksaveasfilename',return_value=str(path)):
            self.commands.export_map()
        self.assertTrue(path.exists())
        with Image.open(path) as image:
            self.assertEqual(image.format,'PNG')
            self.assertEqual(image.size,(self.ui.map.canvas.winfo_width(),self.ui.map.canvas.winfo_height()))

    def feature(self, ident='archive-1', sent='2026-10-01T12:00:00Z'):
        return {'type':'Feature','id':ident,'geometry':None,'properties':{
            'id':ident,'event':'Gale Warning','sent':sent,'expires':'2026-10-02T12:00:00Z',
            'areaDesc':'Coastal waters','web':'https://api.weather.gov/alerts/'+ident}}

    def write_import(self, features):
        path = Path(self.directory.name)/'nws.json'
        path.write_text(json.dumps({'type':'FeatureCollection','features':features}))
        return path

    def test_import_is_deduplicated_history_only_with_file_provenance(self):
        path = self.write_import([self.feature()])
        self.assertEqual(self.commands.import_file(path),1)
        self.assertEqual(self.commands.import_file(path),0)
        self.assertEqual(self.ui.history.rows(active_only=True),[])
        self.assertEqual(self.ui.history.delivery_count(),0)
        row = self.ui.history.search_history()[0]
        self.assertEqual(row['source'],'Local NWS GeoJSON')
        self.assertEqual(row['time_basis'],'Issued (imported file)')
        self.service.deliver_sound.assert_not_called()
        self.service.deliver_desktop.assert_not_called()

    def test_bad_import_rolls_back_entire_file(self):
        path = self.write_import([self.feature(),self.feature('invalid','not-a-date')])
        with self.assertRaises(ValueError):
            self.commands.import_file(path)
        self.assertEqual(self.ui.history.history_count(),0)
        path.write_text('{"type":"wrong"}')
        with self.assertRaises(ValueError):
            self.commands.import_file(path)

    def test_import_runs_in_worker_and_shutdown_cancels_before_database_close(self):
        path = self.write_import([self.feature()])
        started, release = threading.Event(), threading.Event()
        original = self.commands.import_file
        threads = []
        def blocked_import(filename):
            threads.append(threading.get_ident())
            started.set()
            self.assertTrue(release.wait(5))
            return original(filename)
        try:
            with patch('application_menu.filedialog.askopenfilename',return_value=str(path)), \
                 patch.object(self.commands,'import_file',side_effect=blocked_import):
                self.commands.groups['Data'].widget.invoke('Import NWS Alert Data…')
                self.assertTrue(started.wait(3))
                self.assertTrue(self.commands.import_busy)
                self.assertNotEqual(threads[0],threading.get_ident())
                self.root.update()
                self.ui.close()
                self.assertTrue(self.commands.import_cancel.is_set())
        finally:
            release.set()
            if hasattr(self.ui,'cleanup_thread'):
                self.ui.cleanup_thread.join(timeout=5)
        self.assertFalse(self.ui.cleanup_thread.is_alive())

    def test_dialogs_can_be_opened_and_closed_without_monitoring(self):
        for action in (self.commands.connection_status,self.commands.test_notification,self.commands.general,
                       self.commands.appearance,self.commands.time_units,self.commands.data_sources,
                       self.commands.storage,self.commands.diagnostics,self.commands.getting_started,
                       self.commands.shortcuts,self.commands.about):
            action()
            self.root.update_idletasks()
        for window in list(self.ui.app._windows):
            if not window._closed:
                window.close()
        self.service.fetch_alerts.assert_not_called()
        self.assertFalse(self.ui.running)
        self.assertEqual(self.ui.history.history_count(),0)
