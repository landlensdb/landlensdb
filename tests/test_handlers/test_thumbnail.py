"""Source and exact-path browse thumbnails, independent of metadata sidecars."""

import json
from unittest.mock import Mock

import pytest
from osgeo import gdal, osr
from PIL import Image
from pyproj import Transformer

from landlensdb.handlers import importer, local
from landlensdb.handlers.db import Postgres
from landlensdb.import_config import load_import_presets, validate_import_config


@pytest.fixture
def config(tmp_path):
    image = tmp_path / "scene.TIF"
    Image.new("RGB", (40, 20), "red").save(image)
    return {
        "file_glob": str(image),
        "name": "file.name",
        "image_url": "file.path",
        "geometry": {
            "upper_left": [0, 1],
            "upper_right": [1, 1],
            "lower_right": [1, 0],
            "lower_left": [0, 0],
        },
        "metadata": {"sidecar_path": "./missing.json", "value": "sidecar.value"},
        "thumbnail": {
            "enabled": "source",
            "width": 10,
            "height": 10,
            "resampling": "nearest",
        },
    }


@pytest.mark.parametrize("mode", ["source", True, False, "sidecar"])
def test_thumbnail_modes_read_the_selected_file(config, tmp_path, mode):
    config["thumbnail"]["enabled"] = mode
    if mode == "sidecar":
        config["thumbnail"]["sidecar_path"] = "./{base}-BROWSE.JPG"
    Image.new("RGB", (16, 32), "blue").save(tmp_path / "scene-BROWSE.JPG")
    row = importer.import_local_images(config, on_error="error").iloc[0]
    assert row["metadata"] == {"value": None, "import_params": config}
    thumbnail = row["thumbnail"]
    if mode is False:
        assert thumbnail is None
    elif mode == "sidecar":
        assert (thumbnail.RasterXSize, thumbnail.RasterYSize) == (5, 10)
        red, green, blue = thumbnail.ReadAsArray()[:, 0, 0]
        assert blue > 200 and red < 10 and green < 10
    else:
        assert (thumbnail.RasterXSize, thumbnail.RasterYSize) == (10, 5)
        assert tuple(thumbnail.ReadAsArray()[:, 0, 0]) == (255, 0, 0)
        assert thumbnail.GetProjectionRef() == ""
        assert thumbnail.GetGeoTransform(can_return_null=True) is None


@pytest.mark.parametrize("mode", ["source", "sidecar"])
@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"width": 10},
        {"height": 10},
        {"resampling": "lanczos"},
        {"width": 10, "height": 10},
        {"width": 10, "resampling": "lanczos"},
        {"height": 10, "resampling": "lanczos"},
    ],
)
def test_georeferenced_thumbnail_keeps_full_image_without_all_resize_settings(
    config, tmp_path, monkeypatch, mode, settings
):
    config["thumbnail"] = {"enabled": mode, **settings}
    path = tmp_path / ("scene-BROWSE.TIF" if mode == "sidecar" else "scene.TIF")
    if mode == "sidecar":
        config["thumbnail"]["sidecar_path"] = "./{base}-BROWSE.TIF"
    Image.new("RGB", (600, 300), "blue").save(path)
    source = gdal.Open(str(path), gdal.GA_Update)
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromEPSG(3857)
    source.SetProjection(spatial_ref.ExportToWkt())
    transform = (-17300000, 10, 0, 2200000, 0, -10)
    source.SetGeoTransform(transform)
    source = None
    resample = Mock(side_effect=AssertionError("Unrequested resampling"))
    monkeypatch.setattr(local.gdal, "Translate", resample)
    monkeypatch.setattr(local.gdal, "Warp", resample)
    thumbnail = importer.import_local_images(config, on_error="error").iloc[0][
        "thumbnail"
    ]
    assert (thumbnail.RasterXSize, thumbnail.RasterYSize) == (600, 300)
    assert (thumbnail.ReadAsArray() == gdal.Open(str(path)).ReadAsArray()).all()
    assert thumbnail.GetSpatialRef().GetAuthorityCode(None) == "3857"
    assert thumbnail.GetGeoTransform() == transform
    resample.assert_not_called()


