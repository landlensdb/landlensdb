import warnings

import geopandas as gpd
import numpy as np
import os
import osmnx as ox
import pandas as pd

from google.cloud import storage
from shapely.geometry import box
from .controller import MapillaryImport


class DataUtils:
    def __init__(self, data):
        self.data = data
        self.DATABASE_URL = os.environ.get(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/mapillary"
        )

    def _image_paths(self):
        image_urls = self.data["image_url"].to_list()
        image_paths = [image_url.split(".com/")[1] for image_url in image_urls]
        return image_paths

    def _snap_to_osm(self, row):
        """
        Parameters
        ----------
        row: int
            row index of image to snap to osm road.

        Returns
        -------
            void
        """
        pass

    @staticmethod
    def _get_osm_lines(bbox, network_type):
        """
        Get OSM lines from a bounding box.

        Parameters
        ----------
        bbox : tuple
            A tuple of the form (minx, miny, maxx, maxy)
        network_type : string
            The type of network to download.
            One of 'drive', 'drive_service', 'walk', 'bike', 'all', 'all_private', or 'none'.
            See https://github.com/gboeing/osmnx/blob/master/osmnx/core.py for more details.

        Returns
        -------
        network : GeoDataFrame
            A GeoDataFrame of the OSM lines.
        """
        minx, miny, maxx, maxy = bbox
        graph = ox.graph_from_bbox(maxy, miny, minx, maxx, network_type=network_type)
        network = ox.utils_graph.graph_to_gdfs(graph, nodes=False)
        return network

    def write_image_list(self, file_name):
        """
        Creates a txt file with download links to images on GCP. This will allow for fast download of many files.

        Parameters
        ----------
        file_name: str
          path to file to write list of images urls to. Must have extension .txt.

        Returns
        -------
        void
        """

        image_paths = self._image_paths()
        image_urls = ["gs://" + image_path for image_path in image_paths]
        with open(file_name, "w") as f:
            for image_url in image_urls:
                f.write(f"{image_url}\n")

    def download_gcp_image(self, image_id, download_dir):
        """
        Downloads image by image id. Very slow.

        Parameters
        ----------
        image_id: int
            id of image to download
        download_dir: str
            path to save downloaded image.

        Returns
        -------
            void
        """
        image_url = self.data.loc[self.data["id"] == image_id]["image_url"].values[0]
        image_path = image_url.split(".com/")[1]

        bucket_name = image_path.split("/")[0]
        rel_path = "/".join(image_path.split("/")[1:])
        image_name = image_path.split("/")[-1]
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(bucket_name)
        blob = bucket.blob(f"{rel_path}")
        filename = f"{download_dir}/{image_name}"
        blob.download_to_filename(filename)

    def snap_to_road_network(
        self,
        tolerance,
        subset=None,
        use_osm=True,
        network_type="all_private",
        update_db=True,
        update_conflicting=False,
        network=None,
    ):
        """
        If not using OSM, the supplied dataframe must contain a geometry column
        """
        if subset is not None:
            points = subset[["id", "geometry"]]
        else:
            points = self.data[["id", "geometry"]]
        points = points.to_crs(3857)
        minx, miny, maxx, maxy = points.geometry.total_bounds

        bbox_geom = box(
            minx - tolerance, miny - tolerance, maxx + tolerance, maxy + tolerance
        )
        bbox = gpd.GeoDataFrame(index=[0], crs="epsg:3857", geometry=[bbox_geom])
        bbox = bbox.to_crs(4326)

        if use_osm:
            try:
                lines = self._get_osm_lines(bbox.geometry.total_bounds, network_type)
            except ValueError as e:
                raise Exception(f"Could not fetch osm network: {e}")
        else:
            if network is None:
                raise Exception(
                    "Network is missing. Please supply road network or set use_osm to True"
                )
            lines = network
            if "LineString" not in lines.geom_type.values:
                raise Exception(
                    "Invalid geometry. Network geodataframe geometry must contain LineString geometries"
                )

        lines = lines.to_crs(3857)

        bbox_series = points.bounds + [-tolerance, -tolerance, tolerance, tolerance]
        hits = bbox_series.apply(
            lambda row: list(lines.sindex.intersection(row)), axis=1
        )

        tmp = pd.DataFrame(
            {
                "pt_idx": np.repeat(hits.index, hits.apply(len)),
                "line_i": np.concatenate(hits.values),
            }
        )
        tmp = tmp.join(lines.reset_index(drop=True), on="line_i")
        tmp = tmp.join(points.geometry.rename("point"), on="pt_idx")
        tmp = gpd.GeoDataFrame(tmp, geometry="geometry", crs=points.crs)

        tmp["snap_dist"] = tmp.geometry.distance(gpd.GeoSeries(tmp.point))
        tmp = tmp.loc[tmp.snap_dist <= tolerance]
        tmp = tmp.sort_values(by=["snap_dist"])

        closest = tmp.groupby("pt_idx").first()
        closest = gpd.GeoDataFrame(closest, geometry="geometry")

        pos = closest.geometry.project(gpd.GeoSeries(closest.point))
        new_pts = closest.geometry.interpolate(pos)
        new_pts.crs = "EPSG:3857"
        new_pts = new_pts.to_crs(4326)
        points = points.to_crs(4326)
        points["use_osm"] = use_osm
        points["geometry"] = new_pts
        points.rename(columns={"id": "image_id"}, inplace=True)

        missing = points[points["geometry"].isnull()].image_id.tolist()
        if len(missing) > 0:
            warnings.warn(
                f"""
            Not all images were snapped. Non-snapped images will not be added 
            to the snapped image table. To snap all images, try increasing the threshold 
            or changing the road network. The following images could not be snapped 
            to a road network: {missing}
            """
            )

        if update_db:
            importer = MapillaryImport()
            importer.import_snapped_images(
                points, use_osm, update_conflicting=update_conflicting
            )

        return points
