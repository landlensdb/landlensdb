import datetime
import json
import os
import psycopg2
import requests

from geopandas import read_postgis
from google.cloud import storage
from shapely.geometry import Point
from sqlalchemy import create_engine
from tqdm import tqdm


class MapillaryImage:
    """
    Mapillary Image controller.

    Contains functions to read from the database and output in various formats.
    """

    def __init__(self):
        self.DATABASE_URL = os.environ.get(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/mapillary"
        )

    def select_within_bbox(self, bbox):
        """
        Selects rows that lie completely within the supplied bounding box.

        Parameters
        ----------
        bbox : list
          list of lat long coordinates. Specify in this order: left, bottom, right, top
          (or minLon, minLat, maxLon, maxLat).

        Returns
        -------
        GeoDataFrame: Geopandas dataframe of rows that lie within the bounding box
        """
        minx, miny, maxx, maxy = bbox
        con = create_engine(self.DATABASE_URL)
        sql = f"""
            SELECT * FROM mly_images WHERE geometry &&  ST_MakeEnvelope({minx}, {miny}, {maxx}, {maxy}, 4326);
            """
        df = read_postgis(sql, con, "geometry")
        return df

    def select_by_image_id(self, image_id):
        """
        Selects row where id equals the supplied image id.

        Parameters
        ----------
        image_id : int
          image id to query

        Returns
        -------
        GeoDataFrame: Geopandas dataframe
        """

        con = create_engine(self.DATABASE_URL)
        sql = f"""
            SELECT * FROM mly_images WHERE id = {image_id};
            """
        df = read_postgis(sql, con, "geometry")
        return df

    def select_by_sequence_id(self, sequence_id):
        """
        Selects rows where seq equals the supplied sequence id.

        Parameters
        ----------
        sequence_id : string
          sequence id to query

        Returns
        -------
        GeoDataFrame: Geopandas dataframe
        """

        con = create_engine(self.DATABASE_URL)
        sql = f"""
            SELECT * FROM mly_images WHERE seq = '{sequence_id}';
            """
        df = read_postgis(sql, con, "geometry")
        return df


