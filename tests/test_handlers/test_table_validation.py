"""Validate required PostgreSQL columns without modifying existing tables."""

from unittest.mock import Mock

import pytest

from landlensdb.handlers.db import IMPORT_TABLE_COLUMNS, validate_table


def test_valid_table_can_have_additional_columns():
    cursor = Mock()
    cursor.fetchall.return_value = [*IMPORT_TABLE_COLUMNS.items(), ("id", "int8")]
    validate_table(cursor, "images", IMPORT_TABLE_COLUMNS)
    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[0].startswith("SELECT ")


def test_all_missing_and_incompatible_columns_are_reported_together():
    columns = dict(IMPORT_TABLE_COLUMNS)
    del columns["input_sha"]
    del columns["metadata"]
    columns["geometry"] = "text"
    cursor = Mock()
    cursor.fetchall.return_value = list(columns.items())
    with pytest.raises(ValueError) as error:
        validate_table(cursor, "old_images", IMPORT_TABLE_COLUMNS, schema="survey")
    assert "survey.old_images" in str(error.value)
    assert "missing input_sha (text)" in str(error.value)
    assert "missing metadata (jsonb)" in str(error.value)
    assert "geometry is text; expected geometry" in str(error.value)
    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[0].startswith("SELECT ")


def test_missing_or_inaccessible_table_is_reported():
    cursor = Mock()
    cursor.fetchall.return_value = []
    with pytest.raises(ValueError, match="does not exist or is not accessible"):
        validate_table(cursor, "missing", IMPORT_TABLE_COLUMNS)


def test_schema_and_requirements_are_explicit_parameters():
    cursor = Mock()
    cursor.fetchall.return_value = [("label", "varchar"), ("id", "int8")]
    schema = 'survey "one"'
    table = "images; DROP TABLE important"
    validate_table(cursor, table, {"label": "varchar", "id": "int8"}, schema=schema)
    statement, parameters = cursor.execute.call_args.args
    assert schema not in statement and table not in statement
    assert parameters == (schema, table)
    assert cursor.execute.call_count == 1
