"""Reusable command policies for buttons, menus, and other GUI callbacks."""
from __future__ import annotations

from concurrent.futures import Future
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .app import App
from ._helpers import _callback


class Command:
    """Capture inputs on the GUI thread, run work in the pool, deliver results safely.

    prepare(*event_args) must return a tuple of positional worker arguments.
    Duplicate invocations share the current Future while work is pending.
    """

    def __init__(self, app: App, function: Callable, *, prepare: Callable | None = None,
                 background: bool = True, on_result: Callable | None = None,
                 on_error: Callable | None = None, on_done: Callable | None = None) -> None:
        for name, callback in (("function", function), ("prepare", prepare),
                               ("on_result", on_result), ("on_error", on_error), ("on_done", on_done)):
            _callback(callback, name)
        if function is None:
            raise TypeError("function must be callable")
        self.app = app
        self.function = function
        self.prepare = prepare
        self.background = background
        self.on_result = on_result
        self.on_error = on_error
        self.on_done = on_done
        self.future: Future | None = None
        self.running = False

    def __call__(self, *args: Any) -> Any:
        self.app._check_thread()
        if self.app._closed:
            raise RuntimeError("Cannot invoke a command after the app has closed")
        if self.running:
            return self.future
        self.running = True
        try:
            if self.prepare is not None:
                args = self.prepare(*args)
                if not isinstance(args, tuple):
                    raise TypeError("prepare must return a tuple of worker arguments")
            if self.background:
                self.future = self.app.run_in_thread(self.function, *args,
                                                    on_result=self._success, on_error=self._failure)
                self.future.add_done_callback(self._cancelled)
                return self.future
            result = self.function(*args)
        except Exception as error:
            self._failure(error)
            return None
        self._success(result)
        return result

    def _finish(self) -> None:
        self.running = False
        if self.on_done is not None:
            self.on_done()

    def _success(self, result: Any) -> None:
        try:
            if self.on_result is not None:
                self.on_result(result)
        finally:
            self._finish()

    def _failure(self, error: BaseException) -> None:
        try:
            if self.on_error is not None:
                self.on_error(error)
            else:
                self.app._report_error(error)
        finally:
            self._finish()

    def _cancelled(self, future: Future) -> None:
        if future.cancelled():
            self.app.call_soon(self._finish)

    def cancel(self) -> bool:
        """Cancel queued work. Running functions must cancel cooperatively."""
        self.app._check_thread()
        return self.future.cancel() if self.future is not None else False
