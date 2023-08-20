from landlens_db.geoclasses.geoimageframe import (
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


def test_to_dict_records(sample_geoimageframe):
    records = sample_geoimageframe.to_dict_records()
    assert isinstance(records, list), "Should return a list"
