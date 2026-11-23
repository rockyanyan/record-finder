# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：单文件、无控制台、带图标。
# 用法：python -m PyInstaller record-finder.spec --noconfirm
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
sys.path.insert(0, str(ROOT))

ICON = ROOT / "assets" / "app.ico"
VERSION_FILE = ROOT / "version_info.txt"

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "openpyxl",
        "openpyxl.styles",
        "openpyxl.utils",
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.font",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 明确排除用不到的大件，控制体积
    excludes=[
        "numpy", "pandas", "matplotlib", "scipy", "PIL", "pytest", "IPython",
        "setuptools", "pip", "wheel", "sqlite3.dump", "test", "unittest",
        "distutils", "lib2to3", "pickletools", "lxml", "docx", "pptx",
    ],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="记录检索器",
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
    icon=str(ICON) if ICON.exists() else None,
    version=str(VERSION_FILE) if VERSION_FILE.exists() else None,
)
