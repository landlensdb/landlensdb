"""Exact sidecar paths and import I/O regression coverage."""

import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from osgeo import gdal
from shapely.geometry import Point

from landlensdb.handlers import importer
from landlensdb.import_config import validate_import_config


@pytest.fixture
def config(tmp_path):
    return {
        "file_glob": str(tmp_path / "*.jpg"),
        "name": "file.name",
        "image_url": "file.path",
        "geometry": {
            "upper_left": [0, 1],
            "upper_right": [1, 1],
            "lower_right": [1, 0],
            "lower_left": [0, 0],
        },
        "metadata": {"sidecar_path": "./{base}.json", "value": "sidecar.value"},
        "thumbnail": {"enabled": False},
    }


@pytest.mark.parametrize(
    "relative_path, expected",
    [
        ("./{base}.json", "images/nested/photo.v1.json"),
        ("./metadata.json", "images/nested/metadata.json"),
        ("../metadata.json", "images/metadata.json"),
        ("../../metadata/{base}.json", "metadata/photo.v1.json"),
        (
            "./metadata/{base}/{base}.json",
            "images/nested/metadata/photo.v1/photo.v1.json",
        ),
    ],
)
def test_paths_are_relative_to_image_not_working_directory(
    tmp_path, monkeypatch, relative_path, expected
):
    image = tmp_path / "images/nested/photo.v1.jpg"
    image.parent.mkdir(parents=True)
    sidecar = tmp_path / expected
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text('{"value": 42}')
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert importer.resolve_sidecar(image, relative_path) == {"value": 42}


def test_parent_after_symlink_uses_filesystem_semantics(tmp_path):
    image = tmp_path / "images/photo.jpg"
    image.parent.mkdir()
    target = tmp_path / "actual/nested"
    target.mkdir(parents=True)
    (image.parent / "linked").symlink_to(target, target_is_directory=True)
    (target.parent / "metadata.json").write_text('{"value": "correct"}')
    (image.parent / "metadata.json").write_text('{"value": "wrong"}')
    assert importer.resolve_sidecar(image, "./linked/../metadata.json") == {
        "value": "correct"
    }


def test_base_substitution_preserves_literal_special_characters(tmp_path):
    image = tmp_path / "survey [1] {parent} a+b.v2.jpg"
    image.with_suffix(".json").write_text('{"value": 42}')
    assert importer.resolve_sidecar(image, "./{base}.json") == {"value": 42}


@pytest.mark.parametrize(
    "value, message",
    [
        (None, "non-empty"),
        (False, "non-empty"),
        ([], "non-empty"),
        ("", "non-empty"),
        ("  ", "non-empty"),
        ("/absolute/metadata.json", "relative"),
        ("C:/metadata.json", "relative"),
        ("C:metadata.json", "relative"),
        (r"\\server\share\metadata.json", "relative"),
        ("{parent}/{base}.json", "placeholder"),
        ("./{stem}.json", "placeholder"),
        ("./{base!r}.json", "placeholder"),
        ("./{base:>10}.json", "placeholder"),
        ("./{base.json", "placeholder"),
        ("./*.json", "glob"),
        ("../**/{base}.json", "glob"),
        ("./{base}.@(json|yaml)", "glob"),
        ("./{base}.[jJ][sS][oO][nN]", "glob"),
        ("./{base}.?son", "glob"),
    ],
)
def test_invalid_sidecar_paths_fail_before_discovery(
    config, monkeypatch, value, message
):
    config["metadata"]["sidecar_path"] = value
    discover = Mock(side_effect=AssertionError("must validate before discovery"))
    monkeypatch.setattr(importer, "discover_image_paths", discover)
    with pytest.raises(ValueError, match=message):
        importer.import_local_images(config)
    discover.assert_not_called()


def test_old_sidecar_glob_has_migration_error(config):
    config["sidecar_glob"] = config["metadata"].pop("sidecar_path")
    with pytest.raises(ValueError, match="sidecar_glob.*sidecar_path"):
        validate_import_config(config)


@pytest.mark.parametrize("section", ["metadata", "thumbnail"])
@pytest.mark.parametrize(
    "path",
    [
        "{base}.json",
        "metadata.json",
        "metadata/{base}.json",
        ".",
        "..",
        ".hidden/file.json",
        ".../file.json",
    ],
)
def test_sidecar_paths_require_explicit_relative_prefix(config, section, path):
    if section == "thumbnail":
        config[section]["enabled"] = "sidecar"
    config[section]["sidecar_path"] = path
    with pytest.raises(ValueError, match="must start with './' or '../'"):
        validate_import_config(config)


@pytest.mark.parametrize("section", ["metadata", "thumbnail"])
@pytest.mark.parametrize(
    "path", ["./{base}.json", "../{base}.json", "../../metadata/{base}.json"]
)
def test_explicit_relative_prefixes_are_valid(config, section, path):
    if section == "thumbnail":
        config[section]["enabled"] = "sidecar"
    config[section]["sidecar_path"] = path
    assert validate_import_config(config)[section]["sidecar_path"] == path


