"""File selection and ordering without GUI dependencies."""

import re
from pathlib import Path

SUPPORTED_EXTS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".avif",
        ".heic",
        ".heif",
        ".webp",
        ".bmp",
        ".gif",
        ".tif",
        ".tiff",
    }
)


def natural_key(path):
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in re.split(r"(\d+)", Path(path).name)
    )


def list_images(folder, order="name"):
    paths = [
        path.resolve()
        for path in Path(folder).iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS
    ]
    if order == "number":
        return sorted(paths, key=natural_key)
    if order == "date":
        return sorted(paths, key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return sorted(paths, key=lambda path: (path.name.casefold(), path.name))


class FileModel:
    def __init__(self):
        self.paths = []

    def add(self, paths):
        existing = set(self.paths)
        added = 0
        for value in paths:
            path = Path(value).expanduser().resolve()
            candidates = list_images(path) if path.is_dir() else [path]
            for candidate in candidates:
                if (
                    candidate.is_file()
                    and candidate.suffix.lower() in SUPPORTED_EXTS
                    and candidate not in existing
                ):
                    self.paths.append(candidate)
                    existing.add(candidate)
                    added += 1
        return added

    def filtered(self, query=""):
        return [path for path in self.paths if query.casefold() in path.name.casefold()]

    def remove(self, selected):
        selected = set(selected)
        self.paths = [path for path in self.paths if path not in selected]

    def move(self, selected, direction):
        selected = set(selected)
        if direction in {"top", "bottom"}:
            moving = [path for path in self.paths if path in selected]
            remaining = [path for path in self.paths if path not in selected]
            self.paths = moving + remaining if direction == "top" else remaining + moving
            return
        if direction == "up":
            for index in range(1, len(self.paths)):
                if self.paths[index] in selected and self.paths[index - 1] not in selected:
                    self.paths[index - 1], self.paths[index] = (
                        self.paths[index],
                        self.paths[index - 1],
                    )
        elif direction == "down":
            for index in range(len(self.paths) - 2, -1, -1):
                if self.paths[index] in selected and self.paths[index + 1] not in selected:
                    self.paths[index], self.paths[index + 1] = (
                        self.paths[index + 1],
                        self.paths[index],
                    )
        else:
            raise ValueError("Unknown movement direction")

    def move_before(self, selected, target):
        selected = set(selected)
        if target in selected or target not in self.paths:
            return
        moving = [path for path in self.paths if path in selected]
        remaining = [path for path in self.paths if path not in selected]
        position = remaining.index(target)
        self.paths = remaining[:position] + moving + remaining[position:]
