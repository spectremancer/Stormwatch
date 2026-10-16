"""TkFlow-compatible active cards and an offline interactive geographic map."""
from datetime import datetime, timezone
import math
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

from TkFlow.widget import Widget
from TkFlow._layout import _Layout
from alert_history import instant
from locations import rings

BG, PANEL, TEXT, MUTED = "#0b1424", "#142238", "#e5edf8", "#9aaec7"


def countdown(alert, now=None):
    end = instant(alert.get("ends") or alert.get("expires"))
    if not end:
        return "Expiration unavailable"
    seconds = int((end - (now or datetime.now(timezone.utc))).total_seconds())
    if seconds <= 0:
        return "Expired"
    minutes = math.ceil(seconds / 60)
    return f"Expires in {minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"Expires in {minutes}m"


class Page(_Layout):
    def __init__(self, app, notebook, title):
        self.app = app
        self.widget = ttk.Frame(notebook, padding=12)
        self._init_layout("vertical", 10)
        notebook.add(self.widget, text=title)


class Tabs(Widget):
    def __init__(self, parent):
        self._attach(parent, ttk.Notebook(parent.widget), expand=True, fill="both")
        self.pages = []

    def page(self, title):
        page = Page(self.app, self.widget, title)
        self.pages.append(page)
        return page

    def _dispose(self):
        for page in self.pages:
            for child in page._children:
                child._dispose()
        super()._dispose()


