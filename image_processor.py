"""Headless conversion with explicit PDF geometry and atomic output."""

import errno
import io
import logging
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import img2pdf
from PIL import Image, ImageCms, ImageOps
from pypdf import PdfWriter

LOGGER = logging.getLogger(__name__)
PAGE_SIZES_MM = {"A4": (210.0, 297.0), "A3": (297.0, 420.0), "Letter": (215.9, 279.4)}
DEFAULT_DPI = 96.0
MM_TO_PT = 72.0 / 25.4
# Formats whose compressed data img2pdf can embed into a PDF unchanged.
NATIVE_EMBED_FORMATS = frozenset({"JPEG", "MPO", "PNG"})
# Resolved at import time; tests override this to exercise the Windows path.
WINDOWS = os.name == "nt"
# Resource failures are not recoverable by skipping an image or retrying.
RESOURCE_ERRNOS = {
    errno.ENOSPC,
    errno.EACCES,
    errno.EPERM,
    errno.EROFS,
    errno.EMFILE,
    errno.ENFILE,
    errno.EIO,
}


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


def _make_layout_fun(geometry, options):
    """Answer layout queries with the pre-computed geometry for each frame.

    If img2pdf reports an unexpected number of pages (for example when it
    splits an embedded file internally), recompute the geometry from the
    reported pixel size and DPI instead of failing with StopIteration.
    """
    layouts = iter(geometry)

    def layout_fun(imgwidthpx, imgheightpx, ndpi):
        try:
            return next(layouts)
        except StopIteration:
            LOGGER.warning(
                "img2pdf requested more page layouts than prepared; recomputing from %sx%s px",
                imgwidthpx,
                imgheightpx,
            )
            return page_geometry(imgwidthpx, imgheightpx, ndpi, options)

    return layout_fun


def _has_alpha(image):
    return image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info


def _source_dpi(source):
    """DPI reported by the source, ignoring PIL's (1, 1) TIFF placeholder.

    PIL reports 1 dpi for TIFF files that lack resolution tags. img2pdf
    substitutes its default for those, so the precomputed page geometry must
    do the same or the page becomes gigantic.
    """
    dpi = source.info.get("dpi")
    try:
        if source.format == "TIFF" and tuple(dpi) == (1, 1):
            return None
    except TypeError:
        pass
    return dpi


def _frame_count(source):
    """Number of frames to convert.

    Multi-Picture (MPO) JPEGs from cameras and phones carry extra frames such
    as embedded preview thumbnails; only the primary image becomes a page.
    """
    if source.format == "MPO":
        return 1
    return getattr(source, "n_frames", 1)


def _can_embed_directly(source, frame_count, options):
    """Header-only test: can img2pdf embed this file's pixels unchanged?

    Requires a single upright frame without transparency. JPEG and PNG are
    embedded verbatim, MPO photos contribute only their primary frame, and
    CCITT Group 4 TIFF scans keep their compressed fax data. Everything else
    is decoded and re-encoded by :func:`_convert_frames`.
    """
    if frame_count != 1 or options.quality != "original":
        return False
    if source.getexif().get(274, 1) != 1:
        return False
    if _has_alpha(source):
        return False
    if source.format in NATIVE_EMBED_FORMATS:
        return True
    return (
        source.format == "TIFF"
        and source.mode == "1"
        and source.info.get("compression") == "group4"
    )


_BUILTIN_SRGB_ICC = None


def _builtin_srgb_profile():
    """Bytes of the lcms built-in sRGB profile, used to tag converted CMYK."""
    global _BUILTIN_SRGB_ICC
    if _BUILTIN_SRGB_ICC is None:
        _BUILTIN_SRGB_ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    return _BUILTIN_SRGB_ICC


