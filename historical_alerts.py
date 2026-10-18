"""Opt-in, bounded downloads from the official NWS rolling alert archive."""
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

    def parameters(self, now=None):
        now = now or datetime.now(timezone.utc)
        try:
            first, last = date.fromisoformat(self.start), date.fromisoformat(self.end)
        except ValueError:
            raise ValueError('Dates must use YYYY-MM-DD.') from None
        earliest = now - timedelta(days=7)
        if first > last:
            raise ValueError('The start date must be on or before the end date.')
        if first < earliest.astimezone().date() or last > now.astimezone().date():
            raise ValueError('NWS only provides a rolling seven-day archive. Choose recent dates through today.')
        state = self.state.strip().upper()
        if state != 'US' and state not in STATE_CODES:
            raise ValueError('Choose All US or a US state/territory to download.')
        if self.events and any(not is_supported_event(event) or
                               not all(c.isascii() and (c.isalnum() or c == ' ') for c in event)
                               for event in self.events.split(',')):
            raise ValueError('Choose valid supported NWS weather-event names.')
        start = max(datetime.combine(first,time.min).astimezone(timezone.utc),earliest)
        end = min(datetime.combine(last+timedelta(days=1),time.min).astimezone(timezone.utc),now)
        params = dict(start=start.isoformat(),end=end.isoformat(),status='actual',limit=500)
        if state != 'US':
            params['area'] = state
        if self.events:
            params['event'] = self.events
        return params


def download_recent(query, store, parse_alert, cancel=None, progress=None, session=None, now=None):
    """Download completely before one atomic, history-only import.

    Use a dedicated HTTP session rather than the live monitor's session. Never
    mutate active alerts, versions, processed IDs or notification receipts.
    """
    cancel = cancel if cancel is not None else threading.Event()
    params = query.parameters(now)
    deadline = clock.monotonic()+120
    url = 'https://api.weather.gov/alerts'
    visited, alerts = set(), []
    received = skipped = 0
    owned_session = session is None
    session = session if session is not None else requests.Session()
    try:
        while url:
            if cancel.is_set():
                raise DownloadCancelled('Download cancelled. No archive records were imported.')
            if clock.monotonic() > deadline:
                raise ValueError('Download exceeded two minutes. Choose a shorter date range or an event type.')
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.netloc != 'api.weather.gov' or parsed.path != '/alerts' or url in visited:
                raise ValueError('Invalid NWS archive pagination link; no records were imported.')
            if len(visited) >= 10:
                raise ValueError('More than 5,000 alerts matched. Narrow the dates or event type; no records were imported.')
            visited.add(url)
            with session.get(url,params=params,timeout=(5,20),allow_redirects=False,headers={
                'User-Agent':'Stormwatch/1.0 (github.com/spectremancer/Stormwatch)',
                'Accept':'application/geo+json',
            }) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('NWS archive redirected the request; no records were imported.')
                data = response.json()
            if not isinstance(data,dict) or not isinstance(data.get('features'),list):
                raise ValueError('Invalid NWS archive response; no records were imported.')
            received += len(data['features'])
            if received > 5000:
                raise ValueError('More than 5,000 alerts matched. Narrow the dates or event type.')
            for feature in data['features']:
                if not isinstance(feature,dict) or not isinstance(feature.get('properties'),dict):
                    raise ValueError('Invalid NWS archive alert; no records were imported.')
                if feature['properties'].get('status') != 'Actual':
                    skipped += 1
                    continue
                if not query.events and not is_weather_event(feature['properties'].get('event')):
                    skipped += 1
                    continue
                alert = parse_alert(feature)
                if alert is None:
                    skipped += 1
                else:
                    alerts.append(alert)
            pagination = data.get('pagination') or {}
            if not isinstance(pagination,dict):
                raise ValueError('Invalid NWS archive pagination.')
            url = pagination.get('next')
            if url is not None and not isinstance(url,str):
                raise ValueError('Invalid NWS archive pagination.')
            params = None
            if progress:
                progress(received)
        imported = store.import_archive(alerts,query.state.strip().upper(),cancel)
        return dict(received=received,imported=imported,duplicates=len(alerts)-imported,skipped=skipped)
    finally:
        if owned_session:
            session.close()
