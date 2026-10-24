# -*- mode: python ; coding: utf-8 -*-
import json
import tempfile
from pathlib import Path
from version import source_identity

identity_directory = tempfile.TemporaryDirectory(prefix='stormwatch-build-')
identity_file = Path(identity_directory.name)/'build_identity.json'
identity_file.write_text(json.dumps(source_identity(Path.cwd())),encoding='utf-8')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.ico', '.'), ('alert.mp3', '.'), ('data', 'data'), (str(identity_file), '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
    version='packaging/windows-version.txt',
)

identity_directory.cleanup()
