import os
import geopandas as gpd
import pandas as pd
import requests
import numpy as np
from PIL import Image
from io import BytesIO
from pathlib import Path
from shapely.geometry import Point
from dotenv import load_dotenv
from sqlalchemy import text, String, Float, DateTime, Integer
from landlens_db.handlers.db import Postgres
from landlens_db.geoclasses.geoimageframe import GeoImageFrame
from landlens_db.handlers.cloud import Mapillary
from landlens_db.handlers.image import Local
from landlens_db.process.road_network import get_osm_lines, optimize_network_for_snapping, validate_network_topology
from landlens_db.process.snap import snap_to_road_network

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
    """Ensure the table has the correct schema for both local and Mapillary images."""
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
            geometry geometry(Point, 4326)
        );
        CREATE INDEX IF NOT EXISTS idx_mly_id ON {table_name} (mly_id);
        CREATE INDEX IF NOT EXISTS idx_geometry ON {table_name} USING GIST (geometry);
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
            
    # Convert timestamp
    if 'captured_at' in images.columns:
        images['captured_at'] = pd.to_datetime(images['captured_at'], utc=True)
        
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
    local_images = Local.load_images("test_images/local")
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
    map_html.save('test_map.html')
    print("Map saved as test_map.html")
    
    return local_images

