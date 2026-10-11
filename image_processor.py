"""Headless conversion with explicit PDF geometry and atomic output."""

import errno
import io
import logging
import math
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import img2pdf
from PIL import Image, ImageCms, ImageOps
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, NameObject, NumberObject

LOGGER = logging.getLogger(__name__)
PAGE_SIZES_MM = {"A4": (210.0, 297.0), "A3": (297.0, 420.0), "Letter": (215.9, 279.4)}
DEFAULT_DPI = 96.0
MM_TO_PT = 72.0 / 25.4
_SRGB_PROFILE = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
_SRGB_ICC_PROFILE = _SRGB_PROFILE.tobytes()


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
    default_dpi: float = DEFAULT_DPI

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
        if not math.isfinite(self.default_dpi) or not 1 <= self.default_dpi <= 10000:
            raise ValueError("DPI不明時の既定値は1〜10000で指定してください")


@dataclass(frozen=True)
class DpiInfo:
    horizontal: float
    vertical: float
    source: str
    used_default: bool = False

    @property
    def values(self):
        return self.horizontal, self.vertical


@dataclass(frozen=True)
class ImageInfo:
    width: int
    height: int
    frame_count: int
    dpi: DpiInfo
    icc_profile: str


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


def _valid_dpi_pair(value):
    try:
        horizontal, vertical = map(float, value)
        if all(math.isfinite(item) and 1 <= item <= 10000 for item in (horizontal, vertical)):
            return horizontal, vertical
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def normalize_dpi(value, default_dpi=DEFAULT_DPI):
    """Return a validated DPI pair, falling back to the caller-visible default."""
    pair = _valid_dpi_pair(value)
    if pair is not None:
        return pair
    return float(default_dpi), float(default_dpi)


def _rational_number(value):
    try:
        if isinstance(value, (tuple, list)) and len(value) == 2:
            numerator, denominator = map(float, value)
            if denominator == 0:
                return None
            number = numerator / denominator
        else:
            number = float(value)
        if math.isfinite(number) and number > 0:
            return number
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        pass
    return None


def _resolution_from_tags(tags, source):
    if tags is None:
        return None
    horizontal = _rational_number(tags.get(282))
    vertical = _rational_number(tags.get(283))
    if horizontal is None or vertical is None:
        return None
    raw_unit = tags.get(296)
    unit = 2 if raw_unit is None else _rational_number(raw_unit)
    if unit is None:
        return None
    unit = round(unit)
    if unit == 2:
        multiplier = 1.0
    elif unit == 3:
        multiplier = 2.54  # pixels per centimetre -> pixels per inch
    else:
        return None
    pair = _valid_dpi_pair((horizontal * multiplier, vertical * multiplier))
    return (pair, source) if pair is not None else None


def resolve_dpi(image, default_dpi=DEFAULT_DPI):
    """Resolve DPI from format metadata or EXIF/TIFF tags and expose its origin."""
    try:
        exif = image.getexif()
    except (AttributeError, OSError, ValueError):
        exif = None
    tags = getattr(image, "tag_v2", None)

    # Prefer explicit EXIF resolution on JPEGs; Pillow may expose a rounded or
    # synthesized pair through info['dpi'] when EXIF has different X/Y values.
    if image.format == "JPEG":
        result = _resolution_from_tags(exif, "EXIF解像度タグ")
        if result is not None:
            pair, source = result
            return DpiInfo(*pair, source)

    if image.format == "TIFF":
        result = _resolution_from_tags(tags, "TIFF解像度タグ")
        if result is None:
            result = _resolution_from_tags(exif, "EXIF解像度タグ")
        if result is not None:
            pair, source = result
            return DpiInfo(*pair, source)

    pair = _valid_dpi_pair(image.info.get("dpi"))
    if image.format == "TIFF" and pair == (1.0, 1.0):
        # Pillow synthesizes (1, 1) for some TIFFs with no resolution tags.
        has_resolution_tags = tags is not None and (282 in tags or 283 in tags)
        if not has_resolution_tags:
            pair = None
    if pair is not None:
        source = {
            "JPEG": "JPEG/JFIF",
            "PNG": "PNG pHYs",
            "TIFF": "TIFF解像度タグ",
        }.get(image.format, "画像メタデータ")
        return DpiInfo(*pair, source)

    result = _resolution_from_tags(exif, "EXIF解像度タグ")
    if result is None:
        result = _resolution_from_tags(tags, "TIFF解像度タグ")
    if result is not None:
        pair, source = result
        return DpiInfo(*pair, source)

    fallback = float(default_dpi)
    return DpiInfo(fallback, fallback, f"既定値 ({fallback:g} DPI)", used_default=True)


