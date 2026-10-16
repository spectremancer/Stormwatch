# Stormwatch

A TkFlow desktop dashboard for National Weather Service watches and warnings.

## Run

Use Python 3.12 or newer with Tk support and install the runtime dependencies:

```sh
python -m pip install requests pygame plyer
python main.py
```

A desktop display and audio device are required for the interface and audible
alerts. Linux distributions may package Tk separately as `python3-tk` and desktop
notification tools as `libnotify-bin`/`python3-dbus`.

Choose watch and warning types, then select **Start monitoring**. The dashboard
refreshes every 60 seconds. **Pause monitoring** stops delivery; an outstanding
request may finish in the background. Changes to event selections apply on the
next refresh. Additional active NWS event types appear in the selection list
unchecked. The first successful refresh displays unseen selected alerts. Previously unseen
tornado and hurricane watches/warnings also trigger desktop notifications on
that first refresh, including Windows notifications through plyer. Other event
types begin notifying after the first successful refresh. Tornado and hurricane
events also play `alert.mp3`. Windows notification settings and Do Not Disturb
can affect whether a notification is displayed.

**Test alert sound** plays `alert.mp3` without generating a fake weather alert.
The read-only feed contains only selected weather alerts. Connection failures,
retry information, and sound-test results appear in the status bar. **Clear feed**
clears the display without making processed alerts appear again.

Alert IDs are recorded in a persistent per-user SQLite database: on Windows,
`%LOCALAPPDATA%/Stormwatch/processed-alerts.sqlite3`; elsewhere,
`$XDG_STATE_HOME/Stormwatch/processed-alerts.sqlite3` (defaulting to
`~/.local/state/Stormwatch/processed-alerts.sqlite3`). Each selected alert ID is
processed once, even across restarts, filter changes, disappearance/reappearance,
or changes to its content. A newly issued alert with a new ID is processed normally.
The history begins with this version; previous GUI sessions did not retain a
durable record of which alerts they displayed. IDs are recorded before delivery
to prevent repeats; an interruption or notification failure does not retry the
same ID.

NWS access requires HTTPS connectivity to `api.weather.gov`. This application is
an informational monitor; continue to follow official local weather guidance.

The existing `--test-tornado` and `--test-hurricane` flags can test the MP3 without
opening the GUI.

## Tests

```sh
python -m unittest discover -s tests -v
```

The GUI integration tests need a display (`DISPLAY` on Linux); otherwise they
are explicitly skipped. For headless testing, run under a virtual X server and
set `SDL_AUDIODRIVER=dummy`. Dummy audio checks playback without audible output.
