"""Capture real Stormwatch windows with isolated, clearly simulated sample data.

Run from a desktop session at least 1364 x 1024 pixels:
    python scripts/capture_screenshots.py

No weather requests or device notifications are made. All state is temporary.
Images are unaltered client-area screen captures, saved under docs/screenshots.
"""
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock

os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ.setdefault('TZ', 'America/Chicago')
if hasattr(time, 'tzset'):
    time.tzset()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import ImageGrab
from alert_history import AlertHistory
from locations import LocationProfile
from main import StormwatchApp
from sound_preferences import SoundPreferences

OUTPUT = Path(__file__).resolve().parents[1] / 'docs' / 'screenshots'


def sample(number, event, area, severity, bounds, minutes, now):
    west, south, east, north = bounds
    return dict(id=f'SIMULATION-README-{number}', event=event, severity=severity,
        headline=f'SIMULATION — {event} for {area}', area=area, urgency='Immediate',
        sent=(now-timedelta(minutes=12-number)).isoformat(),
        expires=(now+timedelta(minutes=minutes)).isoformat(), ends='',
        description='SIMULATION ONLY. Fictional weather used to demonstrate the interface.',
        instruction='SIMULATION ONLY — No real weather threat. Read official NWS instructions during actual events.',
        url='', message_type='Alert', references=[], simulated=True,
        geocode={'UGC':['FLC021', 'FLC057', 'FLC086']},
        geometry={'type':'Polygon', 'coordinates':[[[west,south],[east,south],
                    [east,north],[west,north],[west,south]]]})