class MapillaryImport:
    """
    Mapillary image import class.

    Contains functions to import data from mapillary servers to self-managed storage blobs and databases.
    """

    def __init__(self):
        self.DATABASE_URL = os.environ.get(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/mapillary"
        )
        self.TOKEN = os.environ.get("MAPILLARY_TOKEN", "")
        self.BUCKET_NAME = os.environ.get("BUCKET_NAME", "")

    def _get_image_ids(self):
        """
        Gets a list of all mapillary image IDs from the database.

        Returns:
        list: list of mapillary image IDs.
        """
        conn = psycopg2.connect(self.DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT id FROM mly_images")
        rows = cur.fetchall()
        images = [row[0] for row in rows]
        cur.close()
        conn.close()

        return images

    @staticmethod
    def _split_bbox(inner_bbox):
        """
        splits bounding box into quadrants

        | q1 | q2 |
        | -- | -- |
        | q3 | q4 |

        Parameters
        ----------
        inner_bbox : list
          list of coordinates. Specify in this order: left, bottom, right, top
          (or minLon, minLat, maxLon, maxLat).

        Returns
        -------
            list: list of length 4. Each element is a list of coordinates that represent a bbox.
        """
        x1, y1, x2, y2 = inner_bbox[:]
        xm = (x2 - x1) / 2
        ym = (y2 - y1) / 2

        q1 = [x1, y1, x1 + xm, y1 + ym]
        q2 = [x1 + xm, y1, x2, y1 + ym]
        q3 = [x1, y1 + ym, x1 + xm, y2]
        q4 = [x1 + xm, y1 + ym, x2, y2]

        return [q1, q2, q3, q4]

    def import_images_by_bbox(self, initial_bbox, start_date, end_date, export_path):
        """
        Inserts new image records to the database and saves a copy of the image one sequence at a time.

        Parameters
        ----------
        initial_bbox : list
          list of coordinates that encompass the region of study. Specify in this order: left, bottom, right, top
          (or minLon, minLat, maxLon, maxLat).
        start_date: Character
          starting date (YYYY-MM-DD)
        end_date: Character
          ending date (YYYY-MM-DD)
        export_path: Character
          path to save downloaded images on GCP storage bucket.

        Returns
        -------
        void
        """
        headers = {"Authorization": "OAuth {}".format(self.TOKEN)}
        existing_images = self._get_image_ids()

        fields_list = [
            "id",
            "sequence",
            "altitude",
            "computed_altitude",
            "camera_type",
            "camera_parameters",
            "captured_at",
            "compass_angle",
            "computed_compass_angle",
            "exif_orientation",
            "merge_cc",
            "mesh",
            "sfm_cluster",
            "detections",
            "thumb_1024_url",
            "computed_geometry",
            "geometry",
        ]
        fields = ",".join(fields_list)

        # todo: check that time zones dont matter. Because we arent concerned with times,
        #  it probably is never necessary to look at timezones.
        # tz = pytz.timezone('Asia/Tokyo')
        tz = datetime.timezone.utc
        start_timestamp = (
            datetime.datetime.strptime(start_date, "%Y-%m-%d")
            .astimezone(tz)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        end_timestamp = (
            datetime.datetime.strptime(end_date, "%Y-%m-%d")
            .astimezone(tz)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

        base_url = "https://graph.mapillary.com/images"

        bbox_list = list([initial_bbox])
        images = []

        # use a double ended queue (deque) and add to queue when necessary and remove when either box too large or complete
        print("Fetching data from Mapillary ...")
        while len(bbox_list) > 0:
            current_bbox = bbox_list[0]
            bbox_string = ",".join(str(i) for i in current_bbox)
            url = (
                f"{base_url}?access_token={self.TOKEN}&start_captured_at={start_timestamp}"
                f"&end_captured_at={end_timestamp}&fields={fields}&bbox={bbox_string}"
                f"&limit=2000"
            )

            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                raise Exception(
                    f"There was an error connecting to the Mapillary API. Exception: {response.text}"
                )

            response_data = response.json().get("data")
            response_count = len(response_data)

            if response_count == 2000:
                bbox_children = self._split_bbox(current_bbox)
                bbox_list.pop(0)
                for bbox_child in bbox_children:
                    bbox_list.append(bbox_child)
            else:
                images += response_data
                bbox_list.pop(0)
        # todo: this should print the number of images that will be imported.
        print(f"fetched a total of {len(images)} images")

        print("Beginning import")
        # todo: loop through images that are not in existing images
        for image in tqdm(images):
            if int(image["id"]) not in existing_images:
                image_id = image.get("id")
                seq = image.get("sequence")
                altitude = image.get("altitude")
                computed_altitude = image.get("computed_altitude")
                camera_type = image.get("camera_type")
                camera_parameters = (
                    json.dumps(image.get("camera_parameters"))
                    if image.get("camera_parameters")
                    else None
                )
                captured_at = datetime.datetime.fromtimestamp(
                    image.get("captured_at") / 1000, datetime.timezone.utc
                )
                compass_angle = image.get("compass_angle")
                computed_compass_angle = image.get("computed_compass_angle")
                exif_orientation = image.get("exif_orientation")
                merge_cc = int(image.get("merge_cc"))
                mesh = json.dumps(image.get("mesh")) if image.get("mesh") else None
                sfm_cluster = (
                    json.dumps(image.get("sfm_cluster"))
                    if image.get("sfm_cluster")
                    else None
                )
                detections = (
                    json.dumps(image.get("detections"))
                    if image.get("detections")
                    else None
                )
                computed_geometry = (
                    "SRID=4326;"
                    + Point(image.get("computed_geometry").get("coordinates")).wkt
                )
                geometry = (
                    "SRID=4326;" + Point(image.get("geometry").get("coordinates")).wkt
                )

                image_data = requests.get(image["thumb_1024_url"], stream=True).content
                image_path = "{}/{}/image_{}.jpg".format(export_path, seq, image_id)

                storage_client = storage.Client()
                bucket = storage_client.bucket(self.BUCKET_NAME)
                blob = bucket.blob(image_path)
                blob.upload_from_string(image_data)
                image_url = f"https://storage.cloud.google.com/sudb_images/{image_path}"

                conn = psycopg2.connect(self.DATABASE_URL)
                cur = conn.cursor()

                conn.autocommit = True
                cur.execute(
                    """
                    INSERT INTO mly_images (
                        id, seq, altitude, computed_altitude,
                        camera_parameters, camera_type, captured_at, compass_angle,
                        computed_compass_angle, exif_orientation,
                        merge_cc, mesh, sfm_cluster, detections,
                        image_url, computed_geometry, geometry) VALUES
                      (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
                    """,
                    [
                        image_id,
                        seq,
                        altitude,
                        computed_altitude,
                        camera_parameters,
                        camera_type,
                        captured_at,
                        compass_angle,
                        computed_compass_angle,
                        exif_orientation,
                        merge_cc,
                        mesh,
                        sfm_cluster,
                        detections,
                        image_url,
                        computed_geometry,
                        geometry,
                    ],
                )
                cur.close()
                conn.close()

        print(f"Successfully imported {len(images)} records into the database.")
