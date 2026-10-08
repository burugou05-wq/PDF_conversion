"""Shared ttk palette and styles."""

from tkinter import ttk

COLORS = {
    "bg": "#F5F7FA",
    "surface": "#FFFFFF",
    "border": "#DADFE7",
    "accent": "#1A73E8",
    "text": "#202124",
    "subtext": "#5F6368",
    "list_bg": "#FAFBFD",
}


def apply_theme(root):
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    root.configure(bg=COLORS["bg"])
    style.configure(
        ".", font=("Yu Gothic UI", 10), background=COLORS["bg"], foreground=COLORS["text"]
    )
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("TLabel", background=COLORS["bg"])
    style.configure("Sub.TLabel", foreground=COLORS["subtext"])
    style.configure("TButton", padding=(8, 5))
    style.configure(
        "Accent.TButton", background=COLORS["accent"], foreground="white", padding=(14, 7)
    )
    style.map("Accent.TButton", background=[("disabled", "#CCD1D9"), ("active", "#1557B0")])
    style.configure(
        "Treeview", background=COLORS["surface"], rowheight=28, fieldbackground=COLORS["surface"]
    )
    style.map(
        "Treeview", background=[("selected", "#D2E3FC")], foreground=[("selected", COLORS["text"])]
    )
    style.configure("TProgressbar", background=COLORS["accent"])
