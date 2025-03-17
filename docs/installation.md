# Installation

## Prerequisites

landlensdb requires **PostgreSQL** (≥ 14) and **PostGIS** (≥ 3.5). You should also have **Python ≥ 3.10**. PostGIS is an extension that adds spatial types to PostgreSQL, enabling geospatial queries and storage.

### PostgreSQL and PostGIS

1. **Using conda (recommended)**

```bash
conda create -n landlensdb_env -c conda-forge postgresql postgis
conda activate landlensdb_env
```

Remember to initialize and start the PostgreSQL server before using `landlensdb`. Once your database is up, enable PostGIS in your database:

```sql
CREATE EXTENSION postgis;
```

2. **Using system packages** (example: Ubuntu/Debian)

```bash
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib postgis
```

Then enable PostGIS in PostgreSQL as shown above.

For more details on setup and configuration:
- [PostgreSQL docs](https://www.postgresql.org/docs/)
- [PostGIS docs](https://postgis.net/documentation/)

## Installing landlensdb

### From PyPI

```bash
pip install landlensdb
```

### From GitHub

Install the latest development version:

```bash
pip install git+https://github.com/landlensdb/landlensdb
```

## Docker

A Docker environment with `landlensdb` can be provided as well. Adjust the Docker image and tag as needed:

```bash
docker run -it --rm -p 8888:8888 iosefa/landlensdb:latest
```