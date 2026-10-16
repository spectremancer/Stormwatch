"""Persistent alert-change archive, filtering, and CSV export."""
import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile


@dataclass(frozen=True)
class HistoryFilter:
    text: str = ''
    location: str = ''
    event: str = ''
    kind: str = ''
    outcome: str = ''
    start: str = ''
    end: str = ''

    def boundaries(self):
        try:
            start = date.fromisoformat(self.start) if self.start.strip() else None
            end = date.fromisoformat(self.end) if self.end.strip() else None
        except ValueError:
            raise ValueError('Dates must use YYYY-MM-DD.') from None
        if start and end and start > end:
            raise ValueError('The start date must be on or before the end date.')
        try:
            lower = datetime.combine(start, time.min).astimezone(timezone.utc).isoformat() if start else None
            upper = datetime.combine(end + timedelta(days=1), time.min).astimezone(timezone.utc).isoformat() if end else None
        except (ValueError, OverflowError):
            raise ValueError('These dates are outside the supported local time range.') from None
        return lower, upper


def csv_cell(value):
    text = str(value or '')
    # Alerts are external text. Keep spreadsheet programs from evaluating cells.
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else text


class HistoryArchive:
    def _initialize_archive(self):
        with self.lock, self.connection:
            self.connection.executescript('''
                CREATE TABLE IF NOT EXISTS history_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL, version TEXT NOT NULL, kind TEXT NOT NULL, recorded_at TEXT NOT NULL,
                    time_basis TEXT NOT NULL, data TEXT NOT NULL, search_text TEXT NOT NULL,
                    event TEXT NOT NULL, UNIQUE(id,version,kind));
                CREATE TABLE IF NOT EXISTS history_locations (sequence INTEGER, profile TEXT, name TEXT NOT NULL,
                    PRIMARY KEY(sequence,profile));
                CREATE INDEX IF NOT EXISTS history_event_name ON history_events(event);
                CREATE INDEX IF NOT EXISTS history_change ON history_events(kind);
                CREATE INDEX IF NOT EXISTS history_time ON history_events(recorded_at);
                CREATE INDEX IF NOT EXISTS history_location_name ON history_locations(name);
            ''')
            marker = self.connection.execute("SELECT data FROM settings WHERE name='archive_initialized'").fetchone()
            if not marker:
                for row in self.connection.execute('SELECT * FROM versions').fetchall():
                    alert = json.loads(row['data'])
                    profiles = self.connection.execute('''SELECT DISTINCT p.id,p.data FROM profiles p JOIN deliveries d
                        ON p.id=d.profile WHERE d.id=? AND d.version=?''', (row['id'],row['version'])).fetchall()
                    places = [dict(id=p['id'], name=json.loads(p['data'])['name']) for p in profiles]
                    stamp = ''
                    try:
                        issued = datetime.fromisoformat(alert.get('sent','').replace('Z','+00:00'))
                        if issued.tzinfo is not None:
                            stamp = issued.astimezone(timezone.utc).isoformat()
                    except (ValueError, AttributeError):
                        pass
                    self._archive_event(alert, row['version'], row['kind'], places, stamp,
                                        'Issued (imported)' if stamp else 'Unknown (imported)')
                self.connection.execute("INSERT OR REPLACE INTO settings VALUES ('archive_initialized','true')")

    def _archive_event(self, alert, version, kind, locations=None, stamp=None, basis='Observed'):
        if stamp is None:
            stamp = datetime.now(timezone.utc).isoformat()
        existing = self.connection.execute('SELECT sequence FROM history_events WHERE id=? AND version=? AND kind=?',
                                           (alert['id'],version,kind)).fetchone()
        if existing:
            sequence = existing[0]
        else:
            cursor = self.connection.execute('''INSERT INTO history_events
                (id,version,kind,recorded_at,time_basis,data,search_text,event) VALUES (?,?,?,?,?,?,?,?)''',
                (alert['id'], version, kind, stamp, basis, json.dumps(alert),
                 ' '.join(str(alert.get(k,'')) for k in ('event','headline','area','description','instruction')).casefold(), alert['event']))
            sequence = cursor.lastrowid
        if locations is None:
            inherited = self.connection.execute('''SELECT h.profile,h.name FROM history_locations h
                JOIN history_events e ON e.sequence=h.sequence WHERE e.id=? AND e.version=? ORDER BY e.sequence''',
                (alert['id'],version)).fetchall()
            locations = [dict(r) for r in inherited]
        for profile in locations:
            profile_id = profile['id'] if isinstance(profile, dict) and 'id' in profile else profile['profile'] if isinstance(profile, dict) else profile.id
            name = profile['name'] if isinstance(profile, dict) else profile.name
            self.connection.execute('INSERT OR IGNORE INTO history_locations VALUES (?,?,?)', (sequence,profile_id,name))
        return sequence

    @staticmethod
    def _archive_where(filters, before=None):
        lower, upper = filters.boundaries()
        clauses, values = [], []
        for word in filters.text.strip().casefold().split():
            literal = word.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            clauses.append("e.search_text LIKE ? ESCAPE '\\'")
            values.append('%'+literal+'%')
        if filters.location:
            clauses.append('EXISTS (SELECT 1 FROM history_locations l WHERE l.sequence=e.sequence AND l.name=?)')
            values.append(filters.location)
        if filters.event:
            clauses.append('e.event=?')
            values.append(filters.event)
        if filters.kind:
            clauses.append('e.kind=?')
            values.append(filters.kind)
        if filters.outcome:
            states = {'Submitted':'sent', 'Failed':'failed', 'Pending':'pending', 'Suppressed':'skipped'}
            if filters.outcome == 'No notifications':
                clauses.append('NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.id=e.id AND d.version=e.version)')
            elif filters.outcome in states:
                clauses.append('EXISTS (SELECT 1 FROM deliveries d WHERE d.id=e.id AND d.version=e.version AND d.state=?)')
                values.append(states[filters.outcome])
            else:
                raise ValueError('Unknown delivery outcome.')
        for operator, stamp in (('>=',lower), ('<',upper)):
            if stamp:
                clauses.append(f"e.recorded_at!='' AND e.recorded_at {operator} ?")
                values.append(stamp)
        if before is not None:
            clauses.append('e.sequence<?')
            values.append(before)
        return (' WHERE ' + ' AND '.join(clauses) if clauses else ''), values

    def history_count(self, filters=HistoryFilter()):
        where, values = self._archive_where(filters)
        with self.lock:
            return self.connection.execute('SELECT count(*) FROM history_events e'+where, values).fetchone()[0]

    def _history_sql(self, filters, before=None):
        where, values = self._archive_where(filters, before)
        return ("""SELECT e.*,a.status AS current_status,
                (SELECT group_concat(DISTINCT l.name) FROM history_locations l WHERE l.sequence=e.sequence) AS locations,
                (SELECT group_concat(DISTINCT d.channel||':'||d.state) FROM deliveries d WHERE d.id=e.id AND d.version=e.version) AS outcomes
                FROM history_events e LEFT JOIN alerts a ON a.id=e.id""" + where + ' ORDER BY e.sequence DESC', values)

    def search_history(self, filters=HistoryFilter(), limit=50, offset=0, before=None):
        sql, values = self._history_sql(filters, before)
        with self.lock:
            rows = self.connection.execute(sql + ' LIMIT ? OFFSET ?', (*values, limit, offset)).fetchall()
            return [dict(r, alert=json.loads(r['data'])) for r in rows]

    def history_options(self):
        with self.lock:
            return ([r[0] for r in self.connection.execute('SELECT DISTINCT name FROM history_locations ORDER BY name')],
                    [r[0] for r in self.connection.execute('SELECT DISTINCT event FROM history_events ORDER BY event')])

    def export_history(self, path, filters=HistoryFilter()):
        sql, values = self._history_sql(filters)
        target = Path(path).resolve()
        database = self.path.resolve()
        if target in (database, Path(str(database)+'-wal'), Path(str(database)+'-shm')):
            raise ValueError('Choose a CSV file outside the application database.')
        count = 0
        temporary = None
        # A separate read transaction provides a consistent export, including
        # receipt outcomes, while WAL allows live monitoring to keep writing.
        reader = sqlite3.connect(self.path)
        reader.row_factory = sqlite3.Row
        try:
            reader.execute('BEGIN')
            cursor = reader.execute(sql, values)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8-sig', newline='',
                                             dir=target.parent, suffix='.csv.tmp', delete=False) as output:
                temporary = Path(output.name)
                writer = csv.writer(output)
                writer.writerow(('alert_id','version','change','recorded_at_utc','time_basis','event','locations','area',
                                 'severity','issued_at','expires_at','current_status','channel_results','headline','instruction','url'))
                while True:
                    rows = cursor.fetchmany(250)
                    if not rows:
                        break
                    for row in rows:
                        a = json.loads(row['data'])
                        writer.writerow(csv_cell(v) for v in (row['id'],row['version'],row['kind'],row['recorded_at'],
                            row['time_basis'],a['event'],row['locations'],a.get('area'),a.get('severity'),a.get('sent'),
                            a.get('ends') or a.get('expires'),row['current_status'],row['outcomes'],a.get('headline'),a.get('instruction'),a.get('url')))
                        count += 1
            os.replace(temporary, target)
            return count
        finally:
            reader.close()
            if temporary and temporary.exists():
                temporary.unlink()
