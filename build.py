"""Build the one-file Windows release and the portable onedir package."""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from app_config import (
    APP_NAME,
    PORTABLE_BUNDLE_NAME,
    PORTABLE_DATA_DIRECTORY,
    PORTABLE_MARKER,
    VERSION,
)

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
BUILD_MODES = ("release", "portable")


def configure_console_encoding():
    """Avoid Windows code-page failures when build paths contain Japanese text."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def portable_readme(version=VERSION):
    return (
        f"画像PDF変換ツール v{version} ポータブル版\n\n"
        "このフォルダーを任意の場所に展開し、"
        f"「{APP_NAME}.exe」を実行してください。インストールやPython環境は不要です。\n"
        "実行ファイルだけを取り出さず、フォルダー内のファイル一式を保ったままご利用ください。\n\n"
        f"ログはこのフォルダー内の「{PORTABLE_DATA_DIRECTORY}\\app.log」に保存します。\n"
        "ログには画像のパスやエラー理由が含まれることがあります。共有する前に内容をご確認ください。\n"
        "書き込み権限がない場所では、ログファイルを作成できない場合があります。\n"
    )


def create_portable_archive(bundle_directory: Path, archive_path: Path, version=VERSION):
    """Add portable-mode metadata and ZIP a complete PyInstaller onedir bundle."""
    bundle_directory = Path(bundle_directory)
    archive_path = Path(archive_path)
    executable = bundle_directory / f"{APP_NAME}.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"Portable executable not found: {executable}")

    (bundle_directory / PORTABLE_MARKER).write_text(
        "Store app-owned data next to this executable.\n", encoding="utf-8"
    )
    (bundle_directory / "PORTABLE.txt").write_text(portable_readme(version), encoding="utf-8")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for path in sorted(bundle_directory.rglob("*")):
            relative_path = path.relative_to(bundle_directory)
            if path.is_file() and PORTABLE_DATA_DIRECTORY not in relative_path.parts:
                archive.write(
                    path,
                    arcname=Path(PORTABLE_BUNDLE_NAME) / path.relative_to(bundle_directory),
                )
    return archive_path


def sha256_file(path: Path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(artifacts, destination: Path):
    lines = [f"{sha256_file(path)}  {Path(path).name}" for path in artifacts]
    Path(destination).write_text("\n".join(lines) + "\n", encoding="ascii")
    return Path(destination)


def package_release_artifacts(targets, dist_directory=DIST, version=VERSION):
    """Prepare versioned release assets from already-built PyInstaller outputs."""
    dist_directory = Path(dist_directory)
    artifacts = []

    if "release" in targets:
        executable = dist_directory / f"{APP_NAME}.exe"
        if not executable.is_file():
            raise FileNotFoundError(f"Release executable not found: {executable}")
        release_executable = dist_directory / f"ImageToPDF-v{version}-Windows-x64.exe"
        shutil.copy2(executable, release_executable)
        artifacts.append(release_executable)

    if "portable" in targets:
        bundle = dist_directory / PORTABLE_BUNDLE_NAME
        portable_archive = dist_directory / (
            f"ImageToPDF-v{version}-Windows-x64-Portable.zip"
        )
        artifacts.append(create_portable_archive(bundle, portable_archive, version))

    if not artifacts:
        raise ValueError("At least one build target is required")
    checksums = write_checksums(artifacts, dist_directory / "SHA256SUMS.txt")
    return [*artifacts, checksums]


def build_windows_bundle(mode):
    environment = os.environ.copy()
    environment["IMAGE_TO_PDF_BUILD_MODE"] = mode
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(HERE / "build_tmp" / mode),
            str(HERE / "ImageToPDF.spec"),
        ],
        cwd=HERE,
        env=environment,
        check=True,
    )


def main():
    configure_console_encoding()
    parser = argparse.ArgumentParser(description="Build the Windows release packages")
    parser.add_argument("--skip-install", action="store_true", help="Use the current environment")
    parser.add_argument(
        "--target",
        choices=("all", *BUILD_MODES),
        default="all",
        help="Build both packages, the single-file release, or the portable package",
    )
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

    targets = BUILD_MODES if arguments.target == "all" else (arguments.target,)
    for mode in targets:
        build_windows_bundle(mode)

    artifacts = package_release_artifacts(targets)
    print("Completed:")
    for artifact in artifacts:
        print(f" - {artifact}")
    if "release" in targets:
        print(f" - {DIST / f'{APP_NAME}.exe'} (local single-file build output)")
    if "portable" in targets:
        print(f" - {DIST / PORTABLE_BUNDLE_NAME} (portable bundle directory)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
