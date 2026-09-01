import os, sys, threading, urllib.request, json, shutil, traceback, re

# ── Windows 高DPI対応 ────────────────────────────────────────────
# EXEのmanifest（dpi_aware.manifest）に PerMonitorV2 を宣言するのが第一手段。
# それに加えてコード側からも API を呼ぶことで、manifest なし環境や
# Python直接実行時でもぼやけを防ぐ。
# ※ tkinter / Tk() の生成より前に必ず呼ぶこと。
def _set_dpi_aware():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import ctypes.wintypes

        # ── 方法①: SetProcessDpiAwarenessContext（Windows 10 1607以降）
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        # これが最優先・最高品質。Per-Monitor V2 = モニターごとに動的DPI追従
        CONTEXT_PER_MONITOR_V2 = -4
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(
                ctypes.wintypes.HANDLE(CONTEXT_PER_MONITOR_V2))
            return  # 成功したらここで終わり
        except Exception:
            pass

        # ── 方法②: SetProcessDpiAwareness（Windows 8.1以降 / shcore.dll）
        # 2 = PROCESS_PER_MONITOR_DPI_AWARE
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return
        except Exception:
            pass

        # ── 方法③: SetProcessDPIAware（Vista以降 / 最終フォールバック）
        # System DPI Aware（プライマリモニター基準だが非対応よりはるかにマシ）
        ctypes.windll.user32.SetProcessDPIAware()

    except Exception:
        pass  # Windows以外 or 失敗しても起動は継続

_set_dpi_aware()

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _HAS_DND = True
except Exception:
    _HAS_DND = False

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageTk
except Exception as e:
    messagebox.showerror("起動エラー", f"Pillowが見つかりません:\n{e}")
    sys.exit(1)

try:
    import pillow_avif  # noqa
except Exception:
    pass
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

_img2pdf = None
try:
    import img2pdf as _img2pdf
    _HAS_IMG2PDF = True
except Exception:
    _HAS_IMG2PDF = False

# TurboJPEG: 利用可能なら使う（3〜5倍速、XnConvert同等エンジン）
try:
    from turbojpeg import TurboJPEG, TJPF_RGB, TJSAMP_444
    _turbo = TurboJPEG()
    _HAS_TURBO = True
except Exception:
    _HAS_TURBO = False

VERSION = "1.0"
# ── アップデートチェック用 URL ──────────────────────────────────
# 配布時に実際の URL へ変更してください。
# 例) UPDATE_URL = "https://example.com/app/version.json"
# None のままだとアップデートチェック機能は無効です。
# build.py のコメント参照。
UPDATE_URL = None
SUPPORTED_EXTS = ('.jpg', '.jpeg', '.avif', '.webp', '.png', '.bmp', '.gif', '.tiff', '.tif')

# ── カラーパレット ────────────────────────────────────────────────
C = {
    "bg":       "#F5F5F5",
    "surface":  "#FFFFFF",
    "border":   "#E0E0E0",
    "accent":   "#1A73E8",
    "accent_h": "#1557B0",
    "text":     "#202124",
    "subtext":  "#5F6368",
    "success":  "#188038",
    "warn":     "#E37400",
    "error":    "#C5221F",
    "list_bg":  "#FAFAFA",
    "sel_bg":   "#D2E3FC",
    "hover":    "#E8F0FE",
}

def apply_theme(root):
    style = ttk.Style(root)
    # vista/winnative/xpnative はネイティブ描画のためカスタム色が完全無視される。
    # clam テーマは純粋な Tk 描画なので foreground/background が確実に反映される。
    for t in ("clam", "alt", "default"):
        if t in style.theme_names():
            style.theme_use(t)
            break
    root.configure(bg=C["bg"])

    style.configure(".",
        background=C["bg"],
        foreground=C["text"],
        troughcolor=C["border"],
        selectbackground=C["sel_bg"],
        selectforeground=C["text"],
        fieldbackground=C["surface"],
        font=("Yu Gothic UI", 11))

    style.configure("TFrame",       background=C["bg"])
    style.configure("Surface.TFrame", background=C["surface"], relief="flat")
    style.configure("TLabel",       background=C["bg"],      foreground=C["text"])
    style.configure("Surface.TLabel", background=C["surface"], foreground=C["text"])
    style.configure("Sub.TLabel",   background=C["bg"],      foreground=C["subtext"])
    style.configure("Surface.Sub.TLabel", background=C["surface"], foreground=C["subtext"])

    style.configure("TLabelframe",
        background=C["bg"], bordercolor=C["border"], relief="groove")
    style.configure("TLabelframe.Label",
        background=C["bg"], foreground=C["subtext"])
    style.configure("Surface.TLabelframe",
        background=C["surface"], bordercolor=C["border"], relief="groove")
    style.configure("Surface.TLabelframe.Label",
        background=C["surface"], foreground=C["subtext"])

    style.configure("TSeparator",   background=C["border"])

    # ── ボタン共通マップ ─────────────────────────────────────────
    # clam テーマなら configure + map の foreground が確実に効く
    def _btn(name, bg, fg, pad, font=None, active_bg=None, disabled_bg=None, disabled_fg=None):
        kw = dict(background=bg, foreground=fg, padding=pad,
                  relief="flat", borderwidth=1, bordercolor=C["border"],
                  focusthickness=0, focuscolor=bg)
        if font:
            kw["font"] = font
        style.configure(name, **kw)
        style.map(name,
            background=[("active",   active_bg or C["hover"]),
                        ("pressed",  active_bg or C["hover"]),
                        ("disabled", disabled_bg or C["border"])],
            foreground=[("disabled", disabled_fg or C["subtext"]),
                        ("active",   fg),
                        ("pressed",  fg),
                        ("!disabled", fg)])

    _btn("TButton",
         bg=C["surface"], fg=C["text"], pad=(10, 5))
    _btn("Toolbar.TButton",
         bg=C["surface"], fg=C["text"], pad=(8, 4))
    _btn("Accent.TButton",
         bg=C["accent"], fg="#FFFFFF", pad=(16, 8),
         font=("Yu Gothic UI", 10, "bold"),
         active_bg=C["accent_h"],
         disabled_bg="#BDBDBD", disabled_fg="#FFFFFF")

    style.configure("TNotebook",      background=C["bg"], tabmargins=[0, 0, 0, 0])
    style.configure("TNotebook.Tab",  background=C["border"], foreground=C["subtext"],
                    padding=[16, 7])
    style.map("TNotebook.Tab",
        background=[("selected", C["surface"]), ("active", C["hover"])],
        foreground=[("selected", C["accent"]),  ("active", C["text"])])

    style.configure("TProgressbar",
        troughcolor=C["border"], background=C["accent"],
        thickness=4, borderwidth=0)

    style.configure("TRadiobutton",
        background=C["surface"], foreground=C["text"], focusthickness=0)
    style.map("TRadiobutton",
        background=[("active", C["surface"])],
        foreground=[("active", C["text"])])

    style.configure("TCheckbutton",
        background=C["surface"], foreground=C["text"], focusthickness=0)
    style.map("TCheckbutton",
        background=[("active", C["surface"])],
        foreground=[("active", C["text"])])

    style.configure("TEntry",
        fieldbackground=C["surface"], foreground=C["text"],
        bordercolor=C["border"], lightcolor=C["border"],
        insertcolor=C["text"], relief="flat")
    style.map("TEntry",
        bordercolor=[("focus", C["accent"])])

    style.configure("TScrollbar",
        background=C["border"], troughcolor=C["bg"],
        arrowcolor=C["subtext"], borderwidth=0, relief="flat")
    style.map("TScrollbar",
        background=[("active", C["subtext"])])

