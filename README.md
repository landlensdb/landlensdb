# landlens_db: Geospatial Image Handling Library

## Introduction

`landlens_db` is a Python library designed to manage and process geolocated images. It facilitates operations such
as downloading, mapping, saving, fetching images, aligning with road networks, and managing 
PostgreSQL database operations.

## Features

- **GeoImageFrame Management**: Download, map, convert geolocated images.
- **Mapillary API Integration**: Fetch image data based on different criteria.
- **EXIF Data Processing**: Extract geotagging information from local images.
- **PostgreSQL Database Operations**: Handle image-related database operations.
- **Road Network Alignment**: Align images with road networks.

## Requirements

- Python 3.13.2 or later
- pip (latest version)
- virtualenv or venv module

For detailed version requirements of dependencies, see `requirements.txt`.

## Installation

### Quick Install

Install the package using pip:

```bash
pip install landlens_db
```

### Development Setup (Python 3.13)

For development or if you're using Python 3.13, follow these steps:

1. Create and activate a virtual environment:
   ```bash
   python3.13 -m venv venv
   source venv/bin/activate  # On Unix/macOS
   # or
   .\venv\Scripts\activate  # On Windows
   ```

2. Install core dependencies:
   ```bash
   pip install --upgrade pip
   pip install setuptools==69.2.0
   pip install -r requirements.txt
   ```

For detailed setup instructions and troubleshooting, see `ai/docs/python313_setup_guide.md`.

## Tutorial

There is a Jupyter notebook tutorial that showcases some simple commands and usage of `landlens_db`. To run this tutorial, you
must install `dotenv~==1.0.0` and `jupyter`.

## Usage

Example to create a `GeoImageFrame`:

```python
from landlens_db.geoclasses import GeoImageFrame
from shapely.geometry import Point

geo_frame = GeoImageFrame({'image_url': ['http://example.com/image.jpg'], 'name': ['Sample'], 'geometry': [Point(0, 0)]})
```

For more detailed examples and full API documentation, refer to the [official documentation](link-to-documentation).

## Testing

This project uses [Pytest](https://pytest.org) for running tests. All tests are located in the `test` directory.
To run tests, make sure you have Pytest installed, and then execute the following command:

```bash
pytest tests
```

## Code Formatting

This repository uses [Black](https://github.com/psf/black) for code formatting. To contribute, make sure to format your code with Black 
(version 22.10.0) targeting Python 3.9:

```bash
pre-commit run --all-files
```

You can set up pre-commit hooks to automate this process:

```bash
pre-commit install
```

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct, and the process for 
submitting pull requests.

## Documentation

This project uses Sphinx and the Read the Docs theme for documentation. Contributors are encouraged to write 
comprehensive and clear documentation for any new code. For guidelines on writing and building documentation,
please refer to the [CONTRIBUTING.md](CONTRIBUTING.md) file.

## Compatibility Notes

- Python 3.13 support requires specific package versions (see `requirements.txt`)
- Some dependencies may need to be installed in a specific order
- Virtual environment usage is strongly recommended
- See `ai/docs/python313_setup_guide.md` for detailed compatibility information

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.
```