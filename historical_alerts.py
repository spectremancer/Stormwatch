"""Opt-in, bounded downloads from the official NWS rolling alert archive."""
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import threading
import time as clock
from urllib.parse import urlparse

import requests

from locations import STATE_CODES
from event_catalog import is_supported_event, is_weather_event


class DownloadCancelled(Exception):
    pass


@dataclass(frozen=True)
class ArchiveQuery:
    start: str
    end: str
    state: str
    events: str = ''
    automatic: bool = False

    @classmethod
    def latest(cls, state='US', events=''):
        return cls('', '', state, events, automatic=True)

    def parameters(self, now=None):
        now = now or datetime.now(timezone.utc)
        earliest = now - timedelta(days=7)
        if self.automatic:
            start, end = earliest, now
        else:
            try:
                first, last = date.fromisoformat(self.start), date.fromisoformat(self.end)
            except ValueError:
                raise ValueError('Dates must use YYYY-MM-DD.') from None
            if first > last:
                raise ValueError('The start date must be on or before the end date.')
            if first < earliest.astimezone().date() or last > now.astimezone().date():
                raise ValueError('NWS only provides a rolling seven-day archive. Choose recent dates through today.')
            start = max(datetime.combine(first,time.min).astimezone(timezone.utc),earliest)
            end = min(datetime.combine(last+timedelta(days=1),time.min).astimezone(timezone.utc),now)
        state = self.state.strip().upper()
        if state != 'US' and state not in STATE_CODES:
            raise ValueError('Choose All US or a US state/territory to download.')
        if self.events and any(not is_supported_event(event) or
                               not all(c.isascii() and (c.isalnum() or c == ' ') for c in event)
                               for event in self.events.split(',')):
            raise ValueError('Choose valid supported NWS weather-event names.')
        params = dict(start=start.isoformat(),end=end.isoformat(),status='actual',limit=500)
        if state != 'US':
            params['area'] = state
        if self.events:
            params['event'] = self.events
        return params


class WindowFull(Exception):
    """A time window reached its retrieval budget and needs subdivision."""


def download_recent(query, store, parse_alert, cancel=None, progress=None, session=None, now=None):
    """Queue daily windows, fully retrieve them, then atomically import history only."""
    from alert_history import version_of

    cancel = cancel if cancel is not None else threading.Event()
    params = query.parameters(now)
    first, last = (datetime.fromisoformat(params[key]) for key in ('start', 'end'))
    windows = deque()
    start = first
    while start < last:
        end = min(start + timedelta(days=1), last) if query.automatic else last
        windows.append((start, end))
        start = end
    deadline = clock.monotonic() + (900 if query.automatic else 120)
    owned_session = session is None
    session = session if session is not None else requests.Session()
    alerts = {}
    received = skipped = transferred = requests_made = accepted = 0

    def check_cancel():
        if cancel.is_set():
            raise DownloadCancelled('Download cancelled. No archive records were imported.')
        if clock.monotonic() > deadline:
            raise ValueError('Download exceeded its time budget. No records were imported; try again later or select fewer event types.')

    def fetch_window(start, end):
        nonlocal transferred, requests_made
        url = 'https://api.weather.gov/alerts'
        request_params = dict(params, start=start.isoformat(), end=end.isoformat())
        visited, values = set(), []
        count = unsupported = 0
        while url:
            check_cancel()
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.netloc != 'api.weather.gov' or parsed.path != '/alerts' or url in visited:
                raise ValueError('Invalid NWS archive pagination link; no records were imported.')
            if len(visited) >= 10:
                raise WindowFull()
            if requests_made >= 1000:
                raise ValueError('Download exceeded 1,000 requests. No records were imported; select fewer event types.')
            visited.add(url)
            requests_made += 1
            with session.get(url, params=request_params, timeout=(5,20), allow_redirects=False, headers={
                'User-Agent':'Stormwatch/1.0 (github.com/spectremancer/Stormwatch)',
                'Accept':'application/geo+json',
            }) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('NWS archive redirected the request; no records were imported.')
                data = response.json()
            check_cancel()
            if not isinstance(data,dict) or not isinstance(data.get('features'),list):
                raise ValueError('Invalid NWS archive response; no records were imported.')
            count += len(data['features'])
            transferred += len(data['features'])
            if progress:
                progress(transferred)
            # Subdivide even without a next link at exactly the ceiling, rather
            # than assuming the server returned every record in a busy window.
            if count > 5000 or (query.automatic and count >= 5000):
                raise WindowFull()
            for feature in data['features']:
                if not isinstance(feature,dict) or not isinstance(feature.get('properties'),dict):
                    raise ValueError('Invalid NWS archive alert; no records were imported.')
                if feature['properties'].get('status') != 'Actual':
                    unsupported += 1
                    continue
                if not query.events and not is_weather_event(feature['properties'].get('event')):
                    unsupported += 1
                    continue
                alert = parse_alert(feature)
                if alert is None:
                    unsupported += 1
                else:
                    values.append(alert)
            pagination = data.get('pagination') or {}
            if not isinstance(pagination,dict):
                raise ValueError('Invalid NWS archive pagination.')
            url = pagination.get('next')
            if url is not None and not isinstance(url,str):
                raise ValueError('Invalid NWS archive pagination.')
            request_params = None
        return values, count, unsupported

    try:
        while windows:
            check_cancel()
            start, end = windows.popleft()
            try:
                values, count, unsupported = fetch_window(start, end)
            except WindowFull:
                if not query.automatic:
                    raise ValueError('More than 5,000 alerts matched. Use the automatic seven-day download.') from None
                if end - start <= timedelta(minutes=1):
                    raise ValueError('NWS returned too many records within a one-minute window. No records were imported.') from None
                middle = start + (end-start)/2
                windows.appendleft((middle,end))
                windows.appendleft((start,middle))
                continue
            received += count
            skipped += unsupported
            accepted += len(values)
            for alert in values:
                alerts[(alert['id'],version_of(alert))] = alert
            if len(alerts) > 100000:
                raise ValueError('Download exceeded 100,000 unique versions. No records were imported; select fewer event types.')
        check_cancel()
        imported = store.import_archive(list(alerts.values()),query.state.strip().upper(),cancel)
        return dict(received=received,imported=imported,duplicates=accepted-imported,skipped=skipped)
    finally:
        if owned_session:
            session.close()
