"""Resizable TkFlow-compatible workspace with a collapsible event sidebar."""
from tkinter import ttk
from TkFlow.widget import Widget
from TkFlow._layout import _Layout


class Workspace(Widget, _Layout):
    def __init__(self,parent):
        self._init_layout('horizontal',0)
        self._attach(parent,ttk.Panedwindow(parent.widget,orient='horizontal'),expand=True,fill='both')

    def _place(self,child,*,expand,fill,padx,pady):
        child._slot = self._next_slot
        child._weight = int(expand)
        self._next_slot += 1
        self._children.append(child)
        self.widget.add(child.widget,weight=int(expand))

    def _dispose(self):
        for child in self._children:
            child._dispose()
        super()._dispose()
