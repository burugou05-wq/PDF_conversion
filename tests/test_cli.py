import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

CLI = Path(__file__).resolve().parents[1] / "cli.py"


def test_cli_conversion(tmp_path):
    source = tmp_path / "source.png"
    with Image.new("RGB", (60, 90)) as image:
        image.save(source)
    output = tmp_path / "output.pdf"
    completed = subprocess.run(
        [sys.executable, str(CLI), str(source), "-o", str(output), "--page", "A4"],
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "ページ".encode("utf-8") in completed.stdout
    assert len(PdfReader(output).pages) == 1
    assert b"output.pdf" in completed.stdout


def test_cli_accepts_custom_default_dpi(tmp_path):
    source = tmp_path / "source.png"
    with Image.new("RGB", (60, 90)) as image:
        image.save(source)
    output = tmp_path / "output.pdf"

    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            str(source),
            "-o",
            str(output),
            "--default-dpi",
            "300",
        ],
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    page = PdfReader(output).pages[0]
    assert float(page.mediabox.width) == pytest.approx(60 / 300 * 72, abs=0.01)
    assert float(page.mediabox.height) == pytest.approx(90 / 300 * 72, abs=0.01)


def test_cli_verbose_reports_dpi_source(tmp_path):
    source = tmp_path / "source.png"
    with Image.new("RGB", (60, 90)) as image:
        image.save(source, dpi=(300, 300))
    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            str(source),
            "-o",
            str(tmp_path / "output.pdf"),
            "--verbose",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    diagnostics = (completed.stderr or "") + (completed.stdout or "")
    assert "PNG pHYs" in diagnostics, f"{completed!r}; diagnostics={diagnostics!r}"
    assert "ICC" in diagnostics


def test_cli_missing_input_is_failure(tmp_path):
    completed = subprocess.run(
        [sys.executable, str(CLI), str(tmp_path / "missing.png"), "-o", str(tmp_path / "out.pdf")],
        capture_output=True,
    )
    assert completed.returncode == 1
    assert not (tmp_path / "out.pdf").exists()


def test_cli_partial_success_exit_code(tmp_path):
    source = tmp_path / "source.png"
    with Image.new("RGB", (60, 90)) as image:
        image.save(source)
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"broken")
    completed = subprocess.run(
        [sys.executable, str(CLI), str(source), str(broken), "-o", str(tmp_path / "out.pdf")],
        capture_output=True,
    )
    assert completed.returncode == 2
    assert "スキップ".encode("utf-8") in completed.stderr
    assert (tmp_path / "out.pdf").exists()
