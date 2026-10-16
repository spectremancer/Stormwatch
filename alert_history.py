"""Versioned alerts, saved locations, and independent delivery receipts."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading

from locations import LocationProfile


def instant(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def version_of(alert):
    # Deliberately ignore fetch time, map geometry enrichment, and profile names.
    fields = ("event", "headline", "area", "severity", "urgency", "sent", "expires",
              "ends", "instruction", "description", "message_type", "references", "geocode", "zones")
    payload = {key: alert.get(key) for key in fields}
    payload["geometry"] = alert.get("geometry") if alert.get("geometry_source") != "NWS affected zones" else None
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class AlertHistory:
    def __init__(self, path=None):
        if path is None:
            root = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
            path = root / "Stormwatch" / "processed-alerts.sqlite3"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS processed_alerts (id TEXT PRIMARY KEY, processed_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, version TEXT, data TEXT NOT NULL,
                status TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS versions (id TEXT, version TEXT, kind TEXT, data TEXT NOT NULL,
                displayed INTEGER DEFAULT 0, PRIMARY KEY(id, version));
            CREATE TABLE IF NOT EXISTS deliveries (id TEXT, version TEXT, profile TEXT, channel TEXT,
                state TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0, error TEXT DEFAULT '',
                PRIMARY KEY(id, version, profile, channel));
        ''')
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(deliveries)")}
        for name in ("scheduled_at", "last_attempt", "reason"):
            if name not in columns:
                self.connection.execute(f"ALTER TABLE deliveries ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        self.connection.commit()

    def claim(self, alert_id):
        """Retained for compatibility with the original ID-only store."""
        with self.lock, self.connection:
            result = self.connection.execute("INSERT OR IGNORE INTO processed_alerts (id) VALUES (?)", (alert_id,))
            return result.rowcount == 1

    def setting(self, name, default=None):
        with self.lock:
            row = self.connection.execute("SELECT data FROM settings WHERE name=?", (name,)).fetchone()
            return json.loads(row[0]) if row else default

    def save_setting(self, name, value):
        with self.lock, self.connection:
            self.connection.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (name, json.dumps(value)))

    def profiles(self):
        with self.lock:
            return [LocationProfile.from_json(row[0]) for row in self.connection.execute("SELECT data FROM profiles ORDER BY rowid")]

    def save_profile(self, profile):
        profile.validate()
        with self.lock, self.connection:
            self.connection.execute("INSERT OR REPLACE INTO profiles VALUES (?, ?)", (profile.id, profile.to_json()))

    def delete_profile(self, profile_id):
        with self.lock, self.connection:
            self.connection.execute("DELETE FROM profiles WHERE id=?", (profile_id,))

    def observe(self, alert, now=None):
        now = now or datetime.now(timezone.utc)
        version = version_of(alert)
        data = json.dumps(alert)
        with self.lock, self.connection:
            old = self.connection.execute("SELECT * FROM alerts WHERE id=?", (alert["id"],)).fetchone()
            reference_old = None
            for ref in alert.get("references", []):
                reference_id = ref.get("identifier") or ref.get("id") if isinstance(ref, dict) else ref
                referenced = self.connection.execute("SELECT * FROM alerts WHERE id=?", (reference_id,)).fetchone()
                if referenced and reference_old is None:
                    reference_old = referenced
                if referenced and alert.get("message_type", "").lower() == "update":
                    self.connection.execute("UPDATE alerts SET status='Superseded' WHERE id=?", (reference_id,))
            previous = old or reference_old
            kind = "New" if previous is None else "Updated"
            if previous:
                old_alert = json.loads(previous["data"])
                old_end, new_end = instant(old_alert.get("ends") or old_alert.get("expires")), instant(alert.get("ends") or alert.get("expires"))
                if old_end and new_end and new_end > old_end:
                    kind = "Extended"
            cancelled = alert.get("message_type", "").lower() == "cancel"
            end = instant(alert.get("ends") or alert.get("expires"))
            status = "Cancelled" if cancelled else "Expired" if end and end <= now else "Active"
            if cancelled:
                kind = "Cancelled"
            elif status == "Expired":
                kind = "Expired"
            self.connection.execute("INSERT OR REPLACE INTO alerts VALUES (?, ?, ?, ?, ?)",
                                    (alert["id"], version, data, status, now.isoformat()))
            self.connection.execute("INSERT OR IGNORE INTO versions (id, version, kind, data) VALUES (?, ?, ?, ?)",
                                    (alert["id"], version, kind, data))
            kind = self.connection.execute("SELECT kind FROM versions WHERE id=? AND version=?", (alert["id"], version)).fetchone()[0]
            # Migrate ID-only history as a quiet baseline. Later versions notify.
            legacy = old is None and self.connection.execute("SELECT 1 FROM processed_alerts WHERE id=?", (alert["id"],)).fetchone()
            if legacy:
                self.connection.execute("UPDATE versions SET displayed=1 WHERE id=? AND version=?", (alert["id"], version))
            return version, kind, bool(legacy)

    def displayed(self, alert_id, version):
        with self.lock:
            return bool(self.connection.execute("SELECT displayed FROM versions WHERE id=? AND version=?", (alert_id, version)).fetchone()[0])

    def mark_displayed(self, alert_id, version):
        with self.lock, self.connection:
            self.connection.execute("UPDATE versions SET displayed=1 WHERE id=? AND version=?", (alert_id, version))

    def schedule(self, alert_id, version, profile, channel, quiet=False, reason=""):
        with self.lock, self.connection:
            self.connection.execute("INSERT OR IGNORE INTO deliveries (id,version,profile,channel,state,scheduled_at,reason) VALUES (?,?,?,?,?,?,?)",
                                    (alert_id, version, profile, channel, "skipped" if quiet else "pending",
                                     datetime.now(timezone.utc).isoformat(), reason or ("Quiet startup or legacy baseline" if quiet else "")))

    def pending(self, alert_id, version, profile, channel):
        with self.lock:
            row = self.connection.execute("SELECT state, attempts FROM deliveries WHERE id=? AND version=? AND profile=? AND channel=?",
                                          (alert_id, version, profile, channel)).fetchone()
            return bool(row and row["state"] in ("pending", "failed") and row["attempts"] < 3)

    def receipt(self, alert_id, version, profile, channel, error=None):
        with self.lock, self.connection:
            self.connection.execute("UPDATE deliveries SET state=?, attempts=attempts+1, error=?, last_attempt=? WHERE id=? AND version=? AND profile=? AND channel=?",
                                    ("failed" if error else "sent", str(error or ""), datetime.now(timezone.utc).isoformat(),
                                     alert_id, version, profile, channel))

    def is_current(self, alert_id, version):
        with self.lock:
            row = self.connection.execute("SELECT version,status FROM alerts WHERE id=?", (alert_id,)).fetchone()
            return bool(row and row["version"] == version and row["status"] in ("Active", "Cancelled"))

    def delivery(self, alert_id, version, profile, channel):
        with self.lock:
            row = self.connection.execute("SELECT * FROM deliveries WHERE id=? AND version=? AND profile=? AND channel=?",
                                          (alert_id, version, profile, channel)).fetchone()
            return dict(row) if row else None

    def delivery_count(self, failed_only=False):
        with self.lock:
            where = " WHERE state='failed'" if failed_only else ""
            return self.connection.execute("SELECT count(*) FROM deliveries" + where).fetchone()[0]

    def delivery_rows(self, limit=50, offset=0, failed_only=False):
        with self.lock:
            where = " WHERE d.state='failed'" if failed_only else ""
            rows = self.connection.execute("""SELECT d.*, v.data AS alert_data, v.kind, v.displayed,
                p.data AS profile_data, a.status AS alert_status, a.version AS current_version
                FROM deliveries d LEFT JOIN versions v ON d.id=v.id AND d.version=v.version
                LEFT JOIN profiles p ON d.profile=p.id LEFT JOIN alerts a ON d.id=a.id""" +
                where + " ORDER BY d.rowid DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            return [dict(row, alert=json.loads(row["alert_data"]) if row["alert_data"] else {},
                         location=json.loads(row["profile_data"]) if row["profile_data"] else {}) for row in rows]

    def rows(self, active_only=False):
        with self.lock:
            sql = "SELECT * FROM alerts" + (" WHERE status='Active'" if active_only else "") + " ORDER BY updated DESC"
            return [dict(row, alert=json.loads(row["data"])) for row in self.connection.execute(sql)]

    def reconcile(self, current_ids, now=None):
        """Absence is not proof of cancellation. Failed polls never call this."""
        now = now or datetime.now(timezone.utc)
        changes = []
        with self.lock, self.connection:
            for row in self.rows(active_only=True):
                end = instant(row["alert"].get("ends") or row["alert"].get("expires"))
                status = "Expired" if end and end <= now else "No longer active" if row["id"] not in current_ids else None
                if status:
                    self.connection.execute("UPDATE alerts SET status=? WHERE id=?", (status, row["id"]))
                    changes.append((row["alert"], status))
        return changes

    def cancel_references(self, alert):
        changed = []
        with self.lock, self.connection:
            for ref in alert.get("references", []):
                alert_id = ref.get("identifier") or ref.get("id") if isinstance(ref, dict) else ref
                row = self.connection.execute("SELECT data FROM alerts WHERE id=? AND status='Active'", (alert_id,)).fetchone()
                if row:
                    self.connection.execute("UPDATE alerts SET status='Cancelled' WHERE id=?", (alert_id,))
                    changed.append((json.loads(row[0]), "Cancelled"))
        return changed

    def close(self):
        with self.lock:
            self.connection.close()
