"""Exercise metadata-selected local images, including existing WorldView imports."""

import pytest
from qgis.PyQt import QtGui
from shapely.geometry import Point

from ..landlensdb.geoclasses.geoimageframe import GeoImageFrame
from ..shared.image_sources import (
    metadata_field_paths,
    metadata_value,
    resolve_image_path,
)
from ..tabs.view_tab import ViewTab
from .utilities import get_qgis_app

QGIS_APP = get_qgis_app()
BROWSE_FIELD = ("import_params", "thumbnail", "sidecar_path")


@pytest.fixture
def tab():
    widget = ViewTab(None)
    yield widget
    widget.close()
    widget.deleteLater()


def frame(*rows, **row):
    return GeoImageFrame(
        [dict(name="Scene", geometry=Point(0, 0), **item) for item in (rows or [row])]
    )


def choose_metadata(tab, path):
    tab.source_menu.aboutToShow.emit()
    menu = next(a.menu() for a in tab.source_menu.actions() if a.text() == "Metadata")
    for part in path[:-1]:
        menu = next(
            a.menu() for a in menu.actions() if a.text() == str(part) and a.menu()
        )
    next(
        a for a in menu.actions() if a.text() == str(path[-1]) and not a.menu()
    ).trigger()


def save_image(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QtGui.QImage(20, 10, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor(color))
    assert image.save(str(path))


def test_existing_browse_template_loads_each_image_and_preserves_selection(
    tab, tmp_path
):
    rows = []
    for scene, color in (("scene.one", "red"), ("scene.two", "blue")):
        save_image(tmp_path / (scene + "-BROWSE.JPG"), color)
        rows.append(
            {
                "image_url": str(tmp_path / (scene + ".TIL")),
                "metadata": {
                    "import_params": {
                        "thumbnail": {
                            "enabled": "sidecar",
                            "sidecar_path": "./{base}-BROWSE.JPG",
                        }
                    }
                },
            }
        )
    tab.set_geoimageframe(frame(*rows), source_query="SELECT * FROM images")
    tab.grid_layout.itemAt(0).widget().selection_checkbox.setChecked(True)
    choose_metadata(tab, BROWSE_FIELD)

    assert [a.text() for a in tab.source_menu.actions()] == [
        "Preview",
        "image_url",
        "Metadata",
    ]
    assert (
        tab.source_button.toolTip() == "metadata.import_params.thumbnail.sidecar_path"
    )
    for index, row in enumerate(rows):
        tile = tab.grid_layout.itemAt(index).widget()
        assert not tile.canvas._pixmap_item.pixmap().isNull()
        assert tile.status_label.text() == row["image_url"].replace(
            ".TIL", "-BROWSE.JPG"
        )
        assert tile.selection_checkbox.isChecked() == (index == 0)
    assert tab._checked_image_urls == {rows[0]["image_url"]}
    requests = []
    tab.addImagesRequested.connect(lambda *args: requests.append(args))
    tab._add_checked_images(False, True)
    assert requests == [("SELECT * FROM images", [rows[0]["image_url"]], False, True)]
    tab.north_up_toggle.setChecked(True)
    assert tab._checked_image_urls == {rows[0]["image_url"]}
    tab.source_menu.actions()[0].trigger()
    assert tab.source_button.text() == "Preview"
    assert tab._checked_image_urls == {rows[0]["image_url"]}


def test_nested_array_field_loads_a_real_image_and_reloads_for_new_rows(tab, tmp_path):
    path = tmp_path / "preview.png"
    save_image(path, "green")
    tab.set_geoimageframe(
        frame(
            image_url=str(tmp_path / "one.TIL"),
            metadata={"assets": [{"browse.path": str(path)}]},
        )
    )
    choose_metadata(tab, ("assets", 0, "browse.path"))
    assert not tab.grid_layout.itemAt(0).widget().canvas._pixmap_item.pixmap().isNull()
    tab.set_geoimageframe(frame(image_url=str(tmp_path / "two.TIL"), metadata={}))
    assert (
        "No image path in metadata.assets.0.browse.path"
        in tab.grid_layout.itemAt(0).widget().status_label.text()
    )
    tab.source_menu.aboutToShow.emit()
    metadata_menu = tab.source_menu.actions()[-1].menu()
    assert metadata_menu.actions()[0].text() == "No metadata fields"
    assert not metadata_menu.actions()[0].isEnabled()


@pytest.mark.parametrize("value", [None, "", 42, True, {}, []])
def test_missing_or_non_string_metadata_does_not_fall_back_to_original(tab, value):
    tab._set_source_mode("metadata", ("browse",))
    pixmap, status = tab._build_tile_content(
        {"image_url": "/images/source.jpg", "metadata": {"browse": value}}
    )
    assert pixmap is None
    assert "No image path in metadata.browse" in status


def test_missing_browse_file_reports_the_resolved_path(tab, tmp_path):
    tab._set_source_mode("metadata", BROWSE_FIELD)
    pixmap, status = tab._build_tile_content(
        {
            "image_url": str(tmp_path / "scene.TIL"),
            "metadata": {
                "import_params": {"thumbnail": {"sidecar_path": "./{base}-BROWSE.JPG"}}
            },
        }
    )
    assert pixmap is None
    assert str(tmp_path / "scene-BROWSE.JPG") in status


def test_image_url_and_stored_preview_remain_available(tab, tmp_path):
    path = tmp_path / "source.png"
    save_image(path, "red")
    row = {"image_url": str(path), "preview_png": path.read_bytes()}
    for mode in ("preview", "image_url"):
        tab._set_source_mode(mode)
        pixmap, status = tab._build_tile_content(row)
        assert not pixmap.isNull()
        assert status == ("Preview" if mode == "preview" else str(path))


@pytest.mark.parametrize(
    "source,value,expected",
    [
        (
            r"S:\Satellite_Imagery\scene.v1.TIL",
            "./{base}-BROWSE.JPG",
            r"S:\Satellite_Imagery\scene.v1-BROWSE.JPG",
        ),
        (
            r"\\server\share\scene.TIL",
            "../browse/{base}.JPG",
            r"\\server\share\..\browse\scene.JPG",
        ),
        (
            "/images/link/scene.TIL",
            "../browse/{base}.jpg",
            "/images/link/../browse/scene.jpg",
        ),
        ("/images/scene.TIL", "browse.jpg", "/images/browse.jpg"),
        ("/images/scene.TIL", "/other/exact.jpg", "/other/exact.jpg"),
        (r"S:\images\scene.TIL", r"T:\browse\exact.jpg", r"T:\browse\exact.jpg"),
        (None, "/other/exact.jpg", "/other/exact.jpg"),
        (None, "./{base}.jpg", None),
    ],
)
def test_resolve_metadata_paths_without_changing_drive_or_symlink(
    source, value, expected
):
    assert resolve_image_path(value, source) == expected


def test_leaf_paths_preserve_dotted_keys_array_indexes_and_missing_shapes():
    data = {"a.b": {"assets": [None, {"path": "/browse.jpg"}]}, "missing": None}
    assert list(metadata_field_paths(data)) == [
        ("a.b", "assets", 0),
        ("a.b", "assets", 1, "path"),
        ("missing",),
    ]
    assert metadata_value(data, ("a.b", "assets", 1, "path")) == "/browse.jpg"
    assert metadata_value(data, ("a.b", "assets", 2, "path")) is None
    assert metadata_value({"a.b": None}, ("a.b", "assets", 1, "path")) is None
