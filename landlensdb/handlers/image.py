import os
import pytz
import warnings
import numbers

import numpy as np

from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from shapely import Point
from timezonefinder import TimezoneFinder

from landlensdb.geoclasses.geoimageframe import GeoImageFrame


KNOWN_CAMERAS = {
    "360 Models": ["RICOH THETA SC", "RICOH THETA S", "RICOH THETA V", "RICOH THETA X"]
}


class Local:
    """
    A class to process EXIF data from images, mainly focusing on extracting geotagging information.

    This class includes methods to extract various camera and image properties, such as focal length,
    camera type, coordinates, and other related data.
    """

    @staticmethod
    def _get_camera_model(exif_data):
        """
        Extracts the camera model from the EXIF data.

        Args:
            exif_data (dict): The EXIF data.

        Returns:
            str: Camera model if available, otherwise None.
        """
        return exif_data.get("Model", "").strip()

    @staticmethod
    def _infer_camera_type(focal_length, camera_model=None):
        """
        Infers the camera type based on the focal length and camera model.

        Args:
            focal_length (float): The focal length of the camera.
            camera_model (str): The camera model.

        Returns:
            str: One of "fisheye", "perspective", or "360-degree".
        """
        if not focal_length and not camera_model:
            return np.nan

        known_360_cameras = KNOWN_CAMERAS.get("360 Models", [])

        if camera_model in known_360_cameras:
            return "360-degree"

        # Further classification based on focal length
        if focal_length < 1.5:
            return "fisheye"
        else:
            return "perspective"

    @staticmethod
    def get_exif_data(img):
        """
        Retrieves the EXIF data from an image.

        Args:
            img (PIL.Image.Image): The image to extract EXIF data from.

        Returns:
            dict: A dictionary containing the EXIF data.
        """
        exif_data = {}
        info = img._getexif()
        if info:
            for tag, value in info.items():
                tag_name = TAGS.get(tag, tag)
                if tag_name == "GPSInfo":
                    gps_info = {}
                    for t in value:
                        sub_tag_name = GPSTAGS.get(t, t)
                        gps_info[sub_tag_name] = value[t]
                    exif_data[tag_name] = gps_info
                else:
                    exif_data[tag_name] = value
        return exif_data

    @staticmethod
    def create_thumbnail(image_path, size=(256, 256)):
        """
        Creates a thumbnail for the given image while preserving aspect ratio.

        Args:
            image_path (str): Path to the original image
            size (tuple): Desired thumbnail size as (width, height). Default is (256, 256)

        Returns:
            str: Path to the created thumbnail

        Raises:
            FileNotFoundError: If the image file doesn't exist
            ValueError: If the image cannot be opened or processed
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        # Create thumbnails directory in the same directory as the original image
        original_dir = os.path.dirname(image_path)
        thumbnail_dir = os.path.join(original_dir, "thumbnails")
        os.makedirs(thumbnail_dir, exist_ok=True)

        # Generate thumbnail filename
        original_filename = os.path.basename(image_path)
        thumbnail_filename = f"thumb_{original_filename}"
        thumbnail_path = os.path.join(thumbnail_dir, thumbnail_filename)

        try:
            with Image.open(image_path) as img:
                # Convert to RGB if necessary
                if img.mode in ('RGBA', 'LA'):
                    img = img.convert('RGB')
                
                # Calculate new dimensions preserving aspect ratio
                img.thumbnail(size, Image.Resampling.LANCZOS)
                
                # Save thumbnail
                img.save(thumbnail_path, "JPEG", quality=85)
                return thumbnail_path

        except Exception as e:
            raise ValueError(f"Error creating thumbnail for {image_path}: {str(e)}")

    @staticmethod
    def _to_decimal(coord_tuple):
        """
        Converts coordinates from degrees, minutes, and seconds to decimal.

        Args:
            coord_tuple (tuple or str): The coordinate tuple to convert.

        Returns:
            float: Decimal representation of the coordinates.
        """
        if isinstance(coord_tuple, tuple) and len(coord_tuple) == 3:
            return (
                float(coord_tuple[0])
                + float(coord_tuple[1]) / 60
                + float(coord_tuple[2]) / 3600
            )
        elif isinstance(coord_tuple, str) and "/" in coord_tuple:
            num, denom = coord_tuple.split("/")
            if float(denom) != 0:
                return float(num) / float(denom)
            else:
                return None
        return coord_tuple

    @classmethod
    def _get_geotagging(cls, exif):
        """
        Extracts geotagging information from EXIF metadata.

        Args:
            exif (dict): The EXIF metadata.

        Returns:
            dict: A dictionary containing the geotagging information.

        Raises:
            ValueError: If no EXIF metadata found or no GPSInfo tag found.
        """
        if not exif:
            raise ValueError("No EXIF metadata found")

        idx = None
        for tag, label in TAGS.items():
            if label == "GPSInfo":
                idx = tag
                break

        if idx is None:
            raise ValueError("No GPSInfo tag found in TAGS.")

        gps_data = exif.get("GPSInfo", exif.get(idx, None))
        if not gps_data:
            raise ValueError("No EXIF geotagging found")

        geotagging = {}
        for key, val in GPSTAGS.items():
            data_value = gps_data.get(key) or gps_data.get(val)
            if data_value:
                geotagging[val] = data_value

        return geotagging

    @classmethod
    def _get_image_altitude(cls, geotags):
        """
        Retrieves the altitude information from geotags.

        Args:
            geotags (dict): The geotags information.

        Returns:
            float: Altitude information if available, otherwise None.
        """
        if "GPSAltitude" in geotags:
            return geotags["GPSAltitude"]
        return None

    @classmethod
    def _get_image_direction(cls, geotags):
        """
        Retrieves the image direction information from geotags.

        Args:
            geotags (dict): The geotags information.

        Returns:
            float: Image direction information if available, otherwise None.
        """
        if "GPSImgDirection" in geotags:
            return geotags["GPSImgDirection"]
        return None

    @classmethod
    def _get_coordinates(cls, geotags):
        """
        Retrieves the latitude and longitude coordinates from geotags.

        Args:
            geotags (dict): The geotags information.

        Returns:
            tuple: Latitude and longitude coordinates.

        Raises:
            ValueError: If the coordinates are invalid.
        """
        lat = cls._to_decimal(geotags["GPSLatitude"])
        lon = cls._to_decimal(geotags["GPSLongitude"])

        if geotags["GPSLatitudeRef"] == "S":
            lat = -lat

        if geotags["GPSLongitudeRef"] == "W":
            lon = -lon

        return lat, lon

    @staticmethod
    def _get_focal_length(exif_data):
        """
        Retrieves the focal length from the EXIF data.

        Args:
            exif_data (dict): The EXIF data.

        Returns:
            float: Focal length if available, otherwise None.
        """
        focal_length = exif_data.get("FocalLength", None)

        if focal_length is None:
            return None

        if isinstance(focal_length, numbers.Number):
            return float(focal_length)

        elif (
            isinstance(focal_length, tuple)
            and len(focal_length) == 2
            and focal_length[1] != 0
        ):
            return float(focal_length[0]) / focal_length[1]

        elif (
            hasattr(focal_length, "num")
            and hasattr(focal_length, "den")
            and focal_length.den != 0
        ):
            return float(focal_length.num) / focal_length.den

        else:
            return None

    @classmethod
    def load_images(cls, directory, additional_columns=None, create_thumbnails=True, thumbnail_size=(256, 256)):
        """
        Loads images from a given directory, extracts relevant information, and returns it in a GeoImageFrame.

        Args:
            directory (str): Path to the directory containing images.
            additional_columns (list, optional): List of additional column names or tuples containing column name and EXIF tag.
            create_thumbnails (bool): Whether to create thumbnails for the images. Defaults to True.
            thumbnail_size (tuple): Size for generated thumbnails as (width, height). Defaults to (256, 256).

        Returns:
            GeoImageFrame: Frame containing the data extracted from the images.

        Raises:
            ValueError: If no valid images are found in the directory.

        Examples:
            >>> directory = "/path/to/images"
            >>> image_data = Local.load_images(directory, create_thumbnails=True)
        """
        tf = TimezoneFinder()
        data = []
        valid_image_count = 0
        for root, dirs, files in os.walk(directory):
            # Skip thumbnails directory
            if "thumbnails" in dirs:
                dirs.remove("thumbnails")
            for file in files:
                if file.lower().endswith((".png", ".jpg", ".jpeg")):
                    valid_image_count += 1
                    filepath = os.path.join(root, file)
                    img = Image.open(filepath)
                    exif_data = cls.get_exif_data(img)
                    try:
                        geotags = cls._get_geotagging(exif_data)
                        lat, lon = cls._get_coordinates(geotags)
                        if lat is None or lon is None:
                            raise ValueError(
                                f"Invalid coordinates for {filepath}: Latitude: {lat}, Longitude: {lon}"
                            )
                        geometry = Point(lon, lat)
                    except Exception as e:
                        warnings.warn(
                            f"Error extracting geotags for {filepath}: {str(e)}. Skipped."
                        )
                        continue
                    focal_length = cls._get_focal_length(exif_data)
                    camera_model = cls._get_camera_model(exif_data)
                    camera_type = cls._infer_camera_type(focal_length, camera_model)

                    k1 = None
                    k2 = None
                    if None in [focal_length, k1, k2]:
                        camera_parameters = np.nan
                    else:
                        camera_parameters = ",".join(
                            [str(focal_length), str(k1), str(k2)]
                        )

                    captured_at_str = exif_data.get("DateTime", None)
                    if captured_at_str and geometry:
                        captured_at_naive = datetime.strptime(
                            captured_at_str, "%Y:%m:%d %H:%M:%S"
                        )
                        tz_name = tf.timezone_at(lat=lat, lng=lon)
                        if tz_name:
                            local_tz = pytz.timezone(tz_name)
                            captured_at = local_tz.localize(
                                captured_at_naive
                            ).isoformat()
                        else:
                            captured_at = captured_at_naive.isoformat()
                    else:
                        captured_at = None

                    altitude = np.float32(cls._get_image_altitude(geotags))
                    compass_angle = np.float32(cls._get_image_direction(geotags))
                    exif_orientation = np.float32(exif_data.get("Orientation", None))

                    # Generate thumbnail if requested
                    thumb_url = None
                    if create_thumbnails:
                        try:
                            # Check if thumbnail already exists
                            thumbnail_dir = os.path.join(os.path.dirname(filepath), "thumbnails")
                            thumb_filename = f"thumb_{os.path.basename(filepath)}"
                            thumb_path = os.path.join(thumbnail_dir, thumb_filename)
                            
                            if os.path.exists(thumb_path):
                                thumb_url = thumb_path
                            else:
                                thumb_url = cls.create_thumbnail(filepath, size=thumbnail_size)
                        except Exception as e:
                            warnings.warn(f"Error creating thumbnail for {filepath}: {str(e)}")

                    image_data = {
                        "name": filepath.split("/")[-1],
                        "altitude": altitude,
                        "camera_type": camera_type,
                        "camera_parameters": camera_parameters,
                        "captured_at": captured_at,
                        "compass_angle": compass_angle,
                        "exif_orientation": exif_orientation,
                        "image_url": filepath,
                        "thumb_url": thumb_url,
                        "geometry": geometry,
                    }

                    for column_info in additional_columns or []:
                        if isinstance(column_info, str):
                            image_data[column_info] = np.nan
                        elif isinstance(column_info, tuple):
                            col_name, exif_tag = column_info
                            image_data[col_name] = exif_data.get(exif_tag, np.nan)

                    data.append(image_data)

        if valid_image_count == 0:
            raise ValueError("The directory does not contain any valid images")

        gif = GeoImageFrame(data, geometry="geometry")
        gif.set_crs(epsg=4326, inplace=True)
        return gif
