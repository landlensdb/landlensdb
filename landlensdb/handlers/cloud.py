import math
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import mapbox_vector_tile
import pytz
import requests
from geopandas import GeoDataFrame
from shapely.geometry import Point
from timezonefinder import TimezoneFinder
from tqdm import tqdm

from landlensdb.geoclasses.geoimageframe import GeoImageFrame


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
    TILES_URL = "https://tiles.mapillary.com"
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
        "quality_score"  # Added quality score field
    ]

    QUALITY_INDICATORS = [
        "quality_score",  # Primary quality indicator
        "computed_compass_angle",  # Secondary indicator
        "atomic_scale"  # Tertiary indicator
    ]
    IMAGE_URL_KEYS = [
        "thumb_256_url",
        "thumb_1024_url",
        "thumb_2048_url",
        "thumb_original_url",
    ]
    LIMIT = 2000
    TF = TimezoneFinder()
    ZOOM_LEVEL = 14  # Default zoom level for coverage tiles

    def __init__(self, mapillary_token):
        """
        Initialize a Mapillary object.

        Args:
            mapillary_token (str): The authentication token for Mapillary.
        """
        self.TOKEN = mapillary_token

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
        # Early return if no data
        if not json_data:
            return GeoDataFrame(geometry=[])

        for img in json_data:
            # Basic field conversions
            coords = img.get("geometry", {}).get("coordinates", [None, None])
            img["geometry"] = Point(coords)
            img["mly_id"] = img.pop("id")
            img["name"] = f"mly|{img['mly_id']}"

            # Handle computed geometry
            if "computed_geometry" in img:
                coords = img.get("computed_geometry", {}).get(
                    "coordinates", [None, None]
                )
                img["computed_geometry"] = Point(coords)

            # Process timestamp with timezone
            if "captured_at" in img:
                lat = img["geometry"].y
                lng = img["geometry"].x
                img["captured_at"] = self._process_timestamp(
                    img.get("captured_at"), lat, lng
                )

            # Set image URL from available options
            image_url_found = False
            for key in self.IMAGE_URL_KEYS:
                if key in img:
                    img["image_url"] = str(img.pop(key))  # Explicitly convert to string
                    image_url_found = True
                    break

            # If no image URL was found, set a placeholder URL
            # Instead of using a direct Mapillary API URL that might fail,
            # we'll use a placeholder that indicates the image URL is missing
            if not image_url_found:
                img["image_url"] = f"placeholder://mapillary/{img['mly_id']}"

            # Convert list parameters to strings
            for key in ["camera_parameters", "computed_rotation"]:
                if key in img and isinstance(img[key], list):
                    img[key] = ",".join(map(str, img[key]))

            # Calculate quality score if not present
            if "quality_score" not in img:
                quality_score = 0.0
                if "computed_compass_angle" in img:
                    quality_score += 0.5  # Good compass data
                if "atomic_scale" in img:
                    quality_score += 0.3  # Good scale data
                if img.get("camera_type"):
                    quality_score += 0.2  # Camera type available
                img["quality_score"] = quality_score

        # Create GeoDataFrame
        gdf = GeoDataFrame(json_data, crs="EPSG:4326")
        gdf.set_geometry("geometry", inplace=True)

        # Sort by quality indicators and drop duplicates by sequence
        if "sequence" in gdf.columns:
            sort_columns = [col for col in self.QUALITY_INDICATORS if col in gdf.columns]
            if sort_columns:
                gdf = gdf.sort_values(sort_columns, ascending=False)
                gdf = gdf.drop_duplicates(subset=['sequence'], keep='first')

        # Ensure image_url is a string type
        if "image_url" in gdf.columns:
            gdf["image_url"] = gdf["image_url"].astype(str)

        return gdf

    def _bbox_to_tile_coords(self, bbox, zoom):
        """
        Convert a bounding box to tile coordinates at a given zoom level.

        Args:
            bbox (list): [west, south, east, north] coordinates
            zoom (int): Zoom level

        Returns:
            tuple: (min_x, min_y, max_x, max_y) tile coordinates
        """
        def lat_to_tile_y(lat_deg, zoom):
            lat_rad = math.radians(lat_deg)
            n = 2.0 ** zoom
            return int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)

        def lon_to_tile_x(lon_deg, zoom):
            n = 2.0 ** zoom
            return int((lon_deg + 180.0) / 360.0 * n)

        west, south, east, north = bbox
        min_x = lon_to_tile_x(west, zoom)
        max_x = lon_to_tile_x(east, zoom)
        min_y = lat_to_tile_y(north, zoom)  # Note: y coordinates are inverted
        max_y = lat_to_tile_y(south, zoom)

        return min_x, min_y, max_x, max_y

    def _tile_to_bbox(self, tile, zoom_level):
        """
        Converts tile coordinates to a bounding box.

        Args:
            tile (dict): Tile coordinates (x, y).
            zoom_level (int): The zoom level of the tile.

        Returns:
            list: Bounding box coordinates [west, south, east, north].
        """
        x, y = tile['x'], tile['y']
        n = 2.0 ** zoom_level
        west = x / n * 360.0 - 180.0
        east = (x + 1) / n * 360.0 - 180.0

        def inv_lat(y_tile):
            return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y_tile / n))))

        north = inv_lat(y)
        south = inv_lat(y + 1)

        return [west, south, east, north]

    def _fetch_coverage_tile(self, zoom, x, y):
        """
        Fetches a single coverage tile.

        Args:
            zoom (int): Zoom level
            x (int): Tile X coordinate
            y (int): Tile Y coordinate

        Returns:
            list: Image features from the tile
        """
        url = (
            f"{self.TILES_URL}/maps/vtp/mly1_public/2"
            f"/{zoom}/{x}/{y}"
            f"?access_token={self.TOKEN}"
        )

        try:
            response = requests.get(url)
            if response.status_code == 200:
                # Vector tiles are binary, not JSON
                if 'application/x-protobuf' in response.headers.get('content-type', ''):
                    try:
                        # Decode the vector tile
                        tile_data = mapbox_vector_tile.decode(response.content)

                        # Check for image layer at zoom level 14
                        if 'image' in tile_data and zoom == 14:
                            return tile_data['image']['features']

                        # Check for sequence layer at zoom levels 6-14
                        elif 'sequence' in tile_data and 6 <= zoom <= 14:
                            return tile_data['sequence']['features']

                        # Check for overview layer at zoom levels 0-5
                        elif 'overview' in tile_data and 0 <= zoom <= 5:
                            return tile_data['overview']['features']

                        else:
                            warnings.warn(f"No usable layers found in tile {x},{y}")
                            return []

                    except Exception as e:
                        warnings.warn(f"Error decoding vector tile {x},{y}: {str(e)}")
                        return []
                else:
                    warnings.warn(f"Unexpected content type for tile {x},{y}")
                    return []
            else:
                warnings.warn(f"Error fetching tile {x},{y}: {response.status_code}")
                return []
        except Exception as e:
            warnings.warn(f"Exception fetching tile {x},{y}: {str(e)}")
            return []

    def _extract_image_ids_from_features(self, features):
        """
        Extracts image IDs from tile features.

        Args:
            features (list): List of features from a vector tile

        Returns:
            list: List of image IDs
        """
        image_ids = []

        for feature in features:
            if 'id' in feature.get('properties', {}):
                image_ids.append(str(feature['properties']['id']))
            elif 'image_id' in feature.get('properties', {}):
                image_ids.append(str(feature['properties']['image_id']))

        return image_ids

    def _fetch_image_metadata(self, image_ids, fields, max_workers=10):
        """
        Fetches metadata for multiple images using multi-threading.

        Args:
            image_ids (list): List of image IDs
            fields (list): Fields to include in the response
            max_workers (int, optional): Maximum number of concurrent workers. Default is 10.

        Returns:
            list: List of image metadata
        """
        results = []

        def fetch_single_image(image_id):
            url = (
                f"{self.BASE_URL}/{image_id}"
                f"?access_token={self.TOKEN}"
                f"&fields={','.join(fields)}"
            )

            try:
                response = requests.get(url)
                if response.status_code == 200:
                    return response.json()
                else:
                    warnings.warn(f"Error fetching image {image_id}: {response.status_code}")
                    return None
            except Exception as e:
                warnings.warn(f"Exception fetching image {image_id}: {str(e)}")
                return None

        # Use ThreadPoolExecutor for parallel fetching
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks and create a map of future to image_id
            future_to_id = {executor.submit(fetch_single_image, image_id): image_id
                           for image_id in image_ids}

            # Process results as they complete with a progress bar
            for future in tqdm(as_completed(future_to_id),
                              total=len(image_ids),
                              desc="Fetching metadata"):
                result = future.result()
                if result:
                    results.append(result)

        return results

    def fetch_within_bbox(
        self,
        initial_bbox,
        start_date=None,
        end_date=None,
        fields=None,
        max_recursion_depth=25,
        use_coverage_tiles=True,
        max_images=5000,
        max_workers=10
    ):
        """
        Fetches images within a bounding box.

        Args:
            initial_bbox (list): The bounding box to fetch images from [west, south, east, north].
            start_date (str, optional): Start date for filtering images (YYYY-MM-DD).
            end_date (str, optional): End date for filtering images (YYYY-MM-DD).
            fields (list, optional): Fields to include in the response.
            max_recursion_depth (int, optional): Maximum depth for recursive fetching.
            use_coverage_tiles (bool, optional): Whether to use coverage tiles API for large areas.
            max_images (int, optional): Maximum number of images to process. Default is 5000.
            max_workers (int, optional): Maximum number of concurrent workers. Default is 10.

        Returns:
            GeoImageFrame: A GeoImageFrame containing the image data.
        """
        if fields is None:
            fields = self.FIELDS_LIST

        # Ensure required fields are included
        if "id" not in fields:
            fields.append("id")
        if "geometry" not in fields:
            fields.append("geometry")
        if not any(url_key in fields for url_key in self.IMAGE_URL_KEYS):
            fields.append("thumb_1024_url")

        start_timestamp = self._get_timestamp(start_date) if start_date else None
        end_timestamp = self._get_timestamp(end_date, True) if end_date else None

        if use_coverage_tiles:
            # Get coverage tiles for the area
            min_x, min_y, max_x, max_y = self._bbox_to_tile_coords(initial_bbox, self.ZOOM_LEVEL)

            all_image_ids = []
            print(f"Fetching {(max_x - min_x + 1) * (max_y - min_y + 1)} tiles...")

            # Fetch all tiles in the bounding box
            for x in range(min_x, max_x + 1):
                for y in range(min_y, max_y + 1):
                    features = self._fetch_coverage_tile(self.ZOOM_LEVEL, x, y)
                    image_ids = self._extract_image_ids_from_features(features)
                    all_image_ids.extend(image_ids)

                    # Check if we've reached the maximum number of images
                    if len(all_image_ids) >= max_images * 2:  # Get more than needed to allow for filtering
                        print(f"Reached maximum number of images ({max_images}), stopping tile fetching")
                        break

                # Check again after processing a row of tiles
                if len(all_image_ids) >= max_images * 2:
                    break

            print(f"Found {len(all_image_ids)} total images")

            # Remove duplicates
            all_image_ids = list(set(all_image_ids))
            print(f"After removing duplicates: {len(all_image_ids)} unique images")

            # Limit the number of images to process
            if len(all_image_ids) > max_images:
                print(f"Limiting to {max_images} images for processing")
                all_image_ids = all_image_ids[:max_images]

            # Fetch metadata for all images using multi-threading
            all_data = self._fetch_image_metadata(all_image_ids, fields, max_workers=max_workers)

            data = self._json_to_gdf(all_data)
            return GeoImageFrame(data, geometry="geometry")
        else:
            # Use traditional recursive fetching
            data = self._recursive_fetch(
                initial_bbox,
                fields,
                start_timestamp,
                end_timestamp,
                max_recursion_depth=max_recursion_depth
            )
            gdf = self._json_to_gdf(data)
            return GeoImageFrame(gdf, geometry="geometry")

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
        url = (
            f"{self.BASE_URL}/{image_id}"
            f"?access_token={self.TOKEN}"
            f"&fields={','.join(fields)}"
        )
        response = requests.get(url)
        if response.status_code != 200:
            raise Exception(
                f"Error connecting to Mapillary API. Exception: {response.text}"
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
            Exception: If the connection to Mapillary API fails.
        """
        if fields is None:
            fields = self.FIELDS_LIST
        else:
            self._validate_fields(fields)
        url = (
            f"{self.BASE_URL}/images"
            f"?access_token={self.TOKEN}"
            f"&sequence_ids={','.join(sequence_ids)}"
            f"&fields={','.join(fields)}"
        )
        response = requests.get(url)
        if response.status_code != 200:
            raise Exception(
                f"Error connecting to Mapillary API. Exception: {response.text}"
            )
        response_data = response.json().get("data")
        if len(response_data) == self.LIMIT:
            raise Exception(
                "Data count reached the limit. Please provide fewer sequence IDs."
            )

        data = self._json_to_gdf(response_data)
        return GeoImageFrame(data, geometry="geometry")

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

    def _process_timestamp(self, epoch_time_ms, lat, lng):
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

        tz_name = self.TF.timezone_at(lat=lat, lng=lng)
        if tz_name:
            local_tz = pytz.timezone(tz_name)
            return dt_utc.astimezone(local_tz).isoformat()
        else:
            return dt_utc.isoformat()

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
                "Max recursion depth reached. Consider splitting requests."
            )
            return []

        url = (
            f"{self.BASE_URL}/images"
            f"?access_token={self.TOKEN}"
            f"&fields={','.join(fields)}"
            f"&bbox={','.join(str(i) for i in bbox)}"
            f"&limit={self.LIMIT}"
        )

        if start_timestamp:
            url += f"&start_captured_at={start_timestamp}"
        if end_timestamp:
            url += f"&end_captured_at={end_timestamp}"

        response = requests.get(url)
        if response.status_code != 200:
            raise Exception(
                f"Error connecting to Mapillary API. Exception: {response.text}"
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
