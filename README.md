# Stormwatch

A TkFlow desktop weather dashboard for saved locations, live National Weather
Service weather and environmental alerts, and independent sound, desktop, and optional spoken notifications.

## Install and run

Use Python 3.12 or 3.13 with Tk support:

```sh
python -m pip install -r requirements.txt
python main.py
```

Run `python main.py --monitor` to immediately monitor the saved locations.

Before choosing **Start monitoring**, use **NWS refresh** in the sidebar to select
**30, 60, 90, or 120 seconds**. The default is 60 seconds, and your choice is saved
across restarts, including `--monitor` and launch-at-login startup. The selector
is locked while monitoring; pause to choose a different interval, then start
again. The first check runs immediately; subsequent checks wait the selected
interval after the previous check finishes. Failed requests use the same retry
interval. The countdown and stale-data checks follow the chosen interval.
Radar retains its separate five-minute refresh schedule.

`--test-tornado` and `--test-hurricane` play `alert.mp3` without opening the GUI.
The interface needs a desktop display; audible alerts need an audio device.
On Debian/Ubuntu Linux, install the desktop dependencies first:

```sh
sudo apt-get install python3-tk python3-venv libnotify-bin espeak-ng python3-gi gir1.2-ayatanaappindicator3-0.1
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

Use the distribution's Python (3.12/3.13) with `--system-site-packages` so the
optional tray backend can import the system PyGObject (`gi`) bindings. A virtual
environment using a different Python minor version may not be able to load those
bindings. Core monitoring, maps, history, and MP3 playback do not require GTK.
Linux needs a graphical desktop; a Wayland session also needs XWayland for Tk.
Desktop notifications require `notify-send` and a working session D-Bus
notification service. A failed submission is recorded as failed for retry.
Speech requires `espeak-ng` or `espeak`. Tray menus require GTK/AppIndicator and a
tray host; GNOME may require the AppIndicator extension. The basic Xorg pystray
backend lacks menus, so Stormwatch keeps its window open instead of hiding it
when that unsupported backend is selected. Linux launch-at-login is not provided;
the Windows-specific control remains disabled on Linux.

Windows uses Tk/Pillow icons, native notifications via plyer, and Windows
PowerShell/.NET System.Speech for optional voice announcements. MP3 playback uses
pygame on both platforms. Both need a working default audio output for audible
alerts; successful software submission does not prove you heard the alert.

The project-root `icon.ico` supplies the title-bar, Windows taskbar, child-window,
and tray icons. Windows uses a Stormwatch-specific taskbar application identity.
Asset paths are resolved relative to the application, including frozen builds.
To build the Windows executable **on Windows**:

```sh
python -m pip install pyinstaller
python -m PyInstaller --clean main.spec
```

The spec embeds `icon.ico` and bundles the icon, sound, and data directory. The
checked-in `dist/main.exe` is an older build; source changes require rebuilding
it with the command above. This release's Windows executable was not built on
the Linux development machine.

## Cross-platform verification

`.github/workflows/desktop-compatibility.yml` runs the GUI/application tests on
Windows and Linux with Python 3.12 and 3.13. Linux uses Xvfb; Windows GUI tests run
natively without requiring the Linux `DISPLAY` variable. Each job also runs
`scripts/desktop_smoke.py` against the real application with isolated temporary
state and dummy audio. The Windows 3.13 job builds an EXE and uploads it as an
artifact; this does not replace the checked-in executable automatically.

To repeat the native smoke test locally:

```sh
python -B scripts/desktop_smoke.py
```

On headless Linux, use `xvfb-run -a python -B scripts/desktop_smoke.py`. This checks
startup, assets, map/settings rendering, writable storage, real MP3 decoding, and
clean shutdown. It does not make weather requests or send real notifications.
Physical sound, actual notification display, and tray-host integration still
require an interactive desktop check. Linux cloud validation cannot establish
native Windows behavior; inspect the Windows CI results and test your packaged
build on its target Windows desktop before distributing it.

Logs and legacy service state now live beside the database in the writable
per-user state directory, rather than beside installed assets. Windows uses
`%LOCALAPPDATA%/Stormwatch`; Linux uses `$XDG_STATE_HOME/Stormwatch` or
`~/.local/state/Stormwatch`. Existing project-root service state is read as a
migration fallback; future writes use the user directory. **Tools → Open Log
Folder** opens the actual logger destination.

## Saved locations

Use **Add** for a three-step guided setup:

1. Search the offline city/ZIP catalog (examples: `Chicago, IL`, `Springfield Illinois`,
   or `60601`). Choose one of the labeled city/state/ZIP results.
2. Confirm the approximate pin on the offline map. Nearby place labels provide
   geographic context. Click to adjust the pin, drag to pan, and scroll to zoom.
3. Name the location Home, Family, Work, or something else; choose event types and
   sound/desktop preferences. Saving resolves the pin's official NWS zones.

Searches stay on your device and require no API key. The bundled catalog contains
40,970 postal-place entries, not street addresses or a complete/current postal
registry. ZIP/city pins represent areas, **not an exact home address**. Missing
places can be entered through **Advanced location editor…**, which also supports
state-wide and county-wide profiles. A failed NWS lookup saves no partial profile.
Data attribution and coverage details are in [data/README.md](data/README.md).

Each profile saves its own event selections, enabled state, sound preference,
and desktop notification preference. All enabled profiles monitor together;
selecting a profile in the sidebar changes which profile you are editing.
**Edit** opens the advanced editor for existing locations:

- **States:** enter two-letter codes, such as `IL, IN`.
- **Counties:** enter state codes first and use **Choose counties** to select
  counties by name. You can also enter exact NWS county UGC codes, such as
  `ILC031` for Cook County, Illinois.
- **Coordinates:** enter latitude and longitude to save a point. Saving resolves
  the point's official NWS county and forecast/fire-weather zones.
- Empty geography means all US alerts. If multiple filters are specified, all
  must match. Coordinates use an alert's storm polygon when one exists;
  otherwise they fall back to the resolved NWS zones. Zone-based matching can
  cover a wider area than the point itself. Unresolvable points are not saved.

**Event types** applies to the selected location. **Select all** and **Clear**
change that location's event list. Additional event types discovered in active
NWS data appear unchecked. Preferences persist and apply on the next refresh.
An alert matching multiple locations is combined into one sound submission and
one desktop submission per alert version. The desktop notification lists the
locations whose rules allow that channel; cards, the feed, and history list all
matching enabled locations. Location receipts remain separate for troubleshooting.
Adding another overlapping location later does not replay a channel already
submitted for that version. A new meaningful alert version can notify again.

## Supported weather events and notification categories

The sidebar, location wizard, sound/speech selectors, History event filter, and
history-download selector share a catalog of **97 NWS weather/environmental
types**, checked against the [NWS event catalog](https://api.weather.gov/alerts/types)
on October 18, 2026. Types are
available before an active alert of that type is encountered. Coverage includes
all 38 previously excluded weather-related advisories, statements, outlooks,
forecasts, Air Quality Alert, and Extreme Fire Danger. It also includes previously
unlisted marine, storm-surge, lake-effect snow, ashfall, avalanche, typhoon, fire,
and related natural-hazard warnings and watches.

Examples include Winter Weather Advisory, Heat Advisory, Cold Weather Advisory,
Flood Advisory, Dense Fog Advisory, Small Craft Advisory, Special Weather
Statement, Rip Current Statement, Hazardous Weather Outlook, Hydrologic Outlook,
Short Term Forecast, and Air Quality Alert. New entries are available for selection
but are **not automatically enabled**. Existing profiles keep their selections;
new profiles still start with the six tornado, hurricane, and severe-thunderstorm
watch/warning types. The Tornado + hurricane preset remains exactly four types.

The weather catalog excludes civil, administrative, telephone-outage, abduction,
and test messages. Previously supported saved Watch/Warning names, including
legacy NWS names, remain compatible. Newly encountered supported weather names
appear unchecked. Availability of a catalog entry does not guarantee that NWS
currently has a message of that type in the selected area or download period.

The location wizard and **Edit** include **Event-category rules**, with separate
sound and desktop switches for six categories:

- Warnings.
- Watches.
- Advisories.
- Statements.
- Outlooks / forecasts.
- Other weather alerts (Air Quality Alert and Extreme Fire Danger).

Each category's rules inherit the location's master switches unless overridden.
For example, enable desktop notifications for advisories while silencing their
sound, without changing warning or watch behavior. The sidebar summarizes the
selected categories. Speech retains its own master switch, per-event selection,
and monitoring-session issue-time cutoff, independently of sound/desktop rules.
Older profiles acquire the new category settings without losing existing rules.

Categories use the NWS event name, not the separate NWS severity field. Event-type
selections still determine what is monitored;
turning off notification channels does not hide matching cards or history.
Sound/desktop master switches override the category rules. Existing profiles
retain their previous behavior until edited. Rules apply on the next refresh;
turning a channel off also prevents its queued or failed submissions from retrying.
Cancellations and expired versions remain silent regardless of warning rules.

### Choose which events play alert.mp3

Select a location in the sidebar, then choose **Sound events**. To play sound
only for tornado and hurricane events, choose **Tornado + hurricane**, then
**Save sound events**. This selects Tornado Warning, Tornado Watch, Hurricane
Warning, and Hurricane Watch. You can instead uncheck **Allow sound for all
monitored event types** and choose individual event names, such as Tornado Warning
without Tornado Watch. **No event sounds** silences automatic sounds for that
location. **All event types** follows all monitored types, including future
selections.

The location's Sound switch and event-category sound rules must also allow an
event. The event must match an enabled location and be selected for monitoring.
Sound filtering does not remove alerts from the feed, cards, history, or desktop
notifications. With overlapping locations, an event may still play once if any
matching location allows it; each location has its own sound choices. Preferences
persist across restarts and apply on the next refresh. Pending and manual retries
also check the current sound filter. Existing profiles keep their previous sound
behavior until a filter is saved.

**Test sound** is an explicit manual preview and still plays on request,
even when all automatic event sounds are disabled. Previewing Demo sounds is
also separate from live location preferences.

## Notification explanations

Open an alert's details and choose **Why did I get this?**. This explains the
event selection and geographic match for each saved location: state, county,
storm polygon, resolved NWS zone, or nationwide monitoring. It also explains
silence caused by disabled monitoring, an unselected event, a channel switch,
event/category filters, quiet startup, legacy history, cancellation, expiration,
or an alert that is no longer current. Explanations and operational messages
stay outside the alert-only chat feed.

Decisions for sound, desktop, and speech are saved separately when a matching
alert version is processed. A submitted or quiet-baseline decision stays fixed;
unsent decisions can update when preferences change. The explanation window
distinguishes recorded decisions from **current preferences**, so changing a
location afterward does not rewrite why a previous notification was submitted.
Delivery details include the recorded reason, shared-location result, and errors.
Older and simulated records without decisions say so rather than inventing a
historical explanation. These records use an additive SQLite table; existing
alerts, history, and receipts remain intact.

## Spoken alerts

Choose a location and open **Spoken alerts**. Enable **Read alerts aloud**, choose
individual event types or the **Tornado + hurricane** preset, then save. Speech
is **off by default**, including for existing profiles. Its event filter is
independent of `alert.mp3` and desktop/category preferences; the location must
still be enabled and the event selected for monitoring. **All event types** also
allows future monitored types; **No spoken events** leaves automatic speech
silent. **Test voice** is an explicit preview, even with automatic speech off.

After a complete NWS refresh has been processed, eligible speech is grouped by
event type. Twelve new Gale Warnings produce one Gale Warning report rather than
twelve separate announcements. The report uses deduplicated NWS affected-area
names, with punctuation pauses between locations, followed by the latest known
expiration among that batch's still-active alerts in the computer's local time.
For example: “Gale Warning for North coastal waters; South coastal waters;
Outer waters. Until October 19 at 7 PM local time.” Broad profile names such as
US or United States are not substituted for available NWS area descriptions.

Reports list up to 16 areas within a 480-character location budget and summarize
additional areas by count so nationwide reports remain brief. Full coverage is
available in alert details and the map. Missing expiration information is stated
explicitly. Reports do not rewrite safety instructions or infer storm movement.

Speech uses local operating-system voices, with no cloud speech service or API key:

| Platform | Local engine |
| --- | --- |
| Windows | Windows PowerShell and .NET `System.Speech`, using the default installed voice/audio output |
| macOS | `/usr/bin/say` |
| Linux | `espeak-ng` or `espeak`, installed separately |

An unavailable engine reports a clear failure in Delivery or the test feedback.
Native Windows speech execution has not been verified on the Linux development
machine; Windows command construction, Unicode stdin, failures, cancellation,
timeouts, and receipt behavior are tested with controlled subprocesses.

Speech has its own worker and receipts, so a slow/failed voice does not block
polling, sound, or desktop submission. Overlapping locations share one spoken
submission per alert version. Failed speech retries on refresh up to three
shared attempts; Delivery can retry that failed channel once without replaying
successful sound or desktop channels. Successful speech is not repeated for an
unchanged version. Legacy history remains a quiet baseline.

Automatic speech covers **only alert messages issued after the current monitoring
session starts**. Each Start or resume establishes a new cutoff using the NWS
issue timestamp. Alerts already in effect, late-arriving older messages, and
alerts with missing/invalid/timezone-less issue times stay silent, including
tornado and hurricane alerts. They still appear in the feed, cards, and History;
sound and desktop preferences keep their existing behavior. New messages issued
after Start can speak even on the first successful refresh. New issued versions
can qualify; an older issue time does not qualify merely because content changed.
Old pending/failed speech jobs are suppressed on resume rather than replayed,
and speech retries must satisfy the current session cutoff. **Test voice** and
explicit simulation previews remain available.

The speech queue holds at most 32 event-type batches, with up to 1,000 unique
alert versions in each, prioritizing warnings, severity, and tornado/hurricane
events. Eligible overflow remains pending for a later refresh. Per-alert and
per-location receipts remain independent: one successful spoken batch marks its
eligible members submitted, failed members can retry together, and successful
members are not repeated with later additions. Before speaking, the worker checks
current preferences, fresh monitoring data, version, and expiration. Only active
messages are spoken; cancellations, expirations, superseded messages and messages
no longer active never enter the report. Invalid queued members are removed. If
an alert becomes invalid during a report, its owned voice process is stopped and
remaining active, unsent members can be regrouped; an interrupted report may
therefore repeat part of the still-valid coverage.
Pausing monitoring clears the queue and stops the owned voice process;
closing the application also stops it. Each native speech command has a 45-second
timeout. Completion does not prove someone heard the announcement.

## Active alerts, lifecycle, and map

**Active alerts** shows current matched alerts as cards with profile names,
affected area, severity, issue time, and an expiration countdown. Cards are
paginated at 20 per page to handle large national alert lists. Opening details
shows the full NWS description and instructions and an official HTTPS link.
Cards sort warnings before watches, then other categories; within each group,
official severity sorts highest first, followed by expiration longest to shortest.
Unknown expiration times sort last within the same category/severity group.
Stored active alerts remain visible after a restart, with a **NO LIVE DATA**
notice until a fresh request succeeds.

**Alert feed** contains alert changes only. It distinguishes new alerts,
updates, extensions, explicit cancellations, expirations, and alerts no longer
listed as active. Clearing this feed clears the view, not the delivery history
or current cards. Operational messages stay in the status bar.

NWS updates may use the same ID or a new ID referencing an earlier alert. Both
are tracked; referenced alerts are superseded. Cancellations come from a
separate NWS cancellation query (initially the preceding 15 minutes, then since
the last successful cancellation request). A failed cancellation request is
reported as incomplete coverage and retried. If an alert disappears without an
explicit cancellation, it is labeled **No longer active**, not cancelled.
Expiration is also checked locally every second. Cancellations older than the
startup lookback may only be identified as no longer active.
Active cards, map polygons, location counts, and the current snapshot remove
cancelled, superseded, disappeared and expired alerts. Effective expiration is
the earlier valid NWS `expires` or `ends` timestamp, so a message is not kept past
its validity merely because its hazard end is later. Existing expiry indexes are
updated once on upgrade. Identical or previously recorded cancelled/superseded
versions cannot be resurrected by a stale active response. Expiration cleanup
continues while paused or offline and does not wait for another API refresh.
Stored history and notification receipts are retained.

**Alert map** supports drag-to-pan, wheel/button zoom, fit-to-content, saved-point
markers, and clicking an alert outline for details. Public-domain Natural Earth
outlines are bundled for offline geographic context. NWS storm polygons are
used where available; otherwise official affected-zone boundaries are retrieved
and cached, with at most six new lookups per refresh. Zone outlines are broader
coverage boundaries, not precise storm paths. Incomplete/missing geometry is
counted on the map; those alerts remain in the cards. The map requires no map
API key. Its geographic context works offline. Dataset attribution is in
[data/README.md](data/README.md).

### Personal threat overview

The **Locations** tab shows all saved locations, with 20 cards per page. Each
card shows its geographic filter, selected alert count, monitoring status, and
highest-priority matching alert with an expiration countdown and details button.
Warnings rank first, followed by official severity; tornado/hurricane events,
event category, and earlier expirations break ties. Each category has a distinct
feed/card/map color; advisories and statements are not labeled as watches.
Disabled locations are clearly labeled.
**NO LIVE DATA** and **STALE** remain visible until monitoring has a recent
successful refresh. “No selected active alerts” applies only to the location's
selected event types and does not establish an all-clear for other hazards.

### What changed?

New alert versions receive factual change summaries in the feed, active cards,
details, history, and the CSV `change_summary` column. Summaries identify extension
or shortening minutes, severity/event changes, added or removed NWS county/zone
codes, and changes to official instructions, headlines, descriptions, or native
boundaries. They compare the previous version or an explicitly referenced prior
alert; they do not infer storm movement or write new safety advice.

If an update removes a formerly matching location, that update still appears in
the feed with the location marked **previously affected**, including replacement
alert IDs. Current cards reflect the changed coverage. Explicit cancellations,
elapsed expirations, and unconfirmed disappearance remain distinct. Summaries
are saved per version and historical change; older records without a summary
remain readable and are not assigned an invented comparison.

### Radar playback

In **Alert map**, enable **Show recent radar**. This opt-in overlay uses
[RainViewer](https://www.rainviewer.com) observed precipitation imagery under
the NWS alert boundaries and saved-location markers. Use **Play/Pause**,
**Previous frame**, **Next frame**, and **Refresh radar**. The latest six available
past frames are loaded; no forecast radar frames are used. Each displayed
frame shows its **generation time** in UTC, age, and sequence number. RainViewer
explains that a composite frame contains readings from different observation
times; its timestamp is not the observation time of every radar reading. The
overlay uses the **Universal Blue** palette with smoothing and separate snow
colors enabled. Radar colors represent reflectivity, not warning severity.
Radar coverage can be incomplete; a blank area does not prove safety.
**Connection details** sits alongside the map's zoom and Fit buttons. The separate
palette legend row and RainViewer button have been removed, giving that space
to the map canvas. Palette settings remain available in Connection details.

Radar refreshes every five minutes while enabled and the map is visible. A
failed refresh retains the last successful imagery with its original timestamp
and marks it stale; imagery is also marked stale when the newest frame was generated
over 20 minutes old. Panning, zooming, or resizing hides the old overlay while
the new view loads, so imagery cannot remain attached to the wrong coordinates.
Playback pauses when leaving the map. Disabling radar clears the overlay and
frame images. Radar operational status never enters the alert-only chat feed.

Network requests and reprojection run outside the GUI thread. Loads use at most
six frames, 12 tiles per frame, four concurrent tile requests, and a 96-tile
in-memory cache. Resolution is capped at provider zoom 7; large viewports may use
lower resolution. Web Mercator tiles are reprojected onto the map's geographic
grid. There is no persistent radar archive or storm-arrival prediction. Alert
monitoring and the offline map continue if radar is unavailable.

Radar needs HTTPS access to `api.rainviewer.com` and `tilecache.rainviewer.com`.
No API key is required by this integration; availability and usage remain
subject to the provider's service and terms. RainViewer is credited in the frame
status and Connection details. The integration was checked against the official
[Weather Maps API documentation](https://www.rainviewer.com/api/weather-maps-api.html)
and [color scheme documentation](https://www.rainviewer.com/api/color-schemes.html).
It requests `https://api.rainviewer.com/public/weather-maps.json`, reads
`radar.past`, and builds tile URLs from the returned HTTPS `host` and each frame's
`path`:

