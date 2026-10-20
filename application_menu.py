"""Application menus: navigation and shared actions, with no duplicate monitoring state."""
from pathlib import Path
import logging
import os
import subprocess
import sys
import json
import threading
import webbrowser
from tkinter import filedialog

from TkFlow import Button, Checkbox, Label, Menu, TextArea, Window
from application_paths import state_directory


class ApplicationMenu:
    def __init__(self, owner):
        self.owner = owner
        self.root = owner.app.root
        self.bar = owner.menu
        self.import_future = None
        self.import_busy = False
        self.import_cancel = threading.Event()
        self.groups = {}
        for name in ('File', 'Monitoring', 'Alerts', 'Data', 'Tools', 'Settings', 'Help'):
            self.groups[name] = self.bar.dropdown(name)
        file = self.groups['File']
        file.add_command('Export Alert History…', self.export_history, accelerator='Ctrl+E')
        file.add_command('Export Map Image…', self.export_map)
        file.separator()
        file.add_command('Minimize to Tray', owner.hide_to_tray)
        file.add_command('Exit', owner.close, accelerator='Ctrl+Q')

        monitoring = self.groups['Monitoring']
        self.start_index = monitoring.add_command('Start Monitoring', lambda: self.monitor(True))
        self.pause_index = monitoring.add_command('Pause Monitoring', lambda: self.monitor(False))
        self.refresh_index = monitoring.add_command('Refresh Now', self.refresh_now, accelerator='F5')
        self.interval_menu = monitoring.dropdown('Refresh Interval')
        self.interval = owner.refresh_interval_picker.variable
        for seconds in (30, 60, 90, 120):
            self.interval_menu.widget.add_radiobutton(label=f'{seconds} seconds', variable=self.interval,
                value=f'{seconds} seconds', command=lambda n=seconds: owner.set_refresh_interval(f'{n} seconds'))

        alerts = self.groups['Alerts']
        alerts.add_command('Sound Settings…', owner.edit_sound_events)
        alerts.add_command('Speech Settings…', owner.edit_speech_events)
        alerts.add_command('Test Notification…', self.test_notification)
        alerts.separator()
        alerts.add_command('Clear Alert Feed', owner.clear_feed)

        data = self.groups['Data']
        owner.data_menu = data
        data.add_command('Metrics', owner.open_metrics)
        data.add_command('Download Latest 7 Days', self.download_history)
        data.add_command('History Download Options…', lambda: (self.show_tab('History'), owner.history_panel.open_download()))
        data.add_command('Export Matching History CSV…', self.export_history)
        data.add_command('Import NWS Alert Data…', self.import_data)
        data.add_command('Data Sources…', self.data_sources)
        data.add_command('Storage & Retention…', self.storage)

        tools = self.groups['Tools']
        tools.add_command('Demo Mode', owner.open_demo)
        tools.add_command('Notification Delivery Log', lambda: self.show_tab('Notifications'))
        tools.add_command('Diagnostics…', self.diagnostics)
        tools.add_command('Open Log Folder', self.open_logs)
        settings = self.groups['Settings']
        settings.add_command('General…', self.general)
        settings.add_command('Appearance…', self.appearance)
        settings.add_command('Time & Units…', self.time_units)
        help_menu = self.groups['Help']
        help_menu.add_command('Getting Started', self.getting_started, accelerator='F1')
        help_menu.add_command('NWS Alert Definitions', lambda: webbrowser.open('https://www.weather.gov/safety/'))
        help_menu.add_command('Keyboard Shortcuts', self.shortcuts)
        help_menu.add_command('Report an Issue…', lambda: webbrowser.open('https://github.com/spectremancer/Stormwatch/issues/new'))
        help_menu.add_command('About Stormwatch', self.about)

        for sequence, action in (('<F5>', self.refresh_now), ('<Control-f>', self.search_history),
                                 ('<Control-e>', self.export_history), ('<Control-q>', owner.close), ('<F1>', self.getting_started)):
            self.root.bind(sequence, lambda event, action=action: self.shortcut(action), add='+')
        for menu in self.groups.values():
            menu.widget.configure(postcommand=self.sync)
        self.interval_menu.widget.configure(postcommand=self.sync)
        self.sync()

    @staticmethod
    def shortcut(action):
        action()
        return 'break'

    def sync(self):
        owner = self.owner
        monitoring = self.groups['Monitoring'].widget
        monitoring.entryconfigure(self.start_index, state='disabled' if owner.running or owner.busy else 'normal')
        monitoring.entryconfigure(self.pause_index, state='normal' if owner.running else 'disabled')
        monitoring.entryconfigure(self.refresh_index, state='normal' if owner.running and not owner.busy else 'disabled')
        monitoring.entryconfigure('Refresh Interval', state='disabled' if owner.running else 'normal')
        self.interval.set(f'{owner.service.interval} seconds')
        self.groups['Data'].widget.entryconfigure('Import NWS Alert Data…', state='disabled' if self.import_busy else 'normal')
        self.groups['File'].widget.entryconfigure('Export Alert History…',
            state='disabled' if owner.history_panel.exporting else 'normal')
        self.groups['Data'].widget.entryconfigure('Export Matching History CSV…',
            state='disabled' if owner.history_panel.exporting else 'normal')

    def show_tab(self, title):
        notebook = self.owner.tabs.widget
        for tab in notebook.tabs():
            if notebook.tab(tab, 'text') == title:
                notebook.select(tab)
                return
        raise ValueError(f'Unknown tab: {title}')

    def monitor(self, running):
        if self.owner.running != running:
            self.owner.toggle_monitoring()
        self.sync()

    def refresh_now(self):
        owner = self.owner
        if not owner.running or owner.busy:
            owner.status.set('Start monitoring to refresh live alerts.' if not owner.running else 'A refresh is already in progress.')
            return
        if owner.timer is not None:
            self.root.after_cancel(owner.timer)
            owner.timer = None
        owner.poll()
        self.sync()

    def search_history(self):
        self.show_tab('History')
        self.owner.history_panel.text.widget.focus_set()

    def export_history(self):
        self.show_tab('History')
        self.owner.history_panel.export()

    def download_history(self):
        self.show_tab('History')
        self.owner.history_panel.download_latest()

    def import_data(self):
        if self.import_busy:
            return
        path = filedialog.askopenfilename(parent=self.root, title='Import NWS GeoJSON into history',
                                         filetypes=[('NWS GeoJSON / JSON', '*.geojson *.json')])
        if not path:
            return
        self.import_busy = True
        self.import_cancel.clear()
        self.owner.status.set('Importing NWS alert records into history…')
        self.import_future = self.owner.app.run_in_thread(self.import_file, path,
            on_result=self.imported, on_error=self.import_failed)

    def import_file(self, path):
        # A bounded, atomic history-only import. It never observes live alerts or schedules delivery.
        with open(path, 'rb') as stream:
            raw = stream.read(10 * 1024 * 1024 + 1)
        if len(raw) > 10 * 1024 * 1024:
            raise ValueError('Choose a GeoJSON file smaller than 10 MiB.')
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get('type') != 'FeatureCollection':
            raise ValueError('Expected an NWS GeoJSON FeatureCollection.')
        features = payload.get('features')
        if not isinstance(features, list) or len(features) > 5000:
            raise ValueError('Expected a features list with at most 5,000 records.')
        alerts = []
        for feature in features:
            if not isinstance(feature, dict) or not isinstance(feature.get('properties'), dict):
                raise ValueError('Invalid GeoJSON feature; no records were imported.')
            alert = self.owner.service.parse_alert(feature)
            if alert:
                alerts.append(alert)
        if not alerts:
            raise ValueError('The file contains no supported NWS weather alerts.')
        return self.owner.history.import_archive(alerts, 'Local file', self.import_cancel, source='Local NWS GeoJSON')

    def imported(self, count):
        self.import_busy = False
        self.show_tab('History')
        self.owner.history_panel.refresh()
        self.owner.status.set(f'Imported {count} new historical records. Existing versions were skipped; no live notifications were issued.')

    def import_failed(self, error):
        self.import_busy = False
        self.owner.app.message(f'Import failed: {error}', title='Import NWS data', kind='error')

    def close(self):
        self.import_cancel.set()

    def wait(self):
        if self.import_future is not None:
            try:
                self.import_future.result()
            except Exception:
                pass

    def map_action(self, zoom):
        self.show_tab('Map')
        self.owner.map.fit() if zoom is None else self.owner.map.zoom(zoom)

    def export_map(self):
        self.show_tab('Map')
        path = filedialog.asksaveasfilename(parent=self.root, title='Export visible alert map',
            defaultextension='.png', filetypes=[('PNG image', '*.png')], initialfile='stormwatch-map.png')
        if not path:
            return
        try:
            # Capture only the visible map canvas, including the current radar frame.
            from PIL import ImageGrab
            self.root.update_idletasks()
            self.owner.map.flush_draw()
            canvas = self.owner.map.canvas
            x, y = canvas.winfo_rootx(), canvas.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + canvas.winfo_width(), y + canvas.winfo_height())).save(path)
            self.owner.status.set('Exported the visible map to PNG. Radar retains its original observation time.')
        except Exception as error:
            self.owner.app.message(f'Could not export the visible map: {error}', title='Map export', kind='error')

    def info(self, title, body):
        window = Window(self.owner.app, title, width=730, height=540)
        Label(window, title, style='Heading.TLabel')
        area = TextArea(window, readonly=True, autoscroll=False, expand=True, fill='both',
                        bg='#101c30', fg='#e5edf8', padx=16, pady=12)
        area.set(body)
        Button(window, 'Close', window.close)
        return window

    def connection_status(self):
        owner = self.owner
        owner.update_health()
        window = self.info('Connection status', owner.health.get() + '\n\n' +
            f'Monitoring: {"running" if owner.running else "paused"}\nNWS refresh interval: {owner.service.interval} seconds\n'
            f'Request in progress: {owner.busy}\nLast NWS error: {owner.last_error or "None"}\n'
            f'Coverage notice: {owner.coverage_warning or "None"}\n\nRadar: {owner.radar.status.get()}\n\n'
            'This is a snapshot. The main connection banner updates every second. NWS and radar connections are independent.')
        Button(window, 'Radar Connection Details…', owner.radar.show_details)

    def reset_layout(self):
        self.root.geometry('1260x900')
        self.show_tab('Locations')
        self.owner.filters.canvas.yview_moveto(0)
        self.owner.map.fit()
        self.owner.status.set('Window size, selected tab, event scroll position, and map extent reset.')

    def test_notification(self):
        window = Window(self.owner.app, 'Test notifications', width=560, height=340)
        Label(window, 'Notification tests', style='Heading.TLabel')
        Label(window, 'These are manual tests. Demo alerts are labeled SIMULATION.', wraplength=490)
        Button(window, 'Test Alert Sound', self.owner.test_sound)
        Button(window, 'Test Speech', self.owner.test_speech)
        Button(window, 'Open Desktop Notification Demo', lambda: (self.owner.open_demo(), window.close()))

    def general(self):
        window = Window(self.owner.app, 'General settings', width=560, height=360)
        Label(window, 'Application behavior', style='Heading.TLabel')
        # Share the application preference variables across settings dialogs.
        for label, control, command in (('Close window to tray', self.owner.tray_mode, self.owner.set_tray_mode),
                                        ('Launch at login (Windows)', self.owner.login, self.owner.set_login)):
            check = Checkbox(window, label, value=control.get(), command=command)
            check.widget.configure(variable=control.variable)
            if 'Windows' in label and sys.platform != 'win32':
                check.disable()
            # The callback must read the shared variable, not the unused local one.
            check.widget.configure(command=lambda control=control, command=command: command(control.get()))
        Button(window, 'Close', window.close)
        return window

    def appearance(self):
        window = Window(self.owner.app, 'Appearance', width=530, height=330)
        Label(window, 'Text size', style='Heading.TLabel')
        Label(window, 'Applies to application controls. Alert cards and map labels keep their dedicated styles.', wraplength=460)
        for size in (10, 12, 14):
            Button(window, f'{size} point text', lambda size=size: self.set_text_size(size))

    def set_text_size(self, size):
        from tkinter import font
        self.owner.history.save_setting('control_text_size', size)
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont'):
            font.nametofont(name, root=self.root).configure(size=size)
        self.owner.app.style.configure('.', font=(self.owner.font_family, size))
        self.owner.status.set(f'Control text size set to {size} points.')

    def time_units(self):
        self.info('Time & units', 'Alert times and spoken expiration times use this computer’s local timezone. '
            'Change the operating system timezone to change local time display.\n\n'
            'Radar timestamps explicitly use UTC. Historical search dates use local calendar dates.\n\n'
            'Official NWS alert descriptions retain the source units and wording; Stormwatch does not convert safety instructions.')

    def data_sources(self):
        self.info('Data sources', 'Live alerts and recent historical downloads: National Weather Service (api.weather.gov).\n\n'
            'Radar imagery: RainViewer. Radar is optional, shows recent past observations, and has separate connection status.\n\n'
            'Local history: observed alert changes and optional downloaded NWS archive records. Downloads do not trigger live notifications.\n\n'
            'Demo: synthetic simulations kept separate from live monitoring.\n\n'
            'Alert-map boundaries may come from NWS alert polygons or resolved affected zones. Alerts lacking boundaries remain in Active alerts.')

    def storage(self):
        path = self.owner.history.path
        size = sum(p.stat().st_size for p in (path, Path(str(path)+'-wal'), Path(str(path)+'-shm')) if p.exists())
        self.info('Storage & retention', f'Local database:\n{path}\n\nDatabase and journal size: {size / 1048576:.2f} MiB\n\n'
            'Alert history and delivery receipts are retained. Expired and cancelled alerts leave current views, but remain searchable.\n\n'
            'Export matching history to CSV from File or Data. This menu does not delete records; retaining delivery receipts prevents duplicate notifications.')

    def diagnostics(self):
        owner = self.owner
        self.info('Diagnostics', f'Platform: {sys.platform}\nPython: {sys.version.split()[0]}\n'
            f'Monitoring: {owner.running}\nRequest in progress: {owner.busy}\n'
            f'Enabled locations: {sum(p.enabled for p in owner.profiles)}\n'
            f'Current matching alerts: {len(owner.snapshot)}\n'
            f'Pending speech event groups: {len(owner.speech_pending)}\n'
            f'Speech in progress: {owner.speech_busy}\n\n'
            f'{owner.health.get()}\nLast NWS error: {owner.last_error or "None"}\n\n'
            f'Radar: {owner.radar.status.get()}\n\nUse Notification Delivery Log for channel-specific failures and retry outcomes.')

    def open_logs(self):
        # Use the actual logger destination when available, including packaged builds.
        handlers = logging.getLogger('WeatherService').handlers
        path = next((Path(h.baseFilename).parent for h in handlers if isinstance(h, logging.FileHandler)),
                    state_directory())
        try:
            if sys.platform == 'win32':
                os.startfile(str(path))
            else:
                subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])
        except OSError as error:
            self.info('Log folder', f'{path}\n\nCould not open the system file manager: {error}')

    def getting_started(self):
        self.info('Getting started', '1. Add saved locations and choose the event types to follow. All enabled locations monitor together.\n\n'
            '2. Configure sound, speech, and desktop preferences under Alerts. Choose the NWS refresh interval before starting.\n\n'
            '3. Start monitoring. Check the connection banner for stale data. Active alerts and the map remove expired and cancelled events.\n\n'
            '4. Speech covers new events after monitoring starts, grouped by event type and affected locations.\n\n'
            '5. Use History to search or export previous alerts, Data → Metrics for totals, and Tools → Demo Mode for simulations.\n\n'
            'Minimize to Tray keeps monitoring running. Exit stops the application.')

    def shortcuts(self):
        self.info('Keyboard shortcuts', 'F5 — Refresh NWS alerts while monitoring\nCtrl+F — Search alert history\n'
            'Ctrl+E — Export history using the applied filters\nCtrl+Q — Exit Stormwatch\nF1 — Getting started\nAlt+F4 — Close window (uses your Close to Tray setting)\n\n'
            'On the map: drag to pan, scroll to zoom, double-click to zoom in.')

    def about(self):
        self.info('About Stormwatch', 'STORMWATCH\nWeather intelligence for your locations\n\n'
            'Location-aware NWS alerts, live maps, searchable history, and independent notification channels.\n\n'
            'Weather alerts: National Weather Service\nRadar imagery: RainViewer\nInterface: TkFlow / Tk\n\n'
            'Project: github.com/spectremancer/Stormwatch')
