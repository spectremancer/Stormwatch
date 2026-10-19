"""TkFlow container classes and helpers."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
from tkinter import ttk
from .widget import Widget
from ._layout import _Layout

if TYPE_CHECKING:
    from . import App, Window, Container, Widget, Section, Row, Column


class Container(Widget, _Layout):
    """A nested frame that automatically arranges its children."""

    def __init__(self, parent: App | Window | Container, *,
                 orientation: str = "vertical", spacing: int = 8,
                 padding: Any = 8, title: str | None = None,
                 expand: bool = False, fill: str = "x", padx: int = 0,
                 pady: int = 0, _master: Any = None, **options: Any) -> None:
        parent.app._check_thread()
        self._init_layout(orientation, spacing)
        master = parent.widget if _master is None else _master
        frame = (ttk.Frame(master, padding=padding, **options) if title is None
                 else ttk.LabelFrame(master, text=title, padding=padding, **options))
        self._attach(parent, frame, expand=expand, fill=fill, padx=padx, pady=pady)

    def _dispose(self) -> None:
        for child in self._children:
            child._dispose()
        super()._dispose()
