import argparse
import time

from src.controller import MapillaryImport


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download and import Mapillary imagery data into the data base and GCP Buckets"
    )
    parser.add_argument(
        "--bbox",
        required=True,
        help="Bounding Box of to use to search Mapillary images. Must be string of EPSG:4326 coordinates in form "
        "'left,bottom,right,top' ",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Downloads images take from this date. Must be in the form YYYY-MM-DD",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="Downloads images take until this date. Must be in the form YYYY-MM-DD",
    )
    parser.add_argument(
        "--image_directory",
        default="images",
        help="Directory on GCP bucket to save downloaded images.",
    )

    args = parser.parse_args()

    bbox = [float(x) for x in args.bbox.split(",")]
    start = args.start
    end = args.end
    image_dir = args.image_directory

    importer = MapillaryImport()

    start_time = time.time()
    importer.import_images_by_bbox(bbox, start, end, image_dir)
    print("--- %s seconds ---" % (time.time() - start_time))
