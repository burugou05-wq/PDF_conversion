import importlib.util

import pytest
from PIL import Image
from pypdf import PdfReader

from image_processor import ConversionOptions, convert_to_pdf


@pytest.mark.parametrize(
    "format_name, extension",
    [
        ("PNG", "png"),
        ("JPEG", "jpg"),
        ("BMP", "bmp"),
        ("GIF", "gif"),
        ("WEBP", "webp"),
        ("TIFF", "tiff"),
    ],
)
def test_supported_formats(tmp_path, format_name, extension):
    source = tmp_path / f"input.{extension}"
    with Image.new("RGB", (64, 80), "green") as image:
        image.save(source, format_name)
    output = tmp_path / "output.pdf"
    result = convert_to_pdf([source], output)
    assert result.page_count == 1
    assert not result.skipped


@pytest.mark.parametrize(
    "format_name, extension, plugin",
    [
        ("AVIF", "avif", "pillow_avif"),
        ("HEIF", "heic", "pillow_heif"),
    ],
)
def test_optional_formats(tmp_path, format_name, extension, plugin):
    if importlib.util.find_spec(plugin) is None:
        pytest.skip("Optional codec not installed")
    source = tmp_path / f"input.{extension}"
    with Image.new("RGB", (64, 80), "green") as image:
        image.save(source, format_name)
    result = convert_to_pdf([source], tmp_path / "output.pdf")
    assert result.page_count == 1
    assert not result.skipped


def test_animated_gif_keeps_all_frames(tmp_path):
    source = tmp_path / "animation.gif"
    with Image.new("RGB", (64, 80), "red") as first, Image.new("RGB", (64, 80), "blue") as second:
        first.save(source, save_all=True, append_images=[second], duration=100, loop=0)
    result = convert_to_pdf(
        [source], tmp_path / "output.pdf", options=ConversionOptions(page_size="A4", margin_mm=10)
    )
    assert result.page_count == 2


def test_page_order_matches_input(tmp_path):
    paths = []
    for index, color in enumerate(["red", "green", "blue"]):
        path = tmp_path / f"{index}.png"
        with Image.new("RGB", (20, 30), color) as image:
            image.save(path)
        paths.append(path)
    output = tmp_path / "output.pdf"
    convert_to_pdf(paths[::-1], output)
    colors = [
        next(iter(page.images)).image.convert("RGB").getpixel((0, 0))
        for page in PdfReader(output).pages
    ]
    assert colors == [(0, 0, 255), (0, 128, 0), (255, 0, 0)]
