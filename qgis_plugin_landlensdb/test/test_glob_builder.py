"""Native paths and extension choices for the search glob builder."""

import ntpath
import posixpath
from types import SimpleNamespace

import pytest
from wcmatch import glob as wcglob

from ..shared import glob_builder


@pytest.mark.parametrize(
    "path, folder, platform, flags",
    [
        (posixpath, "/data/My Photos/", "darwin", wcglob.FORCEUNIX),
        (ntpath, "C:\\Users\\Lama\\My Photos\\", "win32", wcglob.FORCEWIN),
        (ntpath, "\\\\server\\share\\My Photos\\", "win32", wcglob.FORCEWIN),
    ],
)
@pytest.mark.parametrize("recursive", [False, True])
def test_generated_glob_matches_native_paths(
    monkeypatch, path, folder, platform, flags, recursive
):
    from ..landlensdb.handlers import importer

    monkeypatch.setattr(glob_builder, "os", SimpleNamespace(path=path))
    monkeypatch.setattr(importer.sys, "platform", platform)
    pattern = glob_builder.build_file_glob(folder, ["jpg", "png"], recursive)
    parts = ["**"] if recursive else []
    assert pattern == path.join(path.normpath(folder), *parts, "*.@(jpg|JPG|png|PNG)")
    matching_pattern = importer._escape_glob_separators(pattern)
    for name, expected in [
        ("photo.JPG", True),
        ("photo.png", True),
        ("photo.gif", False),
    ]:
        for subfolder in ["", "trip"]:
            candidate = path.join(folder, subfolder, name)
            assert wcglob.globmatch(
                candidate, matching_pattern, flags=importer.WCMATCH_FLAGS | flags
            ) == (expected and (recursive or not subfolder))


def test_empty_extension_selection_is_rejected():
    with pytest.raises(ValueError, match="Choose at least one extension"):
        glob_builder.build_file_glob("/photos", [])
