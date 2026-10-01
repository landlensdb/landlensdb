import json
from pathlib import Path

import pytest
import yaml
from PIL import Image
from shapely.geometry import Point, Polygon

from landlensdb.handlers.importer import (
    build_geometry,
    build_metadata,
    import_local_images,
    resolve_sidecar,
    discover_image_paths,
)
from landlensdb import import_config
from landlensdb.import_config import (
    calculate_input_sha,
    load_example_import_json,
    load_import_presets,
    normalize_import_json,
    parse_import_json,
)


def _example_config():
    config = parse_import_json(load_import_presets()["geotagged_photos.json"])
    config["file_glob"] = str(Path("test_data/local").resolve() / "**/*.jpg")
    config["thumbnail"]["enabled"] = False
    return config


def test_json_hash_ignores_formatting_and_key_order():
    config = _example_config()
    first = json.dumps(config, indent=2)
    second = json.dumps(dict(reversed(list(config.items()))))
    assert normalize_import_json(first) == normalize_import_json(second)
    assert calculate_input_sha(first) == calculate_input_sha(second)
    config["metadata"]["survey"] = "changed"
    assert calculate_input_sha(config) != calculate_input_sha(first)


def test_whole_number_thumbnail_dimensions_normalize_without_changing_input():
    config = _example_config()
    expected_json = normalize_import_json(config)
    expected_sha = calculate_input_sha(config)
    config["thumbnail"].update(width=256.0, height=256.0)

    normalized = import_config.validate_import_config(config)

    for key in ("width", "height"):
        assert type(normalized["thumbnail"][key]) is int
        assert normalized["thumbnail"][key] == 256
        assert type(config["thumbnail"][key]) is float
    assert normalize_import_json(json.dumps(config)) == expected_json
    assert calculate_input_sha(config) == expected_sha


