"""Tests for OSM snap compass realignment."""

import geopandas as gpd
from shapely.geometry import LineString, Point

from landlensdb.process.snap import (
    _bearing_along_line_at_point,
    _calculate_bearing,
    _circular_angle_diff,
    align_compass_with_road,
)


def test_circular_angle_diff_wraps_around_zero():
    assert _circular_angle_diff(350, 10) == 20.0
    assert _circular_angle_diff(10, 350) == 20.0
    assert _circular_angle_diff(0, 180) == 180.0


def test_bearing_uses_local_edge_not_way_start():
    """Long polylines must use the edge nearest the snap point."""
    coords = [(0.0, 0.0), (0.01, 0.0), (0.01, 0.01)]
    line = LineString(coords)
    snap_pt = Point(0.01, 0.005)

    old_style = _calculate_bearing(Point(coords[0]), Point(coords[1]))
    local = _bearing_along_line_at_point(line, snap_pt)

    assert abs(old_style - 90.0) < 1.0
    assert abs(local - 0.0) < 1.0 or abs(local - 360.0) < 1.0


def test_align_compass_picks_closer_road_direction():
    line = LineString([(0.0, 0.0), (0.01, 0.0), (0.01, 0.01)])
    network = gpd.GeoDataFrame({"geometry": [line]}, crs="EPSG:4326")
    snap_pt = Point(0.01, 0.005)

    northish = gpd.GeoDataFrame(
        {
            "compass_angle": [10.0],
            "snapped_geometry": [snap_pt],
            "snapped_angle": [None],
            "geometry": [Point(0.0101, 0.005)],
        },
        crs="EPSG:4326",
    )
    southish = northish.copy()
    southish["compass_angle"] = 190.0

    out_n = align_compass_with_road(northish, network)
    out_s = align_compass_with_road(southish, network)

    assert abs(out_n.iloc[0].snapped_angle - 0.0) < 1.0
    assert abs(out_s.iloc[0].snapped_angle - 180.0) < 1.0
