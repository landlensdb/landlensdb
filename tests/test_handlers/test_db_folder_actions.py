"""Folder deletion changes only the selected group's matching database rows."""

from pathlib import Path

import pytest
from sqlalchemy import Column, MetaData, Table, Text, create_engine, select

from landlensdb.handlers.db import Postgres
from landlensdb.handlers.importer import (
    discover_image_paths,
    filter_folder_image_urls,
    prepare_import_paths,
)


@pytest.fixture
def database():
    engine = create_engine("sqlite://")
    table = Table(
        "images",
        MetaData(),
        Column("image_url", Text, primary_key=True),
        Column("input_sha", Text),
    )
    table.create(engine)
    db = Postgres(engine)
    db.selected_table = table
    yield db
    engine.dispose()


@pytest.mark.parametrize("drop_old", [False, True])
@pytest.mark.parametrize("recursive", [False, True])
@pytest.mark.parametrize("anonymized", [False, True])
def test_folder_deletes_preserve_other_folders_extensions_and_groups(
    database, tmp_path, drop_old, recursive, anonymized
):
    root = tmp_path / "photos"
    folder = root / "flight[1]%"
    folder.mkdir(parents=True)
    existing = folder / "existing.JPG"
    existing.touch()
    missing = folder / "missing.jpg"
    nested = folder / "nested/missing.jpg"
    other_extension = folder / "missing.png"
    sibling = root / "flight[1]%extra/missing.jpg"
    other_group = folder / "other_group.jpg"
    config = {"file_glob": str(root / "**/*.jpg")}
    if anonymized:
        config["anonymize"] = {
            "enabled": True,
            "source_dir": str(root),
            "output_dir": str(tmp_path / "anonymized"),
        }

    def stored(path):
        return str(prepare_import_paths(config, [path])[1][0])

    paths = [existing, missing, nested, other_extension, sibling, other_group]
    rows = [
        {
            "image_url": stored(path),
            "input_sha": "other" if path == other_group else "group",
        }
        for path in paths
    ]
    with database.engine.begin() as connection:
        connection.execute(database.selected_table.insert(), rows)
        group_urls = (
            connection.execute(
                select(database.selected_table.c.image_url).where(
                    database.selected_table.c.input_sha == "group"
                )
            )
            .scalars()
            .all()
        )
    scope = filter_folder_image_urls(
        config, group_urls, folder, ["jpg"], recursive=recursive
    )
    expected = {stored(missing)}
    if recursive:
        expected.add(stored(nested))
    if drop_old:
        found = discover_image_paths(config["file_glob"], search_folder=folder)
        _, matched_urls = prepare_import_paths(config, found)
        deleted = database.remove_unmatched_for_input(
            "group", matched_urls, scope_image_urls=scope
        )
    else:
        expected.add(stored(existing))
        deleted = database.remove_all_for_input("group", scope_image_urls=scope)
    assert deleted == len(expected)
    with database.engine.connect() as connection:
        remaining = set(
            connection.execute(select(database.selected_table.c.image_url)).scalars()
        )
    assert remaining == {row["image_url"] for row in rows} - expected
    assert existing.is_file()


@pytest.mark.parametrize("drop_old", [False, True])
def test_empty_folder_scope_never_falls_back_to_deleting_a_group(database, drop_old):
    with database.engine.begin() as connection:
        connection.execute(
            database.selected_table.insert(),
            {"image_url": "/keep.jpg", "input_sha": "group"},
        )
    if drop_old:
        deleted = database.remove_unmatched_for_input("group", [], scope_image_urls=[])
    else:
        deleted = database.remove_all_for_input("group", scope_image_urls=[])
    assert deleted == 0
    with database.engine.connect() as connection:
        assert connection.execute(
            select(database.selected_table.c.image_url)
        ).scalars().all() == ["/keep.jpg"]


def test_folder_filter_rejects_empty_extension_selection():
    with pytest.raises(ValueError, match="Choose at least one extension"):
        filter_folder_image_urls({}, ["/photos/a.jpg"], Path("/photos"), [])


@pytest.mark.parametrize("drop_old", [False, True])
def test_group_wide_deletion_still_preserves_other_groups(database, drop_old):
    with database.engine.begin() as connection:
        connection.execute(
            database.selected_table.insert(),
            [
                {"image_url": "/keep.jpg", "input_sha": "group"},
                {"image_url": "/missing.jpg", "input_sha": "group"},
                {"image_url": "/other.jpg", "input_sha": "other"},
            ],
        )
    if drop_old:
        assert database.remove_unmatched_for_input("group", ["/keep.jpg"]) == 1
    else:
        assert database.remove_all_for_input("group") == 2
    with database.engine.connect() as connection:
        remaining = set(
            connection.execute(select(database.selected_table.c.image_url)).scalars()
        )
    assert remaining == ({"/keep.jpg", "/other.jpg"} if drop_old else {"/other.jpg"})
