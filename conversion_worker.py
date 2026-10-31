"""JSONL worker entry point used by the WinUI frontend.

Requests carry an ``operation``: ``convert`` (default) writes a PDF and emits
``progress`` events plus a terminal ``completed`` event, ``thumbnail`` answers
with base64 PNG data sized by the optional ``thumbnailSize`` pair (default
640x480), and ``inspect`` answers with the first frame's size, DPI provenance,
frame count and ICC description. Every request is answered by exactly one
terminal event (``completed`` / ``thumbnail`` / ``inspect`` / ``cancelled`` /
``error``).

One-shot mode (compatibility and debugging)::

    conversion_worker.py --request request.json

Reads a single JSON request file, writes JSON response lines to stdout and
exits. A ``{"type": "cancel"}`` line on stdin cancels the running request.

Server mode (default, no arguments)::

    conversion_worker.py

Reads one JSON request per line from stdin and answers with one JSON response
line per event on stdout, each tagged with the request's ``id``. The process
stays alive until stdin closes, so the frontend pays the interpreter or EXE
startup cost only once. Requests run on separate threads and are multiplexed
by id; ``{"type": "cancel", "id": ...}`` cancels the matching request.
"""

import argparse
import base64
import io
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

from image_processor import (
    DEFAULT_DPI,
    ConversionCancelled,
    ConversionOptions,
    convert_to_pdf,
    inspect_image,
    inspect_pdf,
    is_pdf_input,
    make_thumbnail,
)

LOGGER = logging.getLogger("ImageToPDF.Worker")

#: Fallback box for ``thumbnail`` requests, matching the WinUI preview size.
DEFAULT_THUMBNAIL_SIZE = (640, 480)
MIN_THUMBNAIL_SIDE = 16
MAX_THUMBNAIL_SIDE = 4096


def thumbnail_size(request):
    """Return the requested thumbnail box as ``(width, height)``.

    The WinUI grid view asks for small tiles while the preview fallback asks
    for a large one, so the box travels with the request instead of being
    fixed in the worker.
    """
    values = request.get("thumbnailSize")
    if not values:
        return DEFAULT_THUMBNAIL_SIZE
    if not isinstance(values, (list, tuple)) or len(values) != 2:
        raise ValueError("サムネイル寸法は [幅, 高さ] の2要素で指定してください")
    try:
        width, height = (int(value) for value in values)
    except (TypeError, ValueError):
        raise ValueError("サムネイル寸法は整数で指定してください") from None
    if not MIN_THUMBNAIL_SIDE <= width <= MAX_THUMBNAIL_SIDE:
        raise ValueError(
            f"サムネイル幅は{MIN_THUMBNAIL_SIDE}〜{MAX_THUMBNAIL_SIDE}で指定してください"
        )
    if not MIN_THUMBNAIL_SIDE <= height <= MAX_THUMBNAIL_SIDE:
        raise ValueError(
            f"サムネイル高さは{MIN_THUMBNAIL_SIDE}〜{MAX_THUMBNAIL_SIDE}で指定してください"
        )
    return width, height


def trace(message):
    """Append a startup/protocol step to the file named by the environment.

    Used by the WinUI self-test to localize stalls in packaged builds where
    stderr is otherwise invisible.
    """
    log_path = os.environ.get("IMAGETOPDF_WORKER_LOG")
    if not log_path:
        return
    try:
        with open(log_path, "a", encoding="utf-8") as stream:
            stream.write(f"{time.strftime('%H:%M:%S')} pid={os.getpid()} {message}\n")
    except OSError:
        pass


def configure_streams():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "reconfigure"):
        # The WinUI host writes UTF-8 bytes to the pipe; the platform default
        # for a piped stdin is the ANSI/OEM code page, which mangles paths.
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")


def options_from_request(request):
    values = request.get("options", {})
    page_size = values.get("pageSize")
    custom_page = values.get("customPageMm")
    metadata = values.get("metadata")
    return ConversionOptions(
        quality=values.get("quality", "original"),
        page_size=page_size,
        margin_mm=float(values.get("marginMm", 0)),
        bg_color=tuple(values.get("background", [255, 255, 255])),
        auto_rotate=bool(values.get("autoRotate", True)),
        default_dpi=float(values.get("defaultDpi", DEFAULT_DPI)),
        compact_dpi=int(values.get("compactDpi", 150)),
        jpeg_quality=int(values.get("jpegQuality", 85)),
        custom_page_mm=tuple(custom_page) if custom_page else None,
        fit_to_page=bool(values.get("fitToPage", False)),
        alignment=values.get("alignment", "center"),
        metadata=dict(metadata) if metadata else None,
        outline=bool(values.get("outline", False)),
    )


