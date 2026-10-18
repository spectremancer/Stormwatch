"""Optional recent NWS archive download dialog; workers never access Tk."""
from datetime import datetime, timedelta
import threading

from TkFlow import Button, Dropdown, Label, TextInput, Window
from historical_alerts import ArchiveQuery, DownloadCancelled, download_recent
from locations import STATE_CODES


EVENTS = {
    'All watches and warnings':'',
    'Tornado watches and warnings':'Tornado Warning,Tornado Watch',
    'Hurricane watches and warnings':'Hurricane Warning,Hurricane Watch',
}


class HistoryDownload:
    def __init__(self, panel):
        self.panel, self.owner = panel, panel.owner
        self.cancel = threading.Event()
        self.busy = False
        self.window = Window(self.owner.app,'Download recent NWS alerts',width=620,height=550,
                             min_width=560,min_height=530)
        self.window.root.protocol('WM_DELETE_WINDOW',self.close)
        Label(self.window,'Download recent alerts',style='Heading.TLabel')
        Label(self.window,'Source: official NWS API · Rolling seven-day archive.\n'
              'Older dates need a different archive. The oldest available day may be partial.\n'
              'Downloads go only to History and never trigger live notifications.',
              style='Muted.TLabel',wraplength=550)
        dates = self.window.row(padding=0)
        today = datetime.now().date()
        Label(dates,'From')
        self.start = TextInput(dates,str(today-timedelta(days=1)),width=12)
        Label(dates,'Through')
        self.end = TextInput(dates,str(today),width=12)
        Label(self.window,'Dates use your local calendar: YYYY-MM-DD.',style='Muted.TLabel')
        area = self.window.row(padding=0)
        Label(area,'State / territory')
        states = self.owner.profile.states
        self.state = Dropdown(area,['Choose state']+sorted(STATE_CODES),
                              value=states[0] if states else 'Choose state',width=14)
        options = list(EVENTS) + sorted(set(self.owner.profile.events))
        self.event = Dropdown(self.window,options,value='Tornado watches and warnings')
        self.message = Label(self.window,'Choose dates, a state and event types, then download.',
                             style='Muted.TLabel',wraplength=550)
        tools = self.window.row(padding=0)
        self.download_button = Button(tools,'Download to History',self.start_download)
        self.cancel_button = Button(tools,'Cancel download',self.cancel_download)
        self.cancel_button.disable()
        self.controls = (self.start,self.end,self.state,self.event)

    def start_download(self):
        if self.busy:
            return
        event = self.event.get()
        query = ArchiveQuery(self.start.get().strip(),self.end.get().strip(),self.state.get(),EVENTS.get(event,event))
        try:
            query.parameters()
        except ValueError as error:
            self.message.set(str(error))
            return
        self.cancel.clear()
        self.busy = True
        for control in self.controls + (self.download_button,self.panel.download_button):
            control.disable()
        self.cancel_button.enable()
        self.message.set('Downloading from NWS… Monitoring continues while this runs.')
        try:
            self.panel.download_future = self.owner.app.run_in_thread(
                download_recent,query,self.panel.store,self.owner.service.parse_alert,self.cancel,
                progress=lambda count:self.owner.app.call_soon(self.progress,count),
                on_result=self.completed,on_error=self.failed)
        except RuntimeError as error:
            self.failed(error)

    def progress(self, count):
        if not self.window._closed:
            self.message.set(f'Downloaded {count:,} NWS messages. Checking remaining pages…')

    def finish(self):
        self.busy = False
        self.panel.download_button.enable()
        if not self.window._closed:
            for control in self.controls + (self.download_button,):
                control.enable()
            self.cancel_button.disable()

    def completed(self, result):
        self.finish()
        self.panel.clear()
        message = (f"Imported {result['imported']:,} changes · {result['duplicates']:,} already recorded · "
                   f"{result['skipped']:,} unsupported/test messages skipped. No live notifications sent.")
        if not result['received']:
            message = 'NWS returned no alerts for these dates, state and event types. No records were added.'
        self.panel.message.set(message)
        if not self.window._closed:
            self.message.set(message)

    def failed(self, error):
        self.finish()
        message = str(error) if isinstance(error,DownloadCancelled) else f'Download failed: {error}. No records were imported.'
        self.panel.message.set(message)
        if not self.window._closed:
            self.message.set(message)

    def cancel_download(self):
        self.cancel.set()
        if self.busy and not self.window._closed:
            self.message.set('Cancelling after the current request finishes. No partial import will be kept.')
            self.cancel_button.disable()

    def close(self):
        self.cancel_download()
        self.window.close()
