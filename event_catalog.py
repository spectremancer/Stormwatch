"""Shared NWS weather/environmental event catalog (checked 2026-10-18).

Source: https://api.weather.gov/alerts/types. Selectors work offline.
Civil, administrative and test messages are not weather catalog entries.
Legacy/future Watch and Warning names remain supported for saved preferences.
"""

NON_WEATHER_EVENTS = frozenset('''911 Telephone Outage
Administrative Message
Blue Alert
Child Abduction Emergency
Civil Danger Warning
Civil Emergency Message
Evacuation Immediate
Hazardous Materials Warning
Law Enforcement Warning
Local Area Emergency
Nuclear Power Plant Warning
Radiological Hazard Warning
Shelter In Place Warning
Test'''.splitlines())

WEATHER_EVENTS = tuple(sorted('''Air Quality Alert
Air Stagnation Advisory
Ashfall Advisory
Ashfall Warning
Avalanche Advisory
Avalanche Warning
Avalanche Watch
Beach Hazards Statement
Blizzard Warning
Blowing Dust Advisory
Blowing Dust Warning
Brisk Wind Advisory
Coastal Flood Advisory
Coastal Flood Statement
Coastal Flood Warning
Coastal Flood Watch
Cold Weather Advisory
Dense Fog Advisory
Dense Smoke Advisory
Dust Advisory
Dust Storm Warning
Earthquake Warning
Extreme Heat Warning
Extreme Heat Watch
Extreme Cold Warning
Extreme Cold Watch
Extreme Fire Danger
Extreme Wind Warning
Fire Warning
Fire Weather Watch
Flash Flood Statement
Flash Flood Warning
Flash Flood Watch
Flood Advisory
Flood Statement
Flood Warning
Flood Watch
Freeze Warning
Freeze Watch
Freezing Fog Advisory
Freezing Spray Advisory
Frost Advisory
Gale Warning
Gale Watch
Hazardous Seas Warning
Hazardous Seas Watch
Hazardous Weather Outlook
Heat Advisory
Heavy Freezing Spray Warning
Heavy Freezing Spray Watch
High Surf Advisory
High Surf Warning
High Wind Warning
High Wind Watch
Hurricane Force Wind Warning
Hurricane Force Wind Watch
Hurricane Warning
Hurricane Watch
Hydrologic Outlook
Ice Storm Warning
Lake Effect Snow Warning
Lake Wind Advisory
Lakeshore Flood Advisory
Lakeshore Flood Statement
Lakeshore Flood Warning
Lakeshore Flood Watch
Low Water Advisory
Marine Weather Statement
Red Flag Warning
Rip Current Statement
Severe Thunderstorm Warning
Severe Thunderstorm Watch
Severe Weather Statement
Short Term Forecast
Small Craft Advisory
Snow Squall Warning
Special Marine Warning
Special Weather Statement
Storm Surge Warning
Storm Surge Watch
Storm Warning
Storm Watch
Tornado Warning
Tornado Watch
Tropical Cyclone Local Statement
Tropical Storm Warning
Tropical Storm Watch
Tsunami Advisory
Tsunami Warning
Tsunami Watch
Typhoon Warning
Typhoon Watch
Volcano Warning
Wind Advisory
Winter Storm Warning
Winter Storm Watch
Winter Weather Advisory'''.splitlines()))

CATEGORY_LABELS = {
    'warning':'Warnings', 'watch':'Watches', 'advisory':'Advisories',
    'statement':'Statements', 'outlook':'Outlooks / forecasts', 'other':'Other weather alerts',
}
EVENT_COLORS = dict(warning='#ffbc87',watch='#85caff',advisory='#f6d365',
                   statement='#8ee2cf',outlook='#c4b5fd',other='#f0a6d6')
DEFAULT_EVENTS = ('Tornado Warning','Tornado Watch','Hurricane Warning','Hurricane Watch',
                  'Severe Thunderstorm Warning','Severe Thunderstorm Watch')
CRITICAL_EVENTS = frozenset(DEFAULT_EVENTS[:4])


def event_category(event):
    if not isinstance(event,str):
        return None
    for suffix,category in ((' Warning','warning'),(' Watch','watch'),(' Advisory','advisory'),
                            (' Statement','statement'),(' Outlook','outlook'),(' Forecast','outlook')):
        if event.endswith(suffix):
            return category
    return 'other' if event in ('Air Quality Alert','Extreme Fire Danger') else None


def is_supported_event(event):
    return event_category(event) is not None


def is_weather_event(event):
    return is_supported_event(event) and event not in NON_WEATHER_EVENTS


def event_color(event):
    return EVENT_COLORS.get(event_category(event),'#9aaec7')
