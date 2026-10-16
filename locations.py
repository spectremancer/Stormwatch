"""Saved monitoring profiles and geographic matching, independent of the GUI."""
from dataclasses import asdict, dataclass, field
import json
import math
import re
import uuid

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
    events: list = field(default_factory=lambda: [
        "Tornado Warning", "Tornado Watch", "Hurricane Warning", "Hurricane Watch",
        "Severe Thunderstorm Warning", "Severe Thunderstorm Watch"])
    enabled: bool = True
    sound: bool = True
    desktop: bool = True

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
        return self

    def matches(self, alert):
        if not self.enabled or alert["event"] not in self.events:
            return False
        codes = set(alert.get("geocode", {}).get("UGC", []))
        codes.update(url.rstrip("/").rsplit("/", 1)[-1] for url in alert.get("zones", []))
        if self.states and not any(code[:2] in self.states for code in codes):
            return False
        if self.counties and not codes.intersection(self.counties):
            return False
        if self.latitude is not None:
            if rings(alert.get("geometry")) and alert.get("geometry_source") != "NWS affected zones":
                return contains(alert["geometry"], self.latitude, self.longitude)
            return bool(codes.intersection(self.zones))
        return True

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
