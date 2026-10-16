"""TkFlow widget classes and helpers."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
import tkinter as tk
from ._helpers import Callback

if TYPE_CHECKING:
    from . import App, Window, Container, Widget, Section, Row, Column


class Widget:
    """Common wrapper operations; the native Tk widget is available as .widget."""

    def _attach(self, parent: App | Window | Container, widget: tk.Widget,
                *, expand: bool = False, fill: str = "x", padx: int = 0,
                pady: int = 0) -> None:
        self.app = parent.app
        self.parent = parent
        self.widget = widget
        self._destroyed = False
        parent._place(self, expand=expand, fill=fill, padx=padx, pady=pady)

    def _layout_weight(self, weight: int) -> None:
        if self.parent.orientation == "horizontal":
            self.parent.widget.columnconfigure(self._slot, weight=weight)
        else:
            self.parent.widget.rowconfigure(self._slot, weight=weight)

    def _check(self) -> None:
        self.app._check_thread()
        if self._destroyed:
            raise RuntimeError("This widget has been destroyed")

    def configure(self, **options: Any) -> Widget:
        """Forward native widget options, e.g. style, width, or padding."""
        self._check()
        self.widget.configure(**options)
        return self

    def enable(self) -> Widget:
        self._check()
        self.widget.state(["!disabled"])
        return self

    def disable(self) -> Widget:
        self._check()
        self.widget.state(["disabled"])
        return self

    def hide(self) -> Widget:
        self._check()
        self.widget.grid_remove()
        self._layout_weight(0)
        return self

    def show(self) -> Widget:
        self._check()
        self.widget.grid()
        self._layout_weight(self._weight)
        return self

    def destroy(self) -> None:
        self._check()
        self._dispose()
        self._layout_weight(0)
        self.widget.destroy()
        self.parent._children.remove(self)

    def _dispose(self) -> None:
        self._destroyed = True

    def bind(self, event: str, command: Callback, *, add: bool = True) -> str:
        """Bind a Tk event; command receives the native event object."""
        self._check()
        return self.widget.bind(event, command, add="+" if add else "")
