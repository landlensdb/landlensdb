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

def get_existing_mapillary_ids(db_con, table_name):
    """Get existing Mapillary IDs from the database."""
    try:
        query = text("SELECT mly_id FROM mapillary_images WHERE mly_id IS NOT NULL")
        existing_ids = pd.read_sql(query, db_con.engine)
        return set(existing_ids['mly_id']) if not existing_ids.empty else set()
    except Exception as e:
        print(f"Error fetching existing Mapillary IDs: {str(e)}")
        return set()

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
        
        # Get existing Mapillary IDs from database
        existing_ids = get_existing_mapillary_ids(db_con, table_name)
        print(f"Found {len(existing_ids)} existing Mapillary images in database")
        
        # Load images from Mapillary
        fields = ["id", "altitude", "captured_at", "camera_type", "thumb_1024_url",
                 "compass_angle", "computed_compass_angle", "computed_geometry", "geometry"]
        all_images = handler.fetch_within_bbox(bbox, fields=fields)
        
        if len(all_images) > 0:
            # Filter out existing images
            new_images = all_images[~all_images['mly_id'].isin(existing_ids)]
            print(f"Found {len(all_images)} total Mapillary images")
            print(f"Of which {len(new_images)} are new images")
            
            if len(new_images) > 0:
                # Prepare data for database
                new_images = prepare_data_for_db(new_images, create_thumbnails=False)
                new_images['thumb_url'] = new_images['image_url']  # Use original URLs for Mapillary
                
                print("\nSample of new Mapillary data:")
                print(new_images[['altitude', 'image_url', 'geometry']].head())
                
                # Test image download only for new images
                print("\nTesting image download...")
                download_dir = os.getenv('DOWNLOAD_DIR')
                if not os.path.exists(download_dir):
                    os.makedirs(download_dir)
                
                # Download first new image if not already downloaded
                first_image = new_images.iloc[0]
                image_path = os.path.join(download_dir, f"mly_{first_image['mly_id']}.jpg")
                if not os.path.exists(image_path):
                    response = requests.get(first_image['image_url'])
                    if response.status_code == 200:
                        with open(image_path, 'wb') as f:
                            f.write(response.content)
                        print("Successfully downloaded test image")
                    else:
                        print("Failed to download test image")
                else:
                    print("Test image already exists")
                
                # Return only new images for database operations
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
    
    # Test database operations with local images
    if local_images is not None:
        test_database_operations(local_images)
    
    # Test database operations with Mapillary images if available
    if mapillary_images is not None and len(mapillary_images) > 0:
        print("\nTesting database operations with Mapillary images...")
        test_database_operations(mapillary_images)

if __name__ == "__main__":
    main() 