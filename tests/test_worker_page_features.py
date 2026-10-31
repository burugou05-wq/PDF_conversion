import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from image_processor import MM_TO_PT

WORKER = Path(__file__).resolve().parents[1] / "conversion_worker.py"


def invoke_worker(tmp_path, request):
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(WORKER), "--request", str(request_path)],
        input="",
        encoding="utf-8",
        text=True,
        capture_output=True,
        check=False,
    )
    return completed, [json.loads(line) for line in completed.stdout.splitlines()]


def test_worker_accepts_all_new_options(tmp_path):
    source = tmp_path / "sample.png"
    with Image.new("RGB", (60, 90), "navy") as image:
        image.save(source)
    output = tmp_path / "output.pdf"
    completed, events = invoke_worker(
        tmp_path,
        {
            "imagePaths": [str(source)],
            "outputPath": str(output),
            "options": {
                "pageSize": "Custom",
                "customPageMm": [100, 148],
                "fitToPage": True,
                "alignment": "top",
                "metadata": {"title": "題名", "keywords": "x"},
                "outline": True,
                "quality": "compact",
                "compactDpi": 100,
                "jpegQuality": 60,
            },
        },
    )
    assert completed.returncode == 0, completed.stderr
    result = events[-1]
    assert result["type"] == "completed"
    assert result["outputSize"] == output.stat().st_size
    reader = PdfReader(output)
    assert float(reader.pages[0].mediabox.width) / MM_TO_PT == pytest.approx(100, abs=0.05)
    assert reader.metadata.title == "題名"
    assert [item.title for item in reader.outline] == ["sample.png"]


def test_worker_rejects_invalid_custom_page(tmp_path):
    source = tmp_path / "sample.png"
    with Image.new("RGB", (10, 10)) as image:
        image.save(source)
    completed, events = invoke_worker(
        tmp_path,
        {
            "imagePaths": [str(source)],
            "outputPath": str(tmp_path / "o.pdf"),
            "options": {"pageSize": "Custom", "customPageMm": [1, 1]},
        },
    )
    assert completed.returncode == 1
    assert events[-1]["type"] == "error"
    assert "カスタム用紙" in events[-1]["message"]


def test_worker_inspects_pdf_inputs(tmp_path):
    existing = tmp_path / "doc.pdf"
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=210 * MM_TO_PT, height=297 * MM_TO_PT)
    with existing.open("wb") as stream:
        writer.write(stream)
    completed, events = invoke_worker(
        tmp_path, {"operation": "inspect", "imagePaths": [str(existing)]}
    )
    assert completed.returncode == 0, completed.stderr
    result = events[-1]
    assert result["type"] == "inspect"
    assert result["isPdf"] is True
    assert result["frameCount"] == 3
    assert result["pageWidthMm"] == pytest.approx(210, abs=0.01)
