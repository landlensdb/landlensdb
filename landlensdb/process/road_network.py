import os
import time
import warnings
from datetime import datetime

import geopandas as gpd
import networkx as nx
import osmnx as ox
from shapely.geometry import box


def get_osm_lines(bbox, network_type='drive', cache_dir=None, retries=3):
    """Get road network from OpenStreetMap for a given bounding box.

    Args:
        bbox (list): Bounding box coordinates [minx, miny, maxx, maxy].
            Can be in any CRS.
        network_type (str, optional): Type of network to fetch.
            Defaults to 'drive' Options are: {"all", "all_public", "bike", "drive", "drive_service", "walk"}.
        cache_dir (str, optional): Directory to cache downloaded networks.
            Defaults to None.
        retries (int, optional): Number of times to retry fetching network.
            Defaults to 3.

    Returns:
        GeoDataFrame: Road network as a GeoDataFrame.

    Raises:
        ConnectionError: If network cannot be fetched after retries.
        ValueError: If bbox coordinates are invalid.
    """
    # Input validation
    if len(bbox) != 4:
        raise ValueError("bbox must contain exactly 4 coordinates")

    # Convert bbox to GeoDataFrame to handle CRS conversion
    bbox_geom = box(bbox[0], bbox[1], bbox[2], bbox[3])
    bbox_gdf = gpd.GeoDataFrame(geometry=[bbox_geom], crs="EPSG:4326")

    # Get bounds in WGS84
    bbox_wgs84 = bbox_gdf.geometry.total_bounds

    # Validate coordinates are within valid ranges
    if (bbox_wgs84[0] < -180 or bbox_wgs84[2] > 180 or
        bbox_wgs84[1] < -90 or bbox_wgs84[3] > 90):
        raise ValueError(
            "Invalid coordinates. Longitude must be between -180 and 180, "
            "latitude between -90 and 90"
        )

    # Create bbox tuple for OSMnx (left, bottom, right, top)
    west, south = min(bbox_wgs84[0], bbox_wgs84[2]), min(bbox_wgs84[1], bbox_wgs84[3])
    east, north = max(bbox_wgs84[0], bbox_wgs84[2]), max(bbox_wgs84[1], bbox_wgs84[3])
    bbox_tuple = (west, south, east, north)

    # Set up cache directory
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        ox.settings.cache_folder = cache_dir

    # Try to fetch network with retries
    for attempt in range(retries):
        try:
            # Pass bbox as a tuple
            graph = ox.graph_from_bbox(
                bbox=bbox_tuple,
                network_type=network_type,
                truncate_by_edge=True
            )
            network = ox.graph_to_gdfs(graph, nodes=False)
            return network
        except Exception as e:
            if attempt == retries - 1:
                msg = (
                    f"Failed to fetch OSM network after {retries} attempts: {str(e)}"
                )
                raise ConnectionError(msg)
            print(f"Attempt {attempt + 1} failed, retrying in 1 second...")
            time.sleep(1)

    return None

def optimize_network_for_snapping(network, simplify=True, remove_isolated=True):
    """Optimize road network for efficient snapping operations.

    Args:
        network (GeoDataFrame): The road network to optimize
        simplify (bool): Whether to simplify geometries
        remove_isolated (bool): Whether to remove isolated segments

    Returns:
        GeoDataFrame: Optimized network
    """
    if network is None or network.empty:
        return network

    # Work on a copy
    network = network.copy()

    # Ensure proper CRS
    if network.crs is None:
        network.set_crs(epsg=4326, inplace=True)

    # Simplify geometries while preserving topology
    if simplify:
        network.geometry = network.geometry.simplify(tolerance=1e-5)

    # Remove duplicate geometries
    network = network.drop_duplicates(subset='geometry')

    # Remove isolated segments if requested
    if remove_isolated:
        # Find connected components
        G = nx.Graph()
        for idx, row in network.iterrows():
            coords = list(row.geometry.coords)
            for i in range(len(coords)-1):
                G.add_edge(coords[i], coords[i+1])

        # Keep only largest component
        largest_cc = max(nx.connected_components(G), key=len)
        network = network[network.geometry.apply(
            lambda g: any(c in largest_cc for c in g.coords)
        )]

    # Create spatial index
    network.sindex

    return network

def validate_network_topology(network):
    """Validate and repair road network topology.

    Args:
        network (GeoDataFrame): Road network to validate

    Returns:
        GeoDataFrame: Validated and repaired network
        dict: Report of validation results
    """
    if network is None or network.empty:
        return network, {'status': 'empty'}

    report = {
        'original_size': len(network),
        'issues': [],
        'repairs': []
    }

    # Check for invalid geometries
    invalid_mask = ~network.geometry.is_valid
    if invalid_mask.any():
        report['issues'].append(f"Found {invalid_mask.sum()} invalid geometries")
        network.geometry = network.geometry.buffer(0)
        report['repairs'].append("Applied buffer(0) to fix invalid geometries")

    # Check for duplicate geometries
    duplicates = network.geometry.duplicated()
    if duplicates.any():
        report['issues'].append(f"Found {duplicates.sum()} duplicate geometries")
        network = network[~duplicates]
        report['repairs'].append("Removed duplicate geometries")

    # Check for null geometries
    null_geoms = network.geometry.isna()
    if null_geoms.any():
        report['issues'].append(f"Found {null_geoms.sum()} null geometries")
        network = network[~null_geoms]
        report['repairs'].append("Removed null geometries")

    # Check connectivity
    G = nx.Graph()
    for idx, row in network.iterrows():
        coords = list(row.geometry.coords)
        for i in range(len(coords)-1):
            G.add_edge(coords[i], coords[i+1])

    components = list(nx.connected_components(G))
    if len(components) > 1:
        report['issues'].append(f"Found {len(components)} disconnected components")
        report['repairs'].append("Consider using optimize_network_for_snapping() to clean")

    report['final_size'] = len(network)
    return network, report

def create_network_cache_dir():
    """Create a cache directory for storing downloaded road networks.

    Returns:
        str: Path to the cache directory
    """
    cache_dir = os.path.join(os.path.expanduser("~"), ".landlensdb", "network_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

def clear_network_cache(cache_dir=None, older_than_days=None):
    """Clear cached road networks.

    Args:
        cache_dir (str, optional): Cache directory to clear. If None, uses default.
        older_than_days (int, optional): Only clear networks older than this many days.
    """
    if cache_dir is None:
        cache_dir = create_network_cache_dir()

    if not os.path.exists(cache_dir):
        return

    for filename in os.listdir(cache_dir):
        if not filename.endswith('.gpkg'):
            continue

        filepath = os.path.join(cache_dir, filename)
        if older_than_days is not None:
            file_age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(filepath))).days
            if file_age <= older_than_days:
                continue

        try:
            os.remove(filepath)
        except Exception as e:
            warnings.warn(f"Failed to remove cached network {filename}: {str(e)}")
