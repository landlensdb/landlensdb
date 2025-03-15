FROM jupyter/base-notebook:latest
LABEL maintainer="Iosefa Percival"
LABEL repo="https://github.com/landlensdb/landlensdb"

USER root

RUN apt-get update -y && apt-get install -y \
    postgresql postgresql-contrib postgis \
    gdal-bin libgdal-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN service postgresql start \
    && sudo -u postgres psql -c "CREATE DATABASE landlens;" \
    && sudo -u postgres psql -d landlens -c "CREATE EXTENSION postgis;" \
    && service postgresql stop

RUN pip install --no-cache-dir \
    landlensdb \
    jupyter-server-proxy

RUN mkdir -p /home/jovyan/examples
COPY /docs/examples /home/jovyan/examples
RUN mkdir -p /home/jovyan/example_data
COPY /docs/example_data /home/jovyan/example_data

ENV JUPYTER_ENABLE_LAB=yes

RUN chown -R ${NB_UID} /home/jovyan

USER ${NB_USER}
