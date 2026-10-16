"""TkFlow menu classes and helpers."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
import tkinter as tk
from ._helpers import Callback, _command

if TYPE_CHECKING:
    from . import App, Window, Container, Widget, Section, Row, Column


class Menu:
    """Attach a menu bar to App/Window, then add dropdowns and commands."""

    def __init__(self, parent: App | Window | Menu, *, tearoff: bool = False,
                 **options: Any) -> None:
        self.app = parent.app
        self.app._check_thread()
        self.widget = tk.Menu(parent.widget if isinstance(parent, Menu) else parent.root,
                              tearoff=tearoff, **options)
        if not isinstance(parent, Menu):
            parent.root.configure(menu=self.widget)

    def dropdown(self, label: str, **options: Any) -> Menu:
        """Add a dropdown or nested submenu and return it for adding items."""
        self.app._check_thread()
        submenu = Menu(self, **options)
        self.widget.add_cascade(label=label, menu=submenu.widget)
        return submenu

    def add_command(self, label: str, command: Callback, *, background: bool = False,
                    on_result: Callback | None = None, on_error: Callback | None = None,
                    **options: Any) -> int:
        """Add a zero-argument command; return its native menu index."""
        self.app._check_thread()
        self.widget.add_command(label=label, command=_command(self.app, command, background,
                                                              on_result, on_error), **options)
        return int(self.widget.index("end"))

    def separator(self) -> Menu:
        self.app._check_thread()
        self.widget.add_separator()
        return self
