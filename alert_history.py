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
from alert_changes import summarize_change
from application_paths import state_directory


def instant(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def expiration_of(alert):
    """Use the first known CAP message expiry or hazard end."""
    values = [end for key in ('ends','expires') if (end := instant(alert.get(key))) is not None]
    return min(values) if values else None


def version_of(alert):
    # Deliberately ignore fetch time, map geometry enrichment, and profile names.
    fields = ("event", "headline", "area", "severity", "urgency", "sent", "expires",
              "ends", "instruction", "description", "message_type", "references", "geocode", "zones")
    payload = {key: alert.get(key) for key in fields}
    payload["geometry"] = alert.get("geometry") if alert.get("geometry_source") != "NWS affected zones" else None
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def reference_ids(alert):
    return [ref.get('identifier') or ref.get('id') if isinstance(ref,dict) else ref
            for ref in alert.get('references',[]) if ref]


class AlertHistory(HistoryArchive):
    def __init__(self, path=None):
        if path is None:
            path = state_directory() / "processed-alerts.sqlite3"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._transaction_depth = 0
        self.revision = 0
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        try:
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
                CREATE TABLE IF NOT EXISTS notification_decisions (id TEXT, version TEXT, profile TEXT, channel TEXT,
                    location_name TEXT, allowed INTEGER, reason TEXT, recorded_at TEXT,
                    PRIMARY KEY(id,version,profile,channel));
            ''')
            alert_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(alerts)")}
            if "expires_at" not in alert_columns:
                self.connection.execute("ALTER TABLE alerts ADD COLUMN expires_at TEXT NOT NULL DEFAULT ''")
            if not self.connection.execute("SELECT 1 FROM settings WHERE name='expiry_basis_v2'").fetchone():
                for row in self.connection.execute("SELECT id,data,expires_at FROM alerts").fetchall():
                    alert = json.loads(row["data"])
                    end = expiration_of(alert)
                    stamp = end.isoformat() if end else ''
                    if stamp != row['expires_at']:
                        self.connection.execute("UPDATE alerts SET expires_at=? WHERE id=?", (stamp,row['id']))
                self.connection.execute("INSERT INTO settings VALUES ('expiry_basis_v2','true')")
            self.connection.execute("CREATE INDEX IF NOT EXISTS active_alert_expiry ON alerts(status,expires_at)")
            self.connection.execute("CREATE INDEX IF NOT EXISTS active_alert_updated ON alerts(status,updated DESC)")
            if 'summary' not in {row[1] for row in self.connection.execute('PRAGMA table_info(versions)')}:
                self.connection.execute("ALTER TABLE versions ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
            columns = {row[1] for row in self.connection.execute("PRAGMA table_info(deliveries)")}
            for name in ("scheduled_at", "last_attempt", "reason"):
                if name not in columns:
                    self.connection.execute(f"ALTER TABLE deliveries ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            self.connection.commit()
            self._initialize_archive()
        except BaseException:
            self.connection.close()
            raise

    @contextmanager
    def transaction(self):
        """Nested operations share one atomic commit per short processing batch."""
        with self.lock:
            outer = self._transaction_depth == 0
            before = self.connection.total_changes if outer else None
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
                        if self.connection.total_changes != before:
                            self.revision += 1
                    except BaseException:
                        self.connection.rollback()
                        raise
            finally:
                self._transaction_depth -= 1

    @contextmanager
    def read_snapshot(self):
        """Independent WAL reader; imports never hold this reader's Python lock."""
        reader = object.__new__(type(self))
        reader.path = self.path
        reader.lock = threading.RLock()
        reader._transaction_depth = 0
        reader.revision = self.revision
        reader.connection = sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
        reader.connection.row_factory = sqlite3.Row
        try:
            reader.connection.execute('BEGIN')
            reader.fts_enabled = getattr(self,'fts_enabled',False)
            yield reader
        finally:
            reader.connection.close()

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

    def update_profile_events(self, profile_id, events):
        """Event edits never replace independently saved channel/geography fields."""
        payload=json.dumps(sorted(set(events)))
        with self.transaction():
            self.connection.execute("""UPDATE profiles SET data=json_set(data,'$.events',json(?))
                WHERE id=? AND json_extract(data,'$.events') IS NOT json(?)""",(payload,profile_id,payload))

    def delete_profile(self, profile_id):
        with self.transaction():
            self.connection.execute("DELETE FROM profiles WHERE id=?", (profile_id,))

    def observe(self, alert, now=None, locations=None):
        now = now or datetime.now(timezone.utc)
        version = version_of(alert)
        data = json.dumps(alert)
        with self.transaction():
            old = self.connection.execute("SELECT * FROM alerts WHERE id=?", (alert["id"],)).fetchone()
            if old and old['status'] in ('Cancelled','Superseded','Expired') and (
                    old['version']==version or self.connection.execute(
                        'SELECT 1 FROM versions WHERE id=? AND version=?',(alert['id'],version)).fetchone()):
                return version,old['status'],False
            reference_old = None
            for ref in alert.get("references", []):
                reference_id = ref.get("identifier") or ref.get("id") if isinstance(ref, dict) else ref
                referenced = self.connection.execute("SELECT * FROM alerts WHERE id=?", (reference_id,)).fetchone()
                if referenced and reference_old is None:
                    reference_old = referenced
                if referenced and alert.get("message_type", "").lower() == "update":
                    self.connection.execute("UPDATE alerts SET status='Superseded' WHERE id=?", (reference_id,))
            end = expiration_of(alert)
            cancelled = alert.get("message_type", "").lower() == "cancel"
            status = "Cancelled" if cancelled else "Expired" if end and end <= now else "Active"
            if old and old["version"] == version:
                prior_version = self.connection.execute("SELECT kind,summary FROM versions WHERE id=? AND version=?", (alert["id"],version)).fetchone()
                kind = prior_version['kind']
                if old["data"] != data or old["status"] != status:
                    self.connection.execute("UPDATE alerts SET data=?,status=?,updated=?,expires_at=? WHERE id=?",
                        (data,status,now.isoformat(),end.isoformat() if end else "",alert["id"]))
                self._archive_event(alert, version, kind, locations, summary=prior_version['summary'])
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
            summary = summarize_change(json.loads(previous['data']) if previous else None, alert, kind)
            self.connection.execute("INSERT OR REPLACE INTO alerts (id,version,data,status,updated,expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                                    (alert["id"], version, data, status, now.isoformat(), end.isoformat() if end else ""))
            self.connection.execute("INSERT OR IGNORE INTO versions (id, version, kind, data, summary) VALUES (?, ?, ?, ?, ?)",
                                    (alert["id"], version, kind, data, summary))
            stored = self.connection.execute("SELECT kind,summary FROM versions WHERE id=? AND version=?", (alert["id"], version)).fetchone()
            kind = stored['kind']
            self._archive_event(alert, version, kind, locations, now.astimezone(timezone.utc).isoformat(), summary=stored['summary'])
            # Migrate ID-only history as a quiet baseline. Later versions notify.
            legacy = old is None and self.connection.execute("SELECT 1 FROM processed_alerts WHERE id=?", (alert["id"],)).fetchone()
            if legacy:
                self.connection.execute("UPDATE versions SET displayed=1 WHERE id=? AND version=?", (alert["id"], version))
            return version, kind, bool(legacy)

    def displayed(self, alert_id, version):
        with self.lock:
            return bool(self.connection.execute("SELECT displayed FROM versions WHERE id=? AND version=?", (alert_id, version)).fetchone()[0])

    def change_summary(self, alert, kind=None):
        if kind in ('Cancelled', 'Expired', 'No longer active'):
            return summarize_change(None, alert, kind)
        with self.lock:
            row = self.connection.execute('SELECT summary FROM versions WHERE id=? AND version=?',
                                          (alert['id'],version_of(alert))).fetchone()
            return row['summary'] if row else ''

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

    def record_decision(self, alert_id, version, profile, channel, allowed, reason):
        """Freeze submitted/quiet decisions; update unsent decisions only when rules change."""
        with self.transaction():
            self.connection.execute('''INSERT INTO notification_decisions VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(id,version,profile,channel) DO UPDATE SET location_name=excluded.location_name,
                allowed=excluded.allowed,reason=excluded.reason,recorded_at=excluded.recorded_at
                WHERE (notification_decisions.reason!=excluded.reason OR notification_decisions.allowed!=excluded.allowed
                    OR notification_decisions.location_name!=excluded.location_name)
                AND NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.id=excluded.id AND d.version=excluded.version
                    AND d.profile=excluded.profile AND d.channel=excluded.channel AND d.state IN ('sent','skipped'))''',
                (alert_id,version,profile.id,channel,profile.name,int(allowed),reason,datetime.now(timezone.utc).isoformat()))

    def suppress_delivery(self, alert_id, version, profile, channel, reason):
        """Retire old pending/failed work while preserving successful deliveries."""
        with self.transaction():
            self.schedule(alert_id,version,profile,channel,quiet=True,reason=reason)
            self.connection.execute('''UPDATE deliveries SET state='skipped',reason=?
                WHERE id=? AND version=? AND profile=? AND channel=? AND state IN ('pending','failed')''',
                (reason,alert_id,version,profile,channel))

    def decision_rows(self, alert_id, version):
        with self.lock:
            return [dict(row) for row in self.connection.execute('''SELECT * FROM notification_decisions
                WHERE id=? AND version=? ORDER BY location_name,channel''',(alert_id,version))]

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

    def is_active(self, alert_id, version, now=None):
        stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        with self.lock:
            return self.connection.execute("""SELECT 1 FROM alerts WHERE id=? AND version=?
                AND status='Active' AND (expires_at='' OR expires_at>?)""",(alert_id,version,stamp)).fetchone() is not None

    def active_ids(self):
        with self.lock:
            return {row[0] for row in self.connection.execute("""SELECT id FROM alerts WHERE status='Active'
                AND (expires_at='' OR expires_at>?)""",(datetime.now(timezone.utc).isoformat(),))}

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
                p.data AS profile_data, a.status AS alert_status, a.version AS current_version,
                n.reason AS decision_reason, n.recorded_at AS decision_at
                FROM deliveries d LEFT JOIN versions v ON d.id=v.id AND d.version=v.version
                LEFT JOIN profiles p ON d.profile=p.id LEFT JOIN alerts a ON d.id=a.id
                LEFT JOIN notification_decisions n ON n.id=d.id AND n.version=d.version AND n.profile=d.profile AND n.channel=d.channel""" +
                where + " ORDER BY d.rowid DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            return [dict(row, alert=json.loads(row["alert_data"]) if row["alert_data"] else {},
                         location=json.loads(row["profile_data"]) if row["profile_data"] else {}) for row in rows]

    def rows(self, active_only=False):
        with self.lock:
            sql = "SELECT alerts.*, (SELECT summary FROM versions v WHERE v.id=alerts.id AND v.version=alerts.version) AS summary FROM alerts" + (" WHERE status='Active' AND (expires_at='' OR expires_at>?)" if active_only else "") + " ORDER BY updated DESC"
            values = (datetime.now(timezone.utc).isoformat(),) if active_only else ()
            return [dict(row, alert=json.loads(row["data"])) for row in self.connection.execute(sql,values)]

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
                self._archive_event(alert,row["version"],status,stamp=stamp,summary=summarize_change(None,alert,status))
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
                    self._archive_event(json.loads(row["data"]), row["version"], "Cancelled", summary=summarize_change(None,alert,'Cancelled'))
                    changed.append((json.loads(row[0]), "Cancelled"))
        return changed

    def close(self):
        with self.lock:
            self.connection.close()
