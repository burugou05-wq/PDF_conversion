"""Tk startup and filtered selection regression checks."""

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"), reason="Tk needs a display"
)


def walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk_widgets(child)


def test_gui_starts_and_builds_widgets(monkeypatch):
    import tkinter as tk

    import img2pdf_app

    built = []
    monkeypatch.setattr(img2pdf_app, "configure_logging", lambda: None)

    def smoke(root):
        root.update_idletasks()
        built.extend(root.winfo_children())
        root.destroy()

    monkeypatch.setattr(tk.Tk, "mainloop", smoke)
    assert img2pdf_app.main() == 0
    assert built


def test_gui_filtered_delete_targets_the_visible_file(monkeypatch, tmp_path):
    import tkinter as tk
    from tkinter import filedialog, ttk

    from PIL import Image

    import img2pdf_app

    paths = [tmp_path / name for name in ["A.png", "B.png", "C.png"]]
    for path in paths:
        with Image.new("RGB", (20, 20)) as image:
            image.save(path)
    monkeypatch.setattr(img2pdf_app, "configure_logging", lambda: None)
    monkeypatch.setattr(filedialog, "askopenfilenames", lambda **kwargs: tuple(map(str, paths)))

    def smoke(root):
        widgets = list(walk_widgets(root))
        buttons = {
            str(widget.cget("text")): widget for widget in widgets if isinstance(widget, ttk.Button)
        }
        tree = next(widget for widget in widgets if isinstance(widget, ttk.Treeview))
        search = next(widget for widget in widgets if widget.winfo_class() == "TEntry")
        buttons["ファイル追加"].invoke()
        assert len(tree.get_children()) == 3
        search.insert(0, "C")
        assert tree.get_children() == (str(paths[2].resolve()),)
        tree.selection_set(tree.get_children())
        buttons["選択削除"].invoke()
        search.delete(0, "end")
        assert tree.get_children() == (str(paths[0].resolve()), str(paths[1].resolve()))
        root.destroy()

    monkeypatch.setattr(tk.Tk, "mainloop", smoke)
    assert img2pdf_app.main() == 0


def test_gui_falls_back_when_tkdnd_library_fails(monkeypatch):
    import tkinter as tk

    from tkinterdnd2 import TkinterDnD

    import img2pdf_app

    # Some Windows runner images ship a Python whose Tcl library is incomplete.
    # Then no plain Tk window can start, so this test cannot reach the fallback.
    try:
        tk.Tk().destroy()
    except tk.TclError as error:
        pytest.skip(f"Tk cannot start on this runner: {error}")

    class BrokenDnDTk(tk.Tk):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            raise RuntimeError("tkdnd unavailable")

    built = []
    monkeypatch.setattr(img2pdf_app, "configure_logging", lambda: None)
    monkeypatch.setattr(TkinterDnD, "Tk", BrokenDnDTk)

    def smoke(root):
        built.append(root)
        root.destroy()

    monkeypatch.setattr(tk.Tk, "mainloop", smoke)
    assert img2pdf_app.main() == 0
    assert built and type(built[0]) is tk.Tk
