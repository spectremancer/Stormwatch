"""Consistent SQLite backups, staged restores, and explicit archive retention."""
from datetime import datetime, timedelta, timezone
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import shutil
import tempfile


def validate_backup(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('The backup failed SQLite integrity validation.')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {'alerts':{'id','version','data','status','updated'},
                    'versions':{'id','version','data','kind','displayed'},'profiles':{'id','data'},
                    'settings':{'name','data'},'deliveries':{'id','version','profile','channel','state','attempts','error'}}
        if not required.keys()<=tables:
            raise ValueError('Choose a complete Stormwatch database backup, not a CSV or another database.')
        for table,columns in required.items():
            actual = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
            if not columns<=actual:
                raise ValueError('The backup is missing required Stormwatch fields.')


def backup_database(source, target):
    source,target = Path(source).resolve(),Path(target).resolve()
    if target in (source,Path(str(source)+'-wal'),Path(str(source)+'-shm')):
        raise ValueError('Choose a backup file outside the running database and journals.')
    descriptor,temporary = tempfile.mkstemp(dir=target.parent,suffix='.sqlite3.tmp')
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as reader, closing(sqlite3.connect(temporary)) as output:
            reader.backup(output,pages=256,sleep=.02)
        validate_backup(temporary)
        os.replace(temporary,target)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()
    return str(target)


def stage_restore(database, source):
    database,source = Path(database).resolve(),Path(source).resolve()
    if source == database:
        raise ValueError('The selected file is the running database.')
    validate_backup(source)
    staged = database.with_suffix('.restore.sqlite3')
    backup_database(source,staged)
    return str(staged)


def apply_pending_restore(database):
    database = Path(database)
    staged = database.with_suffix('.restore.sqlite3')
    if not staged.exists():
        return
    validate_backup(staged)
    if database.exists():
        try:
            backup_database(database,database.with_suffix('.before-restore.sqlite3'))
        except sqlite3.DatabaseError:
            # A user-requested valid restore can recover a corrupt live database;
            # preserve the damaged bytes and journals for manual recovery too.
            damaged = database.with_suffix('.before-restore.corrupt.sqlite3')
            shutil.copy2(database,damaged)
            for suffix in ('-wal','-shm'):
                journal = Path(str(database)+suffix)
                if journal.exists():shutil.copy2(journal,Path(str(damaged)+suffix))
    for suffix in ('-wal','-shm'):
        Path(str(database)+suffix).unlink(missing_ok=True)
    os.replace(staged,database)


def prune_archive(database, days):
    if days not in (30,90,365):
        raise ValueError('Choose 30, 90, or 365 days, or retain all history.')
    cutoff = (datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
    removed = 0
    with closing(sqlite3.connect(database,timeout=2)) as db:
        while True:
            with db:
                ids = [r[0] for r in db.execute('''SELECT sequence FROM history_events WHERE recorded_at!=''
                    AND recorded_at<? AND NOT EXISTS (SELECT 1 FROM alerts a WHERE a.id=history_events.id
                    AND a.status='Active') LIMIT 250''',(cutoff,))]
                if not ids:
                    break
                placeholders = ','.join('?' for _ in ids)
                db.execute(f'DELETE FROM history_locations WHERE sequence IN ({placeholders})',ids)
                db.execute(f'DELETE FROM history_events WHERE sequence IN ({placeholders})',ids)
                removed += len(ids)
    return removed


class StorageTools:
    def __init__(self, owner):
        from TkFlow import Button, Dropdown, Label, Window
        self.owner,self.future,self.busy = owner,None,False
        self.window = Window(owner.app,'Stormwatch · Storage & backups',width=740,height=470)
        Label(self.window,'Storage, retention & backup',style='Heading.TLabel')
        Label(self.window,str(owner.history.path),wraplength=680)
        size = sum(path.stat().st_size for path in (owner.history.path,Path(str(owner.history.path)+'-wal'),
                   Path(str(owner.history.path)+'-shm')) if path.exists())
        Label(self.window,f'Database and journals: {size/1048576:.2f} MiB. Cleanup frees reusable pages; file size may not shrink.',wraplength=680)
        Label(self.window,'Backups include profiles, settings, history, and delivery receipts.\n'
              'Restores are validated and applied on next launch. Your current database is backed up first.\n'
              'Archive cleanup preserves active alerts and all version/delivery deduplication records.',wraplength=680)
        policies = ['Keep all history','30 days','90 days','365 days']
        saved = owner.history.setting('retention_policy',policies[0])
        self.retention = Dropdown(self.window,policies,value=saved if saved in policies else policies[0])
        Button(self.window,'Back up database…',self.backup)
        Button(self.window,'Restore backup on next launch…',self.restore)
        Button(self.window,'Apply archive retention…',self.prune)
        self.note = Label(self.window,'No records are removed unless you apply retention explicitly.',wraplength=680)
        Button(self.window,'Close',self.window.close)

    def run(self, function, *args):
        if self.busy:
            return
        self.busy = True
        self.note.set('Working… Live archive readers remain available.')
        def done(message):
            self.busy = False
            if not self.window._closed:
                self.note.set(str(message))
            self.owner.status.set(str(message))
            self.owner.refresh_records()
        try:
            self.future = self.owner.app.run_in_thread(function,*args,on_result=done,
                                                      on_error=lambda error:done(f'Storage operation failed: {error}'))
        except RuntimeError as error:
            done(error)

    def backup(self):
        from tkinter import filedialog
        target = filedialog.asksaveasfilename(parent=self.window.root,defaultextension='.sqlite3',
                                              initialfile='stormwatch-backup.sqlite3')
        if target:
            self.run(backup_database,self.owner.history.path,target)

    def restore(self):
        from tkinter import filedialog
        source = filedialog.askopenfilename(parent=self.window.root,filetypes=[('SQLite backup','*.sqlite3 *.db')])
        if source and self.owner.app.confirm('Replace profiles, settings, and history on next launch with this backup?\n'
                'The current database will be saved as a before-restore backup. Fully exit, then restart to apply.',title='Restore backup'):
            self.run(stage_restore,self.owner.history.path,source)

    def prune(self):
        policy = self.retention.get()
        if policy == 'Keep all history':
            self.owner.history.save_setting('retention_policy',policy)
            self.note.set('All history retained. Automatic deletion remains disabled.')
            return
        if self.owner.app.confirm('Remove inactive archive records older than '+policy+'?\n'
                'A pre-retention backup will be created. Delivery and version receipts remain.',title='Apply retention'):
            days = int(policy.split()[0])
            def work():
                backup_database(self.owner.history.path,self.owner.history.path.with_suffix('.before-retention.sqlite3'))
                count = prune_archive(self.owner.history.path,days)
                self.owner.history.save_setting('retention_policy',policy)
                return f'Removed {count:,} inactive archive records; delivery receipts preserved.'
            self.run(work)

    def wait(self):
        if self.future is not None:
            try:
                self.future.result()
            except Exception:
                pass
