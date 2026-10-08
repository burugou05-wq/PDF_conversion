"""Windows-only executable startup/normal-exit smoke check."""

import argparse
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    arguments = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows only")
    executable = arguments.executable.resolve()
    if not executable.is_file():
        parser.error("Executable not found")
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    matched = []

    def visit(window, _):
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(window, title, len(title))
        if "画像PDF変換ツール v2.0.0" == title.value and user32.IsWindowVisible(window):
            matched.append(window)
        return True

    callback = callback_type(visit)
    process = subprocess.Popen([str(executable)])
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            user32.EnumWindows(callback, 0)
            if matched:
                break
            if process.poll() is not None:
                raise RuntimeError(f"EXE exited before startup: {process.returncode}")
            time.sleep(0.2)
        if not matched:
            raise RuntimeError("Application window did not appear")
        user32.PostMessageW(matched[0], 0x0010, 0, 0)
        return_code = process.wait(timeout=15)
        if return_code != 0:
            raise RuntimeError(f"EXE exit code: {return_code}")
        print("Executable startup and normal exit: OK")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
