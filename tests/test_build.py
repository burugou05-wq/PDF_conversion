from zipfile import ZipFile

from app_config import (
    APP_NAME,
    PORTABLE_BUNDLE_NAME,
    PORTABLE_DATA_DIRECTORY,
    PORTABLE_MARKER,
    VERSION,
)
from build import package_release_artifacts, sha256_file


def test_release_packager_creates_both_assets_and_checksums(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / f"{APP_NAME}.exe").write_bytes(b"single-file executable")
    portable = dist / PORTABLE_BUNDLE_NAME
    internal = portable / "_internal"
    internal.mkdir(parents=True)
    (portable / f"{APP_NAME}.exe").write_bytes(b"portable executable")
    (internal / "python-library.pyd").write_bytes(b"dependency")
    old_log = portable / PORTABLE_DATA_DIRECTORY / "app.log"
    old_log.parent.mkdir()
    old_log.write_text("private image path", encoding="utf-8")

    artifacts = package_release_artifacts(("release", "portable"), dist, VERSION)

    release_exe = dist / f"ImageToPDF-v{VERSION}-Windows-x64.exe"
    portable_zip = dist / f"ImageToPDF-v{VERSION}-Windows-x64-Portable.zip"
    checksums = dist / "SHA256SUMS.txt"
    assert artifacts == [release_exe, portable_zip, checksums]
    assert release_exe.read_bytes() == b"single-file executable"

    with ZipFile(portable_zip) as archive:
        names = set(archive.namelist())
        assert f"{PORTABLE_BUNDLE_NAME}/{APP_NAME}.exe" in names
        assert f"{PORTABLE_BUNDLE_NAME}/{PORTABLE_MARKER}" in names
        assert f"{PORTABLE_BUNDLE_NAME}/PORTABLE.txt" in names
        assert f"{PORTABLE_BUNDLE_NAME}/_internal/python-library.pyd" in names
        assert not any(f"/{PORTABLE_DATA_DIRECTORY}/" in name for name in names)

    lines = checksums.read_text(encoding="ascii").splitlines()
    assert lines == [
        f"{sha256_file(release_exe)}  {release_exe.name}",
        f"{sha256_file(portable_zip)}  {portable_zip.name}",
    ]
