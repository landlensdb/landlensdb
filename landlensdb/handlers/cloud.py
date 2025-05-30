import math
import warnings
import os
import random
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import mapbox_vector_tile
import pytz
import requests
import pandas as pd
from geopandas import GeoDataFrame
from shapely.geometry import Point
from timezonefinder import TimezoneFinder
from PIL import Image
from tqdm import tqdm

from landlensdb.geoclasses.geoimageframe import GeoImageFrame


class Mapillary:
    """
    Class to interact with Mapillary's API to fetch image data and download images.
    Implements accurate rate limiting based on Mapillary's API documentation.

    Args:
        mapillary_token (str): The authentication token for Mapillary.

    Examples:
        >>> mapillary = Mapillary("YOUR_TOKEN_HERE")
        >>> images = mapillary.fetch_within_bbox([12.34, 56.78, 90.12, 34.56])
        >>> mapillary.download_images(images, "output_directory")
    """

    # API endpoints
    BASE_URL = "https://graph.mapillary.com"
    TILES_URL = "https://tiles.mapillary.com"

    # API rate limits
    ENTITY_LIMIT = 60000  # 60,000 requests per minute for entity API
    SEARCH_LIMIT = 10000  # 10,000 requests per minute for search API
    TILES_LIMIT = 50000  # 50,000 requests per day for tiles API

    # Results limit for recursive fetch
    LIMIT = 2000  # Maximum number of results per API call

    # Fields and settings
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
        "quality_score",
    ]

    QUALITY_INDICATORS = ["quality_score", "computed_compass_angle", "atomic_scale"]
    IMAGE_URL_KEYS = [
        "thumb_256_url",
        "thumb_1024_url",
        "thumb_2048_url",
        "thumb_original_url",
    ]

    TF = TimezoneFinder()
    ZOOM_LEVEL = 14  # Default zoom level for coverage tiles

    # User agents for rotating during API requests
    USER_AGENTS = [
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        },
        {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36"
        },
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Safari/605.1.15"
        },
    ]

    def __init__(self, mapillary_token):
        """
        Initialize a Mapillary object with rate limiting.

        Args:
            mapillary_token (str): The authentication token for Mapillary.
        """
        self.TOKEN = mapillary_token

        # Rate limit tracking
        self._rate_limits = {
            "entity": {
                "count": 0,
                "reset_time": time.time(),
                "limit": self.ENTITY_LIMIT,
                "window": 60,
            },
            "search": {
                "count": 0,
                "reset_time": time.time(),
                "limit": self.SEARCH_LIMIT,
                "window": 60,
            },
            "tiles": {
                "count": 0,
                "reset_time": time.time(),
                "limit": self.TILES_LIMIT,
                "window": 86400,
            },
        }

    def _rate_limited_request(self, url, method="get", api_type=None, **kwargs):
        """
        Makes a rate-limited request to the Mapillary API.

        Args:
            url (str): URL to request
            method (str, optional): HTTP method ('get', 'post', etc.). Defaults to 'get'.
            api_type (str, optional): API type for rate limiting ('entity', 'search', 'tiles').
                If None, will be determined from the URL.
            **kwargs: Additional arguments to pass to requests.request()

        Returns:
            requests.Response: Response from the server

        Raises:
            Exception: If rate limit is exceeded or other request error
        """
        # Determine API type if not provided
        if api_type is None:
            if "tiles.mapillary.com" in url:
                api_type = "tiles"
            elif "/images?" in url or "bbox=" in url:
                api_type = "search"
            else:
                api_type = "entity"

        rate_limit = self._rate_limits[api_type]

        # Check if we need to reset the counter
        current_time = time.time()
        elapsed = current_time - rate_limit["reset_time"]

        if elapsed >= rate_limit["window"]:
            # Reset counter if time window has passed
            rate_limit["count"] = 0
            rate_limit["reset_time"] = current_time

        # Check if we're at the limit
        if rate_limit["count"] >= rate_limit["limit"]:
            # Calculate time until reset
            wait_time = rate_limit["window"] - elapsed

            if wait_time > 0:
                print(
                    f"{api_type.capitalize()} API rate limit reached. Waiting {wait_time:.1f} seconds..."
                )
                time.sleep(wait_time)
                # Reset counter after waiting
                rate_limit["count"] = 0
                rate_limit["reset_time"] = time.time()

        # Add random user agent if not provided
        if "headers" not in kwargs:
            kwargs["headers"] = random.choice(self.USER_AGENTS)

        # Add timeout if not provided
        if "timeout" not in kwargs:
            kwargs["timeout"] = 30

        # Make the request with retry logic
        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                response = getattr(requests, method.lower())(url, **kwargs)

                # Update rate limit tracking
                rate_limit["count"] += 1

                # Handle rate limiting responses
                if response.status_code == 429:  # Too Many Requests
                    retry_after = int(response.headers.get("Retry-After", 60))
                    print(f"Rate limit exceeded. Waiting {retry_after} seconds...")
                    time.sleep(retry_after)
                    continue

                # Handle server errors with backoff
                if response.status_code >= 500:
                    if attempt < max_retries - 1:
                        sleep_time = retry_delay * (2**attempt)  # Exponential backoff
                        print(
                            f"Server error: HTTP {response.status_code}. Retrying in {sleep_time} seconds..."
                        )
                        time.sleep(sleep_time)
                        continue

                return response

            except (
                requests.exceptions.RequestException,
                requests.exceptions.ConnectionError,
            ) as e:
                if attempt < max_retries - 1:
                    sleep_time = retry_delay * (2**attempt)  # Exponential backoff
                    print(
                        f"Request failed: {str(e)}. Retrying in {sleep_time} seconds..."
                    )
                    time.sleep(sleep_time)
                else:
                    raise Exception(
                        f"Request failed after {max_retries} attempts: {str(e)}"
                    )

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
            if not image_url_found:
                img["image_url"] = f"placeholder://mapillary/{img['mly_id']}"

            # Convert list parameters to strings
            for key in ["camera_parameters", "computed_rotation"]:
                if key in img and isinstance(img[key], list):
                    img[key] = ",".join(map(str, img[key]))

        # Create GeoDataFrame with all images
        gdf = GeoDataFrame(json_data, crs="EPSG:4326")
        gdf.set_geometry("geometry", inplace=True)

        # Ensure image_url is a string type
        if "image_url" in gdf.columns:
            gdf["image_url"] = gdf["image_url"].astype(str)

        return gdf

    def fetch_within_bbox(
        self,
        initial_bbox,
        start_date=None,
        end_date=None,
        fields=None,
        max_recursion_depth=25,
        use_coverage_tiles=True,
        max_images=None,
        max_workers=10,
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
            max_images (int, optional): Maximum number of images to process. Default is None (no limit).
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

        # Convert dates to timestamps in milliseconds
        start_timestamp = self._get_timestamp_ms(start_date) if start_date else None
        end_timestamp = self._get_timestamp_ms(end_date, True) if end_date else None

        if use_coverage_tiles:
            # Get coverage tiles for the area
            min_x, min_y, max_x, max_y = self._bbox_to_tile_coords(
                initial_bbox, self.ZOOM_LEVEL
            )

            all_image_ids = []
            print(f"Fetching {(max_x - min_x + 1) * (max_y - min_y + 1)} tiles...")

            # Fetch all tiles in the bounding box
            for x in range(min_x, max_x + 1):
                for y in range(min_y, max_y + 1):
                    features = self._fetch_coverage_tile(
                        self.ZOOM_LEVEL,
                        x,
                        y,
                        start_timestamp=start_timestamp,
                        end_timestamp=end_timestamp,
                    )
                    image_ids = self._extract_image_ids_from_features(features)
                    all_image_ids.extend(image_ids)

                    # Only check max_images if it's set
                    if max_images is not None and len(all_image_ids) >= max_images * 2:
                        print(
                            f"Reached maximum number of images ({max_images}), stopping tile fetching"
                        )
                        break

                # Check again after processing a row of tiles
                if max_images is not None and len(all_image_ids) >= max_images * 2:
                    break

            print(f"Found {len(all_image_ids)} total images")

            # Remove duplicates
            all_image_ids = list(set(all_image_ids))
            print(f"After removing duplicates: {len(all_image_ids)} unique images")

            # If no images found, return empty GeoImageFrame with all required columns
            if not all_image_ids:
                print("No images found matching the criteria")
                empty_data = {
                    "id": [],
                    "mly_id": [],
                    "name": [],
                    "geometry": [],
                    "image_url": [],
                    "quality_score": [],
                    "captured_at": [],
                    "computed_geometry": [],
                    "camera_parameters": [],
                    "computed_rotation": [],
                }
                return GeoImageFrame(empty_data, geometry="geometry")

            # Limit the number of images to process only if max_images is set
            if max_images is not None and len(all_image_ids) > max_images:
                print(f"Limiting to {max_images} images for processing")
                all_image_ids = all_image_ids[:max_images]

            # Fetch metadata for all images using multi-threading
            all_data = self._fetch_image_metadata(
                all_image_ids, fields, max_workers=max_workers
            )

            data = self._json_to_gdf(all_data)
            return GeoImageFrame(data, geometry="geometry")
        else:
            # Use traditional recursive fetching
            data = self._recursive_fetch(
                initial_bbox,
                fields,
                start_timestamp,
                end_timestamp,
                max_recursion_depth=max_recursion_depth,
            )
            gdf = self._json_to_gdf(data)
            return GeoImageFrame(gdf, geometry="geometry")

    def download_images(
        self,
        geoimageframe,
        output_dir,
        resolution=1024,
        cropped=False,
        batch_size=25,
        max_workers=10,
        skip_existing=True,
        quality_threshold=None,
        max_retries=3,
    ):
        """
        Download images from a GeoImageFrame with proper rate limiting.

        Args:
            geoimageframe (GeoImageFrame): GeoImageFrame containing image metadata
            output_dir (str): Directory to save the downloaded images
            resolution (int, optional): Resolution of the images. Defaults to 1024.
                Valid options are 256, 1024, 2048
            cropped (bool, optional): Whether to crop the images to the upper half. Defaults to False.
            batch_size (int, optional): Number of images per batch. Defaults to 25.
            max_workers (int, optional): Maximum number of concurrent workers. Defaults to 10.
                Note: Even with multiple workers, the class respects API rate limits.
            skip_existing (bool, optional): Whether to skip existing images. Defaults to True.
            quality_threshold (float, optional): Minimum quality score to download. Defaults to None.
            max_retries (int, optional): Maximum number of retries for failed downloads. Defaults to 3.

        Returns:
            tuple: (success_count, failed_list) - Number of successfully downloaded images and list of failed IDs
        """
        # Create output directory if it doesn't exist
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create a cache directory for metadata
        cache_dir = output_dir / ".cache"
        cache_dir.mkdir(exist_ok=True)

        # Prepare cache filename
        cache_file = cache_dir / "download_status.json"

        # Load status cache if it exists
        download_status = {}
        if cache_file.exists() and skip_existing:
            try:
                with open(cache_file, "r") as f:
                    download_status = json.load(f)
            except Exception as e:
                warnings.warn(f"Error loading cache: {str(e)}")

        # Filter by quality threshold if provided
        if quality_threshold is not None and "quality_score" in geoimageframe.columns:
            pre_filter_count = len(geoimageframe)
            geoimageframe = geoimageframe[
                geoimageframe["quality_score"] >= quality_threshold
            ]
            filtered_count = pre_filter_count - len(geoimageframe)
            if filtered_count > 0:
                print(
                    f"Filtered out {filtered_count} images below quality threshold {quality_threshold}"
                )

        # Find already downloaded images
        existing_files = []
        if skip_existing:
            existing_files = set(f.stem for f in output_dir.glob("*.png"))
            print(
                f"Found {len(existing_files)} existing images in the output directory"
            )

        # Filter out images that have already been downloaded or failed permanently
        df = geoimageframe.copy()

        # Ensure necessary columns exist
        if "mly_id" not in df.columns:
            if "id" in df.columns:
                df["mly_id"] = df["id"]
            else:
                raise ValueError("DataFrame must contain 'mly_id' or 'id' column")

        # Convert mly_id to string for consistent handling
        df["mly_id"] = df["mly_id"].astype(str)

        # Filter out already downloaded images
        if skip_existing:
            df = df[~df["mly_id"].isin(existing_files)]
            df = df[
                ~df["mly_id"].isin(
                    [
                        id
                        for id, status in download_status.items()
                        if status == "failed_permanent"
                    ]
                )
            ]

        if len(df) == 0:
            print("No new images to download")
            return 0, []

        print(f"Preparing to download {len(df)} images")

        # Check for image_url column, fallback to constructing URLs
        has_image_url = (
            "image_url" in df.columns
            and not df["image_url"].str.contains("placeholder").any()
        )

        # If no image_url but we have a specific resolution, check for thumb_*_url
        url_column = f"thumb_{resolution}_url"
        if not has_image_url and url_column in df.columns:
            has_image_url = True
            df["image_url"] = df[url_column]

        # Function to download a single image with rate limiting
        def download_single_image(row):
            image_id = str(row["mly_id"])

            # Get URL from the dataframe if it exists, otherwise construct it
            if (
                has_image_url
                and not pd.isna(row["image_url"])
                and not row["image_url"].startswith("placeholder")
            ):
                url = row["image_url"]
            else:
                # Construct URL for the image using the API
                url = f"https://graph.mapillary.com/{image_id}/thumbnail?access_token={self.TOKEN}&height={resolution}"

            image_path = output_dir / f"{image_id}.png"

            # Skip if already downloaded
            if image_path.exists():
                return True, image_id, "skipped"

            for retry in range(max_retries):
                try:
                    # Use rate-limited request
                    response = self._rate_limited_request(url, api_type="entity")

                    if response.status_code == 200:
                        # Save the image
                        with open(image_path, "wb") as f:
                            f.write(response.content)

                        # Crop the image if requested
                        if cropped:
                            try:
                                img = Image.open(image_path)
                                w, h = img.size
                                img_cropped = img.crop((0, 0, w, h // 2))
                                img_cropped.save(image_path)
                            except Exception as e:
                                warnings.warn(
                                    f"Error cropping image {image_id}: {str(e)}"
                                )
                                # Continue anyway since we have the full image

                        return True, image_id, "success"

                    elif response.status_code == 404:
                        # Permanent failure, don't retry
                        return False, image_id, "failed_permanent"

                    elif response.status_code == 429:
                        # Rate limit exceeded - this shouldn't happen with our rate limiter
                        # but just in case, sleep and retry
                        retry_after = int(response.headers.get("Retry-After", 60))
                        print(
                            f"Rate limit exceeded for {image_id}. Waiting {retry_after} seconds..."
                        )
                        time.sleep(retry_after)

                    else:
                        # Other error, sleep and retry
                        wait_time = 2**retry  # Exponential backoff
                        print(
                            f"Error downloading image {image_id} (HTTP {response.status_code}). Retrying in {wait_time}s... ({retry+1}/{max_retries})"
                        )
                        time.sleep(wait_time)

                except Exception as e:
                    # Handle connection errors
                    wait_time = 2**retry  # Exponential backoff
                    print(
                        f"Error downloading image {image_id}: {str(e)}. Retrying in {wait_time}s... ({retry+1}/{max_retries})"
                    )
                    time.sleep(wait_time)

            # If we get here, all retries failed
            return False, image_id, "failed_temporary"

        # Process in batches
        success_count = 0
        failed_ids = []

        # Calculate number of batches
        num_batches = (len(df) + batch_size - 1) // batch_size

        for batch_idx in range(num_batches):
            print(f"Processing batch {batch_idx + 1}/{num_batches}")

            # Get batch of images
            batch_df = df.iloc[batch_idx * batch_size : (batch_idx + 1) * batch_size]

            # Download images with controlled concurrency
            batch_results = []
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_row = {
                    executor.submit(download_single_image, row): row
                    for _, row in batch_df.iterrows()
                }

                for future in tqdm(
                    as_completed(future_to_row),
                    total=len(future_to_row),
                    desc=f"Batch {batch_idx + 1}",
                ):
                    success, image_id, status = future.result()
                    batch_results.append((success, image_id, status))

                    # Update status cache
                    download_status[image_id] = status

                    if success:
                        success_count += 1
                    elif status == "failed_temporary":
                        failed_ids.append(image_id)

            # Save status after each batch
            with open(cache_file, "w") as f:
                json.dump(download_status, f)

            # Calculate and display batch success rate
            batch_success = sum(1 for success, _, _ in batch_results if success)
            batch_size_actual = len(batch_df)
            print(
                f"Batch {batch_idx + 1} complete: {batch_success}/{batch_size_actual} images downloaded successfully"
            )

        # Print final summary
        print(
            f"Download complete: {success_count}/{len(df)} images downloaded successfully"
        )
        if failed_ids:
            print(f"Failed to download {len(failed_ids)} images")

        return success_count, failed_ids

    def _fetch_coverage_tile(
        self, zoom, x, y, start_timestamp=None, end_timestamp=None
    ):
        """
        Fetches a single coverage tile with optional date filtering.

        Args:
            zoom (int): Zoom level
            x (int): Tile X coordinate
            y (int): Tile Y coordinate
            start_timestamp (str, optional): Start timestamp for filtering
            end_timestamp (str, optional): End timestamp for filtering

        Returns:
            list: Image features from the tile
        """
        url = (
            f"{self.TILES_URL}/maps/vtp/mly1_public/2"
            f"/{zoom}/{x}/{y}"
            f"?access_token={self.TOKEN}"
        )

        try:
            response = self._rate_limited_request(url, api_type="tiles")
            if response.status_code == 200:
                # Vector tiles are binary, not JSON
                if "application/x-protobuf" in response.headers.get("content-type", ""):
                    try:
                        # Decode the vector tile
                        tile_data = mapbox_vector_tile.decode(response.content)
                        features = []

                        # Check for image layer at zoom level 14
                        if "image" in tile_data and zoom == 14:
                            features = tile_data["image"]["features"]
                        # Check for sequence layer at zoom levels 6-14
                        elif "sequence" in tile_data and 6 <= zoom <= 14:
                            features = tile_data["sequence"]["features"]
                        # Check for overview layer at zoom levels 0-5
                        elif "overview" in tile_data and 0 <= zoom <= 5:
                            features = tile_data["overview"]["features"]
                        else:
                            warnings.warn(f"No usable layers found in tile {x},{y}")
                            return []

                        # Apply date filtering if timestamps are provided
                        if start_timestamp or end_timestamp:
                            filtered_features = []
                            for feature in features:
                                props = feature.get("properties", {})
                                captured_at = props.get("captured_at")

                                if captured_at:
                                    # Convert captured_at to timestamp for comparison
                                    try:
                                        captured_ts = int(captured_at)
                                        if start_timestamp and captured_ts < int(
                                            start_timestamp
                                        ):
                                            continue
                                        if end_timestamp and captured_ts > int(
                                            end_timestamp
                                        ):
                                            continue
                                        filtered_features.append(feature)
                                    except (ValueError, TypeError):
                                        # If timestamp conversion fails, include the feature
                                        filtered_features.append(feature)
                                else:
                                    # If no timestamp, include the feature
                                    filtered_features.append(feature)

                            return filtered_features

                        return features

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
            if "id" in feature.get("properties", {}):
                image_ids.append(str(feature["properties"]["id"]))
            elif "image_id" in feature.get("properties", {}):
                image_ids.append(str(feature["properties"]["image_id"]))

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
                response = self._rate_limited_request(url, api_type="entity")
                if response.status_code == 200:
                    return response.json()
                else:
                    warnings.warn(
                        f"Error fetching image {image_id}: {response.status_code}"
                    )
                    return None
            except Exception as e:
                warnings.warn(f"Exception fetching image {image_id}: {str(e)}")
                return None

        # Use ThreadPoolExecutor for parallel fetching
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks and create a map of future to image_id
            future_to_id = {
                executor.submit(fetch_single_image, image_id): image_id
                for image_id in image_ids
            }

            # Process results as they complete with a progress bar
            for future in tqdm(
                as_completed(future_to_id),
                total=len(image_ids),
                desc="Fetching metadata",
            ):
                result = future.result()
                if result:
                    results.append(result)

        return results

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
            n = 2.0**zoom
            return int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)

        def lon_to_tile_x(lon_deg, zoom):
            n = 2.0**zoom
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
        x, y = tile["x"], tile["y"]
        n = 2.0**zoom_level
        west = x / n * 360.0 - 180.0
        east = (x + 1) / n * 360.0 - 180.0

        def inv_lat(y_tile):
            return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y_tile / n))))

        north = inv_lat(y)
        south = inv_lat(y + 1)

        return [west, south, east, north]

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
            warnings.warn("Max recursion depth reached. Consider splitting requests.")
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

        response = self._rate_limited_request(url, api_type="search")
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

    def _split_bbox(self, inner_bbox):
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

    def _get_timestamp_ms(self, date_string, end_of_day=False):
        """
        Converts a date string to a timestamp in milliseconds.

        Args:
            date_string (str): The date string to convert (YYYY-MM-DD)
            end_of_day (bool, optional): Whether to set the timestamp to the end of the day

        Returns:
            int: The timestamp in milliseconds
        """
        if not date_string:
            return None

        dt = datetime.strptime(date_string, "%Y-%m-%d")
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Convert to UTC timestamp in milliseconds
        return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)

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
