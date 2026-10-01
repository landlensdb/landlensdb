"""Resolve metadata fields used as local image sources in the viewer."""

from pathlib import PurePosixPath, PureWindowsPath


def metadata_field_paths(value, path=()):
    """Yield leaf paths, including array indexes, without flattening key names."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from metadata_field_paths(item, path + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from metadata_field_paths(item, path + (index,))
    elif path:
        yield path


def metadata_value(metadata, path):
    """Read one selected field; missing or differently shaped rows return None."""
    value = metadata
    for key in path:
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list) and isinstance(key, int) and key < len(value):
            value = value[key]
        else:
            return None
    return value


def resolve_image_path(value, image_url):
    """Resolve relative paths and {base} using the row's original image URL.

    Preserve mapped drives, UNC paths and symlinks; do not resolve filesystem
    links or collapse parent-directory components.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    source = image_url if isinstance(image_url, str) else ""
    path_class = (
        PureWindowsPath
        if PureWindowsPath(source).drive or PureWindowsPath(value).drive
        else PurePosixPath
    )
    if "{base}" in value:
        if not source:
            return None
        value = value.replace("{base}", path_class(source).stem)
    if path_class(value).is_absolute():
        return value
    if not path_class(source).is_absolute():
        return None
    return str(path_class(source).parent / value)
