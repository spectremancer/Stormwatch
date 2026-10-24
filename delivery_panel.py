"""User-facing, channel-specific notification submission results."""
from datetime import datetime
from tkinter import ttk

from TkFlow import Button, Checkbox, Label, TextArea
from TkFlow.widget import Widget
from locations import LocationProfile
from async_views import LatestQuery


def delivery_status(row, running=True, automatic=True):
    state = row['state']
    if state == 'sent':
        return 'Submitted'
    if state == 'skipped':
        return 'Suppressed'
    if state == 'failed' and row['attempts'] >= 3:
        return 'Failed · retries exhausted'
    profile = row.get('location', {})
    if not profile or not profile.get('enabled', True) or not LocationProfile(**profile).allows(row.get('alert', {}), row['channel']):
        return 'Paused by preferences'
    if row.get('current_version') != row['version'] or row.get('alert_status') not in ('Active', 'Cancelled'):
        return 'No longer current'
    if row['channel'] in ('sound','speech') and row.get('alert_status') != 'Active':
        return 'No longer current'
    if not running:
        return 'Failed · paused' if state == 'failed' else 'Waiting · paused'
    return ('Failed · retry on refresh' if automatic else 'Failed · manual retry') if state == 'failed' else 'Pending'


def local_time(value):
    try:
        return datetime.fromisoformat(value).astimezone().strftime('%b %d %H:%M:%S')
    except (ValueError, TypeError):
        return 'Not recorded'


class DeliveryTable(Widget):
    def __init__(self, parent, selected):
        frame = ttk.Frame(parent.widget)
        columns = ('event', 'location', 'channel', 'status', 'attempts')
        self.tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse', height=10)
        for col, title, width in zip(columns, ('Alert', 'Location', 'Channel', 'Result', 'Attempts'), (190, 110, 75, 185, 65)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, minwidth=50, stretch=col != 'attempts')
        vertical = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.bind('<<TreeviewSelect>>', lambda _: selected())
        self._attach(parent, frame, expand=True, fill='both')


class DeliveryPanel:
    def __init__(self, parent, store, retry, running=lambda: True, title='Notification delivery', automatic=True, compact=False):
        self.store, self.retry, self.running = store, retry, running
        self.query = LatestQuery(parent.app)
        self.automatic = automatic
        self.rows = []
        self.page = 0
        self.row_map = {}
        if not compact:
            Label(parent, title, style='Heading.TLabel')
            Label(parent, 'Sound, desktop and speech results are independent. Submitted means accepted/completed locally;\n'
                  'it does not confirm that you heard or saw the notification.', style='Muted.TLabel', wraplength=760)
        actions = parent.row(padding=0)
        self.failed_only = Checkbox(actions, 'Failed only', command=lambda _: self.filter_changed())
        Button(actions, 'Refresh', self.refresh)
        self.previous = Button(actions, 'Previous', lambda: self.change_page(-1))
        self.next = Button(actions, 'Next', lambda: self.change_page(1))
        self.counter = Label(parent, '', style='Muted.TLabel')
        if compact:
            self.counter.hide()
        self.table = DeliveryTable(parent, self.selected)
        self.details = TextArea(parent, readonly=True, autoscroll=False, height=2 if compact else 7, bg='#101c30', fg='#e5edf8', padx=12, pady=10)
        self.retry_button = Button(actions if compact else parent,
                                   'Retry channel once' if compact else 'Retry selected failed channel once', self.retry_selected)
        self.refresh()

    @staticmethod
    def key(row):
        return (row['id'], row['version'], row['profile'], row['channel'])

    def filter_changed(self):
        self.page = 0
        self.refresh()

    def change_page(self, delta):
        self.page = max(0, self.page + delta)
        self.refresh()

    def refresh(self):
        current = self.current()
        selected_key = self.key(current) if current else None
        page, failed = self.page, self.failed_only.get()
        def query():
            with self.store.read_snapshot() as reader:
                total = reader.delivery_count(failed)
                current = min(page,max(0,(total-1)//50))
                return total,current,reader.delivery_rows(offset=current*50,failed_only=failed)
        self.query.request(query,lambda result:self.render(result,selected_key),
                           lambda error:self.details.set(f'Delivery search failed: {error}'))

    def render(self, result, selected_key):
        if self.query.app._closed or self.table._destroyed:
            return
        total,self.page,self.rows = result
        self.table.tree.delete(*self.table.tree.get_children())
        self.row_map = {}
        for i, row in enumerate(self.rows):
            iid = str(i)
            self.row_map[iid] = row
            self.table.tree.insert('', 'end', iid=iid, values=(row['alert'].get('event', row['id']),
                row['location'].get('name', 'Removed location'), row['channel'].title(),
                delivery_status(row, self.running(), self.automatic), row['attempts']))
            if self.key(row) == selected_key:
                self.table.tree.selection_set(iid)
        if not self.table.tree.selection() and self.rows:
            self.table.tree.selection_set('0')
        start = self.page * 50
        self.counter.set(f'{start + 1 if self.rows else 0}–{start + len(self.rows)} of {total} channel records')
        self.previous.disable() if self.page == 0 else self.previous.enable()
        self.next.disable() if start + 50 >= total else self.next.enable()
        self.selected()

    def current(self):
        selection = self.table.tree.selection()
        return self.row_map.get(selection[0]) if selection else None

    def selected(self):
        row = self.current()
        if row is None:
            self.details.set('No delivery records yet. Start monitoring, or open Demo to try simulated alerts.')
            self.retry_button.disable()
            return
        self.retry_button.enable() if row['state'] == 'failed' else self.retry_button.disable()
        self.details.set(f"{row['alert'].get('headline', row['id'])}\n"
            f"{row['location'].get('name', 'Removed location')} · {row['channel'].title()} · {delivery_status(row, self.running(), self.automatic)}\n"
            f"Alert version: {row['version'][:12]} · Feed: {'logged' if row.get('displayed') else 'not logged'}\n"
            f"Scheduled: {local_time(row.get('scheduled_at'))} · Last attempt: {local_time(row.get('last_attempt'))}\n"
            f"Shared channel attempts: {row['attempts']} (automatic limit: 3; manual retry adds one attempt)\n"
            f"Why this notification: {row.get('decision_reason') or 'No decision recorded for this older or simulated alert.'}\n"
            f"{'Speech waits in its own bounded queue and rechecks current rules, freshness, and expiration before speaking.' if row['channel'] == 'speech' else ''}\n"
            f"{row.get('reason') or ''}\n{('Last error: ' + row['error']) if row.get('error') else 'No reported error.'}")

    def retry_selected(self):
        row = self.current()
        if row and row['state'] == 'failed':
            self.retry(row)
