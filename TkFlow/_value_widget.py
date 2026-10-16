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
        if getattr(self, "_trace_id", None) is not None:
            self.variable.trace_remove("write", self._trace_id)
            self._trace_id = None
        super()._dispose()
