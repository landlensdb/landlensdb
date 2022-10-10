# SU_GCPsystem

This system aims to create ground reference data from street-level images and very high-resolution (VHR) images.

## System descriptions

- It builds on GCP.
- Street-level photos are obtained from Mapillary via Mapillary API (v4) and are stored in PostgreSQL.
- This DB helps avoid over-access to the Mapillary server.
- It has a mapping system in a _.ipynb_ notebook by querying a user-defined spatial extent.
- It has a photo visualization system in a _.ipynb_ notebook by querying imageid(s) and/or sequenceid.
- It may have (this might work in the Colaboratory environment) a deep-learning classification model to predict land cover from street-level photos
- Street-level photos are divided into two sides (left/right) to predict Land cover on each side.
- It has an annotation system for polygons from street-level photos.
- Polygons will be made by a segmentation model (**[RSGISLib](http://rsgislib.org/rsgislib_segmentation.html)** or deep learning model) from the VHR image (Planet)
- A polygon will be annotated by predicted LC from nearby street-level photos.
- The algorithm should be developed.

## NOTE

- No need to run this system for 24 hours!
- Turn off the system (including PostgreSQL!) as much as possible after your development is done every day to save GCP costs.
- All requests will be found on Github issues.
- Slack is a supplementary tool.
- A test site is Muroran city, Hokkaido, Japan.
- Postgresql DB will be also used for sakura mapping.
- Some functions are already developed in Windows. Migration is required.
- The development flow should follow the [Github flow](https://docs.github.com/en/get-started/quickstart/github-flow)
