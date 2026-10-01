"""Cancellation and bounded scheduling during image import."""

import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from landlensdb.handlers import importer
from landlensdb.handlers.local import ImportCancelledError


def config(tmp_path):
    return {
        "file_glob": str(tmp_path / "*.jpg"),
        "name": "file.name",
        "image_url": "file.path",
        "geometry": "point_from_exif",
        "thumbnail": {"enabled": False},
    }


def test_cancel_before_discovery_does_no_filesystem_work(tmp_path, monkeypatch):
    cancelled = threading.Event()
    cancelled.set()
    glob = Mock(side_effect=AssertionError("discovery must not start"))
    monkeypatch.setattr(importer.wcglob, "iglob", glob)
    with pytest.raises(ImportCancelledError):
        importer.import_local_images(config(tmp_path), cancel_event=cancelled)
    glob.assert_not_called()


def test_discovery_stops_between_matches(tmp_path, monkeypatch):
    cancelled = threading.Event()
    image = tmp_path / "one.jpg"
    image.touch()

    def matches(*args, **kwargs):
        yield str(image)
        cancelled.set()
        yield str(tmp_path / "two.jpg")
        pytest.fail("discovery continued after cancellation")

    monkeypatch.setattr(importer.wcglob, "iglob", matches)
    with pytest.raises(ImportCancelledError):
        importer.discover_image_paths(
            config(tmp_path)["file_glob"], cancel_event=cancelled
        )


@pytest.mark.parametrize("on_error", ["skip", "warn", "error"])
def test_cancel_stops_before_next_image_even_inside_large_batch(
    tmp_path, monkeypatch, on_error
):
    paths = [tmp_path / f"{index}.jpg" for index in range(20)]
    cancelled = threading.Event()

    def load(*args, **kwargs):
        cancelled.set()
        return None

    loader = Mock(side_effect=load)
    monkeypatch.setattr(importer, "_load_image_record", loader)
    batches = importer.import_local_images(
        config(tmp_path),
        discovered_paths=paths,
        cancel_event=cancelled,
        return_as_yield=True,
        batch_size=20,
        on_error=on_error,
    )
    with pytest.raises(ImportCancelledError):
        list(batches)
    loader.assert_called_once()


def test_batch_queue_is_bounded_and_cancellation_releases_workers(
    tmp_path, monkeypatch
):
    cancelled = threading.Event()
    submitted = []
    real_executor = importer.ThreadPoolExecutor

    class Executor(real_executor):
        def submit(self, function, batch):
            submitted.append(batch)
            return super().submit(function, batch)

    entered = threading.Event()
    release = threading.Event()

    def load(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return None

    monkeypatch.setattr(importer, "ThreadPoolExecutor", Executor)
    monkeypatch.setattr(importer, "_load_image_record", load)
    batches = importer.import_local_images(
        config(tmp_path),
        discovered_paths=[tmp_path / f"{i}.jpg" for i in range(100)],
        cancel_event=cancelled,
        return_as_yield=True,
        batch_size=1,
        max_workers=2,
    )
    errors = []

    def consume():
        try:
            list(batches)
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=consume)
    worker.start()
    try:
        assert entered.wait(3)
        cancelled.set()
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert len(submitted) <= 2
    assert len(errors) == 1 and isinstance(errors[0], ImportCancelledError)


def test_reused_discovery_does_not_glob_again(tmp_path, monkeypatch):
    discover = Mock(side_effect=AssertionError("must reuse discovery"))
    monkeypatch.setattr(importer, "discover_image_paths", discover)
    monkeypatch.setattr(importer, "_load_image_record", lambda *args, **kwargs: None)
    assert (
        list(
            importer.import_local_images(
                config(tmp_path),
                discovered_paths=[Path("already-found.jpg")],
                return_as_yield=True,
            )
        )
        == []
    )
    discover.assert_not_called()
