"""TkFlow value widget classes and helpers."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
from .widget import Widget

if TYPE_CHECKING:
    from . import App, Window, Container, Widget, Section, Row, Column


class _ValueWidget(Widget):
    def get(self) -> Any:
        self._check()
        return self.variable.get()

    def set(self, value: Any) -> _ValueWidget:
        self._check()
        self.variable.set(value)
        return self

    def _dispose(self) -> None:
        if self._destroyed:
            return
        if getattr(self, "_trace_id", None) is not None:
            self.variable.trace_remove("write", self._trace_id)
            self._trace_id = None
        # Variable.__del__ calls Tcl. Dispose it while the GUI thread and
        # interpreter are still available, not later in a worker's GC cycle.
        self.variable.__del__()
        self.variable._tk = None
        super()._dispose()