# ══════════════════════════════════════════════════════════════════
#  画像処理
# ══════════════════════════════════════════════════════════════════

# img2pdf がそのままPDFに埋め込める形式（再エンコード不要）
_IMG2PDF_NATIVE = frozenset({'.jpg', '.jpeg', '.png'})

# PIL で開いて PNG 変換が必要な形式
_NEED_CONVERT = frozenset({'.avif', '.heif', '.heic', '.webp',
                            '.bmp', '.gif', '.tiff', '.tif'})

# ページサイズ定義（単位: mm）
_PAGE_SIZES_MM = {
    "A4":     (210.0, 297.0),
    "A3":     (297.0, 420.0),
    "Letter": (215.9, 279.4),
}

def _mm_to_px(mm: float, dpi: float) -> int:
    return max(1, int(mm / 25.4 * dpi))

def _open_as_rgb(path: str, bg_color=(255, 255, 255)) -> "Image.Image":
    """PIL で画像を開き、RGBに変換して返す。
    アルファチャンネルを持つ画像（RGBA/LA、または透過キーを持つPモード）は
    bg_color で合成してからRGB化する。透過なしPモードは直接RGB変換。"""
    img = Image.open(path)
    # Pモード（パレット）は透過キーがある場合のみアルファ合成が必要
    has_alpha = img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info
    )
    if has_alpha:
        bg = Image.new("RGB", img.size, bg_color)
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[3])
        return bg
    return img.convert("RGB")

def _make_tmp_png(img: "Image.Image", tmp_files: list) -> str:
    """PIL Image を一時PNGファイルに書き出してパスを返す。
    compress_level=1 で書き込みを高速化（PDFに埋め込むので最終サイズへの影響は軽微）。
    tmp_files リストに追加するので呼び出し元で finally 管理すること。"""
    import tempfile
    t = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    t.close()
    img.save(t.name, format='PNG', compress_level=1)
    tmp_files.append(t.name)
    return t.name

def _make_tmp_jpg(img: "Image.Image", tmp_files: list, quality: int = 95) -> str:
    """PIL Image を一時JPEGファイルに書き出してパスを返す。
    TurboJPEG が使えるなら使う（3〜5倍速、4:4:4サブサンプリング）。"""
    import tempfile
    import numpy as np
    t = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
    t.close()
    if _HAS_TURBO:
        arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
        jpg_bytes = _turbo.encode(arr, quality=quality,
                                  pixel_format=TJPF_RGB,
                                  jpeg_subsample=TJSAMP_444)
        with open(t.name, 'wb') as f:
            f.write(jpg_bytes)
    else:
        img.save(t.name, format='JPEG', quality=quality, subsampling=0)
    tmp_files.append(t.name)
    return t.name

def _is_lossless_webp(path: str) -> bool:
    """WebPファイルのヘッダーを読んでロスレスか判定。
    VP8L チャンクを持つものだけがロスレス。"""
    try:
        with open(path, "rb") as f:
            header = f.read(16)
        return len(header) >= 16 and header[8:12] == b'WEBP' and header[12:16] == b'VP8L'
    except Exception:
        return False

def _apply_layout(img: "Image.Image", page_size_mm, margin_mm: float,
                  bg_color=(255, 255, 255), src_dpi=None):
    """ページサイズ・余白に合わせてレイアウトを適用する。
    - page_size_mm : (w_mm, h_mm) または None
    - margin_mm    : 余白（mm）
    - bg_color     : 余白部分の背景色
    - src_dpi      : 元画像のDPI（余白px計算に使用。None時は96dpiで近似）
    - 縮小のみ行い、拡大はしない（情報を捏造しない）
    - ページサイズ指定なし・余白のみの場合はキャンバス追加だけ
    - ページサイズ指定あり・横長画像は自動回転して有効面積を最大化する
    戻り値: 加工済み Image（必要なければ元の img をそのまま返す）"""
    if page_size_mm is None and margin_mm == 0:
        return img  # 何もしない

    orig_w, orig_h = img.size

    if page_size_mm is not None:
        pw_mm, ph_mm = page_size_mm
        # auto-rotate: 画像と用紙の向きが異なる場合は用紙を回転して有効面積を最大化
        # 例）横長画像（4:3）→ A4縦（2:3）の場合、A4横（3:2）に変えてフィットさせる
        img_landscape  = orig_w > orig_h
        page_landscape = pw_mm  > ph_mm
        if img_landscape != page_landscape:
            pw_mm, ph_mm = ph_mm, pw_mm   # 用紙を90度回転

        # 余白を引いた有効領域（mm）
        inner_w_mm = max(1.0, pw_mm - margin_mm * 2)
        inner_h_mm = max(1.0, ph_mm - margin_mm * 2)
        # ページの px サイズは「元画像の最大辺をページの長辺に合わせる」で決定
        long_px = max(orig_w, orig_h)
        long_mm = max(pw_mm, ph_mm)
        dpi_est = long_px / (long_mm / 25.4)
        # ページキャンバスの px サイズ
        page_w_px  = _mm_to_px(pw_mm,      dpi_est)
        page_h_px  = _mm_to_px(ph_mm,      dpi_est)
        inner_w_px = _mm_to_px(inner_w_mm, dpi_est)
        inner_h_px = _mm_to_px(inner_h_mm, dpi_est)
        # アスペクト比を維持しつつ有効領域に収まるスケール（縮小のみ）
        scale = min(1.0,
                    inner_w_px / orig_w,
                    inner_h_px / orig_h)
        fit_w = max(1, int(orig_w * scale))
        fit_h = max(1, int(orig_h * scale))
        img = img.resize((fit_w, fit_h), Image.LANCZOS)
        canvas = Image.new("RGB", (page_w_px, page_h_px), bg_color)
        ox = (page_w_px - img.width)  // 2
        oy = (page_h_px - img.height) // 2
        canvas.paste(img, (ox, oy))
        return canvas
    else:
        # 余白のみ追加（画像サイズは変えない）
        # 余白 mm → px の変換に元画像の DPI を使う。
        # DPI 不明時は 96dpi で近似（スクリーン画像の標準値）。
        ref_dpi = src_dpi[0] if src_dpi else 96
        margin_px = _mm_to_px(margin_mm, ref_dpi)
        nw = orig_w + margin_px * 2
        nh = orig_h + margin_px * 2
        canvas = Image.new("RGB", (nw, nh), bg_color)
        canvas.paste(img, (margin_px, margin_px))
        return canvas

