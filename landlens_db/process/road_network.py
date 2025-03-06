import os
import time
import warnings
from datetime import datetime

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pandas as pd
from shapely.geometry import Point, LineString, box
from rtree import index

def get_osm_lines(bbox, network_type='drive', cache_dir=None, retries=3):
    """
    Fetch OSM road network for a given bounding box.
    
    Args:
        bbox (list): Bounding box coordinates [minx, miny, maxx, maxy]
        network_type (str): Type of network to fetch ('drive', 'walk', etc.)
        cache_dir (str): Directory to cache downloaded data
        retries (int): Number of times to retry on failure
        
    Returns:
        GeoDataFrame: Road network as linestrings
    """
    minx, miny, maxx, maxy = bbox
    
    # Add buffer to ensure we capture roads just outside the points
    buffer_dist = 0.001  # ~100m at equator
    maxx += buffer_dist
    maxy += buffer_dist
    minx -= buffer_dist
    miny -= buffer_dist
    
    # Create bbox tuple for OSMnx 2.0.1 (north, south, east, west)
    bbox_tuple = (maxy, miny, maxx, minx)
    
    for attempt in range(retries):
        try:
            # Fetch the network using the bbox tuple
            graph = ox.graph_from_bbox(
                bbox=bbox_tuple,
                network_type=network_type,
                truncate_by_edge=True
            )
            
            # Convert to GeoDataFrame
            gdf = ox.graph_to_gdfs(graph, nodes=False, edges=True)
            
            # Project to UTM
            gdf = gdf.to_crs(epsg=4326)
            
            return gdf
            
        except Exception as e:
            if attempt < retries - 1:
                warnings.warn(f"Attempt {attempt + 1} failed, retrying...")
                continue
            raise ConnectionError(f"Failed to fetch OSM network after {retries} attempts: {str(e)}")
            
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