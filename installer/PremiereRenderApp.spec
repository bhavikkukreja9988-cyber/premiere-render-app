# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the FileSender desktop executable."""

import os

project_root = os.path.abspath(os.getcwd())
agent = os.path.join(project_root, "src", "render", "jsx", "PremiereRenderAgent.jsx")
app_icon = os.path.join(project_root, "assets", "FileSender.ico")

block_cipher = None

a = Analysis(
    [os.path.join(project_root, "src", "main.py")],
    pathex=[project_root],
    binaries=[],
    datas=[
        (agent, os.path.join("src", "render", "jsx")),
        (app_icon, os.path.join("assets")),
    ],
    hiddenimports=[
        "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
        "supabase", "gotrue", "postgrest", "storage3", "realtime",
        "httpx", "httpcore", "h2", "websockets",
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
    name="FileSender",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=app_icon if os.path.isfile(app_icon) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FileSender",
)
