import errno
import io
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageCms
from pypdf import PdfReader

from image_processor import (
    MM_TO_PT,
    ConversionCancelled,
    ConversionOptions,
    convert_to_pdf,
    inspect_image,
    make_thumbnail,
    normalize_dpi,
    page_geometry,
    resolve_dpi,
)


def create_image(path, size=(600, 900), color="red", **kwargs):
    with Image.new("RGB", size, color) as image:
        image.save(path, **kwargs)
    return path


@pytest.mark.parametrize("size", [(600, 900), (1200, 1800)])
def test_a4_dimensions_independent_of_resolution(tmp_path, size):
    source = create_image(tmp_path / "source.png", size)
    output = tmp_path / "output.pdf"
    result = convert_to_pdf(
        [source], output, options=ConversionOptions(page_size="A4", margin_mm=10)
    )
    page = PdfReader(output).pages[0]
    assert float(page.mediabox.width) == pytest.approx(210 * MM_TO_PT, abs=0.01)
    assert float(page.mediabox.height) == pytest.approx(297 * MM_TO_PT, abs=0.01)
    assert result.page_count == 1


def test_landscape_auto_rotation(tmp_path):
    source = create_image(tmp_path / "source.jpg", (1000, 500))
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output, options=ConversionOptions(page_size="A4"))
    page = PdfReader(output).pages[0]
    assert float(page.mediabox.width) == pytest.approx(297 * MM_TO_PT, abs=0.01)


def test_margin_is_in_points_without_reencoding():
    options = ConversionOptions(margin_mm=10)
    page_width, page_height, width, height = page_geometry(600, 900, (300, 300), options)
    assert page_width - width == pytest.approx(20 * MM_TO_PT)
    assert page_height - height == pytest.approx(20 * MM_TO_PT)


@pytest.mark.parametrize("page", [None, "A4"])
def test_all_tiff_frames_preserved(tmp_path, page):
    source = tmp_path / "multi.tiff"
    with Image.new("RGB", (50, 70), "red") as first, Image.new("RGB", (80, 40), "blue") as second:
        first.save(source, save_all=True, append_images=[second])
    output = tmp_path / "out.pdf"
    result = convert_to_pdf(
        [source], output, options=ConversionOptions(page_size=page, margin_mm=5)
    )
    assert result.page_count == 2
    assert len(PdfReader(output).pages) == 2


def test_broken_input_skipped_with_reason(tmp_path):
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image")
    valid = create_image(tmp_path / "valid.png")
    result = convert_to_pdf([broken, valid], tmp_path / "out.pdf")
    assert result.page_count == 1
    assert result.skipped[0].path == broken.resolve()
    assert result.skipped[0].reason


def test_all_invalid_does_not_replace_existing_output(tmp_path):
    source = tmp_path / "broken.png"
    source.write_bytes(b"broken")
    output = tmp_path / "out.pdf"
    output.write_bytes(b"existing")
    with pytest.raises(ValueError, match="変換できる画像"):
        convert_to_pdf([source], output, overwrite=True)
    assert output.read_bytes() == b"existing"


def test_cancel_preserves_existing_output(tmp_path):
    source = create_image(tmp_path / "source.png")
    output = tmp_path / "out.pdf"
    output.write_bytes(b"existing")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ConversionCancelled):
        convert_to_pdf([source], output, cancel_event=cancel, overwrite=True)
    assert output.read_bytes() == b"existing"


def test_cancel_after_processing_preserves_output(tmp_path):
    source = create_image(tmp_path / "source.png")
    output = tmp_path / "out.pdf"
    output.write_bytes(b"existing")
    cancel = threading.Event()
    with pytest.raises(ConversionCancelled):
        convert_to_pdf(
            [source],
            output,
            progress_cb=lambda _: cancel.set(),
            cancel_event=cancel,
            overwrite=True,
        )
    assert output.read_bytes() == b"existing"


def test_atomic_save_failure_preserves_original_and_removes_temp(tmp_path):
    source = create_image(tmp_path / "source.png")
    output = tmp_path / "out.pdf"
    output.write_bytes(b"existing")
    with patch("image_processor.os.replace", side_effect=PermissionError("locked")):
        with pytest.raises(PermissionError):
            convert_to_pdf([source], output, overwrite=True)
    assert output.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".img2pdf-*"))


def test_disk_full_is_not_skipped(tmp_path):
    source = create_image(tmp_path / "source.png")
    with patch("image_processor._convert_file", side_effect=OSError(errno.ENOSPC, "full")):
        with pytest.raises(OSError):
            convert_to_pdf([source], tmp_path / "out.pdf")
    assert not (tmp_path / "out.pdf").exists()


