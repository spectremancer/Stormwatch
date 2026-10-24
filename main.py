"""Stormwatch: location-aware desktop weather monitoring built with TkFlow."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from copy import deepcopy
from monitoring_runtime import BoundaryResolver, defer_store_work
from workspace_layout import Workspace
from async_views import LatestQuery
from preference_changes import PreferenceChanges
from active_snapshot import active_rows
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import sqlite3
import threading
import webbrowser
from tkinter import font as tkfont

import pygame

from TkFlow import TextInput, App, Button, Checkbox, Dropdown, Form, Label, Menu, TextArea, Window
from WeatherService import WeatherService
from alert_history import AlertHistory, expiration_of
from dashboard_views import AlertMap, Cards, Tabs, LocationOverview, threat_priority, active_sort_key
from desktop import Tray, set_login, configure_identity
from location_wizard import LocationWizard
from delivery_panel import DeliveryPanel
from demo import DemoPanel
from locations import LocationProfile
from notification_rules import add_rule_fields, rule_values
from history_panel import HistoryPanel
from radar_panel import RadarPanel
from sound_preferences import SoundPreferences
from notification_explanations import decisions, explanation_text
from speech import SpeechService, SpeechCancelled, announcement, batch_announcement, issued_after
from metrics import Metrics
from application_menu import ApplicationMenu
from appearance import Appearance
from event_catalog import WEATHER_EVENTS, DEFAULT_EVENTS, CRITICAL_EVENTS, EVENT_COLORS, event_category

CRITICAL = CRITICAL_EVENTS
REFRESH_INTERVALS = (30,60,90,120)


from monitoring_controller import MonitoringController
from workspace_actions import WorkspaceActions


class StormwatchApp(MonitoringController, WorkspaceActions):
    def __init__(self, service=None, history=None):
        self.service = service or WeatherService(interval=60)
        self.history = history if history is not None else AlertHistory()
        saved_interval = self.history.setting('nws_refresh_interval',60)
        self.service.interval = saved_interval if type(saved_interval) is int and saved_interval in REFRESH_INTERVALS else 60
        self.profiles = self.history.profiles()
        if not self.profiles:
            self.profiles = [LocationProfile()]
            self.history.save_profile(self.profiles[0])
        self.profile = self.profiles[0]
        self.app = App("Stormwatch · Weather intelligence", width=1260, height=900,
                       min_width=800, min_height=560, padding=12, spacing=8, theme="clam")
        self.app.root.geometry(f"{min(1260,self.app.root.winfo_screenwidth()-60)}x{min(900,self.app.root.winfo_screenheight()-100)}")
        self.active_query = LatestQuery(self.app,critical=True)
        self.preference_changes = PreferenceChanges(self.history,self.app)
        configure_identity(self.app.root)
        self.snapshot = {}
        self.initialized = False
        self.running = self.busy = False
        self.generation = 0
        self.timer = None
        self.processing_timer = None
        self.health_timer = None
        self.last_success = self.next_refresh = None
        self.last_error = self.coverage_warning = ""
        self.failures = 0
        self.count = 0
        self.sound_lock = threading.Lock()
        self.network_lock = threading.Lock()
        self.boundaries = BoundaryResolver()
        self.boundary_future = None
        self._record_revisions = {}
        self.delivery_busy = False
        self.delivery_future = None
        self.speaker = SpeechService()
        self.speech_busy = False
        self.speech_future = None
        self.speech_pending = {}
        self.speech_current = None
        self.speech_current_jobs = []
        self.speech_started_at = None
        self.cancel_since = datetime.now(timezone.utc) - timedelta(minutes=15)
        self.loading_profile = False
        self.tray_ready = False
        self.hidden = False
        self.font_family = tkfont.nametofont("TkDefaultFont").actual("family")
        self._style()
        self.appearance = Appearance(self.app, self.history)
        self.metrics = None
        self.menu = Menu(self.app)
        header = self.app.row(padding=0)
        brand = header.column(padding=0, expand=True)
        Label(brand, "STORMWATCH", style="Brand.TLabel")
        Label(brand, "Weather intelligence • Your locations, in view", style="Muted.TLabel")
        Button(header,'Event filters',self.toggle_sidebar,style='Sidebar.TButton')
        Button(header,'Readiness',lambda:__import__('workspace_tools').readiness(self),style='Sidebar.TButton')
        self.state = Label(header, "●  PAUSED", style="Status.TLabel", foreground="#ff6b6b")
        body = self.workspace = Workspace(self.app)
        controls = body.column(padding=(8, 6), spacing=3, fill="both", style="Panel.TFrame")
        self.sidebar = controls
        self.sidebar_visible = True
        location_heading = controls.row(padding=0, spacing=6)
        Label(location_heading, "Saved locations", style="Heading.TLabel")
        self.profile_picker = Dropdown(location_heading, [p.name for p in self.profiles],
                                       on_change=self.choose_profile, width=14, expand=True)
        self.location_summary = Label(controls, self.profile.summary(), style="Muted.TLabel", wraplength=290)
        self.rule_summary = Label(controls, self.profile.rules_summary(), style="Muted.TLabel", wraplength=300)
        buttons = controls.row(padding=0)
        Button(buttons, "Add", self.add_location, style="Sidebar.TButton", width=0)
        Button(buttons, "Edit", self.edit_profile, style="Sidebar.TButton", width=0)
        Button(buttons, "Remove", self.remove_profile, style="Sidebar.TButton", width=0)
        Label(controls, "All enabled locations monitor together.", style="Muted.TLabel")
        actions = controls.row(padding=0)
        Button(actions, "Select all", lambda: self.select_all(True), style="Sidebar.TButton", width=0)
        Button(actions, "Clear", lambda: self.select_all(False), style="Sidebar.TButton", width=0)
        self.selection = Label(actions, "", style="Muted.TLabel", expand=True, anchor="e")
        find = controls.row(padding=0,spacing=3)
        Label(find,'Find')
        self.event_search = TextInput(find,on_change=lambda _:self.filter_events(),expand=True,width=12)
        self.event_group = Dropdown(find,['All','Selected','Warnings','Watches','Advisories','Statements','Outlooks','Other'],
            width=10,on_change=lambda _:self.filter_events())
        self.event_presets = Dropdown(controls,['Event presets…','Severe Weather','Winter','Marine','Tropical'],
            on_change=self.apply_event_preset)
        self.filters = Form(controls, "Event types · selected location", expand=True, fill="both", padding=4)
        self.filters.body.spacing = 0
        self.filters.actions.widget.grid_configure(pady=0)
        self.filters.canvas.configure(background="#0b1424")
        self.choices = {}
        for event in list(DEFAULT_EVENTS) + [event for event in WEATHER_EVENTS if event not in DEFAULT_EVENTS]:
            self.add_event(event, event in self.profile.events)
        for event in self.profile.events:
            self.add_event(event, True)
        self.update_selection(save=False)
        refresh = controls.row(padding=0, spacing=4)
        Label(refresh,'NWS refresh',style='Muted.TLabel')
        self.refresh_interval_picker = Dropdown(refresh,[f'{seconds} seconds' for seconds in REFRESH_INTERVALS],
            value=f'{self.service.interval} seconds',on_change=self.set_refresh_interval,width=10)
        self.toggle = Button(refresh, "Start monitoring", self.toggle_monitoring,
                             style="Sidebar.Primary.TButton", width=0, expand=True)
        self.sound_testing = False
        self.sound_preferences = None
        self.speech_preferences = None
        self.tray_mode = Checkbox(controls, "Close window to tray",
                                  value=self.history.setting("close_to_tray", False), command=self.set_tray_mode)
        self.login = Checkbox(controls, "Launch at login (Windows)",
                              value=self.history.setting("launch_at_login", False), command=self.set_login)
        # Retain shared preference variables for the Settings popup without
        # reserving sidebar rows; the expanding event selector uses this space.
        self.tray_mode.hide()
        self.login.hide()
        content = body.column(padding=0, expand=True, fill="both", spacing=8)
        self.health = Label(content, "NO LIVE DATA • Start monitoring", style="Health.TLabel", wraplength=780)
        self.tabs = Tabs(content)
        overview_page = self.tabs.page('Locations')
        Label(overview_page, 'Your locations at a glance', style='Heading.TLabel')
        Label(overview_page, 'Selected alert types only · Highest-priority alert shown for each saved location',
              style='Muted.TLabel', wraplength=740)
        self.overview = LocationOverview(overview_page, self.open_alert)
        active = self.tabs.page("Active Alerts")
        self.active_count = Label(active, "Current alerts for enabled locations", style="Heading.TLabel")
        view_tools = active.row(padding=0,spacing=4)
        self.compact = Checkbox(view_tools,'Compact cards',value=self.history.setting('compact_cards',False) is True,
                                command=self.set_card_view)
        sorts = ['Priority • longest remaining','Soonest expiration','Newest issued','Urgency']
        saved_sort = self.history.setting('alert_sort',sorts[0])
        self.sort_mode = Dropdown(view_tools,sorts,
            value=saved_sort if saved_sort in sorts else sorts[0],on_change=self.set_alert_sort,expand=True)
        self.cards = Cards(active, self.open_alert)
        self.cards.compact = self.compact.get()
        self.cards.show_on_map = self.show_alert_on_map
        feed_page = self.tabs.page("Alert Feed")
        toolbar = feed_page.row(padding=0)
        self.counter = Label(toolbar, "0 alert changes", style="Muted.TLabel", expand=True)
        Button(toolbar, "Clear feed", self.clear_feed)
        self.empty = Label(feed_page, "Only alert changes appear here. Operational messages stay in the status bar.",
                           style="Muted.TLabel", wraplength=700)
        self.feed = TextArea(feed_page, readonly=True, max_lines=4000, expand=True, fill="both",
                             font=(self.font_family, 11), bg="#101c30", fg="#e5edf8", relief="flat",
                             padx=16, pady=12, borderwidth=0)
        tags = [(kind,color,12) for kind,color in EVENT_COLORS.items()] + [
            ('meta','#9aaec7',10),('body','#e5edf8',11)]
        for tag,color,size in tags:
            self.feed.text.tag_configure(tag, foreground=color, font=(self.font_family, size), spacing1=5, spacing3=6)
        map_page = self.tabs.page("Map")
        map_page.spacing = 4
        map_page.widget.configure(padding=8)
        tools = map_page.row(padding=0, spacing=4)
        Label(tools, "Affected areas & saved locations", style="Heading.TLabel", expand=True,wraplength=0)
        Button(tools, "+", lambda: self.map.zoom(1.5), width=0, style="Map.TButton")
        Button(tools, "−", lambda: self.map.zoom(1 / 1.5), width=0, style="Map.TButton")
        Button(tools, "Fit", lambda: self.map.fit(), width=0, style="Map.TButton")
        self.map = AlertMap(map_page, self.map_alert_selected)
        Button(tools,"Layers…",self.map.layer_settings,width=0,style="Map.TButton")
        self.radar = RadarPanel(map_page,self.map,connection_tools=tools)
        delivery_page = self.tabs.page("Notifications")
        self.delivery_panel = DeliveryPanel(delivery_page, self.history, self.retry_delivery, lambda: self.running)
        history_page = self.tabs.page("History")
        self.history_panel = HistoryPanel(history_page, self)
        self.demo = None
        self.demo_window = None
        self.location_wizard = None
        self.tabs.widget.bind("<<NotebookTabChanged>>", lambda _: self.refresh_records(),add="+")
        self.status = Label(self.app, "Ready • Choose locations and start monitoring.", style="Muted.TLabel", wraplength=1180)
        self.tray = Tray(self.app, self.show_window, self.close, self.on_tray_ready, self.tray_failed)
        self.app.root.protocol("WM_DELETE_WINDOW", self.window_closed)
        self.commands = ApplicationMenu(self)
        text_size = self.history.setting('control_text_size', 10)
        if type(text_size) is int and text_size in (10, 12, 14):
            self.commands.set_text_size(text_size, save=False)
        self.render_active()
        self.appearance.apply(self.appearance.name)
        self.tick()
        self.health.widget.bind('<Configure>',lambda e:self.health.configure(wraplength=max(240,e.width)))
        if self.app.root.winfo_screenwidth()<1100:
            self.toggle_sidebar()
    def open_demo(self):
        if self.demo_window is None:
            self.demo_window = Window(self.app, 'Stormwatch · Demo Mode', width=1000, height=760,
                                      min_width=850, min_height=680)
            self.demo = DemoPanel(self.demo_window, self)
            # Keep the simulation state and any in-flight preview attached to
            # live widgets when the popup closes. Final cleanup belongs to Quit.
            self.demo_window.root.protocol('WM_DELETE_WINDOW', self.demo_window.root.withdraw)
        self.demo_window.root.deiconify()
        self.demo_window.root.lift()
        return self.demo_window

    def _style(self):
        style = self.app.style
        style.configure(".", background="#0b1424", foreground="#e5edf8", font=(self.font_family, 10))
        style.configure("TNotebook", background="#0b1424", borderwidth=0)
        style.configure("TNotebook.Tab", background="#243a56", foreground="#e5edf8", padding=(14, 8))
        style.map("TNotebook.Tab", background=[("selected", "#176caa"), ("active", "#355474")],
                  foreground=[("selected", "#ffffff"), ("active", "#ffffff")])
        style.configure("TCombobox", fieldbackground="#142238", background="#243a56", foreground="#e5edf8")
        style.map("TCombobox", fieldbackground=[("readonly", "#142238")], foreground=[("readonly", "#e5edf8")])
        style.configure("Treeview", background="#101c30", fieldbackground="#101c30", foreground="#e5edf8", rowheight=28)
        style.configure("Treeview.Heading", background="#243a56", foreground="#e5edf8", padding=8)
        style.map("Treeview", background=[("selected", "#176caa")], foreground=[("selected", "#ffffff")])
        style.configure("TEntry", fieldbackground="#ffffff", foreground="#000000", insertcolor="#000000", padding=6)
        style.map("TEntry", foreground=[("disabled", "#555555"), ("!disabled", "#000000")],
                  fieldbackground=[("disabled", "#eeeeee"), ("!disabled", "#ffffff")])
        style.configure("Input.TCombobox", fieldbackground="#ffffff", foreground="#000000", insertcolor="#000000")
        style.map("Input.TCombobox", foreground=[("disabled", "#555555"), ("!disabled", "#000000")],
                  fieldbackground=[("disabled", "#eeeeee"), ("!disabled", "#ffffff")])
        style.configure("TFrame", background="#0b1424")
        style.configure("Panel.TFrame", background="#142238")
        style.configure("TLabel", background="#0b1424")
        style.configure("Brand.TLabel", font=(self.font_family, 23, "bold"), foreground="#f5f9ff")
        style.configure("Health.TLabel", font=(self.font_family, 10, "bold"))
        style.configure("Heading.TLabel", font=(self.font_family, 13, "bold"))
        style.configure("Muted.TLabel", foreground="#9aaec7")
        style.configure("Status.TLabel", foreground="#85caff", font=(self.font_family, 10, "bold"))
        style.configure("TButton", padding=(12, 9), background="#243a56")
        style.map("TButton", background=[("active", "#355474")])
        style.configure("Primary.TButton", background="#176caa", font=(self.font_family, 10, "bold"))
        style.configure("Map.TButton", padding=(6, 3))
        style.configure("Sidebar.TButton", padding=(8, 4))
        style.configure("Sidebar.Primary.TButton", padding=(8, 5))
        style.configure("TCheckbutton", padding=3)
        style.map("TCheckbutton", background=[("active", "#243a56")])








    def add_event(self, event, selected=False):
        if event not in self.choices:
            self.choices[event] = Checkbox(self.filters.body, event, value=selected,
                                           command=lambda _: self.update_selection())

    def selected_events(self):
        return {event for event, choice in self.choices.items() if choice.get()}

    @defer_store_work
    def update_selection(self, save=True):
        self.selection.set(f"{len(self.selected_events())} event types selected")
        if save and not self.loading_profile:
            self.profile.events = sorted(self.selected_events())
            self.history.update_profile_events(self.profile.id,self.profile.events)
            self.rule_summary.set(self.profile.rules_summary())
            self.render_active()
        self.filter_events()

    def select_all(self, value):
        for choice in self.choices.values():
            choice.set(value)
        self.update_selection()

    @defer_store_work
    def choose_profile(self, name):
        self.profile = next(p for p in self.profiles if p.name == name)
        self.loading_profile = True
        for event in self.profile.events:
            self.add_event(event)
        for event, control in self.choices.items():
            control.set(event in self.profile.events)
        self.location_summary.set(self.profile.summary())
        self.rule_summary.set(self.profile.rules_summary())
        self.update_selection(save=False)
        self.loading_profile = False
        self.event_presets.set('Event presets…')
        self.filter_events()

    @defer_store_work
    def refresh_profiles(self, profile=None):
        self.profiles = self.history.profiles()
        self.profile = next((p for p in self.profiles if profile is not None and p.id==profile.id),self.profiles[0])
        values = tuple(p.name for p in self.profiles)
        self.profile_picker.values = values
        self.profile_picker.configure(values=values)
        self.profile_picker.set(self.profile.name)
        self.choose_profile(self.profile.name)
        self.render_active()

    def add_location(self):
        if self.location_wizard and not self.location_wizard.window._closed:
            self.location_wizard.window.root.lift()
        else:
            self.location_wizard = LocationWizard(self)

    def edit_sound_events(self):
        if self.sound_preferences and not self.sound_preferences.window._closed:
            self.sound_preferences.window.close()
        self.sound_preferences = SoundPreferences(self)

    def edit_speech_events(self):
        if self.speech_preferences and not self.speech_preferences.window._closed:
            self.speech_preferences.window.close()
        self.speech_preferences = SoundPreferences(self,'speech')

    def edit_profile(self, new=False):
        profile = LocationProfile(name="New location") if new else replace(self.profile)
        window = Window(self.app, "Add location" if new else "Edit location", width=570, height=730)
        form = Form(window, scrollable=True, expand=True, fill="both")
        form.add_text("name", "Location name", profile.name)
        form.add_text("states", "State codes, comma separated (e.g. IL, IN)", ", ".join(profile.states))
        form.add_text("counties", "County UGC codes (e.g. ILC031), comma separated", ", ".join(profile.counties))
        form.add_text("lat", "Latitude (optional)", "" if profile.latitude is None else str(profile.latitude))
        form.add_text("lon", "Longitude (optional)", "" if profile.longitude is None else str(profile.longitude))
        form.add_checkbox("enabled", "Monitor this location", profile.enabled, text="Enabled")
        form.add_checkbox("sound", "Sound for selected event types", profile.sound, text="Play alert.mp3")
        form.add_checkbox("desktop", "Desktop notifications", profile.desktop, text="Send desktop notifications")
        add_rule_fields(form, profile)
        note = form.add_label("Blank geography monitors all US alerts. When combined, filters must all match.\n"
                              "A coordinate is resolved through NWS when saved. County codes identify counties exactly.", wraplength=470)

        def complete(zones, candidate):
            if window._closed:
                return
            candidate.zones = zones
            self.history.save_profile(candidate)
            self.refresh_profiles(candidate)
            window.close()
            self.status.set("Location saved • New preferences apply on the next refresh.")

        def failure(error):
            if not window._closed:
                note.set(str(error))
                save.enable()

        def submit():
            values = form.get()
            try:
                candidate = replace(profile, name=values["name"], states=values["states"].split(","),
                                    counties=values["counties"].split(","),
                                    latitude=float(values["lat"]) if values["lat"].strip() else None,
                                    longitude=float(values["lon"]) if values["lon"].strip() else None,
                                    enabled=values["enabled"], sound=values["sound"], desktop=values["desktop"],
                                    sound_events=next((p.sound_events for p in self.profiles if p.id == profile.id),profile.sound_events),
                                    speech=next((p.speech for p in self.profiles if p.id == profile.id),profile.speech),
                                    speech_events=next((p.speech_events for p in self.profiles if p.id == profile.id),profile.speech_events),
                                    **rule_values(values)).validate()
                if any(p.name == candidate.name and p.id != candidate.id for p in self.profiles):
                    raise ValueError("A location with this name already exists.")
                if candidate.latitude is None:
                    complete([], candidate)
                else:
                    save.disable()
                    note.set("Resolving NWS zones…")
                    self.app.run_in_thread(self.resolve_location, candidate,
                                           on_result=lambda zones: complete(zones, candidate), on_error=failure)
            except (ValueError, sqlite3.Error) as error:
                failure(error)
        def choose_counties():
            states = [s.strip().upper() for s in form.get()["states"].split(",") if s.strip()]
            try:
                LocationProfile(states=states).validate()
                if not states:
                    raise ValueError("Enter one or more state codes first, then choose counties.")
            except ValueError as error:
                failure(error)
                return
            note.set("Loading county names from NWS…")

            def loaded(counties):
                if window._closed:
                    return
                picker = Window(self.app, "Choose counties", width=550, height=600)
                fields = Form(picker, "County names", expand=True, fill="both")
                chosen = {s.strip().upper() for s in form.get()["counties"].split(",")}
                choices = [(code, Checkbox(fields.body, f"{name} ({code})", value=code in chosen))
                           for code, name in counties]

                def apply():
                    form.fields["counties"].control.set(", ".join(code for code, control in choices if control.get()))
                    picker.close()
                fields.add_button("Use selected counties", apply)
                note.set("County names loaded. Select the counties to monitor.")
            self.app.run_in_thread(self.load_counties, states, on_result=loaded, on_error=failure)

        form.add_button("Choose counties", choose_counties)
        save = form.add_button("Save location", submit)
        form.add_button("Cancel", window.close)

    def load_counties(self, states):
        with self.network_lock:
            return self.service.list_counties(states)

    def resolve_location(self, profile):
        with self.network_lock:
            return self.service.resolve_location(profile.latitude, profile.longitude)

    @defer_store_work
    def remove_profile(self):
        if len(self.profiles) == 1:
            self.status.set("Keep at least one location. Edit or disable this location instead.")
            return
        if self.app.confirm(f"Remove {self.profile.name}?", title="Remove location"):
            self.history.delete_profile(self.profile.id)
            self.refresh_profiles()

    @defer_store_work
    def set_refresh_interval(self, value):
        previous = f'{self.service.interval} seconds'
        if self.running:
            self.refresh_interval_picker.set(previous)
            self.status.set('Pause monitoring before changing the NWS refresh interval.')
            return False
        choices = {f'{seconds} seconds':seconds for seconds in REFRESH_INTERVALS}
        if value not in choices:
            self.refresh_interval_picker.set(previous)
            self.status.set('Choose an NWS refresh interval of 30, 60, 90, or 120 seconds.')
            return False
        try:
            self.history.save_setting('nws_refresh_interval',choices[value])
        except sqlite3.Error:
            self.refresh_interval_picker.set(previous)
            self.status.set('Could not save the NWS refresh interval. Try again before starting monitoring.')
            return False
        self.service.interval = choices[value]
        self.refresh_interval_picker.set(value)
        self.status.set(f'NWS refresh set to {value} · Applies when monitoring starts.')
        return True

    @defer_store_work
    def toggle_monitoring(self):
        if self.running:
            self.running = False
            self.generation += 1
            self.speech_pending.clear()
            self.speaker.stop()
            if self.timer is not None:
                self.app.root.after_cancel(self.timer)
                self.timer = None
            self.next_refresh = None
            self.refresh_interval_picker.enable()
            self.toggle.set("Start monitoring")
            self.state.set("●  PAUSED")
            self.status.set("Paused • Saved alerts remain visible.")
        elif self.busy:
            self.status.set("Finishing the previous request. Please start again in a moment.")
        elif not any(p.enabled and p.events for p in self.profiles):
            self.status.set("Enable at least one location and select an event type.")
        else:
            if not self.set_refresh_interval(self.refresh_interval_picker.get()):
                return
            self.running = True
            self.speech_started_at = datetime.now(timezone.utc)
            self.speech_pending.clear()
            self.refresh_interval_picker.disable()
            self.toggle.set("Pause monitoring")
            self.state.set("●  MONITORING")
            self.poll()
        self.update_health()
        self.delivery_panel.refresh()





    def send_notifications(self, generation, jobs, manual=False):
        voice = [job for job in jobs if job[3]=='speech']
        errors = self.send_speech_batch(generation,voice,manual) if voice else []
        jobs = [job for job in jobs if job[3]!='speech']
        grouped = {}
        for alert, version, _, channel, kind in jobs:
            grouped[(alert["id"], version, channel)] = (alert, kind)
        for (alert_id, version, channel), (alert, kind) in grouped.items():
            with (nullcontext() if channel == 'speech' else self.sound_lock):
                if not self.running or generation != self.generation:
                    break
                if channel == 'speech' and not issued_after(alert,self.speech_started_at):
                    continue
                if not self.history.is_current(alert_id, version):
                    continue
                if channel in ('sound','speech') and self.history.get_alert(alert_id)['status'] != 'Active':
                    continue
                end = expiration_of(alert)
                if end and end <= datetime.now(timezone.utc) and kind != "Cancelled":
                    continue
                profiles = []
                for profile in list(self.profiles):
                    if not profile.matches(alert) or not profile.allows(alert, channel):
                        continue
                    row = self.history.delivery(alert_id, version, profile.id, channel)
                    if row and row["state"] in ("pending", "failed"):
                        profiles.append(profile)
                if not profiles:
                    continue
                submission = self.history.submission(alert_id, version, channel)
                if submission["state"] == "sent" or (submission["attempts"] >= 3 and not manual):
                    self.history.share_submission(alert_id, version, channel, profiles, submission)
                    continue
                if manual and not any(self.history.delivery(alert_id, version, p.id, channel)["state"] == "failed" for p in profiles):
                    continue
                names = ", ".join(p.name for p in profiles)
                for profile in profiles:
                    choice = decisions(profile,alert,kind)[channel]
                    self.history.record_decision(alert_id,version,profile,channel,**choice)
                try:
                    if channel == "sound":
                        self.service.deliver_sound()
                    elif channel == 'speech':
                        self.speaker.speak(announcement(alert,profiles,kind),
                                           should_continue=lambda:self.running and generation == self.generation and self.speech_fresh())
                    else:
                        self.service.deliver_desktop(alert, kind, names)
                except SpeechCancelled:
                    continue
                except Exception as error:
                    self.history.combined_receipt(alert_id, version, channel, profiles, error)
                    errors.append(f"{names} {channel}: {error}")
                else:
                    self.history.combined_receipt(alert_id, version, channel, profiles)
        return errors

    def speech_eligible(self, job):
        alert,version,_,_,kind = job
        if kind in ('Expired','Cancelled','Superseded','No longer active') or (alert.get('message_type') or '').lower()=='cancel':
            return False
        end = expiration_of(alert)
        return bool(issued_after(alert,self.speech_started_at) and
                    (end is None or end>datetime.now(timezone.utc)) and self.history.is_active(alert['id'],version))

    def send_speech_batch(self, generation, jobs, manual=False):
        grouped, errors = {}, []
        for job in jobs:
            grouped.setdefault((job[0]['event'],tuple(sorted(p.id for p in self.profiles
                if p.matches(job[0]) and p.allows(job[0],'speech')))),{})[(job[0]['id'],job[1])] = job
        for members in grouped.values():
            if not self.running or generation!=self.generation or not self.speech_fresh():
                break
            ready = []
            for job in members.values():
                if not self.speech_eligible(job):
                    continue
                alert,version,_,_,kind = job
                profiles = []
                for profile in list(self.profiles):
                    if profile.matches(alert) and profile.allows(alert,'speech'):
                        row = self.history.delivery(alert['id'],version,profile.id,'speech')
                        if row and row['state'] in ('pending','failed') and (not manual or row['state']=='failed'):
                            profiles.append(profile)
                if not profiles:
                    continue
                submission = self.history.submission(alert['id'],version,'speech')
                if submission['state']=='sent' or (submission['attempts']>=3 and not manual):
                    self.history.share_submission(alert['id'],version,'speech',profiles,submission)
                    continue
                for profile in profiles:
                    self.history.record_decision(alert['id'],version,profile,'speech',**decisions(profile,alert,kind)['speech'])
                ready.append((job,profiles))
            if not ready:
                continue
            try:
                self.speaker.speak(batch_announcement([job[0] for job,_ in ready],
                    list({p.id:p for _,profiles in ready for p in profiles}.values())),
                    should_continue=lambda:self.running and generation==self.generation and self.speech_fresh()
                        and all(self.speech_eligible(job) for job,_ in ready))
            except SpeechCancelled:
                if self.running and generation==self.generation:
                    remaining = [job for job,_ in ready if self.speech_eligible(job)]
                    self.app.call_soon(self.enqueue_speech,generation,remaining,True)
                continue
            except Exception as error:
                with self.history.transaction():
                    for job,profiles in ready:
                        if self.speech_eligible(job):
                            self.history.combined_receipt(job[0]['id'],job[1],'speech',profiles,error)
                errors.append(f'{ready[0][0][0]["event"]} speech: {error}')
            else:
                with self.history.transaction():
                    for job,profiles in ready:
                        if self.speech_eligible(job):
                            self.history.combined_receipt(job[0]['id'],job[1],'speech',profiles)
        return errors

    def prune_speech(self):
        for key,(generation,members) in list(self.speech_pending.items()):
            valid = {identity:job for identity,job in members.items()
                     if generation==self.generation and self.speech_eligible(job)}
            if valid:
                self.speech_pending[key] = (generation,valid)
            else:
                self.speech_pending.pop(key,None)
        if self.speech_current_jobs and not all(self.speech_eligible(job) for job in self.speech_current_jobs):
            self.speaker.stop()

    def enqueue_speech(self, generation, jobs, requeue=False):
        if generation!=self.generation or not self.running:
            return
        self.prune_speech()
        for job in sorted(jobs,key=lambda item:threat_priority(item[0]),reverse=True):
            identity = (job[0]['id'],job[1])
            if (not requeue and identity in (self.speech_current or ())) or not self.speech_eligible(job):
                continue
            key = (generation,job[0]['event'])
            if key not in self.speech_pending and len(self.speech_pending)>=32:
                lowest = min(self.speech_pending,key=lambda k:max(threat_priority(j[0]) for j in self.speech_pending[k][1].values()))
                if threat_priority(job[0])<=max(threat_priority(j[0]) for j in self.speech_pending[lowest][1].values()):
                    continue
                self.speech_pending.pop(lowest)
            members = self.speech_pending.setdefault(key,(generation,{}))[1]
            if len(members)<1000:
                members[identity] = job
        self.start_speech()

    def start_speech(self):
        if self.speech_busy or not self.running or self.app._closed or not self.speech_pending:
            return
        if not self.speech_fresh():
            return
        self.prune_speech()
        if not self.speech_pending:
            return
        key = max(self.speech_pending,key=lambda k:max(threat_priority(j[0]) for j in self.speech_pending[k][1].values()))
        generation,members = self.speech_pending.pop(key)
        self.speech_current_jobs = list(members.values())
        self.speech_busy, self.speech_current = True,frozenset(members)
        try:
            self.speech_future = self.app.run_in_thread(self.send_notifications,generation,self.speech_current_jobs,critical=True,
                on_result=self.speech_done,on_error=self.speech_failed)
        except RuntimeError:
            self.speech_busy, self.speech_current = False,None
            self.speech_current_jobs = []
            self.speech_pending[key] = (generation,members)
            self.status.set('Speech is waiting for a background worker. It will be checked on the next refresh.')

    def speech_fresh(self):
        return bool(self.last_success and not self.last_error and
                    (datetime.now(timezone.utc)-self.last_success).total_seconds()<max(120,self.service.interval*2))

    def speech_done(self, errors):
        self.speech_busy, self.speech_current = False,None
        self.speech_current_jobs = []
        self.refresh_records()
        if errors:
            self.status.set('Speech failed · See Notifications for the reason and retry options.')
        self.start_speech()

    def speech_failed(self, error):
        self.speech_busy, self.speech_current = False,None
        self.speech_current_jobs = []
        self.status.set(f'Speech worker failed: {error}')
        self.start_speech()

    def test_speech(self, feedback=None):
        if self.speech_busy:
            if feedback:
                feedback('A voice announcement is already running. Try again when it finishes.')
            return
        self.speech_busy = True
        def finished(error=None):
            self.speech_busy = False
            message = f'Voice test failed: {error}' if error else 'Voice test completed. Check your audio output.'
            self.status.set(message)
            if feedback:
                feedback(message)
            self.start_speech()
        try:
            self.speech_future = self.app.run_in_thread(self.speaker.speak,
                'Stormwatch voice preview. This is a test, not a weather alert.',
                on_result=lambda _:finished(),on_error=finished)
        except RuntimeError:
            finished('The background queue is busy. Try Test voice again shortly.')

    def delivered(self, errors):
        self.delivery_busy = False
        self.refresh_records()
        if not errors:
            self.status.set("Notification check complete · See Notifications for channel results.")
        if errors:
            self.status.set("Notification submission failed · See Notifications for remaining retries. " + errors[0])

    def delivery_failed(self, error):
        self.delivery_busy = False
        self.delivery_panel.refresh()
        self.status.set(f"Notification worker failed: {error}")

    @defer_store_work
    def retry_delivery(self, row):
        if not self.running:
            self.status.set("Start monitoring before retrying a live notification channel.")
            return
        if (self.speech_busy if row['channel'] == 'speech' else self.delivery_busy):
            self.status.set("A notification submission is already in progress. Try again when it finishes.")
            return
        fresh = self.last_success and not self.last_error and (datetime.now(timezone.utc) - self.last_success).total_seconds() < max(120, self.service.interval * 2)
        current = self.history.get_alert(row["id"])
        profile = next((p for p in self.profiles if p.id == row["profile"]), None)
        receipt = self.history.delivery(row["id"], row["version"], row["profile"], row["channel"])
        if not fresh or not current or current["version"] != row["version"] or current["status"] not in ("Active", "Cancelled"):
            self.status.set("Only current notifications with fresh live data can be retried. Wait for a successful refresh.")
            return
        if row['channel'] in ('sound','speech') and current['status'] != 'Active':
            self.status.set('Cancelled alerts do not play sound or speech.')
            return
        if not profile or not profile.matches(row["alert"]) or not profile.allows(row["alert"], row["channel"]):
            self.status.set("This notification channel is disabled or no longer matches an enabled location.")
            return
        if not receipt or receipt["state"] != "failed":
            self.status.set("Only failed channels can be retried; successful submissions will not be replayed.")
            return
        if row['channel'] == 'speech':
            if not issued_after(row['alert'],self.speech_started_at):
                self.status.set('Speech only covers alerts issued after this monitoring session started.')
                return
            for _,members in self.speech_pending.values():
                members.pop((row['id'],row['version']),None)
            self.speech_busy = True
            self.speech_current = frozenset({(row['id'],row['version'])})
            self.speech_current_jobs = [(row['alert'],row['version'],profile.id,'speech',row['kind'])]
            try:
                self.speech_future = self.app.run_in_thread(self.send_notifications,self.generation,
                    [(row['alert'],row['version'],profile.id,'speech',row['kind'])],True,
                    on_result=self.speech_done,on_error=self.speech_failed)
            except RuntimeError:
                self.speech_busy, self.speech_current = False,None
                self.speech_current_jobs = []
                self.status.set('The background queue is busy. Try the speech retry again shortly.')
            return
        self.delivery_busy = True
        self.status.set(f"Retrying {row['channel']} once for {profile.name}…")
        self.delivery_future = self.app.run_in_thread(self.send_notifications, self.generation,
            [(row["alert"], row["version"], profile.id, row["channel"], row["kind"])], True,
            on_result=self.delivered, on_error=self.delivery_failed)



    def matching_rows(self):
        result = []
        for row in self.history.rows(active_only=True):
            names = [p.name for p in self.profiles if p.matches(row["alert"])]
            if names:
                result.append(dict(row, locations=names))
        return sorted(result,key=lambda row:active_sort_key(row,self.sort_mode.get() if hasattr(self,"sort_mode") else "Priority • longest remaining"))

    @defer_store_work
    def render_active(self):
        if len(self.history.active_ids())>500:
            profiles,mode = deepcopy(self.profiles),self.sort_mode.get()
            self.active_query.request(lambda:active_rows(self.history,profiles,mode),self.apply_active_rows,
                                     lambda error:self.status.set(f'Could not prepare active view: {error}'))
            return
        self.active_query.invalidate()
        self.apply_active_rows(self.matching_rows())

    def apply_active_rows(self, rows):
        plan = getattr(rows,"map_plan",None)
        if self.app._closed:
            return
        now = datetime.now(timezone.utc)
        rows = [row for row in rows if (end := expiration_of(row["alert"])) is None or end>now]
        self.snapshot = {row["id"]: row["alert"] for row in rows}
        self.active_count.set(f"{len(rows)} active alerts · {sum(p.enabled for p in self.profiles)} enabled locations")
        self.cards.render(rows)
        self.overview.render_locations(self.profiles, rows)
        self.map.render(rows, self.profiles,plan=plan)
        if hasattr(self, "history_panel"):
            self.refresh_records()

    def refresh_records(self):
        if self.app._closed or not hasattr(self,'history_panel'):
            return
        selected = self.tabs.widget.tab(self.tabs.widget.select(),'text')
        if selected in ('History','Notifications'):
            revision = (self.history.revision,self.running)
            if self._record_revisions.get(selected)==revision:
                return
            self._record_revisions[selected] = revision
            (self.history_panel if selected=='History' else self.delivery_panel).refresh()
        elif selected == 'Map':
            self.enrich_map()





    def append_alert(self, alert, kind="New", locations=()):
        self.append_alerts([(alert,kind,locations)])

    def append_alerts(self, messages):
        if not messages:
            return
        self.empty.hide()
        self.count += len(messages)
        self.counter.set(f"{self.count} alert changes")
        segments = []
        def excerpt(value, limit):
            return value if len(value) <= limit else value[:limit] + "… [Full text in alert details]"
        for alert, kind, locations in messages:
            tag = event_category(alert['event']) or 'other'
            summary = self.history.change_summary(alert, kind)
            segments.extend([
                (f"{kind.upper()}  ·  {alert['event']}\n",tag),
                (f"{datetime.now():%b %d · %H:%M:%S}  •  {alert['severity']}  •  {', '.join(locations)}\n","meta"),
                (f"What changed: {summary}\n" if summary else '', 'body'),
                (f"{excerpt(alert['headline'],2000)}\n\n{excerpt(alert['area'],4000)}\n\n{excerpt(alert['instruction'],8000)}\n","body"),
                (f"Expires: {alert['expires']}\n{alert['url']}\n\n{'─' * 45}\n\n","meta")])
        self.feed.append_segments(segments)

    def open_alert(self, alert, summary=None):
        title = ("SIMULATION · " if alert.get("simulated") else "") + alert["event"]
        window = Window(self.app, title, width=740, height=630)
        Label(window, title, style="Heading.TLabel")
        details = TextArea(window, readonly=True, expand=True, fill="both", bg="#101c30", fg="#e5edf8", padx=16, pady=12)
        summary = self.history.change_summary(alert) if summary is None else summary
        details.set((f'What changed: {summary}\n\n' if summary else '') + f"{alert['headline']}\n\n{alert['area']}\n\nSeverity: {alert['severity']}\nIssued: {alert['sent']}\n"
                    f"Expires: {alert['expires']}\n\n{alert.get('description', '')}\n\n{alert['instruction']}")
        Button(window,'Why did I get this?',lambda:self.show_notification_explanation(alert))
        from urllib.parse import urlparse
        if urlparse(alert["url"]).scheme == "https":
            Button(window, "Open official alert", lambda: webbrowser.open(alert["url"]))

    def open_metrics(self):
        if self.metrics is None:
            self.metrics = Metrics(self)
        self.metrics.show()

    def show_notification_explanation(self, alert):
        window = Window(self.app,'Notification explanations',width=780,height=620)
        Label(window,'Why did I get this? / Why was it silent?',style='Heading.TLabel')
        text = TextArea(window,readonly=True,expand=True,fill='both',bg='#101c30',fg='#e5edf8',padx=14,pady=12,autoscroll=False)
        text.set(explanation_text(self.history,alert,self.profiles))
        Button(window,'Close',window.close)

    def clear_feed(self):
        self.feed.clear()
        self.count = 0
        self.counter.set("0 alert changes")
        self.empty.show()

    def test_sound(self):
        if self.sound_testing:
            return
        self.sound_testing = True
        self.status.set("Testing alert.mp3…")
        try:
            self.app.run_in_thread(self.play_test, on_result=lambda _: self.sound_finished(), on_error=self.sound_failed)
        except RuntimeError as error:
            self.sound_failed(error)

    def play_test(self):
        with self.sound_lock:
            self.service.deliver_sound()

    def sound_finished(self):
        self.sound_testing = False
        self.status.set("Sound test started • Check your audio device.")

    def sound_failed(self, error):
        self.sound_testing = False
        self.status.set(f"Sound test failed: {error}")

    def hide_to_tray(self):
        if self.tray_ready:
            self.hidden = True
            self.app.root.withdraw()
        else:
            self.status.set("Starting system tray… The window will stay open if the tray is unavailable.")
            self.tray.start()

    def on_tray_ready(self):
        self.tray_ready = True
        self.hide_to_tray()

    def tray_failed(self, error):
        self.tray_ready = False
        self.tray_mode.set(False)
        self.show_window()
        self.status.set(f"System tray unavailable: {error}. The window remains open.")

    def show_window(self):
        self.hidden = False
        self.app.root.deiconify()
        self.app.root.lift()

    def set_tray_mode(self, enabled):
        self.history.save_setting("close_to_tray", enabled)
        self.status.set("Closing the window will minimize it to the tray." if enabled else "Closing the window will quit Stormwatch.")

    def set_login(self, enabled):
        try:
            set_login(enabled)
            self.history.save_setting("launch_at_login", enabled)
            self.status.set("Launch at login enabled." if enabled else "Launch at login disabled.")
        except Exception as error:
            self.login.set(not enabled)
            self.status.set(str(error))

    def window_closed(self):
        if self.tray_mode.get():
            self.hide_to_tray()
        else:
            self.close()

    def close(self):
        if self.app._closed:
            return
        pending = getattr(self,'_store_waiters',{})
        self._exit_profile = replace(self.profile,events=sorted(self.selected_events())) if 'update_selection' in pending else None
        self._exit_settings = {}
        if 'set_card_view' in pending:self._exit_settings['compact_cards'] = self.compact.get()
        if 'set_alert_sort' in pending:self._exit_settings['alert_sort'] = self.sort_mode.get()
        picked = self.refresh_interval_picker.get()
        if 'set_refresh_interval' in pending and picked in {f'{n} seconds' for n in REFRESH_INTERVALS}:
            self._exit_settings['nws_refresh_interval'] = int(picked.split()[0])
        self.running = False
        self.generation += 1
        self.boundaries.stop_event.set()
        if isinstance(self.service,WeatherService):
            self.service.stop_event.set()
        for timer in (self.timer, self.processing_timer, self.health_timer,*getattr(self,'_store_waiters',{}).values()):
            if timer is not None:
                self.app.root.after_cancel(timer)
        self.tray.stop()
        self.speech_pending.clear()
        self.speaker.stop()
        self.radar.close()
        self.commands.close()
        self.active_query.close()
        self.history_panel.query.close()
        self.delivery_panel.query.close()
        self.history_panel.cancel_download()
        self.app.root._stormwatch_icons.clear()
        self.app.close()
        self.cleanup_thread = threading.Thread(target=self.cleanup, daemon=True)
        self.cleanup_thread.start()

    def cleanup(self):
        if self.boundary_future is not None:
            try:
                self.boundary_future.result()
            except Exception:
                pass
        self.active_query.wait()
        self.delivery_panel.query.wait()
        if self.speech_future is not None:
            try:
                self.speech_future.result()
            except Exception:
                pass
        if self.delivery_future is not None:
            try:
                self.delivery_future.result()
            except Exception:
                pass
        if self.demo is not None:
            self.demo.close()
        self.history_panel.close()
        self.commands.wait()
        if self.metrics is not None:
            self.metrics.wait()
        for error in self.preference_changes.wait():
            self.service.logger.error('Could not save requested preferences: %s',error)
        try:
            if self._exit_profile is not None:
                current = next((p for p in self.history.profiles() if p.id==self._exit_profile.id),None)
                if current is not None:
                    self.history.save_profile(replace(current,events=self._exit_profile.events))
            for name,value in self._exit_settings.items():
                self.history.save_setting(name,value)
        except (sqlite3.Error,ValueError) as error:
            self.service.logger.error('Could not save exit preferences: %s',error)
        finally:
            with self.network_lock:
                self.service.session.close()
            with self.sound_lock:
                pygame.mixer.quit()
                self.history.close()

    def run(self):
        self.app.run()


def main():
    parser = argparse.ArgumentParser(description="Stormwatch weather dashboard")
    parser.add_argument("--test-tornado", action="store_true", help="Test alert sound without the GUI")
    parser.add_argument("--test-hurricane", action="store_true", help="Test alert sound without the GUI")
    parser.add_argument("--monitor", action="store_true", help="Start monitoring saved locations immediately")
    parser.add_argument('--restore-backup',metavar='SQLITE_BACKUP',help='Restore a validated backup before normal startup')
    parser.add_argument('--self-test',metavar='REPORT_JSON',help='Run an offline packaged-app acceptance check')
    args = parser.parse_args()
    if args.self_test:
        from packaged_check import run
        run(args.self_test)
        return
    if args.test_tornado or args.test_hurricane:
        service = WeatherService()
        try:
            service.deliver_sound()
            while pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.time.wait(100)
        finally:
            pygame.mixer.quit()
            service.session.close()
    else:
        from single_instance import InstanceLock
        from application_paths import state_directory
        from storage_tools import apply_pending_restore, stage_restore
        try:
            instance = InstanceLock(state_directory())
        except RuntimeError as error:
            from tkinter import Tk, messagebox
            root = Tk()
            root.withdraw()
            configure_identity(root)
            messagebox.showinfo('Stormwatch',str(error),parent=root)
            root.destroy()
            return
        try:
            if args.restore_backup:
                stage_restore(state_directory()/'processed-alerts.sqlite3',args.restore_backup)
            apply_pending_restore(state_directory()/'processed-alerts.sqlite3')
            ui = StormwatchApp()
            if not ui.history.setting('readiness_seen',False):
                def first_run():
                    __import__('workspace_tools').readiness(ui)
                    ui.history.save_setting('readiness_seen',True)
                ui.app.after(250,first_run)
            if args.monitor:
                ui.toggle_monitoring()
            ui.run()
        finally:
            if 'ui' in locals() and hasattr(ui,'cleanup_thread'):
                ui.cleanup_thread.join(timeout=45)
            instance.close()


if __name__ == "__main__":
    main()
