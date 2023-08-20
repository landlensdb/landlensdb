import pytest
from shapely.geometry import Point
from landlens_db.geoclasses.geoimageframe import GeoImageFrame


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
