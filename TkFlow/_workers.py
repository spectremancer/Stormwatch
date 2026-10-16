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
                future, function, args, kwargs = self._tasks.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if self._stopping.is_set():
                    future.cancel()
                elif future.set_running_or_notify_cancel():
                    try:
                        result = function(*args, **kwargs)
                    except BaseException as error:
                        future.set_exception(error)
                    else:
                        future.set_result(result)
            finally:
                self._tasks.task_done()

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
