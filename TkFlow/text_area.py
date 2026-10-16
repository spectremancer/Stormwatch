"""Scrollable multiline text for editors, chat transcripts, and output."""
from __future__ import annotations
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from . import App, Window, Container
import tkinter as tk
from tkinter import ttk
from .widget import Widget
from ._helpers import _layout_options, _positive


class TextArea(Widget):
    """A scrolling text widget. .widget is the frame; .text is native tk.Text."""

    def __init__(self, parent: App | Window | Container, value: str = "", *, readonly: bool = False,
                 max_lines: int | None = None, autoscroll: bool = True, **options: Any) -> None:
        parent.app._check_thread()
        if max_lines is not None:
            _positive(max_lines, "max_lines")
        layout = _layout_options(options)
        self.readonly = readonly
        self.max_lines = max_lines
        self.autoscroll = autoscroll
        frame = ttk.Frame(parent.widget)
        options.setdefault("wrap", "word")
        options.setdefault("height", 10)
        options.setdefault("width", 40)
        self.text = tk.Text(frame, **options)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self._attach(parent, frame, **layout)
        self.set(value)

    def get(self) -> str:
        self._check()
        return self.text.get("1.0", "end-1c")

    def _edit(self, function):
        self._check()
        state = self.text.cget("state")
        self.text.configure(state="normal")
        try:
            function()
            if self.max_lines is not None:
                last = int(self.text.index("end-1c").split(".")[0])
                if self.text.get("end-2c", "end-1c") == "\n":
                    last -= 1
                excess = last - self.max_lines
                if excess > 0:
                    self.text.delete("1.0", f"{excess + 1}.0")
            if self.autoscroll:
                self.text.see("end")
        finally:
            self.text.configure(state="disabled" if self.readonly else state)
        return self

    def set(self, value: str) -> TextArea:
        def replace():
            self.text.delete("1.0", "end")
            self.text.insert("end", value)
        return self._edit(replace)

    def append(self, value: str, *, tag: str | None = None) -> TextArea:
        return self._edit(lambda: self.text.insert("end", value, (tag,) if tag else ()))

    def append_segments(self, segments) -> TextArea:
        """Insert a tagged batch with one trim/scroll operation."""
        def insert():
            for value, tag in segments:
                self.text.insert("end", value, (tag,) if tag else ())
        return self._edit(insert)

    def clear(self) -> TextArea:
        return self.set("")

    def configure(self, **options: Any) -> TextArea:
        self._check()
        self.text.configure(**options)
        return self

    def enable(self) -> TextArea:
        self._check()
        self.text.configure(state="disabled" if self.readonly else "normal")
        return self

    def disable(self) -> TextArea:
        self._check()
        self.text.configure(state="disabled")
        return self

    def bind(self, event: str, command, *, add: bool = True) -> str:
        self._check()
        return self.text.bind(event, command, add="+" if add else "")