@pytest.mark.parametrize("state", ["missing", "directory", "present"])
def test_sidecar_uses_one_stat_no_scanning_and_reads_only_present_file(
    tmp_path, monkeypatch, state
):
    image = tmp_path / "photo.jpg"
    sidecar = image.with_suffix(".json")
    if state == "directory":
        sidecar.mkdir()
    elif state == "present":
        sidecar.write_text('{"value": 42}')
    stat_paths = []
    open_paths = []
    original_stat, original_open = Path.stat, Path.open

    def stat(path, *args, **kwargs):
        stat_paths.append(path)
        return original_stat(path, *args, **kwargs)

    def open_file(path, *args, **kwargs):
        open_paths.append(path)
        return original_open(path, *args, **kwargs)

    forbidden = Mock(side_effect=AssertionError("directory search or realpath walk"))
    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", stat)
        patch.setattr(Path, "open", open_file)
        patch.setattr(Path, "resolve", forbidden)
        patch.setattr(importer.wcglob, "glob", forbidden)
        patch.setattr(importer.wcglob, "iglob", forbidden)
        patch.setattr(Path, "iterdir", forbidden)
        result = importer.resolve_sidecar(image, "./{base}.json")
    assert stat_paths == [sidecar]
    assert open_paths == ([sidecar] if state == "present" else [])
    assert result == ({"value": 42} if state == "present" else {})
    forbidden.assert_not_called()


def test_disappearing_sidecar_leaves_metadata_empty(tmp_path, monkeypatch):
    image = tmp_path / "photo.jpg"
    image.with_suffix(".json").write_text("{}")
    loader = Mock(side_effect=FileNotFoundError)
    monkeypatch.setitem(importer.SIDECAR_LOADERS, ".json", loader)
    assert importer.resolve_sidecar(image, "./{base}.json") == {}
    loader.assert_called_once()


def test_sidecar_contents_and_existence_are_not_cached(tmp_path):
    image = tmp_path / "photo.jpg"
    sidecar = image.with_suffix(".json")
    assert importer.resolve_sidecar(image, "./{base}.json") == {}
    sidecar.write_text('{"value": 1}')
    assert importer.resolve_sidecar(image, "./{base}.json") == {"value": 1}
    sidecar.write_text('{"value": 2}')
    assert importer.resolve_sidecar(image, "./{base}.json") == {"value": 2}
    sidecar.unlink()
    assert importer.resolve_sidecar(image, "./{base}.json") == {}


@pytest.mark.parametrize("on_error", ["skip", "warn", "error"])
@pytest.mark.parametrize("max_workers", [1, 2])
def test_missing_sidecars_import_without_metadata_and_keep_progress(
    tmp_path, config, monkeypatch, on_error, max_workers
):
    for name in ("missing", "present", "also_missing"):
        (tmp_path / (name + ".jpg")).write_bytes(b"not decoded")
    (tmp_path / "present.json").write_text('{"value": 42}')
    forbidden = Mock(side_effect=AssertionError("unexpected image read"))
    monkeypatch.setattr(importer.Image, "open", forbidden)
    monkeypatch.setattr(importer, "_get_raster_metadata", forbidden)
    monkeypatch.setattr(importer, "_create_thumbnail_dataset", forbidden)
    updates = []
    images = importer.import_local_images(
        config,
        on_error=on_error,
        batch_size=1,
        max_workers=max_workers,
        progress_callback=lambda *values: updates.append(values),
    )
    assert set(images["name"]) == {"present.jpg", "missing.jpg", "also_missing.jpg"}
    metadata = dict(zip(images["name"], images["metadata"]))
    assert metadata == {
        "present.jpg": {"value": 42, "import_params": config},
        "missing.jpg": {"value": None, "import_params": config},
        "also_missing.jpg": {"value": None, "import_params": config},
    }
    assert updates == [(0, 3), (1, 3), (2, 3), (3, 3)]
    forbidden.assert_not_called()


def test_missing_sidecar_still_builds_requested_thumbnail_and_fingerprint(
    tmp_path, config, monkeypatch
):
    (tmp_path / "missing.jpg").write_bytes(b"image")
    config["thumbnail"]["enabled"] = True
    config["fingerprint"] = {"enabled": True}
    dataset = gdal.GetDriverByName("MEM").Create("", 1, 1, 1)
    thumbnail = Mock(return_value=dataset)
    fingerprint = Mock(return_value="fingerprint")
    monkeypatch.setattr(importer, "_create_thumbnail_dataset", thumbnail)
    monkeypatch.setattr(importer, "calculate_file_fingerprint", fingerprint)
    images = importer.import_local_images(config, on_error="error")
    assert len(images) == 1
    assert images.iloc[0]["thumbnail"] is dataset
    assert images.iloc[0]["fingerprint"] == "fingerprint"
    thumbnail.assert_called_once()
    fingerprint.assert_called_once()


