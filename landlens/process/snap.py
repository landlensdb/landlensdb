import warnings

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
from shapely import Point


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


def snap_to_road_network(gif, tolerance, network):
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

    return gif
