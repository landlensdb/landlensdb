import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from landlensdb.geoclasses.geoimageframe import (
    GeoImageFrame,
    _generate_arrow_icon,
    _generate_arrow_svg,
)


def test_generate_arrow_icon():
    icon = _generate_arrow_icon(90)
    assert icon is not None, "Icon should not be None"


def test_generate_arrow_svg():
    svg_str = _generate_arrow_svg(45)
    assert svg_str is not None, "SVG string should not be None"


def test_geoimageframe_initialization(sample_data):
    gdf = GeoImageFrame(sample_data)
    assert gdf is not None, "GeoImageFrame should not be None"


def test_verify_structure(sample_geoimageframe):
    # Testing if structure is verified without error
    sample_geoimageframe._verify_structure()


def test_incomplete_projection_uses_base_frame(sample_geoimageframe):
    tabular_projection = sample_geoimageframe[["name"]]
    geospatial_projection = sample_geoimageframe[["name", "geometry"]]

    assert type(tabular_projection) is pd.DataFrame
    assert type(geospatial_projection) is gpd.GeoDataFrame


def test_complete_operations_preserve_geoimageframe(sample_geoimageframe):
    assert type(sample_geoimageframe.copy()) is GeoImageFrame
    assert type(sample_geoimageframe.head()) is GeoImageFrame


def test_wide_geoimageframe_repr(sample_geoimageframe):
    wide_frame = sample_geoimageframe.assign(
        **{f"extra_{index}": index for index in range(20)}
    )

    assert "image_url" in repr(wide_frame)


def test_explicit_incomplete_construction_still_fails():
    with pytest.raises(ValueError, match="required column 'image_url'"):
        GeoImageFrame({"name": ["Sample"], "geometry": [Point(0, 0)]})


def test_to_dict_records(sample_geoimageframe):
    records = sample_geoimageframe.to_dict_records()
    assert isinstance(records, list), "Should return a list"
