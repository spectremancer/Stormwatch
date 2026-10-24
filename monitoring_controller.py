"""Live polling and alert processing, independent of the window constructor."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import islice, chain
import time
import sqlite3
from WeatherService import WeatherService
from alert_history import reference_ids, expiration_of
from event_catalog import CRITICAL_EVENTS as CRITICAL
from notification_explanations import decisions
from speech import issued_after
from monitoring_runtime import connection_health, defer_store_work, trim_cached_expirations


class MonitoringController:
    def poll(self):
        self.timer = None
        if not self.running or self.busy:
            return
        self.busy = True
        self.next_refresh = None
        generation = self.generation
        self.status.set("Checking National Weather Service alerts…")
        self.app.run_in_thread(self.fetch, critical=True, on_result=lambda result: self.received(generation, result),
                               on_error=lambda error: self.failed(generation, error))


    def fetch(self):
        current = {}
        warning = ""
        with self.network_lock:
            features = self.service.fetch_alerts()
            try:
                since = self.cancel_since
                features += self.service.fetch_cancellations(since - timedelta(minutes=1))
            except Exception as error:
                warning = f"Cancellation feed unavailable: {error}"
        for feature in features:
            alert = self.service.parse_alert(feature)
            if alert is not None:
                current[alert["id"]] = alert
        return current, warning


    @defer_store_work
    def received(self, generation, result):
        if not self.running or generation != self.generation:
            self.busy = False
            return
        current, warning = result
        self.busy = True
        self.profile.events = sorted(self.selected_events())
        self.coverage_warning = warning
        if not warning:
            self.cancel_since = datetime.now(timezone.utc)
        try:
            candidates = set(current)
            for alert in current.values():
                candidates.update(reference_ids(alert))
            known = self.history.known_ids(candidates)
        except sqlite3.Error as error:
            self.failed(generation, RuntimeError(f"Could not read alert history: {error}"))
            return
        state = dict(generation=generation, current=current, warning=warning, jobs=[],
                     known=known,
                     alerts=iter(sorted(current.values(), key=lambda a: a.get("message_type") == "Cancel")))
        self.process_batch(state)


    @defer_store_work
    def process_batch(self, state):
        self.processing_timer = None
        if not self.running or state["generation"] != self.generation:
            self.busy = False
            return
        batch = list(islice(state["alerts"], 20))
        batch_started = time.perf_counter()
        jobs, messages = state["jobs"], []
        existing_ids = state["known"]
        try:
            with self.history.transaction():
                for index,alert in enumerate(batch):
                    if index and time.perf_counter()-batch_started>=.008:
                        state['alerts'] = chain(batch[index:],state['alerts'])
                        state['yielded'] = True
                        break
                    self.add_event(alert["event"])
                    matched = [p for p in self.profiles if p.matches(alert)]
                    existing = alert["id"] in existing_ids
                    prior_matches = []
                    relevant_references = [ref for ref in reference_ids(alert) if ref in existing_ids]
                    if not matched:
                        for prior_id in ([alert['id']] if existing else []) + relevant_references:
                            previous = self.history.get_alert(prior_id)
                            if previous:
                                prior_matches.extend(p for p in self.profiles if p.matches(previous['alert']) and p not in prior_matches)
                    if not matched and not existing and not relevant_references:
                        continue
                    version, kind, legacy = self.history.observe(alert, locations=matched or prior_matches)
                    if (matched or prior_matches) and not self.history.displayed(alert["id"], version):
                        messages.append((alert,kind,[p.name for p in matched] or [p.name+' (previously affected)' for p in prior_matches]))
                        self.history.mark_displayed(alert["id"], version)
                    if alert.get("message_type") == "Cancel":
                        for previous, status in self.history.cancel_references(alert):
                            if any(p.matches(previous) for p in self.profiles):
                                messages.append((previous,status,[]))
                    end = expiration_of(alert)
                    expired = end and end <= datetime.now(timezone.utc)
                    speech_baseline = not issued_after(alert,self.speech_started_at)
                    for profile in matched or prior_matches:
                        quiet = legacy or (not self.initialized and alert["event"] not in CRITICAL)
                        choices = decisions(profile,alert,kind,quiet,legacy,speech_baseline=speech_baseline)
                        for channel,choice in choices.items():
                            self.history.record_decision(alert['id'],version,profile,channel,**choice)
                            enabled = profile in matched and profile.allows(alert,channel)
                            if enabled and kind not in ('Superseded','No longer active') and not (expired and alert.get('message_type') != 'Cancel') and not (channel in ('sound','speech') and (expired or kind in ('Cancelled','Expired'))):
                                channel_quiet = (legacy or speech_baseline) if channel == 'speech' else quiet
                                if channel == 'speech' and channel_quiet:
                                    self.history.suppress_delivery(alert['id'],version,profile.id,channel,choice['reason'])
                                    continue
                                if self.history.schedule(alert["id"], version, profile.id, channel, channel_quiet,choice['reason']):
                                    jobs.append((alert, version, profile.id, channel, kind))
            self.append_alerts(messages)
            yielded = state.pop('yielded',False)
            if len(batch) == 20 or yielded:
                self.processing_timer = self.app.after(1, lambda: self.process_batch(state))
                return
            changes = self.history.reconcile(set(state["current"]))
            self.append_alerts([(alert,kind,[]) for alert,kind in changes if any(p.matches(alert) for p in self.profiles)])
        except sqlite3.Error as error:
            self.failed(state["generation"], RuntimeError(f"Could not save alert history: {error}"))
            return
        self.busy = False
        self.initialized = True
        self.last_success = datetime.now(timezone.utc)
        self.last_error = ""
        self.failures = 0
        self.state.set("●  MONITORING")
        self.render_active()
        speech_jobs = [job for job in jobs if job[3] == 'speech']
        jobs = [job for job in jobs if job[3] != 'speech']
        if not self.delivery_busy and jobs:
            self.delivery_busy = True
            self.delivery_future = self.app.run_in_thread(self.send_notifications, state["generation"], jobs, critical=True,
                                   on_result=self.delivered, on_error=self.delivery_failed)
        self.enqueue_speech(state['generation'],speech_jobs)
        self.enrich_map()
        self.schedule_next()
        self.status.set(state["warning"] or "Alerts are current • Monitoring all enabled locations.")
        self.update_health()


    def failed(self, generation, error):
        self.busy = False
        if not self.running or generation != self.generation:
            return
        self.last_error = str(error)
        self.failures += 1
        self.provider_retry_after = 0
        response = getattr(error,'response',None)
        if response is not None:
            try:
                value = response.headers.get('Retry-After','0')
                try:
                    delay = int(value)
                except ValueError:
                    from email.utils import parsedate_to_datetime
                    delay = int((parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds())
                self.provider_retry_after = min(3600,max(0,delay))
            except (AttributeError,TypeError,ValueError,OverflowError):
                pass
        self.state.set("●  RETRYING")
        self.status.set(f"Unable to refresh: {error} • Saved alerts may be stale.")
        self.schedule_next()
        self.update_health()


    def schedule_next(self):
        delay = max(getattr(self,'provider_retry_after',0) if self.failures else 0,
                    min(900,self.service.interval * 2**min(max(0,self.failures-1),5)))
        self.next_refresh = datetime.now(timezone.utc) + timedelta(seconds=delay)
        self.timer = self.app.after(delay * 1000, self.poll)


    @defer_store_work
    def enrich_map(self):
        if self.app._closed or self.boundary_future is not None or not isinstance(self.service,WeatherService):
            return
        alerts = [deepcopy(a) for a in self.snapshot.values() if not a.get('geometry') and a.get('zones')]
        if not alerts:
            return
        generation = self.generation
        versions = {a['id']:self.history.get_alert(a['id'])['version'] for a in alerts}
        def done(result):
            self.boundary_future = None
            self.apply_boundaries(generation,versions,result)
        try:
            self.boundary_future = self.app.run_in_thread(self.boundaries.resolve,alerts,deepcopy(self.profiles),
                on_result=done,on_error=lambda error:done([]))
        except RuntimeError:
            pass  # Optional map context must never prevent alert delivery.


    @defer_store_work
    def apply_boundaries(self,generation,versions,result):
        if generation!=self.generation or self.app._closed:
            return
        changed=False
        with self.history.transaction():
            for alert in result:
                current=self.history.get_alert(alert['id'])
                if alert.get('geometry') and current and current['version']==versions[alert['id']] and current['status']=='Active':
                    self.history.observe(alert)
                    changed=True
        if changed:self.render_active()

    def update_health(self):
        health = connection_health(self.running,self.busy,self.last_success,self.service.interval,
                                   self.last_error,self.coverage_warning)
        self.state.set('●  '+('MONITORING' if health.state=='LIVE' else health.state))
        self.state.configure(foreground=self.app.palette[health.color])
        message = health.state+' • '+health.detail
        if self.next_refresh:
            message += f' • Next check in {max(0,int((self.next_refresh-datetime.now(timezone.utc)).total_seconds()))}s'
        self.health.set(message)
        self.health.configure(foreground=self.app.palette[health.color])
        self.overview.set_health(health.state if health.state!='STALE' else 'STALE · Last known alerts')


    @defer_store_work
    def tick(self):
        if self.app._closed:
            return
        try:
            self.prune_speech()
            self.cards.tick()
            self.overview.tick()
            if self.demo is not None:
                self.demo.tick()
            self.radar.tick()
            self.update_health()
            # An elapsed expiration can be determined locally, even while offline.
            changes = self.history.reconcile()
            if changes:
                for alert, kind in changes:
                    if any(p.matches(alert) for p in self.profiles):
                        self.append_alert(alert, kind)
            if changes or (self.snapshot and not set(self.snapshot).issubset(self.history.active_ids())):
                self.render_active()
        except sqlite3.Error as error:
            self.last_error = f'Storage unavailable: {error}'
            self.status.set(self.last_error+' · Expired visuals are still removed locally.')
            trim_cached_expirations(self)
            self.update_health()
        finally:
            self.health_timer = self.app.after(1000, self.tick)
