# -*- mode: python ; coding: utf-8 -*-
# EXE(exclude_binaries=True) + COLLECT produces a PyInstaller onedir build.
from pathlib import Path

project = Path(SPECPATH)
a = Analysis(
    [str(project / "main.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[(str(project / "bulk_mailer" / "assets"), "bulk_mailer/assets")],
    hiddenimports=["pythoncom", "pywintypes", "win32timezone", "win32com.client"],
    hookspath=[str(project / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="OutlookMailDesk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(project / "bulk_mailer" / "assets" / "maildesk.ico"),
    contents_directory="_internal",
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False,
    upx=False,
    name="OutlookMailDesk",
)
