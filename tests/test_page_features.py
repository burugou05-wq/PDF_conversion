"""Paper sizes, custom pages, fit-to-page, alignment, metadata, outline and PDF input."""

import re

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from image_processor import (
    CUSTOM_PAGE_SIZE,
    MM_TO_PT,
    PAGE_SIZES_MM,
    ConversionOptions,
    convert_to_pdf,
    image_offset,
    inspect_pdf,
    page_geometry,
)


def create_image(path, size=(600, 900), color="red", **kwargs):
    with Image.new("RGB", size, color) as image:
        image.save(path, **kwargs)
    return path


def page_size_mm(page):
    return float(page.mediabox.width) / MM_TO_PT, float(page.mediabox.height) / MM_TO_PT


@pytest.mark.parametrize("name", sorted(PAGE_SIZES_MM))
def test_every_named_page_size_produces_matching_mediabox(tmp_path, name):
    source = create_image(tmp_path / "source.png", (300, 400))
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output, options=ConversionOptions(page_size=name))
    width, height = page_size_mm(PdfReader(output).pages[0])
    expected_width, expected_height = PAGE_SIZES_MM[name]
    assert width == pytest.approx(expected_width, abs=0.05)
    assert height == pytest.approx(expected_height, abs=0.05)


def test_custom_page_size(tmp_path):
    source = create_image(tmp_path / "source.png", (300, 400))
    output = tmp_path / "out.pdf"
    options = ConversionOptions(page_size=CUSTOM_PAGE_SIZE, custom_page_mm=(100, 148))
    convert_to_pdf([source], output, options=options)
    width, height = page_size_mm(PdfReader(output).pages[0])
    assert (width, height) == (pytest.approx(100, abs=0.05), pytest.approx(148, abs=0.05))


@pytest.mark.parametrize(
    "custom", [None, (5, 100), (100, 6000), ("a", "b"), (100,), (float("nan"), 100)]
)
def test_invalid_custom_page_rejected(custom):
    with pytest.raises(ValueError):
        ConversionOptions(page_size=CUSTOM_PAGE_SIZE, custom_page_mm=custom).validate()


def test_fit_to_page_enlarges_small_images():
    # 100x150 px at 300 dpi is 24x36 pt; A4 is much larger.
    base = ConversionOptions(page_size="A4", margin_mm=10)
    _, _, width, height = page_geometry(100, 150, (300, 300), base)
    assert width == pytest.approx(24)
    page_width, page_height, fitted_width, fitted_height = page_geometry(
        100, 150, (300, 300), ConversionOptions(page_size="A4", margin_mm=10, fit_to_page=True)
    )
    assert fitted_width > width
    assert fitted_height <= page_height - 20 * MM_TO_PT + 1e-6
    assert fitted_width / fitted_height == pytest.approx(100 / 150)


def test_fit_to_page_never_exceeds_margins():
    options = ConversionOptions(page_size="A4", margin_mm=20, fit_to_page=True)
    page_width, page_height, width, height = page_geometry(1000, 1000, (72, 72), options)
    assert width <= page_width - 40 * MM_TO_PT + 1e-6
    assert height <= page_height - 40 * MM_TO_PT + 1e-6


def test_image_offset_alignments():
    options = ConversionOptions(page_size="A4", margin_mm=10)
    page = (595.0, 842.0, 100.0, 200.0)
    assert image_offset(*page, options) == pytest.approx((247.5, 321.0))
    top = ConversionOptions(page_size="A4", margin_mm=10, alignment="top")
    x, y = image_offset(*page, top)
    assert x == pytest.approx(247.5)
    assert y == pytest.approx(842.0 - 10 * MM_TO_PT - 200.0)
    top_left = ConversionOptions(page_size="A4", margin_mm=10, alignment="top-left")
    x, y = image_offset(*page, top_left)
    assert x == pytest.approx(10 * MM_TO_PT)


def image_matrix(page):
    content = page.get_contents().get_data().decode("latin-1")
    match = re.search(r"([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm", content)
    assert match, content
    return tuple(float(value) for value in match.groups())


@pytest.mark.parametrize("alignment", ["top", "top-left"])
def test_alignment_rewrites_image_position(tmp_path, alignment):
    source = create_image(tmp_path / "source.jpg", (300, 300))
    output = tmp_path / "out.pdf"
    options = ConversionOptions(page_size="A4", margin_mm=10, alignment=alignment)
    convert_to_pdf([source], output, options=options)
    page = PdfReader(output).pages[0]
    width, height, x, y = image_matrix(page)
    page_height = float(page.mediabox.height)
    assert y == pytest.approx(page_height - 10 * MM_TO_PT - height, abs=0.01)
    if alignment == "top-left":
        assert x == pytest.approx(10 * MM_TO_PT, abs=0.01)
    else:
        assert x == pytest.approx((float(page.mediabox.width) - width) / 2, abs=0.01)


