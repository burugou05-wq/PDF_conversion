"""
image_processor.py - 画像処理と PDF 変換ロジック

画像形式の判定、一時ファイル生成、マルチスレッド並列処理を担当。
"""

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing

from PIL import Image

# DPI対応・ライブラリ検出コード（img2pdf_app.py から移植）
try:
    from turbojpeg import TurboJPEG, TJPF_RGB, TJSAMP_444
    _HAS_TURBO = True
    _turbo = TurboJPEG()
except Exception:
    _HAS_TURBO = False

try:
    import img2pdf as _img2pdf
    _HAS_IMG2PDF = True
except Exception:
    _HAS_IMG2PDF = False

# 画像形式定義
IMG2PDF_NATIVE = frozenset({'.jpg', '.jpeg', '.png'})
NEED_CONVERT = frozenset({'.avif', '.heif', '.heic', '.webp', '.bmp', '.gif', '.tiff', '.tif'})

PAGE_SIZES_MM = {
    "A4":     (210.0, 297.0),
    "A3":     (297.0, 420.0),
    "Letter": (215.9, 279.4),
}

def mm_to_px(mm: float, dpi: float) -> int:
    """mm をピクセルに変換"""
    return max(1, int(mm / 25.4 * dpi))

def open_as_rgb(path: str, bg_color=(255, 255, 255)) -> Image.Image:
    """
    PIL で画像を開き RGB に変換。
    透過画像はbg_color で背景合成。
    """
    img = Image.open(path)
    has_alpha = img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info
    )
    if has_alpha:
        bg = Image.new("RGB", img.size, bg_color)
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[3])
        return bg
    return img.convert("RGB")

def make_tmp_png(img: Image.Image, tmp_files: list, dpi=None) -> str:
    """PIL Image を一時 PNG に書き出す。compress_level=1 で高速化"""
    import tempfile
    t = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    t.close()
    save_kwargs = dict(format='PNG', compress_level=1)
    if dpi:
        save_kwargs['dpi'] = (int(round(dpi[0])), int(round(dpi[1])))
    img.save(t.name, **save_kwargs)
    tmp_files.append(t.name)
    return t.name

def make_tmp_jpg(img: Image.Image, tmp_files: list, quality: int = 95, dpi=None) -> str:
    """
    PIL Image を一時 JPEG に書き出す。
    TurboJPEG が使える場合は使用（3-5倍高速）。
    """
    import tempfile
    import numpy as np
    
    t = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
    t.close()
    
    if _HAS_TURBO and dpi is None:
        arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
        jpg_bytes = _turbo.encode(arr, quality=quality,
                                  pixel_format=TJPF_RGB,
                                  jpeg_subsample=TJSAMP_444)
        with open(t.name, 'wb') as f:
            f.write(jpg_bytes)
    else:
        save_kwargs = dict(format='JPEG', quality=quality, subsampling=0)
        if dpi:
            save_kwargs['dpi'] = (int(round(dpi[0])), int(round(dpi[1])))
        img.save(t.name, **save_kwargs)
    
    tmp_files.append(t.name)
    return t.name

def is_lossless_webp(path: str) -> bool:
    """WebP がロスレスか判定（ヘッダー読み込み）"""
    try:
        with open(path, "rb") as f:
            header = f.read(16)
        return len(header) >= 16 and header[8:12] == b'WEBP' and header[12:16] == b'VP8L'
    except Exception:
        return False

def apply_layout(img: Image.Image, page_size_mm, margin_mm: float,
                 bg_color=(255, 255, 255), src_dpi=None) -> Image.Image:
    """
    ページサイズ・余白に合わせてレイアウトを適用。
    - 縮小のみ（拡大なし）
    - 横長画像は用紙を自動回転
    """
    if page_size_mm is None and margin_mm == 0:
        return img

    orig_w, orig_h = img.size

    if page_size_mm is not None:
        pw_mm, ph_mm = page_size_mm
        img_landscape = orig_w > orig_h
        page_landscape = pw_mm > ph_mm
        
        if img_landscape != page_landscape:
            pw_mm, ph_mm = ph_mm, pw_mm  # 用紙を回転

        inner_w_mm = max(1.0, pw_mm - margin_mm * 2)
        inner_h_mm = max(1.0, ph_mm - margin_mm * 2)
        
        long_px = max(orig_w, orig_h)
        long_mm = max(pw_mm, ph_mm)
        dpi_est = long_px / (long_mm / 25.4)
        
        page_w_px = mm_to_px(pw_mm, dpi_est)
        page_h_px = mm_to_px(ph_mm, dpi_est)
        inner_w_px = mm_to_px(inner_w_mm, dpi_est)
        inner_h_px = mm_to_px(inner_h_mm, dpi_est)
        
        scale = min(1.0, inner_w_px / orig_w, inner_h_px / orig_h)
        fit_w = max(1, int(orig_w * scale))
        fit_h = max(1, int(orig_h * scale))
        
        img = img.resize((fit_w, fit_h), Image.LANCZOS)
        canvas = Image.new("RGB", (page_w_px, page_h_px), bg_color)
        ox = (page_w_px - img.width) // 2
        oy = (page_h_px - img.height) // 2
        canvas.paste(img, (ox, oy))
        return canvas
    else:
        ref_dpi = src_dpi[0] if src_dpi else 96
        margin_px = mm_to_px(margin_mm, ref_dpi)
        nw = orig_w + margin_px * 2
        nh = orig_h + margin_px * 2
        canvas = Image.new("RGB", (nw, nh), bg_color)
        canvas.paste(img, (margin_px, margin_px))
        return canvas

