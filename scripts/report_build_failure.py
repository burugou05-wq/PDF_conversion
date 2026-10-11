"""Expose the Windows build log as a concise GitHub Actions annotation."""

import sys
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        print("Usage: report_build_failure.py <build-log>", file=sys.stderr)
        return 2
    log = Path(sys.argv[1])
    if not log.is_file():
        return 0
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    detail = "\n".join(lines[-15:]).encode("ascii", "backslashreplace").decode("ascii")
    message = f"Windows build failed. Final log lines:\n{detail}"
    message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::error title=Windows build failure::{message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
