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


def srgb_profile_bytes():
    from PIL import ImageCms

    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def embedded_image_object(pdf_path):
    reader = PdfReader(pdf_path)
    return next(iter(reader.pages[0]["/Resources"]["/XObject"].values())).get_object()


def test_mpo_embeds_only_the_primary_frame(tmp_path):
    source = tmp_path / "photo.mpo"
    with Image.new("RGB", (640, 480), "red") as main, Image.new(
        "RGB", (80, 60), "blue"
    ) as thumb:
        main.save(source, format="MPO", save_all=True, append_images=[thumb])
    output = tmp_path / "out.pdf"
    result = convert_to_pdf([source], output)
    assert result.page_count == 1
    data = source.read_bytes()
    second_frame = data.find(b"\xff\xd8\xff", 1)
    assert second_frame > 0
    image_stream = embedded_image_object(output)
    assert image_stream.get("/Filter") == "/DCTDecode"
    # The embedded JPEG is the primary frame's original bytes, not a re-encode.
    assert image_stream.get_data() == data[:second_frame]


def test_mpo_with_orientation_uses_one_transposed_page(tmp_path):
    source = tmp_path / "rotated.mpo"
    exif = Image.Exif()
    exif[274] = 6
    with Image.new("RGB", (80, 40), "red") as main:
        main.save(source, format="MPO", save_all=True, exif=exif, append_images=[])
    output = tmp_path / "out.pdf"
    result = convert_to_pdf([source], output)
    assert result.page_count == 1
    image = next(iter(PdfReader(output).pages[0].images)).image
    assert image.size == (40, 80)


def test_reencode_preserves_icc_profile(tmp_path):
    source = tmp_path / "wide_gamut.png"
    # Transparency forces the re-encoding path.
    with Image.new("RGBA", (40, 30), (10, 200, 90, 128)) as image:
        image.save(source, icc_profile=srgb_profile_bytes())
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output, options=ConversionOptions(bg_color=(255, 255, 255)))
    colorspace = embedded_image_object(output)["/ColorSpace"]
    assert "/ICCBased" in str(colorspace)


def test_cmyk_with_profile_converted_via_imagecms(tmp_path, monkeypatch):
    from PIL import ImageCms

    source = tmp_path / "print_scan.tiff"
    with Image.new("CMYK", (30, 20), (0, 255, 255, 0)) as image:
        image.save(source, icc_profile=srgb_profile_bytes())

    def fake_profile_to_profile(image, *_args, **_kwargs):
        return Image.new("RGB", image.size, (12, 34, 56))

    monkeypatch.setattr(ImageCms, "profileToProfile", fake_profile_to_profile)
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output)
    colorspace = embedded_image_object(output)["/ColorSpace"]
    assert "/ICCBased" in str(colorspace)
    image = next(iter(PdfReader(output).pages[0].images)).image
    assert image.convert("RGB").getpixel((0, 0)) == (12, 34, 56)


def test_cmyk_without_profile_uses_simple_conversion(tmp_path):
    source = tmp_path / "plain_cmyk.tiff"
    with Image.new("CMYK", (30, 20), (0, 255, 255, 0)) as image:
        image.save(source)
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output)
    image = next(iter(PdfReader(output).pages[0].images)).image
    expected = Image.new("CMYK", (1, 1), (0, 255, 255, 0)).convert("RGB").getpixel((0, 0))
    assert image.convert("RGB").getpixel((0, 0)) == expected


def test_cmyk_with_broken_profile_still_converts(tmp_path):
    source = tmp_path / "broken_profile_cmyk.tiff"
    with Image.new("CMYK", (30, 20), (0, 0, 255, 0)) as image:
        image.save(source, icc_profile=b"not an icc profile")
    output = tmp_path / "out.pdf"
    result = convert_to_pdf([source], output)
    assert result.page_count == 1
    assert not result.skipped


def test_group4_tiff_passes_through_without_reencoding(tmp_path):
    source = tmp_path / "scan.tif"
    with Image.new("1", (400, 300)) as image:
        image.save(source, compression="group4")
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output)
    image_stream = embedded_image_object(output)
    assert "/CCITTFaxDecode" in str(image_stream.get("/Filter"))
    assert image_stream.get("/ColorSpace") == "/DeviceGray"
    assert image_stream.get("/BitsPerComponent") == 1
    image = next(iter(PdfReader(output).pages[0].images)).image
    assert image.size == (400, 300)


def test_group4_tiff_with_orientation_reencodes(tmp_path):
    source = tmp_path / "rotated_scan.tif"
    exif = Image.Exif()
    exif[274] = 6
    with Image.new("1", (80, 40)) as image:
        image.save(source, compression="group4", exif=exif)
    output = tmp_path / "out.pdf"
    result = convert_to_pdf([source], output)
    assert result.page_count == 1
    image = next(iter(PdfReader(output).pages[0].images)).image
    assert image.size == (40, 80)


def test_grayscale_tiff_stays_grayscale(tmp_path):
    source = tmp_path / "gray_scan.tiff"
    with Image.new("L", (60, 40), 128) as image:
        image.save(source)
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output)
    image_stream = embedded_image_object(output)
    assert image_stream.get("/ColorSpace") == "/DeviceGray"
    assert image_stream.get("/BitsPerComponent") == 8