@pytest.mark.parametrize("output_crs", ["EPSG:4326", "EPSG:3857"])
@pytest.mark.parametrize("resize", [False, True])
def test_worldview_browse_stores_real_georeferencing(
    tmp_path, monkeypatch, output_crs, resize
):
    config = json.loads(load_import_presets()["worldview3.json"])
    image = tmp_path / "scene.TIL"
    image.write_bytes(b"Source imagery must not be opened for a browse thumbnail")
    config["file_glob"] = str(image)
    # A rotated footprint catches swapped corners and bounding-box-only placement.
    corners = [
        (-155.7, 19.8),
        (-155.493, 19.8414),
        (-155.4582, 19.6674),
        (-155.6652, 19.626),
    ]
    imd = ["BEGIN_GROUP = BAND_P;"]
    for prefix, (lon, lat) in zip(("UL", "UR", "LR", "LL"), corners):
        imd.extend((f"{prefix}Lon = {lon};", f"{prefix}Lat = {lat};"))
    imd.extend(("END_GROUP = BAND_P;", "END;"))
    image.with_suffix(".IMD").write_text("\n".join(imd))
    # The configuration order must not determine the GCP order.
    config["geometry"] = dict(reversed(list(config["geometry"].items())))
    browse_path = tmp_path / "scene-BROWSE.JPG"
    browse = Image.new("RGB", (1035, 870))
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    for color, box in zip(
        colors,
        [
            (0, 0, 517, 435),
            (517, 0, 1035, 435),
            (0, 435, 517, 870),
            (517, 435, 1035, 870),
        ],
    ):
        browse.paste(color, box)
    browse.save(browse_path)
    original = browse_path.read_bytes()
    if resize:
        config["thumbnail"].update(width=256, height=256, resampling="nearest")
    original_open = gdal.Open

    def open_browse_only(path, *args, **kwargs):
        assert str(path) != str(image), "Full source imagery was opened"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(local.gdal, "Open", open_browse_only)
    row = importer.import_local_images(
        config, output_crs=output_crs, on_error="error"
    ).iloc[0]
    thumbnail = row["thumbnail"]
    # Exercise the exact GeoTIFF serialization used for ST_FromGDALRaster.
    stored_path = tmp_path / "stored-thumbnail.tif"
    stored_path.write_bytes(Postgres._thumbnail_to_gdal_raster(thumbnail))
    stored = gdal.Open(str(stored_path))
    assert stored.GetSpatialRef().GetAuthorityCode(None) == output_crs.split(":")[1]
    transform = stored.GetGeoTransform(can_return_null=True)
    assert transform is not None
    assert stored.GetGeoTransform() == thumbnail.GetGeoTransform()
    minx = transform[0]
    maxy = transform[3]
    maxx = minx + stored.RasterXSize * transform[1]
    miny = maxy + stored.RasterYSize * transform[5]
    assert (minx, miny, maxx, maxy) == pytest.approx(
        row.geometry.bounds, abs=2 * max(abs(transform[1]), abs(transform[5]))
    )
    if resize:
        assert (stored.RasterXSize, stored.RasterYSize) == (256, 215)
    else:
        assert stored.RasterXSize > 1000 and stored.RasterYSize > 870
    project = Transformer.from_crs("EPSG:4326", output_crs, always_xy=True)
    inverse = gdal.InvGeoTransform(transform)
    pixels = stored.ReadAsArray()
    for (u, v), color in zip(
        ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)), colors
    ):
        lon = (
            corners[0][0]
            + u * (corners[1][0] - corners[0][0])
            + v * (corners[3][0] - corners[0][0])
        )
        lat = (
            corners[0][1]
            + u * (corners[1][1] - corners[0][1])
            + v * (corners[3][1] - corners[0][1])
        )
        pixel, line = gdal.ApplyGeoTransform(inverse, *project.transform(lon, lat))
        assert pixels[:, int(line), int(pixel)].tolist() == pytest.approx(color, abs=5)
    assert stored.GetRasterBand(1).GetNoDataValue() is None
    assert browse_path.read_bytes() == original
    assert not browse_path.with_suffix(".JPG.aux.xml").exists()


@pytest.mark.parametrize("nodata", [None, 0, 99])
def test_browse_corners_override_transform_without_crs_and_preserve_nodata(
    tmp_path, nodata
):
    path = tmp_path / "browse.tif"
    source = gdal.GetDriverByName("GTiff").Create(str(path), 10, 10, 1)
    source.SetGeoTransform((0, 1, 0, 0, 0, -1))
    source.GetRasterBand(1).Fill(50)
    if nodata is not None:
        source.GetRasterBand(1).SetNoDataValue(nodata)
    source = None
    thumbnail = local._create_thumbnail_dataset(
        path, corners=[(-156, 20), (-155, 20), (-155, 19), (-156, 19)]
    )
    assert thumbnail.GetGeoTransform() == pytest.approx((-156, 0.1, 0, 20, 0, -0.1))
    assert thumbnail.GetSpatialRef().GetAuthorityCode(None) == "4326"
    assert thumbnail.GetRasterBand(1).GetNoDataValue() == nodata
    assert gdal.Open(str(path)).GetProjectionRef() == ""


