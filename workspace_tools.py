"""Focused notification configuration and an actionable monitoring-readiness review."""
from dataclasses import replace
import sqlite3
from TkFlow import Button, Checkbox, Dropdown, Form, Label, TextArea, Window
from dashboard_views import Tabs
from event_catalog import WEATHER_EVENTS, CRITICAL_EVENTS
from notification_rules import add_rule_fields, rule_values


class NotificationCenter:
    def __init__(self, owner):
        self.owner = owner
        self.profile = owner.profile
        self.window = Window(owner.app,'Stormwatch · Notification preferences',width=900,height=700,
                             min_width=720,min_height=520)
        Label(self.window,f'Notification preferences · {self.profile.name}',style='Heading.TLabel')
        Label(self.window,'Settings below apply to this saved location. Save changes before closing.\n'
              'Monitoring selections and geography still determine which alerts match.',style='Muted.TLabel',wraplength=780)
        tabs = Tabs(self.window)
        rules = tabs.page('Channels & rules')
        self.rules = Form(rules,'Enable channels and choose category rules',expand=True,fill='both')
        for channel,title in (('sound','Play alert.mp3'),('desktop','Desktop notifications'),('speech','Read alerts aloud')):
            self.rules.add_checkbox(channel,title,getattr(self.profile,channel),text=title)
        self.rules.add_dropdown('speech_length','Spoken report length',
            ['Brief (4 areas)','Standard (8 areas)','Detailed (16 areas)'],
            value='Brief (4 areas)' if self.profile.speech_max_areas<=4 else
                  'Standard (8 areas)' if self.profile.speech_max_areas<=8 else 'Detailed (16 areas)')
        add_rule_fields(self.rules,self.profile)
        self.event_choices = {}
        self.follow = {}
        for channel,title in (('sound','Sound events'),('speech','Speech events')):
            page = tabs.page(title)
            selection = getattr(self.profile,channel+'_events')
            self.follow[channel] = Checkbox(page,'Follow all monitored event types',value=selection is None)
            tools = page.row(padding=0)
            for label,values in (('Tornado + hurricane',set(CRITICAL_EVENTS)),('All',set(WEATHER_EVENTS)),('None',set())):
                Button(tools,label,lambda c=channel,v=values:self.preset(c,v))
            form = Form(page,'Event allowlist',expand=True,fill='both')
            self.event_choices[channel] = {event:Checkbox(form.body,event,value=selection is None or event in selection)
                for event in sorted(set(WEATHER_EVENTS)|set(self.profile.events),key=lambda e:(e not in CRITICAL_EVENTS,e))}
        preview = tabs.page('Preview decisions')
        self.preview_event = Dropdown(preview,list(WEATHER_EVENTS),value='Tornado Warning')
        Button(preview,'Preview current form settings',self.preview)
        self.report = TextArea(preview,readonly=True,expand=True,fill='both',bg='#101c30',fg='#e5edf8')
        Button(preview,'Test devices…',owner.commands.test_notification)
        self.note = Label(self.window,'Sound, desktop, and speech have independent delivery receipts.',style='Muted.TLabel',wraplength=780)
        actions = self.window.row(padding=0)
        Button(actions,'Save preferences',self.save,style='Primary.TButton')
        Button(actions,'Help',lambda:owner.commands.open_documentation('Notification rules'))
        Button(actions,'Cancel',self.window.close)
        self.preview()

    def preset(self, channel, values):
        self.follow[channel].set(False)
        for event,choice in self.event_choices[channel].items():
            choice.set(event in values)

    def candidate(self):
        values = self.rules.get()
        options = dict(rule_values(values),**{c:values[c] for c in ('sound','desktop','speech')})
        areas,chars = {'Brief (4 areas)':(4,180),'Standard (8 areas)':(8,320),'Detailed (16 areas)':(16,480)}[values['speech_length']]
        options.update(speech_max_areas=areas,speech_max_chars=chars)
        for channel in ('sound','speech'):
            options[channel+'_events'] = None if self.follow[channel].get() else sorted(
                event for event,choice in self.event_choices[channel].items() if choice.get())
        current = next((profile for profile in self.owner.profiles if profile.id==self.profile.id),None)
        if current is None:
            raise ValueError('This location was removed. Close this window and select a saved location.')
        return replace(current,**options).validate()

    def preview(self):
        try:
            profile = self.candidate()
        except ValueError as error:
            self.note.set(str(error))
            return
        event = self.preview_event.get()
        selected = profile.enabled and event in profile.events
        lines = [f'{event} · {profile.name}',f'Location enabled: {profile.enabled}',
                 f'Event monitored: {event in profile.events}',f'Geography: {profile.summary()}', '']
        for channel in ('sound','desktop','speech'):
            permitted = selected and profile.allows(event,channel)
            lines.append(f'{channel.title()}: '+('Eligible when geography and live delivery checks pass' if permitted else
                         'Disabled by location, monitored events, channel switch, category rule, or allowlist'))
        lines.extend(['','This previews preferences, not delivery. Previously successful versions do not replay.',
                      'Speech covers new issue timestamps after Start; cancellations and expirations stay silent.',
                      'Existing non-critical startup alerts populate quietly.'])
        self.report.set('\n'.join(lines))

    def save(self):
        try:
            candidate = self.candidate()
        except (ValueError,sqlite3.Error) as error:
            self.note.set(f'Preferences were not saved: {error}')
            return
        self.note.set('Saving preferences… You can continue using the app.')
        def done(profile):
            self.owner.refresh_profiles(profile)
            if not self.window._closed:
                self.profile = profile
                self.note.set('Saved. Successful channels will not replay.')
                self.preview()
        def failed(error):
            if not self.window._closed:self.note.set(f'Preferences were not saved: {error}')
        self.owner.preference_changes.save(candidate,done,failed)


def readiness(owner):
    window = Window(owner.app,'Stormwatch · Ready to monitor',width=760,height=610,min_width=650,min_height=430)
    Label(window,'Monitoring readiness',style='Heading.TLabel')
    report = TextArea(window,readonly=True,expand=True,fill='both',bg='#101c30',fg='#e5edf8',padx=12,pady=10)
    import shutil,sys
    lines = []
    for profile in owner.profiles:
        lines.extend([profile.name+(' · ENABLED' if profile.enabled else ' · DISABLED'),
            profile.summary(),f'{len(profile.events)} monitored types · {profile.rules_summary()}',
            'Nationwide coverage: add geography if this is unintended.' if not any(
                (profile.states,profile.counties,profile.latitude is not None)) else '', ''])
    lines.extend([f'NWS refresh: {owner.service.interval} seconds',
        'Speech engine: '+('Windows System.Speech' if sys.platform=='win32' else
                          shutil.which('espeak-ng') or shutil.which('espeak') or 'Unavailable — install espeak-ng'),
        'Desktop service: '+('Windows notifications' if sys.platform=='win32' else
                            shutil.which('notify-send') or 'Unavailable — install libnotify-bin'),
        '', 'Test the devices before relying on notifications. Keep the computer awake and connected.',
        'First refresh: existing non-critical events are quiet. Speech starts with newly issued events.'])
    report.set('\n'.join(lines))
    actions = window.row(padding=0)
    Button(actions,'Add location',owner.add_location)
    Button(actions,'Notification preferences',lambda:NotificationCenter(owner))
    Button(actions,'Test devices',owner.commands.test_notification)
    Button(actions,'Help',lambda:owner.commands.open_documentation('Quick start'))
    Button(window,'Close',window.close)
    return window