```text
{host}{path}/256/{z}/{x}/{y}/2/1_1.png
```

Paths are opaque identifiers. For example, the live API returned
`/v2/radar/2e6b69161301`; the app preserves that value rather than deriving a path
from the timestamp or requiring a numeric identifier. The API supplies roughly
two hours of past frames at ten-minute intervals; Stormwatch displays the latest
six. Tile size 256, zoom at most 7, color 2 (Universal Blue), and options 1_1
(smoothing on, snow colors on) follow the documented parameters. The image host
is validated against the supported RainViewer HTTPS origin before requesting.

After the approved network settings took effect, live metadata and tile requests
returned HTTP 200. The actual radar loader successfully downloaded and reprojected
six nonempty frames using 24 tiles in a small test viewport. Regression fixtures
also cover opaque frame paths and the exact documented request format.

**Connection details** shows the last attempt and the full failure reason. The
status under the map also reports the reason instead of only “Radar unavailable”:

| Reported failure | Meaning and action |
| --- | --- |
| Proxy CONNECT HTTP 403 | The configured proxy blocked the host before contacting RainViewer. Allow both radar hosts in the network policy. In the managed cloud environment, review/save and publish the saved network additions. |
| Host returned HTTP 401/403 | The request reached an HTTP service that denied access. Check provider access rules or firewall filtering. |
| HTTP 429 | Provider rate limit; wait a few minutes before retrying. |
| TLS certificate validation failed | Check the system clock and trusted certificates. TLS verification stays enabled. |
| Timed out / could not connect | Check internet access, DNS, firewall, and system proxy settings. |
| No recent generated frames | Check the system clock or provider availability. |
| Map too large | Resize the map to at most 1800 × 1200 pixels, then retry. |

