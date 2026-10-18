"""Keep Tcl interpreter destruction on the thread that created it.

Destroying a window does not release its Python widgets. Cycles and pending
worker callbacks can outlive it, and Python's cyclic GC can run on any thread.
Keep one interpreter reference until all those owners have gone, then release
it from the GUI event loop. This uses CPython's reference count, just as _tkinter
does; no widgets, callbacks or application objects are retained here.
"""
import sys
import threading


_interpreters = {}


def retain(interpreter):
    _check_thread()
    reap()
    _interpreters[id(interpreter)] = interpreter


def reap():
    _check_thread()
    for key in tuple(_interpreters):
        # The dictionary and getrefcount's temporary argument are the only
        # references when every widget, variable and worker has released Tk.
        if sys.getrefcount(_interpreters[key]) == 2:
            del _interpreters[key]


def _check_thread():
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Tcl interpreter cleanup must run on the main thread")
