"""Isolated, explicitly simulated alert scenarios and notification previews."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import uuid

from TkFlow import Button, Checkbox, Dropdown, Label, TextArea
from alert_history import AlertHistory
from dashboard_views import AlertMap, Cards, Tabs
from delivery_panel import DeliveryPanel
from locations import LocationProfile


class DemoModel:
    def __init__(self):
        self.directory = tempfile.TemporaryDirectory(prefix='stormwatch-demo-')
        self.store = AlertHistory(Path(self.directory.name) / 'simulation.sqlite3')
        self.profile = LocationProfile(name='SIMULATION · Demo location', latitude=41.88, longitude=-87.63,
                                       zones=['ILC031'], sound=False, desktop=False)
        self.store.save_profile(self.profile)
        self.alert = None
        self.sequence = 0
        self.connection_failed = False
        self.fake_failures = set()

    def sample(self):
        now = datetime.now(timezone.utc)
        return dict(id='SIMULATION-' + uuid.uuid4().hex, event='Tornado Warning',
            headline='SIMULATION — Sample tornado warning. No real weather threat.',
            area='SIMULATION · Demo County, Illinois', severity='Extreme', urgency='Immediate',
            sent=now.isoformat(), expires=(now + timedelta(minutes=15)).isoformat(), ends='',
            instruction='SIMULATION ONLY. This is a software demonstration, not an official weather alert.',
            description='SIMULATED weather data for testing the Stormwatch interface.', url='',
            geocode={'UGC':['ILC031']}, references=[], message_type='Alert', simulated=True,
            geometry={'type':'Polygon', 'coordinates':[[[-87.9,41.7],[-87.4,41.7],[-87.4,42.05],[-87.9,42.05],[-87.9,41.7]]]})

    def scenario(self, name):
        if name == 'offline':
            self.connection_failed = True
            return None
        if name == 'recover':
            self.connection_failed = False
            return None
        self.connection_failed = False
        self.sequence += 1
        if name == 'new' or self.alert is None:
            # Retire the prior sample; a new scenario starts a fresh incident.
            self.store.reconcile(set())
            self.alert = self.sample()
        elif name == 'update':
            self.alert = dict(self.alert, headline=f'SIMULATION — Updated sample warning #{self.sequence}.',
                              instruction=f'SIMULATION ONLY — Sample instructions changed (revision {self.sequence}).',
                              message_type='Update', sent=datetime.now(timezone.utc).isoformat())
        elif name == 'extend':
            end = datetime.fromisoformat(self.alert['expires']) + timedelta(minutes=15)
            self.alert = dict(self.alert, expires=end.isoformat(), message_type='Update')
        elif name == 'cancel':
            self.alert = dict(self.alert, message_type='Cancel', headline='SIMULATION — Sample warning cancelled.')
        elif name == 'expire':
            self.alert = dict(self.alert, expires=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),
                              headline='SIMULATION — Sample warning expired.')
        else:
            raise ValueError('Unknown demonstration scenario')
        version, kind, _ = self.store.observe(self.alert)
        return self.alert, version, kind

    def close(self):
        self.store.close()
        self.directory.cleanup()


class DemoPanel:
    def __init__(self, parent, owner):
        self.owner = owner
        self.model = DemoModel()
        self.future = None
        self.busy = False
        self.synthetic_retry = False
        Label(parent, 'SIMULATION · No real weather alerts', style='Heading.TLabel')
        Label(parent, 'Samples stay separate from live monitoring. Device previews are off unless you enable them.',
              style='Muted.TLabel', wraplength=760)
        self.health = Label(parent, 'SIMULATION · Ready · No live connection is used', style='Health.TLabel')
        controls = parent.row(padding=0, spacing=8)
        self.scenarios = {'New warning':'new', 'Updated warning':'update', 'Extended warning':'extend',
                          'Cancelled warning':'cancel', 'Expired warning':'expire', 'Connection failure':'offline',
                          'Recover connection':'recover', 'Simulate delivery failure':'delivery_failure'}
        self.scenario_picker = Dropdown(controls, list(self.scenarios), expand=True)
        self.buttons = [Button(controls, 'Run simulation', self.run_selected)]
        options = parent.row(padding=0)
        self.sound = Checkbox(options, 'Play real sample sound (off by default)')
        self.desktop = Checkbox(options, 'Send real SIMULATION desktop notification')
        self.tabs = Tabs(parent)
        active = self.tabs.page('Sample cards')
        self.cards = Cards(active, owner.open_alert)
        feed = self.tabs.page('Sample feed')
        self.feed = TextArea(feed, readonly=True, max_lines=500, expand=True, fill='both',
                             bg='#101c30', fg='#e5edf8', padx=12, pady=12)
        map_page = self.tabs.page('Sample map')
        self.map = AlertMap(map_page, owner.open_alert)
        deliveries = self.tabs.page('Sample delivery')
        self.deliveries = DeliveryPanel(deliveries, self.model.store, self.retry,
                                        title='SIMULATION · Notification delivery', automatic=False, compact=True)
        self.message = Label(parent, 'Choose New warning to start. Optional previews use your actual sound/desktop devices.',
                             style='Muted.TLabel', wraplength=760)
        self.render()

    def run_selected(self):
        scenario = self.scenarios[self.scenario_picker.get()]
        if scenario == 'delivery_failure':
            self.simulate_delivery_failure()
        else:
            self.run_scenario(scenario)

    def set_busy(self, value):
        self.busy = value
        self.scenario_picker.disable() if value else self.scenario_picker.enable()
        for button in self.buttons:
            button.disable() if value else button.enable()

    def run_scenario(self, name):
        if self.busy:
            return
        if name not in ('new', 'offline', 'recover') and (not self.model.alert or
            not self.model.store.rows(active_only=True)):
            self.message.set('Start a new sample warning before trying an update or ending scenario.')
            return
        result = self.model.scenario(name)
        if result is None:
            self.health.set('SIMULATION · CONNECTION FAILED · Sample information is stale' if name == 'offline' else
                            'SIMULATION · Connection recovered · Sample information is current')
            self.message.set('Simulated connection change only; your real connection and alerts are unchanged.')
            return
        alert, version, kind = result
        if not self.model.store.displayed(alert['id'], version):
            self.feed.append(f"SIMULATION · {kind.upper()} · {alert['event']}\n{alert['headline']}\n{alert['area']}\n"
                             f"{alert['instruction']}\nExpires: {alert['expires']}\n\n")
            self.model.store.mark_displayed(alert['id'], version)
        self.health.set('SIMULATION · Sample information is current · No real weather threat')
        profile = replace(self.model.profile, sound=self.sound.get(), desktop=self.desktop.get())
        self.model.profile = profile
        self.model.store.save_profile(profile)
        jobs = []
        for channel, enabled in (('sound', profile.sound), ('desktop', profile.desktop)):
            if enabled and not (channel == 'sound' and kind in ('Cancelled', 'Expired')):
                self.model.store.schedule(alert['id'], version, profile.id, channel)
                jobs.append((alert, version, channel))
        self.render()
        self.message.set(f'SIMULATION · {kind} sample generated.' + (' Submitting the opted-in device previews…' if jobs else ' Device previews are off.'))
        if jobs:
            self.synthetic_retry = False
            self.submit(jobs)

    def render(self):
        rows = [dict(row, locations=['SIMULATION · Demo location']) for row in self.model.store.rows(active_only=True)]
        self.cards.render(rows)
        self.map.render(rows, [self.model.profile])
        self.deliveries.refresh()

    def submit(self, jobs, manual=False):
        self.set_busy(True)
        self.future = self.owner.app.run_in_thread(self.send, jobs, manual,
                                                   on_result=self.completed, on_error=self.failed)

    def send(self, jobs, manual=False):
        errors = []
        for alert, version, channel in jobs:
            key = (alert['id'], version, self.model.profile.id, channel)
            row = self.model.store.delivery(*key)
            if not row or (row['state'] != 'failed' if manual else not self.model.store.pending(*key)):
                continue
            try:
                # A deliberately fabricated failure is retried without touching an
                # OS channel; successful sample sound records are left alone.
                if key in self.model.fake_failures:
                    pass  # Fabricated records must never touch real devices, even after a failed receipt write.
                else:
                    with self.owner.sound_lock:
                        if self.owner.app._closed:
                            break
                        if channel == 'sound':
                            self.owner.service.deliver_sound()
                        else:
                            self.owner.service.deliver_desktop(alert, 'SIMULATION', 'SIMULATION · Demo location')
            except Exception as error:
                self.model.store.receipt(*key, error)
                errors.append(str(error))
            else:
                self.model.store.receipt(*key)
        return errors

    def completed(self, errors):
        self.set_busy(False)
        self.deliveries.refresh()
        if self.synthetic_retry and not errors:
            self.message.set('SIMULATION · Fabricated desktop result is now submitted. No device was used; sound was not retried.')
            self.synthetic_retry = False
            return
        self.message.set('SIMULATION · Preview submission failed: ' + errors[0] if errors else
                         'SIMULATION · Selected preview channels submitted. Check your devices; receipt is not proof of display or sound.')

    def failed(self, error):
        self.set_busy(False)
        self.deliveries.refresh()
        self.message.set(f'SIMULATION · Preview worker failed: {error}')

    def simulate_delivery_failure(self):
        if self.busy:
            return
        result = self.model.scenario('new')
        alert, version, kind = result
        self.feed.append(f"SIMULATION · NEW · {alert['event']}\n{alert['headline']}\n\n")
        self.model.store.mark_displayed(alert['id'], version)
        self.model.profile = replace(self.model.profile, sound=True, desktop=True)
        self.model.store.save_profile(self.model.profile)
        for channel in ('sound', 'desktop'):
            key = (alert['id'], version, self.model.profile.id, channel)
            self.model.store.schedule(*key, reason="SIMULATION: fabricated result; no device was used.")
            self.model.store.receipt(*key, 'SIMULATION: desktop service unavailable' if channel == 'desktop' else None)
            if channel == 'desktop':
                self.model.fake_failures.add(key)
        self.render()
        self.tabs.widget.select(self.deliveries.table.parent.widget)
        self.message.set('SIMULATION · No device was used. Sound is marked submitted; desktop failed. Select desktop and retry to see sound stay unchanged.')

    def retry(self, row):
        if self.busy:
            return
        key = (row['id'], row['version'], row['profile'], row['channel'])
        fake = key in self.model.fake_failures
        if not fake and not (self.sound.get() if row['channel'] == 'sound' else self.desktop.get()):
            self.message.set('Enable the corresponding real-device preview checkbox before retrying this preview.')
            return
        if row['current_version'] != row['version']:
            self.message.set('That sample version is no longer current. Generate a new sample instead.')
            return
        self.synthetic_retry = fake
        self.submit([(row['alert'], row['version'], row['channel'])], manual=True)

    def tick(self):
        self.cards.tick()

    def close(self):
        if self.future is not None:
            try:
                self.future.result()
            except Exception:
                pass
        self.model.close()
