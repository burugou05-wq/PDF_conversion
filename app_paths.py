"""Resolve application-owned paths for installed and portable builds."""

import os
import sys
from pathlib import Path

from app_config import APP_DATA_DIRECTORY, PORTABLE_DATA_DIRECTORY, PORTABLE_MARKER


def log_directory(
    *,
    executable_path: str | Path | None = None,
    local_app_data: str | Path | None = None,
    frozen: bool | None = None,
) -> Path:
    """Return the directory for logs without writing outside a portable bundle.

    The portable build ships a marker beside its executable. Its log folder is kept beside
    the executable too, so moving the extracted folder carries all app-owned data with it.
    Single-file builds and source runs continue to use the normal per-user data directory.
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if executable_path is None:
        executable_path = sys.executable

    if frozen:
        application_directory = Path(executable_path).resolve().parent
        if (application_directory / PORTABLE_MARKER).is_file():
            return application_directory / PORTABLE_DATA_DIRECTORY

    if local_app_data is None:
        local_app_data = os.environ.get("LOCALAPPDATA", str(Path.home()))
    return Path(local_app_data) / APP_DATA_DIRECTORY
