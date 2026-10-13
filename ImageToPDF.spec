# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
portable = os.environ.get("IMAGE_TO_PDF_BUILD_MODE") == "portable"
datas = []
binaries = []
hiddenimports = []
for package in ("tkinterdnd2", "pillow_avif", "pillow_heif"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_imports)

a = Analysis(
    [str(root / "img2pdf_app.py")], pathex=[str(root)], binaries=binaries,
    datas=datas, hiddenimports=hiddenimports, hookspath=[], hooksconfig={},
    runtime_hooks=[], excludes=["pytest", "ruff"], noarchive=False,
)
pyz = PYZ(a.pure)

if portable:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="画像PDF変換ツール",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        icon=str(root / "app_icon.ico"),
        manifest=str(root / "dpi_aware.manifest"),
    )
    bundle = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="ImageToPDF-Portable",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="画像PDF変換ツール",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        icon=str(root / "app_icon.ico"),
        manifest=str(root / "dpi_aware.manifest"),
    )
