# landlensdb Documentation

[![Contributors](https://img.shields.io/github/contributors/landlensdb/landlensdb.svg?label=contributors)](https://github.com/landlensdb/landlensdb/graphs/contributors)

<p align="center">
  <img src="images/landlensdb.png" alt="landlensdb" width="200">
</p>

**Geospatial image handling and management with Python and PostgreSQL**

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

## Examples
The examples below are Jupyter notebooks and can help you get started!

- [Getting Started: DTM and CHM](examples/getting-started.ipynb)
- [Calculating Forest Metrics](examples/calculate-forest-metrics.ipynb)
- [Working with Large Point Clouds](examples/working-with-large-point-clouds.ipynb)

To install Jupyter, you can use conda or pip, with either:

```python
conda install jupyter
```

or

```python
pip install jupyter
```

## Attribution