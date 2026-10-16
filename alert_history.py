"""Durable, per-user record of alert IDs already delivered to the dashboard."""
import os
from pathlib import Path
import sqlite3


class AlertHistory:
    def __init__(self, path=None):
        if path is None:
            root = Path(os.environ.get("LOCALAPPDATA") or
                        os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
            path = root / "Stormwatch" / "processed-alerts.sqlite3"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS processed_alerts "
            "(id TEXT PRIMARY KEY, processed_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        self.connection.commit()

    def claim(self, alert_id):
        """Atomically reserve an ID before delivery, including across restarts."""
        with self.connection:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO processed_alerts (id) VALUES (?)", (alert_id,))
        return cursor.rowcount == 1

    def close(self):
        self.connection.close()
