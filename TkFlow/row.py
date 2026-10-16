"""TkFlow row classes and helpers."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
from .container import Container

if TYPE_CHECKING:
    from . import App, Window, Container, Widget, Section, Row, Column


class Row(Container):
    """Arrange children from left to right."""

    def __init__(self, parent: App | Window | Container, **options: Any) -> None:
        super().__init__(parent, orientation="horizontal", **options)
