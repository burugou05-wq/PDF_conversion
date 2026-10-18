"""Tk startup and filtered selection regression checks."""

import os
import sys

import pytest


def _tk_startup_error():
    """Return why the Tk UI cannot be exercised here, or None when it can.

    The probe mirrors what the UI does at startup: build one window, take it
    down, then build the drag-and-drop window. Two defects of the hosted
    Windows runners show up here and would otherwise turn into red builds:

    * tkinterdnd2's tkdnd package sometimes cannot be loaded, so every test
      would take the plain-Tk fallback path, and
    * after a Tcl interpreter went away, creating the next one in the same
      process can fail with "Can't find a usable init.tcl".

    Both are runner problems rather than UI regressions, so they skip the
    module instead of failing it.
    """
    import tkinter as tk

    try:
        tk.Tk().destroy()

        from tkinterdnd2 import TkinterDnD

        TkinterDnD.Tk().destroy()
    except tk.TclError as error:
        return str(error)
    except (ImportError, RuntimeError):
        # tkinterdnd2 is optional and rejects unknown platforms; the UI then
        # starts without drag-and-drop, which the tests below still cover.
        return None
    return None


# Some Windows runner images ship a Python whose Tcl library is incomplete.
_TK_STARTUP_ERROR = (
    _tk_startup_error() if sys.platform == "win32" or os.environ.get("DISPLAY") else None
)

pytestmark = [
    pytest.mark.skipif(
        sys.platform != "win32" and not os.environ.get("DISPLAY"), reason="Tk needs a display"
    ),
    pytest.mark.skipif(
        _TK_STARTUP_ERROR is not None,
        reason=f"Tk cannot start on this runner: {_TK_STARTUP_ERROR}",
    ),
]


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


def test_folder_search_filters_cached_listing_without_rescan(monkeypatch, tmp_path):
    import tkinter as tk

    from PIL import Image

    import img2pdf_app

    for name in ("alpha.png", "beta.png", "gamma.jpg"):
        with Image.new("RGB", (20, 20)) as image:
            image.save(tmp_path / name)
    monkeypatch.setattr(img2pdf_app, "configure_logging", lambda: None)

    scans = []
    real_list_images = img2pdf_app.list_images

    def counted_list_images(folder, order="name"):
        scans.append(order)
        return real_list_images(folder, order)

    monkeypatch.setattr(img2pdf_app, "list_images", counted_list_images)

    def smoke(root):
        app = img2pdf_app.LAST_APPLICATION
        assert app is not None
        app.tabs.select(1)  # folder mode
        app.folder = tmp_path
        app.reload_folder()
        assert len(scans) == 1
        assert app.tree.get_children() == tuple(
            str(path.resolve())
            for path in sorted(tmp_path.glob("*"), key=lambda p: p.name.casefold())
        )
        # Typing in the search box must filter the cached listing only.
        app.query.set("beta")
        assert len(scans) == 1
        assert app.tree.get_children() == (str((tmp_path / "beta.png").resolve()),)
        app.query.set("zzz")
        assert app.tree.get_children() == ()
        assert len(scans) == 1
        # Reload is the only path that rescans.
        app.query.set("")
        app.reload_folder()
        assert len(scans) == 2
        root.destroy()

    monkeypatch.setattr(tk.Tk, "mainloop", smoke)
    assert img2pdf_app.main() == 0


def test_multi_selection_drag_moves_all_selected_rows(monkeypatch, tmp_path):
    import tkinter as tk
    from pathlib import Path

    from PIL import Image

    import img2pdf_app

    paths = [tmp_path / name for name in ["A.png", "B.png", "C.png", "D.png"]]
    for path in paths:
        with Image.new("RGB", (20, 20)) as image:
            image.save(path)
    monkeypatch.setattr(img2pdf_app, "configure_logging", lambda: None)

    def smoke(root):
        app = img2pdf_app.LAST_APPLICATION
        assert app is not None
        app.model.add(paths)
        app.refresh()
        resolved = [str(path.resolve()) for path in paths]
        tree = app.tree
        tree.selection_set([resolved[0], resolved[3]])  # A and D

        # The drag handlers must be attached so real clicks reach them.
        assert tree.bind("<ButtonPress-1>")
        assert tree.bind("<ButtonRelease-1>")

        # Drive the handlers directly with synthetic coordinates mapped
        # through identify_row, so the test needs no on-screen geometry and
        # no synthetic event dispatch (unreliable on headless CI sessions).
        rows = {11: resolved[0], 33: resolved[2]}
        monkeypatch.setattr(tree, "identify_row", lambda y: rows.get(y, ""))

        class FakeEvent:
            def __init__(self, y):
                self.y = y

        app.drag_start(FakeEvent(11))
        # The Treeview class binding replaces a multi-selection with the
        # pressed row right after the press; drag_start saved it beforehand.
        tree.selection_set([resolved[0]])
        assert app.drag_saved_selection == {Path(resolved[0]), Path(resolved[3])}
        app.drag_end(FakeEvent(33))

        # A and D moved before C, keeping their relative order.
        assert [str(path) for path in app.model.paths] == [
            resolved[1],
            resolved[0],
            resolved[3],
            resolved[2],
        ]
        assert set(tree.selection()) == {resolved[0], resolved[3]}
        root.destroy()

    monkeypatch.setattr(tk.Tk, "mainloop", smoke)
    assert img2pdf_app.main() == 0


def test_gui_falls_back_when_tkdnd_library_fails(monkeypatch):
    import tkinter as tk

    from tkinterdnd2 import TkinterDnD

    import img2pdf_app

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
    try:
        assert img2pdf_app.main() == 0
    except tk.TclError as error:
        # Some Windows runner images serve only the first Tcl interpreter of a
        # session and then fail to load init.tcl again. The BrokenDnDTk above
        # leaks one interpreter by design, so the fallback window is the second
        # or third one; that is a runner problem, not a fallback problem.
        pytest.skip(f"Tk cannot start again on this runner: {error}")
    assert built and type(built[0]) is tk.Tk