def _valid_icc_for_output(mode, icc):
    """Keep ICC profiles that match the output color mode; drop the others.

    A profile whose color space disagrees with the pixel data (an RGB profile
    on grayscale output, for instance) produces inconsistent PDF images, so
    the profile is verified before it is attached to a re-encoded frame.
    """
    if not icc:
        return None
    expected = {"RGB": "RGB", "L": "GRAY"}.get(mode)
    if expected is None:
        return None
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc)).profile
        # ICC signatures are four bytes ("RGB ", "GRAY"); lcms keeps padding.
        if (profile.xcolor_space or "").strip() == expected:
            return icc
        LOGGER.warning("Dropping %s ICC profile from %s output", profile.xcolor_space, mode)
    except Exception:
        LOGGER.warning("Ignoring unreadable ICC profile", exc_info=True)
    return None


def _convert_cmyk_to_rgb(image):
    """Convert CMYK pixels to sRGB, honoring the embedded ICC profile.

    Pillow's plain ``convert("RGB")`` ignores color management, which shifts
    the colors of print-ready scans. When the image carries a CMYK profile it
    is converted with LittleCMS instead; the result is tagged as sRGB.

    Returns ``(image, icc_profile_bytes)`` where the profile may be None when
    the conversion fell back to the simple transform.
    """
    profile = image.info.get("icc_profile")
    if profile:
        try:
            source_profile = ImageCms.ImageCmsProfile(io.BytesIO(profile))
            target_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
            converted = ImageCms.profileToProfile(
                image, source_profile, target_profile, outputMode="RGB"
            )
            return converted, _builtin_srgb_profile()
        except Exception:
            LOGGER.warning(
                "ICC-based CMYK conversion failed; using simple conversion", exc_info=True
            )
    return image.convert("RGB"), None


def flatten_image(image, color):
    """Composite transparency onto the background color.

    Grayscale and bilevel images keep their mode so scanned documents stay
    small; everything else becomes RGB. The result is always a new image.
    """
    if not _has_alpha(image):
        if image.mode in {"1", "L", "RGB"}:
            return image.copy()
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (*color, 255))
    try:
        composited = Image.alpha_composite(background, rgba)
        try:
            if image.mode in {"1", "L", "LA"}:
                return composited.convert("L")
            return composited.convert("RGB")
        finally:
            composited.close()
    finally:
        rgba.close()
        background.close()


def make_thumbnail(path, size=(240, 200)):
    """Return a PIL image; only the UI thread creates Tk objects."""
    with Image.open(path) as source:
        # JPEG decoders can scale while decoding (DCT scaling). Requesting
        # about twice the target size keeps enough detail for the final
        # LANCZOS shrink while decoding a fraction of the pixel data.
        source.draft(source.mode, (size[0] * 2, size[1] * 2))
        oriented = ImageOps.exif_transpose(source)
        try:
            thumbnail = flatten_image(oriented, (245, 245, 245))
            thumbnail.thumbnail(size, Image.Resampling.LANCZOS)
            return thumbnail
        finally:
            oriented.close()


def _save_frame(image, frame_path, dpi, icc, options):
    if options.quality != "compact":
        image.save(frame_path, "PNG", compress_level=3, dpi=dpi, icc_profile=icc)
        return
    if image.mode == "1":
        # JPEG has no bilevel mode; fall back to 8-bit grayscale.
        converted = image.convert("L")
        try:
            converted.save(
                frame_path,
                "JPEG",
                quality=options.jpeg_quality,
                subsampling=0,
                dpi=dpi,
                icc_profile=icc,
            )
        finally:
            converted.close()
    else:
        image.save(
            frame_path,
            "JPEG",
            quality=options.jpeg_quality,
            subsampling=0,
            dpi=dpi,
            icc_profile=icc,
        )


def _embed_source_directly(path, source, directory, options, cancel_event):
    """Write a single-page PDF without decoding the image pixels."""
    check_cancel(cancel_event)
    dpi = normalize_dpi(_source_dpi(source))
    geometry = [page_geometry(source.width, source.height, dpi, options)]
    keywords = {"first_frame_only": True} if source.format == "MPO" else {}
    pdf_path = directory / "image.pdf"
    with pdf_path.open("wb") as output:
        img2pdf.convert(
            str(path),
            layout_fun=_make_layout_fun(geometry, options),
            outputstream=output,
            **keywords,
        )
    return pdf_path


