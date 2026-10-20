# README screenshots

These PNGs are unaltered screen captures of real Stormwatch client areas on Linux
(Python 3.13, Tk 8.6), using the Navy theme. They were captured on October 20, 2026.
Window chrome, fonts, and operating-system controls can vary across desktops.

The weather, profiles, history, and delivery outcomes are fictional. The main
window and alert cards label the session **SIMULATION**; notification successes
and the example failure are database fixtures, not actual device submissions.
The map displays sample affected-area polygons and saved pins with radar off.
The Documentation window shows the real bundled guide and its search results.

To regenerate from the repository root with dependencies from `requirements.txt`
installed and a graphical display at least 1364 × 1024 pixels:

```sh
python scripts/capture_screenshots.py
```

On a Linux virtual display, set `DISPLAY` to that display first. Use a native Tk
installation with normal Unicode font support for readable screenshots. The
script uses temporary state, never starts monitoring, leaves radar disabled, and
blocks NWS fetches and sound/desktop submission methods. It captures active
alerts, saved-location summaries, map, notification delivery, history, sound
settings, Metrics, and Documentation. It closes the application and removes the
temporary database after capture; no production settings or history are changed.
