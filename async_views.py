"""Coalesced background queries; stale results never replace a newer UI request."""
class LatestQuery:
    def __init__(self, app, critical=False):
        self.app = app
        self.critical = critical
        self.future = None
        self.generation = 0
        self.pending = None
        self.closed = False

    def request(self, query, render, failed):
        if self.closed:
            return
        self.generation += 1
        self.pending = (self.generation,query,render,failed)
        if self.future is None:
            self._start()

    def _start(self):
        if self.closed or not self.pending:
            return
        generation,query,render,failed = self.pending
        self.pending = None
        def complete(result=None, error=None):
            self.future = None
            if self.closed:
                return
            if generation == self.generation:
                failed(error) if error else render(result)
            self._start()
        try:
            self.future = self.app.run_in_thread(query,critical=self.critical,on_result=lambda result:complete(result),
                                                 on_error=lambda error:complete(error=error))
        except RuntimeError as error:
            self.future = None
            failed(error)

    def invalidate(self):
        self.generation += 1
        self.pending = None

    def close(self):
        self.closed = True
        self.pending = None

    def wait(self):
        if self.future is not None:
            try:
                self.future.result()
            except Exception:
                pass
