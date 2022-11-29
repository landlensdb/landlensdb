import argparse
import datetime
import json
import os
import psycopg2
import requests

from google.cloud import storage
from tqdm import tqdm
from shapely.geometry import Point


DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/mapillary')
TOKEN = os.environ.get('MAPILLARY_TOKEN', '')
BUCKET_NAME = os.environ.get('BUCKET_NAME', '')

headers = {"Authorization": "OAuth {}".format(TOKEN)}


def get_image_ids():
    """
    Gets a list of all mapillary image IDs from the database.

    Returns:
        list: list of mapillary image IDs.
    """
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT id FROM mly_images")
    rows = cur.fetchall()
    images = [row[0] for row in rows]
    cur.close()
    conn.close()

    return images


def split_bbox(inner_bbox):
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
    xm = (x2 - x1)/2
    ym = (y2 - y1)/2

    q1 = [x1, y1, x1 + xm, y1 + ym]
    q2 = [x1 + xm, y1, x2, y1 + ym]
    q3 = [x1, y1 + ym, x1 + xm, y2]
    q4 = [x1 + xm, y1 + ym, x2, y2]

    return [q1, q2, q3, q4]


def add_images(initial_bbox, start_date, end_date, export_path):
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
    existing_images = get_image_ids()

    fields_list = [
        'id',
        'sequence',
        'altitude',
        'computed_altitude',
        'camera_type',
        'camera_parameters',
        'captured_at',
        'compass_angle',
        'computed_compass_angle',
        'exif_orientation',
        'merge_cc',
        'mesh',
        'sfm_cluster',
        'detections',
        'thumb_1024_url',
        'computed_geometry',
        'geometry'
    ]
    fields = ','.join(fields_list)

    # todo: check that time zones dont matter. Because we arent concerned with times,
    #  it probably is never necessary to look at timezones.
    # tz = pytz.timezone('Asia/Tokyo')
    tz = datetime.timezone.utc
    start_timestamp = datetime.datetime.strptime(start_date, '%Y-%m-%d').astimezone(tz).replace(
        microsecond=0).isoformat().replace('+00:00', 'Z')
    end_timestamp = datetime.datetime.strptime(end_date, '%Y-%m-%d').astimezone(tz).replace(microsecond=0).isoformat().replace('+00:00', 'Z')

    base_url = 'https://graph.mapillary.com/images'

    bbox_list = list([initial_bbox])
    images = []

    # use a double ended queue (deque) and add to queue when necessary and remove when either box too large or complete
    while len(bbox_list) > 0:
        current_bbox = bbox_list[0]
        bbox_string = ",".join(str(i) for i in current_bbox)
        url = f'{base_url}?access_token={TOKEN}&start_captured_at={start_timestamp}' \
              f'&end_captured_at={end_timestamp}&fields={fields}&bbox={bbox_string}' \
              f'&limit=2000'

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(
                "There was an error connecting to the Mapillary API. "
                "Requested area/time frame may be too large. "
                "Please check that your token is correct "
                "and that your internet connection is stable.")

        response_data = response.json().get('data')
        response_count = len(response_data)

        if response_count == 2000:
            bbox_children = split_bbox(current_bbox)
            bbox_list.pop(0)
            for bbox_child in bbox_children:
                bbox_list.append(bbox_child)
        else:
            images += response_data
            bbox_list.pop(0)

    for image in tqdm(images):
        if image['id'] not in existing_images:
            image_id = image.get('id')
            seq = image.get('sequence')
            altitude = image.get('altitude')
            computed_altitude = image.get('computed_altitude')
            camera_type = image.get('camera_type')
            camera_parameters = json.dumps(image.get('camera_parameters')) if image.get('camera_parameters') else None
            captured_at = datetime.datetime.fromtimestamp(image.get('captured_at')/1000, datetime.timezone.utc)
            compass_angle = image.get('compass_angle')
            computed_compass_angle = image.get('computed_compass_angle')
            exif_orientation = image.get('exif_orientation')
            merge_cc = int(image.get('merge_cc'))
            mesh = json.dumps(image.get('mesh')) if image.get('mesh') else None
            sfm_cluster = json.dumps(image.get('sfm_cluster')) if image.get('sfm_cluster') else None
            detections = json.dumps(image.get('detections')) if image.get('detections') else None
            computed_geometry = "SRID=4326;" + Point(image.get('computed_geometry').get('coordinates')).wkt
            geometry = "SRID=4326;" + Point(image.get('geometry').get('coordinates')).wkt

            image_data = requests.get(image['thumb_1024_url'], stream=True).content
            image_path = '{}/{}/image_{}.jpg'.format(export_path, seq, image_id)

            storage_client = storage.Client()
            bucket = storage_client.bucket(BUCKET_NAME)
            blob = bucket.blob(image_path)
            blob.upload_from_string(image_data)
            image_url = f'https://storage.cloud.google.com/sudb_images/{image_path}'

            conn = psycopg2.connect(DATABASE_URL)
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
                [image_id, seq, altitude, computed_altitude, camera_parameters, camera_type,
                 captured_at, compass_angle, computed_compass_angle, exif_orientation,
                 merge_cc, mesh, sfm_cluster, detections,
                 image_url, computed_geometry, geometry]
            )
            cur.close()
            conn.close()

    print(f'Successfully imported {len(images)} records into the database.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Download and import Mapillary imagery data into the data base and GCP Buckets'
    )
    parser.add_argument(
        "--bbox",
        required=True,
        help="Bounding Box of to use to search Mapillary images. Must be string of EPSG:4326 coordinates in form "
             "'left,bottom,right,top' "
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Downloads images take from this date. Must be in the form YYYY-MM-DD"
    )
    parser.add_argument(
        "--end",
        required=True,
        help="Downloads images take until this date. Must be in the form YYYY-MM-DD"
    )
    parser.add_argument(
        "--image_directory",
        default='images',
        help="Directory on GCP bucket to save downloaded images."
    )

    args = parser.parse_args()

    bbox = [float(x) for x in args.bbox.split(',')]
    start = args.start
    end = args.end
    image_dir = args.image_directory

    add_images(bbox, start, end, image_dir)
