"""Writable user data locations, separate from installed or bundled assets."""
import os
from pathlib import Path
import sys


def state_directory():
    if sys.platform == 'win32':
        root = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    else:
        root = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state')
    return root / 'Stormwatch'
