"""Command-line frontend to the same conversion engine as the desktop app."""

import argparse
import logging
import sys
from pathlib import Path

from file_model import FileModel
from image_processor import (
    ALIGNMENTS,
    CUSTOM_PAGE_SIZE,
    DEFAULT_DPI,
    PAGE_SIZES_MM,
    ConversionOptions,
    convert_to_pdf,
    inspect_image,
    is_pdf_input,
)


def configure_console_encoding():
    """Keep Japanese CLI messages safe when Windows redirects output to a pipe."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def parse_page(value):
    """Accept a named size (A4, B5, ...) or "<width>x<height>" in millimetres."""
    if value in PAGE_SIZES_MM:
        return value, None
    text = value.lower().replace("×", "x")
    if "x" in text:
        width_text, _, height_text = text.partition("x")
        try:
            return CUSTOM_PAGE_SIZE, (float(width_text), float(height_text))
        except ValueError:
            pass
    names = ", ".join(PAGE_SIZES_MM)
    raise argparse.ArgumentTypeError(f"用紙は {names} または 幅x高さ(mm) で指定してください")


def main():
    configure_console_encoding()
    parser = argparse.ArgumentParser(description="画像を指定順でPDFに変換します")
    parser.add_argument("images", nargs="+", type=Path, help="画像・PDFまたはフォルダ")
    parser.add_argument("-o", "--output", required=True, type=Path)
    parser.add_argument(
        "--page",
        type=parse_page,
        help=f"用紙: {', '.join(PAGE_SIZES_MM)} または 幅x高さ(mm) 例: 100x148",
    )
    parser.add_argument("--margin", type=float, default=0)
    parser.add_argument("--quality", choices=["original", "compact"], default="original")
    parser.add_argument(
        "--compact-dpi", type=int, default=150, help="軽量化モードの最大DPI (36〜600)"
    )
    parser.add_argument(
        "--jpeg-quality", type=int, default=85, help="軽量化モードのJPEG品質 (1〜100)"
    )
    parser.add_argument("--background", choices=["white", "black", "gray"], default="white")
    parser.add_argument(
        "--default-dpi",
        type=float,
        default=DEFAULT_DPI,
        help="DPI情報がない画像に使う既定値 (default: 96)",
    )
    parser.add_argument("--no-auto-rotate", action="store_true")
    parser.add_argument(
        "--fit-to-page", action="store_true", help="小さな画像を用紙いっぱいに拡大する"
    )
    parser.add_argument(
        "--align", choices=sorted(ALIGNMENTS), default="center", help="用紙上の配置"
    )
    parser.add_argument("--title", help="PDFのタイトル")
    parser.add_argument("--author", help="PDFの作成者")
    parser.add_argument("--subject", help="PDFの件名")
    parser.add_argument("--keywords", help="PDFのキーワード")
    parser.add_argument(
        "--outline", action="store_true", help="入力ファイルごとにしおりを付ける"
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--verbose", action="store_true", help="各画像のDPI取得元とICC情報を表示"
    )
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    try:
        model = FileModel()
        for path in arguments.images:
            if not path.exists():
                raise ValueError(f"入力が存在しません: {path}")
        model.add(arguments.images)
        colors = {"white": (255, 255, 255), "black": (0, 0, 0), "gray": (180, 180, 180)}
        page_size, custom_page = arguments.page or (None, None)
        metadata = {
            key: value
            for key, value in (
                ("title", arguments.title),
                ("author", arguments.author),
                ("subject", arguments.subject),
                ("keywords", arguments.keywords),
            )
            if value
        }
        options = ConversionOptions(
            quality=arguments.quality,
            page_size=page_size,
            custom_page_mm=custom_page,
            margin_mm=arguments.margin,
            bg_color=colors[arguments.background],
            auto_rotate=not arguments.no_auto_rotate,
            default_dpi=arguments.default_dpi,
            compact_dpi=arguments.compact_dpi,
            jpeg_quality=arguments.jpeg_quality,
            fit_to_page=arguments.fit_to_page,
            alignment=arguments.align,
            metadata=metadata or None,
            outline=arguments.outline,
        )
        if arguments.verbose:
            for path in model.paths:
                if is_pdf_input(path):
                    print(f"情報: {path.name}: PDF（そのまま結合）", file=sys.stdout)
                    continue
                try:
                    info = inspect_image(path, options.default_dpi)
                    dpi = info.dpi
                    print(
                        f"情報: {path.name}: {dpi.horizontal:g} × {dpi.vertical:g} DPI "
                        f"({dpi.source}); ICC {info.icc_profile}",
                        file=sys.stdout,
                    )
                except Exception as error:
                    print(f"情報: {path.name}: DPI/ICCを読めません: {error}", file=sys.stderr)
        result = convert_to_pdf(
            model.paths, arguments.output, options=options, overwrite=arguments.overwrite
        )
    except (ValueError, OSError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1
    print(f"{result.output_path}: {result.page_count}ページ ({result.output_size / 1024:.1f} KB)")
    for item in result.skipped:
        print(f"スキップ: {item.path.name}: {item.reason}", file=sys.stderr)
    return 2 if result.skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
