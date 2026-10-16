"""Stormwatch desktop dashboard, composed with TkFlow."""
from __future__ import annotations

import argparse
from datetime import datetime
import threading

import pygame

from TkFlow import App, Button, Checkbox, Label, TextArea
from WeatherService import WeatherService


# NWS event families. Other active watch/warning types are discovered on refresh.
EVENT_FAMILIES = (
    "Tornado", "Severe Thunderstorm", "Hurricane", "Tropical Storm",
    "Flash Flood", "Flood", "Coastal Flood", "Winter Storm", "Blizzard",
    "Ice Storm", "Snow Squall", "High Wind", "Extreme Wind", "Dust Storm",
    "Excessive Heat", "Extreme Heat", "Extreme Cold", "Freeze", "Hard Freeze",
    "Wind Chill", "Red Flag", "Fire Weather", "Storm", "Gale", "Tsunami",
)



class StormwatchApp:
    def __init__(self, service=None):
        self.app = App("Stormwatch · Weather intelligence", width=1180, height=800,
                       min_width=900, min_height=620, padding=24, spacing=16,
                       theme="clam")
        self.service = service or WeatherService(interval=60)
        self.snapshot = {}
        self.initialized = False
        self.running = False
        self.busy = False
        self.generation = 0
        self.timer = None
        self.count = 0
        self.sound_lock = threading.Lock()
        self._style()
        header = self.app.row(padding=0)
        branding = header.column(padding=0, expand=True)
        Label(branding, "STORMWATCH", style="Brand.TLabel")
        Label(branding, "Weather intelligence • United States", style="Muted.TLabel")
        self.state = Label(header, "●  PAUSED", style="Status.TLabel")
        body = self.app.row(padding=0, expand=True, fill="both", spacing=24)
        controls = body.column(padding=16, spacing=12, style="Panel.TFrame")
        Label(controls, "Monitoring preferences", style="Heading.TLabel")
        Label(controls, "Choose the events you want to follow.", style="Muted.TLabel")
        actions = controls.row(padding=0)
        Button(actions, "Select all", lambda: self.select_all(True))
        Button(actions, "Clear", lambda: self.select_all(False))
        # A scrollable TkFlow form keeps the full event catalog accessible.
        from TkFlow import Form
        self.filters = Form(controls, "Event types", expand=True, fill="both", padding=8)
        self.choices = {}
        for family in EVENT_FAMILIES:
            for kind in ("Warning", "Watch"):
                event = f"{family} {kind}"
                self.add_event(event, event in self.service.WATCHED_EVENTS)
        self.selection = Label(controls, "", style="Muted.TLabel")
        self.update_selection()
        self.toggle = Button(controls, "Start monitoring", self.toggle_monitoring,
                             style="Primary.TButton")
        self.sound_button = Button(controls, "▶  Test alert sound", self.test_sound)
        Label(controls, "Refreshes every 60 seconds\nSound: tornado & hurricane events",
              style="Muted.TLabel")
        feed = body.column(padding=0, expand=True, fill="both", spacing=10)
        toolbar = feed.row(padding=0)
        Label(toolbar, "Alert feed", style="Heading.TLabel", expand=True)
        self.counter = Label(toolbar, "0 alerts", style="Muted.TLabel")
        Button(toolbar, "Clear feed", self.clear_feed)
        self.empty = Label(feed, "Your alert feed is clear. Start monitoring to receive selected alerts.",
                           style="Muted.TLabel", wraplength=600)
        self.feed = TextArea(feed, readonly=True, max_lines=4000, expand=True,
                             fill="both", font=("TkDefaultFont", 11), bg="#101c30",
                             fg="#e5edf8", relief="flat", padx=20, pady=16,
                             insertbackground="#e5edf8", borderwidth=0)
        for tag, color, size in (("warning", "#ffbc87", 12), ("watch", "#85caff", 12),
                                 ("meta", "#9aaec7", 10), ("body", "#e5edf8", 11)):
            self.feed.text.tag_configure(tag, foreground=color,
                                         font=("TkDefaultFont", size), spacing1=5, spacing3=6)
        self.status = Label(self.app, "Ready • Select your events, then start monitoring.",
                            style="Muted.TLabel", wraplength=1080)
        self.app.root.protocol("WM_DELETE_WINDOW", self.close)

    def _style(self):
        style = self.app.style
        style.configure(".", background="#0b1424", foreground="#e5edf8", font=("TkDefaultFont", 10))
        style.configure("TFrame", background="#0b1424")
        style.configure("Panel.TFrame", background="#142238")
        style.configure("TLabel", background="#0b1424")
        style.configure("Brand.TLabel", font=("TkDefaultFont", 23, "bold"), foreground="#f5f9ff")
        style.configure("Heading.TLabel", font=("TkDefaultFont", 13, "bold"))
        style.configure("Muted.TLabel", foreground="#9aaec7")
        style.configure("Status.TLabel", foreground="#85caff", font=("TkDefaultFont", 10, "bold"))
        style.configure("TButton", padding=(12, 9), background="#243a56")
        style.map("TButton", background=[("active", "#355474")])
        style.configure("Primary.TButton", background="#176caa", font=("TkDefaultFont", 10, "bold"))
        style.configure("TCheckbutton", padding=3)
        style.map("TCheckbutton", background=[("active", "#243a56")])

    def add_event(self, event, selected=False):
        if event not in self.choices:
            self.choices[event] = Checkbox(self.filters.body, event, value=selected,
                                           command=lambda _: self.update_selection())

    def selected_events(self):
        return {event for event, choice in self.choices.items() if choice.get()}

    def update_selection(self):
        self.selection.set(f"{len(self.selected_events())} event types selected")

    def select_all(self, value):
        for choice in self.choices.values():
            choice.set(value)
        self.update_selection()

    def toggle_monitoring(self):
        if self.running:
            self.running = False
            self.generation += 1
            if self.timer is not None:
                self.app.root.after_cancel(self.timer)
                self.timer = None
            self.toggle.set("Start monitoring")
            self.state.set("●  PAUSED")
            self.status.set("Paused • No new alerts will be delivered.")
        elif self.busy:
            self.status.set("Finishing the previous request. Please start again in a moment.")
        elif not self.selected_events():
            self.status.set("Select at least one event type before starting.")
        else:
            self.running = True
            self.toggle.set("Pause monitoring")
            self.state.set("●  MONITORING")
            self.poll()

    def poll(self):
        self.timer = None
        if not self.running or self.busy:
            return
        self.busy = True
        generation = self.generation
        self.status.set("Checking National Weather Service alerts…")
        selected = self.selected_events()
        # Notifications are delivered only after checking that this request is
        # still current. The worker only fetches and compares data.
        self.app.run_in_thread(
            self.fetch, selected, dict(self.snapshot),
            on_result=lambda result: self.received(generation, selected, result),
            on_error=lambda error: self.failed(generation, error))

    def fetch(self, selected, previous):
        # Suppress service notifications here; pause and filter changes must take
        # effect even when a network request is already in flight.
        current = {}
        with self.sound_lock:
            features = self.service.fetch_alerts()
        for feature in features:
            alert = self.service.parse_alert(feature)
            if alert is not None:
                current[alert["id"]] = alert
        return current, previous

    def received(self, generation, selected, result):
        self.busy = False
        if not self.running or generation != self.generation:
            return
        current, previous = result
        self.state.set("●  MONITORING")
        selected &= self.selected_events()
        for alert in current.values():
            self.add_event(alert["event"])
            old = previous.get(alert["id"])
            if alert["event"] in selected and (old is None or self.service.get_fingerprint(old) != self.service.get_fingerprint(alert)):
                self.append_alert(alert, old is not None)
                if self.initialized:
                    self.app.run_in_thread(self.send_notification, generation, alert, old is not None,
                                           on_error=self.notification_error)
        self.initialized = True
        self.snapshot = {key: alert for key, alert in current.items() if alert["event"] in selected}
        self.status.set(f"Updated {datetime.now():%H:%M:%S} • {len(self.snapshot)} selected active alerts • Next check in 60 seconds")
        self.timer = self.app.after(self.service.interval * 1000, self.poll)

    def send_notification(self, generation, alert, updated):
        with self.sound_lock:
            if self.running and generation == self.generation:
                self.service.notify(alert, updated=updated)

    def notification_error(self, error):
        self.status.set(f"Notification unavailable: {error}")

    def failed(self, generation, error):
        self.busy = False
        if not self.running or generation != self.generation:
            return
        self.state.set("●  RETRYING")
        self.status.set(f"Unable to refresh: {error} • Retrying in 60 seconds")
        self.timer = self.app.after(self.service.interval * 1000, self.poll)

    def append_alert(self, alert, updated=False):
        self.empty.hide()
        self.count += 1
        self.counter.set(f"{self.count} alerts")
        tag = "warning" if alert["event"].endswith("Warning") else "watch"
        self.feed.append(f"{'UPDATED' if updated else 'NEW'}  ·  {alert['event']}\n", tag=tag)
        self.feed.append(f"{datetime.now():%b %d · %H:%M:%S}  •  {alert['severity']}  •  {alert['urgency']}\n", tag="meta")
        self.feed.append(f"{alert['headline']}\n\n{alert['area']}\n\n{alert['instruction']}\n", tag="body")
        self.feed.append(f"Expires: {alert['expires']}\n{alert['url']}\n\n{'─' * 45}\n\n", tag="meta")

    def clear_feed(self):
        self.feed.clear()
        self.count = 0
        self.counter.set("0 alerts")
        self.empty.show()

    def test_sound(self):
        self.sound_button.disable()
        self.status.set("Testing alert.mp3…")
        self.app.run_in_thread(self.play_test,
                               on_result=lambda _: self.sound_finished(),
                               on_error=self.sound_failed)

    def play_test(self):
        # Unlike the service's best-effort method, surface device/file failures.
        with self.sound_lock:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(str(self.service.base_dir / "alert.mp3"))
            pygame.mixer.music.play()

    def sound_finished(self):
        self.sound_button.enable()
        self.status.set("Sound test started • You should hear the alert on your audio device.")

    def sound_failed(self, error):
        self.sound_button.enable()
        self.status.set(f"Sound test failed: {error}")

    def close(self):
        self.running = False
        self.generation += 1
        if self.timer is not None:
            self.app.root.after_cancel(self.timer)
        self.app.close()
        # Wait away from Tk for any in-flight request/audio operation to finish.
        threading.Thread(target=self.cleanup, daemon=True).start()

    def cleanup(self):
        with self.sound_lock:
            self.service.session.close()
            pygame.mixer.quit()

    def run(self):
        self.app.run()


def main():
    parser = argparse.ArgumentParser(description="Stormwatch weather dashboard")
    parser.add_argument("--test-tornado", action="store_true", help="Test alert sound without the GUI")
    parser.add_argument("--test-hurricane", action="store_true", help="Test alert sound without the GUI")
    args = parser.parse_args()
    if args.test_tornado or args.test_hurricane:
        service = WeatherService()
        try:
            service.play_tornado_alert()
            while pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.time.wait(100)
        finally:
            pygame.mixer.quit()
            service.session.close()
    else:
        StormwatchApp().run()


if __name__ == "__main__":
    main()
