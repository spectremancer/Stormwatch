"""TkFlow window classes and helpers."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
import tkinter as tk
from .app import _Window

if TYPE_CHECKING:
    from . import App, Window, Container, Widget, Section, Row, Column


class Window(_Window):
    """An additional window sharing the App's event loop and worker dispatcher."""

    def __init__(self, parent: App | Window, title: str = "TkFlow",
                 height: int = 320, width: int = 480, *, min_height: int = 100,
                 min_width: int = 100, resizable: bool | tuple[bool, bool] = True,
                 padding: Any = 12, spacing: int = 8) -> None:
        self.app = parent.app
        self.app._check_thread()
        self.root = tk.Toplevel(parent.root)
        try:
            self._setup_window(title, height, width, min_height, min_width,
                               resizable, padding, spacing)
        except Exception:
            self.root.destroy()
            raise
        self.app._windows.append(self)
