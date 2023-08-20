Getting Started
===============

Installation
------------
To install ``landlens_db``, simply use pip:

.. code-block:: bash

   pip install landlens_db

Loading Images
--------------
``landlens_db`` enables loading images from both local directories and the Mapillary API.

**Local Images**:

.. code-block:: python

   from landlens_db.handlers.image import Local

   local_images = Local.load_images(YOUR_LOCAL_IMAGES_DIRECTORY)

**Mapillary Images**:

.. code-block:: python

   from landlens_db.handlers.cloud import Mapillary

   importer = Mapillary(YOUR_MLY_TOKEN)
   images = importer.fetch_within_bbox(YOUR_BBOX, start_date=START_DATE, end_date=END_DATE)

Processing and Visualization
----------------------------
Processing includes snapping images to road networks:

.. code-block:: python

   from landlens_db.process import snap

   snap.snap_to_road_network(image, THRESHOLD, network)

Visualize `GeoImageFrames` using Folium:

.. code-block:: python

   image.map(additional_properties=['altitude', 'camera_type'])

Storing Images
--------------
Store `GeoImageFrame` data in different formats or in a PostGIS enabled PostgreSQL database.

**Saving to Geopackage**:

.. code-block:: python

   image.to_file('image1.gpkg')

**Saving to PostgreSQL Database**:

.. code-block:: python

   from landlens_db.handlers.db import Postgres

   db_con = Postgres(DATABASE_URL)
   local_images.to_postgis(DB_TABLE, db_con.engine)

Additional Features
-------------------
Explore further functionalities such as querying existing tables, loading data from arbitrary sources, updating existing tables, and more in the API documentation.

With ``landlens_db``, you have all the necessary tools to manage, analyze, and visualize geolocated images effortlessly.
