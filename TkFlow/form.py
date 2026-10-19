"""Composable, dynamically sized forms built out of Sections and controls."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
import tkinter as tk
from tkinter import ttk
from .section import Section
from .label import Label
from .text_input import TextInput
from .dropdown import Dropdown
from .checkbox import Checkbox
from .button import Button
from .command import Command
from ._helpers import _callback


@dataclass
class FormField:
    """Public handles for a field's control, label, row, and validation message."""
    control: Any
    label: Label
    row: Section
    error_label: Label
    default: Any
    required: bool = False
    validator: Callable | None = None


class FormValidationError(ValueError):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{key}: {message}" for key, message in errors.items()))


class Form(Section):
    """Add named fields, collect values, validate, reset, and submit a snapshot.

    Validators return None for valid values, or a human-readable error string.
    There is no fixed field count. Field rows can be hidden, shown, or removed.
    """

    def __init__(self, parent, title="", *, scrollable=True, **options):
        if options.pop("orientation", "vertical") != "vertical":
            raise ValueError("Form uses a vertical layout; use rows inside its body for custom content")
        super().__init__(parent, title=title, **options)
        self.fields: dict[str, FormField] = {}
        self.errors: dict[str, str] = {}
        if scrollable:
            self.canvas = tk.Canvas(self.widget, highlightthickness=0, height=240, width=300)
            scrollbar = ttk.Scrollbar(self.widget, orient="vertical", command=self.canvas.yview)
            self.canvas.configure(yscrollcommand=scrollbar.set)
            # Native canvas children are clipped to the viewport. Sibling
            # windows can paint over the section title when scrolled.
            self.body = self.column(padding=0, expand=True, fill="both",_master=self.canvas)
            self.body.widget.grid_forget()
            item = self.canvas.create_window(0, 0, window=self.body.widget, anchor="nw")
            self.canvas.grid(row=0, column=0, sticky="nsew")
            scrollbar.grid(row=0, column=1, sticky="ns")
            self.body.widget.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
            self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(item, width=event.width))
        else:
            self.body = self.column(padding=0, expand=True, fill="both")
        self.actions = self.row(padding=0)

    def _add(self, name, label, factory, default, *, required=False, validator=None):
        self._check()
        if not isinstance(name, str) or not name:
            raise ValueError("Field name must be a nonempty string")
        if name in self.fields:
            raise ValueError(f"Field {name!r} already exists")
        _callback(validator, "validator")
        row = Section(self.body, padding=0, spacing=3)
        label_widget = Label(row, label)
        try:
            control = factory(row)
        except Exception:
            row.destroy()
            raise
        error = Label(row, "", foreground="#b42318")
        error.hide()
        field = FormField(control, label_widget, row, error, default, required, validator)
        self.fields[name] = field
        return control

    def add_label(self, text: str, **options: Any) -> Label:
        """Add explanatory text without adding a value to the form snapshot."""
        self._check()
        return Label(self.body, text, **options)

    def add_text(self, name: str, label: str, value: str = "", *, required: bool = False,
                 validator: Callable | None = None, **options: Any) -> TextInput:
        return self._add(name, label, lambda row: TextInput(row, value, **options), value,
                         required=required, validator=validator)

    def add_dropdown(self, name: str, label: str, values, value: str | None = None, *,
                     required: bool = False, validator: Callable | None = None, **options: Any) -> Dropdown:
        choices = tuple(values) if not isinstance(values, str) else values
        default = value if value is not None else (choices[0] if choices else "")
        return self._add(name, label, lambda row: Dropdown(row, choices, value, **options), default,
                         required=required, validator=validator)

    def add_checkbox(self, name: str, label: str, value: bool = False, *, required: bool = False,
                     validator: Callable | None = None, **options: Any) -> Checkbox:
        return self._add(name, label, lambda row: Checkbox(row, value=value, **options), value,
                         required=required, validator=validator)

    def get(self) -> dict[str, Any]:
        self._check()
        return {name: field.control.get() for name, field in self.fields.items()}

    def set(self, values: dict[str, Any]) -> Form:
        self._check()
        unknown = values.keys() - self.fields.keys()
        if unknown:
            raise KeyError(f"Unknown form fields: {sorted(unknown)}")
        for name, value in values.items():
            self.fields[name].control.set(value)
        return self

    def validate(self) -> dict[str, str]:
        self._check()
        errors = {}
        for name, field in self.fields.items():
            value = field.control.get()
            message = None
            if field.required and (value is False or value is None or isinstance(value, str) and not value.strip()):
                message = "This field is required"
            elif field.validator is not None:
                message = field.validator(value)
                if message is not None and not isinstance(message, str):
                    raise TypeError("Validators must return None or an error string")
            if message:
                errors[name] = message
                field.error_label.set(message).show()
            else:
                field.error_label.set("").hide()
        self.errors = errors
        return dict(errors)

    def snapshot(self) -> dict[str, Any]:
        if self.validate():
            raise FormValidationError(dict(self.errors))
        return self.get()

    def reset(self) -> Form:
        self.set({name: field.default for name, field in self.fields.items()})
        self.errors = {}
        for field in self.fields.values():
            field.error_label.set("").hide()
        return self

    def remove(self, name: str) -> None:
        self._check()
        field = self.fields.pop(name)
        field.row.destroy()
        self.errors.pop(name, None)

    def add_button(self, text: str, command: Callable, **options: Any) -> Button:
        self._check()
        return Button(self.actions, text, command, **options)

    def add_submit(self, text: str, command: Callable, *, background: bool = True,
                   on_result: Callable | None = None, on_error: Callable | None = None,
                   **options: Any) -> Button:
        """Validate/capture on GUI thread; command(values) uses the pool by default."""
        def result(value):
            if not self._destroyed and on_result is not None:
                on_result(value)

        def error(exception):
            if self._destroyed:
                return
            if on_error is not None:
                on_error(exception)
            elif not isinstance(exception, FormValidationError):
                self.app._report_error(exception)

        action = Command(self.app, command, prepare=lambda: (self.snapshot(),),
                         background=background, on_result=result, on_error=error)
        button = self.add_button(text, action, **options)
        button.command = action
        return button