@pytest.mark.parametrize("key", ["width", "height"])
@pytest.mark.parametrize(
    "value",
    [
        0,
        -1,
        0.0,
        -1.0,
        256.5,
        True,
        False,
        "256",
        None,
        [],
        {},
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_thumbnail_dimensions_reject_values_that_are_not_positive_whole_numbers(
    key, value
):
    config = _example_config()
    config["thumbnail"][key] = value
    with pytest.raises(ValueError, match=r"thumbnail\." + key):
        import_config.validate_import_config(config)


def test_import_geotagged_photos_with_decimal_thumbnail_dimensions():
    config = _example_config()
    config["file_glob"] = str(Path("test_data/local").resolve() / "*.JPG")
    config["thumbnail"].update(enabled="source", width=256.0, height=256.0)

    images = import_local_images(config, on_error="error")

    assert len(images) == 3
    for _, row in images.iterrows():
        thumbnail = row["thumbnail"]
        assert max(thumbnail.RasterXSize, thumbnail.RasterYSize) == 256
        for key in ("width", "height"):
            assert type(row["metadata"]["import_params"]["thumbnail"][key]) is int


def test_all_built_in_presets_use_compact_json():
    presets = load_import_presets()
    assert list(presets) == [
        "georeferenced_rasters.json",
        "geotagged_photos.json",
        "worldview3.json",
    ]
    for value in presets.values():
        config = parse_import_json(value)
        assert config["file_glob"].startswith("/path/to/")
        assert "output_crs" not in config
        assert "required" not in value
        assert "default" not in value
    for name in ("georeferenced_rasters.json", "geotagged_photos.json"):
        assert parse_import_json(presets[name])["thumbnail"] == {
            "enabled": "source",
            "width": 256,
            "height": 256,
            "resampling": "lanczos",
        }
    photos = parse_import_json(presets["geotagged_photos.json"])
    assert photos["file_glob"] == "/path/to/photos/**/*.@(jpg|JPG|png|PNG|jpeg|JPEG)"
    assert photos["metadata"]["camera"]["model"] == "exif.Model"
    worldview = parse_import_json(presets["worldview3.json"])
    assert not {"width", "height", "resampling"} & worldview["thumbnail"].keys()
    assert worldview["metadata"]["sidecar_path"] == "./{base}.IMD"
    assert worldview["geometry"] == {
        "upper_left": ["sidecar.BAND_*.ULLon", "sidecar.BAND_*.ULLat"],
        "upper_right": ["sidecar.BAND_*.URLon", "sidecar.BAND_*.URLat"],
        "lower_right": ["sidecar.BAND_*.LRLon", "sidecar.BAND_*.LRLat"],
        "lower_left": ["sidecar.BAND_*.LLLon", "sidecar.BAND_*.LLLat"],
    }


def test_template_discovery_has_no_fixed_filenames_or_required_default(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(import_config, "IMPORT_TEMPLATE_DIRECTORY", tmp_path)
    assert load_import_presets() == {}
    assert load_example_import_json() == "{}"
    (tmp_path / "My survey.JSON").write_text('{"custom": true}')
    (tmp_path / "notes.txt").write_text("ignore")
    (tmp_path / "folder.json").mkdir()
    assert load_import_presets() == {"My survey.JSON": '{"custom": true}'}
    assert load_example_import_json() == '{"custom": true}'


@pytest.mark.parametrize(
    "template, extensions",
    [
        ("geotagged_photos.json", ["jpg", "jpeg", "png"]),
        ("georeferenced_rasters.json", ["tif", "tiff", "vrt", "img", "jp2"]),
        ("worldview3.json", ["til"]),
    ],
)
def test_template_globs_include_lowercase_and_uppercase_extensions(
    tmp_path, template, extensions
):
    config = parse_import_json(load_import_presets()[template])
    expected = []
    for extension in extensions:
        for index, spelling in enumerate((extension, extension.upper())):
            assert spelling in config["file_glob"].split("@(", 1)[1].rstrip(")").split(
                "|"
            )
            path = tmp_path / ("photo_{}.{}".format(index, spelling))
            path.touch()
            expected.append(path)
    (tmp_path / "unrelated.gif").touch()
    pattern = str(tmp_path / config["file_glob"].split("/", 4)[-1])
    assert set(discover_image_paths(pattern)) == set(expected)


@pytest.mark.parametrize("field", ["file_glob", "name", "image_url", "geometry"])
@pytest.mark.parametrize("value", [None, "", {}, False])
def test_derived_fields_reject_missing_or_invalid_values(field, value):
    config = _example_config()
    config[field] = value
    with pytest.raises(ValueError, match=field):
        import_local_images(config)
    del config[field]
    with pytest.raises(ValueError, match=field):
        import_local_images(config)


@pytest.mark.parametrize(
    "old_option", ["source", "required", "default", "output_crs", "geometry_latitude"]
)
def test_old_configuration_options_are_rejected(old_option):
    config = _example_config()
    config[old_option] = {}
    with pytest.raises(ValueError, match="Unknown import options"):
        parse_import_json(json.dumps(config))


def test_yaml_and_old_python_arguments_are_not_supported():
    with pytest.raises(json.JSONDecodeError):
        parse_import_json("source: {file_glob: /photos/*.jpg}")
    with pytest.raises(TypeError):
        import_local_images(source_file_glob="/photos/*.jpg")
    with pytest.raises(ValueError, match="JSON object"):
        import_local_images(load_example_import_json())


def test_metadata_resolves_expressions_and_preserves_literals():
    schema = {
        "camera": {"model": "exif.Model", "missing": "exif.Absent"},
        "survey": "Survey A",
        "domain": "example.com",
        "number": 42,
        "enabled": True,
        "empty": None,
        "constant": "constant",
        "items": ["file.name", "literal", {"x": "geometry.x"}],
    }
    result = build_metadata(
        schema,
        exif={"Model": "Camera"},
        raster={},
        sidecar={},
        file={"name": "photo.jpg"},
        geometry=Point(-157, 21),
    )
    assert result == {
        "camera": {"model": "Camera", "missing": None},
        "survey": "Survey A",
        "domain": "example.com",
        "number": 42,
        "enabled": True,
        "empty": None,
        "constant": "constant",
        "items": ["photo.jpg", "literal", {"x": -157.0}],
    }
    assert schema["camera"]["model"] == "exif.Model"


def test_import_stores_json_configuration_and_sha():
    config = _example_config()
    images = import_local_images(config)
    assert len(images) == 3
    assert set(("input_sha", "metadata", "thumbnail")) <= set(images.columns)
    assert images["input_sha"].nunique() == 1
    assert images.iloc[0]["input_sha"] == calculate_input_sha(config)
    assert "import_params" not in images.columns
    assert images.iloc[0]["metadata"]["import_params"] == config
    assert images.crs.to_epsg() == 4326


def test_stored_import_parameters_are_independent_per_row():
    config = _example_config()
    images = import_local_images(config)
    images.iloc[0]["metadata"]["import_params"]["metadata"]["new_key"] = "changed"
    assert "new_key" not in config["metadata"]
    assert "new_key" not in images.iloc[1]["metadata"]["import_params"]["metadata"]


def test_import_params_metadata_key_is_reserved():
    config = _example_config()
    config["metadata"]["import_params"] = {"wrong": "configuration"}
    with pytest.raises(ValueError, match="metadata.import_params.*reserved"):
        import_local_images(config)


def test_progress_and_output_crs_are_separate_runtime_controls():
    updates = []

    class FakeDbFilter:
        def filter_existing_rows(self, paths):
            return [str(paths[0])]

    config = _example_config()
    # Date/time metadata needs WGS84 coordinates even when output is projected.
    images = import_local_images(
        config,
        output_crs="EPSG:3857",
        progress_callback=lambda processed, total: updates.append((processed, total)),
        skip_images_in_postgresql=FakeDbFilter(),
        skip_existing=True,
    )
    assert len(images) == 1
    assert updates == [(0, 1), (1, 1)]
    assert images.crs.to_epsg() == 3857
    assert "import_params" not in images.columns
    assert images.iloc[0]["metadata"]["import_params"] == config
    assert images.iloc[0]["input_sha"] == calculate_input_sha(config)


@pytest.mark.parametrize("field", ["name", "image_url"])
def test_missing_derived_values_fail_the_import(field):
    config = _example_config()
    config[field] = "exif.DoesNotExist"
    with pytest.raises(ValueError, match="Required " + field):
        import_local_images(config, on_error="error")


def test_exif_geometry_uses_coordinate_references_automatically():
    exif = {
        "GPSInfo": {
            "GPSLatitude": [21, 30, 0],
            "GPSLatitudeRef": "S",
            "GPSLongitude": [157, 45, 0],
            "GPSLongitudeRef": "W",
        }
    }
    point = build_geometry(
        "point_from_exif", exif=exif, raster={}, sidecar={}, output_crs="EPSG:4326"
    )
    assert point.equals(Point(-157.75, -21.5))
    del exif["GPSInfo"]["GPSLongitudeRef"]
    assert (
        build_geometry(
            "point_from_exif", exif=exif, raster={}, sidecar={}, output_crs="EPSG:4326"
        )
        is None
    )


def test_raster_geometry_uses_embedded_crs_and_bounds():
    raster = {
        "width": 2,
        "height": 1,
        "projection": "EPSG:3857",
        "geotransform": (
            0,
            111319.49079327357,
            0,
            111325.1428663851,
            0,
            -111325.1428663851,
        ),
    }
    geometry = build_geometry(
        "bounds_from_image", exif={}, raster=raster, sidecar={}, output_crs="EPSG:4326"
    )
    assert geometry.bounds == pytest.approx((0, 0, 2, 1))


def test_timestamp_timezone_is_independent_of_output_crs():
    exif = {
        "DateTimeOriginal": "2024:01:01 12:00:00",
        "GPSInfo": {
            "GPSLatitude": 21.3069,
            "GPSLatitudeRef": "N",
            "GPSLongitude": 157.8583,
            "GPSLongitudeRef": "W",
        },
    }
    point = build_geometry(
        "point_from_exif", exif=exif, raster={}, sidecar={}, output_crs="EPSG:3857"
    )
    metadata = build_metadata(
        {"captured_at": "exif_parse_time_to_timez.DateTimeOriginal"},
        exif=exif,
        raster={},
        sidecar={},
        file={},
        geometry=point,
        output_crs="EPSG:3857",
    )
    assert metadata["captured_at"] == "2024-01-01T12:00:00-10:00"


def test_sidecar_path_selects_only_the_named_file(tmp_path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"image")
    (tmp_path / "photo.yml").write_text("one: 1", encoding="utf-8")
    (tmp_path / "photo.yaml").write_text("two: 2", encoding="utf-8")

    assert resolve_sidecar(image, "./{base}.yml") == {"one": 1}
    assert resolve_sidecar(image, "./{base}.yaml") == {"two": 2}


def test_sidecar_path_returns_empty_metadata_when_configured_file_is_missing(tmp_path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"image")

    assert resolve_sidecar(image, "./{base}.json") == {}
    assert resolve_sidecar(image, None) == {}


def test_imd_preserves_source_groups_for_template_geometry(tmp_path):
    image = tmp_path / "scene.TIL"
    image.write_bytes(b"image")
    (tmp_path / "scene.IMD").write_text(
        """generationTime = \"2024-01-01T00:00:00Z\";
BEGIN_GROUP = IMAGE_1
  satId = \"WV03\";
  firstLineTime = \"2024-01-01T01:02:03Z\";
END_GROUP = IMAGE_1
BEGIN_GROUP = BAND_P
  ULLon = -158.2;
  ULLat = 21.7;
  URLon = -157.8;
  URLat = 21.7;
  LRLon = -157.8;
  LRLat = 21.3;
  LLLon = -158.2;
  LLLat = 21.3;
END_GROUP = BAND_P
END;
""",
        encoding="utf-8",
    )

    sidecar = resolve_sidecar(image, "./{base}.IMD")

    assert sidecar["generationTime"] == "2024-01-01T00:00:00Z"
    assert sidecar["IMAGE_1"]["satId"] == "WV03"
    assert sidecar["BAND_P"]["ULLon"] == -158.2
    assert set(sidecar) == {"generationTime", "IMAGE_1", "BAND_P"}
    geometry = build_geometry(
        parse_import_json(load_import_presets()["worldview3.json"])["geometry"],
        exif={},
        raster={},
        sidecar=sidecar,
        output_crs="EPSG:4326",
    )
    assert geometry.bounds == pytest.approx((-158.2, 21.3, -157.8, 21.7))


def _corner_config():
    return {
        "file_glob": "/path/to/images/*.jpg",
        "name": "file.name",
        "image_url": "file.path",
        # Intentionally not in ring order: names determine the corner order.
        "geometry": {
            "lower_left": [
                "sidecar.product.footprint.3.lon",
                "sidecar.product.footprint.3.lat",
            ],
            "upper_left": [
                "sidecar.product.footprint.0.lon",
                "sidecar.product.footprint.0.lat",
            ],
            "lower_right": [
                "sidecar.product.footprint.2.lon",
                "sidecar.product.footprint.2.lat",
            ],
            "upper_right": [
                "sidecar.product.footprint.1.lon",
                "sidecar.product.footprint.1.lat",
            ],
        },
        "metadata": {
            "sidecar_path": "./{base}.json",
            "columns": "sidecar.product.numColumns",
        },
        "thumbnail": {"enabled": False},
        "fingerprint": {"enabled": False},
    }


@pytest.mark.parametrize("suffix", ["json", "yaml"])
def test_import_resolves_arbitrary_sidecar_corners_and_preserves_footprint(
    tmp_path, suffix
):
    image = tmp_path / "scene.jpg"
    Image.new("RGB", (2, 2)).save(image)
    corners = [(-158.2, 21.6), (-157.9, 21.7), (-157.8, 21.4), (-158.1, 21.3)]
    sidecar = {
        "product": {
            "numColumns": 2,
            "footprint": [{"lon": str(lon), "lat": lat} for lon, lat in corners],
        }
    }
    content = json.dumps(sidecar) if suffix == "json" else yaml.safe_dump(sidecar)
    image.with_suffix("." + suffix).write_text(content, encoding="utf-8")
    config = _corner_config()
    config["file_glob"] = str(image)
    config["metadata"]["sidecar_path"] = "./{base}." + suffix
    # Canonical JSON sorts the corner keys; this must not change the footprint.
    config = parse_import_json(normalize_import_json(config))
    images = import_local_images(config, on_error="error")
    assert len(images) == 1
    row = images.iloc[0]
    assert row.geometry.equals_exact(Polygon(corners), 1e-10)
    assert row.geometry.area < row.geometry.envelope.area
    assert row["metadata"] == {"columns": 2, "import_params": config}
    assert row["image_url"] == str(image)
    assert "import_params" not in row.index
    assert row["metadata"]["import_params"] == config
    assert row["input_sha"] == calculate_input_sha(config)


def test_literal_corners_need_no_sidecar_and_use_runtime_output_crs():
    config = _corner_config()
    del config["metadata"]["sidecar_path"]
    config["geometry"] = {
        "upper_left": [0, 1],
        "upper_right": [1, 1],
        "lower_right": [1, 0],
        "lower_left": [0, 0],
    }
    config = parse_import_json(json.dumps(config))
    geometry = build_geometry(
        config["geometry"], exif={}, raster={}, sidecar={}, output_crs="EPSG:3857"
    )
    assert geometry.bounds == pytest.approx(
        (0, 0, 111319.49079327357, 111325.1428663851)
    )


@pytest.mark.parametrize(
    "corner", ["upper_left", "upper_right", "lower_right", "lower_left"]
)
def test_geometry_requires_all_four_corners(corner):
    config = _corner_config()
    del config["geometry"][corner]
    with pytest.raises(ValueError, match="four corners"):
        parse_import_json(json.dumps(config))


@pytest.mark.parametrize(
    "pair", [[1], [1, 2, 3], [None, 1], [True, 1], [1, {}], "sidecar.corner"]
)
def test_geometry_rejects_malformed_corner_pairs(pair):
    config = _corner_config()
    config["geometry"]["upper_left"] = pair
    with pytest.raises(ValueError, match="geometry.upper_left"):
        parse_import_json(json.dumps(config))


def test_sidecar_corner_paths_require_sidecar_path():
    config = _corner_config()
    del config["metadata"]["sidecar_path"]
    with pytest.raises(ValueError, match="sidecar_path"):
        parse_import_json(json.dumps(config))


def test_hardcoded_sidecar_geometry_mode_is_rejected():
    config = _corner_config()
    config["geometry"] = "bounds_from_sidecar"
    with pytest.raises(ValueError, match="Unsupported geometry"):
        parse_import_json(json.dumps(config))


@pytest.mark.parametrize(
    "value", [None, "not a coordinate", "NaN", "Infinity", True, {}, []]
)
def test_geometry_rejects_missing_or_nonnumeric_metadata_coordinates(value):
    config = _corner_config()
    sidecar = {"product": {"footprint": [{"lon": value, "lat": 21}]}}
    with pytest.raises(ValueError, match="geometry.upper_left.*finite coordinates"):
        build_geometry(
            config["geometry"],
            exif={},
            raster={},
            sidecar=sidecar,
            output_crs="EPSG:4326",
        )


def test_crossed_corners_are_rejected():
    with pytest.raises(ValueError, match="valid polygon"):
        build_geometry(
            {
                "upper_left": [0, 1],
                "upper_right": [1, 0],
                "lower_right": [1, 1],
                "lower_left": [0, 0],
            },
            exif={},
            raster={},
            sidecar={},
            output_crs="EPSG:4326",
        )


@pytest.mark.parametrize("on_error", ["skip", "warn", "error"])
@pytest.mark.parametrize("sidecar_exists", [False, True])
def test_missing_corner_values_follow_import_error_policy(
    tmp_path, on_error, sidecar_exists
):
    image = tmp_path / "scene.jpg"
    Image.new("RGB", (2, 2)).save(image)
    if sidecar_exists:
        image.with_suffix(".json").write_text("{}")
    config = _corner_config()
    config["file_glob"] = str(image)
    batches = import_local_images(config, on_error=on_error, return_as_yield=True)
    if on_error == "error":
        with pytest.raises(ValueError, match="Required geometry.upper_left"):
            list(batches)
    elif on_error == "warn":
        with pytest.warns(UserWarning, match="Required geometry.upper_left"):
            assert list(batches) == []
    else:
        assert list(batches) == []


def test_unsupported_sidecar_format_is_rejected(tmp_path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"image")
    (tmp_path / "photo.txt").write_text("not: accepted", encoding="utf-8")

    try:
        resolve_sidecar(image, "./{base}.txt")
    except ValueError as exc:
        assert "supported formats" in str(exc)
        assert ".imd" in str(exc)
    else:
        raise AssertionError("Unsupported sidecars should be rejected")


def test_on_error_error_propagates_import_failures(tmp_path):
    (tmp_path / "invalid.jpg").write_bytes(b"not an image")
    config = _example_config()
    config["file_glob"] = str(tmp_path / "*.jpg")
    with pytest.raises(ValueError, match="Required geometry"):
        import_local_images(config, on_error="error")
