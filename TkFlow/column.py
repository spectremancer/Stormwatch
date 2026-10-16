"""TkFlow column classes and helpers."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
from .container import Container

if TYPE_CHECKING:
    from . import App, Window, Container, Widget, Section, Row, Column


class Column(Container):
    """Arrange children from top to bottom."""

    def __init__(self, parent: App | Window | Container, **options: Any) -> None:
        super().__init__(parent, orientation="vertical", **options)
