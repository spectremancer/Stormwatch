"""Release identity shared by diagnostics and the packaged executable."""
import json
from pathlib import Path
import subprocess
import sys

VERSION = '1.1.0'
BUILD = 'stabilization-1'
IDENTITY = f'Stormwatch {VERSION} ({BUILD})'


def source_identity(directory):
    try:
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=directory,text=True,stderr=subprocess.DEVNULL).strip()
        changed=subprocess.check_output(['git','status','--porcelain','--','*.py','*.spec','requirements.txt',
            'data','packaging','icon.ico','alert.mp3'],cwd=directory,text=True,stderr=subprocess.DEVNULL)
        return dict(commit=commit,dirty=bool(changed.strip()))
    except (OSError,subprocess.CalledProcessError):
        return dict(commit='unknown',dirty=True)


def running_identity():
    if not getattr(sys,'frozen',False):
        return source_identity(Path(__file__).parent)
    try:
        data=json.loads(Path(__file__).with_name('build_identity.json').read_text(encoding='utf-8'))
        return dict(commit=str(data['commit']),dirty=data.get('dirty') is not False)
    except (OSError,ValueError,KeyError,TypeError):
        return dict(commit='unknown',dirty=True)


# Capture at import time: pulling source while an app is running must not change
# the identity reported by code that was already loaded.
BUILD_INFO = running_identity()