def _profile_description(profile_bytes, mode):
    if not profile_bytes:
        if mode == "CMYK":
            return "なし（CMYKの色解釈は出力環境依存）"
        return "なし（未タグのRGB画像はsRGBと仮定）"
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(profile_bytes))
        description = ImageCms.getProfileDescription(profile).strip()
        return f"埋め込み: {description or 'ICCプロファイル'}"
    except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
        return "埋め込み（読み込み不可）"


def inspect_image(path, default_dpi=DEFAULT_DPI):
    """Read first-frame dimensions, DPI provenance, and embedded ICC description."""
    with Image.open(path) as source:
        source.seek(0)
        width, height = source.size
        dpi = resolve_dpi(source, default_dpi)
        orientation = source.getexif().get(274, 1)
        if orientation in {5, 6, 7, 8}:
            width, height = height, width
            dpi = replace(dpi, horizontal=dpi.vertical, vertical=dpi.horizontal)
        return ImageInfo(
            width=width,
            height=height,
            frame_count=getattr(source, "n_frames", 1),
            dpi=dpi,
            icc_profile=_profile_description(source.info.get("icc_profile"), source.mode),
        )


def page_geometry(width, height, dpi, options):
    """Return page and image sizes in points, independently of pixel resolution."""
    horizontal, vertical = normalize_dpi(dpi, options.default_dpi)
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


def _load_icc_profile(profile_bytes):
    try:
        return ImageCms.ImageCmsProfile(io.BytesIO(profile_bytes))
    except (ImageCms.PyCMSError, OSError, ValueError, TypeError) as error:
        raise ValueError(f"ICCプロファイルを読み込めません: {error}") from error


def to_srgb(image, bg_color=(255, 255, 255)):
    """Convert a frame to 8-bit sRGB, honoring any embedded ICC profile."""
    owned = []

    def keep(value):
        owned.append(value)
        return value

    try:
        has_alpha = image.mode in {"RGBA", "LA", "PA", "RGBa", "La"} or (
            "transparency" in image.info
        )
        alpha = None
        if image.mode in {"LA", "La"}:
            rgba = keep(image.convert("RGBA"))
            alpha = keep(rgba.getchannel("A"))
            color_image = keep(image.getchannel("L"))
        elif has_alpha:
            rgba = keep(image.convert("RGBA"))
            alpha = keep(rgba.getchannel("A"))
            if image.mode in {"1", "L"} or image.mode.startswith("I"):
                color_image = keep(image.convert("L"))
            else:
                color_image = keep(rgba.convert("RGB"))
        elif image.mode in {"RGB", "CMYK", "L", "LAB", "XYZ"}:
            color_image = image
        elif image.mode == "1" or image.mode.startswith("I"):
            color_image = keep(image.convert("L"))
        else:
            color_image = keep(image.convert("RGB"))

        profile_bytes = image.info.get("icc_profile")
        if profile_bytes:
            source_profile = _load_icc_profile(profile_bytes)
            try:
                converted = ImageCms.profileToProfile(
                    color_image,
                    source_profile,
                    _SRGB_PROFILE,
                    renderingIntent=ImageCms.Intent.PERCEPTUAL,
                    outputMode="RGB",
                )
            except (ImageCms.PyCMSError, OSError, ValueError) as error:
                raise ValueError(f"ICC色変換に失敗しました: {error}") from error
            if converted is None:
                raise ValueError("ICC色変換に失敗しました")
            converted = keep(converted)
        else:
            if image.mode == "CMYK":
                LOGGER.warning("Untagged CMYK image is converted using Pillow's default conversion")
            converted = keep(color_image.convert("RGB"))

        if alpha is None:
            return converted.copy()
        rgba = keep(converted.convert("RGBA"))
        rgba.putalpha(alpha)
        return flatten_image(rgba, bg_color)
    finally:
        for item in reversed(owned):
            item.close()


