from pathlib import Path

import pytest

from file_model import FileModel, list_images


def test_search_selection_removes_the_selected_path():
    model = FileModel()
    model.paths = [Path("A.jpg"), Path("B.jpg"), Path("C.jpg")]
    model.remove(model.filtered("C"))
    assert model.paths == [Path("A.jpg"), Path("B.jpg")]


@pytest.mark.parametrize(
    "direction, expected",
    [
        ("up", ["C", "A", "B"]),
        ("down", ["A", "B", "C"]),
        ("top", ["C", "A", "B"]),
        ("bottom", ["A", "B", "C"]),
    ],
)
def test_filtered_move_uses_paths(direction, expected):
    model = FileModel()
    model.paths = [Path("A"), Path("B"), Path("C")]
    model.move(model.filtered("C"), direction)
    if direction == "up":
        expected = ["A", "C", "B"]
    assert model.paths == [Path(value) for value in expected]


def test_multiple_selection_preserves_order():
    model = FileModel()
    model.paths = [Path(value) for value in "ABCDE"]
    model.move([Path("B"), Path("C")], "down")
    assert model.paths == [Path(value) for value in "ADBCE"]
    model.move([Path("B"), Path("C")], "up")
    assert model.paths == [Path(value) for value in "ABCDE"]


def test_drag_move_preserves_selection_order():
    model = FileModel()
    model.paths = [Path(value) for value in "ABCDE"]
    model.move_before([Path("D"), Path("E")], Path("B"))
    assert model.paths == [Path(value) for value in "ADEBC"]


def test_folder_ignores_directories_and_natural_sort(tmp_path):
    for name in ("image10.png", "image2.png", "IMAGE1.JPG", "notes.txt"):
        (tmp_path / name).touch()
    (tmp_path / "directory.png").mkdir()
    assert [path.name for path in list_images(tmp_path, "number")] == [
        "IMAGE1.JPG",
        "image2.png",
        "image10.png",
    ]


def test_add_deduplicates_resolved_paths(tmp_path):
    image = tmp_path / "image.png"
    image.touch()
    model = FileModel()
    assert model.add([image, tmp_path]) == 1
    assert model.paths == [image.resolve()]
