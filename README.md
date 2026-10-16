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

Use **Add** to create Home, Family, Work, or other named profiles. Each profile
saves its own event selections, enabled state, sound preference, and desktop
notification preference. All enabled profiles monitor together; selecting a
profile in the sidebar changes which profile you are editing.

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
An alert matching multiple profiles has separate notification receipts for each
profile, so overlapping profiles may each notify.

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
  refreshes, up to three attempts per profile/version/channel. Disabling a
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
`~/.local/state/Stormwatch/processed-alerts.sqlite3`). Back up this file to
preserve profiles and history. The feed is a current-session view; searchable
history/CSV export are future work.

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

## Validation

```sh
python -m unittest discover -s tests -v
```

GUI integration tests require a display (`DISPLAY` on Linux); otherwise they
are explicitly skipped. For headless runs, use a virtual X server and
`SDL_AUDIODRIVER=dummy`. Tests cover profiles, geographic matching, alert
versions, lifecycle transitions, channel-specific retries, migration, card
pagination, map interaction, and tray failure handling. Windows Run-entry and
notification submission paths are mocked on Linux; actual Windows tray/toast
behavior still needs verification on Windows.

Forecasts, text-to-speech, full notification rule editors, searchable history,
and a user-facing demo mode are not part of this release.