def test_alignment_keeps_jpeg_bytes(tmp_path):
    source = create_image(tmp_path / "source.jpg", (300, 300), quality=90)
    output = tmp_path / "out.pdf"
    options = ConversionOptions(page_size="A4", alignment="top-left")
    convert_to_pdf([source], output, options=options)
    page = PdfReader(output).pages[0]
    xobject = next(iter(page["/Resources"]["/XObject"].values())).get_object()
    assert xobject["/Filter"] == "/DCTDecode"


def test_invalid_alignment_rejected():
    with pytest.raises(ValueError):
        ConversionOptions(alignment="bottom").validate()


def test_metadata_written_to_info_dictionary(tmp_path):
    source = create_image(tmp_path / "source.png", (30, 30))
    output = tmp_path / "out.pdf"
    options = ConversionOptions(
        metadata={"title": "題名", "author": "作者", "subject": "件名", "keywords": "a, b"}
    )
    convert_to_pdf([source], output, options=options)
    info = PdfReader(output).metadata
    assert info.title == "題名"
    assert info.author == "作者"
    assert info.subject == "件名"
    assert info["/Keywords"] == "a, b"
    assert "Image to PDF" in info.producer


def test_empty_metadata_values_are_omitted(tmp_path):
    source = create_image(tmp_path / "source.png", (30, 30))
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output, options=ConversionOptions(metadata={"title": ""}))
    assert "/Title" not in PdfReader(output).metadata


@pytest.mark.parametrize("metadata", [{"bogus": "x"}, {"title": 1}, ["title"]])
def test_invalid_metadata_rejected(metadata):
    with pytest.raises(ValueError):
        ConversionOptions(metadata=metadata).validate()


def test_outline_has_one_entry_per_input(tmp_path):
    first = create_image(tmp_path / "first.png", (30, 30))
    second = tmp_path / "second.tif"
    frames = [Image.new("RGB", (20, 20), color) for color in ("red", "blue", "green")]
    frames[0].save(second, save_all=True, append_images=frames[1:])
    output = tmp_path / "out.pdf"
    convert_to_pdf([first, second], output, options=ConversionOptions(outline=True))
    reader = PdfReader(output)
    outline = reader.outline
    assert [item.title for item in outline] == ["first.png", "second.tif (3ページ)"]
    assert reader.get_destination_page_number(outline[0]) == 0
    assert reader.get_destination_page_number(outline[1]) == 1


def test_no_outline_by_default(tmp_path):
    source = create_image(tmp_path / "source.png", (30, 30))
    output = tmp_path / "out.pdf"
    convert_to_pdf([source], output)
    assert PdfReader(output).outline == []


def make_pdf(path, pages=2, size=(200.0, 300.0)):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=size[0], height=size[1])
    with path.open("wb") as stream:
        writer.write(stream)
    return path


def test_pdf_inputs_are_merged_in_order(tmp_path):
    image = create_image(tmp_path / "photo.png", (30, 30))
    existing = make_pdf(tmp_path / "doc.pdf", pages=2)
    output = tmp_path / "out.pdf"
    result = convert_to_pdf([existing, image, existing], output, options=ConversionOptions())
    reader = PdfReader(output)
    assert result.page_count == 5
    assert float(reader.pages[0].mediabox.width) == pytest.approx(200.0)
    assert float(reader.pages[2].mediabox.width) != pytest.approx(200.0)
    assert float(reader.pages[3].mediabox.width) == pytest.approx(200.0)


def test_pdf_pages_are_not_resized_by_page_option(tmp_path):
    existing = make_pdf(tmp_path / "doc.pdf", pages=1, size=(200.0, 300.0))
    output = tmp_path / "out.pdf"
    convert_to_pdf([existing], output, options=ConversionOptions(page_size="A4"))
    page = PdfReader(output).pages[0]
    assert float(page.mediabox.width) == pytest.approx(200.0)


def test_broken_pdf_is_skipped_with_reason(tmp_path):
    good = create_image(tmp_path / "ok.png", (30, 30))
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    output = tmp_path / "out.pdf"
    result = convert_to_pdf([good, broken], output)
    assert result.page_count == 1
    assert [item.path.name for item in result.skipped] == ["broken.pdf"]


def test_outline_counts_pdf_pages(tmp_path):
    existing = make_pdf(tmp_path / "doc.pdf", pages=3)
    output = tmp_path / "out.pdf"
    convert_to_pdf([existing], output, options=ConversionOptions(outline=True))
    assert [item.title for item in PdfReader(output).outline] == ["doc.pdf (3ページ)"]


def test_inspect_pdf_reports_page_count_and_size(tmp_path):
    existing = make_pdf(tmp_path / "doc.pdf", pages=4, size=(100 * MM_TO_PT, 148 * MM_TO_PT))
    pages, width, height = inspect_pdf(existing)
    assert pages == 4
    assert width == pytest.approx(100, abs=0.01)
    assert height == pytest.approx(148, abs=0.01)


def test_output_size_is_reported(tmp_path):
    source = create_image(tmp_path / "source.png", (30, 30))
    output = tmp_path / "out.pdf"
    result = convert_to_pdf([source], output)
    assert result.output_size == output.stat().st_size > 0
