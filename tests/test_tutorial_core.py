import os

import geopandas as gpd
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import DateTime, Float, Integer, String, text

from landlensdb.geoclasses.geoimageframe import GeoImageFrame
from landlensdb.handlers.cloud import Mapillary
from landlensdb.handlers.db import Postgres
from landlensdb.handlers.image import Local
from landlensdb.process.road_network import (get_osm_lines,
                                             optimize_network_for_snapping,
                                             validate_network_topology)
from landlensdb.process.snap import snap_to_road_network


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/landlens_test")

def get_existing_mapillary_data(db_con, table_name):
    """Get existing Mapillary data (IDs and image paths) from the database."""
    try:
        # Query both IDs and image paths
        query = text(f"""
        SELECT mly_id, image_url
        FROM {table_name}
        WHERE mly_id IS NOT NULL
        AND image_url IS NOT NULL
        """)
        existing_data = pd.read_sql(query, db_con.engine)

        # Create a mapping of IDs to existing file paths
        existing_map = {}
        if not existing_data.empty:
            for _, row in existing_data.iterrows():
                if os.path.exists(row['image_url']):
                    existing_map[row['mly_id']] = row['image_url']

        return existing_map
    except Exception as e:
        print(f"Error fetching existing Mapillary data: {str(e)}")
        return {}


def ensure_table_schema(db_con, table_name):
    """Ensure the table has the correct schema for local and Mapillary images."""
    try:
        # Drop table if exists
        drop_query = text(f"DROP TABLE IF EXISTS {table_name};")
        with db_con.engine.connect() as conn:
            conn.execute(drop_query)
            conn.commit()

        # Create table with all necessary columns
        create_query = text(f"""
        CREATE TABLE {table_name} (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255),
            mly_id VARCHAR(255),
            altitude DOUBLE PRECISION,
            camera_type VARCHAR(50),
            camera_parameters TEXT,
            captured_at TIMESTAMP WITH TIME ZONE,
            compass_angle DOUBLE PRECISION,
            computed_compass_angle DOUBLE PRECISION,
            computed_geometry geometry(Point, 4326),
            exif_orientation INTEGER,
            image_url TEXT,
            thumb_url TEXT,
            geometry geometry(Point, 4326),
            snapped_geometry geometry(Point, 4326),
            snapped_angle DOUBLE PRECISION
        );
        CREATE INDEX IF NOT EXISTS idx_mly_id ON {table_name} (mly_id);
        CREATE INDEX IF NOT EXISTS idx_geometry
            ON {table_name} USING GIST (geometry);
        CREATE INDEX IF NOT EXISTS idx_snapped_geometry
            ON {table_name} USING GIST (snapped_geometry);
        """)
        with db_con.engine.connect() as conn:
            conn.execute(create_query)
            conn.commit()
        print(f"Created table {table_name} with required schema")

    except Exception as e:
        print(f"Error ensuring table schema: {str(e)}")
        raise

def prepare_data_for_db(images, create_thumbnails=True):
    """Prepare data for database insertion by ensuring correct data types."""
    if images is None:
        return None

    # Convert data types and handle nulls
    images = images.copy()

    # Convert numeric fields
    numeric_fields = ['altitude', 'compass_angle', 'computed_compass_angle']
    for field in numeric_fields:
        if field in images.columns:
            images[field] = pd.to_numeric(images[field], errors='coerce')
            # Replace inf values with None
            images[field] = images[field].replace([np.inf, -np.inf], np.nan)

    # Convert timestamp with ISO8601 format
    if 'captured_at' in images.columns:
        images['captured_at'] = pd.to_datetime(images['captured_at'], format='ISO8601', utc=True)

    # Ensure geometry is in EPSG:4326
    if 'geometry' in images.columns and images.crs is None:
        images.set_crs(epsg=4326, inplace=True)

    # Convert string fields
    string_fields = ['name', 'mly_id', 'camera_type', 'image_url']
    for field in string_fields:
        if field in images.columns:
            images[field] = images[field].astype(str)
            # Replace 'nan' with None
            images[field] = images[field].replace('nan', None)

    # Convert integer fields
    if 'exif_orientation' in images.columns:
        images['exif_orientation'] = pd.to_numeric(images['exif_orientation'], errors='coerce').astype('Int64')

    # Create thumbnails for local images if needed
    if create_thumbnails and 'image_url' in images.columns:
        images['thumb_url'] = images['image_url'].apply(lambda x: Local.create_thumbnail(x, size=(800, 800)) if os.path.exists(x) else x)

    return images

