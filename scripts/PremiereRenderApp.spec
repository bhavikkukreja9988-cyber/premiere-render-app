# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Premiere Render App.

The Media Encoder agent script is bundled as data: it is copied out to the
user's Adobe startup-scripts folder at runtime.
"""
import os

block_cipher = None
project_root = os.path.abspath(os.getcwd())

a = Analysis(
    ['../src/main.py'],
    pathex=[project_root],
    binaries=[],
    datas=[('../src/render/jsx/PremiereRenderAgent.jsx', 'src/render/jsx')],
    hiddenimports=['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.Qt3DCore',
              'PySide6.QtMultimedia', 'PySide6.QtQuick', 'matplotlib', 'numpy'],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PremiereRenderApp',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False,
               name='PremiereRenderApp')
