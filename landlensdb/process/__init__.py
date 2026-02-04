from .snap import snap_to_road_network, create_bbox, align_compass_with_road
from .road_network import (
    get_osm_lines,
    optimize_network_for_snapping,
    validate_network_topology,
    create_network_cache_dir,
)

__all__ = [
    "snap_to_road_network",
    "create_bbox",
    "align_compass_with_road",
    "get_osm_lines",
    "optimize_network_for_snapping",
    "validate_network_topology",
    "create_network_cache_dir",
]


# Lazy import for anonymize module (requires optional dependencies)
def __getattr__(name):
    if name == "Anonymizer":
        from .anonymize import Anonymizer

        return Anonymizer
    elif name == "anonymize_images":
        from .anonymize import anonymize_images

        return anonymize_images
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