def test_local_images():
    print("\nTesting local image loading...")
    local_images = Local.load_images("test_data/local")
    print(f"Loaded {len(local_images)} local images")
    print("Sample data:")
    print(local_images.head())

    # Create thumbnails for visualization
    local_images = prepare_data_for_db(local_images, create_thumbnails=True)

    # Convert to GeoImageFrame if needed
    if not isinstance(local_images, GeoImageFrame):
        local_images = GeoImageFrame(local_images, geometry="geometry")

    # Update image_url to use thumbnails for visualization
    local_images['image_url'] = local_images['thumb_url']

    # Test visualization using thumbnails
    print("\nGenerating map visualization...")
    map_html = local_images.map(
        additional_properties=['altitude', 'camera_type'],
        additional_geometries=[
            {'geometry': 'geometry', 'angle': 'compass_angle', 'label': 'Original'}
        ]
    )
    os.makedirs('test_data/output', exist_ok=True)
    map_html.save('test_data/output/test_map.html')

    return local_images

def test_mapillary_images():
    print("\nTesting Mapillary image loading...")
    try:
        # Define a very small bounding box in Tokyo (around Shibuya crossing)
        # This is approximately 100m x 100m area
        bbox = [139.7003, 35.6585, 139.7013, 35.6595]
        print(f"Testing area: {bbox} (approximately 100m x 100m in Tokyo)")

        # Create handlers
        handler = Mapillary(os.getenv("MLY_TOKEN"))
        db_con = Postgres(DATABASE_URL)
        table_name = "tests"

        # Ensure table schema
        ensure_table_schema(db_con, table_name)

        # Get existing Mapillary data from database
        existing_data = get_existing_mapillary_data(db_con, table_name)
        print(f"Found {len(existing_data)} existing Mapillary images in database")

        # Skip traditional method due to API limitations
        print("\nSkipping traditional method due to API limitations")

        # Test coverage tiles method
        print("\nTesting coverage tiles method...")
        fields = [
            "id", "altitude", "captured_at", "camera_type", "thumb_1024_url",
            "compass_angle", "computed_compass_angle", "computed_geometry",
            "geometry", "sequence", "quality_score"
        ]

        # Set a small max_images limit to avoid processing too many images
        coverage_images = handler.fetch_within_bbox(
            bbox,
            fields=fields,
            use_coverage_tiles=True,
            max_images=100  # Limit to 100 images
        )

        print(f"\nCoverage tiles method found: {len(coverage_images)} images")

        # Use the coverage tiles results for further processing
        all_images = coverage_images

        if all_images is not None and len(all_images) > 0:
            print(f"\nAnalyzing {len(all_images)} total Mapillary images:")
            print(f"- Unique sequences: {all_images['sequence'].nunique()}")

            if 'quality_score' in all_images.columns:
                print(f"- Average quality score: {all_images['quality_score'].mean():.2f}")

            print(f"- Images with compass angle: {all_images['compass_angle'].notna().sum()}")

            if 'computed_compass_angle' in all_images.columns:
                print(f"- Images with computed compass: {all_images['computed_compass_angle'].notna().sum()}")

            # Filter out existing images
            if not all_images.empty:
                new_images = all_images[~all_images['mly_id'].isin(existing_data.keys())]
                print(f"\nFound {len(new_images)} new images to process")

                if len(new_images) > 0:
                    print("\nSample of new Mapillary data:")
                    sample_cols = ['altitude', 'compass_angle', 'image_url']
                    if 'quality_score' in new_images.columns:
                        sample_cols.append('quality_score')
                    print(new_images[sample_cols].head())

                    # Process images for database
                    processed_images = []
                    for _, row in new_images.iterrows():
                        try:
                            image_data = {
                                'name': f"mly|{row['mly_id']}",
                                'mly_id': row['mly_id'],
                                'altitude': row.get('altitude'),
                                'camera_type': row.get('camera_type'),
                                'captured_at': row.get('captured_at'),
                                'compass_angle': row.get('compass_angle'),
                                'computed_compass_angle': row.get('computed_compass_angle'),
                                'computed_geometry': row.get('computed_geometry'),
                                'geometry': row['geometry'],
                                'image_url': row.get('image_url')
                            }
                            processed_images.append(image_data)
                        except Exception as e:
                            print(f"Error processing image {row.get('mly_id', 'unknown')}: {str(e)}")
                            continue

                    if processed_images:
                        new_images = pd.DataFrame(processed_images)

                        # Remove columns not in schema
                        schema_columns = [
                            'name', 'mly_id', 'altitude', 'camera_type',
                            'camera_parameters', 'captured_at', 'compass_angle',
                            'computed_compass_angle', 'computed_geometry',
                            'exif_orientation', 'image_url', 'thumb_url',
                            'geometry'
                        ]
                        extra_columns = [col for col in new_images.columns
                                       if col not in schema_columns]
                        if extra_columns:
                            new_images = new_images.drop(columns=extra_columns)

                        print(f"\nSuccessfully processed {len(processed_images)} images")

                        # Ensure GeoDataFrame for database operations
                        if not isinstance(new_images, gpd.GeoDataFrame):
                            new_images = gpd.GeoDataFrame(
                                new_images,
                                geometry='geometry'
                            )
                            new_images.set_crs(epsg=4326, inplace=True)

                        return new_images
                else:
                    print("No new images to download")
                    return None
            else:
                print("No images found in the response")
                return None
        else:
            print("No Mapillary images found in the specified area")
            return None

    except Exception as e:
        print(f"Error fetching Mapillary images: {e}")
        return None

