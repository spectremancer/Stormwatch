"""Offline city/ZIP lookup using an attributed GeoNames postal-code catalog."""
import csv
from dataclasses import dataclass
from functools import lru_cache
import gzip
from pathlib import Path
import re
import unicodedata

from locations import LocationProfile

STATE_NAMES = dict(zip(
    ('alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|district of columbia|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming').split('|'),
    'AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split()))


def normalized(value):
    value = ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c)).casefold()
    return ' '.join(re.sub(r'[^a-z0-9 ]', ' ', value).split())


@dataclass(frozen=True)
class Place:
    zip: str
    city: str
    state: str
    latitude: float
    longitude: float

    @property
    def label(self):
        return f'{self.city}, {self.state} {self.zip}'

    def profile(self, name=None):
        return LocationProfile(name=name or self.label, latitude=self.latitude, longitude=self.longitude).validate()


@lru_cache(maxsize=1)
def catalog():
    with gzip.open(Path(__file__).with_name('data') / 'us_places.tsv.gz', 'rt', encoding='utf-8') as source:
        return tuple(Place(r['zip'], r['city'], r['state'], float(r['latitude']), float(r['longitude']))
                     for r in csv.DictReader(source, delimiter='\t'))


def search_places(query, limit=40):
    query = query.strip()
    if len(query) < 2:
        raise ValueError('Enter a city name or a five-digit ZIP code.')
    if re.fullmatch(r'\d{5}(?:-\d{4})?', query):
        return [p for p in catalog() if p.zip == query[:5]][:limit]
    terms = normalized(query)
    state = None
    for name in sorted(STATE_NAMES, key=len, reverse=True):
        if terms.endswith(' ' + name):
            state = STATE_NAMES[name]
            terms = terms[:-len(name)].strip()
            break
    if state is None and len(terms.split()) > 1 and len(terms.split()[-1]) == 2:
        state = terms.split()[-1].upper()
        terms = ' '.join(terms.split()[:-1])
    results = []
    for place in catalog():
        city = normalized(place.city)
        if (not state or place.state == state) and all(token in city for token in terms.split()):
            rank = 0 if city == terms else 1 if city.startswith(terms) else 2
            results.append((rank, place))
    results.sort(key=lambda item: (item[0], item[1].city, item[1].state, item[1].zip))
    return [place for _, place in results[:limit]]


def nearby_places(latitude, longitude, limit=30):
    """Nearby postal place labels for context on the offline confirmation map."""
    candidates = [p for p in catalog() if abs(p.latitude - latitude) < 3 and abs(p.longitude - longitude) < 4]
    candidates.sort(key=lambda p: (p.latitude-latitude)**2 + ((p.longitude-longitude)*.75)**2)
    seen, result = set(), []
    for place in candidates:
        key = (place.city, place.state)
        if key not in seen:
            seen.add(key)
            result.append(place)
            if len(result) == limit:
                break
    return result