@pytest.mark.parametrize("content", ["{broken", "[]"])
@pytest.mark.parametrize("on_error", ["skip", "warn", "error"])
def test_invalid_present_sidecar_obeys_error_policy(
    tmp_path, config, content, on_error
):
    (tmp_path / "photo.jpg").touch()
    (tmp_path / "photo.json").write_text(content)
    batches = importer.import_local_images(
        config, return_as_yield=True, on_error=on_error
    )
    if on_error == "error":
        with pytest.raises(ValueError):
            list(batches)
    elif on_error == "warn":
        with pytest.warns(UserWarning, match="Skipped"):
            assert list(batches) == []
    else:
        assert list(batches) == []


@pytest.mark.parametrize(
    "suffix, content",
    [("json", "{}"), ("geojson", "null"), ("yaml", ""), ("yml", "{}"), ("JSON", "{}")],
)
def test_empty_present_sidecar_does_not_skip_image(tmp_path, config, suffix, content):
    (tmp_path / "photo.jpg").touch()
    (tmp_path / ("photo." + suffix)).write_text(content)
    config["metadata"]["sidecar_path"] = "./{base}." + suffix
    images = importer.import_local_images(config, on_error="error")
    assert len(images) == 1
    assert images.iloc[0]["metadata"] == {"value": None, "import_params": config}


@pytest.mark.parametrize(
    "source",
    [
        "exif.Model",
        "raster.width",
        "file.size",
        "file.created_at",
        "file.modified_at",
        "exif_parse_time_to_timez.DateTimeOriginal",
    ],
)
@pytest.mark.parametrize("location", ["metadata", "name", "image_url"])
def test_metadata_sources_are_loaded_when_referenced(
    tmp_path, config, monkeypatch, source, location
):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"123")
    image.with_suffix(".json").write_text("{}")
    exif = Mock(
        return_value={
            "Model": "camera",
            "DateTimeOriginal": "2024-01-01T12:00:00+00:00",
        }
    )
    image_open = MagicMock()
    raster = Mock(return_value={"width": 42})
    monkeypatch.setattr(importer.Image, "open", image_open)
    monkeypatch.setattr(importer, "_get_exif_data", exif)
    monkeypatch.setattr(importer, "_get_raster_metadata", raster)
    config[location] = (
        {"nested": [{"value": source}]} if location == "metadata" else source
    )
    images = importer.import_local_images(config, on_error="error")
    result = images.iloc[0][location]
    if location == "metadata":
        result = result["nested"][0]["value"]
    expected = {
        "exif.Model": "camera",
        "raster.width": 42,
        "file.size": 3,
        "exif_parse_time_to_timez.DateTimeOriginal": "2024-01-01T12:00:00+00:00",
    }.get(source)
    if expected is not None:
        assert result == (expected if location == "metadata" else str(expected))
    else:
        assert datetime.fromisoformat(result).tzinfo is not None
    assert image_open.call_count == int(source.startswith("exif"))
    assert raster.call_count == int(source.startswith("raster."))


def test_timezone_finder_is_reused_within_worker(monkeypatch):
    constructor = Mock()
    constructor.return_value.timezone_at.return_value = "Pacific/Honolulu"
    monkeypatch.setattr(importer, "_WORKER_LOCAL", threading.local())
    monkeypatch.setattr(importer, "TimezoneFinder", constructor)
    for _ in range(3):
        assert (
            importer._parse_exif_time("2024:01:01 12:00:00", Point(-157, 21))
            == "2024-01-01T12:00:00-10:00"
        )
    constructor.assert_called_once()
    assert constructor.return_value.timezone_at.call_count == 3


def test_imd_keeps_arbitrary_nested_groups_without_required_coordinates(tmp_path):
    from landlensdb.handlers.importer import resolve_sidecar

    image = tmp_path / "sample.tif"
    (tmp_path / "sample.imd").write_text(
        'version = 2;\nBEGIN_GROUP = SENSOR;\nname = "Camera";\n'
        "BEGIN_GROUP = CALIBRATION;\ngain = 1.5;\n"
        "END_GROUP = CALIBRATION;\nEND_GROUP = SENSOR;\nEND;\n"
    )
    assert resolve_sidecar(image, "./{base}.imd") == {
        "version": 2,
        "SENSOR": {"name": "Camera", "CALIBRATION": {"gain": 1.5}},
    }


def test_json_metadata_selects_groups_using_explicit_patterns():
    from landlensdb.handlers.importer import build_metadata

    schema = {
        "reading": "sidecar.sensor_*.reading",
        "exact": "sidecar.sensor_b.reading",
        "missing": "sidecar.other_*.reading",
    }
    assert build_metadata(
        schema,
        sidecar={"sensor_a": {"reading": 0}, "sensor_b": {"reading": 12}},
    ) == {"reading": 0, "exact": 12, "missing": None}
