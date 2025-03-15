import json
import math
import os

import mapbox_vector_tile
import requests
from dotenv import load_dotenv
from shapely.geometry import Point, shape


def lon_to_tile_x(lon_deg, zoom):
    """Convert longitude to tile X coordinate"""
    n = 2.0 ** zoom
    return int((lon_deg + 180.0) / 360.0 * n)

def lat_to_tile_y(lat_deg, zoom):
    """Convert latitude to tile Y coordinate"""
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    return int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)

def bbox_to_tiles(bbox, zoom):
    """Convert a bounding box to tile coordinates"""
    west, south, east, north = bbox
    min_x = lon_to_tile_x(west, zoom)
    max_x = lon_to_tile_x(east, zoom)
    min_y = lat_to_tile_y(north, zoom)  # Note: y coordinates are inverted
    max_y = lat_to_tile_y(south, zoom)
    return min_x, min_y, max_x, max_y

def tile_to_bbox(x, y, zoom):
    """Convert tile coordinates to a bounding box"""
    n = 2.0 ** zoom
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0

    def inv_lat(y_tile):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y_tile / n))))

    north = inv_lat(y)
    south = inv_lat(y + 1)

    return [west, south, east, north]

def fetch_coverage_tile(token, zoom, x, y):
    """Fetch a single coverage tile"""
    url = f"https://tiles.mapillary.com/maps/vtp/mly1_public/2/{zoom}/{x}/{y}?access_token={token}"
    print(f"Fetching tile: {url}")

    try:
        response = requests.get(url)
        if response.status_code == 200:
            print(f"Success! Content type: {response.headers.get('content-type')}")
            # Vector tiles are binary, not JSON
            if 'application/x-protobuf' in response.headers.get('content-type', ''):
                print("Received vector tile data (binary)")
                try:
                    # Decode the vector tile
                    tile_data = mapbox_vector_tile.decode(response.content)

                    # Check for image layer at zoom level 14
                    if 'image' in tile_data and zoom == 14:
                        features = tile_data['image']['features']
                        print(f"Found {len(features)} image features in tile")

                        # Print a sample of the first few features
                        if features:
                            print("\nSample image features:")
                            for i, feature in enumerate(features[:3]):
                                print(f"Feature {i+1}:")
                                print(f"  ID: {feature['properties'].get('id')}")
                                print(f"  Captured at: {feature['properties'].get('captured_at')}")
                                print(f"  Sequence ID: {feature['properties'].get('sequence_id')}")

                        return {
                            'success': True,
                            'is_vector_tile': True,
                            'features': features,
                            'size': len(response.content)
                        }

                    # Check for sequence layer at zoom levels 6-14
                    elif 'sequence' in tile_data and 6 <= zoom <= 14:
                        features = tile_data['sequence']['features']
                        print(f"Found {len(features)} sequence features in tile")

                        # Print a sample of the first few features
                        if features:
                            print("\nSample sequence features:")
                            for i, feature in enumerate(features[:3]):
                                print(f"Feature {i+1}:")
                                print(f"  ID: {feature['properties'].get('id')}")
                                print(f"  Image ID: {feature['properties'].get('image_id')}")

                        return {
                            'success': True,
                            'is_vector_tile': True,
                            'features': features,
                            'size': len(response.content)
                        }

                    # Check for overview layer at zoom levels 0-5
                    elif 'overview' in tile_data and 0 <= zoom <= 5:
                        features = tile_data['overview']['features']
                        print(f"Found {len(features)} overview features in tile")

                        return {
                            'success': True,
                            'is_vector_tile': True,
                            'features': features,
                            'size': len(response.content)
                        }

                    else:
                        print(f"Available layers in tile: {list(tile_data.keys())}")
                        return {
                            'success': True,
                            'is_vector_tile': True,
                            'layers': list(tile_data.keys()),
                            'size': len(response.content)
                        }

                except Exception as e:
                    print(f"Error decoding vector tile: {str(e)}")
                    return {
                        'success': True,
                        'is_vector_tile': True,
                        'error_decoding': str(e),
                        'size': len(response.content)
                    }
            else:
                return {'success': True, 'data': response.json()}
        else:
            print(f"Error: {response.status_code}")
            print(f"Response: {response.text}")
            return {'success': False, 'error': response.text}
    except Exception as e:
        print(f"Exception: {str(e)}")
        return {'success': False, 'error': str(e)}

def fetch_image_metadata(token, image_id):
    """Fetch metadata for a specific image"""
    url = f"https://graph.mapillary.com/{image_id}?access_token={token}&fields=id,captured_at,compass_angle,geometry"
    print(f"Fetching image metadata: {url}")

    try:
        response = requests.get(url)
        if response.status_code == 200:
            return {'success': True, 'data': response.json()}
        else:
            print(f"Error: {response.status_code}")
            print(f"Response: {response.text}")
            return {'success': False, 'error': response.text}
    except Exception as e:
        print(f"Exception: {str(e)}")
        return {'success': False, 'error': str(e)}

def extract_image_ids_from_tile(tile_result):
    """Extract image IDs from a tile result"""
    image_ids = []

    if tile_result.get('success') and tile_result.get('is_vector_tile'):
        features = tile_result.get('features', [])

        for feature in features:
            if 'id' in feature.get('properties', {}):
                image_ids.append(str(feature['properties']['id']))

    return image_ids

def main():
    # Load environment variables
    load_dotenv()
    token = os.environ.get("MLY_TOKEN")

    if not token:
        print("Error: MLY_TOKEN environment variable not set")
        return

    # Test area (Tokyo, Shibuya)
    bbox = [139.69, 35.65, 139.71, 35.67]
    zoom = 14

    print(f"Testing area: {bbox} (approximately 2km x 2km in Tokyo)")
    print(f"Using zoom level: {zoom}")

    # Convert bbox to tiles
    min_x, min_y, max_x, max_y = bbox_to_tiles(bbox, zoom)
    print(f"Tile coordinates: X: {min_x}-{max_x}, Y: {min_y}-{max_y}")

    # Limit to a small area for testing
    max_tiles = 2
    tile_count = 0
    all_image_ids = []

    # Try to fetch a few tiles
    for x in range(min_x, min_x + 2):
        for y in range(min_y, min_y + 2):
            if tile_count >= max_tiles:
                break

            print(f"\nTesting tile {x},{y}:")
            tile_bbox = tile_to_bbox(x, y, zoom)
            print(f"Tile covers area: {tile_bbox}")

            result = fetch_coverage_tile(token, zoom, x, y)
            if result['success'] and result.get('is_vector_tile'):
                print(f"Successfully received vector tile data of size {result['size']} bytes")

                # Extract image IDs from the tile
                image_ids = extract_image_ids_from_tile(result)
                print(f"Found {len(image_ids)} image IDs in tile")
                all_image_ids.extend(image_ids[:5])  # Add up to 5 image IDs from each tile

            tile_count += 1

    # Test fetching image metadata directly for a few images
    if all_image_ids:
        print("\nTesting direct image metadata fetch for discovered images:")
        for i, image_id in enumerate(all_image_ids[:3]):  # Test up to 3 images
            print(f"\nImage {i+1} (ID: {image_id}):")
            image_result = fetch_image_metadata(token, image_id)
            if image_result['success']:
                print(f"Image metadata: {json.dumps(image_result['data'], indent=2)}")
    else:
        print("\nNo image IDs found in tiles to test direct metadata fetch")

if __name__ == "__main__":
    main()
