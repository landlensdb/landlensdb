# StreetValidator

This system aims to create ground reference data from street-level images and very high-resolution (VHR) images.


[notes]
* it shouldnt have to depend on postgres/postgis. users should be able to just load and save the images in whatever format they want.
* the library should just give the core functions as the main goal.
* read from a postgres table into a geodataframe.

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

## Installation and Use

### Installation Instructions:

1. create/activate python virtual environment (e.g. `python3 -m venv venv && source venv/bin/activate`)
2. install dependencies: `pip install -r requirements.txt`

Note, to use these tools, you will need to have authenticated your device with GCP. This requires that:

1. Your machine IP is registered to access the database.
2. Your google account is authorized to access GCP resources for this project. 
3. You have authenticated your device using `gcloud auth application-default login`
4. You have a valid service account key with appropriate permissions.

### Use:
See `notebooks` and `scripts` for examples on how to use the various module functions.

## Development

### Formatting
A pre-commit hook exists to format all code on commits. Code formatting 
can be run at any time using the `black` command. For example, `black src` will
format all code in the `src` module directory. `black` must be installed
first before use. Please run `pip install black` to install the package.

### Documentation
This project uses Sphinx with the Read the Docs theme to document functions. To update the documentation, first
install `sphinx` and `sphinx_rtd_theme` using `pip install sphinx sphinx_rtd_theme`. Then, 
to generate html run `make html` or to generate pdf, run `make latexpdf`. If changes are made, 
rebuild the build files by first running `make clean` and then `make html`.