Supported HTTPS redirects between the two trusted RainViewer hosts are followed,
up to a bounded limit. Other redirect hosts, oversized responses, and invalid
images/metadata are rejected with explanations. Raw proxy credentials and server
response bodies are not included in connection diagnostics.

Earlier cloud checks returned proxy CONNECT 403 before RainViewer access was
activated. A separate application bug also rejected valid nonnumeric frame paths;
that parsing bug is now corrected. On Windows, use **Connection details** for
any remaining local connection failure. If running the checked-in executable, rebuild it
from current source using `main.spec` to get these controls and diagnostics.

## Versions and delivery receipts

The previous ID-only behavior has been replaced by per-version records:

- Meaningful content, expiration, geographic coverage, or native storm-polygon
  changes produce a new alert version. Repeated copies of the same version do
  not duplicate the feed. Map-only zone enrichment does not create a version.
- Current cards always reflect the latest successful snapshot, regardless of
  whether that version was previously displayed or notified.
- Feed display, sound submission, desktop submission, and speech are recorded separately.
  A desktop failure does not replay a sound that was already submitted
  successfully, and vice versa. Failed channels retry on subsequent successful
  refreshes, up to three shared attempts per alert version/channel, regardless
  of the number of overlapping locations. Disabling a
  location or channel stops further delivery for it.
