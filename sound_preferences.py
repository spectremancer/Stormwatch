"""Per-location event allowlist for automatic alert.mp3 playback."""
from dataclasses import replace
import sqlite3

from TkFlow import Button, Checkbox, Form, Label, Window


class SoundPreferences:
    def __init__(self, owner):
        self.owner, self.profile = owner, owner.profile
        self.window = Window(owner.app,f'Sound events · {self.profile.name}',width=650,height=680)
        Label(self.window,f'Play alert.mp3 for {self.profile.name}',style='Heading.TLabel')
        Label(self.window,'Choose which monitored events can play sound. Event monitoring and desktop notifications\n'
              'keep their own settings. The location Sound switch and watch/warning rules must also allow playback.',
              style='Muted.TLabel',wraplength=600)
        self.follow = Checkbox(self.window,'Allow sound for all monitored event types (including newly selected types)',
                               value=self.profile.sound_events is None,command=lambda _:self.update())
        tools = self.window.row(padding=0)
        Button(tools,'Tornado + hurricane',self.critical_only)
        Button(tools,'All event types',self.all_events)
        Button(tools,'No event sounds',self.none)
        self.form = Form(self.window,'Specific event types',expand=True,fill='both')
        self.form.canvas.configure(background='#0b1424')
        events = sorted(set(owner.choices) | set(self.profile.events) | set(self.profile.sound_events or []),
                        key=lambda event:(not event.startswith(('Tornado ','Hurricane ')),event))
        self.choices = {event:Checkbox(self.form.body,event,value=self.profile.sound_events is None or event in self.profile.sound_events,
                       command=lambda _:self.update()) for event in events}
        self.note = Label(self.window,'',style='Muted.TLabel',wraplength=600)
        actions = self.window.row(padding=0)
        Button(actions,'Save sound events',self.save)
        Button(actions,'Cancel',self.window.close)
        self.update()

    def update(self):
        follow = self.follow.get()
        for choice in self.choices.values():
            if follow:
                choice.set(True)
            choice.disable() if follow else choice.enable()
        selected = sum(choice.get() for choice in self.choices.values())
        self.note.set('All monitored event types may play sound.' if follow else
                      f'{selected} event types may play sound; unchecked events stay silent.\n'
                      'The Test alert sound button is a manual preview and always plays when requested.')
        if not self.profile.sound:
            self.note.set(self.note.get()+'\nSound is currently off for this location; enable it in Edit for automatic playback.')

    def critical_only(self):
        self.follow.set(False)
        for event,choice in self.choices.items():
            choice.set(event.startswith(('Tornado ','Hurricane ')))
        self.update()

    def all_events(self):
        self.follow.set(True)
        self.update()

    def none(self):
        self.follow.set(False)
        for choice in self.choices.values():
            choice.set(False)
        self.update()

    def save(self):
        current = next((p for p in self.owner.profiles if p.id == self.profile.id),None)
        if current is None:
            self.note.set('This location was removed. Close this window and choose another location.')
            return
        selected = None if self.follow.get() else [event for event,choice in self.choices.items() if choice.get()]
        try:
            candidate = replace(current,sound_events=selected).validate()
            self.owner.history.save_profile(candidate)
        except (ValueError,sqlite3.Error) as error:
            self.note.set(f'Could not save sound preferences: {error}')
            return
        self.owner.refresh_profiles(candidate)
        self.owner.status.set('Sound events saved · Preferences apply on the next refresh. Test sound is a manual preview.')
        self.window.close()
