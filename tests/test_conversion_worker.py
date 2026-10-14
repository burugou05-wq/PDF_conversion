import base64
import json
import subprocess
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

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
    events = [json.loads(line) for line in completed.stdout.splitlines()]
    return completed, events


def test_worker_emits_progress_and_completion_events(tmp_path):
    source = tmp_path / "sample.png"
    with Image.new("RGB", (60, 90), "navy") as image:
        image.save(source)
    output = tmp_path / "output.pdf"

    completed, events = invoke_worker(
        tmp_path,
        {
            "imagePaths": [str(source)],
            "outputPath": str(output),
            "overwrite": False,
            "options": {"pageSize": "A4", "quality": "original"},
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert any(event["type"] == "progress" for event in events)
    result = events[-1]
    assert result["type"] == "completed"
    assert result["pageCount"] == 1
    assert result["outputPath"] == str(output.resolve())
    assert result["skipped"] == []
    assert output.is_file()


def test_worker_generates_base64_preview_for_extended_formats(tmp_path):
    source = tmp_path / "preview.png"
    with Image.new("RGBA", (32, 24), (30, 90, 160, 255)) as image:
        image.save(source)

    completed, events = invoke_worker(
        tmp_path,
        {"operation": "thumbnail", "imagePaths": [str(source)]},
    )

    assert completed.returncode == 0, completed.stderr
    result = events[-1]
    assert result["type"] == "thumbnail"
    with Image.open(BytesIO(base64.b64decode(result["data"]))) as thumbnail:
        assert thumbnail.format == "PNG"
        assert thumbnail.size == (32, 24)


def test_worker_reports_skipped_inputs_as_partial_success(tmp_path):
    valid = tmp_path / "valid.png"
    broken = tmp_path / "broken.jpg"
    with Image.new("RGB", (40, 40), "teal") as image:
        image.save(valid)
    broken.write_bytes(b"not an image")

    completed, events = invoke_worker(
        tmp_path,
        {
            "imagePaths": [str(valid), str(broken)],
            "outputPath": str(tmp_path / "partial.pdf"),
        },
    )

    assert completed.returncode == 2
    result = events[-1]
    assert result["type"] == "completed"
    assert result["pageCount"] == 1
    assert result["skipped"][0]["path"] == str(broken.resolve())
    assert result["skipped"][0]["reason"]


def test_worker_returns_structured_error_for_invalid_request(tmp_path):
    completed, events = invoke_worker(tmp_path, {"imagePaths": []})

    assert completed.returncode == 1
    assert events[-1]["type"] == "error"
    assert "画像" in events[-1]["message"]