def convert_to_pdf(image_paths, output_path, progress_cb=None,
                   quality="lossless", page_size=None, margin_mm=0,
                   bg_color=(255, 255, 255)):
    """
    複数画像を PDF に変換（マルチスレッド並列処理）。
    
    Args:
        image_paths: 画像パスのリスト
        output_path: 出力 PDF パス
        progress_cb: 進捗コールバック（0-100）
        quality: "lossless" | "standard"
        page_size: None | "A4" | "A3" | "Letter"
        margin_mm: 余白（mm）
        bg_color: RGB tuple
    
    Returns:
        スキップされたファイル名のリスト
    """
    if not _HAS_IMG2PDF:
        raise RuntimeError(
            "PDF変換エンジンの読み込みに失敗しました。\n"
            "img2pdf ライブラリをインストール下さい。")

    skipped = []
    tmp_files = []
    tmp_lock = threading.Lock()
    total = len(image_paths)

    page_size_mm = PAGE_SIZES_MM.get(page_size) if page_size else None
    needs_layout = (page_size_mm is not None) or (margin_mm > 0)
    q_high = 95
    q_std = 85

    def _reg(path):
        with tmp_lock:
            tmp_files.append(path)
        return path

    def process_one(args):
        i, path = args
        try:
            ext = os.path.splitext(path)[1].lower()
            q = q_high if quality == "lossless" else q_std

            if not needs_layout:
                if ext in IMG2PDF_NATIVE:
                    return i, path

                elif ext in NEED_CONVERT:
                    img = Image.open(path)
                    src_dpi = img.info.get("dpi")

                    if ext in ('.tiff', '.tif') and getattr(img, 'n_frames', 1) > 1:
                        return i, path

                    has_alpha = img.mode in ("RGBA", "LA") or (
                        img.mode == "P" and "transparency" in img.info
                    )

                    if ext == '.webp':
                        if is_lossless_webp(path) and not has_alpha:
                            return i, _reg(make_tmp_png(img.convert("RGB"), tmp_files, dpi=src_dpi))
                        elif not has_alpha:
                            return i, _reg(make_tmp_jpg(img.convert("RGB"), tmp_files, q, dpi=src_dpi))

                    if has_alpha:
                        return i, _reg(make_tmp_png(open_as_rgb(path, bg_color), tmp_files, dpi=src_dpi))
                    else:
                        return i, _reg(make_tmp_jpg(img.convert("RGB"), tmp_files, q, dpi=src_dpi))
                else:
                    img = Image.open(path)
                    src_dpi = img.info.get("dpi")
                    return i, _reg(make_tmp_png(open_as_rgb(path, bg_color), tmp_files, dpi=src_dpi))

            else:
                img = Image.open(path)
                src_dpi = img.info.get("dpi")
                img = open_as_rgb(path, bg_color)
                img = apply_layout(img, page_size_mm, margin_mm, bg_color, src_dpi=src_dpi)
                return i, _reg(make_tmp_jpg(img, tmp_files, q))

        except Exception:
            return i, None

    workers = min(total, max(2, multiprocessing.cpu_count()))
    results = [None] * total

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(process_one, (i, p)): i for i, p in enumerate(image_paths)}
        done = 0
        for fut in as_completed(futures):
            i, embed_path = fut.result()
            if embed_path is None:
                skipped.append(os.path.basename(image_paths[i]))
            else:
                results[i] = embed_path
            done += 1
            if progress_cb:
                progress_cb(int(done / total * 88))

    embed_paths = [p for p in results if p is not None]

    if not embed_paths:
        raise ValueError(
            "変換できる画像がありません\n"
            "スキップ: " + ", ".join(skipped[:5]))

    try:
        _lib = sys.modules.get("img2pdf") or _img2pdf
        pdf_bytes = _lib.convert(embed_paths)
        if progress_cb:
            progress_cb(96)

        with open(output_path, "wb") as f:
            f.write(pdf_bytes)

        if progress_cb:
            progress_cb(100)
        
        return skipped

    finally:
        for t in tmp_files:
            try:
                os.unlink(t)
            except OSError:
                pass

def make_thumbnail(path, size=(160, 120)):
    """画像のサムネイルを生成"""
    try:
        from PIL import ImageTk
        img = Image.open(path)
        img.thumbnail(size, Image.LANCZOS)
        bg = Image.new("RGB", size, (245, 245, 245))
        offset = ((size[0] - img.width) // 2, (size[1] - img.height) // 2)
        if img.mode in ("RGBA", "LA", "P"):
            bg.paste(img, offset, img.convert("RGBA").split()[3])
        else:
            bg.paste(img.convert("RGB"), offset)
        return ImageTk.PhotoImage(bg)
    except Exception:
        return None
