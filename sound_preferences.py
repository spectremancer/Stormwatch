"""Per-location event allowlist for automatic alert.mp3 playback."""
from dataclasses import replace
import sqlite3

from TkFlow import Button, Checkbox, Form, Label, Window


class SoundPreferences:
    def __init__(self, owner, channel='sound'):
        self.owner, self.profile = owner, owner.profile
        self.channel = channel
        self.speaking = channel == 'speech'
        selection = getattr(self.profile,channel+'_events')
        self.window = Window(owner.app,f'{channel.title()} events · {self.profile.name}',width=650,height=720)
        Label(self.window,f'{"Read alerts aloud" if self.speaking else "Play alert.mp3"} for {self.profile.name}',style='Heading.TLabel')
        Label(self.window,'Speech uses your computer’s local voice and is independent of alert.mp3 and desktop settings.' if self.speaking else
              'Choose which monitored events can play sound. Event monitoring and desktop notifications\n'
              'keep their own settings. The location Sound switch and watch/warning rules must also allow playback.',
              style='Muted.TLabel',wraplength=600)
        if self.speaking:
            self.enabled = Checkbox(self.window,'Read alerts aloud for this location (off by default)',value=self.profile.speech)
            Button(self.window,'Test voice',lambda:owner.test_speech(lambda value:self.note.set(value) if not self.window._closed else None))
        self.follow = Checkbox(self.window,f'Allow {channel} for all monitored event types (including newly selected types)',
                               value=selection is None,command=lambda _:self.update())
        tools = self.window.row(padding=0)
        Button(tools,'Tornado + hurricane',self.critical_only)
        Button(tools,'All event types',self.all_events)
        Button(tools,'No spoken events' if self.speaking else 'No event sounds',self.none)
        self.form = Form(self.window,'Specific event types',expand=True,fill='both')
        self.form.canvas.configure(background='#0b1424')
        events = sorted(set(owner.choices) | set(self.profile.events) | set(selection or []),
                        key=lambda event:(not event.startswith(('Tornado ','Hurricane ')),event))
        self.choices = {event:Checkbox(self.form.body,event,value=selection is None or event in selection,
                       command=lambda _:self.update()) for event in events}
        self.note = Label(self.window,'',style='Muted.TLabel',wraplength=600)
        actions = self.window.row(padding=0)
        Button(actions,f'Save {channel} events',self.save)
        Button(actions,'Cancel',self.window.close)
        self.update()

    def update(self):
        follow = self.follow.get()
        for choice in self.choices.values():
            if follow:
                choice.set(True)
            choice.disable() if follow else choice.enable()
        selected = sum(choice.get() for choice in self.choices.values())
        if self.speaking:
            message = ('All monitored event types may be spoken.' if follow else f'{selected} selected event types may be spoken.')
            message += '\nWindows uses System.Speech; macOS uses say; Linux needs espeak-ng or espeak. Test voice is a manual preview.'
        else:
            message = ('All monitored event types may play sound.' if follow else
                       f'{selected} event types may play sound; unchecked events stay silent.')
            message += '\nThe Test sound button is a manual preview and always plays when requested.'
        self.note.set(message)
        if not self.speaking and not self.profile.sound:
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
            changes = {self.channel+'_events':selected}
            if self.speaking:
                changes['speech'] = self.enabled.get()
            candidate = replace(current,**changes).validate()
            self.owner.history.save_profile(candidate)
        except (ValueError,sqlite3.Error) as error:
            self.note.set(f'Could not save {self.channel} preferences: {error}')
            return
        self.owner.refresh_profiles(candidate)
        self.owner.status.set(f'{self.channel.title()} events saved · Preferences apply on the next refresh. Tests are manual previews.')
        self.window.close()
