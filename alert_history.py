"""Versioned alerts, saved locations, and independent delivery receipts."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading

from locations import LocationProfile
from history_store import HistoryArchive


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


class AlertHistory(HistoryArchive):
    def __init__(self, path=None):
        if path is None:
            root = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
            path = root / "Stormwatch" / "processed-alerts.sqlite3"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._transaction_depth = 0
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS processed_alerts (id TEXT PRIMARY KEY, processed_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS channel_submissions (id TEXT, version TEXT, channel TEXT,
                state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, error TEXT DEFAULT '',
                last_attempt TEXT DEFAULT '', members TEXT DEFAULT '[]', PRIMARY KEY(id,version,channel));
            CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, version TEXT, data TEXT NOT NULL,
                status TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS versions (id TEXT, version TEXT, kind TEXT, data TEXT NOT NULL,
                displayed INTEGER DEFAULT 0, PRIMARY KEY(id, version));
            CREATE TABLE IF NOT EXISTS deliveries (id TEXT, version TEXT, profile TEXT, channel TEXT,
                state TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0, error TEXT DEFAULT '',
                PRIMARY KEY(id, version, profile, channel));
        ''')
        alert_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(alerts)")}
        if "expires_at" not in alert_columns:
            self.connection.execute("ALTER TABLE alerts ADD COLUMN expires_at TEXT NOT NULL DEFAULT ''")
            for row in self.connection.execute("SELECT id,data FROM alerts").fetchall():
                alert = json.loads(row["data"])
                end = instant(alert.get("ends") or alert.get("expires"))
                self.connection.execute("UPDATE alerts SET expires_at=? WHERE id=?", (end.isoformat() if end else "", row["id"]))
        self.connection.execute("CREATE INDEX IF NOT EXISTS active_alert_expiry ON alerts(status,expires_at)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS active_alert_updated ON alerts(status,updated DESC)")
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(deliveries)")}
        for name in ("scheduled_at", "last_attempt", "reason"):
            if name not in columns:
                self.connection.execute(f"ALTER TABLE deliveries ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        self.connection.commit()
        self._initialize_archive()

    @contextmanager
    def transaction(self):
        """Nested operations share one atomic commit per short processing batch."""
        with self.lock:
            outer = self._transaction_depth == 0
            self._transaction_depth += 1
            try:
                yield
            except BaseException:
                if outer:
                    self.connection.rollback()
                raise
            else:
                if outer:
                    try:
                        self.connection.commit()
                    except BaseException:
                        self.connection.rollback()
                        raise
            finally:
                self._transaction_depth -= 1

    def known_ids(self, alert_ids):
        values = list(alert_ids)
        result = set()
        with self.lock:
            for offset in range(0,len(values),500):
                part = values[offset:offset+500]
                result.update(row[0] for row in self.connection.execute(
                    "SELECT id FROM alerts WHERE id IN (" + ",".join("?" for _ in part) + ")", part))
        return result

    def get_alert(self, alert_id):
        with self.lock:
            row = self.connection.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
            return dict(row, alert=json.loads(row["data"])) if row else None

    def claim(self, alert_id):
        """Retained for compatibility with the original ID-only store."""
        with self.transaction():
            result = self.connection.execute("INSERT OR IGNORE INTO processed_alerts (id) VALUES (?)", (alert_id,))
            return result.rowcount == 1

    def setting(self, name, default=None):
        with self.lock:
            row = self.connection.execute("SELECT data FROM settings WHERE name=?", (name,)).fetchone()
            return json.loads(row[0]) if row else default

    def save_setting(self, name, value):
        with self.transaction():
            self.connection.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (name, json.dumps(value)))

    def profiles(self):
        with self.lock:
            return [LocationProfile.from_json(row[0]) for row in self.connection.execute("SELECT data FROM profiles ORDER BY rowid")]

    def save_profile(self, profile):
        profile.validate()
        with self.transaction():
            self.connection.execute("INSERT OR REPLACE INTO profiles VALUES (?, ?)", (profile.id, profile.to_json()))

    def delete_profile(self, profile_id):
        with self.transaction():
            self.connection.execute("DELETE FROM profiles WHERE id=?", (profile_id,))

    def observe(self, alert, now=None, locations=None):
        now = now or datetime.now(timezone.utc)
        version = version_of(alert)
        data = json.dumps(alert)
        with self.transaction():
            old = self.connection.execute("SELECT * FROM alerts WHERE id=?", (alert["id"],)).fetchone()
            reference_old = None
            for ref in alert.get("references", []):
                reference_id = ref.get("identifier") or ref.get("id") if isinstance(ref, dict) else ref
                referenced = self.connection.execute("SELECT * FROM alerts WHERE id=?", (reference_id,)).fetchone()
                if referenced and reference_old is None:
                    reference_old = referenced
                if referenced and alert.get("message_type", "").lower() == "update":
                    self.connection.execute("UPDATE alerts SET status='Superseded' WHERE id=?", (reference_id,))
            end = instant(alert.get("ends") or alert.get("expires"))
            cancelled = alert.get("message_type", "").lower() == "cancel"
            status = "Cancelled" if cancelled else "Expired" if end and end <= now else "Active"
            if old and old["version"] == version:
                kind = self.connection.execute("SELECT kind FROM versions WHERE id=? AND version=?", (alert["id"],version)).fetchone()[0]
                if old["data"] != data or old["status"] != status:
                    self.connection.execute("UPDATE alerts SET data=?,status=?,updated=?,expires_at=? WHERE id=?",
                        (data,status,now.isoformat(),end.isoformat() if end else "",alert["id"]))
                self._archive_event(alert, version, kind, locations)
                return version, kind, False
            previous = old or reference_old
            kind = "New" if previous is None else "Updated"
            if previous:
                old_alert = json.loads(previous["data"])
                old_end, new_end = instant(old_alert.get("ends") or old_alert.get("expires")), instant(alert.get("ends") or alert.get("expires"))
                if old_end and new_end and new_end > old_end:
                    kind = "Extended"
            if cancelled:
                kind = "Cancelled"
            elif status == "Expired":
                kind = "Expired"
            self.connection.execute("INSERT OR REPLACE INTO alerts (id,version,data,status,updated,expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                                    (alert["id"], version, data, status, now.isoformat(), end.isoformat() if end else ""))
            self.connection.execute("INSERT OR IGNORE INTO versions (id, version, kind, data) VALUES (?, ?, ?, ?)",
                                    (alert["id"], version, kind, data))
            kind = self.connection.execute("SELECT kind FROM versions WHERE id=? AND version=?", (alert["id"], version)).fetchone()[0]
            self._archive_event(alert, version, kind, locations, now.astimezone(timezone.utc).isoformat())
            # Migrate ID-only history as a quiet baseline. Later versions notify.
            legacy = old is None and self.connection.execute("SELECT 1 FROM processed_alerts WHERE id=?", (alert["id"],)).fetchone()
            if legacy:
                self.connection.execute("UPDATE versions SET displayed=1 WHERE id=? AND version=?", (alert["id"], version))
            return version, kind, bool(legacy)

    def displayed(self, alert_id, version):
        with self.lock:
            return bool(self.connection.execute("SELECT displayed FROM versions WHERE id=? AND version=?", (alert_id, version)).fetchone()[0])

    def mark_displayed(self, alert_id, version):
        with self.transaction():
            self.connection.execute("UPDATE versions SET displayed=1 WHERE id=? AND version=?", (alert_id, version))

    def schedule(self, alert_id, version, profile, channel, quiet=False, reason=""):
        with self.transaction():
            self.connection.execute("INSERT OR IGNORE INTO deliveries (id,version,profile,channel,state,scheduled_at,reason) VALUES (?,?,?,?,?,?,?)",
                                    (alert_id, version, profile, channel, "skipped" if quiet else "pending",
                                     datetime.now(timezone.utc).isoformat(), reason or ("Quiet startup or legacy baseline" if quiet else "")))
            row = self.connection.execute("SELECT state,attempts FROM deliveries WHERE id=? AND version=? AND profile=? AND channel=?",
                                          (alert_id,version,profile,channel)).fetchone()
            return row["state"] in ("pending","failed") and row["attempts"] < 3

    def pending(self, alert_id, version, profile, channel):
        with self.lock:
            row = self.connection.execute("SELECT state, attempts FROM deliveries WHERE id=? AND version=? AND profile=? AND channel=?",
                                          (alert_id, version, profile, channel)).fetchone()
            return bool(row and row["state"] in ("pending", "failed") and row["attempts"] < 3)

    def receipt(self, alert_id, version, profile, channel, error=None):
        with self.transaction():
            self.connection.execute("UPDATE deliveries SET state=?, attempts=attempts+1, error=?, last_attempt=? WHERE id=? AND version=? AND profile=? AND channel=?",
                                    ("failed" if error else "sent", str(error or ""), datetime.now(timezone.utc).isoformat(),
                                     alert_id, version, profile, channel))

    def submission(self, alert_id, version, channel):
        """Shared result for one alert version/channel, importing older receipts lazily."""
        with self.transaction():
            row = self.connection.execute("SELECT * FROM channel_submissions WHERE id=? AND version=? AND channel=?",
                                          (alert_id, version, channel)).fetchone()
            if row:
                return dict(row)
            receipts = self.connection.execute("SELECT * FROM deliveries WHERE id=? AND version=? AND channel=? AND state!='skipped'",
                                               (alert_id, version, channel)).fetchall()
            sent = next((r for r in receipts if r["state"] == "sent"), None)
            attempts = max((r["attempts"] for r in receipts), default=0)
            state = "sent" if sent else "failed" if attempts else "pending"
            latest = sent or max(receipts, key=lambda r: r["last_attempt"], default=None)
            imported_names = []
            for receipt in receipts:
                if receipt["state"] == "sent":
                    profile = self.connection.execute("SELECT data FROM profiles WHERE id=?", (receipt["profile"],)).fetchone()
                    if profile:
                        imported_names.append(json.loads(profile[0])["name"])
            self.connection.execute("INSERT INTO channel_submissions VALUES (?,?,?,?,?,?,?,?)",
                (alert_id, version, channel, state, attempts, latest["error"] if latest else "",
                 latest["last_attempt"] if latest else "", json.dumps(imported_names)))
            return dict(self.connection.execute("SELECT * FROM channel_submissions WHERE id=? AND version=? AND channel=?",
                                               (alert_id, version, channel)).fetchone())

    def share_submission(self, alert_id, version, channel, profiles, submission):
        """Cover a new overlapping location without repeating an earlier submission."""
        names = ", ".join(json.loads(submission["members"])) or "an earlier matching location"
        reason = f"Shared {channel} result for this alert version; earlier submission: {names}. No duplicate notification."
        with self.transaction():
            for profile in profiles:
                self.connection.execute("""UPDATE deliveries SET state=?, attempts=?, error=?, last_attempt=?, reason=?
                    WHERE id=? AND version=? AND profile=? AND channel=? AND state IN ('pending','failed')""",
                    (submission["state"], submission["attempts"], submission["error"], submission["last_attempt"], reason,
                     alert_id, version, profile.id, channel))

    def combined_receipt(self, alert_id, version, channel, profiles, error=None):
        prior = self.submission(alert_id, version, channel)
        attempts = prior["attempts"] + 1
        names = [p.name for p in profiles]
        stamp = datetime.now(timezone.utc).isoformat()
        state = "failed" if error else "sent"
        reason = "Combined notification for " + ", ".join(names) if len(names) > 1 else "Notification for " + names[0]
        with self.transaction():
            self.connection.execute("UPDATE channel_submissions SET state=?,attempts=?,error=?,last_attempt=?,members=? WHERE id=? AND version=? AND channel=?",
                (state, attempts, str(error or ""), stamp, json.dumps(names), alert_id, version, channel))
            for profile in profiles:
                self.connection.execute("""UPDATE deliveries SET state=?,attempts=?,error=?,last_attempt=?,reason=?
                    WHERE id=? AND version=? AND profile=? AND channel=?""",
                    (state, attempts, str(error or ""), stamp, reason, alert_id, version, profile.id, channel))

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

    def reconcile(self, current_ids=None, now=None):
        """Only decode changed alerts; without a snapshot, check indexed expirations."""
        now = now or datetime.now(timezone.utc)
        stamp = now.astimezone(timezone.utc).isoformat()
        changes = []
        with self.transaction():
            if current_ids is None:
                candidates = [(r["id"], "Expired") for r in self.connection.execute(
                    "SELECT id FROM alerts WHERE status='Active' AND expires_at!='' AND expires_at<=?", (stamp,))]
            else:
                candidates = []
                for row in self.connection.execute("SELECT id,expires_at FROM alerts WHERE status='Active'"):
                    status = "Expired" if row["expires_at"] and row["expires_at"] <= stamp else "No longer active" if row["id"] not in current_ids else None
                    if status:
                        candidates.append((row["id"], status))
            for alert_id, status in candidates:
                row = self.connection.execute("SELECT version,data FROM alerts WHERE id=?", (alert_id,)).fetchone()
                alert = json.loads(row["data"])
                self.connection.execute("UPDATE alerts SET status=? WHERE id=?", (status,alert_id))
                self._archive_event(alert,row["version"],status,stamp=stamp)
                changes.append((alert,status))
        return changes

    def cancel_references(self, alert):
        changed = []
        with self.transaction():
            for ref in alert.get("references", []):
                alert_id = ref.get("identifier") or ref.get("id") if isinstance(ref, dict) else ref
                row = self.connection.execute("SELECT data,version FROM alerts WHERE id=? AND status='Active'", (alert_id,)).fetchone()
                if row:
                    self.connection.execute("UPDATE alerts SET status='Cancelled' WHERE id=?", (alert_id,))
                    self._archive_event(json.loads(row["data"]), row["version"], "Cancelled")
                    changed.append((json.loads(row[0]), "Cancelled"))
        return changed

    def close(self):
        with self.lock:
            self.connection.close()
