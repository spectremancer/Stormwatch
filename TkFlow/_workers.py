"""A bounded daemon worker pool; submission never blocks the GUI thread."""
from concurrent.futures import Future
import queue
import threading


class WorkerPool:
    def __init__(self, max_workers, max_pending):
        self._limit = max_workers
        self._tasks = queue.Queue(maxsize=max_pending)
        self._threads = []
        self._lock = threading.Lock()
        self._stopping = threading.Event()

    def submit(self, function, *args, **kwargs):
        future = Future()
        with self._lock:
            if self._stopping.is_set():
                raise RuntimeError("The worker pool is closed")
            try:
                self._tasks.put_nowait((future, function, args, kwargs))
            except queue.Full:
                raise RuntimeError("Background queue is full; try again when work finishes") from None
            if len(self._threads) < self._limit:
                worker = threading.Thread(target=self._work, name="TkFlow-worker", daemon=True)
                self._threads.append(worker)
                worker.start()
        return future

    def _work(self):
        while not self._stopping.is_set():
            try:
                task = self._tasks.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._run_task(task)
            finally:
                # Do not keep the last job's bound GUI owner/result alive
                # while this worker waits for another job or shuts down.
                del task
                self._tasks.task_done()

    def _run_task(self, task):
        future, function, args, kwargs = task
        if self._stopping.is_set():
            future.cancel()
        elif future.set_running_or_notify_cancel():
            try:
                result = function(*args, **kwargs)
            except BaseException as error:
                future.set_exception(error)
            else:
                future.set_result(result)

    def shutdown(self):
        with self._lock:
            self._stopping.set()
            while True:
                try:
                    future, *_ = self._tasks.get_nowait()
                except queue.Empty:
                    break
                future.cancel()
                self._tasks.task_done()
