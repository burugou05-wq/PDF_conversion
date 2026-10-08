"""Headless conversion with explicit PDF geometry and atomic output."""

import errno
import logging
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import img2pdf
from PIL import Image, ImageOps
from pypdf import PdfWriter

LOGGER = logging.getLogger(__name__)
PAGE_SIZES_MM = {"A4": (210.0, 297.0), "A3": (297.0, 420.0), "Letter": (215.9, 279.4)}
DEFAULT_DPI = 96.0
MM_TO_PT = 72.0 / 25.4


def register_image_plugins():
    try:
        import pillow_avif  # noqa: F401
    except ImportError:
        LOGGER.debug("AVIF plugin not installed")
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:
        LOGGER.debug("HEIF plugin not installed")


register_image_plugins()


class ConversionCancelled(Exception):
    pass


@dataclass(frozen=True)
class ConversionOptions:
    quality: str = "original"
    page_size: str | None = None
    margin_mm: float = 0.0
    bg_color: tuple = (255, 255, 255)
    auto_rotate: bool = True
    compact_dpi: int = 150
    jpeg_quality: int = 85

    def validate(self):
        if self.quality not in {"original", "compact"}:
            raise ValueError("画質モードが不正です")
        if self.page_size is not None and self.page_size not in PAGE_SIZES_MM:
            raise ValueError("用紙サイズが不正です")
        if not math.isfinite(self.margin_mm) or not 0 <= self.margin_mm <= 100:
            raise ValueError("余白は0〜100mmで指定してください")
        if self.page_size and self.margin_mm * 2 >= min(PAGE_SIZES_MM[self.page_size]):
            raise ValueError("余白が用紙サイズを超えています")
        if len(self.bg_color) != 3 or any(
            not isinstance(value, int) or not 0 <= value <= 255 for value in self.bg_color
        ):
            raise ValueError("背景色が不正です")
        if not 36 <= self.compact_dpi <= 600 or not 1 <= self.jpeg_quality <= 100:
            raise ValueError("圧縮設定が不正です")


@dataclass(frozen=True)
class SkippedFile:
    path: Path
    reason: str


@dataclass(frozen=True)
class ConversionResult:
    output_path: Path
    page_count: int
    skipped: tuple


def check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise ConversionCancelled("変換をキャンセルしました")


def normalize_dpi(value):
    try:
        horizontal, vertical = map(float, value)
        if all(math.isfinite(item) and 1 <= item <= 10000 for item in (horizontal, vertical)):
            return horizontal, vertical
    except (TypeError, ValueError, OverflowError):
        pass
    return DEFAULT_DPI, DEFAULT_DPI


def page_geometry(width, height, dpi, options):
    """Return page and image sizes in points, independently of pixel resolution."""
    horizontal, vertical = normalize_dpi(dpi)
    image_width = width * 72.0 / horizontal
    image_height = height * 72.0 / vertical
    margin = options.margin_mm * MM_TO_PT
    if options.page_size is None:
        return image_width + margin * 2, image_height + margin * 2, image_width, image_height
    page_width, page_height = (value * MM_TO_PT for value in PAGE_SIZES_MM[options.page_size])
    if options.auto_rotate and (image_width > image_height) != (page_width > page_height):
        page_width, page_height = page_height, page_width
    scale = min(
        1.0, (page_width - margin * 2) / image_width, (page_height - margin * 2) / image_height
    )
    return page_width, page_height, image_width * scale, image_height * scale


def flatten_image(image, color):
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (*color, 255))
    try:
        composited = Image.alpha_composite(background, rgba)
        try:
            return composited.convert("RGB")
        finally:
            composited.close()
    finally:
        rgba.close()
        background.close()


def make_thumbnail(path, size=(240, 200)):
    """Return a PIL image; only the UI thread creates Tk objects."""
    with Image.open(path) as source:
        oriented = ImageOps.exif_transpose(source)
        try:
            thumbnail = flatten_image(oriented, (245, 245, 245))
            thumbnail.thumbnail(size, Image.Resampling.LANCZOS)
            return thumbnail
        finally:
            oriented.close()