def test_mapillary_images():
    print("\nTesting Mapillary image loading...")
    try:
        # Define a bounding box in Tokyo
        bbox = [139.69139, 35.68917, 139.69167, 35.68944]
        
        # Create handlers
        handler = Mapillary(os.getenv("MLY_TOKEN"))
        db_con = Postgres(os.environ.get("DATABASE_URL"))
        table_name = os.environ.get("DB_TABLE")
        
        # Ensure table schema
        ensure_table_schema(db_con, table_name)
        
        # Get existing Mapillary data from database
        existing_data = get_existing_mapillary_data(db_con, table_name)
        print(f"Found {len(existing_data)} existing Mapillary images in database")
        
        # Load images from Mapillary with enhanced fields
        fields = [
            "id", "altitude", "captured_at", "camera_type", "thumb_1024_url",
            "compass_angle", "computed_compass_angle", "computed_geometry", "geometry",
            "sequence", "quality_score"
        ]
        all_images = handler.fetch_within_bbox(bbox, fields=fields)
        
        if len(all_images) > 0:
            # Filter out existing images
            new_images = all_images[~all_images['mly_id'].isin(existing_data.keys())]
            
            print(f"Found {len(all_images)} total Mapillary images")
            print(f"Of which {len(new_images)} are new images")
            
            # Handle duplicate sequences
            if len(new_images) > 0:
                # Group by sequence and get highest quality image from each sequence
                if 'sequence' in new_images.columns:
                    sequence_counts = new_images['sequence'].value_counts()
                    duplicates = sequence_counts[sequence_counts > 1]
                    
                    if not duplicates.empty:
                        print("\nFiltering duplicate sequences...")
                        print(f"Before filtering: {len(new_images)} images")
                        
                        # Sort by quality_score if available, otherwise use computed_compass_angle as a proxy
                        sort_column = 'quality_score' if 'quality_score' in new_images.columns else 'computed_compass_angle'
                        new_images = new_images.sort_values(sort_column, ascending=False)
                        
                        # Keep only the highest quality image from each sequence
                        new_images = new_images.drop_duplicates(subset=['sequence'], keep='first')
                        
                        print(f"After filtering: {len(new_images)} images")
                        print("Kept highest quality image from each sequence")
            
            if len(new_images) > 0:
                # Prepare data for database
                new_images = prepare_data_for_db(new_images, create_thumbnails=False)
                new_images['thumb_url'] = new_images['image_url']  # Use original URLs for Mapillary
                
                print("\nSample of new Mapillary data:")
                print(new_images[['altitude', 'image_url', 'geometry']].head())
                
                # Initialize download and thumbnail directories
                print("\nTesting image download...")
                download_dir = os.getenv('DOWNLOAD_DIR')
                if not os.path.exists(download_dir):
                    os.makedirs(download_dir)
                thumbnail_dir = os.path.join(download_dir, 'thumbnails')
                if not os.path.exists(thumbnail_dir):
                    os.makedirs(thumbnail_dir)
                
                # Process new images and download if needed
                processed_images = []
                download_errors = []
                
                for _, image in new_images.iterrows():
                    image_path = os.path.join(download_dir, f"mly_{image['mly_id']}.jpg")
                    image_data = image.copy()
                    
                    # Only download if image doesn't exist locally
                    if not os.path.exists(image_path):
                        try:
                            response = requests.get(image['image_url'], timeout=10)
                            response.raise_for_status()  # Raise exception for bad status codes
                            
                            with open(image_path, 'wb') as f:
                                f.write(response.content)
                            print(f"Successfully downloaded image {image['mly_id']}")
                            
                        except requests.exceptions.RequestException as e:
                            download_errors.append(f"Failed to download {image['mly_id']}: {str(e)}")
                            continue
                        except Exception as e:
                            download_errors.append(f"Error processing {image['mly_id']}: {str(e)}")
                            continue
                    
                    # Update image URLs and create thumbnail
                    image_data['image_url'] = image_path
                    try:
                        thumb_path = os.path.join(download_dir, 'thumbnails', f"thumb_mly_{image['mly_id']}.jpg")
                        if not os.path.exists(thumb_path):
                            thumb_path = Local.create_thumbnail(image_path, size=(800, 800))
                        image_data['thumb_url'] = thumb_path
                    except Exception as e:
                        print(f"Warning: Could not create thumbnail for {image['mly_id']}: {str(e)}")
                        image_data['thumb_url'] = image_data['image_url']
                    
                    # Ensure all required columns exist with proper types
                    image_data['camera_type'] = image_data.get('camera_type', 'mapillary')
                    image_data['camera_parameters'] = None  # Mapillary doesn't provide this
                    image_data['exif_orientation'] = None
                    
                    # Convert numeric fields
                    for field in ['altitude', 'compass_angle', 'computed_compass_angle']:
                        if field in image_data:
                            try:
                                image_data[field] = float(image_data[field])
                            except (ValueError, TypeError):
                                image_data[field] = None
                    
                    # Ensure datetime format
                    if 'captured_at' in image_data:
                        try:
                            image_data['captured_at'] = pd.to_datetime(image_data['captured_at'], utc=True)
                        except (ValueError, TypeError):
                            image_data['captured_at'] = None
                            
                    processed_images.append(image_data)
                
                # Report any download errors
                if download_errors:
                    print("\nDownload Errors:")
                    for error in download_errors:
                        print(error)
                
                # Create new DataFrame with processed images
                if processed_images:
                    new_images = pd.DataFrame(processed_images)
                    
                    # Remove columns not in schema
                    schema_columns = [
                        'name', 'mly_id', 'altitude', 'camera_type', 'camera_parameters',
                        'captured_at', 'compass_angle', 'computed_compass_angle',
                        'computed_geometry', 'exif_orientation', 'image_url', 'thumb_url',
                        'geometry'
                    ]
                    extra_columns = [col for col in new_images.columns if col not in schema_columns]
                    if extra_columns:
                        new_images = new_images.drop(columns=extra_columns)
                        
                    print(f"\nSuccessfully processed {len(processed_images)} images")
                    
                    # Ensure GeoDataFrame for database operations
                    if not isinstance(new_images, gpd.GeoDataFrame):
                        new_images = gpd.GeoDataFrame(new_images, geometry='geometry')
                        new_images.set_crs(epsg=4326, inplace=True)
                    
                    return new_images
            else:
                print("No new images to download")
                return None
        else:
            print("No Mapillary images found in the specified area")
            return None
        
    except Exception as e:
        print(f"Error fetching Mapillary images: {str(e)}")
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
        db_con = Postgres(os.environ.get("DATABASE_URL"))
        table_name = os.environ.get("DB_TABLE")
        
        # Ensure table schema
        ensure_table_schema(db_con, table_name)
        
        # Convert GeoDataFrame to PostGIS format
        if isinstance(images, gpd.GeoDataFrame):
            # Prepare data for database
            images = prepare_data_for_db(images)
            
            # Make sure we have all required columns
            required_columns = ['name', 'altitude', 'camera_type', 'captured_at', 
                              'compass_angle', 'image_url', 'thumb_url', 'geometry']
            for col in required_columns:
                if col not in images.columns:
                    images[col] = None
            
            # Convert to PostGIS
            images.to_postgis(
                table_name,
                db_con.engine,
                if_exists='append',
                index=False,
                dtype={
                    'name': String,
                    'mly_id': String,
                    'altitude': Float,
                    'camera_type': String,
                    'captured_at': DateTime(timezone=True),
                    'compass_angle': Float,
                    'computed_compass_angle': Float,
                    'exif_orientation': Integer,
                    'image_url': String,
                    'thumb_url': String
                }
            )
            print(f"Successfully saved {len(images)} new images to PostgreSQL")
        
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
    
    # Test local image loading and visualization
    local_images = test_local_images()
    
    # Test Mapillary image loading and downloading
    mapillary_images = test_mapillary_images()
    
    # Test road network snapping
    if local_images is not None:
        test_road_network_snapping(local_images)
    
    # Test road network snapping with Mapillary images if available
    if mapillary_images is not None and len(mapillary_images) > 0:
        print("\nTesting road network snapping with Mapillary images...")
        test_road_network_snapping(mapillary_images)
    
    # Test database operations with local images
    if local_images is not None:
        test_database_operations(local_images)
    
    # Test database operations with Mapillary images if available
    if mapillary_images is not None and len(mapillary_images) > 0:
        print("\nTesting database operations with Mapillary images...")
        test_database_operations(mapillary_images)

if __name__ == "__main__":
    main() 