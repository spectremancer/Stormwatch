"""Saved monitoring profiles and geographic matching, independent of the GUI."""
from dataclasses import asdict, dataclass, field
import json
import math
import re
import uuid
from event_catalog import CATEGORY_LABELS, DEFAULT_EVENTS, event_category, is_supported_event

STATE_CODES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY AS GU MP PR VI".split())


def rings(geometry):
    if not geometry:
        return []
    if geometry.get("type") == "Polygon":
        return [geometry.get("coordinates", [])]
    if geometry.get("type") == "MultiPolygon":
        return geometry.get("coordinates", [])
    return []


def in_ring(lon, lat, ring):
    inside = False
    for i, start in enumerate(ring):
        end = ring[i - 1]
        x1, y1, x2, y2 = *start[:2], *end[:2]
        cross = (lon - x1) * (y2 - y1) - (lat - y1) * (x2 - x1)
        if abs(cross) < 1e-9 and min(x1, x2) <= lon <= max(x1, x2) and min(y1, y2) <= lat <= max(y1, y2):
            return True
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def contains(geometry, lat, lon):
    return any(poly and in_ring(lon, lat, poly[0]) and
               not any(in_ring(lon, lat, hole) for hole in poly[1:]) for poly in rings(geometry))


@dataclass
class LocationProfile:
    name: str = "United States"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    states: list = field(default_factory=list)
    counties: list = field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    zones: list = field(default_factory=list)
    events: list = field(default_factory=lambda: list(DEFAULT_EVENTS))
    enabled: bool = True
    sound: bool = True
    desktop: bool = True
    warning_sound: bool | None = None
    warning_desktop: bool | None = None
    watch_sound: bool | None = None
    watch_desktop: bool | None = None
    advisory_sound: bool | None = None
    advisory_desktop: bool | None = None
    statement_sound: bool | None = None
    statement_desktop: bool | None = None
    outlook_sound: bool | None = None
    outlook_desktop: bool | None = None
    other_sound: bool | None = None
    other_desktop: bool | None = None
    # None follows all monitored events; [] silences automatic event sounds.
    sound_events: list[str] | None = None
    speech: bool = False
    speech_max_areas: int = 16
    speech_max_chars: int = 480
    speech_events: list[str] | None = field(default_factory=lambda: [
        'Tornado Warning','Tornado Watch','Hurricane Warning','Hurricane Watch'])

    def validate(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Give this location a name.")
        self.states = sorted({s.strip().upper() for s in self.states if s.strip()})
        self.counties = sorted({s.strip().upper() for s in self.counties if s.strip()})
        if any(s not in STATE_CODES for s in self.states):
            raise ValueError("States must be two-letter US state/territory codes, such as IL, TX.")
        if any(not re.fullmatch(r"[A-Z]{2}C\d{3}", code) or code[:2] not in STATE_CODES for code in self.counties):
            raise ValueError("Counties must be NWS UGC codes, such as ILC031 (Cook County, IL).")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Enter both latitude and longitude, or leave both blank.")
        if self.latitude is not None and (not math.isfinite(self.latitude) or not math.isfinite(self.longitude) or
                                          not -90 <= self.latitude <= 90 or not -180 <= self.longitude <= 180):
            raise ValueError("Latitude must be -90…90 and longitude -180…180.")
        for kind in CATEGORY_LABELS:
            for channel in ("sound", "desktop"):
                value = getattr(self, f"{kind}_{channel}")
                if value is not None and not isinstance(value, bool):
                    raise ValueError("Event-category notification rules must be on or off.")
        if type(self.speech_max_areas) is not int or not 1<=self.speech_max_areas<=16:
            raise ValueError('Speech area limit must be between 1 and 16.')
        if type(self.speech_max_chars) is not int or not 80<=self.speech_max_chars<=480:
            raise ValueError('Speech text limit must be between 80 and 480 characters.')
        if not isinstance(self.speech,bool):
            raise ValueError('Read alerts aloud must be on or off.')
        for channel in ('sound','speech'):
            events = getattr(self,channel+'_events')
            if events is not None:
                if not isinstance(events,list) or any(not is_supported_event(event) for event in events):
                    raise ValueError(f'{channel.title()} events must be a list of supported NWS event names.')
                setattr(self,channel+'_events',sorted(set(events)))
        return self

    def allows(self, alert, channel):
        event = alert.get("event", "") if isinstance(alert, dict) else alert
        kind = event_category(event)
        if channel not in ("sound", "desktop", "speech") or kind is None or not getattr(self, channel):
            return False
        if channel in ('sound','speech'):
            events = getattr(self,channel+'_events')
            if events is not None and event not in events:
                return False
        if channel == 'speech':
            return True
        override = getattr(self, f"{kind}_{channel}")
        return override if override is not None else True

    def rules_summary(self):
        result = []
        for kind,label in CATEGORY_LABELS.items():
            events = [event for event in self.events if event_category(event)==kind]
            if not events:
                continue
            channels = [c.title() for c in ("sound", "desktop")
                        if any(self.allows(event,c) for event in events)]
            result.append(f"{label}: {' + '.join(channels) or 'Off'}")
        if self.sound_events is not None:
            result.append(f'Sound filter: {len(self.sound_events)} event types' if self.sound_events else 'Sound filter: no events')
        if self.speech:
            result.append('Speech: '+('all monitored events' if self.speech_events is None else f'{len(self.speech_events)} event types'))
        return "\n".join(result)

    def explain_match(self, alert):
        if not self.enabled or alert["event"] not in self.events:
            return False, 'Location monitoring is disabled.' if not self.enabled else f"{alert['event']} is not selected for monitoring."
        reasons = []
        codes = set(alert.get("geocode", {}).get("UGC", []))
        codes.update(url.rstrip("/").rsplit("/", 1)[-1] for url in alert.get("zones", []))
        if self.states and not any(code[:2] in self.states for code in codes):
            return False, 'The alert does not match the selected states: '+', '.join(self.states)+'.'
        if self.states:
            reasons.append('state '+', '.join(sorted({code[:2] for code in codes if code[:2] in self.states})))
        if self.counties and not codes.intersection(self.counties):
            return False, 'The alert does not match the selected county codes.'
        if self.counties:
            reasons.append('county '+', '.join(sorted(codes.intersection(self.counties))))
        if self.latitude is not None:
            if rings(alert.get("geometry")) and alert.get("geometry_source") != "NWS affected zones":
                if not contains(alert["geometry"], self.latitude, self.longitude):
                    return False, 'The saved pin is outside the NWS storm polygon.'
                reasons.append('saved pin inside the NWS storm polygon')
            else:
                if not codes.intersection(self.zones):
                    return False, 'The alert does not match the pin’s resolved NWS zones; no precise storm polygon is available.'
                reasons.append('resolved NWS zone '+', '.join(sorted(codes.intersection(self.zones)))+' (no precise storm polygon)')
        return True, 'Matched '+('; '.join(reasons) if reasons else 'nationwide monitoring')+'.'

    def matches(self, alert):
        return self.explain_match(alert)[0]

    def summary(self):
        parts = self.states + self.counties
        if self.latitude is not None:
            parts.append(f"{self.latitude:.3f}, {self.longitude:.3f}")
        return " · ".join(parts) or "All US alerts"

    def to_json(self):
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, value):
        return cls(**json.loads(value)).validate()
