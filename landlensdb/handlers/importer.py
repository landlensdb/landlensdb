"""Function-based, parameter-driven local image imports."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import threading
import warnings
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

import pytz
import yaml
from PIL import Image
from shapely.geometry import Point, Polygon
from timezonefinder import TimezoneFinder
from wcmatch import glob as wcglob

from ..geoclasses.geoimageframe import GeoImageFrame
from ..import_config import (
    GEOMETRY_CORNERS,
    normalize_import_json,
    validate_import_config,
    validate_sidecar_path,
)
from .local import (
    ImportCancelledError,
    _create_thumbnail_dataset,
    _get_exif_data,
    _get_raster_metadata,
    _normalize_metadata_value,
    _to_decimal,
)


def _wcmatch_flags() -> int:
    """Enable the useful opt-in wcmatch syntax and traversal features."""
    names = (
        "GLOBSTAR",
        "BRACE",
        "EXTGLOB",
        "NEGATE",
        "NEGATEALL",
        "SPLIT",
        "IGNORECASE",
        "DOTGLOB",
        "FOLLOW",
        "GLOBTILDE",
        "GLOBSTARLONG",
        "NUMRANGE",
    )
    flags = 0
    for name in names:
        flags |= getattr(wcglob, name, 0)
    return flags


WCMATCH_FLAGS = _wcmatch_flags()
SUPPORTED_SIDECAR_EXTENSIONS = (".json", ".geojson", ".yaml", ".yml", ".imd")
_WORKER_LOCAL = threading.local()


def _escape_glob_separators(pattern: str) -> str:
    """Quote literal Windows backslashes for wcmatch without parsing the path."""
    return pattern.replace("\\", "\\\\") if sys.platform == "win32" else pattern


def _check_cancelled(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise ImportCancelledError("Image import cancelled.")


class _FolderGlob(wcglob.Glob):
    """Run the original glob while pruning traversal to a selected subtree."""

    def __init__(self, pattern, folder, cancel_event, recursive=True):
        super().__init__(pattern, flags=WCMATCH_FLAGS)
        self.folder = Path(os.path.abspath(folder))
        self.cancel_event = cancel_event
        self.recursive = recursive

    def _iter(self, curdir, dir_only, deep):
        # Use wcmatch's traversal hook so its pattern parsing, exclusions, and
        # path spelling stay identical to a full import. Ancestors only expose
        # the next directory leading to the selected folder, without scanning.
        _check_cancelled(self.cancel_event)
        directory = Path(os.path.abspath(curdir or "."))
        if directory.is_relative_to(self.folder):
            if not self.recursive and directory != self.folder:
                return
            for entry in super()._iter(curdir, dir_only, deep):
                _check_cancelled(self.cancel_event)
                yield entry
        elif self.folder.is_relative_to(directory):
            for special in self.specials:
                yield special, True, True, False
            child = self.folder.relative_to(directory).parts[0]
            child_path = directory / child
            if child_path.is_dir():
                yield child, True, self._is_hidden(child), child_path.is_symlink()


def discover_image_paths(
    file_glob: str, *, cancel_event=None, search_folder=None, recursive=True
) -> list[Path]:
    """Return glob matches, optionally confined to a folder with optional recursion."""
    if not isinstance(file_glob, str) or not file_glob.strip():
        raise ValueError("`file_glob` must be a non-empty string.")
    _check_cancelled(cancel_event)
    pattern = _escape_glob_separators(file_glob)
    folder = Path(os.path.abspath(search_folder)) if search_folder is not None else None
    matches = (
        wcglob.iglob(pattern, flags=WCMATCH_FLAGS)
        if folder is None
        else _FolderGlob(pattern, folder, cancel_event, recursive).glob()
    )
    paths = set()
    for match in matches:
        _check_cancelled(cancel_event)
        path = Path(match)
        if folder is not None:
            absolute = Path(os.path.abspath(path))
            if not absolute.is_relative_to(folder):
                continue
            if not recursive and absolute.parent != folder:
                continue
        if path.is_file():
            # Preserve mapped drives and symlink paths used by the search glob.
            paths.add(path.absolute())
    _check_cancelled(cancel_event)
    return sorted(paths)


def prepare_import_paths(config, paths):
    """Pair source paths with stored URLs, excluding generated anonymized copies."""
    options = config.get("anonymize", {})
    if not options.get("enabled", False) or options.get("overwrite", False):
        return paths, paths
    source_dir = Path(options["source_dir"]).absolute()
    output_dir = Path(options["output_dir"]).absolute()
    if source_dir.is_relative_to(output_dir):
        raise ValueError("Anonymization output must not contain the source directory.")
    sources, outputs = [], []
    for path in paths:
        path = Path(path).absolute()
        if path.is_relative_to(output_dir):
            continue
        try:
            relative = path.relative_to(source_dir)
        except ValueError:
            raise ValueError("Image is outside `anonymize.source_dir`: {}".format(path))
        sources.append(path)
        outputs.append(output_dir / relative)
    return sources, outputs


def filter_folder_image_urls(
    config, image_urls, folder, extensions, *, recursive=False, cancel_event=None
):
    """Select stored URLs by source folder and extensions, including missing files."""
    folder = Path(os.path.abspath(folder))
    extensions = {extension.lower().lstrip(".") for extension in extensions}
    if not extensions:
        raise ValueError("Choose at least one extension.")
    options = config.get("anonymize", {})
    mapped = options.get("enabled", False) and not options.get("overwrite", False)
    if mapped:
        source_dir = Path(os.path.abspath(options["source_dir"]))
        output_dir = Path(os.path.abspath(options["output_dir"]))
    selected = []
    for image_url in image_urls:
        _check_cancelled(cancel_event)
        source = Path(image_url)
        if not source.is_absolute():
            continue
        source = Path(os.path.abspath(source))
        if mapped:
            if not source.is_relative_to(output_dir):
                continue
            source = source_dir / source.relative_to(output_dir)
        if not source.is_relative_to(folder):
            continue
        relative = source.relative_to(folder)
        if (recursive or len(relative.parts) == 1) and source.suffix.lower().lstrip(
            "."
        ) in extensions:
            selected.append(image_url)
    _check_cancelled(cancel_event)
    return selected


def _load_json_sidecar(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_yaml_sidecar(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _parse_imd_scalar(value: str) -> Any:
    """Convert an IMD scalar to a JSON-compatible value."""
    value = value.strip().rstrip(";")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _load_imd_sidecar(path: Path) -> dict[str, Any]:
    """Read key/value groups without interpreting field names or deriving metadata."""
    root: dict[str, Any] = {}
    groups = [(None, root)]
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or line == "END;":
                continue
            if "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            key = key.strip()
            value = _parse_imd_scalar(raw_value)
            if key == "BEGIN_GROUP":
                group = {}
                parent = groups[-1][1]
                if value in parent:
                    raise ValueError("Duplicate IMD group: {}".format(value))
                parent[value] = group
                groups.append((value, group))
            elif key == "END_GROUP":
                if len(groups) == 1 or groups[-1][0] != value:
                    raise ValueError("Mismatched IMD group: {}".format(value))
                groups.pop()
            else:
                groups[-1][1][key] = value
    if len(groups) != 1:
        raise ValueError("Unclosed IMD group: {}".format(groups[-1][0]))
    return root


SIDECAR_LOADERS = {
    ".json": _load_json_sidecar,
    ".geojson": _load_json_sidecar,
    ".yaml": _load_yaml_sidecar,
    ".yml": _load_yaml_sidecar,
    ".imd": _load_imd_sidecar,
}


def find_sidecar_path(image_path: Path, relative_path: str) -> Path | None:
    """Check one relative file, shared by metadata and thumbnail sidecars."""
    validate_sidecar_path(relative_path)
    sidecar_path = image_path.parent / relative_path.replace("{base}", image_path.stem)
    # One stat, no directory listing or realpath walk. The OS resolves ./ and ../,
    # including their correct meaning when a directory is a symlink.
    if not sidecar_path.is_file():
        return None
    return sidecar_path


def resolve_sidecar(image_path: Path, relative_path: str | None) -> dict[str, Any]:
    """Load an exact relative path, leaving metadata empty when the file is absent."""
    if relative_path is None:
        return {}
    sidecar_path = find_sidecar_path(image_path, relative_path)
    if sidecar_path is None:
        return {}
    suffix = sidecar_path.suffix.lower()
    loader = SIDECAR_LOADERS.get(suffix)
    if loader is None:
        raise ValueError(
            "Unsupported sidecar format {!r}; supported formats are {}.".format(
                suffix or sidecar_path.name,
                ", ".join(SUPPORTED_SIDECAR_EXTENSIONS),
            )
        )
    try:
        value = loader(sidecar_path)
    except FileNotFoundError:
        # The file can disappear between the existence check and open.
        return {}
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Sidecar metadata must contain a mapping at its root.")
    return _normalize_metadata_value(value)


def _lookup(mapping: Mapping[str, Any], path: str) -> Any:
    value: Any = mapping
    components = path.split(".") if path else ()
    for index, component in enumerate(components):
        if isinstance(value, Mapping):
            if component not in value and any(char in component for char in "*?["):
                remaining = ".".join(components[index + 1 :])
                for key, candidate in value.items():
                    if fnmatchcase(str(key), component):
                        match = _lookup(candidate, remaining)
                        if match is not None:
                            return match
                return None
            value = value.get(component)
        elif (
            isinstance(value, list)
            and component.isdecimal()
            and int(component) < len(value)
        ):
            value = value[int(component)]
        else:
            return None
    return value


def _file_values(path: Path, *, include_stat: bool = True) -> dict[str, Any]:
    values = {
        "path": str(path),
        "name": path.name,
        "stem": path.stem,
        "suffix": path.suffix.lower(),
    }
    if include_stat:
        stat = path.stat()
        values.update(
            size=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_ctime).astimezone().isoformat(),
            modified_at=datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
        )
    return values


def _geometry_values(geometry: Point | Polygon | None) -> dict[str, Any]:
    if geometry is None:
        return {}
    values = {
        "wkt": geometry.wkt,
        "bounds": list(geometry.bounds),
    }
    if isinstance(geometry, Point):
        values.update({"x": geometry.x, "y": geometry.y})
    return values


def _parse_exif_time(value: Any, geometry: Point | Polygon | None) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    parsed = None
    for date_format in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, date_format)
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Unable to parse EXIF time {!r}.".format(raw)) from exc
    if parsed.tzinfo is not None:
        return parsed.isoformat()
    if geometry is None:
        return parsed.isoformat()
    point = geometry if isinstance(geometry, Point) else geometry.centroid
    finder = getattr(_WORKER_LOCAL, "timezone_finder", None)
    if finder is None:
        finder = _WORKER_LOCAL.timezone_finder = TimezoneFinder()
    timezone_name = finder.timezone_at(lat=point.y, lng=point.x)
    if not timezone_name:
        return parsed.isoformat()
    return pytz.timezone(timezone_name).localize(parsed).isoformat()


def resolve_source_value(value: Any, **contexts) -> Any:
    """Resolve recognized source expressions and preserve other values literally."""
    if not isinstance(value, str) or "." not in value:
        return value
    namespace, field = value.split(".", 1)
    if namespace == "exif_parse_time_to_timez":
        geometry = contexts["geometry"]
        if geometry is not None:
            geometry = _transform_geometry(
                geometry, contexts.get("output_crs", "EPSG:4326"), "EPSG:4326"
            )
        return _parse_exif_time(_lookup(contexts["exif"], field), geometry)
    if namespace == "geometry":
        return _lookup(_geometry_values(contexts["geometry"]), field)
    if namespace in {"exif", "raster", "sidecar", "file"}:
        return _lookup(contexts[namespace], field)
    return value


def build_metadata(value: Any, **contexts) -> Any:
    """Resolve metadata leaves, preserving nested objects, arrays, and literals."""
    if isinstance(value, dict):
        return {key: build_metadata(item, **contexts) for key, item in value.items()}
    if isinstance(value, list):
        return [build_metadata(item, **contexts) for item in value]
    return _normalize_metadata_value(resolve_source_value(value, **contexts))


def _coordinate(value: Any) -> float | None:
    if value is None:
        return None
    return float(_to_decimal(value))


def _transform_geometry(geometry, input_crs: str | None, output_crs: str):
    if not input_crs or input_crs == output_crs:
        return geometry
    from osgeo import osr

    source_ref = osr.SpatialReference()
    target_ref = osr.SpatialReference()
    source_ref.SetFromUserInput(input_crs)
    target_ref.SetFromUserInput(output_crs)
    source_ref.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    target_ref.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    transform = osr.CoordinateTransformation(source_ref, target_ref)

    def convert(x, y):
        transformed = transform.TransformPoint(float(x), float(y))
        return transformed[0], transformed[1]

    if isinstance(geometry, Point):
        return Point(*convert(geometry.x, geometry.y))
    return Polygon([convert(x, y) for x, y in geometry.exterior.coords])


def build_geometry(source, *, exif, raster, sidecar, output_crs, file=None):
    """Derive geometry from image coordinates or four explicit metadata corners."""
    if isinstance(source, dict):
        resolved = build_metadata(
            source,
            exif=exif,
            raster=raster,
            sidecar=sidecar,
            file=file or {},
            geometry=None,
            output_crs=output_crs,
        )
        corners = []
        for corner in GEOMETRY_CORNERS:
            pair = resolved[corner]
            try:
                if any(value is None or isinstance(value, bool) for value in pair):
                    raise ValueError
                coordinates = tuple(float(value) for value in pair)
                if not all(math.isfinite(value) for value in coordinates):
                    raise ValueError
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    "Required geometry.{} must resolve to two finite coordinates; got {!r}.".format(
                        corner, pair
                    )
                ) from exc
            corners.append(coordinates)
        geometry = Polygon(corners)
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError("Geometry corners must form a valid polygon.")
        return _transform_geometry(geometry, "EPSG:4326", output_crs)

    if source == "point_from_exif":
        gps = exif.get("GPSInfo", {})
        lat = _coordinate(gps.get("GPSLatitude"))
        lon = _coordinate(gps.get("GPSLongitude"))
        lat_ref = str(gps.get("GPSLatitudeRef", "")).upper()
        lon_ref = str(gps.get("GPSLongitudeRef", "")).upper()
        if (
            lat is None
            or lon is None
            or lat_ref not in {"N", "S"}
            or lon_ref not in {"E", "W"}
        ):
            return None
        lat = -abs(lat) if lat_ref == "S" else abs(lat)
        lon = -abs(lon) if lon_ref == "W" else abs(lon)
        return _transform_geometry(Point(lon, lat), "EPSG:4326", output_crs)

    if source == "bounds_from_image":
        transform = raster.get("geotransform")
        width = raster.get("width")
        height = raster.get("height")
        projection = raster.get("projection")
        if transform is None or width is None or height is None or not projection:
            return None

        def pixel_to_map(pixel_x, pixel_y):
            origin_x, pixel_width, rotation_x, origin_y, rotation_y, pixel_height = (
                transform
            )
            return (
                origin_x + pixel_x * pixel_width + pixel_y * rotation_x,
                origin_y + pixel_x * rotation_y + pixel_y * pixel_height,
            )

        corners = [
            pixel_to_map(x, y)
            for x, y in ((0, 0), (width, 0), (width, height), (0, height))
        ]
        return _transform_geometry(Polygon(corners), projection, output_crs)

    raise ValueError("Unsupported geometry: {!r}.".format(source))


def calculate_file_fingerprint(
    image_path: Path,
    *,
    enabled: bool,
    mode: str,
    sample_size: int = 65536,
) -> str | None:
    """Calculate a robust or sampled SHA-256 file fingerprint."""
    if not enabled:
        return None
    if mode not in {"robust", "quick"}:
        raise ValueError("`fingerprint_mode` must be 'robust' or 'quick'.")
    hasher = hashlib.sha256()
    with image_path.open("rb") as handle:
        if mode == "robust":
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        else:
            file_size = image_path.stat().st_size
            offsets = {
                0,
                max(file_size // 2 - sample_size // 2, 0),
                max(file_size - sample_size, 0),
            }
            for offset in sorted(offsets):
                handle.seek(offset)
                hasher.update(handle.read(sample_size))
            hasher.update(str(file_size).encode("utf-8"))
    return hasher.hexdigest()


def _metadata_requirements(config: Mapping[str, Any]) -> set[str]:
    """Determine image reads once per import, including nested metadata leaves."""
    sources = set()

    def visit(value):
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str):
            namespace, separator, field = value.partition(".")
            if separator:
                if namespace in {"exif", "exif_parse_time_to_timez"}:
                    sources.add("exif")
                elif namespace == "raster":
                    sources.add("raster")
                elif namespace == "file" and field in {
                    "size",
                    "created_at",
                    "modified_at",
                }:
                    sources.add("file_stat")

    for key in ("name", "image_url", "geometry"):
        visit(config.get(key))
    for key, value in config.get("metadata", {}).items():
        if key != "sidecar_path":
            visit(value)
    if config["geometry"] == "point_from_exif":
        sources.add("exif")
    elif config["geometry"] == "bounds_from_image":
        sources.add("raster")
    return sources


def _load_image_record(
    image_path, config, *, sources, output_crs, input_sha, transform_image=None
):
    metadata_config = config.get("metadata", {})
    sidecar = resolve_sidecar(image_path, metadata_config.get("sidecar_path"))
    exif = {}
    if "exif" in sources:
        try:
            with Image.open(image_path) as image:
                exif = _normalize_metadata_value(_get_exif_data(image))
        except Exception:
            pass
    raster = {}
    if "raster" in sources:
        try:
            raster = _get_raster_metadata(image_path)
        except Exception:
            pass
    file = _file_values(image_path, include_stat="file_stat" in sources)
    geometry = build_geometry(
        config["geometry"],
        exif=exif,
        raster=raster,
        sidecar=sidecar,
        output_crs=output_crs,
        file=file,
    )
    if geometry is None or geometry.is_empty:
        raise ValueError("Required geometry could not be resolved.")

    if transform_image is not None:
        image_path = transform_image(image_path)
        file = _file_values(image_path, include_stat="file_stat" in sources)

    contexts = dict(
        exif=exif,
        raster=raster,
        sidecar=sidecar,
        file=file,
        geometry=geometry,
        output_crs=output_crs,
    )
    values = {
        key: resolve_source_value(config[key], **contexts)
        for key in ("name", "image_url")
    }
    for key, value in values.items():
        if value is None or not str(value).strip():
            raise ValueError("Required {} could not be resolved.".format(key))

    thumbnail_config = config.get("thumbnail", {})
    thumbnail = None
    thumbnail_mode = thumbnail_config.get("enabled", "source")
    thumbnail_path = image_path
    if thumbnail_mode == "sidecar":
        thumbnail_path = find_sidecar_path(
            image_path,
            thumbnail_config["sidecar_path"],
        )
    if thumbnail_mode and thumbnail_path is not None:
        thumbnail = _create_thumbnail_dataset(
            thumbnail_path,
            size=(
                thumbnail_config.get("width"),
                thumbnail_config.get("height"),
            ),
            resampling=thumbnail_config.get("resampling"),
            corners=(
                list(geometry.exterior.coords)[:4]
                if thumbnail_mode == "sidecar" and isinstance(config["geometry"], dict)
                else None
            ),
            output_crs=output_crs,
        )
    fingerprint = config.get("fingerprint", {})
    metadata = build_metadata(
        {key: value for key, value in metadata_config.items() if key != "sidecar_path"},
        **contexts,
    )
    metadata["import_params"] = deepcopy(config)
    return {
        "name": str(values["name"]),
        "image_url": str(values["image_url"]),
        "geometry": geometry,
        "metadata": metadata,
        "thumbnail": thumbnail,
        "fingerprint": calculate_file_fingerprint(
            image_path,
            enabled=fingerprint.get("enabled", False),
            mode=fingerprint.get("mode", "robust"),
        ),
        "input_sha": input_sha,
    }


def _chunked(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _frame(records, output_crs):
    frame = GeoImageFrame(records, geometry="geometry")
    frame.set_crs(output_crs, inplace=True)
    return frame


def import_local_images(
    config: Mapping[str, Any],
    *,
    output_crs: str = "EPSG:4326",
    max_workers: int = 1,
    batch_size: int = 100,
    return_as_yield: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
    skip_images_in_postgresql=None,
    skip_existing: bool = True,
    on_error: Literal["skip", "warn", "error"] = "skip",
    cancel_event: threading.Event | None = None,
    discovered_paths: list[Path] | None = None,
):
    """Import images from a parsed JSON config with separate runtime controls.

    ``discovered_paths`` reuses files already found by a folder-scoped update
    without traversing the directories again
    or changing the stored import parameters and group SHA.
    """
    if max_workers < 1 or batch_size < 1:
        raise ValueError("`max_workers` and `batch_size` must be positive integers.")
    if on_error not in {"skip", "warn", "error"}:
        raise ValueError("`on_error` must be 'skip', 'warn', or 'error'.")
    config = validate_import_config(config)
    import_params = normalize_import_json(config)
    input_sha = hashlib.sha256(import_params.encode("utf-8")).hexdigest()
    sources = _metadata_requirements(config)
    _check_cancelled(cancel_event)
    paths = (
        discover_image_paths(config["file_glob"], cancel_event=cancel_event)
        if discovered_paths is None
        else list(discovered_paths)
    )
    if not paths:
        raise ValueError("No files match `file_glob`: {}".format(config["file_glob"]))
    paths, image_urls = prepare_import_paths(config, paths)
    anonymize_options = config.get("anonymize", {})
    anonymize_enabled = anonymize_options.get("enabled", False)
    output_paths = dict(zip(paths, image_urls)) if anonymize_enabled else {}
    if skip_existing and skip_images_in_postgresql is not None:
        _check_cancelled(cancel_event)
        missing = skip_images_in_postgresql.filter_existing_rows(image_urls)
        if anonymize_enabled:
            missing = {str(path) for path in missing}
            paths = [path for path in paths if str(output_paths[path]) in missing]
        else:
            paths = [Path(path) for path in missing]
    if not paths:
        raise ValueError("No new files match `file_glob`.")
    _check_cancelled(cancel_event)

    def batches():
        processed = 0
        total = len(paths)
        stop_event = threading.Event()
        _check_cancelled(cancel_event)
        if progress_callback:
            progress_callback(0, total)

        anonymizer = None
        anonymize_lock = threading.Lock()

        def anonymize_image(path):
            nonlocal anonymizer
            # Reuse one model per import; inference on it must be serialized.
            with anonymize_lock:
                _check_cancelled(cancel_event)
                _check_cancelled(stop_event)
                if anonymizer is None:
                    from ..process.anonymize import Anonymizer

                    anonymizer = Anonymizer(
                        model_path=anonymize_options.get("model_path")
                    )
                output = output_paths[path]
                anonymizer.anonymize_image(str(path), str(output))
                _check_cancelled(cancel_event)
                return output

        def load_batch(batch):
            records = []
            for path in batch:
                _check_cancelled(cancel_event)
                _check_cancelled(stop_event)
                try:
                    record = _load_image_record(
                        path,
                        config,
                        sources=sources,
                        output_crs=output_crs,
                        input_sha=input_sha,
                        transform_image=anonymize_image if anonymize_enabled else None,
                    )
                except ImportCancelledError:
                    raise
                except Exception as exc:
                    if on_error == "error":
                        raise
                    if on_error == "warn":
                        warnings.warn("Skipped {}: {}".format(path, exc), stacklevel=2)
                    continue
                if record is not None:
                    records.append(record)
            return records

        executor = ThreadPoolExecutor(max_workers=max_workers)
        remaining = iter(_chunked(paths, batch_size))
        futures = {}

        def submit_next():
            batch = next(remaining, None)
            if batch is not None:
                futures[executor.submit(load_batch, batch)] = len(batch)

        try:
            # Keep only one batch per worker queued, and release completed batches.
            for _ in range(max_workers):
                submit_next()
            while futures:
                _check_cancelled(cancel_event)
                done, _ = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in done:
                    _check_cancelled(cancel_event)
                    batch_count = futures.pop(future)
                    records = future.result()
                    processed += batch_count
                    if progress_callback:
                        progress_callback(processed, total)
                    if records:
                        yield _frame(records, output_crs)
                    _check_cancelled(cancel_event)
                    submit_next()
        finally:
            stop_event.set()
            executor.shutdown(wait=True, cancel_futures=True)

    if return_as_yield:
        return batches()
    frames = list(batches())
    if not frames:
        raise ValueError("Matched files, but none could be imported.")
    records = [record for frame in frames for record in frame.to_dict(orient="records")]
    return _frame(records, output_crs)