def _convert_file(path, directory, options, cancel_event):
    embedded = []
    geometry = []
    with Image.open(path) as source:
        frame_count = getattr(source, "n_frames", 1)
        for frame_index in range(frame_count):
            check_cancel(cancel_event)
            source.seek(frame_index)
            source.load()
            dpi = normalize_dpi(source.info.get("dpi"))
            orientation = source.getexif().get(274, 1)
            image = ImageOps.exif_transpose(source)
            try:
                if orientation in {5, 6, 7, 8}:
                    dpi = dpi[::-1]
                layout = page_geometry(*image.size, dpi, options)
                geometry.append(layout)
                has_alpha = image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info
                native = (
                    frame_count == 1
                    and source.format in {"JPEG", "PNG"}
                    and orientation == 1
                    and not has_alpha
                    and options.quality == "original"
                )
                if native:
                    embedded.append(str(path))
                    continue
                frame_path = directory / f"frame-{frame_index}.png"
                rgb = flatten_image(image, options.bg_color)
                try:
                    if options.quality == "compact":
                        frame_path = frame_path.with_suffix(".jpg")
                        maximum = (
                            max(1, round(layout[2] / 72 * options.compact_dpi)),
                            max(1, round(layout[3] / 72 * options.compact_dpi)),
                        )
                        rgb.thumbnail(maximum, Image.Resampling.LANCZOS)
                        rgb.save(frame_path, "JPEG", quality=options.jpeg_quality, subsampling=0)
                    else:
                        rgb.save(frame_path, "PNG", compress_level=3)
                    embedded.append(str(frame_path))
                finally:
                    rgb.close()
            finally:
                image.close()
    check_cancel(cancel_event)
    layouts = iter(geometry)
    pdf_path = directory / "image.pdf"
    with pdf_path.open("wb") as output:
        img2pdf.convert(embedded, layout_fun=lambda *args: next(layouts), outputstream=output)
    return pdf_path


def convert_to_pdf(
    image_paths, output_path, progress_cb=None, *, options=None, cancel_event=None, overwrite=False
):
    """Sequential preprocessing bounds decoded-image memory.

    Invalid files are skipped as a whole. Cancellation and resource failures
    abort before publishing output. The PDF merger still retains PDF objects.
    """
    options = options or ConversionOptions()
    options.validate()
    paths = [Path(path).expanduser().resolve() for path in image_paths]
    output = Path(output_path).expanduser().resolve()
    if not paths:
        raise ValueError("画像を追加してください")
    if output.suffix.lower() != ".pdf":
        raise ValueError("出力ファイルの拡張子は.pdfにしてください")
    if output in paths:
        raise ValueError("入力ファイルと出力先が同じです")
    if not output.parent.is_dir():
        raise ValueError("出力先フォルダが存在しません")
    if output.exists() and not overwrite:
        raise FileExistsError(f"出力ファイルが存在します: {output}")
    skipped = []
    writer = PdfWriter()
    staging = None
    try:
        with tempfile.TemporaryDirectory(prefix="img2pdf-") as temporary:
            for index, path in enumerate(paths):
                check_cancel(cancel_event)
                directory = Path(temporary) / str(index)
                directory.mkdir()
                try:
                    pdf_path = _convert_file(path, directory, options, cancel_event)
                except (ConversionCancelled, MemoryError):
                    raise
                except Exception as error:
                    # Resource failures are not recoverable by skipping an image.
                    if isinstance(error, OSError) and error.errno in {
                        errno.ENOSPC,
                        errno.EACCES,
                        errno.EPERM,
                        errno.EROFS,
                        errno.EMFILE,
                        errno.ENFILE,
                        errno.EIO,
                    }:
                        raise
                    LOGGER.warning("Skipped %s", path, exc_info=True)
                    skipped.append(SkippedFile(path, str(error) or type(error).__name__))
                else:
                    writer.append(str(pdf_path), import_outline=False)
                if progress_cb:
                    progress_cb(round((index + 1) / len(paths) * 90))
            if not writer.pages:
                details = "\n".join(f"{item.path.name}: {item.reason}" for item in skipped[:5])
                raise ValueError("変換できる画像がありません\n" + details)
            check_cancel(cancel_event)
            writer.add_metadata({"/Producer": "Image to PDF 2.0"})
            descriptor, name = tempfile.mkstemp(
                prefix=".img2pdf-", suffix=".tmp", dir=output.parent
            )
            staging = Path(name)
            with os.fdopen(descriptor, "wb") as stream:
                writer.write(stream)
                stream.flush()
                os.fsync(stream.fileno())
            check_cancel(cancel_event)
            if overwrite:
                os.replace(staging, output)
            else:
                # Publishing with a hard link prevents concurrent overwrite.
                os.link(staging, output)
                staging.unlink()
            staging = None
            result = ConversionResult(output, len(writer.pages), tuple(skipped))
        if progress_cb:
            try:
                progress_cb(100)
            except Exception:
                LOGGER.exception("Completion callback failed after successful save")
        return result
    finally:
        writer.close()
        if staging is not None:
            staging.unlink(missing_ok=True)
