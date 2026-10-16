# Stormwatch

A TkFlow desktop weather dashboard for saved locations, live National Weather
Service watches and warnings, and independent sound/desktop notifications.

## Install and run

Use Python 3.12+ with Tk support:

```sh
python -m pip install -r requirements.txt
python main.py
```

Run `python main.py --monitor` to immediately monitor the saved locations.
`--test-tornado` and `--test-hurricane` play `alert.mp3` without opening the GUI.
The interface needs a desktop display; audible alerts need an audio device.
Linux may require `python3-tk` and desktop notification tools such as
`libnotify-bin`/`python3-dbus`. The system tray uses pystray and Pillow.

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
API key, remote tiles, or additional network domains. It is not radar or storm
tracking. Dataset attribution is in [data/README.md](data/README.md).

## Versions and delivery receipts

The previous ID-only behavior has been replaced by per-version records:

- Meaningful content, expiration, geographic coverage, or native storm-polygon
  changes produce a new alert version. Repeated copies of the same version do
  not duplicate the feed. Map-only zone enrichment does not create a version.
- Current cards always reflect the latest successful snapshot, regardless of
  whether that version was previously displayed or notified.
- Feed display, sound submission, and desktop submission are recorded separately.
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

The **Delivery** tab lists sound and desktop channel records separately, with
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
coverage warnings are displayed separately. Refresh interval: 60 seconds.

Network access is required only to `api.weather.gov` for alert, cancellation,
county, point-resolution, and boundary requests. This is an informational
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
seconds. After these changes, the same-sized snapshot completed in about 0.26
seconds, yielding between batches, with a maximum measured UI heartbeat gap of
33 ms. Ten idle health ticks took about 1 ms. Timings vary with hardware, alert
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
reuse. Windows Run-entry and
notification submission paths are mocked on Linux; actual Windows tray/toast
behavior still needs verification on Windows.

Forecasts, text-to-speech, and individual event/severity-level rule editors
are not part of this release.
