import pytest
import geopandas as gpd

from shapely.geometry import Point
from landlensdb.geoclasses.geoimageframe import GeoImageFrame


@pytest.fixture
def sample_data():
    data = {
        "image_url": ["http://example.com/image.jpg"],
        "name": ["Sample"],
        "geometry": [Point(0, 0)],
    }
    return data


@pytest.fixture
def sample_geoimageframe(sample_data):
    return GeoImageFrame(sample_data)


@pytest.fixture
def images():
    images_gdf = gpd.read_file('test_data/mapillary/images.gpkg')
    return GeoImageFrame(images_gdf)
