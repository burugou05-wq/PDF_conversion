"""One non-interactive Windows build entry point."""

import argparse
import subprocess
import sys
from pathlib import Path

from app_config import APP_NAME

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Build the Windows executable")
    parser.add_argument("--skip-install", action="store_true", help="Use the current environment")
    arguments = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows EXEのビルドはWindows上で実行してください")
    if not arguments.skip_install:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                str(HERE / "requirements-dev.txt"),
                "-r",
                str(HERE / "requirements-optional.txt"),
            ],
            check=True,
        )
    subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=HERE, check=True)
    subprocess.run([sys.executable, "-m", "ruff", "check", "."], cwd=HERE, check=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(HERE / "dist"),
            "--workpath",
            str(HERE / "build_tmp"),
            str(HERE / "ImageToPDF.spec"),
        ],
        cwd=HERE,
        check=True,
    )
    executable = HERE / "dist" / f"{APP_NAME}.exe"
    if not executable.is_file():
        raise RuntimeError("ビルド結果が見つかりません")
    print(f"Completed: {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
