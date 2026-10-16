"""TkFlow section classes and helpers."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
from .container import Container

if TYPE_CHECKING:
    from . import App, Window, Container, Widget, Section, Row, Column


class Section(Container):
    """A titled section; use an empty title for a plain frame."""

    def __init__(self, parent: App | Window | Container, title: str = "",
                 **options: Any) -> None:
        super().__init__(parent, title=title or None, **options)