def test_existing_output_requires_opt_in(tmp_path):
    source = create_image(tmp_path / "source.png")
    output = tmp_path / "out.pdf"
    output.touch()
    with pytest.raises(FileExistsError):
        convert_to_pdf([source], output)


def test_race_does_not_overwrite_new_output(tmp_path):
    source = create_image(tmp_path / "source.png")
    output = tmp_path / "out.pdf"

    def callback(_):
        output.write_bytes(b"race winner")

    with pytest.raises(FileExistsError):
        convert_to_pdf([source], output, progress_cb=callback)
    assert output.read_bytes() == b"race winner"
    assert not list(tmp_path.glob(".img2pdf-*"))


def test_compact_reduces_jpeg_resolution(tmp_path):
    source = create_image(tmp_path / "source.jpg", (2000, 3000), dpi=(300, 300))
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output, options=ConversionOptions(quality="compact"))
    image = next(iter(PdfReader(output).pages[0].images)).image
    assert image.size == (1000, 1500)


def test_original_jpeg_bytes_preserved(tmp_path):
    source = create_image(tmp_path / "source.jpg", (50, 60), quality=92)
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output)
    page = PdfReader(output).pages[0]
    objects = page["/Resources"]["/XObject"]
    image_stream = next(iter(objects.values())).get_object()
    color_space = image_stream["/ColorSpace"]
    assert color_space[0] == "/ICCBased"
    assert color_space[1].get_object()["/N"] == 3
    assert image_stream.get_data() == source.read_bytes()


def test_transparency_flattens_to_requested_background(tmp_path):
    source = tmp_path / "alpha.png"
    with Image.new("RGBA", (30, 40), (255, 0, 0, 0)) as image:
        image.save(source)
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output, options=ConversionOptions(bg_color=(0, 0, 0)))
    image = next(iter(PdfReader(output).pages[0].images)).image
    assert image.convert("RGB").getpixel((0, 0)) == (0, 0, 0)


def test_exif_orientation(tmp_path):
    source = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    create_image(source, (80, 40), exif=exif)
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output)
    image = next(iter(PdfReader(output).pages[0].images)).image
    assert image.size == (40, 80)


def test_thumbnail_is_headless_pil_image(tmp_path):
    source = create_image(tmp_path / "source.png")
    image = make_thumbnail(source, (100, 100))
    try:
        assert isinstance(image, Image.Image)
        assert max(image.size) <= 100
    finally:
        image.close()


@pytest.mark.parametrize("margin", [-1, 101, float("nan"), float("inf")])
def test_invalid_margin_rejected(margin):
    with pytest.raises(ValueError):
        ConversionOptions(margin_mm=margin).validate()


@pytest.mark.parametrize("dpi", [None, (0, 0), (float("nan"), 100), "bad"])
def test_bad_dpi_falls_back(dpi):
    assert normalize_dpi(dpi) == (96, 96)


def test_empty_input_and_wrong_extension(tmp_path):
    with pytest.raises(ValueError):
        convert_to_pdf([], tmp_path / "out.pdf")
    with pytest.raises(ValueError):
        convert_to_pdf([Path("source.png")], tmp_path / "out.png")


def _pdf_image_object(output):
    page = PdfReader(output).pages[0]
    objects = page["/Resources"]["/XObject"]
    return next(iter(objects.values())).get_object()


def test_native_png_icc_profile_is_embedded_in_pdf(tmp_path):
    source = tmp_path / "profiled.png"
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    with Image.new("RGB", (24, 32), (80, 120, 160)) as image:
        image.save(source, icc_profile=profile)

    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output)

    image_object = _pdf_image_object(output)
    color_space = image_object["/ColorSpace"]
    assert color_space[0] == "/ICCBased"
    assert color_space[1].get_object()["/N"] == 3


def test_transcoded_icc_image_is_converted_to_srgb_and_profiled(tmp_path):
    source = tmp_path / "lab.tiff"
    lab_bytes = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    lab_profile = ImageCms.ImageCmsProfile(io.BytesIO(lab_bytes))
    srgb_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    with Image.new("LAB", (8, 9), (50, 128, 128)) as image:
        expected = ImageCms.profileToProfile(
            image, lab_profile, srgb_profile, outputMode="RGB"
        )
        expected_pixel = expected.getpixel((0, 0))
        expected.close()
        image.save(source, icc_profile=lab_bytes)

    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output)

    image_object = _pdf_image_object(output)
    color_space = image_object["/ColorSpace"]
    assert color_space[0] == "/ICCBased"
    output_profile = color_space[1].get_object()
    assert output_profile["/N"] == 3
    extracted = next(iter(PdfReader(output).pages[0].images)).image.convert("RGB")
    actual_pixel = extracted.getpixel((0, 0))
    assert actual_pixel == pytest.approx(expected_pixel, abs=1)


