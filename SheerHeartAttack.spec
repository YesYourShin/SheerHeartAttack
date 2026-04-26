# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

from ui.app_info import APP_ICON_FILE, APP_PACKAGE_NAME


datas = []
binaries = []
APP_NAME = APP_PACKAGE_NAME
ICON_FILE = APP_ICON_FILE
hiddenimports = [
    "PIL.Image",
    "cv2",
    "numpy",
    "ppadb.client",
    "pyautogui",
    "win32timezone",
]

for package_name in ("PySide6", "NodeGraphQt"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

datas.append((ICON_FILE, "."))

a = Analysis(
    ["ui\\node_editor_main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name=APP_NAME,
    icon=ICON_FILE,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
