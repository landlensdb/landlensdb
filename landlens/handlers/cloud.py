import pytz
import requests

from datetime import datetime, timezone
from geopandas import GeoDataFrame
from shapely.geometry import Point
from timezonefinder import TimezoneFinder

from landlens.geoclasses.geoimageframe import GeoImageFrame


class Mapillary:
    BASE_URL = "https://graph.mapillary.com"
    HEADERS_TEMPLATE = {"Authorization": "OAuth {}"}
    REQUIRED_FIELDS = ["id", "geometry"]
    FIELDS_LIST = [
        "id",
        "altitude",
        "atomic_scale",
        "camera_parameters",
        "camera_type",
        "captured_at",
        "compass_angle",
        "computed_altitude",
        "computed_compass_angle",
        "computed_geometry",
        "computed_rotation",
        "exif_orientation",
        "geometry",
        "height",
        "thumb_1024_url",
        "merge_cc",
        "mesh",
        "sequence",
        "sfm_cluster",
        "width",
        "detections",
    ]
    IMAGE_URL_KEYS = [
        "thumb_256_url",
        "thumb_1024_url",
        "thumb_2048_url",
        "thumb_original_url",
    ]
    LIMIT = 2000

    def __init__(self, mapillary_token):
        self.TOKEN = mapillary_token
        self.headers = self.HEADERS_TEMPLATE.copy()
        self.headers["Authorization"] = self.headers["Authorization"].format(self.TOKEN)

    def _validate_fields(self, fields):
        if (
            "id" not in fields
            or "geometry" not in fields
            or not any(image_field in fields for image_field in self.IMAGE_URL_KEYS)
        ):
            raise ValueError(
                "Fields must contain 'id', 'geometry', and one of "
                + str(self.IMAGE_URL_KEYS)
            )

    @staticmethod
    def _split_bbox(inner_bbox):
        x1, y1, x2, y2 = inner_bbox[:]
        xm = (x2 - x1) / 2
        ym = (y2 - y1) / 2

        q1 = [x1, y1, x1 + xm, y1 + ym]
        q2 = [x1 + xm, y1, x2, y1 + ym]
        q3 = [x1, y1 + ym, x1 + xm, y2]
        q4 = [x1 + xm, y1 + ym, x2, y2]

        return [q1, q2, q3, q4]

    def _json_to_gdf(self, json_data):
        for img in json_data:
            coords = img.get("geometry", {}).get("coordinates", [None, None])
            img["geometry"] = Point(coords)
            img["mly_id"] = img.pop("id")
            img["name"] = f"mly|{img['mly_id']}"

            if "computed_geometry" in img:
                coords = img.get("computed_geometry", {}).get(
                    "coordinates", [None, None]
                )
                img["computed_geometry"] = Point(coords)

            if "captured_at" in img:
                lat = img["geometry"].y
                lng = img["geometry"].x
                img["captured_at"] = self._process_timestamp(
                    img.get("captured_at"), lat, lng
                )

            for key in self.IMAGE_URL_KEYS:
                if key in img:
                    img["image_url"] = img.pop(key)
                    break

            for key in ["camera_parameters", "computed_rotation"]:
                if key in img and isinstance(img[key], list):
                    img[key] = ",".join(map(str, img[key]))

        gdf = GeoDataFrame(json_data, crs="EPSG:4326")
        gdf.set_geometry("geometry", inplace=True)
        return gdf

    def _recursive_fetch(self, bbox, fields, start_timestamp=None, end_timestamp=None):
        url = (
            f"{self.BASE_URL}/images?access_token={self.TOKEN}"
            f"&fields={','.join(fields)}&bbox={','.join(str(i) for i in bbox)}"
            f"&limit={self.LIMIT}"
        )

        if start_timestamp:
            url += f"&start_captured_at={start_timestamp}"
        if end_timestamp:
            url += f"&end_captured_at={end_timestamp}"

        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            raise Exception(
                f"There was an error connecting to the Mapillary API. Exception: {response.text}"
            )

        response_data = response.json().get("data")
        if len(response_data) == self.LIMIT:
            child_bboxes = self._split_bbox(bbox)
            data = []
            for child_bbox in child_bboxes:
                data.extend(
                    self._recursive_fetch(
                        child_bbox, fields, start_timestamp, end_timestamp
                    )
                )
            return data
        else:
            return response_data

    @staticmethod
    def _get_timestamp(date_string):
        if not date_string:
            return None

        tz = timezone.utc
        timestamp = (
            datetime.strptime(date_string, "%Y-%m-%d")
            .astimezone(tz)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        return timestamp

    @staticmethod
    def _process_timestamp(epoch_time_ms, lat, lng):
        if not epoch_time_ms:
            return None
        epoch_time = epoch_time_ms / 1000
        dt_utc = datetime.fromtimestamp(epoch_time, tz=timezone.utc)
        tf = TimezoneFinder()
        tz_name = tf.timezone_at(lat=lat, lng=lng)
        if tz_name:
            local_tz = pytz.timezone(tz_name)
            return dt_utc.astimezone(local_tz).isoformat()
        else:
            return dt_utc.isoformat()

    def fetch_within_bbox(
        self, initial_bbox, start_date=None, end_date=None, fields=None
    ):
        if fields is None:
            fields = self.FIELDS_LIST
        else:
            self._validate_fields(fields)
        start_timestamp = self._get_timestamp(start_date)
        end_timestamp = self._get_timestamp(end_date)
        images = self._recursive_fetch(
            initial_bbox, fields, start_timestamp, end_timestamp
        )
        data = self._json_to_gdf(images)
        return GeoImageFrame(data, geometry="geometry")

    def fetch_by_id(self, image_id, fields=None):
        if fields is None:
            fields = self.FIELDS_LIST
        else:
            self._validate_fields(fields)
        url = f"{self.BASE_URL}/{image_id}?fields={','.join(fields)}"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            raise Exception(
                f"There was an error connecting to the Mapillary API. Exception: {response.text}"
            )
        data = self._json_to_gdf([response.json()])
        return GeoImageFrame(data, geometry="geometry")

    def fetch_by_sequence(self, sequence_ids, fields=None):
        if fields is None:
            fields = self.FIELDS_LIST
        else:
            self._validate_fields(fields)
        url = f"{self.BASE_URL}/images?sequence_ids={','.join(sequence_ids)}&fields={','.join(fields)}"
        response = requests.get(url, headers=self.headers)
        if response.status_code != 200:
            raise Exception(
                f"There was an error connecting to the Mapillary API. Exception: {response.text}"
            )
        response_data = response.json().get("data")
        if len(response_data) == self.LIMIT:
            raise Exception(
                "Data count reached the Mapillary limit. Please provide a fewer sequence IDs."
            )

        data = self._json_to_gdf(response_data)
        return GeoImageFrame(data, geometry="geometry")
