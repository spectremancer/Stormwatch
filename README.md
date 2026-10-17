# Stormwatch

A TkFlow desktop weather dashboard for saved locations, live National Weather
Service watches and warnings, and independent sound, desktop, and optional spoken notifications.

## Install and run

Use Python 3.12+ with Tk support:

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
Linux may require `python3-tk` and desktop notification tools such as
`libnotify-bin`/`python3-dbus`. The system tray uses pystray and Pillow.

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

## Watch / warning notification rules

The location wizard and **Edit** include **Watch / warning rules**. For example,
leave the sound/desktop master switches enabled, check sound for warnings, uncheck
sound for watches, and keep desktop notifications checked for both. Each location
has its own four rules: warning sound, warning desktop, watch sound, and watch
desktop. The sidebar summarizes the selected location's effective rules.

These categories use the NWS event's Watch/Warning designation, not the separate
NWS severity field. Event-type selections still determine what is monitored;
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

The location's Sound switch and watch/warning sound rules must also allow an
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

Announcements read the event, matching saved-location names, update type when
applicable, and the expiration in the computer's local timezone. They do not
rewrite safety instructions or infer storm movement. For example: “Tornado
Warning for Home, Family. Until October 17 at 8:30 PM CDT.”

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
unchanged version. Quiet startup/legacy suppression applies to speech too.

The speech queue holds at most 32 alert versions, prioritizing warnings, severity,
and tornado/hurricane events. Eligible overflow remains pending for a later
refresh. Before speaking, the worker checks current preferences, fresh monitoring
data, version, and expiration. Cancelled, superseded, and expired alerts stay
silent. Pausing monitoring clears the queue and stops the owned voice process;
closing the application also stops it. Each native speech command has a 45-second
timeout. Completion does not prove someone heard the announcement.

## Active alerts, lifecycle, and map

**Active alerts** shows current matched alerts as cards with profile names,
affected area, severity, issue time, and an expiration countdown. Cards are
paginated at 20 per page to handle large national alert lists. Opening details
shows the full NWS description and instructions and an official HTTPS link.
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
Warnings rank before watches, then by official severity; tornado/hurricane events
and earlier expirations break ties. Disabled locations are clearly labeled.
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
subject to the provider's service and terms. RainViewer attribution links from
the map. The integration was checked against the official
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

## Searchable history and CSV export

**History** provides a paginated archive of alert versions and lifecycle changes.
Search across event names, headlines, areas, descriptions, and instructions.
Filter by recorded location name, exact event type, change (new, updated,
extended, cancelled, expired, or no longer active), date range, and latest
channel result (submitted, failed, pending, suppressed, or no notifications).
Use **Search** to apply filters and **Clear filters** to reset them. Delivery
results reflect current receipts, not a log of every individual retry.

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
instructions, and official URL. Files use UTF-8 with a BOM for spreadsheet
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
entry that invokes this checkout with `--monitor`; it does not request admin
rights. Keep the checkout and Python installation at the same paths. This
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
cancellation, and slow-voice isolation. Windows Run-entry and
notification submission paths are mocked on Linux; actual Windows tray/toast
behavior still needs verification on Windows.

Forecasts, severity-specific rules, and individual-event desktop
notification rule editors are not part of this release.
