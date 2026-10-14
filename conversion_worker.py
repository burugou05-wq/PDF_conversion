"""JSONL worker entry point used by the WinUI frontend."""

import argparse
import base64
import io
import json
import logging
import sys
import threading
from pathlib import Path

from image_processor import ConversionCancelled, ConversionOptions, convert_to_pdf, make_thumbnail

LOGGER = logging.getLogger("ImageToPDF.Worker")


def emit(event_type, **values):
    message = {"type": event_type, **values}
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def listen_for_cancel(cancel_event):
    """Read cancellation messages independently while conversion reports progress."""
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and message.get("type") == "cancel":
            cancel_event.set()
            return


def options_from_request(request):
    values = request.get("options", {})
    return ConversionOptions(
        quality=values.get("quality", "original"),
        page_size=values.get("pageSize"),
        margin_mm=float(values.get("marginMm", 0)),
        bg_color=tuple(values.get("background", [255, 255, 255])),
        auto_rotate=bool(values.get("autoRotate", True)),
    )


def run(request_path):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    cancel_event = threading.Event()
    threading.Thread(target=listen_for_cancel, args=(cancel_event,), daemon=True).start()

    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        operation = request.get("operation", "convert")
        image_paths = request.get("imagePaths", [])
        if not isinstance(image_paths, list) or not image_paths:
            raise ValueError("画像が指定されていません")

        if operation == "thumbnail":
            thumbnail = make_thumbnail(image_paths[0], (640, 480))
            try:
                with io.BytesIO() as buffer:
                    thumbnail.save(buffer, format="PNG")
                    emit("thumbnail", data=base64.b64encode(buffer.getvalue()).decode("ascii"))
            finally:
                thumbnail.close()
            return 0
        if operation != "convert":
            raise ValueError("ワーカー操作が不正です")

        output_path = request.get("outputPath", "")
        if not isinstance(output_path, str) or not output_path:
            raise ValueError("出力先が指定されていません")

        result = convert_to_pdf(
            image_paths,
            output_path,
            options=options_from_request(request),
            overwrite=bool(request.get("overwrite", False)),
            cancel_event=cancel_event,
            progress_cb=lambda percent: emit("progress", percent=percent),
        )
    except ConversionCancelled as error:
        emit("cancelled", message=str(error))
        return 3
    except Exception as error:
        LOGGER.exception("Conversion worker failed")
        emit("error", message=str(error) or type(error).__name__)
        return 1

    emit(
        "completed",
        outputPath=str(result.output_path),
        pageCount=result.page_count,
        skipped=[
            {"path": str(item.path), "reason": item.reason}
            for item in result.skipped
        ],
    )
    return 2 if result.skipped else 0


def main():
    parser = argparse.ArgumentParser(description="ImageToPDF WinUI conversion worker")
    parser.add_argument("--request", type=Path, required=True, help="UTF-8 JSON request file")
    arguments = parser.parse_args()
    return run(arguments.request)


if __name__ == "__main__":
    raise SystemExit(main())