- The first successful refresh quietly populates non-tornado/hurricane alerts.
  Unseen tornado/hurricane watches and warnings also notify on that first
  refresh. Subsequent selected new/updated versions use the profile's channels.
  Cancellations and expired versions do not play an alert sound.
- Notification success means the OS notification API or audio mixer accepted
  the submission, not proof the person saw or heard it. Windows settings and
  Do Not Disturb can suppress desktop notifications. Asynchronous OS failures
  cannot always be detected. A process interruption between submission and
  recording its receipt can still result in a retry.

The existing SQLite database is migrated in place. Its legacy ID-only records
are retained as quiet baselines because old delivery outcomes are unknown;
new versions can still notify. Data and profiles live under
`%LOCALAPPDATA%/Stormwatch/processed-alerts.sqlite3` on Windows, or
`$XDG_STATE_HOME/Stormwatch/processed-alerts.sqlite3` elsewhere (default:
`~/.local/state/Stormwatch/processed-alerts.sqlite3`). Close Stormwatch before
backup; copy the database and any remaining `-wal`/`-shm` companion files together
as one set. Do not discard those companions. The feed
is a current-session view; the **History** tab retains previous alert changes.

## Application menus

The menu bar groups commands under **File, Monitoring, Locations, Alerts, View,
Data, Tools, Settings, and Help**. Existing sidebar controls remain available.

