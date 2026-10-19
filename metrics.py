"""A read-only summary of the full history archive and monitored active types."""
from collections import Counter
from datetime import datetime, timezone
from tkinter import ttk

from TkFlow import Button, Label, Window
from TkFlow.widget import Widget
from alert_history import instant, expiration_of


def summarize(store, active, now=None):
    now = now or datetime.now(timezone.utc)
    history = store.history_metrics()
    counts = Counter()
    for _,event,expiry in active:
        end = instant(expiry)
        if end is None or end>now:
            counts[event] += 1
    rows = {row['event']:dict(row,active=counts[row['event']]) for row in history['types']}
    for event,count in counts.items():
        rows.setdefault(event,dict(event=event,alert_ids=0,changes=0,downloaded=0,active=count))
    return dict(rows=[rows[event] for event in sorted(rows)],history=history,
                active=sum(counts.values()),active_types=len(counts),at=now)


class MetricsTable(Widget):
    def __init__(self,parent):
        frame = ttk.Frame(parent.widget)
        columns = ('event','alert_ids','changes','downloaded','active')
        self.tree = ttk.Treeview(frame,columns=columns,show='headings',height=12)
        for column,title,width in zip(columns,('Event type','Historical alert IDs','Recorded changes','Downloaded changes','Active alerts'),
                                      (260,145,135,150,100)):
            self.tree.heading(column,text=title)
            self.tree.column(column,width=width,minwidth=90,anchor='w' if column=='event' else 'e')
        vertical = ttk.Scrollbar(frame,orient='vertical',command=self.tree.yview)
        horizontal = ttk.Scrollbar(frame,orient='horizontal',command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        self.tree.grid(row=0,column=0,sticky='nsew')
        vertical.grid(row=0,column=1,sticky='ns')
        horizontal.grid(row=1,column=0,sticky='ew')
        frame.rowconfigure(0,weight=1)
        frame.columnconfigure(0,weight=1)
        self._attach(parent,frame,expand=True,fill='both')


class Metrics:
    def __init__(self,owner):
        self.owner = owner
        self.future = None
        self.busy = False
        self.window = Window(owner.app,'Stormwatch · Metrics',width=960,height=620,min_width=650,min_height=460)
        self.window.root.protocol('WM_DELETE_WINDOW',self.hide)
        title = self.window.row(padding=0)
        Label(title,'Weather event metrics',style='Heading.TLabel',expand=True)
        self.refresh_button = Button(title,'Refresh',self.refresh)
        Label(self.window,'History: all saved records, including NWS downloads; History search filters do not apply.\n'
              'Active: last known alerts matching enabled locations and selected types; expired alerts excluded.',
              style='Muted.TLabel',wraplength=850)
        self.total = Label(self.window,'Loading summary…',style='Heading.TLabel',wraplength=850)
        self.table = MetricsTable(self.window)
        self.message = Label(self.window,'',style='Muted.TLabel',wraplength=850)
        Label(self.window,'Historical alert IDs are distinct NWS message IDs, not a count of storms.\n'
              'Recorded changes include updates, cancellations and expirations; downloaded changes are a subset.',
              style='Muted.TLabel',wraplength=850)
        Button(self.window,'Close',self.hide)

    def show(self):
        self.window.root.deiconify()
        self.window.root.lift()
        self.refresh()

    def hide(self):
        self.window.root.withdraw()

    def refresh(self):
        if self.busy:
            return
        # Copy only immutable fields from the same snapshot used by Active
        # alerts. All archive aggregation happens off the GUI thread.
        active = [(key,alert['event'],expiration_of(alert).isoformat() if expiration_of(alert) else '')
                  for key,alert in self.owner.snapshot.items()]
        self.owner.update_health()
        health = self.owner.health.get()
        self.busy = True
        self.refresh_button.disable()
        self.message.set('Refreshing metrics…')
        try:
            self.future = self.owner.app.run_in_thread(summarize,self.owner.history,active,
                on_result=lambda result:self.render(result,health),on_error=self.failed)
        except RuntimeError as error:
            self.failed(error)

    def render(self,result,health):
        self.busy = False
        if self.window._closed:
            return
        self.refresh_button.enable()
        self.table.tree.delete(*self.table.tree.get_children())
        for row in result['rows']:
            self.table.tree.insert('','end',values=(row['event'],row['alert_ids'],row['changes'],row['downloaded'],row['active']))
        history = result['history']
        self.total.set(f"{len(history['types'])} historical types · {history['alert_ids']:,} alert IDs · "
                       f"{history['changes']:,} changes\n{result['active_types']} active types · {result['active']:,} active alerts")
        self.message.set(f"As of {result['at'].astimezone():%Y-%m-%d %H:%M:%S} · {health}" if result['rows'] else
                         f'No saved history or matching active alerts yet. · {health}')

    def failed(self,error):
        self.busy = False
        if not self.window._closed:
            self.refresh_button.enable()
            self.message.set(f'Metrics refresh failed: {error}. Any previous summary is unchanged.')

    def wait(self):
        if self.future is not None:
            try:
                self.future.result()
            except Exception:
                pass
