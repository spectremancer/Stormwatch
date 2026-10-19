"""Optional recent NWS archive download dialog; workers never access Tk."""
import threading

from TkFlow import Button, Dropdown, Label, Window
from historical_alerts import ArchiveQuery, DownloadCancelled, download_recent
from locations import STATE_CODES
from event_catalog import WEATHER_EVENTS, CATEGORY_LABELS, event_category


EVENTS = {
    'All weather events':'',
    'Tornado watches and warnings':'Tornado Warning,Tornado Watch',
    'Hurricane watches and warnings':'Hurricane Warning,Hurricane Watch',
}
EVENTS.update({label:','.join(event for event in WEATHER_EVENTS if event_category(event)==kind)
               for kind,label in CATEGORY_LABELS.items()})


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
        Label(self.window,'Period: latest 7 days — selected automatically at download time.',
              style='Muted.TLabel',wraplength=550)
        saved = self.owner.history.setting('archive_download_options', {})
        if not isinstance(saved, dict):
            saved = {}
        area = self.window.row(padding=0)
        Label(area,'Coverage')
        states = self.owner.profile.states
        coverage = saved.get('coverage', states[0] if states else 'All US')
        if coverage not in STATE_CODES and coverage != 'All US':
            coverage = 'All US'
        self.state = Dropdown(area,['All US']+sorted(STATE_CODES),value=coverage,width=14,
                              on_change=lambda _:self.save_options())
        options = list(EVENTS) + sorted(set(WEATHER_EVENTS) | set(self.owner.profile.events))
        event = saved.get('event','All weather events')
        self.event = Dropdown(self.window,options,value=event if event in options else 'All weather events',
                              on_change=lambda _:self.save_options())
        self.message = Label(self.window,'Seven daily requests are queued automatically. Busy days split into smaller batches.',
                             style='Muted.TLabel',wraplength=550)
        tools = self.window.row(padding=0)
        self.download_button = Button(tools,'Download Latest 7 Days',self.start_download)
        self.cancel_button = Button(tools,'Cancel download',self.cancel_download)
        self.cancel_button.disable()
        self.controls = (self.state,self.event)

    def save_options(self):
        self.owner.history.save_setting('archive_download_options',
            dict(coverage=self.state.get(),event=self.event.get()))

    def start_download(self):
        if self.busy:
            return
        event = self.event.get()
        state = 'US' if self.state.get() == 'All US' else self.state.get()
        query = ArchiveQuery.latest(state,EVENTS.get(event,event))
        try:
            query.parameters()
        except ValueError as error:
            self.message.set(str(error))
            return
        self.save_options()
        self.cancel.clear()
        self.busy = True
        for control in self.controls + (self.download_button,self.panel.download_button):
            control.disable()
        self.cancel_button.enable()
        self.message.set('Downloading the latest 7 days from NWS in daily batches… Monitoring continues.')
        try:
            self.panel.download_future = self.owner.app.run_in_thread(
                download_recent,query,self.panel.store,self.owner.service.parse_alert,self.cancel,
                progress=lambda count:self.owner.app.call_soon(self.progress,count),
                on_result=self.completed,on_error=self.failed)
        except RuntimeError as error:
            self.failed(error)

    def progress(self, count):
        if not self.window._closed:
            self.message.set(f'Fetched {count:,} NWS messages. Processing the daily request queue…')

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
            message = 'NWS returned no alerts in the latest 7 days for this coverage and event selection. No records were added.'
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
