# Release acceptance

Record the version, source commit, artifact SHA-256, OS, desktop/session, Python
or packaged runtime, display scale, enabled optional backends, and test results.
A green unit suite or offline self-test does not mark the manual checks passed.

## Automated gates

- Windows and Linux suites on Python 3.12 and 3.13, including migrations, lifecycle
  cleanup, per-channel retries, search/import isolation, backup/restore, and GUI cleanup.
- Run the offline source and actual packaged-executable self-test. Verify resources
  and user-writable state when installed under a path containing spaces.
- Verify the version matches the tag, installer, Windows file metadata, and manifest.
  The manifest must match the SHA-256 recorded by the tested executable itself
  and its embedded clean source commit. Reject a report from another build.
- Repeat both documented processing benchmarks. Report initial and repeated timings
  separately, along with hardware and heartbeat gaps.
- Run the populated-archive endurance workload. A dedicated 48-hour run must record
  RSS after warmup and periodically thereafter; investigate a sustained growth trend.
  Test failures must fail acceptance, not be silently retried until a pass appears.

## Native desktop checks (record each as pass, fail, or not tested)

- Windows 10/11: real MP3 sound, installed System.Speech voice, visible desktop
  notifications, disabled notification permissions, and Do Not Disturb behavior.
- Windows: close-to-tray, restore from tray, explicit Quit, per-user login startup,
  moved install paths, install/upgrade/uninstall, and restored settings/receipts.
- Linux: notify-send/session D-Bus, espeak-ng audio, supported/unsupported tray
  backends, X11 and a Wayland/XWayland desktop. Verify graceful missing dependencies.
- Layout: 1366×768, a large/4K display, and Windows 100/125/150/200% scaling.
  Check collapsed sidebar, splitter, keyboard focus, readable fields, popups, and radar.
- Network: loss/recovery, slow NWS, cancellation-only failure, HTTP 429/Retry-After,
  radar metadata success with tile failure, and provider errors. Last-known data must
  remain labeled appropriately and known expired polygons must leave active views.
- Time/session: sleep/wake, overnight operation, timezone change, DST transition,
  and significant clock adjustment. Verify staleness and post-start speech eligibility.
- Storage: representative large import while monitoring, backup during use, rejected
  invalid restore, staged restore after full exit, full/read-only disk failure, and
  forced process termination during a write followed by restart. Preserve a test backup.
- Sign Windows artifacts with the maintainer's certificate when available, verify the
  signature, then generate checksums. Do not label unsigned artifacts as signed.

No native or multi-day check is automatically completed by adding this checklist.