def test_bilevel_compact_quality_converts_to_jpeg(tmp_path):
    source = tmp_path / "mono.tif"
    with Image.new("1", (60, 40)) as image:
        image.save(source)
    output = tmp_path / "out.pdf"
    result = convert_to_pdf([source], output, options=ConversionOptions(quality="compact"))
    assert result.page_count == 1
    assert embedded_image_object(output).get("/Filter") == "/DCTDecode"


def test_passthrough_does_not_decode_pixels(tmp_path, monkeypatch):
    source = tmp_path / "photo.jpg"
    create_image(source, (300, 200))

    def refuse_load(_self):
        raise AssertionError("full pixel decode attempted for a passthrough file")

    monkeypatch.setattr(Image.Image, "load", refuse_load)
    result = convert_to_pdf([source], tmp_path / "out.pdf")
    assert result.page_count == 1


def test_mpo_passthrough_does_not_decode_pixels(tmp_path, monkeypatch):
    source = tmp_path / "photo.mpo"
    with Image.new("RGB", (100, 80), "red") as main, Image.new("RGB", (20, 16), "blue") as thumb:
        main.save(source, format="MPO", save_all=True, append_images=[thumb])

    def refuse_load(_self):
        raise AssertionError("full pixel decode attempted for an MPO passthrough file")

    monkeypatch.setattr(Image.Image, "load", refuse_load)
    result = convert_to_pdf([source], tmp_path / "out.pdf")
    assert result.page_count == 1


def test_group4_passthrough_does_not_decode_pixels(tmp_path, monkeypatch):
    source = tmp_path / "scan.tif"
    with Image.new("1", (200, 100)) as image:
        image.save(source, compression="group4")

    def refuse_load(_self):
        raise AssertionError("full pixel decode attempted for a G4 passthrough file")

    monkeypatch.setattr(Image.Image, "load", refuse_load)
    result = convert_to_pdf([source], tmp_path / "out.pdf")
    assert result.page_count == 1


def test_windows_publish_uses_rename_without_overwriting(tmp_path):
    from unittest.mock import patch

    import image_processor

    source = create_image(tmp_path / "source.png")
    output = tmp_path / "out.pdf"
    # Simulate a race: another process creates the destination between the
    # initial check and the publish, and Windows rename refuses to clobber it.
    with patch.object(image_processor, "WINDOWS", True), patch(
        "image_processor.os.rename", side_effect=FileExistsError(17, "exists")
    ) as rename_mock:
        with pytest.raises(FileExistsError):
            convert_to_pdf([source], output)
    rename_mock.assert_called_once()
    assert not output.exists()
    assert not list(tmp_path.glob(".img2pdf-*"))


def test_windows_publish_renames_when_destination_is_free(tmp_path):
    from unittest.mock import patch

    import image_processor

    source = create_image(tmp_path / "source.png")
    output = tmp_path / "out.pdf"
    with patch.object(image_processor, "WINDOWS", True):
        result = convert_to_pdf([source], output)
    assert result.page_count == 1
    assert output.is_file()
    assert not list(tmp_path.glob(".img2pdf-*"))


def test_publish_reports_success_when_temp_cleanup_fails(tmp_path):
    from unittest.mock import patch

    source = create_image(tmp_path / "source.png")
    output = tmp_path / "out.pdf"
    with patch("image_processor._unlink_quietly") as cleanup:
        result = convert_to_pdf([source], output)
    assert result.page_count == 1
    assert output.is_file()
    cleanup.assert_called_once()


def test_layout_fun_recomputes_for_unexpected_extra_pages():
    from image_processor import _make_layout_fun

    options = ConversionOptions(margin_mm=0)
    expected = page_geometry(600, 900, (96, 96), options)
    layout = _make_layout_fun([expected], options)
    assert layout(600, 900, (96, 96)) == expected
    # An unexpected second page is computed from its own arguments instead of
    # raising StopIteration.
    assert layout(300, 200, (100, 100)) == page_geometry(300, 200, (100, 100), options)


def test_icc_validation_matches_output_mode():
    from image_processor import _valid_icc_for_output

    profile = srgb_profile_bytes()
    assert _valid_icc_for_output("RGB", profile) == profile
    assert _valid_icc_for_output("L", profile) is None
    assert _valid_icc_for_output("1", profile) is None
    assert _valid_icc_for_output("RGB", b"junk") is None
    assert _valid_icc_for_output("RGB", None) is None


def test_tiff_without_resolution_uses_default_dpi(tmp_path):
    # PIL reports (1, 1) dpi for TIFFs without resolution tags; the page must
    # use the 96 dpi default (like img2pdf) instead of becoming gigantic.
    source = tmp_path / "nores.tiff"
    with Image.new("L", (192, 96), 90) as image:
        image.save(source)
    with Image.open(source) as check:
        assert tuple(check.info["dpi"]) == (1, 1)
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output, options=ConversionOptions(margin_mm=0))
    page = PdfReader(output).pages[0]
    assert float(page.mediabox.width) == pytest.approx(144.0, abs=0.5)
    assert float(page.mediabox.height) == pytest.approx(72.0, abs=0.5)


def test_group4_tiff_without_resolution_uses_default_dpi(tmp_path):
    source = tmp_path / "nores_scan.tif"
    with Image.new("1", (600, 400)) as image:
        image.save(source, compression="group4")
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output, options=ConversionOptions(margin_mm=0))
    page = PdfReader(output).pages[0]
    assert float(page.mediabox.width) == pytest.approx(450.0, abs=0.5)
    assert float(page.mediabox.height) == pytest.approx(300.0, abs=0.5)