def test_invalid_icc_profile_skips_only_that_file(tmp_path):
    invalid = tmp_path / "invalid.png"
    with Image.new("RGB", (10, 10), "red") as image:
        image.save(invalid, icc_profile=b"not an ICC profile")
    valid = create_image(tmp_path / "valid.png")

    result = convert_to_pdf([invalid, valid], tmp_path / "out.pdf")

    assert result.page_count == 1
    assert len(result.skipped) == 1
    assert "ICCプロファイル" in result.skipped[0].reason


def test_mismatched_icc_colorspace_is_not_silently_embedded(tmp_path):
    mismatched = tmp_path / "mismatched.png"
    lab_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    with Image.new("RGB", (10, 10), "red") as image:
        image.save(mismatched, icc_profile=lab_profile)
    valid = create_image(tmp_path / "valid.png")

    result = convert_to_pdf([mismatched, valid], tmp_path / "out.pdf")

    assert result.page_count == 1
    assert len(result.skipped) == 1
    assert "一致しません" in result.skipped[0].reason


def test_png_dpi_source_is_reported(tmp_path):
    source = tmp_path / "dpi.png"
    with Image.new("RGB", (100, 200)) as image:
        image.save(source, dpi=(300, 150))

    with Image.open(source) as image:
        dpi = resolve_dpi(image)

    assert dpi.horizontal == pytest.approx(300, abs=0.1)
    assert dpi.vertical == pytest.approx(150, abs=0.1)
    assert dpi.source == "PNG pHYs"
    assert not dpi.used_default


def test_exif_centimetre_resolution_is_converted_to_dpi():
    class ImageWithExif:
        info = {}
        format = "JPEG"

        @staticmethod
        def getexif():
            return {282: (118, 1), 283: (59, 1), 296: 3}

    dpi = resolve_dpi(ImageWithExif())

    assert dpi.horizontal == pytest.approx(118 * 2.54)
    assert dpi.vertical == pytest.approx(59 * 2.54)
    assert dpi.source == "EXIF解像度タグ"
    assert not dpi.used_default


def test_jpeg_exif_resolution_preserves_distinct_axis_values(tmp_path):
    source = tmp_path / "exif-dpi.jpg"
    exif = Image.Exif()
    exif[282] = 300
    exif[283] = 150
    exif[296] = 2
    with Image.new("RGB", (80, 40)) as image:
        image.save(source, exif=exif)

    with Image.open(source) as image:
        assert image.info["dpi"] == (300, 300)
        dpi = resolve_dpi(image)

    assert dpi.values == (300, 150)
    assert dpi.source == "EXIF解像度タグ"


def test_exif_rotation_swaps_anisotropic_dpi_and_preview_dimensions(tmp_path):
    source = tmp_path / "rotated-exif-dpi.jpg"
    exif = Image.Exif()
    exif[274] = 6
    exif[282] = 300
    exif[283] = 150
    exif[296] = 2
    with Image.new("RGB", (80, 40)) as image:
        image.save(source, exif=exif)

    info = inspect_image(source)
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output)
    page = PdfReader(output).pages[0]

    assert (info.width, info.height) == (40, 80)
    assert info.dpi.values == (150, 300)
    assert float(page.mediabox.width) == pytest.approx(40 / 150 * 72, abs=0.01)
    assert float(page.mediabox.height) == pytest.approx(80 / 300 * 72, abs=0.01)


def test_tiff_without_resolution_uses_configured_default(tmp_path):
    source = tmp_path / "no-resolution.tiff"
    with Image.new("RGB", (50, 70)) as image:
        image.save(source)

    with Image.open(source) as image:
        assert image.info["dpi"] == (1, 1)
        dpi = resolve_dpi(image, default_dpi=240)

    assert dpi.values == (240, 240)
    assert dpi.used_default
    assert dpi.source == "既定値 (240 DPI)"


def test_custom_default_dpi_is_visible_and_used_for_missing_metadata(tmp_path):
    source = create_image(tmp_path / "no-dpi.png", (600, 900))
    info = inspect_image(source, default_dpi=240)
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output, options=ConversionOptions(default_dpi=240))

    assert info.dpi.values == (240, 240)
    assert info.dpi.used_default
    assert info.dpi.source == "既定値 (240 DPI)"
    page = PdfReader(output).pages[0]
    assert float(page.mediabox.width) == pytest.approx(600 / 240 * 72, abs=0.01)
    assert float(page.mediabox.height) == pytest.approx(900 / 240 * 72, abs=0.01)


@pytest.mark.parametrize("dpi", [0, -1, 10001, float("nan"), float("inf")])
def test_invalid_default_dpi_rejected(dpi):
    with pytest.raises(ValueError, match="DPI"):
        ConversionOptions(default_dpi=dpi).validate()