def capture(ui, window, name):
    root = window.root
    root.deiconify()
    root.lift()
    root.focus_force()
    root.event_generate('<Motion>', warp=True, x=2, y=2)
    # Let geometry, Map events, text wrapping and native painting settle.
    deadline = time.monotonic() + .35
    while time.monotonic() < deadline:
        ui.app.root.update()
        time.sleep(.01)
    x, y = root.winfo_rootx(), root.winfo_rooty()
    width, height = root.winfo_width(), root.winfo_height()
    assert x >= 0 and y >= 0
    assert x+width <= root.winfo_screenwidth() and y+height <= root.winfo_screenheight(), 'Window exceeds display'
    image = ImageGrab.grab(bbox=(x,y,x+width,y+height))
    path = OUTPUT / name
    image.save(path, optimize=True)
    print(f'{path.relative_to(OUTPUT.parent.parent)}: {width} × {height}')


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stormwatch-screenshots-') as directory:
        previous = {key:os.environ.get(key) for key in ('LOCALAPPDATA','XDG_STATE_HOME')}
        os.environ['LOCALAPPDATA'] = os.environ['XDG_STATE_HOME'] = directory
        ui = None
        try:
            store = AlertHistory(Path(directory)/'preview.sqlite3')
            store.save_setting('appearance_theme', 'Navy')
            events = ['Tornado Warning','Tornado Watch','Severe Thunderstorm Warning',
                      'Severe Thunderstorm Watch','Flash Flood Warning','Flood Watch',
                      'Wind Advisory','Hurricane Warning','Hurricane Watch']
            profiles = [LocationProfile(name=name, latitude=lat, longitude=lon,
                        events=events, sound_events=['Tornado Warning','Tornado Watch',
                        'Hurricane Warning','Hurricane Watch'], speech=True)
                        for name,lat,lon in [('Home',25.76,-80.19),('Work',26.14,-81.80),
                                             ('Family',27.95,-82.46)]]
            for profile in profiles:
                store.save_profile(profile)
            service = Mock(interval=60)
            for action in ('fetch_alerts','fetch_cancellations','deliver_sound','deliver_desktop'):
                getattr(service,action).side_effect = AssertionError('Screenshots must not use live services or devices')
            ui = StormwatchApp(service, store)
            root = ui.app.root
            root.geometry('1340x980+0+0')
            assert root.winfo_screenwidth() >= 1340 and root.winfo_screenheight() >= 980
            # Freeze the local expiry timer for a consistent documentation session.
            root.after_cancel(ui.health_timer)
            ui.health_timer = None
            now = datetime.now(timezone.utc).replace(microsecond=0)
            alerts = [
                sample(1,'Tornado Warning','Collier County, Florida','Extreme',(-82.05,25.90,-81.55,26.40),42,now),
                sample(2,'Hurricane Warning','Miami-Dade County, Florida','Severe',(-81.00,25.30,-80.00,26.20),65,now),
                sample(3,'Flood Watch','Southwest Florida; Southeast Florida; Tampa Bay','Moderate',(-82.80,25.00,-79.80,28.30),310,now),
                sample(4,'Hurricane Watch','Hillsborough County, Florida','Severe',(-82.90,27.55,-82.10,28.30),155,now),
            ]
            for alert in alerts:
                matches = [p for p in profiles if p.matches(alert)]
                version,kind,_ = store.observe(alert, locations=matches)
                for profile in matches:
                    for channel in ('sound','desktop','speech'):
                        allowed = profile.allows(alert,channel)
                        reason = ('SIMULATION · Documentation preview; no device used' if allowed else
                                  'SIMULATION · Event excluded by the profile notification preferences')
                        store.record_decision(alert['id'],version,profile,channel,allowed,reason)
                        store.schedule(alert['id'],version,profile.id,channel,quiet=not allowed,reason=reason)
                        if allowed:
                            store.receipt(alert['id'],version,profile.id,channel,
                                RuntimeError('SIMULATION · Example desktop service failure')
                                if alert is alerts[0] and channel == 'desktop' else None)
                store.mark_displayed(alert['id'],version)
                ui.append_alert(alert,kind,[p.name for p in matches])
            updated = dict(alerts[1], message_type='Update',
                instruction='SIMULATION ONLY — Updated sample instructions. No real weather threat.',
                expires=(now+timedelta(minutes=95)).isoformat())
            store.observe(updated, locations=[profiles[0]])
            ui.append_alert(updated,'Extended',['Home'])
            ui.render_active()
            ui.state.set('●  SIMULATION')
            ui.state.configure(foreground=ui.app.palette['warning'])
            ui.health.set('SIMULATION · Fictional sample alerts · No live weather connection or device delivery')
            ui.overview.set_health('SIMULATION · Sample weather')
            ui.status.set('SIMULATION · README feature preview · Temporary profiles and history · Not official weather information')
            ui.appearance.apply('Navy')
            ui.commands.show_tab('Active Alerts')
            capture(ui,ui.app,'active-alerts.png')
            ui.commands.show_tab('Locations')
            capture(ui,ui.app,'saved-locations.png')
            ui.commands.show_tab('Map')
            root.update()
            ui.map.fit()
            # National overview, with additional isolated fictional map examples.
            scenarios = [
                ('Red Flag Warning','Southern California','Severe',(-120,33.5,-116,36.2)),
                ('High Wind Warning','Pacific Northwest','Severe',(-124,45.4,-120.8,48)),
                ('Winter Storm Warning','Northern Rockies','Severe',(-115.5,44,-109,48)),
                ('Severe Thunderstorm Watch','Central Plains','Severe',(-103,36,-96,41)),
                ('Tornado Watch','Texas; Oklahoma','Severe',(-100,31.8,-94,36.5)),
                ('Flash Flood Warning','Lower Mississippi Valley','Severe',(-93,30.8,-89,34)),
                ('Flood Watch','Ohio Valley','Moderate',(-87,37.2,-80.5,41.2)),
                ('Wind Advisory','New England','Moderate',(-74,41.5,-69.5,45.2))]
            rows = list(ui.map.rows)
            for number,(event,area,severity,bounds) in enumerate(scenarios,20):
                a = sample(number,event,area,severity,bounds,180,now)
                rows.append(dict(id=a['id'],version='SIMULATION',alert=a,locations=[]))
            ui.map.render(rows,ui.profiles)
            ui.map._initial_region = False
            ui.map.center = (-98,38)
            ui.map.scale = min((ui.map.canvas.winfo_width()-80)/62,(ui.map.canvas.winfo_height()-80)/34)
            ui.map.request_draw()
            capture(ui,ui.app,'alert-map.png')
            ui.commands.show_tab('Notifications')
            ui.delivery_panel.refresh()
            # Show the deliberately fabricated failure and independent channel results.
            for iid,row in ui.delivery_panel.row_map.items():
                if row['state'] == 'failed':
                    ui.delivery_panel.table.tree.selection_set(iid)
                    ui.delivery_panel.table.tree.see(iid)
                    break
            capture(ui,ui.app,'notification-delivery.png')
            ui.commands.show_tab('History')
            ui.history_panel.refresh()
            capture(ui,ui.app,'alert-history.png')
            sound = SoundPreferences(ui)
            sound.window.root.geometry('820x820+180+70')
            capture(ui,sound.window,'sound-settings.png')
            sound.window.close()
            ui.open_metrics()
            deadline = time.monotonic()+10
            while ui.metrics.busy and time.monotonic()<deadline:
                root.update()
                time.sleep(.01)
            assert not ui.metrics.busy, 'Metrics did not finish'
            ui.metrics.message.set('SIMULATION · Fictional event statistics · No live data or real delivery')
            ui.metrics.window.root.geometry('1060x680+140+100')
            capture(ui,ui.metrics.window,'event-metrics.png')
            ui.metrics.hide()
            guide = ui.commands.open_documentation('Spoken alerts')
            guide.search.set('speech')
            guide.window.root.geometry('1120x820+100+70')
            capture(ui,guide.window,'documentation.png')
            assert not ui.running
            service.fetch_alerts.assert_not_called()
            service.deliver_sound.assert_not_called()
            service.deliver_desktop.assert_not_called()
        finally:
            if ui:
                ui.close()
                ui.cleanup_thread.join(timeout=10)
                assert not ui.cleanup_thread.is_alive()
            for key,value in previous.items():
                if value is None:
                    os.environ.pop(key,None)
                else:
                    os.environ[key] = value
            for handler in list(logging.getLogger('WeatherService').handlers):
                handler.close()
                logging.getLogger('WeatherService').removeHandler(handler)


if __name__ == '__main__':
    main()
