"""Emit concise pytest failures as GitHub Actions annotations."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        print("Usage: report_pytest_failures.py <junit-xml>", file=sys.stderr)
        return 2
    report = Path(sys.argv[1])
    if not report.is_file():
        return 0
    try:
        root = ET.parse(report).getroot()
    except ET.ParseError as error:
        print(f"Could not read pytest report: {error}", file=sys.stderr)
        return 1

    for case in root.iter("testcase"):
        failure = case.find("failure")
        if failure is None:
            failure = case.find("error")
        if failure is None:
            continue
        detail = " ".join((failure.get("message", "") + " " + (failure.text or "")).split())
        message = f"{case.get('classname', '')}::{case.get('name', '')}: {detail}"[:3000]
        message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error title=pytest failure::{message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
