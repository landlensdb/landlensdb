import os
import pytz
import warnings

import numpy as np
from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from shapely import Point
from timezonefinder import TimezoneFinder

from landlens.geoclasses.geoimageframe import GeoImageFrame


class ImageExifProcessor:
    @staticmethod
    def _infer_camera_type(focal_length):
        if not focal_length:
            return np.nan
        # This is a heuristic. Actual classification can vary based on camera and lens specifications.
        if focal_length < 1.5:
            return "fisheye"
        else:
            return "perspective"

    @staticmethod
    def get_exif_data(img):
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
    def _to_decimal(coord_tuple):
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
        if "GPSAltitude" in geotags:
            return geotags["GPSAltitude"]
        return None

    @classmethod
    def _get_image_direction(cls, geotags):
        if "GPSImgDirection" in geotags:
            return geotags["GPSImgDirection"]
        return None

    @classmethod
    def _get_coordinates(cls, geotags):
        lat = cls._to_decimal(geotags["GPSLatitude"])
        lon = cls._to_decimal(geotags["GPSLongitude"])

        if geotags["GPSLatitudeRef"] == "S":
            lat = -lat

        if geotags["GPSLongitudeRef"] == "W":
            lon = -lon

        return lat, lon

    @staticmethod
    def _get_focal_length(exif_data):
        focal_length = exif_data.get("FocalLength", None)

        if focal_length is None:
            return None

        if (
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
    def load_images(cls, directory):
        tf = TimezoneFinder()
        data = []
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.lower().endswith((".png", ".jpg", ".jpeg")):
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
                    camera_type = cls._infer_camera_type(focal_length)

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
                            captured_at = (
                                captured_at_naive.isoformat()
                            )  # Stays as a naive datetime
                    else:
                        captured_at = None

                    altitude = np.float32(cls._get_image_altitude(geotags))
                    compass_angle = np.float32(cls._get_image_direction(geotags))
                    exif_orientation = np.float32(exif_data.get("Orientation", None))

                    data.append(
                        {
                            "name": filepath.split("/")[-1],
                            "altitude": altitude,
                            "camera_type": camera_type,
                            "camera_parameters": camera_parameters,
                            "captured_at": captured_at,
                            "compass_angle": compass_angle,
                            "exif_orientation": exif_orientation,
                            "image_url": filepath,
                            "geometry": geometry,
                        }
                    )
        gif = GeoImageFrame(data, geometry="geometry")
        gif.set_crs(epsg=4326, inplace=True)
        return gif
