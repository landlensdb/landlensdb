import numpy as np
import cv2


def equirectangular_to_perspective(img, fov, theta, phi, width, height):
    """
    Converts an equirectangular 360° image to a planar perspective image.

    Parameters:
        img: Input equirectangular image (H x W x 3).
        fov: Field of view of the output image in degrees.
        theta: Horizontal angle (yaw) in degrees.
        phi: Vertical angle (pitch) in degrees.
        width: Width of the output image.
        height: Height of the output image.

    Returns:
        Perspective-projected planar image.
    """
    h, w, _ = img.shape

    # Convert angles to radians
    fov_rad = np.radians(fov)
    theta_rad = np.radians(theta)
    phi_rad = np.radians(phi)

    # Generate a grid of pixel coordinates in the output image
    x = np.linspace(-1, 1, width) * np.tan(fov_rad / 2)
    y = np.linspace(-1, 1, height) * np.tan(fov_rad / 2)
    x, y = np.meshgrid(x, y)

    # Calculate the z-coordinate for the field of view
    z = np.ones_like(x)

    # Normalize the grid to unit vectors (Cartesian coordinates in the camera space)
    norm = np.sqrt(x ** 2 + y ** 2 + z ** 2)
    x /= norm
    y /= norm
    z /= norm

    x_rot = x * np.cos(theta_rad) - z * np.sin(theta_rad)
    z_rot = x * np.sin(theta_rad) + z * np.cos(theta_rad)
    y_rot = y * np.cos(phi_rad) - z_rot * np.sin(phi_rad)
    z_rot = y * np.sin(phi_rad) + z_rot * np.cos(phi_rad)

    lon = np.arctan2(x_rot, z_rot)  # Longitude
    lat = np.arcsin(y_rot)  # Latitude

    lon_pixel = (lon + np.pi) / (2 * np.pi) * w
    lat_pixel = (lat + np.pi / 2) / np.pi * h

    lon_pixel = lon_pixel.astype(np.float32)
    lat_pixel = lat_pixel.astype(np.float32)
    perspective_img = cv2.remap(
        img, lon_pixel, lat_pixel,
        interpolation=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_WRAP
    )

    return perspective_img
