import errno
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image
from pypdf import PdfReader

from image_processor import (
    MM_TO_PT,
    ConversionCancelled,
    ConversionOptions,
    convert_to_pdf,
    make_thumbnail,
    normalize_dpi,
    page_geometry,
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
