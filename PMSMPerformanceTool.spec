# -*- mode: python ; coding: utf-8 -*-

excluded_modules = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetwork",
    "scipy",
    "matplotlib",
    "IPython",
    "jupyter",
    "jupyter_client",
    "jupyter_core",
    "notebook",
    "pytest",
    "_pytest",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=2,
)

# Qt's software OpenGL fallback is not used by the QWidget/PyQtGraph raster
# renderer selected by this application and alone adds roughly 20 MiB.
a.binaries = type(a.binaries)(
    entry
    for entry in a.binaries
    if not any(
        name.lower().endswith(suffix)
        for suffix in (
            "opengl32sw.dll",
        )
        for name in (entry[0],)
    )
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PMSMPerformanceTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PMSMPerformanceTool",
)
