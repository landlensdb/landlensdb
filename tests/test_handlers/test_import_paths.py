"""Keep the discovered path as the image identifier, including mapped drives."""

import os
from pathlib import Path, PureWindowsPath

import pytest

from landlensdb.handlers import importer


def config(pattern):
    return {
        "file_glob": pattern,
        "name": "file.name",
        "image_url": "file.path",
        "geometry": {
            "upper_left": [0, 1],
            "upper_right": [1, 1],
            "lower_right": [1, 0],
            "lower_left": [0, 0],
        },
        "metadata": {"name": "file.name", "image_url": "file.path"},
        "thumbnail": {"enabled": False},
    }


@pytest.mark.parametrize(
    "path",
    [
        r"S:\Satellite_Imagery\Big_Island\scene.TIL",
        r"\\IMAGERY\SatelliteImagery\Satellite_Imagery\Big_Island\scene.TIL",
    ],
)
def test_windows_discovery_preserves_the_glob_path_in_row_and_metadata(
    monkeypatch, path
):
    class MatchedWindowsPath(PureWindowsPath):
        def is_file(self):
            return True

        def absolute(self):
            assert self.is_absolute()
            return self

        def resolve(self):
            pytest.fail("Discovery must not expand drive mappings or resolve links")

    monkeypatch.setattr(importer, "Path", MatchedWindowsPath)
    monkeypatch.setattr(
        importer.wcglob, "iglob", lambda *args, **kwargs: iter([path, path])
    )
    images = importer.import_local_images(config(path), on_error="error")
    assert len(images) == 1
    assert images.iloc[0]["image_url"] == path
    assert images.iloc[0]["metadata"]["image_url"] == path


def test_relative_glob_keeps_link_name_and_adjacent_sidecar(tmp_path, monkeypatch):
    original = tmp_path / "original.jpg"
    original.write_bytes(b"Metadata-only import")
    linked = tmp_path / "selected.jpg"
    linked.symlink_to(original)
    linked.with_suffix(".json").write_text('{"value": "beside selected file"}')
    monkeypatch.chdir(tmp_path)
    settings = config("./selected*.jpg")
    settings["metadata"].update(sidecar_path="./{base}.json", value="sidecar.value")
    row = importer.import_local_images(settings, on_error="error").iloc[0]
    assert row["name"] == "selected.jpg"
    assert row["image_url"] == str(linked)
    assert row["metadata"]["image_url"] == str(linked)
    assert row["metadata"]["value"] == "beside selected file"


@pytest.mark.parametrize(
    "pattern",
    [
        "photos/**/*.@(jpg|JPG)|!photos/**/scene_skip.jpg",
        "photos/{selected,sibling}/**/scene_[12].{jpg,png}",
        "photos/*/scene_*.jpg",
        "photos/selected/scene_1.jpg",
        "photos/selected/**/*.jpg|photos/sibling/**/*.png",
        "photos/selected/../selected/**/*.jpg",
    ],
)
@pytest.mark.parametrize("prefix", ["absolute", "relative", "dot_relative"])
@pytest.mark.parametrize("subfolder", ["photos/selected", "outside"])
@pytest.mark.parametrize("recursive", [False, True])
def test_folder_discovery_matches_original_glob_without_scanning_elsewhere(
    tmp_path, monkeypatch, pattern, prefix, subfolder, recursive
):
    for folder in [
        "photos/selected",
        "photos/selected/nested",
        "photos/sibling",
        "outside",
    ]:
        directory = tmp_path / folder
        directory.mkdir(parents=True, exist_ok=True)
        for filename in ["scene_1.jpg", "scene_2.png", "scene_skip.jpg", "other.jpg"]:
            (directory / filename).touch()
    monkeypatch.chdir(tmp_path)
    if prefix == "absolute":
        # Only the top-level separator joins patterns; extension alternatives
        # inside @(...) are deliberately preserved for the original matcher.
        pattern = pattern.replace("|photos/", "|" + str(tmp_path / "photos") + "/")
        pattern = pattern.replace("|!photos/", "|!" + str(tmp_path / "photos") + "/")
        pattern = str(tmp_path) + "/" + pattern
    elif prefix == "dot_relative":
        pattern = "./" + pattern.replace("|photos/", "|./photos/").replace(
            "|!photos/", "|!./photos/"
        )
    folder = tmp_path / subfolder
    expected = [
        path
        for path in importer.discover_image_paths(pattern)
        if Path(os.path.abspath(path)).is_relative_to(folder)
        and (recursive or Path(os.path.abspath(path)).parent == folder)
    ]
    if "scene_skip" in pattern:
        assert all(path.name != "scene_skip.jpg" for path in expected)
    scanned = []
    original_scandir = os.scandir

    def scan(path):
        directory = Path(os.path.abspath(path))
        assert directory.is_relative_to(folder), "Scanned outside the selected folder"
        assert recursive or directory == folder, "Scanned a subfolder without recursion"
        scanned.append(directory)
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", scan)
    assert (
        importer.discover_image_paths(
            pattern, search_folder=folder, recursive=recursive
        )
        == expected
    )
    if expected:
        assert scanned


def test_folder_import_keeps_the_main_import_hash_and_metadata(tmp_path):
    selected = tmp_path / "selected"
    selected.mkdir()
    (selected / "scene.jpg").touch()
    (tmp_path / "other.jpg").touch()
    settings = config(str(tmp_path / "**/*.jpg"))
    main = importer.import_local_images(settings, on_error="error")
    paths = importer.discover_image_paths(settings["file_glob"], search_folder=selected)
    updated = importer.import_local_images(
        settings, discovered_paths=paths, on_error="error"
    )
    assert len(main) == 2 and len(updated) == 1
    assert set(updated["input_sha"]) == set(main["input_sha"])
    assert updated.iloc[0]["metadata"]["import_params"] == settings
