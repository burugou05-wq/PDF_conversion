"""Command-line frontend to the same conversion engine as the desktop app."""

import argparse
import logging
import sys
from pathlib import Path

from file_model import FileModel
from image_processor import DEFAULT_DPI, ConversionOptions, convert_to_pdf, inspect_image


def configure_console_encoding():
    """Keep Japanese CLI messages safe when Windows redirects output to a pipe."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main():
    configure_console_encoding()
    parser = argparse.ArgumentParser(description="画像を指定順でPDFに変換します")
    parser.add_argument("images", nargs="+", type=Path, help="画像またはフォルダ")
    parser.add_argument("-o", "--output", required=True, type=Path)
    parser.add_argument("--page", choices=["A4", "A3", "Letter"])
    parser.add_argument("--margin", type=float, default=0)
    parser.add_argument("--quality", choices=["original", "compact"], default="original")
    parser.add_argument("--background", choices=["white", "black", "gray"], default="white")
    parser.add_argument(
        "--default-dpi",
        type=float,
        default=DEFAULT_DPI,
        help="DPI情報がない画像に使う既定値 (default: 96)",
    )
    parser.add_argument("--no-auto-rotate", action="store_true")
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
        options = ConversionOptions(
            quality=arguments.quality,
            page_size=arguments.page,
            margin_mm=arguments.margin,
            bg_color=colors[arguments.background],
            auto_rotate=not arguments.no_auto_rotate,
            default_dpi=arguments.default_dpi,
        )
        if arguments.verbose:
            for path in model.paths:
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
    print(f"{result.output_path}: {result.page_count}ページ")
    for item in result.skipped:
        print(f"スキップ: {item.path.name}: {item.reason}", file=sys.stderr)
    return 2 if result.skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
