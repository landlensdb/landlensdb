import math
import warnings

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
from shapely import Point
from rtree import index


def create_spatial_index(network):
    idx = index.Index()
    for i, line in enumerate(network):
        idx.insert(i, line.bounds)
    return idx


def get_nearest_segment(point, network, idx):
    nearest_lines = list(idx.nearest(point.bounds, 1))
    nearest = min(
        [
            (line, point.distance(line))
            for line in [network.iloc[i] for i in nearest_lines]
        ],
        key=lambda x: x[1],
    )[0]
    return nearest


def create_bbox(point, x_distance_meters, y_distance_meters):
    if not isinstance(point, Point):
        raise ValueError("Input must be a Shapely Point.")

    geoseries = gpd.GeoSeries([point], crs="EPSG:4326")
    point_mercator = geoseries.to_crs("EPSG:3857").iloc[0]

    minx = point_mercator.x - x_distance_meters / 2
    maxx = point_mercator.x + x_distance_meters / 2
    miny = point_mercator.y - y_distance_meters / 2
    maxy = point_mercator.y + y_distance_meters / 2

    bbox_geoseries = gpd.GeoSeries(
        [Point(coord) for coord in [(minx, miny), (maxx, maxy)]], crs="EPSG:3857"
    )
    transformed_coords = bbox_geoseries.to_crs("EPSG:4326").tolist()

    bbox = [
        transformed_coords[0].x,
        transformed_coords[0].y,
        transformed_coords[1].x,
        transformed_coords[1].y,
    ]

    return bbox


def get_osm_lines(bbox, network_type="all_private"):
    minx, miny, maxx, maxy = bbox
    graph = ox.graph_from_bbox(maxy, miny, minx, maxx, network_type=network_type)
    network = ox.utils_graph.graph_to_gdfs(graph, nodes=False)
    return network


def calculate_bearing(point1, point2):
    lon1, lat1 = math.radians(point1.x), math.radians(point1.y)
    lon2, lat2 = math.radians(point2.x), math.radians(point2.y)
    dlon = lon2 - lon1
    x = math.atan2(
        math.sin(dlon) * math.cos(lat2),
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(dlon),
    )
    bearing = (math.degrees(x) + 360) % 360
    return bearing


def align_compass_with_road(points, network):
    idx = create_spatial_index(network.geometry)
    for row_idx, point in points.iterrows():
        nearest_segment = get_nearest_segment(
            point.snapped_geometry, network.geometry, idx
        )
        segment_coords = nearest_segment.coords[:]
        segment_bearing = calculate_bearing(
            Point(segment_coords[0]), Point(segment_coords[1])
        )

        difference_0 = abs(segment_bearing - point.compass_angle)
        difference_180 = abs((segment_bearing + 180) % 360 - point.compass_angle)

        if difference_0 < difference_180:
            points.at[row_idx, "snapped_angle"] = segment_bearing
        else:
            points.at[row_idx, "snapped_angle"] = (segment_bearing + 180) % 360
    return points


def snap_to_road_network(gif, tolerance, network, realign_camera=True):
    points = gif[["image_url", "geometry"]].copy()
    points = points.to_crs(3857)

    if network is None:
        raise Exception(
            "Network is missing. Please supply road network or set use_osm to True"
        )
    if "LineString" not in network.geom_type.values:
        raise Exception(
            "Invalid geometry. Network geodataframe geometry must contain LineString geometries"
        )

    lines = network.to_crs(3857)

    bbox_series = points.bounds + [-tolerance, -tolerance, tolerance, tolerance]
    hits = bbox_series.apply(lambda row: list(lines.sindex.intersection(row)), axis=1)

    tmp = pd.DataFrame(
        {
            "pt_idx": np.repeat(hits.index, hits.apply(len)),
            "line_i": np.concatenate(hits.values),
        }
    )
    tmp = tmp.join(lines.reset_index(drop=True), on="line_i")
    tmp = tmp.join(points.geometry.rename("point"), on="pt_idx")
    tmp = gpd.GeoDataFrame(tmp, geometry="geometry", crs=points.crs)

    tmp["snap_dist"] = tmp.geometry.distance(gpd.GeoSeries(tmp.point))
    tmp = tmp.loc[tmp.snap_dist <= tolerance]
    tmp = tmp.sort_values(by=["snap_dist"])

    closest = tmp.groupby("pt_idx").first()
    closest = gpd.GeoDataFrame(closest, geometry="geometry")

    pos = closest.geometry.project(gpd.GeoSeries(closest.point))
    new_pts = closest.geometry.interpolate(pos)

    new_pts.crs = "EPSG:3857"
    new_pts = new_pts.to_crs(4326)
    gif["snapped_geometry"] = new_pts.geometry

    missing = gif[gif["snapped_geometry"].isnull()].image_url.tolist()
    if len(missing) > 0:
        warnings.warn(
            f"""
        Not all images were snapped. Non-snapped images will not be added 
        to the snapped image table. To snap all images, try increasing the threshold 
        or changing the road network. The following images could not be snapped 
        to a road network: {missing}
        """
        )

    if realign_camera:
        if "compass_angle" not in gif.columns:
            warnings.warn(
                f"realign_camera requires the compass_angle field. Cannot calculate snapped camera angle."
            )
        else:
            if "snapped_angle" not in gif.columns:
                gif["snapped_angle"] = np.nan
            gif = align_compass_with_road(gif, network)

    return gif
