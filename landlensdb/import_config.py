"""Compact JSON import configurations shared by Python, PostgreSQL, and QGIS."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping

IMPORT_TEMPLATE_DIRECTORY = Path(__file__).with_name("examples")
REQUIRED_FIELDS = ("file_glob", "name", "image_url", "geometry")
GEOMETRY_MODES = {"point_from_exif", "bounds_from_image"}
GEOMETRY_CORNERS = ("upper_left", "upper_right", "lower_right", "lower_left")


def validate_sidecar_path(value: str) -> None:
    """Accept a ./ or ../ filename with only the optional ``{base}`` token."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("`sidecar_path` must be a non-empty string.")
    _validate_sidecar_path(value)


@lru_cache(maxsize=128)
def _validate_sidecar_path(value: str) -> None:
    # Cache validation by template, never by image or file existence.
    if Path(value).is_absolute() or PureWindowsPath(value).anchor:
        raise ValueError("`sidecar_path` must be relative to the image's directory.")
    literal = value.replace("{base}", "")
    if any(character in literal for character in "{}"):
        raise ValueError("`sidecar_path` only supports the {base} placeholder.")
    if any(character in literal for character in "*?[]") or any(
        token in literal for token in ("@(", "+(", "!(")
    ):
        raise ValueError("`sidecar_path` must be a literal path, not a glob.")
    if "\x00" in value:
        raise ValueError("`sidecar_path` must not contain a null character.")
    if not value.startswith(("./", "../")):
        raise ValueError(
            "`sidecar_path` must start with './' or '../', "
            "for example './{base}.json' or '../metadata/{base}.json'."
        )


def load_example_import_json() -> str:
    """Use the first available template when no configuration has been saved."""
    return next(iter(load_import_presets().values()), "{}")


def load_import_presets() -> dict[str, str]:
    """Discover the current JSON files on every call, using filenames as labels."""
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(
            IMPORT_TEMPLATE_DIRECTORY.glob("*"), key=lambda path: path.name.casefold()
        )
        if path.is_file() and path.suffix.lower() == ".json"
    }


