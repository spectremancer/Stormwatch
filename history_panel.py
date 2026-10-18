"""Searchable alert history with complete filtered CSV export."""
from tkinter import filedialog, ttk

from TkFlow import Button, Dropdown, Label, TextArea, TextInput
from TkFlow.widget import Widget
from delivery_panel import local_time
from history_store import HistoryFilter
from history_download import HistoryDownload


class HistoryTable(Widget):
    def __init__(self, parent, selected):
        frame = ttk.Frame(parent.widget)
        columns = ('time','kind','event','locations','outcomes')
        self.tree = ttk.Treeview(frame, columns=columns, show='headings', height=8, selectmode='browse')
        for name, title, width in zip(columns, ('Recorded time','Change','Event','Locations','Channel results'),
                                       (155,110,185,140,180)):
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=70)
        v = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        h = ttk.Scrollbar(frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=v.set, xscrollcommand=h.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        v.grid(row=0, column=1, sticky='ns')
        h.grid(row=1, column=0, sticky='ew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.bind('<<TreeviewSelect>>', lambda _: selected())
        self._attach(parent, frame, expand=True, fill='both')


def outcome_label(value):
    if not value:
        return 'No notifications'
    names = {'sent':'submitted', 'failed':'failed', 'pending':'pending', 'skipped':'suppressed'}
    return '; '.join(f'{part.split(":",1)[0].title()}: {names.get(part.split(":",1)[-1], part)}'
                     for part in value.split(','))


class HistoryPanel:
    def __init__(self, parent, owner):
        self.owner, self.store = owner, owner.history
        self.filters = HistoryFilter()
        self.page = 0
        self.rows = []
        self.future = None
        self.exporting = False
        self.download_future = None
        self.downloader = None
        heading = parent.row(padding=0)
        Label(heading, 'Alert history', style='Heading.TLabel',expand=True)
        self.download_button = Button(heading, 'Download recent alerts', self.open_download)
        search = parent.row(padding=0)
        self.text = TextInput(search, expand=True)
        self.text.bind('<Return>', lambda _: self.apply())
        Button(search, 'Search', self.apply)
        Button(search, 'Clear filters', self.clear)
        categories = parent.row(padding=0, spacing=6)
        self.location = Dropdown(categories, ['All locations'], width=17, expand=True)
        self.event = Dropdown(categories, ['All event types'], editable=True, width=23, expand=True)
        self.event.bind('<Return>', lambda _: self.apply())
        self.kind = Dropdown(categories, ['All changes','New','Updated','Extended','Cancelled','Expired','No longer active'], width=17)
        dates = parent.row(padding=0, spacing=5)
        Label(dates, 'From')
        self.start = TextInput(dates, width=12)
        Label(dates, 'Through')
        self.end = TextInput(dates, width=12)
        self.outcome = Dropdown(dates, ['Any delivery result','Submitted','Failed','Pending','Suppressed','No notifications'], width=22)
        tools = parent.row(padding=0, spacing=6)
        self.counter = Label(tools, '', style='Muted.TLabel', expand=True)
        self.previous = Button(tools, 'Previous', lambda: self.change_page(-1))
        self.next = Button(tools, 'Next', lambda: self.change_page(1))
        self.export_button = Button(tools, 'Export matching CSV', self.export)
        self.table = HistoryTable(parent, self.selected)
        self.details = TextArea(parent, readonly=True, autoscroll=False, height=4, bg='#101c30', fg='#e5edf8', padx=12, pady=10)
        self.open_button = Button(parent, 'View selected alert', self.open_selected)
        self.message = Label(parent, 'Event filter accepts partial names, e.g. tornado · Dates: YYYY-MM-DD.', style='Muted.TLabel', wraplength=760)
        self.refresh()

    def apply(self):
        filters = HistoryFilter(self.text.get(), '' if self.location.get() == 'All locations' else self.location.get(),
            '' if self.event.get() == 'All event types' else self.event.get().strip(),
            '' if self.kind.get() == 'All changes' else self.kind.get(),
            '' if self.outcome.get() == 'Any delivery result' else self.outcome.get(), self.start.get().strip(), self.end.get().strip())
        try:
            filters.boundaries()
        except ValueError as error:
            self.message.set(str(error))
            return
        self.filters, self.page = filters, 0
        self.refresh()
        self.message.set('Filters applied · Export includes every matching record, across all pages.')

    def clear(self):
        self.text.set('')
        self.location.set('All locations')
        self.event.set('All event types')
        self.kind.set('All changes')
        self.outcome.set('Any delivery result')
        self.start.set('')
        self.end.set('')
        self.apply()

    def change_page(self, delta):
        self.page = max(0, self.page + delta)
        self.refresh()

    def refresh(self):
        old = self.current()
        selected_id = old['sequence'] if old else None
        locations, events = self.store.history_options()
        for control, values in ((self.location, ['All locations'] + sorted(set(locations) | {p.name for p in self.owner.profiles})),
                                (self.event, ['All event types'] + events)):
            control.values = tuple(values)
            control.configure(values=values)
        total = self.store.history_count(self.filters)
        self.page = min(self.page, max(0,(total-1)//50))
        self.rows = self.store.search_history(self.filters, offset=self.page*50)
        self.table.tree.delete(*self.table.tree.get_children())
        for i, row in enumerate(self.rows):
            self.table.tree.insert('', 'end', iid=str(i), values=(local_time(row['recorded_at']) +
                (' (imported)' if row['time_basis'] != 'Observed' else ''), row['kind'], row['event'],
                row['locations'] or 'Not recorded', outcome_label(row['outcomes'])))
            if row['sequence'] == selected_id:
                self.table.tree.selection_set(str(i))
        if not self.table.tree.selection() and self.rows:
            self.table.tree.selection_set('0')
        self.counter.set(f'{self.page*50+1 if self.rows else 0}–{self.page*50+len(self.rows)} of {total} changes')
        self.previous.disable() if self.page == 0 else self.previous.enable()
        self.next.disable() if self.page*50+50 >= total else self.next.enable()
        self.selected()

    def current(self):
        selection = self.table.tree.selection()
        if selection and int(selection[0]) < len(self.rows):
            return self.rows[int(selection[0])]
        return None

    def selected(self):
        row = self.current()
        if not row:
            self.details.set('No matching history. Adjust filters or start monitoring to record alert changes.')
            self.open_button.disable()
            return
        self.open_button.enable()
        a = row['alert']
        self.details.set(f"{row['kind']} · {a['event']} · {row['locations'] or 'Location not recorded'}\n"
            f"What changed: {row['summary'] or 'Change summary unavailable for this older record.'}\n"
            f"{a.get('headline','')}\n{a.get('area','')}\n"
            f"Time basis: {row['time_basis']} · Current alert status: {row['current_status'] or 'Unknown'}\n"
            f"Source: {row['source']}\n"
            f"{outcome_label(row['outcomes'])}\n{a.get('instruction','')}")

    def open_selected(self):
        if self.current():
            self.owner.open_alert(self.current()['alert'], self.current()['summary'])

    def export(self):
        if self.exporting:
            return
        path = filedialog.asksaveasfilename(parent=self.owner.app.root, title='Export matching alert history',
                                           defaultextension='.csv', filetypes=[('CSV files','*.csv')], initialfile='stormwatch-history.csv')
        if not path:
            return
        self.exporting = True
        self.export_button.disable()
        self.message.set('Exporting every record matching the applied filters…')
        self.future = self.owner.app.run_in_thread(self.store.export_history, path, self.filters,
                                                   on_result=self.exported, on_error=self.export_failed)

    def exported(self, count):
        self.exporting = False
        self.export_button.enable()
        self.message.set(f'Exported {count} matching records to CSV.')

    def export_failed(self, error):
        self.exporting = False
        self.export_button.enable()
        self.message.set(f'CSV export failed: {error}')

    def open_download(self):
        if self.downloader is not None and self.downloader.busy and self.downloader.window._closed:
            self.message.set('The previous download is cancelling. Wait for it to finish before starting another.')
            return
        if self.downloader is not None and not self.downloader.window._closed:
            self.downloader.window.root.lift()
            return
        self.downloader = HistoryDownload(self)

    def cancel_download(self):
        if self.downloader is not None:
            self.downloader.cancel.set()

    def close(self):
        self.cancel_download()
        for future in (self.future,self.download_future):
            if future is not None:
                try:
                    future.result()
                except Exception:
                    pass