def test_unreferenced_browse_without_corners_keeps_pixel_coordinates(
    tmp_path, monkeypatch
):
    path = tmp_path / "browse.jpg"
    Image.new("RGB", (600, 300), "red").save(path)
    forbidden = Mock(side_effect=AssertionError("No coordinates for georeferencing"))
    monkeypatch.setattr(local.gdal, "Warp", forbidden)
    monkeypatch.setattr(local.gdal, "Translate", forbidden)
    thumbnail = local._create_thumbnail_dataset(path)
    assert (thumbnail.RasterXSize, thumbnail.RasterYSize) == (600, 300)
    assert thumbnail.GetProjectionRef() == ""
    assert thumbnail.GetGeoTransform(can_return_null=True) is None
    assert (thumbnail.ReadAsArray() == gdal.Open(str(path)).ReadAsArray()).all()
    forbidden.assert_not_called()


def test_thumbnail_sidecar_uses_same_relative_solver(config, tmp_path, monkeypatch):
    image = tmp_path / "images/scene.TIF"
    image.parent.mkdir()
    image.write_bytes(b"source must not be decoded")
    browse = tmp_path / "previews/scene.jpg"
    browse.parent.mkdir()
    Image.new("RGB", (24, 12)).save(browse)
    (image.parent / "metadata.json").write_text('{"value": 42}')
    config["file_glob"] = str(image)
    config["metadata"]["sidecar_path"] = "./metadata.json"
    config["thumbnail"].update(enabled="sidecar", sidecar_path="../previews/{base}.jpg")
    forbidden = Mock(side_effect=AssertionError("source image was opened"))
    monkeypatch.setattr(importer.Image, "open", forbidden)
    monkeypatch.setattr(importer, "_get_raster_metadata", forbidden)
    row = importer.import_local_images(config, on_error="error").iloc[0]
    assert row["metadata"] == {"value": 42, "import_params": config}
    assert row["thumbnail"].RasterXSize == 10
    forbidden.assert_not_called()


def test_missing_browse_does_not_read_source_or_metadata_parser(config, monkeypatch):
    config["thumbnail"].update(enabled="sidecar", sidecar_path="./{base}-BROWSE.JPG")
    forbidden = Mock(side_effect=AssertionError("missing browse must not be read"))
    monkeypatch.setattr(importer, "_create_thumbnail_dataset", forbidden)
    monkeypatch.setitem(importer.SIDECAR_LOADERS, ".json", forbidden)
    row = importer.import_local_images(config, on_error="error").iloc[0]
    assert row["thumbnail"] is None
    assert row["metadata"] == {"value": None, "import_params": config}
    forbidden.assert_not_called()


@pytest.mark.parametrize("value", [None, 0, 1, [], {}, "", "true", "browse"])
def test_invalid_thumbnail_modes_are_rejected(config, value):
    config["thumbnail"]["enabled"] = value
    with pytest.raises(ValueError, match="thumbnail.enabled"):
        validate_import_config(config)


def test_sidecar_thumbnail_requires_a_filename_in_json(config):
    config["thumbnail"]["enabled"] = "sidecar"
    with pytest.raises(ValueError, match="explicit.*thumbnail.sidecar_path"):
        validate_import_config(config)


@pytest.mark.parametrize("path", ["*.JPG", "{parent}/{base}.JPG", "/browse.JPG"])
def test_thumbnail_path_uses_metadata_path_validation(config, path):
    config["thumbnail"].update(enabled="sidecar", sidecar_path=path)
    with pytest.raises(ValueError, match="sidecar_path"):
        validate_import_config(config)


def test_source_mode_does_not_accept_ignored_sidecar_setting(config):
    config["thumbnail"]["sidecar_path"] = "./browse.JPG"
    with pytest.raises(ValueError, match="requires"):
        validate_import_config(config)


def test_only_top_level_metadata_sidecar_path_is_reserved(config, tmp_path):
    (tmp_path / "scene.json").write_text('{"value": 42}')
    config["metadata"] = {
        "sidecar_path": "./{base}.json",
        "value": "sidecar.value",
        "nested": {"sidecar_path": "ordinary user metadata"},
    }
    row = importer.import_local_images(config, on_error="error").iloc[0]
    assert row["metadata"] == {
        "import_params": config,
        "value": 42,
        "nested": {"sidecar_path": "ordinary user metadata"},
    }


def test_top_level_metadata_sidecar_setting_reports_new_location(config):
    config["sidecar_path"] = config["metadata"].pop("sidecar_path")
    with pytest.raises(ValueError, match="metadata.sidecar_path"):
        validate_import_config(config)
