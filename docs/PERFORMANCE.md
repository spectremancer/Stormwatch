# Stabilization performance observations

These measurements use the Linux development host, Python 3.12, a virtual Xorg
display, temporary databases, and disabled real notifications. They are workload
observations, not a guarantee for every computer, provider response, or desktop.

## Processing benchmark

| Incoming alerts / pre-existing alert rows | Before: first pass | After: first pass | After: repeated passes | Before: largest UI heartbeat gap | After: largest UI heartbeat gap |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1,000 / 10,000 | 0.504 s | 0.736 s | 0.243–0.273 s | 65 ms | 23 ms |
| 5,000 / 50,000 | 2.529 s | 3.905 s | 1.349–1.496 s | 397 ms | 83 ms |

Largest gaps cover all three passes. The first pass now also builds searchable
history/FTS entries; it takes longer while yielding to the interface more often.
Repeated processing preserves successful receipts and avoids rebuilding unchanged
cards and archive views. End-to-end network and physical-device delivery times
are not included. Pre-existing rows in this benchmark are alert rows, not a fully
populated searchable archive; the endurance workload below supplies that separately.

```sh
DISPLAY=:99 SDL_AUDIODRIVER=dummy python -B scripts/benchmark_processing.py --incoming 1000 --stored 10000 --passes 3
DISPLAY=:99 SDL_AUDIODRIVER=dummy python -B scripts/benchmark_processing.py --incoming 5000 --stored 50000 --passes 3
```

Local responsiveness goals are below 100 ms for the smaller workload and below
200 ms for the larger burst. Record cold processing duration separately from
responsiveness and steady-state processing time.

## Combined endurance workload

A 60-second run completed 30 cycles with 1,000 complex-polygon alerts, five
profiles, 10,000 searchable historical records, simulated radar loading/viewport
changes, background imports, ending events, and simulated connection failures.
There were no import errors. The maximum UI heartbeat gap was 244 ms, below the
500 ms regression ceiling used for this combined workload. CI uses a more
permissive 1,000 ms ceiling because shared-runner timing is less predictable.

The workload exposed repeated per-vertex Tk size queries and redundant overlapping
polygon draws. Projection dimensions are now cached, large display plans are
prepared off-thread, off-screen alert outlines are skipped, and coincident
outlines share a searchable message picker. Matching uses the original geometry.

Process RSS grew from about 86 MiB at the start to 280 MiB at the end, with a peak
of about 282 MiB; the first post-warmup sample was about 236 MiB. This short run
includes substantial cache/UI warmup and continuing archive growth. It does not
prove bounded multi-day memory usage or establish the absence of a memory leak.

```sh
DISPLAY=:99 SDL_AUDIODRIVER=dummy python -B scripts/soak_monitoring.py --seconds 60 --incoming 1000 --archive 10000 --profiles 5 --report /tmp/soak.json
```

A dedicated 48-hour run, measured after warmup and across restarts, remains a
release acceptance task. Real Windows speech/toast/tray behavior, actual radar
connectivity, physical sound, and display scaling require the native checks in
[RELEASE_ACCEPTANCE.md](RELEASE_ACCEPTANCE.md). The simulated radar provider makes
this endurance workload independent of external network availability.
