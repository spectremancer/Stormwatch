"""TkFlow helpers classes and helpers."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
from typing import Callable
Callback = Callable[..., Any]

if TYPE_CHECKING:
    from . import App, Window, Container, Widget, Section, Row, Column


def _positive(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _callback(value: Callback | None, name: str) -> None:
    if value is not None and not callable(value):
        raise TypeError(f"{name} must be callable or None")


def _command(app: App, command: Callback | None, background: bool,
             on_result: Callback | None, on_error: Callback | None) -> Callback:
    for name, callback in (("command", command), ("on_result", on_result), ("on_error", on_error)):
        _callback(callback, name)

    def invoke(*args: Any) -> Any:
        if command is None:
            return None
        if background:
            return app.run_in_thread(command, *args, on_result=on_result, on_error=on_error)
        try:
            result = command(*args)
        except Exception as error:
            if on_error is None:
                raise
            on_error(error)
            return None
        if on_result is not None:
            on_result(result)
        return result

    return invoke


def _layout_options(options: dict[str, Any]) -> dict[str, Any]:
    return {key: options.pop(key) for key in ("expand", "fill", "padx", "pady") if key in options}