- **File** exports the applied History filters to CSV or captures the visible
  map as PNG, minimizes to the tray, and exits. Keep the map visible and
  unobstructed during image export; this is a screen capture, including radar
  when enabled, rather than a GIS data export.
- **Monitoring** starts/pauses monitoring and refreshes immediately. Refresh Now
  requires monitoring and waits until any current request finishes. Interval
  choices share the sidebar setting and can be changed only while paused.
- **Locations** opens the overview, adds/edits/removes locations, and provides a
  checked list for selecting the location whose preferences are being edited.
- **Alerts** opens notification rules for the selected location, sound/speech
  preferences, manual notification tests, and the event selector. Clear Alert
  Feed clears only the session feed, not saved history.
- **View** navigates the main tabs, shows connection status, restores the default
  window/tab/map extent, and provides map zoom, fit, and radar controls.
- **Data** opens Metrics, recent NWS history downloads, CSV export, local NWS
  GeoJSON import, source information, and a read-only storage/retention summary.
  Imports accept NWS FeatureCollections up to 10 MiB and 5,000 features, retain
  supported weather alerts, deduplicate versions, and run atomically in a worker.
  Imported records are labeled **Local NWS GeoJSON** and never enter live views
  or trigger notifications. Invalid issue times abort the entire import.
