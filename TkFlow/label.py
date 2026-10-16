"""TkFlow label classes and helpers."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
from tkinter import ttk
from .widget import Widget
from ._helpers import _layout_options

if TYPE_CHECKING:
    from . import App, Window, Container, Widget, Section, Row, Column


class Label(Widget):
    """A themed label with get()/set() text access."""

    def __init__(self, parent: App | Window | Container, text: str = "", **options: Any) -> None:
        parent.app._check_thread()
        layout = _layout_options(options)
        self._attach(parent, ttk.Label(parent.widget, text=text, **options), **layout)

    def get(self) -> str:
        self._check()
        return str(self.widget.cget("text"))

    def set(self, text: str) -> Label:
        self.configure(text=text)
        return self