def test_road_network_snapping(images):
    print("\nTesting road network snapping...")
    try:
        # Get the bounding box coordinates
        bbox = images['geometry'].total_bounds

        # Create cache directory
        cache_dir = os.path.join(os.path.dirname(__file__), "test_cache")
        os.makedirs(cache_dir, exist_ok=True)

        # Download the road network using enhanced functions
        network = get_osm_lines(
            bbox,
            network_type='drive',
            cache_dir=cache_dir
        )
        print("Successfully downloaded road network")

        # Optimize and validate network
        network = optimize_network_for_snapping(network)
        network, report = validate_network_topology(network)

        if report['issues']:
            print("Network validation report:")
            for issue in report['issues']:
                print(f"- {issue}")
            for repair in report['repairs']:
                print(f"- {repair}")

        # Snap images to road network
        snap_to_road_network(
            images,
            tolerance=100,
            network=network,
            realign_camera=True
        )
        print("Successfully snapped images to road network")

        # Print statistics
        total_images = len(images)
        snapped_images = images['snapped_geometry'].notna().sum()
        print(f"\nSnapping statistics:")
        print(f"- Total images: {total_images}")
        print(f"- Successfully snapped: {snapped_images}")
        print(f"- Failed to snap: {total_images - snapped_images}")

        print("\nSample data with snapped geometry:")
        print(images[['name', 'geometry', 'snapped_geometry', 'snapped_angle']].head())

        # Generate visualization
        print("\nGenerating map visualization...")
        # Convert to GeoImageFrame if needed
        if not isinstance(images, GeoImageFrame):
            images = GeoImageFrame(images, geometry='geometry')

        # Create visualization map
        map_html = images.map(
            tiles='OpenStreetMap',
            zoom_start=18,
            max_zoom=19,
            additional_properties=['altitude', 'camera_type', 'compass_angle', 'snapped_angle'],
            additional_geometries=[
                {'geometry': 'geometry', 'angle': 'compass_angle', 'label': 'Original'},
                {'geometry': 'snapped_geometry', 'angle': 'snapped_angle', 'label': 'Snapped'}
            ]
        )
        os.makedirs('test_data/output', exist_ok=True)
        map_html.save('test_data/output/test_snapped_map.html')

    except Exception as e:
        print(f"Error in road network snapping: {e}")
        raise

def test_database_operations(images):
    if images is None or len(images) == 0:
        print("\nNo new images to save to database")
        return

    print("\nTesting database operations...")
    try:
        # Basic database operations
        db_con = Postgres(DATABASE_URL)
        table_name = "tests"

        # Ensure table schema
        ensure_table_schema(db_con, table_name)

        # Convert GeoDataFrame to PostGIS format
        images.to_postgis(table_name, db_con.engine, if_exists="replace")

        # Test querying with different filters
        print("\nTesting database queries...")

        # Query by altitude
        high_altitude_query = text(f"""
        SELECT COUNT(*)
        FROM {table_name}
        WHERE altitude > 50;
        """)
        high_altitude_count = pd.read_sql(high_altitude_query, db_con.engine).iloc[0, 0]
        print(f"Found {high_altitude_count} high altitude images")

        # Query by date if available
        if 'captured_at' in images.columns:
            recent_query = text(f"""
            SELECT COUNT(*)
            FROM {table_name}
            WHERE captured_at > '2024-01-01';
            """)
            recent_count = pd.read_sql(recent_query, db_con.engine).iloc[0, 0]
            print(f"Found {recent_count} images captured after 2024-01-01")

    except Exception as e:
        print(f"Error in database operations: {e}")
        raise

def main():
    print("Loading environment variables...")
    load_dotenv()

    print("\nSkipping local image testing...")
    local_images = None

    # Test Mapillary image loading and downloading
    mapillary_images = test_mapillary_images()

    # Test road network snapping with Mapillary images if available
    if mapillary_images is not None and len(mapillary_images) > 0:
        print("\nTesting road network snapping with Mapillary images...")
        test_road_network_snapping(mapillary_images)

        print("\nTesting database operations with Mapillary images...")
        test_database_operations(mapillary_images)


if __name__ == "__main__":
    main()
