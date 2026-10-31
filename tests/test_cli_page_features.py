import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from image_processor import MM_TO_PT

CLI = Path(__file__).resolve().parents[1] / "cli.py"


def make_image(path):
    with Image.new("RGB", (60, 90)) as image:
        image.save(path)
    return path


def run_cli(*arguments):
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, arguments)], capture_output=True, text=True,
        encoding="utf-8",
    )


@pytest.mark.parametrize("page", ["B5", "Postcard", "L"])
def test_cli_accepts_new_named_sizes(tmp_path, page):
    source = make_image(tmp_path / "s.png")
    output = tmp_path / "o.pdf"
    completed = run_cli(source, "-o", output, "--page", page)
    assert completed.returncode == 0, completed.stderr
    assert PdfReader(output).pages[0].mediabox.width > 0


def test_cli_accepts_custom_size(tmp_path):
    source = make_image(tmp_path / "s.png")
    output = tmp_path / "o.pdf"
    completed = run_cli(source, "-o", output, "--page", "100x148")
    assert completed.returncode == 0, completed.stderr
    width = float(PdfReader(output).pages[0].mediabox.width) / MM_TO_PT
    assert width == pytest.approx(100, abs=0.05)


def test_cli_rejects_bad_page(tmp_path):
    source = make_image(tmp_path / "s.png")
    completed = run_cli(source, "-o", tmp_path / "o.pdf", "--page", "huge")
    assert completed.returncode == 2
    assert "用紙" in completed.stderr


def test_cli_metadata_outline_and_pdf_input(tmp_path):
    source = make_image(tmp_path / "s.png")
    existing = tmp_path / "doc.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with existing.open("wb") as stream:
        writer.write(stream)
    output = tmp_path / "o.pdf"
    completed = run_cli(
        source, existing, "-o", output, "--title", "T", "--author", "A", "--outline"
    )
    assert completed.returncode == 0, completed.stderr
    reader = PdfReader(output)
    assert len(reader.pages) == 2
    assert reader.metadata.title == "T"
    assert reader.metadata.author == "A"
    assert [item.title for item in reader.outline] == ["s.png", "doc.pdf"]
    assert "KB" in completed.stdout


def test_cli_fit_and_align(tmp_path):
    source = make_image(tmp_path / "s.png")
    output = tmp_path / "o.pdf"
    completed = run_cli(
        source, "-o", output, "--page", "A4", "--fit-to-page", "--align", "top-left"
    )
    assert completed.returncode == 0, completed.stderr
    assert len(PdfReader(output).pages) == 1
