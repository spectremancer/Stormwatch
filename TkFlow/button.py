"""TkFlow button classes and helpers."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
from tkinter import ttk
from .label import Label
from ._helpers import Callback, _command, _layout_options

if TYPE_CHECKING:
    from . import App, Window, Container, Widget, Section, Row, Column


class Button(Label):
    """A button; command takes no arguments. background=True runs it in a thread."""

    def __init__(self, parent: App | Window | Container, text: str = "",
                 command: Callback | None = None, *, background: bool = False,
                 on_result: Callback | None = None, on_error: Callback | None = None,
                 **options: Any) -> None:
        parent.app._check_thread()
        self._invoke = _command(parent.app, command, background, on_result, on_error)
        layout = _layout_options(options)
        self._attach(parent, ttk.Button(parent.widget, text=text, command=self._invoke, **options), **layout)

    def invoke(self) -> Any:
        """Invoke unless disabled, returning the result or background Future."""
        self._check()
        if not self.widget.instate(["disabled"]):
            return self._invoke()
        return None