def validate_import_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Require the compact model and reject unsupported configuration options."""
    if not isinstance(config, Mapping):
        raise ValueError("Import configuration must be a JSON object.")
    allowed = set(REQUIRED_FIELDS) | {
        "metadata",
        "thumbnail",
        "fingerprint",
        "anonymize",
    }
    unknown = set(config) - allowed
    if unknown:
        if unknown & {"sidecar_glob", "sidecar_path"}:
            raise ValueError(
                "Top-level `sidecar_glob` and `sidecar_path` are no longer supported; "
                "use `metadata.sidecar_path`, for example './{base}.json'."
            )
        raise ValueError(
            "Unknown import options: {}".format(", ".join(sorted(unknown)))
        )
    for key in ("file_glob", "name", "image_url"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError("`{}` must be a non-empty string.".format(key))
    for key in ("metadata", "thumbnail", "fingerprint", "anonymize"):
        if key in config and not isinstance(config[key], dict):
            raise ValueError("`{}` must be a JSON object.".format(key))
    metadata = config.get("metadata", {})
    if "import_params" in metadata:
        raise ValueError(
            "`metadata.import_params` is reserved for the stored import configuration."
        )
    if "sidecar_path" in metadata:
        validate_sidecar_path(metadata["sidecar_path"])
    geometry = config.get("geometry")
    if isinstance(geometry, dict):
        if set(geometry) != set(GEOMETRY_CORNERS):
            raise ValueError(
                "`geometry` must contain exactly these four corners: {}.".format(
                    ", ".join(GEOMETRY_CORNERS)
                )
            )
        for corner in GEOMETRY_CORNERS:
            pair = geometry[corner]
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError(
                    "`geometry.{}` must be [longitude, latitude].".format(corner)
                )
            for value in pair:
                if not (
                    type(value) in (int, float)
                    or isinstance(value, str)
                    and value.strip()
                ):
                    raise ValueError(
                        "`geometry.{}` coordinates must be numbers or metadata paths.".format(
                            corner
                        )
                    )
                if (
                    isinstance(value, str)
                    and value.startswith("sidecar.")
                    and not metadata.get("sidecar_path")
                ):
                    raise ValueError(
                        "Sidecar geometry paths require `metadata.sidecar_path`."
                    )
    elif not isinstance(geometry, str) or geometry not in GEOMETRY_MODES:
        raise ValueError("Unsupported geometry: {!r}.".format(geometry))
    for key, options in (
        ("thumbnail", {"enabled", "sidecar_path", "width", "height", "resampling"}),
        ("fingerprint", {"enabled", "mode"}),
    ):
        section = config.get(key, {})
        if set(section) - options:
            raise ValueError("Unknown {} options.".format(key))
        if (
            key == "fingerprint"
            and "enabled" in section
            and not isinstance(section["enabled"], bool)
        ):
            raise ValueError("`{}.enabled` must be a boolean.".format(key))
    thumbnail = config.get("thumbnail", {})
    mode = thumbnail.get("enabled", "source")
    if not (
        isinstance(mode, bool)
        or isinstance(mode, str)
        and mode in {"source", "sidecar"}
    ):
        raise ValueError(
            "`thumbnail.enabled` must be 'source', 'sidecar', or false (true also means 'source')."
        )
    if "sidecar_path" in thumbnail:
        validate_sidecar_path(thumbnail["sidecar_path"])
        if mode != "sidecar":
            raise ValueError(
                "`thumbnail.sidecar_path` requires `thumbnail.enabled` to be 'sidecar'."
            )
    elif mode == "sidecar":
        raise ValueError(
            "Sidecar thumbnails require an explicit `thumbnail.sidecar_path`."
        )
    for key in ("width", "height"):
        if key not in thumbnail:
            continue
        value = thumbnail[key]
        if (
            type(value) not in (int, float)
            or value < 1
            or (type(value) is float and not value.is_integer())
        ):
            raise ValueError("`thumbnail.{}` must be a positive integer.".format(key))
    if "resampling" in thumbnail and (
        not isinstance(thumbnail["resampling"], str)
        or not thumbnail["resampling"].strip()
    ):
        raise ValueError("`thumbnail.resampling` must be a non-empty string.")
    if config.get("fingerprint", {}).get("mode", "robust") not in {"robust", "quick"}:
        raise ValueError("`fingerprint.mode` must be 'robust' or 'quick'.")
    anonymize = config.get("anonymize", {})
    if set(anonymize) - {
        "enabled",
        "source_dir",
        "output_dir",
        "overwrite",
        "model_path",
    }:
        raise ValueError("Unknown anonymize options.")
    for key in ("enabled", "overwrite"):
        if key in anonymize and type(anonymize[key]) is not bool:
            raise ValueError("`anonymize.{}` must be a boolean.".format(key))
    for key in ("source_dir", "output_dir", "model_path"):
        if key in anonymize and (
            not isinstance(anonymize[key], str) or not anonymize[key].strip()
        ):
            raise ValueError("`anonymize.{}` must be a non-empty path.".format(key))
    if anonymize.get("enabled", False):
        if anonymize.get("overwrite", False):
            if "output_dir" in anonymize:
                raise ValueError(
                    "Choose `anonymize.output_dir` or `overwrite`, not both."
                )
        elif not all(anonymize.get(key) for key in ("source_dir", "output_dir")):
            raise ValueError(
                "Anonymization requires `source_dir` and `output_dir`, "
                "or explicit `overwrite: true`."
            )
        if geometry != "point_from_exif" or config["image_url"] != "file.path":
            raise ValueError(
                "Anonymization requires geotagged photos with "
                "`geometry: point_from_exif` and `image_url: file.path`."
            )
        if mode == "sidecar":
            raise ValueError(
                "Anonymization requires source thumbnails or disabled thumbnails."
            )
    # Snapshot the parsed JSON so callers cannot change a running import's config.
    normalized = json.loads(json.dumps(dict(config), allow_nan=False))
    for key in ("width", "height"):
        if key in thumbnail:
            normalized["thumbnail"][key] = int(thumbnail[key])
    return normalized


def parse_import_json(text: str) -> dict[str, Any]:
    """Parse and validate one JSON configuration; YAML is not accepted."""
    return validate_import_config(json.loads(text))


def normalize_import_json(value: str | Mapping[str, Any]) -> str:
    config = (
        parse_import_json(value)
        if isinstance(value, str)
        else validate_import_config(value)
    )
    return json.dumps(
        config,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def calculate_input_sha(value: str | Mapping[str, Any]) -> str:
    """Hash the JSON configuration independently of whitespace and key order."""
    return hashlib.sha256(normalize_import_json(value).encode("utf-8")).hexdigest()
