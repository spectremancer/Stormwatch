"""Opt-in radar controls. Tk stays on the main thread; requests stay in workers."""
from datetime import datetime, timezone
import webbrowser

from TkFlow import Button, Checkbox, Label
from radar import RadarService


class RadarPanel:
    def __init__(self, parent, alert_map, service=None):
        self.app, self.map = parent.app, alert_map
        self.service = service or RadarService()
        self.frames = []
        self.loaded_view = None
        self.index, self.generation = 0, 0
        self.busy = self.playing = self.closed = False
        self.error = ''
        self.play_timer = self.view_timer = self.refresh_timer = None
        self.enabled = Checkbox(parent,'Show recent radar',value=False,command=lambda _: self.toggle())
        tools = parent.row(padding=0)
        self.play_button = Button(tools,'Play',self.toggle_play)
        self.previous = Button(tools,'Previous frame',lambda: self.step(-1))
        self.next = Button(tools,'Next frame',lambda: self.step(1))
        self.refresh_button = Button(tools,'Refresh radar',lambda:self.refresh(force=True))
        status_holder = parent.column(padding=0)
        status_holder.widget.configure(height=52)
        status_holder.widget.grid_propagate(False)
        self.status = Label(status_holder,'Radar off · Alert monitoring works independently.',style='Muted.TLabel',wraplength=740,expand=True,fill='both',anchor='nw')
        self.status.widget.bind('<Configure>',lambda e:self.status.configure(wraplength=max(200,e.width)))
        legend = parent.row(padding=0)
        Label(legend,'Radar: blue/green → yellow/red = increasing precipitation intensity',style='Muted.TLabel',expand=True,wraplength=300)
        Button(legend,'RainViewer',lambda:webbrowser.open('https://www.rainviewer.com'))
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
        generation = self.generation
        self.status.set('Loading recent observed radar… Alert boundaries remain available.')
        self.update_buttons()
        self.app.run_in_thread(self.service.load,view,
            on_result=lambda result:self.loaded(generation,result),
            on_error=lambda error:self.failed(generation,view,error))

    def loaded(self, generation, result):
        self.busy = False
        if self.closed:
            return
        view, frames = result
        if generation != self.generation or not self.enabled.get() or view != self.map.viewport():
            self.view_changed()
            self.update_buttons()
            return
        self.error = ''
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
        self.error = 'Radar refresh failed'
        self.status.set('RADAR UNAVAILABLE · Check the connection or retry. '+
                        ('Previous imagery retained with its original timestamp.' if self.frames else 'No radar imagery is displayed.'))
        self.arm_refresh()
        self.update_buttons()

    def arm_refresh(self):
        if self.refresh_timer is not None:
            self.app.root.after_cancel(self.refresh_timer)
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
        state = 'STALE RADAR' if latest_age > 1200 or self.error else 'Observed radar'
        observed = datetime.fromtimestamp(stamp,timezone.utc)
        self.status.set(f'{state} · {observed:%Y-%m-%d %H:%M UTC} · {age} min ago · Frame {self.index+1}/{len(self.frames)}'+
                        (f' · {self.error}' if self.error else '')+' · Radar coverage can be incomplete.')

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
