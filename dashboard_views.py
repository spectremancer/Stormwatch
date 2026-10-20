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
from alert_history import instant, expiration_of
from locations import rings
from radar import Viewport
from event_catalog import event_category, event_color

BG, PANEL, TEXT, MUTED = "#0b1424", "#142238", "#e5edf8", "#9aaec7"


def countdown(alert, now=None):
    end = expiration_of(alert)
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
        self._page_signature = None
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
        signature = (self.page_index,len(self.rows),tuple((r["id"],r.get("version"),r["alert"],r.get('summary'),tuple(r.get("locations",()))) for r in rows))
        if signature == self._page_signature:
            return
        self._page_signature = signature
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
            color = event_color(alert['event'],getattr(self.app,'palette',None))
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
            if row.get('summary'):
                tk.Label(card, text='What changed: '+row['summary'], wraplength=540, justify='left',
                         bg=PANEL, fg=TEXT, anchor='w').pack(fill='x', pady=5)
            label = tk.Label(card, text=countdown(alert), bg=PANEL, fg=color, anchor="w")
            label.pack(fill="x", pady=5)
            self.labels.append((label, alert))
            ttk.Button(card, text="View alert details", command=lambda a=alert: self.open_alert(a)).pack(anchor="w")

    def tick(self):
        for label, alert in self.labels:
            label.configure(text=countdown(alert))


def threat_priority(alert):
    """Warning first, then severity; critical types, category and expiry break ties."""
    end = expiration_of(alert)
    return (int(event_category(alert['event'])=='warning'),
            {'Extreme':4,'Severe':3,'Moderate':2,'Minor':1}.get(alert.get('severity'),0),
            int(alert['event'].startswith(('Tornado','Hurricane'))),
            {'warning':5,'watch':4,'advisory':3,'other':2,'statement':1,'outlook':0}.get(event_category(alert['event']),0),
            -end.timestamp() if end else float('-inf'))


def active_sort_key(row):
    alert = row['alert']
    end = expiration_of(alert)
    return ({'warning':0,'watch':1}.get(event_category(alert['event']),2),
            -{'Extreme':4,'Severe':3,'Moderate':2,'Minor':1}.get(alert.get('severity'),0),
            -end.timestamp() if end else float('inf'),alert['event'].casefold(),row['id'])


class LocationOverview(Cards):
    """Paginated personal threat overview; freshness never implies an all-clear."""
    def __init__(self, parent, open_alert):
        self.freshness = 'NO LIVE DATA'
        self.health_labels = []
        super().__init__(parent, open_alert)

    def render_locations(self, profiles, rows):
        self.render([dict(profile=p, matches=[r for r in rows if p.matches(r['alert'])]) for p in profiles])

    def set_health(self, freshness):
        if freshness != self.freshness:
            self.freshness = freshness
            for label in self.health_labels:
                label.configure(text=freshness, fg=getattr(self.app,'palette',{}).get('good' if freshness == 'LIVE' else 'warning',MUTED))

    def draw_page(self):
        start = self.page_index * 20
        rows = self.rows[start:start+20]
        signature = (self.page_index,len(self.rows),tuple((r['profile'].to_json(),
                     tuple((a['id'],a.get('version'),a['alert']) for a in r['matches'])) for r in rows))
        if signature == self._page_signature:
            return
        self._page_signature = signature
        self.page_label.configure(text=f'{start+1 if rows else 0}–{start+len(rows)} of {len(self.rows)} locations')
        self.previous.state(['disabled'] if start == 0 else ['!disabled'])
        self.next.state(['disabled'] if start+20 >= len(self.rows) else ['!disabled'])
        for child in self.body.winfo_children():
            child.destroy()
        self.labels, self.health_labels = [], []
        for row in rows:
            profile, matches = row['profile'], row['matches']
            top = max((r['alert'] for r in matches), key=threat_priority, default=None)
            color = event_color(top['event'],getattr(self.app,'palette',None)) if top else MUTED
            card = tk.Frame(self.body, bg=PANEL, padx=16, pady=12, highlightthickness=1, highlightbackground='#243a56')
            card.pack(fill='x', pady=(0,10))
            for text, fg, bold in ((profile.name,TEXT,True),(profile.summary(),MUTED,False),
                    ('Disabled' if not profile.enabled else 'No event types selected' if not profile.events else
                     top['event'] if top else 'No selected active alerts',color,True),
                    (f'{len(matches)} matching alerts · {len(profile.events)} selected event types',MUTED,False)):
                tk.Label(card,text=text,bg=PANEL,fg=fg,anchor='w',wraplength=540,justify='left',
                         font=(tkfont.nametofont('TkDefaultFont').actual('family'),11,'bold' if bold else 'normal')).pack(fill='x',pady=2)
            if top:
                label = tk.Label(card,text=countdown(top),bg=PANEL,fg=color,anchor='w')
                label.pack(fill='x',pady=4)
                self.labels.append((label,top))
                ttk.Button(card,text='View highest-priority alert',command=lambda a=top:self.open_alert(a)).pack(anchor='w')
            monitored = profile.enabled and bool(profile.events)
            label = tk.Label(card,text=self.freshness if monitored else 'Monitoring disabled',bg=PANEL,
                             fg=getattr(self.app,'palette',{}).get('good' if self.freshness == 'LIVE' else 'warning',MUTED) if monitored else getattr(self.app,'palette',{}).get('muted',MUTED),anchor='w')
            label.pack(fill='x',pady=(6,0))
            if monitored:
                self.health_labels.append(label)


