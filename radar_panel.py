"""Opt-in radar controls. Tk stays on the main thread; requests stay in workers."""
from datetime import datetime, timedelta, timezone
import time

from TkFlow import Button, Checkbox, Label, TextArea, Window
from radar import METADATA_URL, TILE_HOST, RadarService, error_description


class RadarPanel:
    def __init__(self, parent, alert_map, service=None, connection_tools=None):
        self.app, self.map = parent.app, alert_map
        self.service = service or RadarService()
        self.frames = []
        self.loaded_view = None
        self.index, self.generation = 0, 0
        self.busy = self.playing = self.closed = False
        self.error = ''
        self.diagnostic = ''
        self.last_attempt = self.last_success = self.last_failure = None
        self.last_duration = self.request_started = self.next_refresh_at = None
        self.play_timer = self.view_timer = self.refresh_timer = None
        tools = parent.row(padding=0, spacing=4)
        self.enabled = Checkbox(tools,'Show recent radar',value=False,command=lambda _: self.toggle())
        self.play_button = Button(tools,'Play',self.toggle_play,style='Map.TButton',width=0)
        self.previous = Button(tools,'Previous frame',lambda: self.step(-1),style='Map.TButton',width=0)
        self.next = Button(tools,'Next frame',lambda: self.step(1),style='Map.TButton',width=0)
        self.refresh_button = Button(tools,'Refresh radar',lambda:self.refresh(force=True),style='Map.TButton',width=0)
        self.details_button = Button(connection_tools or tools,'Connection details',self.show_details,style='Map.TButton',width=0)
        # Let the status use only the lines its current text needs. The map
        # receives the remaining height, including while radar is switched off.
        self.status = Label(parent,'Radar off · Alert monitoring works independently.',style='Muted.TLabel',wraplength=740,anchor='nw')
        self.status.widget.bind('<Configure>',lambda e:self.status.configure(wraplength=max(200,e.width)))
        self.map.on_view_changed = self.view_changed
        self.update_buttons()

    def update_buttons(self):
        available = self.enabled.get() and bool(self.frames) and self.loaded_view == self.map.viewport() and not self.busy
        for button in (self.play_button,self.previous,self.next):
            button.enable() if available else button.disable()
        self.refresh_button.enable() if self.enabled.get() and not self.busy else self.refresh_button.disable()
        self.play_button.set('Pause' if self.playing else 'Play')

    def stop_playback(self):
        self.playing = False
        if self.play_timer is not None:
            self.app.root.after_cancel(self.play_timer)
            self.play_timer = None

    def toggle(self):
        self.generation += 1
        self.stop_playback()
        if not self.enabled.get():
            for name in ('view_timer','refresh_timer'):
                timer = getattr(self,name)
                if timer is not None:
                    self.app.root.after_cancel(timer)
                    setattr(self,name,None)
            self.next_refresh_at = None
            self.frames, self.loaded_view = [], None
            self.map.set_radar()
            self.status.set('Radar off · Alert monitoring works independently.')
        else:
            self.refresh()
        self.update_buttons()

    def view_changed(self):
        if self.closed or not self.enabled.get() or self.loaded_view == self.map.viewport():
            return
        self.stop_playback()
        self.update_buttons()
        if self.view_timer is not None:
            self.app.root.after_cancel(self.view_timer)
        self.view_timer = self.app.after(450,self.refresh)

    def refresh(self, force=False):
        self.view_timer = None
        if self.closed or not self.enabled.get() or self.busy or not self.map.canvas.winfo_ismapped():
            return
        view = self.map.viewport()
        if not force and self.loaded_view == view:
            return
        self.stop_playback()
        self.busy = True
        self.last_attempt = datetime.now(timezone.utc)
        self.request_started = time.monotonic()
        generation = self.generation
        self.status.set('Loading recent past radar… Alert boundaries remain available.')
        self.update_buttons()
        try:
            self.app.run_in_thread(self.service.load,view,
                on_result=lambda result:self.loaded(generation,result),
                on_error=lambda error:self.failed(generation,view,error))
        except RuntimeError:
            self.failed(generation,view,ValueError('The background queue is busy. Try Refresh radar again shortly.'))

    def loaded(self, generation, result):
        self.busy = False
        self.last_duration = time.monotonic()-self.request_started if self.request_started is not None else None
        if self.closed:
            return
        view, frames = result
        if generation != self.generation or not self.enabled.get() or view != self.map.viewport():
            self.view_changed()
            self.update_buttons()
            return
        self.last_success = datetime.now(timezone.utc)
        self.error = ''
        self.diagnostic = ''
        self.loaded_view, self.frames = view, frames
        self.index = len(frames)-1
        self.show_frame()
        self.arm_refresh()
        self.update_buttons()

    def failed(self, generation, view, error):
        self.busy = False
        if self.closed:
            return
        if generation != self.generation or not self.enabled.get():
            self.view_changed()
            self.update_buttons()
            return
        if view != self.map.viewport():
            self.view_changed()
            self.update_buttons()
            return
        self.last_failure = datetime.now(timezone.utc)
        self.last_duration = time.monotonic()-self.request_started if self.request_started is not None else None
        self.error = 'Radar refresh failed'
        self.diagnostic = error_description(error)
        self.status.set('RADAR UNAVAILABLE · '+self.diagnostic)
        self.arm_refresh()
        self.update_buttons()

    def arm_refresh(self):
        if self.refresh_timer is not None:
            self.app.root.after_cancel(self.refresh_timer)
        self.next_refresh_at = datetime.now(timezone.utc)+timedelta(minutes=5)
        self.refresh_timer = self.app.after(300000,self.auto_refresh)

    def auto_refresh(self):
        self.refresh_timer = None
        self.refresh(force=True)
        if self.refresh_timer is None:
            self.arm_refresh()

    def show_frame(self):
        if not self.frames or self.loaded_view != self.map.viewport():
            return
        stamp, image = self.frames[self.index]
        self.map.set_radar(image,self.loaded_view)
        self.tick()

    def tick(self):
        if self.closed or not self.enabled.get() or not self.frames or self.busy:
            return
        if self.loaded_view != self.map.viewport():
            self.status.set('Map view changed · Radar is hidden while the new view loads.')
            return
        stamp = self.frames[self.index][0]
        age = max(0,int((datetime.now(timezone.utc).timestamp()-stamp)/60))
        latest_age = datetime.now(timezone.utc).timestamp()-self.frames[-1][0]
        state = 'STALE RADAR' if latest_age > 1200 or self.error else 'Past radar'
        generated = datetime.fromtimestamp(stamp,timezone.utc)
        self.status.set(f'RainViewer · {state} · Frame generated {generated:%Y-%m-%d %H:%M UTC} · {age} min ago · Frame {self.index+1}/{len(self.frames)}'+
                        (f' · {self.error}: {self.diagnostic}' if self.error else '')+' · Radar coverage can be incomplete.')

    def connection_report(self):
        def stamp(value):
            return value.strftime('%Y-%m-%d %H:%M:%S UTC') if value else 'Not recorded'
        state = 'Off' if not self.enabled.get() else 'Loading' if self.busy else 'Refresh failed' if self.error else 'Loaded' if self.frames else 'Waiting'
        lines = [f'Radar: {state}',f'Last attempt: {stamp(self.last_attempt)}',
                 f'Last successful refresh: {stamp(self.last_success)}',f'Last failed refresh: {stamp(self.last_failure)}',
                 f'Last load duration: {self.last_duration:.2f} seconds' if self.last_duration is not None else 'Last load duration: Not measured',
                 f'Next refresh: {stamp(self.next_refresh_at) if self.enabled.get() else "Not scheduled (radar off)"}',
                 f'Loaded frames: {len(self.frames)}',f'Frames match current map view: {self.loaded_view == self.map.viewport()}',
                 f'Last refresh error: {self.diagnostic or "None recorded"}',f'Metadata endpoint: {METADATA_URL}',
                 f'Tile origin: {TILE_HOST}']
        if self.frames:
            lines.append('Newest loaded frame: '+stamp(datetime.fromtimestamp(self.frames[-1][0],timezone.utc)))
        snapshot = self.service.connection_info() if hasattr(self.service,'connection_info') else {}
        if not isinstance(snapshot,dict):
            snapshot = {}
        if snapshot:
            for host,values in sorted(snapshot.items()):
                lines.extend(['',host,f'  Fetches: {values["requests"]} · Completed: {values["successes"]} · Failed: {values["failures"]} · In flight: {values["active"]}',
                              f'  Last result: {values["result"]}',f'  Last attempt: {stamp(values["last_attempt"])}',
                              f'  Last HTTP success: {stamp(values["last_success"])}'])
        for host in ('api.rainviewer.com','tilecache.rainviewer.com'):
            if host not in snapshot:
                lines.append(host+': No fetches observed in this session.')
        if not snapshot:
            lines.append('HTTP request results: No requests observed in this session.')
        return '\n'.join(lines)

    def show_details(self):
        window = Window(self.app,'Radar connection details',width=760,height=570)
        Label(window,'Radar connection details',style='Heading.TLabel')
        text = TextArea(window,readonly=True,expand=True,fill='both',bg='#101c30',fg='#e5edf8',padx=12,pady=12)
        text.set(self.connection_report())
        buttons = window.row(padding=0)
        Button(buttons,'Refresh details',lambda:text.set(self.connection_report()))
        Button(buttons,'Close',window.close)
        return window

    def step(self, delta):
        self.stop_playback()
        if self.frames and self.loaded_view == self.map.viewport() and not self.busy:
            self.index = (self.index+delta)%len(self.frames)
            self.show_frame()
        self.update_buttons()

    def toggle_play(self):
        if self.playing:
            self.stop_playback()
        elif self.frames and self.loaded_view == self.map.viewport() and not self.busy:
            self.playing = True
            self.advance()
        self.update_buttons()

    def advance(self):
        self.play_timer = None
        if not self.playing or self.closed:
            return
        if not self.map.canvas.winfo_ismapped():
            self.stop_playback()
            self.update_buttons()
            return
        self.index = (self.index+1)%len(self.frames)
        self.show_frame()
        self.play_timer = self.app.after(750,self.advance)

    def close(self):
        self.closed = True
        self.generation += 1
        self.stop_playback()
        for timer in (self.view_timer,self.refresh_timer):
            if timer is not None:
                self.app.root.after_cancel(timer)
        self.service.close()
        self.map.set_radar()
        self.frames = []