def execute_request(request, cancel_event, emit):
    """Run a single request, emitting response events through ``emit``.

    Returns the one-shot process exit code: 0 success, 2 success with skips.
    """
    operation = request.get("operation", "convert")
    image_paths = request.get("imagePaths", [])
    if not isinstance(image_paths, list) or not image_paths:
        raise ValueError("画像が指定されていません")

    if operation == "thumbnail":
        thumbnail = make_thumbnail(image_paths[0], thumbnail_size(request))
        try:
            with io.BytesIO() as buffer:
                thumbnail.save(buffer, format="PNG")
                emit("thumbnail", data=base64.b64encode(buffer.getvalue()).decode("ascii"))
        finally:
            thumbnail.close()
        return 0
    if operation == "inspect":
        if is_pdf_input(image_paths[0]):
            page_count, width_mm, height_mm = inspect_pdf(image_paths[0])
            emit(
                "inspect",
                isPdf=True,
                frameCount=page_count,
                pageWidthMm=width_mm,
                pageHeightMm=height_mm,
            )
            return 0
        options = options_from_request(request)
        # 範囲外の既定DPIはエンジンと同じ文言で弾きます（Tkinter版と同じ規則）。
        options.validate()
        info = inspect_image(image_paths[0], options.default_dpi)
        emit(
            "inspect",
            width=info.width,
            height=info.height,
            frameCount=info.frame_count,
            dpiHorizontal=info.dpi.horizontal,
            dpiVertical=info.dpi.vertical,
            dpiSource=info.dpi.source,
            dpiUsedDefault=info.dpi.used_default,
            iccProfile=info.icc_profile,
        )
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
    emit(
        "completed",
        outputPath=str(result.output_path),
        pageCount=result.page_count,
        outputSize=result.output_size,
        skipped=[
            {"path": str(item.path), "reason": item.reason}
            for item in result.skipped
        ],
    )
    return 2 if result.skipped else 0


def write_message(event_type, request_id=None, **values):
    message = {"type": event_type, "id": request_id, **values}
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


def run(request_path):
    """One-shot mode: execute a request file and exit."""
    configure_streams()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    cancel_event = threading.Event()
    threading.Thread(target=listen_for_cancel, args=(cancel_event,), daemon=True).start()

    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        return execute_request(request, cancel_event, write_message)
    except ConversionCancelled as error:
        write_message("cancelled", message=str(error))
        return 3
    except Exception as error:
        LOGGER.exception("Conversion worker failed")
        write_message("error", message=str(error) or type(error).__name__)
        return 1


class WorkerServer:
    """Serve newline-delimited JSON requests on stdin until it closes."""

    def __init__(self):
        self._stdout_lock = threading.Lock()
        self._requests = {}
        self._lock = threading.Lock()

    def emit(self, request_id, event_type, **values):
        with self._stdout_lock:
            write_message(event_type, request_id, **values)
        trace(f"emit: {event_type} id={request_id!r}")

    def serve(self):
        trace("serve: configuring streams")
        configure_streams()
        logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
        trace(f"serve: stdin={sys.stdin!r} encoding={getattr(sys.stdin, 'encoding', None)}")
        while True:
            line = sys.stdin.readline()
            trace(f"serve: read line of {len(line)} bytes")
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                LOGGER.warning("Ignoring malformed request line")
                trace("serve: malformed request line ignored")
                continue
            trace(f"serve: parsed request type={request.get('type')!r} id={request.get('id')!r}")
            if not isinstance(request, dict):
                continue
            request_id = request.get("id")
            if request.get("type") == "cancel":
                with self._lock:
                    cancel_event = self._requests.get(request_id)
                if cancel_event is not None:
                    cancel_event.set()
                continue
            if not isinstance(request_id, str) or not request_id:
                self.emit(None, "error", message="リクエストにidがありません")
                continue
            cancel_event = threading.Event()
            # Register before dispatching so a cancel line that follows
            # immediately cannot race the request thread.
            with self._lock:
                self._requests[request_id] = cancel_event
            threading.Thread(
                target=self._dispatch,
                args=(request, request_id, cancel_event),
                daemon=True,
                name=f"request-{request_id}",
            ).start()
        return 0

    def _dispatch(self, request, request_id, cancel_event):
        try:
            try:
                execute_request(
                    request,
                    cancel_event,
                    lambda event_type, **values: self.emit(request_id, event_type, **values),
                )
            except ConversionCancelled as error:
                self.emit(request_id, "cancelled", message=str(error))
            except Exception as error:
                LOGGER.exception("Conversion worker failed for request %s", request_id)
                self.emit(request_id, "error", message=str(error) or type(error).__name__)
        finally:
            with self._lock:
                self._requests.pop(request_id, None)


def main():
    parser = argparse.ArgumentParser(description="ImageToPDF WinUI conversion worker")
    parser.add_argument(
        "--request",
        type=Path,
        help="Run a single UTF-8 JSON request file and exit (default: serve requests on stdin)",
    )
    arguments = parser.parse_args()
    trace(f"main argv={sys.argv!r} frozen={getattr(sys, 'frozen', False)}")
    if arguments.request is not None:
        trace(f"one-shot request file: {arguments.request}")
        return run(arguments.request)
    try:
        return WorkerServer().serve()
    except Exception as error:
        trace(f"serve crashed: {error!r}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
