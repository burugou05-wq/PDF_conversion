"""Desktop UI. Workers communicate through queues and never touch Tk objects."""

import logging
import os
import queue
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app_config import APP_NAME, VERSION
from file_model import FileModel, list_images
from ui_theme import COLORS, apply_theme


def set_dpi_aware():
    if sys.platform != "win32":
        return
    import ctypes

    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()


def configure_logging():
    directory = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ImageToPDF"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        logging.basicConfig(
            level=logging.INFO,
            handlers=[
                RotatingFileHandler(
                    directory / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
                )
            ],
        )
    except OSError:
        logging.basicConfig(level=logging.INFO)


def main():
    set_dpi_aware()
    configure_logging()
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    try:
        from PIL import ImageTk

        from image_processor import (
            ConversionCancelled,
            ConversionOptions,
            convert_to_pdf,
            make_thumbnail,
        )
    except ImportError as error:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "起動エラー",
            f"依存ライブラリが不足しています。\n"
            f"python -m pip install -r requirements.txt\n\n{error}",
        )
        root.destroy()
        return 1

    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD

        root = TkinterDnD.Tk()
        has_dnd = True
    except (ImportError, tk.TclError):
        root = tk.Tk()
        has_dnd = False

    class Application:
        PAGE_LENGTH = 48

        def __init__(self):
            self.root = root
            self.model = FileModel()
            self.folder = None
            self.events = queue.Queue()
            self.cancel_event = threading.Event()
            self.worker = None
            self.closing = False
            self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="preview")
            self.preview_generation = 0
            self.pending_thumbnails = set()
            self.thumbnail_cache = {}
            self.grid_page = 0
            self.grid_selection = set()
            self.grid_anchor = None
            self.grid_cells = {}
            self.visible = []
            self.busy = False
            self.query = tk.StringVar()
            self.output = tk.StringVar()
            self.view = tk.StringVar(value="list")
            self.sort = tk.StringVar(value="name")
            self.quality = tk.StringVar(value="original")
            self.paper = tk.StringVar(value="元のサイズ")
            self.margin = tk.StringVar(value="0")
            self.background = tk.StringVar(value="白")
            self.rotate = tk.BooleanVar(value=True)
            self.open_after = tk.BooleanVar(value=False)
            apply_theme(root)
            root.title(f"{APP_NAME} v{VERSION}")
            root.geometry("1000x760")
            root.minsize(800, 640)
            self.build()
            self.query.trace_add("write", lambda *_: self.refresh())
            root.protocol("WM_DELETE_WINDOW", self.close)
            root.after(80, self.poll)

        def build(self):
            header = ttk.Frame(root, padding=12)
            header.pack(fill="x")
            ttk.Label(header, text="画像 → PDF", font=("Yu Gothic UI", 18, "bold")).pack(
                side="left"
            )
            ttk.Label(header, text=f"v{VERSION}", style="Sub.TLabel").pack(side="right")
            self.tabs = ttk.Notebook(root)
            self.tabs.pack(fill="x", padx=12)
            manual = ttk.Frame(self.tabs, padding=8)
            folder = ttk.Frame(self.tabs, padding=8)
            self.tabs.add(manual, text="手動選択")
            self.tabs.add(folder, text="フォルダ一括")
            self.tabs.bind("<<NotebookTabChanged>>", self.change_tab)
            self.edit_buttons = []
            actions = [
                ("ファイル追加", self.add_files),
                ("フォルダ追加", self.add_folder),
                ("上へ", lambda: self.move("up")),
                ("下へ", lambda: self.move("down")),
                ("先頭へ", lambda: self.move("top")),
                ("末尾へ", lambda: self.move("bottom")),
                ("選択削除", self.remove),
                ("全削除", self.clear),
            ]
            for text, command in actions:
                button = ttk.Button(manual, text=text, command=command)
                button.pack(side="left", padx=2)
                self.edit_buttons.append(button)
            ttk.Button(folder, text="フォルダを選択", command=self.choose_folder).pack(side="left")
            self.folder_label = ttk.Label(folder, text="未選択", width=38)
            self.folder_label.pack(side="left", padx=8)
            order = ttk.Combobox(
                folder,
                textvariable=self.sort,
                state="readonly",
                width=10,
                values=("name", "number", "date"),
            )
            order.pack(side="left")
            order.bind("<<ComboboxSelected>>", lambda _: self.reload_folder())
            ttk.Button(folder, text="再読込", command=self.reload_folder).pack(side="left", padx=4)
            search = ttk.Frame(root, padding=(12, 6))
            search.pack(fill="x")
            ttk.Label(search, text="検索:").pack(side="left")
            ttk.Entry(search, textvariable=self.query).pack(
                side="left", fill="x", expand=True, padx=6
            )
            for value, label in [("list", "リスト"), ("grid", "グリッド")]:
                ttk.Radiobutton(
                    search, text=label, variable=self.view, value=value, command=self.refresh
                ).pack(side="left")
            self.count = ttk.Label(search)
            self.count.pack(side="right", padx=6)
            middle = ttk.Frame(root, padding=(12, 0))
            middle.pack(fill="both", expand=True)
            self.left = ttk.Frame(middle)
            self.left.pack(side="left", fill="both", expand=True)
            self.tree_frame = ttk.Frame(self.left)
            self.tree = ttk.Treeview(
                self.tree_frame, columns=("order", "name"), show="headings", selectmode="extended"
            )
            self.tree.heading("order", text="順番")
            self.tree.heading("name", text="ファイル名")
            self.tree.column("order", width=55, stretch=False)
            self.tree.column("name", width=430)
            scrollbar = ttk.Scrollbar(self.tree_frame, command=self.tree.yview)
            self.tree.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
            self.tree.pack(fill="both", expand=True)
            self.tree.bind("<<TreeviewSelect>>", self.tree_selected)
            self.tree.bind("<Delete>", lambda _: self.remove())
            self.tree.bind("<Control-a>", self.select_all)
            self.tree.bind("<Alt-Up>", lambda _: self.move("up"))
            self.tree.bind("<Alt-Down>", lambda _: self.move("down"))
            self.tree.bind("<ButtonPress-1>", self.drag_start, add=True)
            self.tree.bind("<ButtonRelease-1>", self.drag_end, add=True)
            self.drag_origin = None
            self.grid_frame = ttk.Frame(self.left)
            navigation = ttk.Frame(self.grid_frame)
            navigation.pack(fill="x")
            ttk.Button(navigation, text="前へ", command=lambda: self.change_page(-1)).pack(
                side="left"
            )
            ttk.Button(navigation, text="次へ", command=lambda: self.change_page(1)).pack(
                side="left"
            )
            self.page_label = ttk.Label(navigation)
            self.page_label.pack(side="left", padx=10)
            self.canvas = tk.Canvas(self.grid_frame, highlightthickness=0, bg=COLORS["list_bg"])
            grid_scroll = ttk.Scrollbar(self.grid_frame, command=self.canvas.yview)
            self.canvas.configure(yscrollcommand=grid_scroll.set)
            grid_scroll.pack(side="right", fill="y")
            self.canvas.pack(fill="both", expand=True)
            self.grid_inner = ttk.Frame(self.canvas)
            self.canvas.create_window((0, 0), window=self.grid_inner, anchor="nw")
            self.grid_inner.bind(
                "<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            )
            preview = ttk.LabelFrame(middle, text="プレビュー", padding=8, width=240)
            preview.pack(side="right", fill="y", padx=(8, 0))
            preview.pack_propagate(False)
            self.preview = ttk.Label(preview)
            self.preview.pack(pady=8)
            self.preview_text = ttk.Label(preview, wraplength=215)
            self.preview_text.pack()
            ttk.Label(
                preview,
                text="Ctrl+A: 全選択\nDelete: 削除\nAlt+↑↓: 順番変更\n"
                "ドラッグ: 選択画像を移動\n検索は表示のみ。変換は全件対象。",
                wraplength=215,
                style="Sub.TLabel",
            ).pack(side="bottom", pady=8)
            if has_dnd:
                for widget in (self.tree, self.canvas):
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self.drop)
            options = ttk.LabelFrame(root, text="変換設定", padding=8)
            options.pack(fill="x", padx=12, pady=6)
            for value, label in [
                ("original", "元画質優先（再圧縮なし）"),
                ("compact", "軽量化（150dpi / JPEG品質85）"),
            ]:
                ttk.Radiobutton(options, text=label, variable=self.quality, value=value).pack(
                    side="left"
                )
            settings = ttk.Frame(root, padding=(12, 0))
            settings.pack(fill="x")
            ttk.Label(settings, text="用紙:").pack(side="left")
            ttk.Combobox(
                settings,
                textvariable=self.paper,
                state="readonly",
                width=12,
                values=("元のサイズ", "A4", "A3", "Letter"),
            ).pack(side="left", padx=4)
            ttk.Label(settings, text="余白(mm):").pack(side="left")
            ttk.Entry(settings, textvariable=self.margin, width=6).pack(side="left", padx=4)
            ttk.Combobox(
                settings,
                textvariable=self.background,
                state="readonly",
                width=6,
                values=("白", "黒", "グレー"),
            ).pack(side="left", padx=4)
            ttk.Checkbutton(settings, text="横長用紙へ自動回転", variable=self.rotate).pack(
                side="left"
            )
            ttk.Checkbutton(settings, text="完了後に開く", variable=self.open_after).pack(
                side="left"
            )
            destination = ttk.Frame(root, padding=12)
            destination.pack(fill="x")
            ttk.Label(destination, text="出力先:").pack(side="left")
            ttk.Entry(destination, textvariable=self.output).pack(
                side="left", fill="x", expand=True, padx=6
            )
            ttk.Button(destination, text="参照", command=self.pick_output).pack(side="left")
            bottom = ttk.Frame(root, padding=(12, 0, 12, 12))
            bottom.pack(fill="x")
            self.convert_button = ttk.Button(
                bottom, text="PDFに変換", style="Accent.TButton", command=self.start
            )
            self.convert_button.pack(side="left")
            self.cancel_button = ttk.Button(
                bottom, text="キャンセル", command=self.cancel_event.set, state="disabled"
            )
            self.cancel_button.pack(side="left", padx=6)
            self.status = ttk.Label(bottom, text="画像を追加してください")
            self.status.pack(side="left", padx=8)
            self.progress = ttk.Progressbar(bottom, length=160)
            self.progress.pack(side="right")
            self.refresh()

        def is_folder_mode(self):
            return self.tabs.index("current") == 1

        def current_paths(self):
            if self.is_folder_mode():
                return list_images(self.folder, self.sort.get()) if self.folder else []
            return self.model.paths

        def change_tab(self, _=None):
            self.query.set("")
            self.grid_selection.clear()
            self.grid_page = 0
            self.refresh()

        def refresh(self, selected=()):
            try:
                paths = self.current_paths()
            except OSError as error:
                messagebox.showerror("フォルダ読込エラー", str(error))
                paths = []
            self.visible = [
                path for path in paths if self.query.get().casefold() in path.name.casefold()
            ]
            self.count.config(text=f"{len(self.visible)} / {len(paths)} 枚")
            self.tree.delete(*self.tree.get_children())
            positions = {path: index + 1 for index, path in enumerate(paths)}
            for path in self.visible:
                self.tree.insert("", "end", iid=str(path), values=(positions[path], path.name))
            selected = [str(path) for path in selected if path in self.visible]
            if selected:
                self.tree.selection_set(selected)
            for button in self.edit_buttons:
                button.config(state="disabled" if self.is_folder_mode() else "normal")
            if self.view.get() == "list":
                self.grid_frame.pack_forget()
                self.tree_frame.pack(fill="both", expand=True)
            else:
                self.tree_frame.pack_forget()
                self.grid_frame.pack(fill="both", expand=True)
                self.render_grid()

        def selected(self):
            if self.view.get() == "grid":
                return self.grid_selection.intersection(self.visible)
            return {Path(value) for value in self.tree.selection()}

        def add_paths(self, paths):
            try:
                added = self.model.add(paths)
                if not self.output.get() and self.model.paths:
                    self.output.set(str(self.model.paths[0].parent / "output.pdf"))
                self.status.config(text=f"{added} 枚追加")
                self.refresh()
            except OSError as error:
                messagebox.showerror("追加エラー", str(error))

        def add_files(self):
            self.add_paths(
                filedialog.askopenfilenames(
                    filetypes=[
                        (
                            "画像",
                            "*.jpg *.jpeg *.png *.webp *.avif *.heic *.heif *.bmp *.gif *.tif *.tiff",
                        ),
                        ("すべて", "*.*"),
                    ]
                )
            )

        def add_folder(self):
            folder = filedialog.askdirectory()
            if folder:
                self.add_paths([folder])

        def choose_folder(self):
            folder = filedialog.askdirectory()
            if folder:
                self.folder = Path(folder)
                self.folder_label.config(text=str(self.folder))
                if not self.output.get():
                    self.output.set(str(self.folder / "output.pdf"))
                self.reload_folder()

        def reload_folder(self):
            self.grid_page = 0
            self.grid_selection.clear()
            self.refresh()

        def drop(self, event):
            paths = self.root.tk.splitlist(event.data)
            if self.is_folder_mode():
                directories = [Path(path) for path in paths if Path(path).is_dir()]
                if directories:
                    self.folder = directories[0]
                    self.folder_label.config(text=str(self.folder))
                    if not self.output.get():
                        self.output.set(str(self.folder / "output.pdf"))
                    self.reload_folder()
            else:
                self.add_paths(paths)

        def remove(self):
            if not self.is_folder_mode():
                self.model.remove(self.selected())
                self.grid_selection.intersection_update(self.model.paths)
                self.refresh()

        def clear(self):
            if messagebox.askyesno("確認", "画像一覧を全削除しますか？"):
                self.model.paths.clear()
                self.grid_selection.clear()
                self.refresh()

        def move(self, direction):
            if self.is_folder_mode():
                return
            selected = self.selected()
            self.model.move(selected, direction)
            self.refresh(selected)

        def select_all(self, _=None):
            self.tree.selection_set(self.tree.get_children())
            return "break"

        def drag_start(self, event):
            self.drag_origin = self.tree.identify_row(event.y)

        def drag_end(self, event):
            target = self.tree.identify_row(event.y)
            if (
                not self.is_folder_mode()
                and self.drag_origin
                and target
                and target != self.drag_origin
            ):
                selected = self.selected() or {Path(self.drag_origin)}
                self.model.move_before(selected, Path(target))
                self.refresh(selected)
            self.drag_origin = None

        def tree_selected(self, _):
            selection = self.tree.selection()
            if selection:
                self.show_preview(Path(selection[-1]))

        def show_preview(self, path):
            self.preview_generation += 1
            generation = self.preview_generation

            def load():
                try:
                    image = make_thumbnail(path, (215, 230))
                    self.events.put(("preview", (generation, path, image, None)))
                except Exception as error:
                    self.events.put(("preview", (generation, path, None, str(error))))

            self.executor.submit(load)

        def change_page(self, delta):
            self.grid_page = max(
                0, min(self.grid_page + delta, max(0, (len(self.visible) - 1) // self.PAGE_LENGTH))
            )
            self.render_grid()

        def render_grid(self):
            for child in self.grid_inner.winfo_children():
                child.destroy()
            self.grid_cells.clear()
            pages = max(1, (len(self.visible) + self.PAGE_LENGTH - 1) // self.PAGE_LENGTH)
            self.grid_page = min(self.grid_page, pages - 1)
            self.page_label.config(text=f"{self.grid_page + 1} / {pages}")
            start = self.grid_page * self.PAGE_LENGTH
            for index, path in enumerate(self.visible[start : start + self.PAGE_LENGTH]):
                cell = tk.Frame(
                    self.grid_inner,
                    bd=2,
                    highlightthickness=2,
                    highlightbackground=COLORS["accent"]
                    if path in self.grid_selection
                    else COLORS["border"],
                )
                cell.grid(row=index // 3, column=index % 3, padx=3, pady=3)
                label = tk.Label(cell, text="読込中", width=18, height=7)
                label.pack()
                caption = tk.Label(cell, text=path.name[:22], width=22)
                caption.pack()
                self.grid_cells[path] = label
                for widget in (cell, label, caption):
                    widget.bind("<Button-1>", lambda event, item=path: self.grid_click(event, item))
                if path in self.thumbnail_cache:
                    self.apply_thumbnail(path, self.thumbnail_cache[path])
                elif path not in self.pending_thumbnails:
                    self.pending_thumbnails.add(path)

                    def load(item=path):
                        try:
                            image = make_thumbnail(item, (150, 105))
                        except Exception:
                            image = None
                        self.events.put(("thumbnail", (item, image)))

                    self.executor.submit(load)
            self.canvas.yview_moveto(0)

        def grid_click(self, event, path):
            if event.state & 1 and self.grid_anchor in self.visible:
                start = self.visible.index(self.grid_anchor)
                end = self.visible.index(path)
                chosen = set(self.visible[min(start, end) : max(start, end) + 1])
                self.grid_selection = self.grid_selection | chosen if event.state & 4 else chosen
            elif event.state & 4:
                self.grid_selection.symmetric_difference_update({path})
                self.grid_anchor = path
            else:
                self.grid_selection = {path}
                self.grid_anchor = path
            for item, label in self.grid_cells.items():
                label.master.config(
                    highlightbackground=COLORS["accent"]
                    if item in self.grid_selection
                    else COLORS["border"]
                )
            self.show_preview(path)

        def apply_thumbnail(self, path, photo):
            label = self.grid_cells.get(path)
            if label:
                if photo is None:
                    label.config(text="読込失敗", image="")
                else:
                    label.config(image=photo, text="", width=150, height=105)
                    label.image = photo

        def pick_output(self):
            path = filedialog.asksaveasfilename(
                defaultextension=".pdf", filetypes=[("PDF", "*.pdf")]
            )
            if path:
                self.output.set(path)

        def start(self):
            if self.busy:
                return
            try:
                paths = list(self.current_paths())
                if not self.output.get().strip():
                    raise ValueError("出力先を指定してください")
                output = Path(self.output.get().strip()).expanduser().resolve()
                colors = {"白": (255, 255, 255), "黒": (0, 0, 0), "グレー": (180, 180, 180)}
                options = ConversionOptions(
                    quality=self.quality.get(),
                    page_size=None if self.paper.get() == "元のサイズ" else self.paper.get(),
                    margin_mm=float(self.margin.get()),
                    bg_color=colors[self.background.get()],
                    auto_rotate=self.rotate.get(),
                )
                options.validate()
                if not paths:
                    raise ValueError("画像を追加してください")
                overwrite = output.exists()
                if overwrite and not messagebox.askyesno(
                    "上書き確認", f"{output}\nを上書きしますか？"
                ):
                    return
            except (ValueError, OSError) as error:
                messagebox.showerror("入力エラー", str(error))
                return
            self.cancel_event.clear()
            self.busy = True
            open_after = self.open_after.get()
            self.convert_button.config(state="disabled")
            self.cancel_button.config(state="normal")
            self.progress["value"] = 0
            self.status.config(text="変換中…")

            def run():
                try:
                    result = convert_to_pdf(
                        paths,
                        output,
                        lambda value: self.events.put(("progress", value)),
                        options=options,
                        cancel_event=self.cancel_event,
                        overwrite=overwrite,
                    )
                    self.events.put(("done", (result, open_after)))
                except ConversionCancelled:
                    self.events.put(("cancelled", None))
                except Exception as error:
                    logging.exception("Conversion failed")
                    self.events.put(("error", str(error)))

            self.worker = threading.Thread(target=run, name="conversion", daemon=False)
            self.worker.start()

        def poll(self):
            try:
                while True:
                    kind, payload = self.events.get_nowait()
                    if kind == "progress":
                        self.progress["value"] = payload
                        self.status.config(text=f"変換中… {payload}%")
                    elif kind == "preview":
                        generation, path, image, error = payload
                        if generation == self.preview_generation and not self.closing:
                            photo = ImageTk.PhotoImage(image, master=root) if image else None
                            self.preview.config(image=photo or "")
                            self.preview.image = photo
                            self.preview_text.config(text=f"{path.name}\n{error or ''}")
                        if image:
                            image.close()
                    elif kind == "thumbnail":
                        path, image = payload
                        self.pending_thumbnails.discard(path)
                        if not self.closing:
                            photo = ImageTk.PhotoImage(image, master=root) if image else None
                            self.thumbnail_cache[path] = photo
                            while len(self.thumbnail_cache) > 100:
                                self.thumbnail_cache.pop(next(iter(self.thumbnail_cache)))
                            self.apply_thumbnail(path, photo)
                        if image:
                            image.close()
                    elif kind in {"done", "cancelled", "error"}:
                        self.busy = False
                        self.convert_button.config(state="normal")
                        self.cancel_button.config(state="disabled")
                        if kind == "done":
                            result, open_after = payload
                            self.status.config(
                                text=f"完成: {result.page_count}ページ / スキップ{len(result.skipped)}件"
                            )
                            if result.skipped and not self.closing:
                                messagebox.showwarning(
                                    "スキップした画像",
                                    "\n".join(
                                        f"{item.path.name}: {item.reason}"
                                        for item in result.skipped
                                    ),
                                )
                            if open_after and not self.closing:
                                try:
                                    if sys.platform == "win32":
                                        os.startfile(result.output_path)
                                    else:
                                        subprocess.Popen(
                                            [
                                                "open" if sys.platform == "darwin" else "xdg-open",
                                                str(result.output_path),
                                            ]
                                        )
                                except OSError as error:
                                    messagebox.showwarning("PDFを開けません", str(error))
                        elif kind == "cancelled":
                            self.status.config(
                                text="キャンセルしました（既存PDFは変更していません）"
                            )
                        else:
                            self.status.config(text="変換に失敗しました")
                            if not self.closing:
                                messagebox.showerror("変換エラー", payload)
            except queue.Empty:
                pass
            if self.closing and not self.busy:
                root.destroy()
                return
            root.after(80, self.poll)

        def close(self):
            if self.closing:
                return
            if self.busy and not messagebox.askyesno(
                "終了確認", "変換をキャンセルして終了しますか？"
            ):
                return
            self.closing = True
            self.cancel_event.set()
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.status.config(text="終了処理中…")

    Application()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
