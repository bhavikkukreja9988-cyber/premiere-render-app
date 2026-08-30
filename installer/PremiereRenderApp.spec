# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Premiere Render App desktop executable.

Run from the repository root via the build scripts; do not run this by hand.
It produces a one-folder build under ``build_app/PremiereRenderApp/`` whose
main executable is ``PremiereRenderApp.exe``. The Inno Setup script in this
folder then wraps that folder into the installer ``FileSender.exe``.

The Media Encoder agent (.jsx) is bundled as data at ``src/render/jsx/`` so the
installed app can copy it into Adobe's startup-scripts folder at runtime.
"""

import os

project_root = os.path.abspath(os.getcwd())
agent = os.path.join(project_root, "src", "render", "jsx",
                     "PremiereRenderAgent.jsx")

block_cipher = None

a = Analysis(
    [os.path.join(project_root, "src", "main.py")],
    pathex=[project_root],
    binaries=[],
    datas=[(agent, os.path.join("src", "render", "jsx"))],
    hiddenimports=[
        "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "numpy", "pandas",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtQuick",
        "PySide6.QtQml", "PySide6.QtNetwork", "PySide6.QtPositioning",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PremiereRenderApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PremiereRenderApp",
)