def _convert_frames(source, frame_count, directory, options, cancel_event):
    """Decode every frame and re-encode it as PNG (or JPEG in compact mode)."""
    embedded = []
    geometry = []
    for frame_index in range(frame_count):
        check_cancel(cancel_event)
        source.seek(frame_index)
        source.load()
        dpi = normalize_dpi(_source_dpi(source))
        orientation = source.getexif().get(274, 1)
        image = ImageOps.exif_transpose(source)
        converted = None
        try:
            if orientation in {5, 6, 7, 8}:
                dpi = dpi[::-1]
            layout = page_geometry(*image.size, dpi, options)
            geometry.append(layout)
            if image.mode == "CMYK":
                converted, icc = _convert_cmyk_to_rgb(image)
            else:
                icc = image.info.get("icc_profile")
            pixels = converted if converted is not None else image
            frame_path = directory / f"frame-{frame_index}.png"
            flattened = flatten_image(pixels, options.bg_color)
            try:
                icc = _valid_icc_for_output(flattened.mode, icc)
                if options.quality == "compact":
                    frame_path = frame_path.with_suffix(".jpg")
                    maximum = (
                        max(1, round(layout[2] / 72 * options.compact_dpi)),
                        max(1, round(layout[3] / 72 * options.compact_dpi)),
                    )
                    flattened.thumbnail(maximum, Image.Resampling.LANCZOS)
                _save_frame(flattened, frame_path, dpi, icc, options)
                embedded.append(str(frame_path))
            finally:
                flattened.close()
        finally:
            if converted is not None:
                converted.close()
            image.close()
    check_cancel(cancel_event)
    pdf_path = directory / "image.pdf"
    with pdf_path.open("wb") as output:
        img2pdf.convert(
            embedded, layout_fun=_make_layout_fun(geometry, options), outputstream=output
        )
    return pdf_path


def _convert_file(path, directory, options, cancel_event):
    """Build one single-file PDF, embedding the original data when possible."""
    with Image.open(path) as source:
        frame_count = _frame_count(source)
        if _can_embed_directly(source, frame_count, options):
            try:
                return _embed_source_directly(path, source, directory, options, cancel_event)
            except (ConversionCancelled, MemoryError):
                raise
            except Exception as error:
                if isinstance(error, OSError) and error.errno in RESOURCE_ERRNOS:
                    raise
                # img2pdf refused the direct embedding (for example an
                # unusual TIFF structure); fall back to decoding the pixels.
                LOGGER.info("Direct embedding failed for %s (%s); re-encoding", path, error)
        return _convert_frames(source, frame_count, directory, options, cancel_event)


def _unlink_quietly(path):
    try:
        os.unlink(path)
    except OSError:
        # The output is already published; a staging file that cannot be
        # removed must not turn a successful save into a reported failure.
        LOGGER.warning("PDFを公開しましたが、一時ファイルを削除できませんでした: %s", path)


def _publish_output(staging, output, overwrite):
    """Publish the finished PDF without ever truncating an existing file."""
    if overwrite:
        os.replace(staging, output)
        return
    if WINDOWS:
        # Windows rename refuses to replace an existing destination, so it
        # offers the same no-clobber guarantee as a hard link while also
        # working on exFAT/FAT32 volumes such as USB sticks and SD cards.
        os.rename(staging, output)
        return
    # POSIX rename would silently replace the destination, so publish through
    # a hard link, which fails atomically if the output already exists.
    os.link(staging, output)
    _unlink_quietly(staging)


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
                    if isinstance(error, OSError) and error.errno in RESOURCE_ERRNOS:
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
            _publish_output(staging, output, overwrite)
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
