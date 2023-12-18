import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="landlens_db",
    version="0.0.1",
    author="Joseph Emile Honour Percival",
    author_email="ipercival@gmail.com",
    description="Geospatial image handling and management",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/naruT/SU_GCPsystem",
    project_urls={
        "Bug Tracker": "https://github.com/naruT/SU_GCPsystem",
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        "geoalchemy2~=0.14.1",
        "geopandas~=0.12.2",
        "numpy~=1.24.1",
        "osmnx~=1.3.0",
        "pandas~=1.5.3",
        "psycopg2~=2.9.9",
        "shapely~=2.0.0",
        "requests~=2.31.0",
        "SQLAlchemy==2.0.23",
        "folium~=0.14.0",
        "Rtree~=1.0.1",
        "pytz~=2022.7.1",
        "timezonefinder~=6.2.0",
        "Pillow~=9.4.0",
        "tqdm~=4.64.1",
    ],
    packages=setuptools.find_packages(),
    python_requires=">=3.9",
)
