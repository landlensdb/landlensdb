import pytz
import requests
import warnings
import pyogrio

from datetime import datetime, timezone
from geopandas import GeoDataFrame
from shapely.geometry import Point
from timezonefinder import TimezoneFinder

from landlens_db.geoclasses.geoimageframe import GeoImageFrame


class Mapillary:
    """
    Class to interact with Mapillary's API to fetch image data.

    Args:
        mapillary_token (str): The authentication token for Mapillary.

    Examples:
        >>> mapillary = Mapillary("YOUR_TOKEN_HERE")
        >>> images = mapillary.fetch_within_bbox([12.34, 56.78, 90.12, 34.56])
    """

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
        """
        Initialize a Mapillary object.

        Args:
            mapillary_token (str): The authentication token for Mapillary.
        """
        self.TOKEN = mapillary_token
        self.headers = self.HEADERS_TEMPLATE.copy()
        self.headers["Authorization"] = self.headers["Authorization"].format(self.TOKEN)

    def _validate_fields(self, fields):
        """
        Validates the fields for fetching data.

        Args:
            fields (list): The fields to be validated.

        Raises:
            ValueError: If the required fields are missing.
        """
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
        """
        Splits a bounding box into four quarters.

        Args:
            inner_bbox (list): A list representing the bounding box to split.

        Returns:
            list: A list of four bounding boxes, each representing a quarter.
        """
        x1, y1, x2, y2 = inner_bbox[:]
        xm = (x2 - x1) / 2
        ym = (y2 - y1) / 2

        q1 = [x1, y1, x1 + xm, y1 + ym]
        q2 = [x1 + xm, y1, x2, y1 + ym]
        q3 = [x1, y1 + ym, x1 + xm, y2]
        q4 = [x1 + xm, y1 + ym, x2, y2]

        return [q1, q2, q3, q4]

    def _json_to_gdf(self, json_data):
        """
        Converts JSON data from Mapillary to a GeoDataFrame.

        Args:
            json_data (list): A list of JSON data from Mapillary.

        Returns:
            GeoDataFrame: A GeoDataFrame containing the image data.
        """
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

    def _recursive_fetch(
        self,
        bbox,
        fields,
        start_timestamp=None,
        end_timestamp=None,
        current_depth=0,
        max_recursion_depth=None,
    ):
        """
        Recursively fetches images within a bounding box, considering timestamps.

        Args:
            bbox (list): The bounding box to fetch images from.
            fields (list): The fields to include in the response.
            start_timestamp (str, optional): The starting timestamp for filtering images.
            end_timestamp (str, optional): The ending timestamp for filtering images.
            current_depth (int, optional): Current depth of recursion.
            max_recursion_depth (int, optional): Maximum depth of recursion.

        Returns:
            list: A list of image data.

        Raises:
            Exception: If the connection to Mapillary API fails.
        """
        if max_recursion_depth is not None and current_depth > max_recursion_depth:
            warnings.warn(
                "Warning: Max recursion depth reached. Consider splitting requests across smaller multiple date ranges."
            )
            return []

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
                        child_bbox,
                        fields,
                        start_timestamp,
                        end_timestamp,
                        current_depth=current_depth + 1,
                        max_recursion_depth=max_recursion_depth,
                    )
                )
            return data
        else:
            return response_data

    @staticmethod
    def _get_timestamp(date_string, end_of_day=False):
        """
        Converts a date string to a timestamp.

        Args:
            date_string (str): The date string to convert.
            end_of_day (bool, optional): Whether to set the timestamp to the end of the day.

        Returns:
            str: The timestamp corresponding to the date string.
        """
        if not date_string:
            return None

        tz = timezone.utc
        dt = datetime.strptime(date_string, "%Y-%m-%d")
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        timestamp = (
            dt.astimezone(tz).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        return timestamp

    @staticmethod
    def _process_timestamp(epoch_time_ms, lat, lng):
        """
        Converts the given epoch time in milliseconds to an ISO-formatted timestamp adjusted to the local timezone
        based on the provided latitude and longitude coordinates.

        Args:
            epoch_time_ms (int): Epoch time in milliseconds.
            lat (float): Latitude coordinate for the timezone conversion.
            lng (float): Longitude coordinate for the timezone conversion.

        Returns:
            str: An ISO-formatted timestamp in the local timezone if timezone information is found, otherwise in UTC.

        Example:
            >>> _process_timestamp(1630456103000, 37.7749, -122.4194)
            '2021-09-01T09:55:03-07:00'
        """
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
        self,
        initial_bbox,
        start_date=None,
        end_date=None,
        fields=None,
        max_recursion_depth=25,
    ):
        """
        Fetches images within a bounding box.

        Args:
            initial_bbox (list): The initial bounding box.
            start_date (str, optional): The starting date for filtering images.
            end_date (str, optional): The ending date for filtering images.
            fields (list, optional): The fields to include in the response.
            max_recursion_depth (int, optional): Maximum depth of recursion.

        Returns:
            GeoImageFrame: A GeoImageFrame containing the fetched images.
        """
        if fields is None:
            fields = self.FIELDS_LIST
        else:
            self._validate_fields(fields)
        start_timestamp = self._get_timestamp(start_date)
        end_timestamp = self._get_timestamp(end_date, end_of_day=True)
        images = self._recursive_fetch(
            initial_bbox,
            fields,
            start_timestamp,
            end_timestamp,
            max_recursion_depth=max_recursion_depth,
        )
        data = self._json_to_gdf(images)
        data.drop_duplicates(subset="mly_id", inplace=True)
        return GeoImageFrame(data, geometry="geometry")

    def fetch_by_id(self, image_id, fields=None):
        """
        Fetches an image by its ID.

        Args:
            image_id (str): The ID of the image to fetch.
            fields (list, optional): The fields to include in the response.

        Returns:
            GeoImageFrame: A GeoImageFrame containing the fetched image.

        Raises:
            Exception: If the connection to Mapillary API fails.
        """
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
        """
        Fetches images by their sequence IDs.

        Args:
            sequence_ids (list): The sequence IDs to fetch images from.
            fields (list, optional): The fields to include in the response.

        Returns:
            GeoImageFrame: A GeoImageFrame containing the fetched images.

        Raises:
            Exception: If the connection to Mapillary API fails or the data count exceeds the limit.
        """
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
