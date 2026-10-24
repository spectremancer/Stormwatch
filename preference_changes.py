"""Merge notification edits without overwriting newer geography/event selections."""
from dataclasses import replace
from notification_rules import RULE_FIELDS

NOTIFICATION_FIELDS = RULE_FIELDS+('sound','desktop','speech','sound_events','speech_events','speech_max_areas','speech_max_chars')


class PreferenceChanges:
    def __init__(self,store,app):
        self.store,self.app=store,app
        self.pending={}
        self.futures=[]

    def write(self, candidate):
        with self.store.transaction():
            current=next((p for p in self.store.profiles() if p.id==candidate.id),None)
            if current is None:raise ValueError('The saved location was removed.')
            if self.pending.get(candidate.id) is not candidate:return current
            updated=replace(current,**{name:getattr(candidate,name) for name in NOTIFICATION_FIELDS})
            self.store.save_profile(updated)
            return updated

    def save(self,candidate,done,failed):
        self.pending[candidate.id]=candidate
        self.futures[:] = [future for future in self.futures if not future.done()]
        def complete(profile):
            if self.pending.get(candidate.id) is candidate:self.pending.pop(candidate.id,None)
            done(profile)
        if self.store.lock.acquire(blocking=False):
            try:
                profile=self.write(candidate)
            except Exception as error:
                failed(error)
            else:complete(profile)
            finally:self.store.lock.release()
            return
        try:
            self.futures.append(self.app.run_in_thread(self.write,candidate,on_result=complete,on_error=failed))
        except RuntimeError as error:failed(error)

    def wait(self):
        for future in self.futures:
            try:future.result()
            except Exception:pass
        errors=[]
        # Explicit saves queued behind an import must survive closing the app,
        # even if the pool cancelled a job that had not started yet.
        for candidate in list(self.pending.values()):
            try:self.write(candidate)
            except Exception as error:errors.append(str(error))
        self.pending.clear()
        return errors
