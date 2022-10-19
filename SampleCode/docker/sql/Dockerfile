FROM postgis/postgis:14-3.1

RUN apt-get update \
    && apt-get -y install --no-install-recommends \
    unzip \
    curl \
    wget \
    postgis \
    osm2pgsql

WORKDIR /work
