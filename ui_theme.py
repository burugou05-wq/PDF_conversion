"""
ui_theme.py - UI テーマと スタイル定義

Google Material Design に基づくカラーパレットと ttk スタイル設定。
"""

import tkinter as tk
from tkinter import ttk

# Google Material Design カラーパレット
COLORS = {
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
    """ttk スタイルをアプリ全体に適用"""
    style = ttk.Style(root)
    
    # clam テーマを使用（ネイティブ描画より純粋 Tk で色が確実に反映）
    for t in ("clam", "alt", "default"):
        if t in style.theme_names():
            style.theme_use(t)
            break
    
    root.configure(bg=COLORS["bg"])

    # グローバルスタイル
    style.configure(".",
        background=COLORS["bg"],
        foreground=COLORS["text"],
        troughcolor=COLORS["border"],
        selectbackground=COLORS["sel_bg"],
        selectforeground=COLORS["text"],
        fieldbackground=COLORS["surface"],
        font=("Yu Gothic UI", 11))

    # Frame
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("Surface.TFrame", background=COLORS["surface"], relief="flat")

    # Label
    style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
    style.configure("Surface.TLabel", background=COLORS["surface"], foreground=COLORS["text"])
    style.configure("Sub.TLabel", background=COLORS["bg"], foreground=COLORS["subtext"])
    style.configure("Surface.Sub.TLabel", background=COLORS["surface"], foreground=COLORS["subtext"])

    # LabelFrame
    style.configure("TLabelframe",
        background=COLORS["bg"], bordercolor=COLORS["border"], relief="groove")
    style.configure("TLabelframe.Label",
        background=COLORS["bg"], foreground=COLORS["subtext"])
    style.configure("Surface.TLabelframe",
        background=COLORS["surface"], bordercolor=COLORS["border"], relief="groove")
    style.configure("Surface.TLabelframe.Label",
        background=COLORS["surface"], foreground=COLORS["subtext"])

    # Separator
    style.configure("TSeparator", background=COLORS["border"])

    # ボタンスタイルヘルパー
    def _configure_button(name, bg, fg, pad, font=None, active_bg=None, disabled_bg=None, disabled_fg=None):
        kw = dict(
            background=bg, foreground=fg, padding=pad,
            relief="flat", borderwidth=1, bordercolor=COLORS["border"],
            focusthickness=0, focuscolor=bg)
        if font:
            kw["font"] = font
        style.configure(name, **kw)
        style.map(name,
            background=[
                ("active", active_bg or COLORS["hover"]),
                ("pressed", active_bg or COLORS["hover"]),
                ("disabled", disabled_bg or COLORS["border"])
            ],
            foreground=[
                ("disabled", disabled_fg or COLORS["subtext"]),
                ("active", fg),
                ("pressed", fg),
                ("!disabled", fg)
            ])

    # Button
    _configure_button("TButton",
        bg=COLORS["surface"], fg=COLORS["text"], pad=(10, 5))
    _configure_button("Toolbar.TButton",
        bg=COLORS["surface"], fg=COLORS["text"], pad=(8, 4))
    _configure_button("Accent.TButton",
        bg=COLORS["accent"], fg="#FFFFFF", pad=(16, 8),
        font=("Yu Gothic UI", 10, "bold"),
        active_bg=COLORS["accent_h"],
        disabled_bg="#BDBDBD", disabled_fg="#FFFFFF")

    # Notebook
    style.configure("TNotebook", background=COLORS["bg"], tabmargins=[0, 0, 0, 0])
    style.configure("TNotebook.Tab", background=COLORS["border"], foreground=COLORS["subtext"],
                    padding=[16, 7])
    style.map("TNotebook.Tab",
        background=[("selected", COLORS["surface"]), ("active", COLORS["hover"])],
        foreground=[("selected", COLORS["accent"]), ("active", COLORS["text"])])

    # Progressbar
    style.configure("TProgressbar",
        troughcolor=COLORS["border"], background=COLORS["accent"],
        thickness=4, borderwidth=0)

    # Radiobutton
    style.configure("TRadiobutton",
        background=COLORS["surface"], foreground=COLORS["text"], focusthickness=0)
    style.map("TRadiobutton",
        background=[("active", COLORS["surface"])],
        foreground=[("active", COLORS["text"])])

    # Checkbutton
    style.configure("TCheckbutton",
        background=COLORS["surface"], foreground=COLORS["text"], focusthickness=0)
    style.map("TCheckbutton",
        background=[("active", COLORS["surface"])],
        foreground=[("active", COLORS["text"])])

    # Entry
    style.configure("TEntry",
        fieldbackground=COLORS["surface"], foreground=COLORS["text"],
        bordercolor=COLORS["border"], lightcolor=COLORS["border"],
        insertcolor=COLORS["text"], relief="flat")
    style.map("TEntry",
        bordercolor=[("focus", COLORS["accent"])])

    # Scrollbar
    style.configure("TScrollbar",
        background=COLORS["border"], troughcolor=COLORS["bg"],
        arrowcolor=COLORS["subtext"], borderwidth=0, relief="flat")
    style.map("TScrollbar",
        background=[("active", COLORS["subtext"])])