def _validate_embedded_icc(image):
    profile_bytes = image.info.get("icc_profile")
    if not profile_bytes:
        return
    profile = _load_icc_profile(profile_bytes)
    mode = image.mode
    expected_space = (
        "CMYK"
        if mode == "CMYK"
        else "Lab"
        if mode == "LAB"
        else "XYZ"
        if mode == "XYZ"
        else "GRAY"
        if mode in {"1", "L", "LA", "La", "I", "I;16", "I;16B", "I;16L"}
        else "RGB"
        if mode in {"RGB", "RGBA", "RGBa", "P", "PA"}
        else None
    )
    actual_space = profile.profile.xcolor_space.strip()
    if expected_space is not None and actual_space.casefold() != expected_space.casefold():
        raise ValueError(
            f"ICC色空間({actual_space})と画像モード({mode})が一致しません"
        )


def _tag_unprofiled_rgb_images(writer):
    """Make the standard sRGB assumption explicit for untagged DeviceRGB images."""
    targets = []
    for page in writer.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        xobjects = resources.get_object().get("/XObject")
        if xobjects is None:
            continue
        for reference in xobjects.values():
            image = reference.get_object()
            if image.get("/Subtype") == "/Image" and image.get("/ColorSpace") == NameObject(
                "/DeviceRGB"
            ):
                targets.append(image)
    if not targets:
        return

    profile = DecodedStreamObject()
    profile.set_data(_SRGB_ICC_PROFILE)
    profile.update(
        {
            NameObject("/N"): NumberObject(3),
            NameObject("/Alternate"): NameObject("/DeviceRGB"),
        }
    )
    profile_reference = writer._add_object(profile)
    for image in targets:
        image[NameObject("/ColorSpace")] = ArrayObject(
            [NameObject("/ICCBased"), profile_reference]
        )


def make_thumbnail(path, size=(240, 200)):
    """Return a PIL image; only the UI thread creates Tk objects."""
    with Image.open(path) as source:
        oriented = ImageOps.exif_transpose(source)
        try:
            thumbnail = to_srgb(oriented, (245, 245, 245))
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
            dpi_info = resolve_dpi(source, options.default_dpi)
            dpi = dpi_info.values
            orientation = source.getexif().get(274, 1)
            image = ImageOps.exif_transpose(source)
            try:
                _validate_embedded_icc(image)
                if orientation in {5, 6, 7, 8}:
                    dpi = dpi[::-1]
                layout = page_geometry(*image.size, dpi, options)
                geometry.append(layout)
                has_alpha = image.mode in {"RGBA", "LA", "PA", "RGBa", "La"} or (
                    "transparency" in image.info
                )
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
                rgb = to_srgb(image, options.bg_color)
                try:
                    if options.quality == "compact":
                        frame_path = frame_path.with_suffix(".jpg")
                        maximum = (
                            max(1, round(layout[2] / 72 * options.compact_dpi)),
                            max(1, round(layout[3] / 72 * options.compact_dpi)),
                        )
                        rgb.thumbnail(maximum, Image.Resampling.LANCZOS)
                        rgb.save(
                            frame_path,
                            "JPEG",
                            quality=options.jpeg_quality,
                            subsampling=0,
                            icc_profile=_SRGB_ICC_PROFILE,
                        )
                    else:
                        rgb.save(
                            frame_path,
                            "PNG",
                            compress_level=3,
                            icc_profile=_SRGB_ICC_PROFILE,
                        )
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
            _tag_unprofiled_rgb_images(writer)
            writer.add_metadata({"/Producer": "Image to PDF 2.0.1"})
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
