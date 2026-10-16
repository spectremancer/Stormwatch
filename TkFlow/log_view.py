"""Bounded thread-safe GUI logging without redirecting global stdout."""
from __future__ import annotations
import logging
import queue
import threading
from typing import Any
from .text_area import TextArea
from ._helpers import _positive


class GuiLogHandler(logging.Handler):
    """Queue formatted records for a LogView; never access Tk in emit()."""

    def __init__(self, view):
        super().__init__()
        self.view = view

    def emit(self, record):
        try:
            self.view.write(self.format(record) + "\n")
        except Exception:
            self.handleError(record)


class LogView(TextArea):
    """Readonly scrolling output with bounded queued chunks and retained lines."""

    def __init__(self, parent, *, max_lines=2000, max_pending=1000,
                 poll_ms=40, batch_size=100, max_message_chars=16000, **options):
        for name, value in (("max_pending", max_pending), ("poll_ms", poll_ms), ("batch_size", batch_size), ("max_message_chars", max_message_chars)):
            _positive(value, name)
        options.pop("readonly", None)
        super().__init__(parent, readonly=True, max_lines=max_lines, **options)
        self._buffer_lock = threading.Lock()
        self._max_message_chars = max_message_chars
        self._messages = queue.Queue(maxsize=max_pending)
        self._poll_ms = poll_ms
        self._batch_size = batch_size
        self._accepting = True
        self._dropped = 0
        self._handlers = []
        self._timer = self.app.after(poll_ms, self._flush)

    @property
    def dropped_messages(self) -> int:
        with self._buffer_lock:
            return self._dropped

    def write(self, text: str) -> None:
        """Thread-safe nonblocking enqueue. Drop newest chunks when the queue is full."""
        text = str(text)
        if len(text) > self._max_message_chars:
            text = text[:self._max_message_chars] + "… [truncated]\n"
        with self._buffer_lock:
            if self._accepting and not self.app._closed:
                try:
                    self._messages.put_nowait(text)
                except queue.Full:
                    self._dropped += 1

    def clear(self):
        self._check()
        with self._buffer_lock:
            while True:
                try:
                    self._messages.get_nowait()
                except queue.Empty:
                    break
        return super().clear()

    def print(self, *values: Any, sep: str = " ", end: str = "\n") -> None:
        self.write(sep.join(str(value) for value in values) + end)

    def attach_logger(self, logger: logging.Logger, *, level=logging.INFO,
                      format="%(asctime)s %(levelname)s %(message)s") -> GuiLogHandler:
        """Attach a handler; configure logger.level yourself to avoid global changes."""
        self._check()
        handler = GuiLogHandler(self)
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(format))
        logger.addHandler(handler)
        self._handlers.append((logger, handler))
        return handler

    def _flush(self):
        if self._destroyed or self.app._closed:
            return
        chunks = []
        for _ in range(self._batch_size):
            try:
                chunks.append(self._messages.get_nowait())
            except queue.Empty:
                break
        if chunks:
            self.append("".join(chunks))
        self._timer = self.app.after(self._poll_ms, self._flush)

    def _dispose(self):
        with self._buffer_lock:
            self._accepting = False
        self.app.root.after_cancel(self._timer)
        for logger, handler in self._handlers:
            logger.removeHandler(handler)
            handler.close()
        self._handlers.clear()
        super()._dispose()
