"""TkFlow checkbox classes and helpers."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
import tkinter as tk
from tkinter import ttk
from ._value_widget import _ValueWidget
from ._helpers import Callback, _command, _layout_options

if TYPE_CHECKING:
    from . import App, Window, Container, Widget, Section, Row, Column


class Checkbox(_ValueWidget):
    """Boolean checkbox; command(value) fires on user activation, not set()."""

    def __init__(self, parent: App | Window | Container, text: str = "", value: bool = False,
                 *, command: Callback | None = None, background: bool = False,
                 on_result: Callback | None = None, on_error: Callback | None = None,
                 **options: Any) -> None:
        parent.app._check_thread()
        if not isinstance(value, bool):
            raise TypeError("Checkbox value must be a bool")
        changed = _command(parent.app, command, background, on_result, on_error)
        layout = _layout_options(options)
        self.variable = tk.BooleanVar(master=parent.widget, value=value)
        self._attach(parent, ttk.Checkbutton(parent.widget, text=text, variable=self.variable,
                                            command=lambda: changed(self.get()), **options), **layout)

    def set(self, value: bool) -> Checkbox:
        if not isinstance(value, bool):
            raise TypeError("Checkbox value must be a bool")
        super().set(value)
        return self
