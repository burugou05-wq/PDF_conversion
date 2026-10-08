import subprocess
import sys
from pathlib import Path

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
    assert len(PdfReader(output).pages) == 1


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
    assert (tmp_path / "out.pdf").exists()