class Cards(Widget):
    def __init__(self, parent, open_alert):
        self.open_alert = open_alert
        self.rows, self.page_index = [], 0
        frame = ttk.Frame(parent.widget)
        self.canvas = tk.Canvas(frame, background=BG, highlightthickness=0)
        self.body = ttk.Frame(self.canvas)
        item = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        bar = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        navigation = ttk.Frame(frame)
        navigation.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.page_label = ttk.Label(navigation, style="Muted.TLabel")
        self.page_label.pack(side="left", expand=True, fill="x")
        self.previous = ttk.Button(navigation, text="Previous", command=lambda: self.change_page(-1))
        self.previous.pack(side="left", padx=4)
        self.next = ttk.Button(navigation, text="Next", command=lambda: self.change_page(1))
        self.next.pack(side="left")
        self.canvas.grid(row=1, column=0, sticky="nsew")
        bar.grid(row=1, column=1, sticky="ns")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(item, width=e.width))
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._attach(parent, frame, expand=True, fill="both")
        self.labels = []

    def render(self, rows):
        self.rows = rows
        self.page_index = min(self.page_index, max(0, (len(rows) - 1) // 20))
        self.draw_page()

    def change_page(self, delta):
        self.page_index = max(0, min(max(0, (len(self.rows) - 1) // 20), self.page_index + delta))
        self.draw_page()
        self.canvas.yview_moveto(0)

    def draw_page(self):
        start = self.page_index * 20
        rows = self.rows[start:start + 20]
        self.page_label.configure(text=f"{start + 1 if rows else 0}–{start + len(rows)} of {len(self.rows)} alerts")
        self.previous.state(["disabled"] if self.page_index == 0 else ["!disabled"])
        self.next.state(["disabled"] if start + 20 >= len(self.rows) else ["!disabled"])
        for child in self.body.winfo_children():
            child.destroy()
        self.labels = []
        if not rows:
            ttk.Label(self.body, text="No active alerts match your enabled locations.\nStart monitoring to refresh.",
                      style="Muted.TLabel", padding=20).pack(anchor="w")
        for row in rows:
            alert = row["alert"]
            color = "#ffbc87" if alert["event"].endswith("Warning") else "#85caff"
            card = tk.Frame(self.body, background=PANEL, padx=16, pady=12, highlightthickness=1,
                            highlightbackground="#243a56")
            card.pack(fill="x", pady=(0, 10))
            tk.Label(card, text=("SIMULATION · " if alert.get("simulated") else "") + alert["event"], bg=PANEL, fg=color,
                     font=(tkfont.nametofont("TkDefaultFont").actual("family"), 13, "bold"), anchor="w").pack(fill="x")
            tk.Label(card, text=" · ".join(row.get("locations", [])), bg=PANEL, fg=MUTED,
                     anchor="w").pack(fill="x", pady=(4, 0))
            tk.Label(card, text=f"{alert['severity']}  ·  Issued {alert.get('sent') or 'unknown'}",
                     bg=PANEL, fg=MUTED, anchor="w").pack(fill="x", pady=4)
            area = tk.Label(card, text=alert["area"], wraplength=540, justify="left", bg=PANEL, fg=TEXT, anchor="w")
            area.pack(fill="x")
            card.bind("<Configure>", lambda e, label=area: label.configure(wraplength=max(180, e.width - 40)))
            label = tk.Label(card, text=countdown(alert), bg=PANEL, fg=color, anchor="w")
            label.pack(fill="x", pady=5)
            self.labels.append((label, alert))
            ttk.Button(card, text="View alert details", command=lambda a=alert: self.open_alert(a)).pack(anchor="w")

    def tick(self):
        for label, alert in self.labels:
            label.configure(text=countdown(alert))


class AlertMap(Widget):
    """Pan/zoom longitude/latitude map; no API key or remote tile requests."""
    def __init__(self, parent, open_alert, on_point=None):
        self.on_point = on_point
        self.canvas = tk.Canvas(parent.widget, background="#101c30", highlightthickness=0, height=400)
        self._attach(parent, self.canvas, expand=True, fill="both")
        self.open_alert = open_alert
        self.rows, self.profiles = [], []
        self.place_labels = []
        self.center = (-98.0, 39.0)
        self.scale = 8.0
        self.drag = None
        self.canvas.bind("<Configure>", lambda e: self.draw())
        self.canvas.bind("<ButtonPress-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.move)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<Double-Button-1>", lambda e: self.zoom(1.5))
        self.canvas.bind("<MouseWheel>", lambda e: self.zoom(1.25 if e.delta > 0 else .8))
        self.canvas.bind("<Button-4>", lambda e: self.zoom(1.25))
        self.canvas.bind("<Button-5>", lambda e: self.zoom(.8))
        self.items = {}
        with Path(__file__).with_name("data").joinpath("north_america.geojson").open() as source:
            self.land = json.load(source)["features"]

    def render(self, rows, profiles):
        self.rows, self.profiles = rows, profiles
        self.draw()

    def project(self, lon, lat):
        return (self.canvas.winfo_width() / 2 + (lon - self.center[0]) * self.scale,
                self.canvas.winfo_height() / 2 - (lat - self.center[1]) * self.scale)

    def zoom(self, factor):
        self.scale = max(1, min(2000, self.scale * factor))
        self.draw()

    def fit(self):
        points = [(p.longitude, p.latitude) for p in self.profiles if p.enabled and p.latitude is not None]
        for row in self.rows:
            for polygon in rings(row["alert"].get("geometry")):
                points.extend(tuple(p[:2]) for p in polygon[0])
        if points:
            xs, ys = zip(*points)
            self.center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
            self.scale = min(max(1, self.canvas.winfo_width() - 100) / max(2, max(xs) - min(xs)),
                             max(1, self.canvas.winfo_height() - 100) / max(2, max(ys) - min(ys)))
        else:
            self.center, self.scale = (-98, 39), 8
        self.draw()

    def start_drag(self, event):
        self.drag = (event.x, event.y, self.center)

    def move(self, event):
        if self.drag:
            x, y, center = self.drag
            self.center = (center[0] - (event.x - x) / self.scale, center[1] + (event.y - y) / self.scale)
            self.draw()

    def release(self, event):
        if self.drag and abs(event.x - self.drag[0]) + abs(event.y - self.drag[1]) < 5:
            if self.on_point is not None:
                lon = self.center[0] + (event.x - self.canvas.winfo_width() / 2) / self.scale
                lat = self.center[1] - (event.y - self.canvas.winfo_height() / 2) / self.scale
                self.on_point(lat, lon)
            for item in reversed(self.canvas.find_overlapping(event.x-2, event.y-2, event.x+2, event.y+2)):
                if item in self.items:
                    self.open_alert(self.items[item])
                    break
        self.drag = None

    def draw(self):
        c = self.canvas
        c.delete("all")
        self.items = {}
        w, h = c.winfo_width(), c.winfo_height()
        step = 10 if self.scale < 20 else 2 if self.scale < 100 else .5
        left = self.center[0] - w / self.scale / 2
        bottom = self.center[1] - h / self.scale / 2
        for feature in self.land:
            for polygon in rings(feature["geometry"]):
                coords = [value for lon, lat, *_ in polygon[0] for value in self.project(lon, lat)]
                if len(coords) >= 6:
                    c.create_polygon(coords, fill="#192c40", outline="#456079", width=1)
        for i in range(int(w / self.scale / step) + 2):
            lon = (math.floor(left / step) + i) * step
            x, _ = self.project(lon, 0)
            c.create_line(x, 0, x, h, fill="#243a56")
            c.create_text(x+4, h-12, text=f"{lon:g}°", fill=MUTED, anchor="w")
        for i in range(int(h / self.scale / step) + 2):
            lat = (math.floor(bottom / step) + i) * step
            _, y = self.project(0, lat)
            c.create_line(0, y, w, y, fill="#243a56")
            c.create_text(5, y-8, text=f"{lat:g}°", fill=MUTED, anchor="w")
        missing = 0
        for row in self.rows:
            alert = row["alert"]
            polygons = rings(alert.get("geometry"))
            if not polygons:
                missing += 1
            for polygon in polygons:
                # Boundaries include interior rings; holes are left unfilled.
                for ring in polygon:
                    coords = [value for lon, lat, *_ in ring for value in self.project(lon, lat)]
                    if len(coords) >= 6:
                        item = c.create_polygon(coords, fill="", width=2,
                                                outline="#ffbc87" if alert["event"].endswith("Warning") else "#85caff")
                        self.items[item] = alert
        labels = [self.project(p.longitude, p.latitude) for p in self.profiles if p.latitude is not None]
        for place in self.place_labels:
            x, y = self.project(place.longitude, place.latitude)
            if 10 < x < w - 100 and 60 < y < h - 25 and all(abs(x-px) > 90 or abs(y-py) > 26 for px, py in labels):
                c.create_oval(x-2, y-2, x+2, y+2, fill="#9aaec7", outline="")
                c.create_text(x+5, y, text=place.city, fill="#9aaec7", anchor="w")
                labels.append((x,y))
        for p in self.profiles:
            if p.enabled and p.latitude is not None:
                x, y = self.project(p.longitude, p.latitude)
                c.create_oval(x-5, y-5, x+5, y+5, fill="#7ce3bf", outline=TEXT)
                c.create_text(x+9, y, text=p.name, fill=TEXT, anchor="w")
        c.create_rectangle(0, 0, w, 48, fill="#101c30", outline="")
        c.create_text(14, 12, text="Confirm your location · Green: approximate pin · Gray: nearby places" if self.on_point else "SIMULATION · Sample boundaries · No real weather threat" if any(row["alert"].get("simulated") for row in self.rows) else "NWS boundaries · Orange: warning / Blue: watch · Green: saved location", fill=TEXT, anchor="w")
        c.create_text(14, 32, text="Drag to pan · Scroll to zoom · Click the map to move the pin" if self.on_point else f"Drag to pan · Scroll or use +/− to zoom · Click an outline for details · {missing} alerts have no polygon", fill=MUTED, anchor="w")