class AlertMap(Widget):
    """Pan/zoom longitude/latitude map; no API key or remote tile requests."""
    def __init__(self, parent, open_alert, on_point=None):
        self.on_point = on_point
        self.canvas = tk.Canvas(parent.widget, background="#101c30", highlightthickness=0, height=400)
        self._attach(parent, self.canvas, expand=True, fill="both")
        self.canvas._stormwatch_map = self
        self.open_alert = open_alert
        self.rows, self.profiles = [], []
        self._render_signature = None
        self._draw_timer = None
        self._dirty = True
        self.place_labels = []
        self.center = (-90.0, 45.0)
        self.scale = 4.0
        self._initial_region = True
        self.drag = None
        self.canvas.bind("<Configure>", lambda e: self.request_draw())
        self.canvas.bind("<Map>", lambda e: self.request_draw())
        self.canvas.bind("<ButtonPress-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.move)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<Double-Button-1>", lambda e: self.zoom(1.5))
        self.canvas.bind("<MouseWheel>", lambda e: self.zoom(1.25 if e.delta > 0 else .8))
        self.canvas.bind("<Button-4>", lambda e: self.zoom(1.25))
        self.canvas.bind("<Button-5>", lambda e: self.zoom(.8))
        self.items = {}
        self.radar_photo = self.radar_view = None
        self.on_view_changed = None
        with Path(__file__).with_name("data").joinpath("world_land.geojson").open() as source:
            self.land = json.load(source)["features"]

    def render(self, rows, profiles):
        signature = (tuple((r["id"],r.get("version"),r["alert"].get("event"),r["alert"].get("simulated"),r["alert"].get("geometry")) for r in rows),
                     tuple((p.id,p.name,p.enabled,p.longitude,p.latitude) for p in profiles),tuple(self.place_labels))
        self.rows, self.profiles = rows, profiles
        if signature != self._render_signature:
            self._render_signature = signature
            self._dirty = True
            if self.canvas.winfo_ismapped():
                self.request_draw()

    def request_draw(self):
        self._dirty = True
        if self._draw_timer is None and not self._destroyed:
            self._draw_timer = self.app.root.after_idle(self.flush_draw)

    def flush_draw(self):
        self._draw_timer = None
        if self._dirty and self.canvas.winfo_ismapped():
            self._dirty = False
            self.draw()

    def _dispose(self):
        if self._draw_timer is not None:
            self.app.root.after_cancel(self._draw_timer)
            self._draw_timer = None
        super()._dispose()

    def project(self, lon, lat):
        return (self.canvas.winfo_width() / 2 + (lon - self.center[0]) * self.scale,
                self.canvas.winfo_height() / 2 - (lat - self.center[1]) * self.scale)

    def viewport(self):
        return Viewport(self.canvas.winfo_width(),self.canvas.winfo_height(),*self.center,self.scale)

    def set_radar(self, image=None, view=None):
        from PIL import ImageTk
        self.radar_photo = ImageTk.PhotoImage(image,master=self.canvas) if image is not None else None
        self.radar_view = view
        self.paint_radar()

    def paint_radar(self):
        self.canvas.delete('radar')
        if self.radar_photo is not None and self.radar_view == self.viewport():
            self.canvas.create_image(0,0,image=self.radar_photo,anchor='nw',tags='radar')
            self.canvas.tag_lower('radar')
            self.canvas.tag_lower('land')

    def zoom(self, factor):
        self._initial_region = False
        self.scale = max(1, min(2000, self.scale * factor))
        self.request_draw()

    def fit(self):
        self._initial_region = False
        points = [(p.longitude, p.latitude) for p in self.profiles
                  if p.enabled and p.latitude is not None and (self.rows or self.on_point is not None)]
        for row in self.rows:
            for polygon in rings(row["alert"].get("geometry")):
                points.extend(tuple(p[:2]) for p in polygon[0])
        if points:
            xs, ys = zip(*points)
            self.center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
            self.scale = min(max(1, self.canvas.winfo_width() - 100) / max(2, max(xs) - min(xs)),
                             max(1, self.canvas.winfo_height() - 100) / max(2, max(ys) - min(ys)))
        else:
            self._north_america()
        self.request_draw()

    def _north_america(self):
        # Alaska, Canada, Greenland, the contiguous US, Mexico and Central America.
        self.center = (-90, 45)
        self.scale = max(0.1, min(max(1,self.canvas.winfo_width()-80)/160,
                                  max(1,self.canvas.winfo_height()-100)/80))

    def start_drag(self, event):
        self.drag = (event.x, event.y, self.center)

    def move(self, event):
        if self.drag:
            self._initial_region = False
            x, y, center = self.drag
            self.center = (center[0] - (event.x - x) / self.scale, center[1] + (event.y - y) / self.scale)
            self.request_draw()

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
        if self._initial_region:
            self._initial_region = False
            self._north_america()
        c = self.canvas
        from appearance import SKINS
        palette = getattr(self.app, "palette", SKINS["Navy"])
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
                    c.create_polygon(coords, fill=palette["land"], outline=palette["shore"], width=1, tags='land')
        self.paint_radar()
        for i in range(int(w / self.scale / step) + 2):
            lon = (math.floor(left / step) + i) * step
            if not -180 <= lon <= 180:
                continue
            x, _ = self.project(lon, 0)
            c.create_line(x, 0, x, h, fill=palette["button"])
            c.create_text(x+4, h-12, text=f"{lon:g}°", fill=palette["muted"], anchor="w")
        for i in range(int(h / self.scale / step) + 2):
            lat = (math.floor(bottom / step) + i) * step
            if not -90 <= lat <= 90:
                continue
            _, y = self.project(0, lat)
            c.create_line(0, y, w, y, fill=palette["button"])
            c.create_text(5, y-8, text=f"{lat:g}°", fill=palette["muted"], anchor="w")
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
                                                outline=event_color(alert['event'],getattr(self.app,'palette',None)))
                        self.items[item] = alert
        labels = [self.project(p.longitude, p.latitude) for p in self.profiles if p.latitude is not None]
        for place in self.place_labels:
            x, y = self.project(place.longitude, place.latitude)
            if 10 < x < w - 100 and 60 < y < h - 25 and all(abs(x-px) > 90 or abs(y-py) > 26 for px, py in labels):
                c.create_oval(x-2, y-2, x+2, y+2, fill=palette["muted"], outline="")
                c.create_text(x+5, y, text=place.city, fill=palette["muted"], anchor="w")
                labels.append((x,y))
        for p in self.profiles:
            if p.enabled and p.latitude is not None:
                x, y = self.project(p.longitude, p.latitude)
                c.create_oval(x-5, y-5, x+5, y+5, fill=palette["good"], outline=palette["text"])
                c.create_text(x+9, y, text=p.name, fill=palette["text"], anchor="w")
        c.create_rectangle(0, 0, w, 48, fill=palette["surface"], outline="")
        c.create_text(14, 12, text="Confirm your location · Green: approximate pin · Gray: nearby places" if self.on_point else "SIMULATION · Sample boundaries · No real weather threat" if any(row["alert"].get("simulated") for row in self.rows) else "NWS boundaries · Orange: warning / Blue: watch · Green: saved location", fill=palette["text"], anchor="w")
        c.create_text(14, 32, text="Drag to pan · Scroll to zoom · Click the map to move the pin" if self.on_point else f"Drag to pan · Scroll or use +/− to zoom · Click an outline for details · {missing} alerts have no polygon", fill=palette["muted"], anchor="w")
        if self.on_view_changed:
            self.on_view_changed()
