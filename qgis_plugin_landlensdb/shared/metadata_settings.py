"""Fetch and persist the metadata parameter tree used by QGIS menus."""

import json

from psycopg2 import sql
from qgis.PyQt import QtCore


METADATA_TREE_KEY = "Landlensdb/metadata_tree"


def merge_metadata_tree(current, value):
    """Merge metadata mappings into a keys-only parameter tree."""
    if not isinstance(value, dict):
        return None
    merged = dict(current or {})
    for key, item in value.items():
        merged[key] = merge_metadata_tree(merged.get(key), item)
    return merged


def save_metadata_tree(tree):
    """Persist a metadata parameter tree in QGIS settings."""
    settings = QtCore.QSettings()
    settings.remove(METADATA_TREE_KEY)
    settings.setValue(
        METADATA_TREE_KEY,
        json.dumps(tree or {}, sort_keys=True, separators=(",", ":")),
    )


def load_metadata_tree():
    """Load the persisted metadata parameter tree."""
    value = QtCore.QSettings().value(METADATA_TREE_KEY, "{}", type=str) or "{}"
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def fetch_metadata_tree(cursor, source_query, input_sha="all"):
    """Fetch one metadata value per unique input SHA and persist its tree."""
    where_parts = [
        sql.SQL("q.input_sha IS NOT NULL"),
        sql.SQL("q.metadata IS NOT NULL"),
    ]
    parameters = []
    if input_sha != "all":
        where_parts.append(sql.SQL("q.input_sha = %s"))
        parameters.append(input_sha)
    query = sql.SQL(
        "SELECT DISTINCT ON (q.input_sha) q.input_sha, q.metadata "
        "FROM ({}) AS q WHERE {} "
        "ORDER BY q.input_sha, q.image_url"
    ).format(source_query, sql.SQL(" AND ").join(where_parts))
    if parameters:
        cursor.execute(query, parameters)
    else:
        cursor.execute(query)
    tree = {}
    for _sha, metadata in cursor.fetchall():
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (TypeError, ValueError):
                continue
        tree = merge_metadata_tree(tree, metadata or {})
    save_metadata_tree(tree)
    return tree