- **Tools** opens simulations, delivery results, diagnostics, and the log folder.
- **Settings → General…** contains close-to-tray and Windows launch-at-login
  preferences. These controls are omitted from the sidebar and separate menu
  entries so the weather event selector has more vertical space. Settings also offers saved
  control text sizes of 10, 12, or 14 points. Dedicated card/map styles retain
  their sizes. Time & Units explains existing local-time, UTC-radar, and
  original NWS-unit behavior; it does not change official alert wording.
- **Help** provides a getting-started guide, NWS safety information, shortcuts,
  the GitHub issue page, and application/source credits.

Shortcuts: **F5** refreshes NWS data while monitoring, **Ctrl+F** focuses history
search, **Ctrl+E** exports matching history, **F1** opens Getting Started, and
**Ctrl+Q** exits. **Alt+F4** uses the configured close-to-tray behavior. Opening
menus or informational dialogs does not start monitoring or connect radar.

## Data menu and metrics

**Data → Metrics** opens a summary of every saved historical event type and the
types in the current monitored alert snapshot. The table shows distinct
historical NWS alert IDs, recorded changes, downloaded changes, and active alerts
for each type. Updates and lifecycle changes can produce several records for
one alert ID; these are not counts of storms. Downloaded changes are a subset
of the historical changes.

Historical totals include the complete saved archive, including optional NWS
downloads, independently of History search filters or pagination. Active counts
match enabled locations and selected event types, exclude elapsed expirations,
and count each alert once across overlapping profiles. They use the last known
monitored snapshot rather than nationwide totals. The summary displays connection
health so cached data is recognizable when paused, offline, or not yet refreshed.

Use **Refresh**, or reopen the window, to update the snapshot. This reads local
data without making NWS requests or sending notifications. Archive aggregation
runs in the background using a consistent SQLite read snapshot, allowing live
monitoring to keep writing. No saved history is changed.

## Searchable history and CSV export

**History** provides a paginated archive of alert versions and lifecycle changes.
Search across event names, headlines, areas, descriptions, and instructions.
Filter by recorded location name, event type, change (new, updated,
extended, cancelled, expired, or no longer active), date range, and latest
channel result (submitted, failed, pending, suppressed, or no notifications).
Use **Search** to apply filters and **Clear filters** to reset them. Delivery
results reflect current receipts, not a log of every individual retry.
The editable event-type filter accepts case-insensitive partial names: typing
`tornado` matches both **Tornado Warning** and **Tornado Watch**. You can also
choose a full event name from the dropdown. Search and CSV export use the same
filters. History searches alerts recorded locally, including optional NWS downloads.

