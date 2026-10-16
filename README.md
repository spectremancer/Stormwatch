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
unchecked. The first successful refresh displays existing selected alerts quietly;
subsequent new or updated alerts trigger WeatherService notifications. Tornado
and hurricane events also play `alert.mp3`.

**Test alert sound** plays `alert.mp3` without generating a fake weather alert.
The read-only feed contains only selected weather alerts. Connection failures,
retry information, and sound-test results appear in the status bar. **Clear feed**
clears the display without making unchanged alerts appear again.

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
