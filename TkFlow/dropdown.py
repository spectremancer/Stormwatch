"""TkFlow dropdown classes and helpers."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
import tkinter as tk
from tkinter import ttk
from typing import Sequence
from ._value_widget import _ValueWidget
from ._helpers import Callback, _command, _layout_options

if TYPE_CHECKING:
    from . import App, Window, Container, Widget, Section, Row, Column


class Dropdown(_ValueWidget):
    """A readonly choice list by default; on_change(value) fires on selection."""

    def __init__(self, parent: App | Window | Container, values: Sequence[str],
                 value: str | None = None, *, editable: bool = False,
                 on_change: Callback | None = None, background: bool = False,
                 on_result: Callback | None = None, on_error: Callback | None = None,
                 **options: Any) -> None:
        parent.app._check_thread()
        if isinstance(values, str):
            raise TypeError("values must be a sequence of strings, not a single string")
        self.values = tuple(values)
        if not all(isinstance(v, str) for v in self.values):
            raise TypeError("Dropdown choices must be strings")
        self.editable = editable
        if value is None:
            value = self.values[0] if self.values else ""
        self._validate(value)
        changed = _command(parent.app, on_change, background, on_result, on_error)
        layout = _layout_options(options)
        self.variable = tk.StringVar(master=parent.widget, value=value)
        options.setdefault("state", "normal" if editable else "readonly")
        if editable:
            options.setdefault("style", "Input.TCombobox")
        self._attach(parent, ttk.Combobox(parent.widget, values=self.values,
                                        textvariable=self.variable, **options), **layout)
        self.widget.bind("<<ComboboxSelected>>", lambda _: changed(self.get()))

    def _validate(self, value: str) -> None:
        if not self.editable and value not in self.values and not (not self.values and value == ""):
            raise ValueError(f"Choose a value from {self.values!r}, or use editable=True")

    def set(self, value: str) -> Dropdown:
        self._validate(value)
        super().set(value)
        return self
