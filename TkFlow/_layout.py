"""TkFlow layout classes and helpers."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING


if TYPE_CHECKING:
    from . import App, Window, Container, Widget, Section, Row, Column


class _Layout:
    def _init_layout(self, orientation: str, spacing: int) -> None:
        if orientation not in ("vertical", "horizontal"):
            raise ValueError("orientation must be 'vertical' or 'horizontal'")
        if isinstance(spacing, bool) or not isinstance(spacing, int) or spacing < 0:
            raise ValueError("spacing must be a nonnegative integer")
        self.orientation = orientation
        self.spacing = spacing
        self._children: list[Widget] = []
        self._next_slot = 0

    def _place(self, child: Widget, *, expand: bool, fill: str,
               padx: int, pady: int) -> None:
        if fill not in ("none", "x", "y", "both"):
            child.widget.destroy()
            raise ValueError("fill must be 'none', 'x', 'y', or 'both'")
        slot = self._next_slot
        child._slot = slot
        child._weight = int(expand)
        self._next_slot += 1
        self._children.append(child)
        horizontal = self.orientation == "horizontal"
        row, column = (0, slot) if horizontal else (slot, 0)
        sticky = {"none": "w", "x": "ew", "y": "ns", "both": "nsew"}[fill]
        gap = self.spacing if slot else 0
        child.widget.grid(row=row, column=column, sticky=sticky,
                          padx=(padx + (gap if horizontal else 0), padx),
                          pady=(pady + (gap if not horizontal else 0), pady))
        self.widget.rowconfigure(row, weight=int(expand) if not horizontal else 1)
        self.widget.columnconfigure(column, weight=int(expand) if horizontal else 1)

    def section(self, title: str = "", **options: Any) -> Section:
        from .section import Section
        return Section(self, title=title, **options)

    def row(self, **options: Any) -> Row:
        from .row import Row
        return Row(self, **options)

    def column(self, **options: Any) -> Column:
        from .column import Column
        return Column(self, **options)
