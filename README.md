# landlensdb: Geospatial Image Handling and Management

[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/landlensdb/landlensdb/HEAD?urlpath=%2Fdoc%2Ftree%2Fexamples%2Fgetting-started.ipynb)
[![PyPI](https://img.shields.io/pypi/v/landlensdb.svg)](https://pypi.org/project/landlensdb/)
[![Docker Pulls](https://img.shields.io/docker/pulls/iosefa/landlensdb?logo=docker&label=pulls)](https://hub.docker.com/r/landlensdb/landlensdb)
[![Contributors](https://img.shields.io/github/contributors/landlensdb/landlensdb.svg?label=contributors)](https://github.com/landlensdb/landlensdb/graphs/contributors)
[![Downloads](https://pepy.tech/badge/landlensdb)](https://pepy.tech/project/landlensdb)
[![Tests](https://img.shields.io/github/actions/workflow/status/landlensdb/landlensdb/main.yml?branch=main)](https://github.com/landlensdb/landlensdb/actions/workflows/main.yml)


**Streamlined geospatial image handling and database management**

## Overview

landlensdb helps you manage geolocated images and integrate them with other spatial data sources. The library supports:
- Image downloading and storage
- EXIF/geotag extraction
- Road-network alignment
- PostgreSQL integration

This workflow is designed for geo-data scientists, map enthusiasts, and anyone needing to process large sets of georeferenced images.

## Features
- **GeoImageFrame Management**: Download, map, and convert geolocated images into a GeoDataFrame-like structure. 
- **Mapillary API Integration**: Fetch and analyze images with geospatial metadata.
- **EXIF Data Processing**: Extract geolocation, timestamps, and orientation from image metadata.
- **Database Operations**: Store image records in PostgreSQL; retrieve them by location or time.
- **Road Network Alignment**: Snap image captures to road networks for precise route mapping.

## Installation

Install the latest release from PyPI:

```
pip install landlensdb
```

### Dependencies

> [!IMPORTANT] 
> You **MUST** have both GDAL and PostgreSQL with PostGIS installed to use `landlensdb`.  
> - See [GDAL Docs](https://gdal.org/en/stable/) for instructions on installing GDAL.  
> - See [PostGIS](https://postgis.net/documentation/getting_started/) for installing PostGIS on top of PostgreSQL.

**Minimum Requirements**:

- **GDAL ≥ 3.5** (ensure command-line tools work, e.g., `gdalinfo --version`)
- **PostgreSQL ≥ 14**  
- **PostGIS ≥ 3.5** (the extension must be installed in your PostgreSQL database)  
- **Python ≥ 3.10**

## Quick Start

Below is a minimal example creating a GeoImageFrame:

```python
from landlensdb.geoclasses import GeoImageFrame
from shapely.geometry import Point

# Create a simple GeoImageFrame from scratch
geo_frame = GeoImageFrame(
	{
		"image_url": ["https://example.com/image1.jpg"],
		"name": ["SampleImage"],
		"geometry": [Point(-120.5, 35.2)]
	}
)

print(geo_frame.head())
```

For additional usage examples, see our documentation.


## Documentation

Full documentation (including tutorials and advanced usage) is available in this repository's docs/ folder.
You can build the docs locally by installing the optional [docs] extras:

```
pip install -e '.[docs]'
mkdocs serve
```

Then open http://127.0.0.1:8000/ in your browser.

## Developer Guides

Local Development
	1.	Clone this repository.
	2.	Install in editable mode with dev extras:
        ```
        pip install --upgrade pip
        pip install -e .[dev]
        ```
	3.	Make changes as needed and contribute via Pull Requests.

## Testing

We use pytest for testing. Tests requires the following test database. Create if does not exist:

```bash
createdb landlens_test && psql landlens_test -c "create extension postgis" 
```

Then, we can run the tests:

```bash
pytest tests
```

You can also run specific test files or functions, for example:

```
pytest tests/test_geoimageframe.py
```

## Code Formatting & Pre-commit

landlensdb uses Black for formatting. Once you’ve installed [dev] extras:

```
pre-commit install
pre-commit run --all-files
```

This enforces linting and formatting on each commit.

## Contributing

We welcome contributions! Please see CONTRIBUTING.md for guidelines on how to open issues, submit pull requests, and follow our code of conduct.

## License

This project is licensed under the MIT License. See LICENSE.md for details.