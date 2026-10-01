"""Upstream anonymization integrated with JSON imports, paths, and thumbnails."""

from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image

from landlensdb.handlers.importer import (
    import_local_images,
    prepare_import_paths,
)
from landlensdb.import_config import (
    load_import_presets,
    parse_import_json,
    validate_import_config,
)
from landlensdb.process import anonymize


@pytest.fixture
def photo_config(tmp_path):
    source = tmp_path / "photos"
    for flight in ("flight1", "flight2"):
        target = source / flight / "scene.JPG"
        target.parent.mkdir(parents=True)
        with Image.open("test_data/local/R0012872.JPG") as image:
            exif = image.getexif().tobytes()
            image.thumbnail((80, 40))
            image.save(target, exif=exif)
    config = parse_import_json(load_import_presets()["geotagged_photos.json"])
    config["file_glob"] = str(source / "**/*.JPG")
    config["anonymize"] = {
        "enabled": True,
        "source_dir": str(source),
        "output_dir": str(source / "anonymized"),
    }
    return config


@pytest.fixture
def fake_model(tmp_path, monkeypatch):
    model = tmp_path / "model.pt"
    model.touch()
    monkeypatch.setattr(anonymize, "_check_yolo_available", lambda: True)
    monkeypatch.setattr(anonymize, "get_default_model_path", lambda: str(model))
    monkeypatch.setattr(anonymize, "_get_device", lambda: "cpu")

    def red_pixels(self, image):
        result = np.zeros_like(image)
        result[:, :, 2] = 255  # Inference receives BGR pixels.
        return result

    monkeypatch.setattr(anonymize.Anonymizer, "_detect_and_blur", red_pixels)
    factory = Mock(wraps=anonymize.Anonymizer)
    monkeypatch.setattr(anonymize, "Anonymizer", factory)
    return factory


def test_disabled_anonymization_never_initializes_model(photo_config, fake_model):
    photo_config["anonymize"]["enabled"] = False
    images = import_local_images(photo_config, on_error="error")
    assert len(images) == 2
    fake_model.assert_not_called()


def test_anonymized_import_preserves_geotags_and_uses_output_for_previews(
    photo_config, fake_model
):
    source = Path(photo_config["anonymize"]["source_dir"])
    originals = {path: path.read_bytes() for path in source.rglob("*.JPG")}
    updates = []
    images = import_local_images(
        photo_config,
        on_error="error",
        max_workers=2,
        batch_size=1,
        progress_callback=lambda done, total: updates.append((done, total)),
    )
    assert len(images) == 2
    fake_model.assert_called_once_with(model_path=None)
    assert updates == [(0, 2), (1, 2), (2, 2)]
    assert set(images.image_url) == {
        str(source / "anonymized" / flight / "scene.JPG")
        for flight in ("flight1", "flight2")
    }
    for _, row in images.iterrows():
        assert row.metadata["image_url"] == row.image_url
        assert row.metadata["camera"]["make"]
        assert not row.geometry.is_empty
        assert row.thumbnail.ReadAsArray()[:, 0, 0].tolist() == pytest.approx(
            [255, 0, 0], abs=2
        )
        with Image.open(row.image_url) as output:
            assert output.getexif().get_ifd(34853)  # GPS IFD survives writing.
    assert all(path.read_bytes() == content for path, content in originals.items())

    # Generated files beneath the search root must not become new input images.
    repeated = import_local_images(photo_config, on_error="error")
    assert set(repeated.image_url) == set(images.image_url)


def test_existing_output_urls_skip_processing_and_model_loading(
    photo_config, fake_model
):
    database = Mock()
    database.filter_existing_rows.return_value = []
    with pytest.raises(ValueError, match="No new files"):
        import_local_images(photo_config, skip_images_in_postgresql=database)
    targets = database.filter_existing_rows.call_args.args[0]
    assert targets == [
        Path(photo_config["anonymize"]["output_dir"]) / flight / "scene.JPG"
        for flight in ("flight1", "flight2")
    ]
    fake_model.assert_not_called()


def test_incremental_import_checks_output_urls_and_reads_only_missing_source(
    photo_config, fake_model
):
    expected = str(Path(photo_config["anonymize"]["output_dir"]) / "flight2/scene.JPG")
    database = Mock()
    database.filter_existing_rows.return_value = [expected]
    images = import_local_images(
        photo_config, skip_images_in_postgresql=database, on_error="error"
    )
    assert images.image_url.tolist() == [expected]


def test_explicit_overwrite_retains_geotags_for_later_imports(photo_config, fake_model):
    photo_config["anonymize"] = {"enabled": True, "overwrite": True}
    first = import_local_images(photo_config, on_error="error")
    photo_config["anonymize"]["enabled"] = False
    second = import_local_images(photo_config, on_error="error")
    assert second.image_url.tolist() == first.image_url.tolist()
    assert second.geometry.equals(first.geometry)
    fake_model.assert_called_once()


@pytest.mark.parametrize(
    "options",
    [
        {"enabled": "yes"},
        {"enabled": True},
        {"enabled": True, "overwrite": True, "output_dir": "/output"},
        {"enabled": True, "overwrite": 1},
        {"source_dir": 42},
        {"unknown": True},
    ],
)
def test_invalid_anonymization_config_fails_before_reading_images(
    photo_config, options
):
    photo_config["anonymize"] = options
    with pytest.raises(ValueError):
        validate_import_config(photo_config)


def test_output_cannot_replace_source_without_explicit_overwrite(photo_config):
    photo_config["anonymize"]["output_dir"] = photo_config["anonymize"]["source_dir"]
    with pytest.raises(ValueError, match="must not contain"):
        prepare_import_paths(photo_config, [])


def test_anonymization_error_does_not_import_unprocessed_images(
    photo_config, fake_model
):
    fake_model.side_effect = RuntimeError("model unavailable")
    with pytest.raises(RuntimeError, match="model unavailable"):
        import_local_images(photo_config, on_error="error")
