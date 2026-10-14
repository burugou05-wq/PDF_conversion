from pathlib import Path

from app_config import (
    APP_DATA_DIRECTORY,
    PORTABLE_DATA_DIRECTORY,
    PORTABLE_MARKER,
)
from app_paths import log_directory


def test_portable_build_keeps_logs_next_to_executable(tmp_path):
    bundle = tmp_path / "ImageToPDF-Portable"
    bundle.mkdir()
    executable = bundle / "画像PDF変換ツール.exe"
    executable.touch()
    (bundle / PORTABLE_MARKER).touch()
    local_app_data = tmp_path / "AppData" / "Local"

    result = log_directory(
        executable_path=executable,
        local_app_data=local_app_data,
        frozen=True,
    )

    assert result == bundle / PORTABLE_DATA_DIRECTORY
    assert not local_app_data.exists()


def test_single_file_build_uses_local_app_data(tmp_path):
    executable = tmp_path / "画像PDF変換ツール.exe"
    executable.touch()
    local_app_data = tmp_path / "AppData" / "Local"

    result = log_directory(
        executable_path=executable,
        local_app_data=local_app_data,
        frozen=True,
    )

    assert result == local_app_data / APP_DATA_DIRECTORY


def test_source_run_ignores_portable_marker(tmp_path):
    bundle = tmp_path / "source"
    bundle.mkdir()
    (bundle / PORTABLE_MARKER).touch()
    local_app_data = tmp_path / "AppData" / "Local"

    result = log_directory(
        executable_path=bundle / "python.exe",
        local_app_data=local_app_data,
        frozen=False,
    )

    assert result == local_app_data / APP_DATA_DIRECTORY


def test_default_local_app_data_uses_environment(monkeypatch, tmp_path):
    app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(app_data))

    result = log_directory(frozen=False)

    assert result == Path(app_data) / APP_DATA_DIRECTORY
