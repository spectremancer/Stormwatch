"""Stormwatch: location-aware desktop weather monitoring built with TkFlow."""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import sqlite3
import threading
import webbrowser
from tkinter import font as tkfont

import pygame

from TkFlow import App, Button, Checkbox, Dropdown, Form, Label, TextArea, Window
from WeatherService import WeatherService
from alert_history import AlertHistory, instant
from dashboard_views import AlertMap, Cards, Tabs
from desktop import Tray, set_login
from location_wizard import LocationWizard
from delivery_panel import DeliveryPanel
from demo import DemoPanel
from locations import LocationProfile

EVENT_FAMILIES = (
    "Tornado", "Severe Thunderstorm", "Hurricane", "Tropical Storm",
    "Flash Flood", "Flood", "Coastal Flood", "Winter Storm", "Blizzard",
    "Ice Storm", "Snow Squall", "High Wind", "Extreme Wind", "Dust Storm",
    "Excessive Heat", "Extreme Heat", "Extreme Cold", "Freeze", "Hard Freeze",
    "Wind Chill", "Red Flag", "Fire Weather", "Storm", "Gale", "Tsunami",
)
CRITICAL = {"Tornado Warning", "Tornado Watch", "Hurricane Warning", "Hurricane Watch"}


class StormwatchApp:
    def __init__(self, service=None, history=None):
        self.service = service or WeatherService(interval=60)
        self.history = history if history is not None else AlertHistory()
        self.profiles = self.history.profiles()
        if not self.profiles:
            self.profiles = [LocationProfile()]
            self.history.save_profile(self.profiles[0])
        self.profile = self.profiles[0]
        self.app = App("Stormwatch · Weather intelligence", width=1260, height=900,
                       min_width=1000, min_height=760, padding=20, spacing=12, theme="clam")
        self.snapshot = {}
        self.initialized = False
        self.running = self.busy = False
        self.generation = 0
        self.timer = None
        self.health_timer = None
        self.last_success = self.next_refresh = None
        self.last_error = self.coverage_warning = ""
        self.count = 0
        self.sound_lock = threading.Lock()
        self.delivery_busy = False
        self.delivery_future = None
        self.cancel_since = datetime.now(timezone.utc) - timedelta(minutes=15)
        self.loading_profile = False
        self.tray_ready = False
        self.hidden = False
        self.font_family = tkfont.nametofont("TkDefaultFont").actual("family")
        self._style()
        header = self.app.row(padding=0)
        brand = header.column(padding=0, expand=True)
        Label(brand, "STORMWATCH", style="Brand.TLabel")
        Label(brand, "Weather intelligence • Your locations, in view", style="Muted.TLabel")
        self.state = Label(header, "●  PAUSED", style="Status.TLabel")
        Button(header, "Minimize to tray", self.hide_to_tray)
        Button(header, "Quit", self.close)
        body = self.app.row(padding=0, expand=True, fill="both", spacing=20)
        controls = body.column(padding=12, spacing=8, style="Panel.TFrame")
        Label(controls, "Saved locations", style="Heading.TLabel")
        self.profile_picker = Dropdown(controls, [p.name for p in self.profiles],
                                       on_change=self.choose_profile)
        self.location_summary = Label(controls, self.profile.summary(), style="Muted.TLabel", wraplength=290)
        buttons = controls.row(padding=0)
        Button(buttons, "Add", self.add_location)
        Button(buttons, "Edit", self.edit_profile)
        Button(buttons, "Remove", self.remove_profile)
        Label(controls, "All enabled locations monitor together.", style="Muted.TLabel")
        actions = controls.row(padding=0)
        Button(actions, "Select all", lambda: self.select_all(True))
        Button(actions, "Clear", lambda: self.select_all(False))
        self.filters = Form(controls, "Event types · selected location", expand=True, fill="both", padding=8)
        self.filters.canvas.configure(background="#0b1424")
        self.choices = {}
        for family in EVENT_FAMILIES:
            for kind in ("Warning", "Watch"):
                event = f"{family} {kind}"
                self.add_event(event, event in self.profile.events)
        for event in self.profile.events:
            self.add_event(event, True)
        self.selection = Label(controls, "", style="Muted.TLabel")
        self.update_selection(save=False)
        self.toggle = Button(controls, "Start monitoring", self.toggle_monitoring, style="Primary.TButton")
        self.sound_button = Button(controls, "▶  Test alert sound", self.test_sound)
        self.tray_mode = Checkbox(controls, "Close window to tray",
                                  value=self.history.setting("close_to_tray", False), command=self.set_tray_mode)
        self.login = Checkbox(controls, "Launch at login (Windows)",
                              value=self.history.setting("launch_at_login", False), command=self.set_login)
        content = body.column(padding=0, expand=True, fill="both", spacing=8)
        self.health = Label(content, "NO LIVE DATA • Start monitoring", style="Health.TLabel", wraplength=780)
        self.tabs = Tabs(content)
        active = self.tabs.page("Active alerts")
        self.active_count = Label(active, "Current alerts for enabled locations", style="Heading.TLabel")
        self.cards = Cards(active, self.open_alert)
        feed_page = self.tabs.page("Alert feed")
        toolbar = feed_page.row(padding=0)
        self.counter = Label(toolbar, "0 alert changes", style="Muted.TLabel", expand=True)
        Button(toolbar, "Clear feed", self.clear_feed)
        self.empty = Label(feed_page, "Only alert changes appear here. Operational messages stay in the status bar.",
                           style="Muted.TLabel", wraplength=700)
        self.feed = TextArea(feed_page, readonly=True, max_lines=4000, expand=True, fill="both",
                             font=(self.font_family, 11), bg="#101c30", fg="#e5edf8", relief="flat",
                             padx=16, pady=12, borderwidth=0)
        for tag, color, size in (("warning", "#ffbc87", 12), ("watch", "#85caff", 12),
                                 ("meta", "#9aaec7", 10), ("body", "#e5edf8", 11)):
            self.feed.text.tag_configure(tag, foreground=color, font=(self.font_family, size), spacing1=5, spacing3=6)
        map_page = self.tabs.page("Alert map")
        tools = map_page.row(padding=0)
        Label(tools, "Affected areas & saved locations", style="Heading.TLabel", expand=True)
        Button(tools, "+", lambda: self.map.zoom(1.5))
        Button(tools, "−", lambda: self.map.zoom(1 / 1.5))
        Button(tools, "Fit", lambda: self.map.fit())
        self.map = AlertMap(map_page, self.open_alert)
        Label(map_page, "Offline map · Storm polygons or NWS affected-zone outlines; missing boundaries remain in Active alerts.\n"
              "Coordinate matching uses the polygon when available, otherwise the resolved NWS county/forecast zones.",
              style="Muted.TLabel", wraplength=740)
        delivery_page = self.tabs.page("Delivery")
        self.delivery_panel = DeliveryPanel(delivery_page, self.history, self.retry_delivery, lambda: self.running)
        demo_page = self.tabs.page("Demo")
        self.demo = DemoPanel(demo_page, self)
        self.location_wizard = None
        self.tabs.widget.bind("<<NotebookTabChanged>>", lambda _: self.delivery_panel.refresh())
        self.status = Label(self.app, "Ready • Choose locations and start monitoring.", style="Muted.TLabel", wraplength=1180)
        self.tray = Tray(self.app, self.show_window, self.close, self.on_tray_ready, self.tray_failed)
        self.app.root.protocol("WM_DELETE_WINDOW", self.window_closed)
        self.render_active()
        self.tick()
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
        style.configure("TCheckbutton", padding=3)
        style.map("TCheckbutton", background=[("active", "#243a56")])

    def add_event(self, event, selected=False):
        if event not in self.choices:
            self.choices[event] = Checkbox(self.filters.body, event, value=selected,
                                           command=lambda _: self.update_selection())

    def selected_events(self):
        return {event for event, choice in self.choices.items() if choice.get()}

    def update_selection(self, save=True):
        self.selection.set(f"{len(self.selected_events())} event types selected")
        if save and not self.loading_profile:
            self.profile.events = sorted(self.selected_events())
            self.history.save_profile(self.profile)
            self.render_active()

    def select_all(self, value):
        for choice in self.choices.values():
            choice.set(value)
        self.update_selection()

    def choose_profile(self, name):
        self.profile = next(p for p in self.profiles if p.name == name)
        self.loading_profile = True
        for event in self.profile.events:
            self.add_event(event)
        for event, control in self.choices.items():
            control.set(event in self.profile.events)
        self.location_summary.set(self.profile.summary())
        self.update_selection(save=False)
        self.loading_profile = False

    def refresh_profiles(self, profile=None):
        self.profiles = self.history.profiles()
        self.profile = profile or self.profiles[0]
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
                                    enabled=values["enabled"], sound=values["sound"], desktop=values["desktop"]).validate()
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
        with self.sound_lock:
            return self.service.list_counties(states)

    def resolve_location(self, profile):
        with self.sound_lock:
            return self.service.resolve_location(profile.latitude, profile.longitude)

    def remove_profile(self):
        if len(self.profiles) == 1:
            self.status.set("Keep at least one location. Edit or disable this location instead.")
            return
        if self.app.confirm(f"Remove {self.profile.name}?", title="Remove location"):
            self.history.delete_profile(self.profile.id)
            self.refresh_profiles()

    def toggle_monitoring(self):
        if self.running:
            self.running = False
            self.generation += 1
            if self.timer is not None:
                self.app.root.after_cancel(self.timer)
                self.timer = None
            self.next_refresh = None
            self.toggle.set("Start monitoring")
            self.state.set("●  PAUSED")
            self.status.set("Paused • Saved alerts remain visible.")
        elif self.busy:
            self.status.set("Finishing the previous request. Please start again in a moment.")
        elif not any(p.enabled and p.events for p in self.profiles):
            self.status.set("Enable at least one location and select an event type.")
        else:
            self.running = True
            self.toggle.set("Pause monitoring")
            self.state.set("●  MONITORING")
            self.poll()
        self.update_health()
        self.delivery_panel.refresh()

    def poll(self):
        self.timer = None
        if not self.running or self.busy:
            return
        self.busy = True
        self.next_refresh = None
        generation = self.generation
        self.status.set("Checking National Weather Service alerts…")
        self.app.run_in_thread(self.fetch, on_result=lambda result: self.received(generation, result),
                               on_error=lambda error: self.failed(generation, error))

    def fetch(self):
        current = {}
        warning = ""
        with self.sound_lock:
            features = self.service.fetch_alerts()
            try:
                since = self.cancel_since
                features += self.service.fetch_cancellations(since - timedelta(minutes=1))
            except Exception as error:
                warning = f"Cancellation feed unavailable: {error}"
        for feature in features:
            alert = self.service.parse_alert(feature)
            if alert is not None:
                current[alert["id"]] = alert
        with self.sound_lock:
            self.service.enrich_boundaries(list(current.values()), list(self.profiles))
        return current, warning

    def received(self, generation, result):
        self.busy = False
        if not self.running or generation != self.generation:
            return
        current, warning = result
        self.profile.events = sorted(self.selected_events())
        self.coverage_warning = warning
        if not warning:
            self.cancel_since = datetime.now(timezone.utc)
        jobs = []
        try:
            # Process cancellations last so their references override an active snapshot.
            existing_ids = {row["id"] for row in self.history.rows()}
            ordered = sorted(current.values(), key=lambda a: a.get("message_type") == "Cancel")
            for alert in ordered:
                self.add_event(alert["event"])
                matched = [p for p in self.profiles if p.matches(alert)]
                existing = alert["id"] in existing_ids
                if not matched and not existing:
                    continue
                version, kind, legacy = self.history.observe(alert)
                if matched and not self.history.displayed(alert["id"], version):
                    self.append_alert(alert, kind, [p.name for p in matched])
                    self.history.mark_displayed(alert["id"], version)
                if alert.get("message_type") == "Cancel":
                    for previous, status in self.history.cancel_references(alert):
                        if any(p.matches(previous) for p in self.profiles):
                            self.append_alert(previous, status)
                end = instant(alert.get("ends") or alert.get("expires"))
                expired = end and end <= datetime.now(timezone.utc)
                for profile in matched:
                    if expired and alert.get("message_type") != "Cancel":
                        continue
                    quiet = legacy or (not self.initialized and alert["event"] not in CRITICAL)
                    for channel, enabled in (("sound", profile.sound), ("desktop", profile.desktop)):
                        if enabled and not (channel == "sound" and (expired or kind == "Cancelled")):
                            self.history.schedule(alert["id"], version, profile.id, channel, quiet)
                            jobs.append((alert, version, profile.id, channel, kind))
            for alert, kind in self.history.reconcile(set(current)):
                if any(p.matches(alert) for p in self.profiles):
                    self.append_alert(alert, kind)
        except sqlite3.Error as error:
            self.failed(generation, RuntimeError(f"Could not save alert history: {error}"))
            return
        self.initialized = True
        self.last_success = datetime.now(timezone.utc)
        self.last_error = ""
        self.state.set("●  MONITORING")
        self.render_active()
        # Pending failed channels are rechecked on each successful refresh. Successful
        # channels are never replayed for the same version/profile.
        if not self.delivery_busy and jobs:
            self.delivery_busy = True
            self.delivery_future = self.app.run_in_thread(self.send_notifications, generation, jobs,
                                   on_result=self.delivered, on_error=self.delivery_failed)
        self.schedule_next()
        self.status.set(warning or "Alerts are current • Monitoring all enabled locations.")
        self.update_health()

    def send_notifications(self, generation, jobs, manual=False):
        errors = []
        for alert, version, profile_id, channel, kind in jobs:
            profile = next((p for p in self.profiles if p.id == profile_id), None)
            if not profile or not profile.matches(alert) or not getattr(profile, channel):
                continue
            key = (alert["id"], version, profile_id, channel)
            receipt = self.history.delivery(*key)
            if not receipt or (receipt["state"] != "failed" if manual else not self.history.pending(*key)):
                continue
            with self.sound_lock:
                if not self.running or generation != self.generation:
                    break
                if not self.history.is_current(alert["id"], version):
                    continue
                end = instant(alert.get("ends") or alert.get("expires"))
                if end and end <= datetime.now(timezone.utc) and kind != "Cancelled":
                    continue
                try:
                    if channel == "sound":
                        self.service.deliver_sound()
                    else:
                        self.service.deliver_desktop(alert, kind, profile.name)
                except Exception as error:
                    self.history.receipt(alert["id"], version, profile_id, channel, error)
                    errors.append(f"{profile.name} {channel}: {error}")
                else:
                    self.history.receipt(alert["id"], version, profile_id, channel)
        return errors

    def delivered(self, errors):
        self.delivery_busy = False
        self.delivery_panel.refresh()
        if not errors:
            self.status.set("Notification check complete · See Delivery for channel results.")
        if errors:
            self.status.set("Notification submission failed · See Delivery for remaining retries. " + errors[0])

    def delivery_failed(self, error):
        self.delivery_busy = False
        self.delivery_panel.refresh()
        self.status.set(f"Notification worker failed: {error}")

    def retry_delivery(self, row):
        if not self.running:
            self.status.set("Start monitoring before retrying a live notification channel.")
            return
        if self.delivery_busy:
            self.status.set("A notification submission is already in progress. Try again when it finishes.")
            return
        fresh = self.last_success and not self.last_error and (datetime.now(timezone.utc) - self.last_success).total_seconds() < max(120, self.service.interval * 2)
        current = next((r for r in self.history.rows() if r["id"] == row["id"]), None)
        profile = next((p for p in self.profiles if p.id == row["profile"]), None)
        receipt = self.history.delivery(row["id"], row["version"], row["profile"], row["channel"])
        if not fresh or not current or current["version"] != row["version"] or current["status"] not in ("Active", "Cancelled"):
            self.status.set("Only current notifications with fresh live data can be retried. Wait for a successful refresh.")
            return
        if not profile or not profile.matches(row["alert"]) or not getattr(profile, row["channel"]):
            self.status.set("This notification channel is disabled or no longer matches an enabled location.")
            return
        if not receipt or receipt["state"] != "failed":
            self.status.set("Only failed channels can be retried; successful submissions will not be replayed.")
            return
        self.delivery_busy = True
        self.status.set(f"Retrying {row['channel']} once for {profile.name}…")
        self.delivery_future = self.app.run_in_thread(self.send_notifications, self.generation,
            [(row["alert"], row["version"], profile.id, row["channel"], row["kind"])], True,
            on_result=self.delivered, on_error=self.delivery_failed)

    def failed(self, generation, error):
        self.busy = False
        if not self.running or generation != self.generation:
            return
        self.last_error = str(error)
        self.state.set("●  RETRYING")
        self.status.set(f"Unable to refresh: {error} • Saved alerts may be stale.")
        self.schedule_next()
        self.update_health()

    def schedule_next(self):
        self.next_refresh = datetime.now(timezone.utc) + timedelta(seconds=self.service.interval)
        self.timer = self.app.after(self.service.interval * 1000, self.poll)

    def matching_rows(self):
        result = []
        for row in self.history.rows(active_only=True):
            names = [p.name for p in self.profiles if p.matches(row["alert"])]
            if names:
                result.append(dict(row, locations=names))
        return result

    def render_active(self):
        rows = self.matching_rows()
        self.snapshot = {row["id"]: row["alert"] for row in rows}
        self.active_count.set(f"{len(rows)} active alerts · {sum(p.enabled for p in self.profiles)} enabled locations")
        self.cards.render(rows)
        self.map.render(rows, self.profiles)
        if hasattr(self, "delivery_panel"):
            self.delivery_panel.refresh()

    def update_health(self):
        now = datetime.now(timezone.utc)
        if self.last_success is None:
            message = "NO LIVE DATA • Waiting for a successful refresh"
            stale = True
        else:
            age = int((now - self.last_success).total_seconds())
            stale = age >= max(120, self.service.interval * 2) or not self.running or bool(self.last_error)
            message = f"{'STALE' if stale else 'LIVE'} • Last success {self.last_success.astimezone():%H:%M:%S} ({age}s ago)"
        if self.next_refresh:
            message += f" • Next check in {max(0, int((self.next_refresh - now).total_seconds()))}s"
        elif not self.running:
            message += " • Paused"
        if self.coverage_warning:
            message += " • Cancellation coverage incomplete"
        self.health.set(message)
        self.health.configure(foreground="#ffbc87" if stale or self.coverage_warning else "#7ce3bf")

    def tick(self):
        if self.app._closed:
            return
        self.cards.tick()
        self.demo.tick()
        self.update_health()
        # An elapsed expiration can be determined locally, even while offline.
        active_ids = {row["id"] for row in self.history.rows(active_only=True)}
        changes = self.history.reconcile(active_ids)
        if changes:
            for alert, kind in changes:
                if any(p.matches(alert) for p in self.profiles):
                    self.append_alert(alert, kind)
            self.render_active()
        self.health_timer = self.app.after(1000, self.tick)

    def append_alert(self, alert, kind="New", locations=()):
        self.empty.hide()
        self.count += 1
        self.counter.set(f"{self.count} alert changes")
        tag = "warning" if alert["event"].endswith("Warning") else "watch"
        self.feed.append(f"{kind.upper()}  ·  {alert['event']}\n", tag=tag)
        self.feed.append(f"{datetime.now():%b %d · %H:%M:%S}  •  {alert['severity']}  •  {', '.join(locations)}\n", tag="meta")
        self.feed.append(f"{alert['headline']}\n\n{alert['area']}\n\n{alert['instruction']}\n", tag="body")
        self.feed.append(f"Expires: {alert['expires']}\n{alert['url']}\n\n{'─' * 45}\n\n", tag="meta")

    def open_alert(self, alert):
        title = ("SIMULATION · " if alert.get("simulated") else "") + alert["event"]
        window = Window(self.app, title, width=740, height=630)
        Label(window, title, style="Heading.TLabel")
        details = TextArea(window, readonly=True, expand=True, fill="both", bg="#101c30", fg="#e5edf8", padx=16, pady=12)
        details.set(f"{alert['headline']}\n\n{alert['area']}\n\nSeverity: {alert['severity']}\nIssued: {alert['sent']}\n"
                    f"Expires: {alert['expires']}\n\n{alert.get('description', '')}\n\n{alert['instruction']}")
        from urllib.parse import urlparse
        if urlparse(alert["url"]).scheme == "https":
            Button(window, "Open official alert", lambda: webbrowser.open(alert["url"]))

    def clear_feed(self):
        self.feed.clear()
        self.count = 0
        self.counter.set("0 alert changes")
        self.empty.show()

    def test_sound(self):
        self.sound_button.disable()
        self.status.set("Testing alert.mp3…")
        self.app.run_in_thread(self.play_test, on_result=lambda _: self.sound_finished(), on_error=self.sound_failed)

    def play_test(self):
        with self.sound_lock:
            self.service.deliver_sound()

    def sound_finished(self):
        self.sound_button.enable()
        self.status.set("Sound test started • Check your audio device.")

    def sound_failed(self, error):
        self.sound_button.enable()
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
        self.running = False
        self.generation += 1
        for timer in (self.timer, self.health_timer):
            if timer is not None:
                self.app.root.after_cancel(timer)
        self.tray.stop()
        self.app.close()
        self.cleanup_thread = threading.Thread(target=self.cleanup, daemon=True)
        self.cleanup_thread.start()

    def cleanup(self):
        if self.delivery_future is not None:
            try:
                self.delivery_future.result()
            except Exception:
                pass
        self.demo.close()
        with self.sound_lock:
            self.service.session.close()
            pygame.mixer.quit()
            self.history.close()

    def run(self):
        self.app.run()


def main():
    parser = argparse.ArgumentParser(description="Stormwatch weather dashboard")
    parser.add_argument("--test-tornado", action="store_true", help="Test alert sound without the GUI")
    parser.add_argument("--test-hurricane", action="store_true", help="Test alert sound without the GUI")
    parser.add_argument("--monitor", action="store_true", help="Start monitoring saved locations immediately")
    args = parser.parse_args()
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
        ui = StormwatchApp()
        if args.monitor:
            ui.toggle_monitoring()
        ui.run()


if __name__ == "__main__":
    main()
