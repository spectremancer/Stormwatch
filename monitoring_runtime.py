"""Monitoring health and optional geography work, independent of widget construction."""
from dataclasses import dataclass
from datetime import datetime, timezone
import requests
import threading
from models import HealthStatus


@dataclass(frozen=True)
class ConnectionHealth:
    state: HealthStatus
    detail: str
    color: str


def connection_health(running, busy, last_success, interval, error='', coverage='', now=None):
    now = now or datetime.now(timezone.utc)
    age = max(0,int((now-last_success).total_seconds())) if last_success else None
    if not running:
        state, color = 'PAUSED', 'bad'
    elif last_success is None:
        state, color = ('CONNECTING' if busy else 'NO LIVE DATA'), 'warning'
    elif error or age >= max(120,interval*2):
        state, color = 'STALE', 'warning'
    elif coverage:
        state, color = 'DEGRADED', 'warning'
    else:
        state, color = 'LIVE', 'good'
    detail = (f'Last success {last_success.astimezone():%H:%M:%S} ({age}s ago)' if last_success else
              'NO LIVE DATA · Waiting for a successful refresh')
    if coverage:
        detail += ' • Cancellation coverage incomplete'
    if error:
        detail += ' • Refresh failed'
    return ConnectionHealth(HealthStatus(state),detail,color)


class BoundaryResolver:
    """An optional, isolated HTTP session: never owns the sound-delivery lock."""
    def __init__(self):
        self._zone_cache = {}
        self.stop_event = threading.Event()

    def resolve(self, alerts, profiles):
        from WeatherService import WeatherService
        # Each task owns its session; cache only successful geometry, bounded by
        # the finite NWS zone catalog. Failed lookups do not erase alert content.
        with requests.Session() as session:
            session.headers.update({'User-Agent':'Stormwatch/1.1 (github.com/spectremancer/Stormwatch)',
                                    'Accept':'application/geo+json'})
            self.session = session
            WeatherService.enrich_boundaries(self,alerts,profiles)
        return alerts


def defer_store_work(function):
    """Keep Tk responsive while an atomic archive import owns the store lock."""
    from functools import wraps
    @wraps(function)
    def deferred(self,*args,**kwargs):
        if self.app._closed:
            return
        if not hasattr(self,'_store_waiters'):
            self._store_waiters = {}
        name = function.__name__
        previous = self._store_waiters.pop(name,None)
        if previous is not None:
            self.app.root.after_cancel(previous)
        if name=='toggle_monitoring' and self.running:
            return function(self,*args,**kwargs)
        if not self.history.lock.acquire(blocking=False):
            # Countdown/freshness labels can advance without touching SQLite.
            if name=='tick':
                trim_cached_expirations(self)
                self.cards.tick()
                self.overview.tick()
                self.update_health()
            self._store_waiters[name] = self.app.after(20,lambda:deferred(self,*args,**kwargs))
            return
        try:
            return function(self,*args,**kwargs)
        finally:
            self.history.lock.release()
    return deferred


def trim_cached_expirations(owner, now=None):
    """Remove expired visuals even when persistence is busy or unavailable."""
    from alert_history import expiration_of
    now = now or datetime.now(timezone.utc)
    rows = [row for row in owner.cards.rows if (end := expiration_of(row['alert'])) is None or end>now]
    if len(rows)!=len(owner.cards.rows):
        owner.active_query.invalidate()
        owner.snapshot = {row['id']:row['alert'] for row in rows}
        owner.cards.render(rows)
        owner.overview.render_locations(owner.profiles,rows)
        owner.map.render(rows,owner.profiles,plan=owner.map.plan)
        owner.active_count.set(f'{len(rows)} active alerts · {sum(p.enabled for p in owner.profiles)} enabled locations')
    if any(expiration_of(job[0]) and expiration_of(job[0])<=now for job in owner.speech_current_jobs):
        owner.speaker.stop()