Use **Download Latest 7 Days** in History or Data to fetch the most recent
seven days with one click. Dates are calculated at download time; no date entry
is required. **Download Options…** in History (or **Data → History Download
Options…**) selects **All US** or one state/territory and event types. These
choices are remembered. Defaults use the selected profile's first state, or All
US if it has none, and all weather events. Downloads are opt-in and run separately
from live monitoring. **Cancel download** stops after the current request;
closing the dialog or quitting also requests cancellation.
Choose **All weather events**, a category such as **Advisories** or **Statements**,
or any individual catalog event. All weather events filters out civil and
administrative messages; previously saved explicit Watch/Warning selections stay
usable. The same parser and event categories are used for live and downloaded
weather records. Imported advisories, statements, forecasts, and alerts appear
in History, CSV export, and metrics with their original NWS event names.

The official NWS API provides a **rolling archive of roughly seven days**, not a
multi-year historical database. The automatic batch covers the preceding 168
hours, ending when the download begins. Archive availability at the oldest edge
may be incomplete. No matches means NWS returned none for that query, not proof
no event occurred. Multi-year searches require another archive source.

The worker queues seven adjacent 24-hour requests, follows each request's NWS
pagination (500 records per page), and combines their results. A window reaching
5,000 messages or ten pages with more pages pending is split into smaller time
windows and requeued; busy days do not impose a 5,000-record ceiling on the week.
Versions returned at multiple window boundaries are deduplicated. The batch
allows up to 15 minutes, 1,000 requests, and 100,000 unique versions; windows
cannot be split below one minute. Exceeding a safety budget reports a failure
rather than silently accepting an incomplete import.

All queued windows and pages must succeed before one atomic import. Failed or
cancelled downloads keep no partial history. Existing alert versions are skipped.
Imported rows show **NWS API archive**, use NWS issue time, and carry a
**NWS archive · STATE** location label distinct from saved monitoring profiles
(**NWS archive · US** for nationwide downloads). All US requests omit the NWS
area filter. Search filters reset after import so new records are visible. NWS
message types identify new, updated, or cancelled messages; extensions and
missing intermediate versions are not inferred.

Downloads populate History only. They never modify active cards, processed IDs,
live notification decisions or delivery receipts, and never trigger sound,
desktop notifications or speech. A later live observation can still notify
normally. Existing locally recorded versions retain their original provenance.

Dates are inclusive local-calendar dates entered as `YYYY-MM-DD`. New entries
use the time Stormwatch observed the change. Each version retains location names
as they were first associated with that version; renaming or removing a profile
does not erase those associations. Clearing the feed does not clear history.
Cancelling a referenced alert can produce both a cancellation-message record
and a lifecycle record for the original alert.

On upgrade, existing saved versions are imported once. Older storage did not
retain observation times, so imported rows use the NWS issue time when available,
explicitly labeled **imported**; unknown timestamps remain **Not recorded** and
are excluded by date filters. Old location names can only be recovered from
available receipts/current profiles. Earlier status-only transitions may not
have separate historical records; the latest alert status remains visible.
Legacy ID-only records have no alert text to import. No history is fabricated.

**Export matching CSV** saves every entry matching the applied filters, across
all pages. It exports a consistent read snapshot while monitoring continues.
Columns include alert ID, version, change, time/basis, event, locations, area,
severity, issue/expiration times, current status, channel results, headline,
instructions, official URL, change summary, and record source. Files use UTF-8 with a BOM for spreadsheet
compatibility. Text that could be interpreted as a spreadsheet formula is
escaped. Export cancellation writes nothing; failures preserve an existing
export. Export cannot overwrite the application database.

## Notification delivery panel

The **Delivery** tab lists sound, desktop, and enabled speech channel records separately, with
pagination and a **Failed only** filter. Select a row to inspect the location,
alert version, feed logging state, scheduled time, last-attempt time, attempt
count, shared-submission/location information, suppression reason, and the last reported error. Results distinguish
pending, submitted, suppressed, paused, no longer current, failed, and exhausted
retries. Older records without timestamps show **Not recorded**.

**Retry selected failed channel once** performs one explicit retry, including
when its three automatic attempts were exhausted. It retries the shared channel
once for eligible matching locations, preserves the shared attempt count, and
leaves successful channels alone. Live retries require monitoring to
be running, fresh data, a still-current alert version, and an enabled matching
location/channel. Old, expired, disabled, and already-successful channels cannot
be replayed from this panel. Manual attempts do not reset the automatic budget.
Older receipt budgets are migrated conservatively using the largest existing
channel attempt count; any prior successful submission suppresses duplicates.
Submission results still cannot prove that a person saw or heard a notification.

## Demo mode

The **Demo** tab is an isolated simulation that can run alongside live monitoring.
Choose a scenario and press **Run simulation** to preview a new warning, update,
extension, cancellation, expiration, connection failure, or recovery. Sample
cards, feed, map, and delivery results are labeled **SIMULATION**. Ending scenarios
require a new/active sample warning first. Simulating a connection failure keeps
sample cards visible and has no effect on the real connection.

Real sample sound and desktop previews are **off by default**. Enable their
checkboxes only when you want to use the actual audio device or OS notification
API. Desktop previews explicitly use a `SIMULATION` title. Turning on a checkbox
only affects subsequent scenarios/previews; it does not itself send anything.
Preview submission failures can be retried manually in **Sample delivery** with
the corresponding real-device preview enabled.

