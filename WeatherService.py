from datetime import datetime, timedelta, timezone
import json
import logging
import platform
import subprocess
import time
import pygame
from pathlib import Path

import requests
from plyer import notification
from event_catalog import WEATHER_EVENTS, is_supported_event


class WeatherService:
    API_URL = "https://api.weather.gov/alerts/active"

    WATCHED_EVENTS = set(WEATHER_EVENTS)

    def __init__(self, interval=60):
        self.interval = interval
        self.base_dir = Path(__file__).resolve().parent
        self.state_file = self.base_dir / "storm_alert_state.json"

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "USStormMonitor/1.0 (storm-monitor-project)",
            "Accept": "application/geo+json",
        })

        self.logger = logging.getLogger("WeatherService")
        self._configure_logging()

        self.seen_alerts = self._load_state()

    def _configure_logging(self):
        self.logger.setLevel(logging.INFO)

        if not self.logger.handlers:
            formatter = logging.Formatter(
                "%(asctime)s %(levelname)s: %(message)s"
            )

            file_handler = logging.FileHandler(
                self.base_dir / "storm_monitor.log",
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)

            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)

            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)

    # ---------- State management ----------

    def _load_state(self):
        try:
            data = json.loads(
                self.state_file.read_text(encoding="utf-8")
            )
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_state(self, state):
        try:
            self.state_file.write_text(
                json.dumps(state, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            self.logger.error("Could not save state: %s", exc)

    # ---------- Weather data ----------

    def fetch_alerts(self):
        return self._features(self.API_URL)

    def _features(self, url, params=None):
        features = []
        visited = set()
        while url:
            # NWS pagination remains on the same trusted API host.
            from urllib.parse import urlparse
            if urlparse(url).scheme != "https" or urlparse(url).netloc != "api.weather.gov" or url in visited:
                raise ValueError("Invalid NWS pagination link")
            visited.add(url)
            if len(visited) > 100:
                raise ValueError("NWS pagination limit exceeded; snapshot is incomplete")
            response = self.session.get(url, params=params, timeout=20)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data.get("features"), list):
                raise ValueError("Invalid NWS alert response")
            features.extend(data["features"])
            url = (data.get("pagination") or {}).get("next")
            params = None
        return features

    def fetch_cancellations(self, since=None):
        since = since or datetime.now(timezone.utc) - timedelta(minutes=15)
        return self._features("https://api.weather.gov/alerts", {
            "message_type": "cancel", "start": since.isoformat(), "limit": 500})

    def enrich_boundaries(self, alerts, profiles, max_requests=6):
        """Cache official affected-zone polygons for alerts without geometry.

        Limit fresh lookups per poll; never draw an incomplete subset of an area.
        Zone outlines are map context, not precise storm polygons.
        """
        from urllib.parse import urlparse
        from locations import rings
        if not hasattr(self, "_zone_cache"):
            self._zone_cache = {}
        for alert in alerts:
            if alert.get("geometry") or not any(p.matches(alert) for p in profiles):
                continue
            urls = alert.get("zones", [])
            for url in urls:
                if url in self._zone_cache or max_requests <= 0:
                    continue
                if urlparse(url).scheme != "https" or urlparse(url).netloc != "api.weather.gov":
                    continue
                max_requests -= 1
                try:
                    response = self.session.get(url, timeout=5)
                    response.raise_for_status()
                    geometry = response.json().get("geometry")
                    if rings(geometry):
                        self._zone_cache[url] = geometry
                except (requests.RequestException, ValueError):
                    continue
            if urls and all(url in self._zone_cache for url in urls):
                polygons = [polygon for url in urls for polygon in rings(self._zone_cache[url])]
                alert["geometry"] = {"type": "MultiPolygon", "coordinates": polygons}
                alert["geometry_source"] = "NWS affected zones"

    def list_counties(self, states):
        response = self.session.get("https://api.weather.gov/zones/county",
                                    params={"area": ",".join(states)}, timeout=20)
        response.raise_for_status()
        return sorted((f["properties"]["id"], f["properties"]["name"])
                      for f in response.json()["features"])

    def resolve_location(self, latitude, longitude):
        response = self.session.get(f"https://api.weather.gov/points/{latitude:.4f},{longitude:.4f}", timeout=20)
        response.raise_for_status()
        props = response.json()["properties"]
        return [props[key].rstrip("/").rsplit("/", 1)[-1]
                for key in ("county", "forecastZone", "fireWeatherZone") if props.get(key)]

    def parse_alert(self, feature):
        props = feature.get("properties") or {}
        event = props.get("event") or ""

        alert_id = props.get("id") or feature.get("id") or ""

        if not alert_id or not is_supported_event(event):
            return None

        return {
            "geometry": feature.get("geometry"),
            "geocode": props.get("geocode") or {},
            "zones": props.get("affectedZones") or [],
            "references": props.get("references") or [],
            "message_type": props.get("messageType") or "Alert",
            "description": props.get("description") or "",
            "ends": props.get("ends") or "",
            "id": alert_id,
            "event": event,
            "headline": props.get("headline") or event,
            "area": props.get("areaDesc") or "Area unavailable",
            "severity": props.get("severity") or "Unknown",
            "urgency": props.get("urgency") or "Unknown",
            "sent": props.get("sent") or "",
            "expires": props.get("expires") or "Unknown",
            "instruction": (
                props.get("instruction")
                or "Read the official alert for safety instructions."
            ),
            "url": props.get("web") or feature.get("id") or self.API_URL,
        }

    def get_fingerprint(self, alert):
        fields = [
            alert["event"],
            alert["headline"],
            alert["area"],
            alert["sent"],
            alert["expires"],
            alert["instruction"],
        ]
        return json.dumps(fields)

    # ---------- Notifications ----------

    def play_sound(self):
        try:
            system = platform.system()

            if system == "Windows":
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)

            elif system == "Darwin":
                subprocess.Popen(
                    [
                        "afplay",
                        "/System/Library/Sounds/Sosumi.aiff",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            else:
                # Terminal bell fallback for Linux and other systems.
                print("\a", end="", flush=True)

        except (OSError, RuntimeError) as exc:
            self.logger.warning("Sound failed: %s", exc)

    def notify(self, alert, updated=False):
        prefix = "UPDATED" if updated else "NEW"
        title = f"{prefix}: {alert['event']}"

        # Every event gets the normal system alert sound.
        self.play_sound()

        # Tornado and hurricane watches/warnings also play alert.mp3.
        if alert["event"] in {
            "Tornado Warning",
            "Tornado Watch",
            "Hurricane Warning",
            "Hurricane Watch",
        }:
            self.play_tornado_alert()

        try:
            notification.notify(
                # Windows NOTIFYICONDATA permits 63 title / 255 body chars.
                title=title[:63],
                message=alert["area"][:255],
                app_name="US Storm Monitor",
                timeout=10,
            )
        except Exception as exc:
            self.logger.warning(
                "Desktop notification failed: %s", exc
            )

        self.logger.warning(
            "%s | %s | Area: %s | URL: %s",
            title,
            alert["headline"],
            alert["area"],
            alert["url"],
        )

    def deliver_desktop(self, alert, kind="New", location=""):
        """Raise synchronous submission failures so the delivery ledger can retry."""
        notification.notify(title=f"{kind.upper()}: {alert['event']}"[:63],
                            message=f"{location + ': ' if location else ''}{alert['area']}"[:255],
                            app_name="Stormwatch", timeout=10)

    def deliver_sound(self):
        """Successful mixer submission is recorded separately from desktop delivery."""
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(str(self.base_dir / "alert.mp3"))
        pygame.mixer.music.play()

    # ---------- Monitoring ----------

    def check_alerts(self, first_check=False):
        features = self.fetch_alerts()
        current_state = {}
        matching_count = 0

        for feature in features:
            alert = self.parse_alert(feature)

            if alert is None:
                continue

            matching_count += 1
            alert_id = alert["id"]
            fingerprint = self.get_fingerprint(alert)
            current_state[alert_id] = fingerprint

            previous = self.seen_alerts.get(alert_id)

            if first_check:
                # Avoid a burst of old notifications at startup,
                # but notify for existing tornado and hurricane warnings.
                if alert["event"] in {
                    "Tornado Warning",
                    "Hurricane Warning",
                }:
                    self.notify(alert)
                continue

            if previous != fingerprint:
                self.notify(
                    alert,
                    updated=previous is not None,
                )

        # Update saved state only after a successful API response.
        self.seen_alerts = current_state
        self._save_state(current_state)

        self.logger.info(
            "Received %d active alerts; %d matching alerts.",
            len(features),
            matching_count,
        )

    def select_alert_types(self):
        """Monitor supported NWS weather alerts and environmental hazards."""

        print("\\n=== US Storm Monitor Setup ===")
        print("Monitoring NWS warnings, watches, advisories, statements, outlooks and weather alerts.")
        print("Tornado and hurricane watches/warnings use alert.mp3.\\n")

    def play_tornado_alert(self):
        """Play alert.mp3 for tornado and hurricane watches/warnings."""

        sound_file = Path(__file__).resolve().parent / "alert.mp3"

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()

            pygame.mixer.music.load(str(sound_file))
            pygame.mixer.music.play()

            self.logger.warning(
                "Playing tornado/hurricane alert sound: %s", sound_file
            )

        except (pygame.error, OSError) as exc:
            self.logger.error("Could not play tornado alert: %s", exc)

    def run_forever(self):
        self.select_alert_types()

        self.logger.info("WeatherService started.")
        self.logger.info("Polling every %d seconds.", self.interval)
        self.logger.info(
            "Monitoring supported NWS weather and environmental events."
        )

        first_check = True

        try:
            while True:
                try:
                    self.check_alerts(first_check=first_check)
                    first_check = False

                except requests.RequestException as exc:
                    self.logger.error("NWS request failed: %s", exc)

                except (ValueError, TypeError, KeyError) as exc:
                    self.logger.error("Alert processing failed: %s", exc)

                time.sleep(self.interval)

        except KeyboardInterrupt:
            self.logger.info("WeatherService stopped.")

        finally:
            self.session.close()
