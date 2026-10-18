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


def start_server():
    return subprocess.Popen(
        [sys.executable, str(WORKER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        text=True,
        bufsize=1,
    )


def read_until(process, condition, limit=500):
    events = []
    for _ in range(limit):
        line = process.stdout.readline()
        if not line:
            break
        event = json.loads(line)
        events.append(event)
        if condition(event):
            return events
    raise AssertionError(f"expected event not received; got: {events}")


def test_server_mode_multiplexes_requests_and_exits_on_eof(tmp_path):
    source = tmp_path / "sample.png"
    with Image.new("RGB", (60, 90), "navy") as image:
        image.save(source)
    output = tmp_path / "output.pdf"

    process = start_server()
    try:
        process.stdin.write(
            json.dumps({"id": "thumb-1", "operation": "thumbnail", "imagePaths": [str(source)]})
            + "\n"
        )
        process.stdin.write(
            json.dumps(
                {
                    "id": "convert-1",
                    "imagePaths": [str(source)],
                    "outputPath": str(output),
                    "overwrite": False,
                }
            )
            + "\n"
        )
        process.stdin.flush()

        # Responses may interleave; wait until both requests reached a
        # terminal state in a single read loop.
        terminal = set()

        def both_done(event):
            if event.get("id") in {"thumb-1", "convert-1"} and event.get("type") in {
                "thumbnail",
                "completed",
                "error",
                "cancelled",
            }:
                terminal.add((event["id"], event["type"]))
            return ("thumb-1", "thumbnail") in terminal and ("convert-1", "completed") in terminal

        events = read_until(process, both_done)
        thumb = next(e for e in events if e["id"] == "thumb-1" and e["type"] == "thumbnail")
        completed = next(e for e in events if e["id"] == "convert-1" and e["type"] == "completed")
        assert completed["pageCount"] == 1
        with Image.open(BytesIO(base64.b64decode(thumb["data"]))) as thumbnail:
            assert thumbnail.format == "PNG"
    finally:
        process.stdin.close()
        process.wait(timeout=30)
    assert process.returncode == 0
    assert output.is_file()


def test_server_mode_cancels_a_running_request(tmp_path):
    # Noise PNGs force the slow re-encoding path; the cancel line arrives
    # while the first image is still being processed.
    import random

    rng = random.Random(7)
    paths = []
    for index in range(6):
        path = tmp_path / f"noise-{index}.png"
        Image.frombytes("RGB", (900, 900), rng.randbytes(900 * 900 * 3)).save(path)
        paths.append(path)
    output = tmp_path / "output.pdf"

    process = start_server()
    try:
        process.stdin.write(
            json.dumps(
                {
                    "id": "big-1",
                    "imagePaths": [str(path) for path in paths],
                    "outputPath": str(output),
                }
            )
            + "\n"
        )
        process.stdin.write(json.dumps({"type": "cancel", "id": "big-1"}) + "\n")
        process.stdin.flush()
        events = read_until(
            process,
            lambda event: event.get("id") == "big-1"
            and event["type"] in {"cancelled", "completed", "error"},
            limit=50,
        )
        terminal = events[-1]
        assert terminal["type"] == "cancelled", events
    finally:
        process.stdin.close()
        process.wait(timeout=60)
    assert not output.exists()


def test_server_mode_reports_errors_per_request(tmp_path):
    process = start_server()
    try:
        process.stdin.write(json.dumps({"id": "bad-1", "imagePaths": []}) + "\n")
        process.stdin.write(
            json.dumps({"id": "malformed-1", "imagePaths": [], "outputPath": ""}) + "\n"
        )
        process.stdin.flush()
        events = read_until(process, lambda event: event.get("id") == "bad-1" and event["type"] == "error")
        assert "画像" in events[-1]["message"]
        # A request without an id is rejected without killing the server.
        process.stdin.write(json.dumps({"imagePaths": []}) + "\n")
        process.stdin.flush()
        events = read_until(process, lambda event: event.get("id") is None and event["type"] == "error")
        assert "id" in events[-1]["message"]
    finally:
        process.stdin.close()
        process.wait(timeout=30)
    assert process.returncode == 0