**Simulate delivery failure** fabricates a successful sound record and a failed
desktop record without using either device. Retrying that fabricated desktop
record marks it successful without touching a device or replaying sound. This
lets you explore error handling without real notifications. Demo channels do
not automatically retry on live refreshes.

Simulation data lives in a separate temporary database that is removed on clean
shutdown. It never writes to live profiles, active alerts, notification receipts,
or alert history. Demo data is not restored after restart.

## Background monitoring and connection health

**Minimize to tray** hides the window only after a tray icon becomes available.
Its menu provides **Open Stormwatch** and **Quit**. Enable **Close window to tray**
to keep monitoring when closing the window; otherwise closing quits the app.
This preference is saved. A missing or unsupported tray backend keeps the
window open with an explanatory message. Tray mode targets Windows and
menu-capable Linux backends; macOS background tray integration is not included.

**Launch at login (Windows)** explicitly adds/removes a per-user Windows Run
entry with `--monitor`; it does not request admin rights. Source installs use
Python/pythonw plus `main.py`; packaged installs invoke the installed EXE directly,
without referencing temporary extracted files. Keep the installation at the same
path. This
setting takes effect only when you choose it in the interface.

The health banner shows the last successful refresh, the next refresh countdown,
and **STALE** when paused, after a failure, or when data is at least two polling
intervals old (minimum two minutes). A failed active request preserves the last
known cards rather than interpreting missing data as cancellations. Cancellation
coverage warnings are displayed separately. NWS refresh interval: configurable
at 30, 60, 90, or 120 seconds (default 60).

Alert monitoring uses `api.weather.gov` for alert, cancellation,
county, point-resolution, and boundary requests. Optional radar uses the two
RainViewer domains listed above. This is an informational
monitor; follow official local weather guidance.

## Responsiveness and input readability

Editable text fields use black text and a black cursor on a white background,
including editable search dropdowns. Disabled fields use gray text.
Scrollable form content is a native child of its canvas, keeping the event list
clipped inside its viewport rather than painting over the Event types heading.

Incoming alerts are processed in batches of 20, yielding to the interface between
batches. Each batch shares a database transaction and a single feed update.
Unchanged alerts avoid unnecessary database writes, and unchanged cards and map
content avoid rebuilding their widgets. Map dragging redraws once per idle cycle.
Expiration checks use an indexed timestamp instead of loading every active alert
each second; incoming IDs and manual retries also use targeted database lookups.

The feed retains its 4,000-line limit and abbreviates unusually long headlines,
areas, and instructions. Full alert text remains available in alert details and
saved history. These changes do not delete saved history. Existing databases
automatically receive the expiry column and indexes on startup.

For a reproducible synthetic load check, with a display available:

```sh
python scripts/benchmark_processing.py --incoming 1000 --stored 10000 --passes 3
```

This uses a temporary database and sends no real notifications. In a Linux virtual
display check, the original 1,000-alert snapshot blocked processing for about 4.7
seconds. With the location overview and summaries, the same-sized snapshot completed in about 0.49
seconds, yielding between batches, with a maximum measured UI heartbeat gap of
73 ms. Ten idle health ticks took about 2 ms. Timings vary with hardware, alert
content, and platform; Windows performance has not been measured here.

## Validation

```sh
python -m unittest discover -s tests -v
```

GUI integration tests require a display (`DISPLAY` on Linux); otherwise they
are explicitly skipped. For headless runs, use a virtual X server and
`SDL_AUDIODRIVER=dummy`. Tests cover profiles, geographic matching, alert
versions, lifecycle transitions, channel-specific retries, migration, card
pagination, map interaction, tray failure handling, guided location setup,
delivery-panel retries, simulation isolation, shared overlap submissions,
watch/warning rules, history filters, full snapshot CSV export, editable-field
contrast, large batches, transaction rollback, idle expiry lookups, and redraw
reuse, change summaries, removed-location updates, location threat ranking,
radar projection, caching, playback, stale imagery, icon setup, event-specific
sound filters, safe connection diagnostics/redirect handling, recorded notification
explanations, speech preferences, independent voice retries, bounded queuing,
cancellation, slow-voice isolation, saved refresh intervals, and background-GC
shutdown safety. Tcl interpreters are released on the GUI thread after their
widgets and pending jobs are gone; closed form variables are disposed before
window destruction, and idle workers release completed jobs. This prevents
`Tcl_AsyncDelete: async handler deleted by the wrong thread` during cleanup
without blocking window closure on network requests. Windows Run-entry and
notification submission paths are mocked on Linux; actual Windows tray/toast
behavior still needs verification on Windows.

A separate current-conditions/forecast panel, severity-specific rules, and
individual-event desktop notification rule editors are not part of this release.
NWS Short Term Forecast alert products are supported when supplied by the alerts API.