def convert_to_pdf(image_paths, output_path, progress_cb=None,
                   quality="lossless", page_size=None, margin_mm=0,
                   bg_color=(255, 255, 255)):
    """
    quality   : "lossless" | "standard"
    page_size : None（元サイズ維持）| "A4" | "A3" | "Letter"
    margin_mm : 余白（mm）。0 = なし
    bg_color  : 透過画像の背景色 RGB tuple

    ── 劣化の原則 ──────────────────────────────────────────────────
    lossless:
      前処理なし（page_size=None, margin_mm=0）
        JPEG/PNG           → バイト列をそのまま埋め込む（劣化ゼロ）
        多ページTIFF       → バイト列をそのまま img2pdf へ（全フレーム・劣化ゼロ）
        ロスレスWebP       → PNG変換（compress_level=1, 完全無劣化・並列化で高速）
        ロッシーWebP       → TurboJPEG q=95 4:4:4（元がロッシーなので追加劣化なし）
        その他（透過なし） → TurboJPEG q=95 4:4:4（元画像DPIを引き継ぐ）
        その他（透過あり） → PNG変換1回のみ（不可避、元画像DPIを引き継ぐ）
      前処理あり（ページサイズ合わせ or 余白）
        縮小のみ（LANCZOS）→ TurboJPEG q=95 4:4:4
        横長画像は用紙を自動回転して有効面積を最大化（auto-rotate）
        余白px計算は元画像DPIを参照（不明時は96dpi）

    standard:
      前処理なし
        JPEG/PNG  → バイト列をそのまま埋め込む（劣化ゼロ）
        その他    → TurboJPEG q=85 4:4:4
      前処理あり
        縮小のみ（LANCZOS）→ TurboJPEG q=85 4:4:4

    ── 速度 ────────────────────────────────────────────────────────
    - TurboJPEG使用でJPEGエンコードが3〜5倍速（XnConvert同等エンジン）
    - PNG compress_level=1 で書き込み高速化
    - ThreadPoolExecutor で画像変換を並列化
    ────────────────────────────────────────────────────────────────
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import multiprocessing

    skipped   = []
    tmp_files = []
    tmp_lock  = threading.Lock()
    total     = len(image_paths)

    if not _HAS_IMG2PDF:
        raise RuntimeError(
            "PDF変換エンジンの読み込みに失敗しました。\n"
            "このEXEが正しく配布されているか確認してください。")

    page_size_mm = _PAGE_SIZES_MM.get(page_size) if page_size else None
    needs_layout = (page_size_mm is not None) or (margin_mm > 0)
    q_high = 95   # lossless時のJPEG品質（XnConvert同等以上）
    q_std  = 85   # standard時のJPEG品質

    def _reg(path):
        with tmp_lock:
            tmp_files.append(path)
        return path

    def _tmp_jpg(img, quality, dpi=None):
        """PIL Image を一時JPEGとして書き出す。
        dpi が指定されていれば JFIF ヘッダーに書き込む（img2pdf のページサイズ計算に使われる）。
        TurboJPEG はDPI埋め込みに対応していないため、DPI指定時は PIL フォールバックを使う。"""
        import tempfile, numpy as np
        t = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
        t.close()
        if _HAS_TURBO and dpi is None:
            # TurboJPEG: DPI未指定時のみ使用（高速パス）
            arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
            data = _turbo.encode(arr, quality=quality,
                                 pixel_format=TJPF_RGB,
                                 jpeg_subsample=TJSAMP_444)
            with open(t.name, 'wb') as f:
                f.write(data)
        else:
            # PIL: DPI情報を JFIF ヘッダーに埋め込む
            save_kwargs = dict(format='JPEG', quality=quality, subsampling=0)
            if dpi:
                save_kwargs['dpi'] = (int(round(dpi[0])), int(round(dpi[1])))
            img.save(t.name, **save_kwargs)
        return _reg(t.name)

    def _tmp_png(img, dpi=None):
        """PIL Image を一時PNGとして書き出す。compress_level=1 で高速化。
        dpi が指定されていれば pHYs チャンクに書き込む（img2pdf のページサイズ計算に使われる）。"""
        import tempfile
        t = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        t.close()
        save_kwargs = dict(format='PNG', compress_level=1)
        if dpi:
            save_kwargs['dpi'] = (int(round(dpi[0])), int(round(dpi[1])))
        img.save(t.name, **save_kwargs)
        return _reg(t.name)

    def process_one(args):
        i, path = args
        try:
            ext = os.path.splitext(path)[1].lower()
            q = q_high if quality == "lossless" else q_std

            if not needs_layout:
                if ext in _IMG2PDF_NATIVE:
                    # JPEG/PNG はバイト列をそのまま img2pdf へ（劣化ゼロ・DPI保持）
                    return i, path

                elif ext in _NEED_CONVERT:
                    img = Image.open(path)
                    # 元画像の DPI を取得（変換後も img2pdf へ引き継ぐ）
                    src_dpi = img.info.get("dpi")

                    # 多ページTIFF は img2pdf に直接渡して全フレームを変換させる
                    # （process_one で1枚に変換すると先頭フレームしか出力されない）
                    if ext in ('.tiff', '.tif') and getattr(img, 'n_frames', 1) > 1:
                        return i, path

                    # Pモード（パレット）の透過判定:
                    # 透過キーがある場合のみアルファ合成が必要。なければ直接RGB化。
                    has_alpha = img.mode in ("RGBA", "LA") or (
                        img.mode == "P" and "transparency" in img.info
                    )

                    if ext == '.webp':
                        if _is_lossless_webp(path) and not has_alpha:
                            # ロスレスWebP → PNG変換（完全無劣化）
                            # img2pdf に直接渡すと内部で compress_level=6 の
                            # シングルスレッドPNG変換が走る。事前に
                            # compress_level=1 でPNG化することで並列化でき、
                            # 速度が向上する。PNGはロスレスのためピクセルデータ完全保持。
                            return i, _tmp_png(img.convert("RGB"), dpi=src_dpi)
                        elif not has_alpha:
                            # ロッシーWebP → TurboJPEG（追加劣化なし）
                            return i, _tmp_jpg(img.convert("RGB"), q, dpi=src_dpi)
                        # 透過WebP → 下の共通処理へ

                    if has_alpha:
                        # 透過あり → PNG（背景合成は不可避）
                        return i, _tmp_png(_open_as_rgb(path, bg_color), dpi=src_dpi)
                    else:
                        # 透過なし → TurboJPEG（速度・品質ともにPIL+PNG超え）
                        return i, _tmp_jpg(img.convert("RGB"), q, dpi=src_dpi)
                else:
                    img = Image.open(path)
                    src_dpi = img.info.get("dpi")
                    return i, _tmp_png(_open_as_rgb(path, bg_color), dpi=src_dpi)

            else:
                # ページサイズ合わせ or 余白 → レイアウト後TurboJPEG
                # ページサイズ指定時はpx→mmの変換にDPIを使うため元画像DPIを渡す
                img = Image.open(path)
                src_dpi = img.info.get("dpi")
                img = _open_as_rgb(path, bg_color)
                img = _apply_layout(img, page_size_mm, margin_mm, bg_color,
                                    src_dpi=src_dpi)
                return i, _tmp_jpg(img, q)

        except Exception:
            return i, None

    # ── 並列変換（CPUコア数に合わせてスレッド数を決定）──────────────
    workers = min(total, max(2, multiprocessing.cpu_count()))
    results = [None] * total

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(process_one, (i, p)): i
                   for i, p in enumerate(image_paths)}
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
    try:
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

# ══════════════════════════════════════════════════════════════════
#  オプションパネル（折りたたみ式）
# ══════════════════════════════════════════════════════════════════
class OptionsPanel(ttk.Frame):
    """画質・ページ設定・余白・背景色などをまとめたオプションパネル"""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.configure(style="Surface.TFrame")

        # 公開変数
        self.quality_var    = tk.StringVar(value="lossless")
        self.page_size_var  = tk.StringVar(value="元のサイズ")
        self.margin_var     = tk.StringVar(value="0")    # ラジオ選択用
        self.margin_custom  = tk.StringVar(value="")     # カスタム入力用（空=未使用）
        self.bg_color_var   = tk.StringVar(value="白")
        self.open_after_var = tk.BooleanVar(value=False)

        self._expanded = False
        self._build_toggle()
        self._build_panel()

    def _build_toggle(self):
        hdr = ttk.Frame(self, style="Surface.TFrame")
        hdr.pack(fill="x")
        self._toggle_btn = tk.Label(
            hdr,
            text="▶  オプション設定",
            bg=C["surface"], fg=C["subtext"],
            font=("Yu Gothic UI", 9),
            cursor="hand2", anchor="w")
        self._toggle_btn.pack(side="left", padx=8, pady=4)
        self._toggle_btn.bind("<Button-1>", lambda _: self._toggle())
        hdr.bind("<Button-1>", lambda _: self._toggle())

    def _build_panel(self):
        self._panel = ttk.Frame(self, style="Surface.TFrame")
        # 最初は非表示

        pad = dict(padx=12, pady=3)

        # ── 画質 ─────────────────────────────────────────────────
        qf = ttk.LabelFrame(self._panel, text="変換モード", style="Surface.TLabelframe", padding=(10,6))
        qf.pack(fill="x", **pad)
        for val, lbl, sub in [
            ("lossless",
             "★ 高品質（推奨）",
             "JPEG・PNG は画質を一切変えずに取り込みます。その他の形式も高品質（品質95）で変換します。"),
            ("standard",
             "標準",
             "ファイルサイズを小さくします。画質はやや下がります。"),
        ]:
            row = ttk.Frame(qf, style="Surface.TFrame")
            row.pack(fill="x", pady=2)
            ttk.Radiobutton(row, text=lbl, variable=self.quality_var,
                            value=val, style="TRadiobutton").pack(side="left", padx=4)
            ttk.Label(row, text=sub, style="Surface.Sub.TLabel",
                      font=("Yu Gothic UI", 9)).pack(side="left", padx=(4,0))

        # ── ページサイズ ──────────────────────────────────────────
        pf = ttk.LabelFrame(self._panel, text="ページサイズ", style="Surface.TLabelframe", padding=(10,4))
        pf.pack(fill="x", **pad)
        for val in ["元のサイズ", "A4", "A3", "Letter"]:
            ttk.Radiobutton(pf, text=val, variable=self.page_size_var,
                            value=val, style="TRadiobutton").pack(side="left", padx=8, pady=2)

        # ── 余白 ─────────────────────────────────────────────────
        mf = ttk.LabelFrame(self._panel, text="余白", style="Surface.TLabelframe", padding=(10,4))
        mf.pack(fill="x", **pad)
        mrow = ttk.Frame(mf, style="Surface.TFrame")
        mrow.pack(fill="x")
        for val, lbl in [("0","なし"),("5","5mm"),("10","10mm"),("20","20mm")]:
            ttk.Radiobutton(mrow, text=lbl, variable=self.margin_var,
                            value=val, style="TRadiobutton",
                            command=lambda: self.margin_custom.set("")
                            ).pack(side="left", padx=6)
        ttk.Label(mrow, text="  カスタム:", style="Surface.TLabel").pack(side="left")
        custom_entry = ttk.Entry(mrow, textvariable=self.margin_custom, width=5)
        custom_entry.pack(side="left")
        ttk.Label(mrow, text="mm", style="Surface.TLabel").pack(side="left")
        # カスタム入力されたらラジオ選択を解除（競合防止）
        def _on_custom_edit(*_):
            if self.margin_custom.get().strip():
                self.margin_var.set("")   # ラジオをどれも選択なし状態に
        self.margin_custom.trace_add("write", _on_custom_edit)

        # ── 背景色 ────────────────────────────────────────────────
        bf = ttk.LabelFrame(self._panel, text="背景色（透過画像用）", style="Surface.TLabelframe", padding=(10,4))
        bf.pack(fill="x", **pad)
        for val, lbl in [("白","白"), ("黒","黒"), ("グレー","グレー")]:
            ttk.Radiobutton(bf, text=lbl, variable=self.bg_color_var,
                            value=val, style="TRadiobutton").pack(side="left", padx=8, pady=2)

        # ── その他 ────────────────────────────────────────────────
        of = ttk.LabelFrame(self._panel, text="その他", style="Surface.TLabelframe", padding=(10,4))
        of.pack(fill="x", **pad)
        ttk.Checkbutton(of, text="変換後にPDFを開く",
                        variable=self.open_after_var, style="TCheckbutton").pack(anchor="w", padx=4)


    def _toggle(self):
        self._expanded = not self._expanded
        if self._expanded:
            self._panel.pack(fill="x", pady=(0, 4))
            self._toggle_btn.config(text="▼  オプション設定")
        else:
            self._panel.pack_forget()
            self._toggle_btn.config(text="▶  オプション設定")

    def get_options(self):
        bg_map = {"白": (255,255,255), "黒": (0,0,0), "グレー": (180,180,180)}
        # カスタム入力が有効ならそちらを優先、なければラジオ選択値を使う
        custom = self.margin_custom.get().strip()
        try:
            margin = max(0, int(custom)) if custom else max(0, int(self.margin_var.get()))
        except Exception:
            margin = 0
        ps = self.page_size_var.get()
        return dict(
            quality   = self.quality_var.get(),
            page_size = None if ps == "元のサイズ" else ps,
            margin_mm = margin,
            bg_color  = bg_map.get(self.bg_color_var.get(), (255,255,255)),
            open_after= self.open_after_var.get(),
        )


# ══════════════════════════════════════════════════════════════════
#  共通ステータスバー
# ══════════════════════════════════════════════════════════════════
class StatusBar(ttk.Frame):
    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.configure(style="TFrame")
        self._prog = ttk.Progressbar(self, mode="determinate", length=160)
        self._prog.pack(side="right", padx=8, pady=4)
        self._lbl = ttk.Label(self, text="", style="Sub.TLabel")
        self._lbl.pack(side="left", padx=8)

    def set(self, text, color=None):
        self._lbl.config(text=text,
                         foreground=color if color else C["subtext"])

    def progress(self, v):
        self._prog["value"] = v

    def reset(self):
        self._prog["value"] = 0
        self._lbl.config(text="", foreground=C["subtext"])


# ══════════════════════════════════════════════════════════════════
#  手動選択タブ（Toplevel → メインウィンドウ内に統合）
# ══════════════════════════════════════════════════════════════════
class ManualTab(ttk.Frame):
    THUMB_W, THUMB_H = 180, 140

    def __init__(self, master, status_bar, **kw):
        super().__init__(master, **kw)
        self._status    = status_bar
        self._files     = []   # [(basename, fullpath)]
        self._thumbs    = {}   # fullpath -> PhotoImage
        self._drag_from = None
        self._view_mode = tk.StringVar(value="list")
        self._search_var = tk.StringVar()
        self._filtered  = []
        self._out_var   = tk.StringVar()
        self._grid_sel  = set()   # グリッド選択中のfullpath集合
        self._grid_last_click = None  # Shift選択のアンカーパス
        # サムネイル非同期ロード用
        from concurrent.futures import ThreadPoolExecutor
        self._thumb_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumb")
        self._thumb_pending  = set()   # ロード中のpath集合
        self._build()

    def _build(self):
        # ── ツールバー ──────────────────────────────────────────
        tb = ttk.Frame(self, style="Surface.TFrame")
        tb.pack(fill="x", padx=0, pady=0)

        def tbtn(text, cmd):
            b = ttk.Button(tb, text=text, command=cmd, style="Toolbar.TButton")
            b.pack(side="left", padx=2, pady=4)
            return b

        tbtn("＋ ファイル追加",  self._add_files)
        tbtn("＋ フォルダ追加",  self._add_folder)
        _sep(tb)
        tbtn("↑ 上へ",   self._move_up)
        tbtn("↓ 下へ",   self._move_down)
        tbtn("先頭へ",    self._move_top)
        tbtn("末尾へ",    self._move_bottom)
        _sep(tb)
        tbtn("選択削除",  self._remove_sel)
        tbtn("全削除",   self._clear)
        _sep(tb)
        ttk.Label(tb, text="表示:", style="Surface.TLabel",
                  font=("Yu Gothic UI", 10)).pack(side="left", padx=(4,0))
        for val, lbl in [("list","  リスト"), ("grid","  グリッド")]:
            ttk.Radiobutton(tb, text=lbl, variable=self._view_mode,
                            value=val, command=self._switch_view,
                            style="TRadiobutton").pack(side="left", padx=4)
        self._count_lbl = ttk.Label(tb, text="0 枚", style="Surface.Sub.TLabel")
        self._count_lbl.pack(side="right", padx=10)

        # ── 検索バー ────────────────────────────────────────────
        sf = ttk.Frame(self, style="Surface.TFrame")
        sf.pack(fill="x", padx=8, pady=2)
        ttk.Label(sf, text="🔍", style="Surface.TLabel").pack(side="left")
        self._search_var.trace_add("write", lambda *_: self._refresh())
        ttk.Entry(sf, textvariable=self._search_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(sf, text="✕", width=3,
                   command=lambda: self._search_var.set("")).pack(side="left")

        ttk.Separator(self).pack(fill="x")

        # ── メインエリア ─────────────────────────────────────────
        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        # 左ペイン
        self._left = ttk.Frame(main)
        self._left.pack(side="left", fill="both", expand=True)

        # リスト
        self._list_frame = ttk.Frame(self._left)
        self._lb = tk.Listbox(self._list_frame,
                              selectmode="extended", activestyle="none",
                              font=("Yu Gothic UI", 11),
                              bg=C["list_bg"], fg=C["text"],
                              selectbackground=C["sel_bg"], selectforeground=C["text"],
                              relief="flat", bd=0, highlightthickness=0)
        sb = ttk.Scrollbar(self._list_frame, orient="vertical", command=self._lb.yview)
        self._lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._lb.pack(fill="both", expand=True)
        self._lb.bind("<<ListboxSelect>>", self._on_select)
        self._lb.bind("<ButtonPress-1>",   self._drag_start)
        self._lb.bind("<B1-Motion>",       self._drag_motion)
        self._lb.bind("<ButtonRelease-1>", self._drag_end)
        self._lb.bind("<Delete>",          lambda _: self._remove_sel())
        # エクスプローラーからのファイルドロップ（リストビュー）
        if _HAS_DND:
            self._lb.drop_target_register(DND_FILES)
            self._lb.dnd_bind("<<Drop>>", lambda e: self.accept_drop(
                self.root.tk.splitlist(e.data)))

        # グリッド
        self._grid_frame = ttk.Frame(self._left)
        self._canvas_g = tk.Canvas(self._grid_frame, bd=0, highlightthickness=0,
                                   background=C["list_bg"])
        gsb = ttk.Scrollbar(self._grid_frame, orient="vertical", command=self._canvas_g.yview)
        self._canvas_g.configure(yscrollcommand=gsb.set)
        gsb.pack(side="right", fill="y")
        self._canvas_g.pack(fill="both", expand=True)
        self._grid_inner = ttk.Frame(self._canvas_g)
        self._canvas_g.create_window((0, 0), window=self._grid_inner, anchor="nw")
        self._grid_inner.bind("<Configure>",
            lambda e: self._canvas_g.configure(scrollregion=self._canvas_g.bbox("all")))
        self._canvas_g.bind("<Configure>", lambda _: self._refresh_grid())

        # 右ペイン（プレビュー）
        pf = ttk.LabelFrame(main, text="プレビュー", width=210, padding=6,
                             style="Surface.TLabelframe")
        pf.pack(side="right", fill="y", padx=(6, 0))
        pf.pack_propagate(False)
        self._prev_img_lbl = ttk.Label(pf, anchor="center", background=C["surface"])
        self._prev_img_lbl.pack(pady=4)
        self._prev_name  = ttk.Label(pf, text="", wraplength=190, anchor="center",
                                     style="Surface.TLabel", font=("Yu Gothic UI", 10))
        self._prev_name.pack()
        self._prev_info  = ttk.Label(pf, text="", wraplength=190, anchor="center",
                                     style="Surface.Sub.TLabel", font=("Yu Gothic UI", 9))
        self._prev_info.pack(pady=2)
        self._prev_order = ttk.Label(pf, text="", anchor="center", style="Surface.TLabel")
        self._prev_order.pack()
        ttk.Separator(pf).pack(fill="x", pady=6)
        for hint in ("Ctrl+A  全選択", "Delete  選択削除", "↑↓  移動", "ドラッグ  並び替え"):
            ttk.Label(pf, text=hint, foreground=C["subtext"],
                      background=C["surface"], font=("Yu Gothic UI", 9)).pack(anchor="w")

        # ── 出力先 ─────────────────────────────────────────────
        bot = ttk.Frame(self, style="Surface.TFrame", padding=(8, 4))
        bot.pack(fill="x", side="bottom")
        ttk.Label(bot, text="出力先:", style="Surface.TLabel").pack(side="left")
        ttk.Entry(bot, textvariable=self._out_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(bot, text="参照…", command=self._pick_output).pack(side="left")

        # キーバインド
        self.bind("<Control-a>", lambda _: self._select_all())
        self.bind("<Delete>",    lambda _: self._remove_sel())
        self.bind("<Up>",        lambda _: self._move_up())
        self.bind("<Down>",      lambda _: self._move_down())

        self._switch_view()
        # エクスプローラーからのファイルドロップ（グリッドビュー）
        if _HAS_DND:
            self._canvas_g.drop_target_register(DND_FILES)
            self._canvas_g.dnd_bind("<<Drop>>", lambda e: self.accept_drop(
                self.root.tk.splitlist(e.data)))

    # ── ドロップ受け付け ──────────────────────────────────────────
    def accept_drop(self, paths):
        self._add_paths(paths)

    # ── 表示切替 ─────────────────────────────────────────────────
    def _switch_view(self):
        if self._view_mode.get() == "list":
            self._grid_frame.pack_forget()
            self._list_frame.pack(fill="both", expand=True)
        else:
            self._list_frame.pack_forget()
            self._grid_frame.pack(fill="both", expand=True)
        self._refresh()

    # ── ファイル管理 ─────────────────────────────────────────────
    def _add_paths(self, paths):
        existing = {p for _, p in self._files}
        added = 0
        for p in paths:
            p = p.strip().strip("{}")
            if os.path.isdir(p):
                for f in sorted(os.listdir(p)):
                    fp = os.path.join(p, f)
                    if f.lower().endswith(SUPPORTED_EXTS) and fp not in existing:
                        self._files.append((f, fp))
                        existing.add(fp)
                        added += 1
                if not self._out_var.get():
                    self._out_var.set(os.path.join(p, "output.pdf"))
            elif p.lower().endswith(SUPPORTED_EXTS) and p not in existing:
                self._files.append((os.path.basename(p), p))
                existing.add(p)
                added += 1
        if added:
            self._refresh()
            self._status.set(f"  {added} 枚追加")

    def _add_files(self):
        exts = " ".join(f"*{e}" for e in SUPPORTED_EXTS)
        paths = filedialog.askopenfilenames(
            title="画像ファイルを選択（Ctrl/Shift で複数選択可）",
            filetypes=[
                ("画像ファイル", exts),
                ("JPEG", "*.jpg *.jpeg"),
                ("PNG",  "*.png"),
                ("WebP", "*.webp"),
                ("AVIF", "*.avif"),
                ("すべて", "*.*"),
            ])
        if paths:
            self._add_paths(list(paths))

    def _add_folder(self):
        folder = filedialog.askdirectory(title="フォルダを選択")
        if folder:
            self._add_paths([folder])

    def _remove_sel(self):
        for i in sorted(self._get_sel_indices(), reverse=True):
            fp = self._files[i][1]
            self._thumbs.pop(fp, None)
            del self._files[i]
        self._refresh()

    def _clear(self):
        if self._files and not messagebox.askyesno("確認", "リストを全削除しますか？"):
            return
        self._files.clear()
        self._thumbs.clear()
        self._grid_sel.clear()
        self._grid_last_click = None
        self._clear_preview()
        self._refresh()

    def _clear_preview(self):
        self._prev_img_lbl.config(image="", text="")
        self._prev_img_lbl._img = None
        self._prev_name.config(text="")
        self._prev_info.config(text="")
        self._prev_order.config(text="")

    def _move_up(self):
        sel = sorted(self._get_sel_indices())
        if not sel or sel[0] == 0: return
        for i in sel:
            self._files[i-1], self._files[i] = self._files[i], self._files[i-1]
        self._refresh(); self._set_sel([i-1 for i in sel])

    def _move_down(self):
        sel = sorted(self._get_sel_indices())
        if not sel or sel[-1] >= len(self._files)-1: return
        for i in reversed(sel):
            self._files[i], self._files[i+1] = self._files[i+1], self._files[i]
        self._refresh(); self._set_sel([i+1 for i in sel])

    def _move_top(self):
        sel = sorted(self._get_sel_indices())
        items = [self._files[i] for i in sel]
        rest  = [f for i,f in enumerate(self._files) if i not in set(sel)]
        self._files = items + rest
        self._refresh(); self._set_sel(list(range(len(items))))

    def _move_bottom(self):
        sel = sorted(self._get_sel_indices())
        items = [self._files[i] for i in sel]
        rest  = [f for i,f in enumerate(self._files) if i not in set(sel)]
        self._files = rest + items
        self._refresh()
        n = len(self._files)
        self._set_sel(list(range(n-len(items), n)))

    def _select_all(self):
        if self._view_mode.get() == "list":
            self._lb.selection_set(0, "end")
        else:
            self._grid_sel = {p for _,p in self._files}
            self._refresh_grid()

    def _get_sel_indices(self):
        if self._view_mode.get() == "list":
            return list(self._lb.curselection())
        else:
            # グリッド選択をself._filesのインデックスに変換
            sel_paths = self._grid_sel
            return [i for i,(_, p) in enumerate(self._files) if p in sel_paths]

    def _set_sel(self, indices):
        if self._view_mode.get() == "list":
            self._lb.selection_clear(0, "end")
            for i in indices: self._lb.selection_set(i)
        else:
            self._grid_sel = {self._files[i][1] for i in indices if i < len(self._files)}
            self._refresh_grid()

    # ── 表示更新 ─────────────────────────────────────────────────
    def _refresh(self):
        q = self._search_var.get().lower()
        self._filtered = [(i, self._files[i][0], self._files[i][1])
                          for i in range(len(self._files))
                          if q in self._files[i][0].lower()] if q else \
                         [(i, n, p) for i,(n,p) in enumerate(self._files)]
        if self._view_mode.get() == "list":
            self._refresh_list()
        else:
            self._refresh_grid()
        self._count_lbl.config(text=f"{len(self._files)} 枚")

    def _refresh_list(self):
        self._lb.delete(0, "end")
        for rank, (_, name, _) in enumerate(self._filtered):
            # 番号部分を右詰め3桁固定にしてズレを防ぐ
            self._lb.insert("end", f"  {rank+1:>4}   {name}")

    def _refresh_grid(self):
        for w in self._grid_inner.winfo_children():
            w.destroy()
        self._grid_cells = {}   # path -> cell Frame
        cw = max(self._canvas_g.winfo_width(), 600)
        cols = max(1, cw // (self.THUMB_W + 24))
        for rank, (_, name, path) in enumerate(self._filtered):
            is_sel = path in self._grid_sel
            hl = C["accent"] if is_sel else C["border"]
            cell = tk.Frame(self._grid_inner, bg=C["surface"],
                            relief="flat", bd=2,
                            highlightbackground=hl, highlightthickness=2,
                            cursor="hand2")
            cell.grid(row=rank // cols, column=rank % cols, padx=5, pady=5)
            self._grid_cells[path] = cell
            if path not in self._thumbs:
                if path not in self._thumb_pending:
                    self._thumb_pending.add(path)
                    def _load_thumb(p=path, c=cell):
                        th = make_thumbnail(p, (self.THUMB_W, self.THUMB_H))
                        def _apply():
                            if th:
                                self._thumbs[p] = th
                                self._thumb_pending.discard(p)
                                # セルがまだ生存していれば差し替え
                                try:
                                    for w in c.winfo_children():
                                        if isinstance(w, tk.Label) and getattr(w, "_is_placeholder", False):
                                            w.config(image=th, text="")
                                            w.image = th
                                            w._is_placeholder = False
                                            break
                                except Exception:
                                    pass
                        self.after(0, _apply)
                    self._thumb_executor.submit(_load_thumb)
                th = None
            else:
                th = self._thumbs.get(path)
            if th:
                lbl = tk.Label(cell, image=th, bg=C["surface"], cursor="hand2")
                lbl.image = th
                lbl.pack()
            else:
                ph_lbl = tk.Label(cell, text="⏳", width=18, bg=C["surface"],
                                  fg=C["subtext"], font=("Yu Gothic UI", 18))
                ph_lbl._is_placeholder = True
                ph_lbl.pack()
            # 番号を固定幅でそろえる（最大3桁を想定）
            num_str = f"{rank+1:3}."
            short = name if len(name) <= 20 else name[:17] + "…"
            tk.Label(cell, text=f"{num_str} {short}", width=22, anchor="w",
                     bg=C["surface"], fg=C["subtext"],
                     font=("Yu Gothic UI Mono", 9)).pack(pady=(0,4), padx=4)

            # クリックで選択トグル・プレビュー
            def _click(e, p=path, rank=rank):
                ctrl  = (e.state & 0x4) != 0
                shift = (e.state & 0x1) != 0
                if shift and self._grid_last_click is not None:
                    # Shift選択: アンカーから現在のセルまでの範囲を選択
                    all_paths = [fp for _, fp in self._files]
                    try:
                        anchor_idx = all_paths.index(self._grid_last_click)
                    except ValueError:
                        anchor_idx = rank
                    lo, hi = min(anchor_idx, rank), max(anchor_idx, rank)
                    if ctrl:
                        # Ctrl+Shift: 範囲を追加
                        for fp in all_paths[lo:hi+1]:
                            self._grid_sel.add(fp)
                    else:
                        # Shift: 範囲のみ選択
                        self._grid_sel = set(all_paths[lo:hi+1])
                elif ctrl:
                    if p in self._grid_sel: self._grid_sel.discard(p)
                    else:                   self._grid_sel.add(p)
                    self._grid_last_click = p
                else:
                    self._grid_sel = {p}
                    self._grid_last_click = p
                self._show_preview(p)
                self._refresh_grid()
            cell.bind("<Button-1>", _click)
            for child in cell.winfo_children():
                child.bind("<Button-1>", _click)

    # ── プレビュー ───────────────────────────────────────────────
    def _on_select(self, _):
        sel = self._lb.curselection()
        if sel and sel[-1] < len(self._filtered):
            self._show_preview(self._filtered[sel[-1]][2])

    def _show_preview(self, path):
        try:
            img = Image.open(path)
            w, h = img.size
            img.thumbnail((210, 200), Image.LANCZOS)
            ph = ImageTk.PhotoImage(img)
            self._prev_img_lbl.config(image=ph); self._prev_img_lbl._img = ph
            self._prev_name.config(text=os.path.basename(path))
            self._prev_info.config(text=f"{w}×{h}px  {os.path.getsize(path)//1024}KB")
            for i,(_, p) in enumerate(self._files):
                if p == path:
                    self._prev_order.config(text=f"順番: {i+1} / {len(self._files)}")
                    break
        except Exception:
            self._prev_img_lbl.config(image="", text="読込失敗")
            self._prev_name.config(text=""); self._prev_info.config(text="")

    # ── ドラッグ並び替え ─────────────────────────────────────────
    def _drag_start(self, e): self._drag_from = self._lb.nearest(e.y)
    def _drag_end(self, _):   self._drag_from = None
    def _drag_motion(self, e):
        if self._drag_from is None: return
        target = self._lb.nearest(e.y)
        if target != self._drag_from and 0 <= target < len(self._filtered):
            oi, ot = self._filtered[self._drag_from][0], self._filtered[target][0]
            self._files[oi], self._files[ot] = self._files[ot], self._files[oi]
            self._drag_from = target
            self._refresh(); self._lb.selection_set(target)

    # ── 出力 ─────────────────────────────────────────────────────
    def _pick_output(self):
        p = filedialog.asksaveasfilename(title="PDF の保存先", defaultextension=".pdf",
                                         filetypes=[("PDF", "*.pdf")])
        if p: self._out_var.set(p)

    def get_files_and_output(self):
        paths = [p for _, p in self._files]
        out   = self._out_var.get().strip()
        return paths, out


# ══════════════════════════════════════════════════════════════════
#  フォルダタブ
# ══════════════════════════════════════════════════════════════════
class FolderTab(ttk.Frame):
    def __init__(self, master, status_bar, **kw):
        super().__init__(master, **kw)
        self._status = status_bar
        self._folder = ""
        self._imgs   = []
        self._out_var = tk.StringVar()
        self._sort_var = tk.StringVar(value="name")
        self._build()

    def _build(self):
        # フォルダ選択エリア
        fa = ttk.LabelFrame(self, text="フォルダを選択", padding=12,
                            style="Surface.TLabelframe")
        fa.pack(fill="x", padx=12, pady=10)

        drop_lbl = tk.Label(fa,
            text="📁  フォルダをここにドロップ、またはクリックして選択",
            bg=C["surface"], fg=C["text"],
            font=("Yu Gothic UI", 12), cursor="hand2", anchor="center")
        drop_lbl.pack(fill="x")
        drop_lbl.bind("<Button-1>", lambda _: self._browse_folder())
        # エクスプローラーからのフォルダドロップ
        if _HAS_DND:
            drop_lbl.drop_target_register(DND_FILES)
            drop_lbl.dnd_bind("<<Drop>>", lambda e: (
                self._load_folder(self.root.tk.splitlist(e.data)[0])
                if os.path.isdir(self.root.tk.splitlist(e.data)[0]) else None))

        ttk.Label(fa, text="JPEG · AVIF · WebP · PNG · BMP · GIF · TIFF 対応",
                  style="Surface.Sub.TLabel", font=("Yu Gothic UI", 10)).pack(pady=(2,4))
        ttk.Button(fa, text="フォルダを開く…",
                   command=self._browse_folder).pack()

        # ソート
        sf = ttk.Frame(self, style="Surface.TFrame", padding=(12,4))
        sf.pack(fill="x")
        ttk.Label(sf, text="並び順:", style="Surface.TLabel").pack(side="left")
        for val, lbl in [("name","ファイル名"),("num","数字順"),("date","更新日時")]:
            ttk.Radiobutton(sf, text=lbl, variable=self._sort_var,
                            value=val, style="TRadiobutton").pack(side="left", padx=4)

        # 情報ラベル
        self._info_lbl = ttk.Label(self, text="", anchor="center", style="Sub.TLabel")
        self._info_lbl.pack(pady=4)

        # ファイル一覧
        lf = ttk.Frame(self, style="Surface.TFrame")
        lf.pack(fill="both", expand=True, padx=12)
        self._lb = tk.Listbox(lf, font=("Yu Gothic UI", 9), height=8,
                              bg=C["list_bg"], fg=C["text"],
                              selectbackground=C["sel_bg"], selectforeground=C["text"],
                              relief="flat", bd=0, highlightthickness=0)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self._lb.yview)
        self._lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._lb.pack(fill="both", expand=True)

        # 出力先
        bot = ttk.Frame(self, style="Surface.TFrame", padding=(12,4))
        bot.pack(fill="x")
        ttk.Label(bot, text="出力先:", style="Surface.TLabel").pack(side="left")
        ttk.Entry(bot, textvariable=self._out_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(bot, text="参照…", command=self._pick_output).pack(side="left")

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="画像フォルダを選択")
        if folder: self._load_folder(folder)

    def _load_folder(self, folder):
        self._folder = folder
        self._refresh_list()
        # 出力先が未設定のときだけデフォルトをセット（手動変更済みは保持）
        if not self._out_var.get().strip():
            self._out_var.set(os.path.join(folder, "output.pdf"))

    def _refresh_list(self):
        folder = self._folder
        files = [f for f in os.listdir(folder) if f.lower().endswith(SUPPORTED_EXTS)]
        sort = self._sort_var.get()
        if sort == "name":
            files.sort(key=str.lower)
        elif sort == "num":
            def numkey(s):
                parts = re.split(r'(\d+)', s)
                return [int(p) if p.isdigit() else p.lower() for p in parts]
            files.sort(key=numkey)
        elif sort == "date":
            files.sort(key=lambda f: os.path.getmtime(os.path.join(folder, f)), reverse=True)
        self._imgs = [os.path.join(folder, f) for f in files]
        self._lb.delete(0, "end")
        for i, f in enumerate(files):
            self._lb.insert("end", f"  {i+1:>3}.  {f}")
        n = len(files)
        self._info_lbl.config(
            text=f"✔  {n} 枚の画像を検出  —  {os.path.basename(folder)}/" if n
            else "⚠ 対応画像が見つかりません",
            foreground=C["success"] if n else C["warn"])

    def _pick_output(self):
        p = filedialog.asksaveasfilename(title="PDF の保存先", defaultextension=".pdf",
                                         filetypes=[("PDF", "*.pdf")])
        if p: self._out_var.set(p)

    def get_files_and_output(self):
        if not self._folder:
            return None, ""
        self._refresh_list()
        return self._imgs, self._out_var.get().strip()


# ══════════════════════════════════════════════════════════════════
#  ユーティリティ
# ══════════════════════════════════════════════════════════════════
def _sep(parent):
    ttk.Separator(parent, orient="vertical").pack(side="left", fill="y", padx=5, pady=3)


# ══════════════════════════════════════════════════════════════════
#  メインウィンドウ
# ══════════════════════════════════════════════════════════════════
class App:
    def __init__(self):
        # TkinterDnD が使えるならエクスプローラーからのドロップに対応
        self.root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()

        # ── Tk の DPI スケーリング補正 ──────────────────────────────
        # Per-Monitor V2 対応後、tkinter が実際の DPI に合わせた
        # スケールを使うよう明示的に設定 → 文字・線がくっきり表示
        if sys.platform == "win32":
            try:
                screen_dpi = self.root.winfo_fpixels("1i")
                self.root.tk.call("tk", "scaling", screen_dpi / 72.0)
            except Exception:
                pass

        apply_theme(self.root)
        self.root.title(f"画像→PDF 変換ツール  v{VERSION}")
        self.root.geometry("860x700")
        self.root.minsize(720, 560)
        self._build()
        self._center()
        threading.Thread(target=self._check_update, daemon=True).start()

    def _center(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 860, 700
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _build(self):
        # ── ヘッダー ──────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=C["surface"], pady=0)
        hdr.pack(fill="x")

        inner = tk.Frame(hdr, bg=C["surface"])
        inner.pack(fill="x", padx=14, pady=10)
        tk.Label(inner, text="🖼  画像→PDF 変換",
                 font=("Yu Gothic UI", 14, "bold"),
                 bg=C["surface"], fg=C["text"]).pack(side="left")
        self._upd_btn = ttk.Button(inner, text="", command=self._do_update)
        self._upd_btn.pack(side="right")
        tk.Label(inner, text=f"v{VERSION}", bg=C["surface"],
                 fg=C["subtext"], font=("Yu Gothic UI", 9)).pack(side="right", padx=6)

        ttk.Separator(self.root).pack(fill="x")

        # ── bottom エリア（pack side="bottom" は後に追加したものが上になる逆順）
        # 積む順: ステータス → セパレータ → 変換ボタン → セパレータ → オプション → セパレータ
        # 画面上の表示順（上→下）: オプション / 変換ボタン / ステータス

        # ① 最下段: ステータスバー
        self._status = StatusBar(self.root)
        self._status.pack(fill="x", side="bottom", pady=0)

        # ② 変換ボタン行
        ttk.Separator(self.root).pack(fill="x", side="bottom")
        conv_row = ttk.Frame(self.root, style="TFrame", padding=(12, 6))
        conv_row.pack(fill="x", side="bottom")
        self._conv_btn = ttk.Button(conv_row, text="▶  PDF に変換する",
                                    style="Accent.TButton",
                                    command=self._start_convert)
        self._conv_btn.pack(side="left")
        self._tab_hint = ttk.Label(conv_row, text="", style="Sub.TLabel")
        self._tab_hint.pack(side="left", padx=10)

        # ③ オプションパネル
        ttk.Separator(self.root).pack(fill="x", side="bottom")
        self._opts = OptionsPanel(self.root)
        self._opts.pack(fill="x", side="bottom", padx=0)

        # ── タブ（残りのスペースを fill="both" expand=True で使う） ──
        ttk.Separator(self.root).pack(fill="x")
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True)

        # タブ中身
        self._manual_tab = ManualTab(nb, self._status)
        nb.add(self._manual_tab, text="  ✍ 手動選択（複数ファイル・順番変更）  ")

        self._folder_tab = FolderTab(nb, self._status)
        nb.add(self._folder_tab, text="  📁 フォルダ一括変換  ")

        self._nb = nb

    # ── 変換 ─────────────────────────────────────────────────────
    def _start_convert(self):
        tab_idx = self._nb.index("current")
        if tab_idx == 0:
            paths, output = self._manual_tab.get_files_and_output()
        else:
            paths, output = self._folder_tab.get_files_and_output()
            if paths is None:
                self._status.set("フォルダを選択してください", C["warn"]); return

        if not paths:
            self._status.set("画像を追加してください", C["warn"]); return
        if not output:
            self._status.set("出力先を指定してください", C["warn"]); return

        # 出力ファイルが既に存在する場合は上書き確認
        if os.path.exists(output):
            if not messagebox.askyesno(
                "上書き確認",
                f"以下のファイルが既に存在します。\n\n{os.path.basename(output)}\n\n上書きしますか？",
                icon="warning"
            ):
                return

        opts = self._opts.get_options()
        self._conv_btn.config(state="disabled")
        self._status.reset()
        self._status.set("変換準備中…")

        def cb(v):
            self.root.after(0, lambda: [
                self._status.progress(v),
                self._status.set(f"変換中… {v}%")])

        def run():
            try:
                skipped = convert_to_pdf(
                    paths, output, cb,
                    quality   = opts["quality"],
                    page_size = opts["page_size"],
                    margin_mm = opts["margin_mm"],
                    bg_color  = opts["bg_color"],
                )
                self.root.after(0, self._done, output, skipped, opts["open_after"])
            except Exception as ex:
                self.root.after(0, self._err, str(ex))

        threading.Thread(target=run, daemon=True).start()

    def _done(self, path, skipped, open_after):
        self._conv_btn.config(state="normal")
        msg = f"✔  完成: {os.path.basename(path)}"
        if skipped:
            msg += f"  （スキップ {len(skipped)} 枚）"
        self._status.set(msg, C["success"])
        self._status.progress(100)
        if open_after:
            try:
                os.startfile(path)
            except Exception:
                pass

    def _err(self, msg):
        self._conv_btn.config(state="normal")
        self._status.set(f"エラー: {msg[:80]}", C["error"])
        messagebox.showerror("変換エラー", msg)

    # ── アップデート ──────────────────────────────────────────────
    def _check_update(self):
        if not UPDATE_URL:
            return  # URL未設定時はチェックをスキップ
        try:
            with urllib.request.urlopen(UPDATE_URL, timeout=4) as r:
                data = json.loads(r.read())
            latest = data.get("version", VERSION)
            if latest != VERSION:
                self.root.after(0, self._show_update_badge, latest, data.get("url",""))
        except Exception:
            pass

    def _show_update_badge(self, latest, url):
        self._update_url = url
        self._upd_btn.config(text=f"⬆ v{latest} に更新")

    def _do_update(self):
        url = getattr(self, "_update_url", "")
        if not url: return
        if not messagebox.askyesno("アップデート", "最新版に更新しますか？"): return
        try:
            dest = os.path.abspath(sys.argv[0])
            tmp  = dest + ".new"
            urllib.request.urlretrieve(url, tmp)
            bak  = dest + ".bak"
            if os.path.exists(bak): os.remove(bak)
            shutil.move(dest, bak); shutil.move(tmp, dest)
            messagebox.showinfo("完了", "アップデートしました。\n再起動してください。")
            self.root.destroy()
        except Exception as e:
            messagebox.showerror("失敗", f"アップデート失敗:\n{e}")




    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    try:
        App().run()
    except Exception:
        try:
            messagebox.showerror("起動エラー", traceback.format_exc())
        except Exception:
            pass
        raise
