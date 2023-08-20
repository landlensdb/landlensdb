Introduction
============

landlens_db: Geospatial Image Handling Library
----------------------------------------------
``landlens_db`` is a versatile Python library built to handle geolocated images with ease. Whether dealing with images acquired from local directories or fetching them from the Mapillary API, the library offers streamlined functions and classes.

With tools to align images with road networks, manipulate their formats, and manage PostgreSQL database operations, ``landlens_db`` stands as a robust platform for managing and processing geospatial data.

Modules
-------

- **geoclasses**: Classes for managing geolocated images, such as `GeoImageFrame`.
- **handlers**: Various handlers for image sources like Mapillary's API and local EXIF data processing.
- **snap**: Functions to snap and align geolocated images with road networks.

Key Features
------------

1. **GeoImageFrame Management**: Enables users to download, map, and convert geolocated images using GeoDataFrame extensions.
2. **Mapillary API Integration**: Fetch and manipulate image data through Mapillary's API.
3. **EXIF Data Processing**: Extract geotagging information from local images.
4. **PostgreSQL Database Operations**: Comprehensive tools for PostgreSQL image-related operations.
5. **Road Network Alignment**: Accurately align geolocated images with road networks.

Getting Started
---------------
To jumpstart your experience with ``landlens_db``, install the package using pip:

.. code-block:: bash

   pip install landlens_db

Below is a quick example of creating a `GeoImageFrame`:

.. code-block:: python

   from landlens_db.geoclasses import GeoImageFrame
   from shapely.geometry import Point

   geo_frame = GeoImageFrame({'image_url': ['http://example.com/image.jpg'], 'name': ['Sample'], 'geometry': [Point(0, 0)]})

Explore detailed examples and full API documentation in the respective modules. With ``landlens_db``, spatial analysis and visualization become more productive and intuitive.
