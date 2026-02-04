"""
Image anonymization module for blurring faces and license plates.

This module provides functionality to detect and blur privacy-sensitive
information (faces and license plates) in street-level imagery using
YOLOv8 model fine-tuned on dashcam data.

Based on: https://github.com/varungupta31/dashcam_anonymizer
"""

import os
import warnings
from pathlib import Path
from typing import Optional, List, Union

import numpy as np
from tqdm import tqdm


# Lazy import flag for optional dependencies
_YOLO_AVAILABLE = None

# Default model filenames
DEFAULT_MODEL_NAME = "dashcam_anonymizer.pt"

# Model download info
MODEL_DOWNLOAD_URL = "https://github.com/varungupta31/dashcam_anonymizer"
MODEL_GDOWN_ID = "1uV8IMuGDbmDabdjyeSy4SUKV9OS-ULbe"


def _get_model_search_paths() -> List[Path]:
    """Get list of directories to search for models.
    
    Returns:
        List of Path objects to search for models (deduplicated).
    """
    paths = []
    seen = set()
    
    def add_path(p: Path):
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            paths.append(p)
    
    # 1. User's home directory
    add_path(Path.home() / ".landlensdb" / "models")
    
    # 2. Current working directory / models
    add_path(Path.cwd() / "models")
    
    # 3. Package directory / models (if running from landlensdb repo)
    package_dir = Path(__file__).parent.parent.parent
    add_path(package_dir / "models")
    
    return paths


def _check_yolo_available():
    """Check if YOLO and its dependencies are available.

    Returns:
        bool: True if YOLO is available, False otherwise.
    """
    global _YOLO_AVAILABLE
    if _YOLO_AVAILABLE is None:
        try:
            from ultralytics import YOLO
            import cv2
            _YOLO_AVAILABLE = True
        except ImportError:
            _YOLO_AVAILABLE = False
    return _YOLO_AVAILABLE


def _get_device() -> str:
    """Auto-detect the best available device for inference.

    Returns:
        str: Device string ('cuda:0' or 'cpu').
    """
    try:
        import torch
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def get_default_model_path() -> Optional[str]:
    """Get the default model path by searching common locations.

    Searches for models in the following order:
    1. ~/.landlensdb/models/
    2. ./models/
    3. <package_dir>/models/

    Returns:
        Path to the model if found, None otherwise.
    """
    # Search in all possible locations
    for search_path in _get_model_search_paths():
        model_path = search_path / DEFAULT_MODEL_NAME
        if model_path.exists():
            return str(model_path)
    
    return None


def list_found_models() -> dict:
    """List all found model files in search paths.
    
    Returns:
        Dictionary with model info and search paths.
    """
    return {
        "model": get_default_model_path(),
        "search_paths": [str(p) for p in _get_model_search_paths()],
    }


def download_model(output_dir: Optional[str] = None) -> str:
    """Download the dashcam_anonymizer model using gdown.
    
    Args:
        output_dir: Directory to save the model. If None, uses first search path.
    
    Returns:
        Path to the downloaded model.
    
    Raises:
        ImportError: If gdown is not installed.
        RuntimeError: If download fails.
    """
    try:
        import gdown
    except ImportError:
        raise ImportError(
            "gdown is required to download the model. "
            "Install with: pip install gdown"
        )
    
    if output_dir is None:
        output_dir = _get_model_search_paths()[0]
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / DEFAULT_MODEL_NAME
    
    print(f"Downloading model to {output_path}...")
    gdown.download(id=MODEL_GDOWN_ID, output=str(output_path), quiet=False)
    
    if not output_path.exists():
        raise RuntimeError("Model download failed.")
    
    print(f"Model downloaded successfully: {output_path}")
    return str(output_path)


def download_models_instructions() -> str:
    """Return instructions for downloading the model.

    Returns:
        str: Instructions for downloading models.
    """
    search_paths = _get_model_search_paths()
    paths_str = "\n   ".join([f"- {p}" for p in search_paths])
    
    return f"""
Anonymization model is required.

Option 1: Automatic download (recommended)
    from landlensdb.process.anonymize import download_model
    download_model()

Option 2: Manual download
    1. Visit: {MODEL_DOWNLOAD_URL}
    2. Download the model (best.pt) and rename to {DEFAULT_MODEL_NAME}
    3. Place in one of these locations:
       {paths_str}

Option 3: Specify custom path
    from landlensdb.process.anonymize import Anonymizer
    anonymizer = Anonymizer(model_path="/your/path/to/{DEFAULT_MODEL_NAME}")
"""


def setup_model_directory(path: Optional[Path] = None) -> Path:
    """Create a model directory if it doesn't exist.
    
    Args:
        path: Path to create. If None, uses the first search path.
    
    Returns:
        Path to the created directory.
    """
    if path is None:
        path = _get_model_search_paths()[0]
    path.mkdir(parents=True, exist_ok=True)
    return path


class Anonymizer:
    """
    A class to anonymize images by blurring faces and license plates.

    This class uses YOLOv8 model fine-tuned on dashcam data for fast detection.
    Requires optional dependencies: pip install landlensdb[anonymize]

    Attributes:
        model_path (str): Path to the YOLO model.
        device (str): Device to run inference on ('cpu' or 'cuda:X').

    Example:
        >>> from landlensdb.process.anonymize import Anonymizer
        >>> anonymizer = Anonymizer()  # Uses default model
        >>> anonymizer.anonymize_image("input.jpg", "output.jpg")
        
        >>> # Or with custom model path
        >>> anonymizer = Anonymizer(model_path="/path/to/model.pt")
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        confidence_threshold: float = 0.25,
        blur_radius: int = 51,
        device: Optional[str] = None,
        auto_download: bool = True,
    ):
        """
        Initialize the Anonymizer.

        Args:
            model_path: Path to YOLO model (.pt file).
                If None, will search for model in default locations.
            confidence_threshold: Confidence threshold for detection (0.0-1.0).
            blur_radius: Radius for Gaussian blur (must be odd number).
            device: Device for inference ('cpu', 'cuda:0', etc.).
                If None, auto-detects.
            auto_download: If True and model not found, attempt to download it.

        Raises:
            ImportError: If required dependencies are not installed.
            ValueError: If model is not found and auto_download fails.
        """
        if not _check_yolo_available():
            raise ImportError(
                "Anonymization requires additional dependencies. "
                "Install with: pip install landlensdb[anonymize]"
            )
        
        # Try to find model in default location if not provided
        if model_path is None:
            model_path = get_default_model_path()
        
        # Auto-download if not found
        if model_path is None and auto_download:
            try:
                print("Model not found. Attempting to download...")
                model_path = download_model()
            except Exception as e:
                print(f"Auto-download failed: {e}")
                print(download_models_instructions())
                raise ValueError(
                    "Model not found and auto-download failed. "
                    "Please download the model manually."
                )
        
        if model_path is None:
            print(download_models_instructions())
            raise ValueError(
                "No model found. Please download the model or provide a path."
            )
        
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")

        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.blur_radius = blur_radius if blur_radius % 2 == 1 else blur_radius + 1
        self.device = device or _get_device()
        
        self._model = None

    def _load_model(self):
        """Lazy-load the YOLO model."""
        if self._model is None:
            from ultralytics import YOLO
            self._model = YOLO(self.model_path)
        return self._model

    def _detect_and_blur(self, image: np.ndarray) -> np.ndarray:
        """Detect faces and license plates, then apply blur.

        Args:
            image: Input image as numpy array (BGR format).

        Returns:
            Blurred image as numpy array.
        """
        import cv2
        
        model = self._load_model()
        
        # Run detection
        results = model(
            image,
            conf=self.confidence_threshold,
            device=self.device,
            verbose=False
        )
        
        # Apply blur to detected regions
        result_image = image.copy()
        
        for result in results:
            if result.boxes is not None:
                for box in result.boxes:
                    # Get bounding box coordinates
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                    
                    # Ensure coordinates are within image bounds
                    h, w = image.shape[:2]
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)
                    
                    if x2 > x1 and y2 > y1:
                        # Extract ROI and apply blur
                        roi = result_image[y1:y2, x1:x2]
                        blurred_roi = cv2.GaussianBlur(
                            roi, 
                            (self.blur_radius, self.blur_radius), 
                            0
                        )
                        result_image[y1:y2, x1:x2] = blurred_roi
        
        return result_image

    def anonymize_image(
        self,
        input_path: str,
        output_path: Optional[str] = None,
    ) -> str:
        """
        Anonymize a single image by blurring faces and license plates.

        Args:
            input_path: Path to the input image.
            output_path: Path to save the anonymized image.
                If None, overwrites the input image.

        Returns:
            Path to the anonymized image.

        Raises:
            FileNotFoundError: If input image doesn't exist.
            ValueError: If image cannot be processed.
        """
        import cv2

        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Input image not found: {input_path}")

        if output_path is None:
            output_path = input_path

        # Read image
        image = cv2.imread(input_path)
        if image is None:
            raise ValueError(f"Could not read image: {input_path}")

        # Detect and blur
        result = self._detect_and_blur(image)

        # Ensure output directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        # Save result
        cv2.imwrite(output_path, result)

        return output_path

    def anonymize_directory(
        self,
        input_dir: str,
        output_dir: Optional[str] = None,
        recursive: bool = False,
        show_progress: bool = True,
    ) -> List[str]:
        """
        Anonymize all images in a directory.

        Args:
            input_dir: Path to directory containing images.
            output_dir: Path to save anonymized images.
                If None, overwrites original images.
            recursive: Whether to process subdirectories.
            show_progress: Whether to show progress bar.

        Returns:
            List of paths to anonymized images.
        """
        if not os.path.exists(input_dir):
            raise FileNotFoundError(f"Input directory not found: {input_dir}")

        # Collect image files
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'}
        image_files = []

        if recursive:
            for root, dirs, files in os.walk(input_dir):
                # Skip thumbnails directory
                if 'thumbnails' in dirs:
                    dirs.remove('thumbnails')
                for file in files:
                    if os.path.splitext(file.lower())[1] in image_extensions:
                        image_files.append(os.path.join(root, file))
        else:
            for file in os.listdir(input_dir):
                if os.path.splitext(file.lower())[1] in image_extensions:
                    image_files.append(os.path.join(input_dir, file))

        if not image_files:
            warnings.warn(f"No image files found in {input_dir}")
            return []

        # Process images
        output_paths = []
        iterator = tqdm(image_files, desc="Anonymizing images") if show_progress else image_files

        for input_path in iterator:
            try:
                if output_dir is None:
                    out_path = input_path
                else:
                    # Preserve directory structure
                    rel_path = os.path.relpath(input_path, input_dir)
                    out_path = os.path.join(output_dir, rel_path)

                result_path = self.anonymize_image(input_path, out_path)
                output_paths.append(result_path)

            except Exception as e:
                warnings.warn(f"Error processing {input_path}: {str(e)}")

        return output_paths


def anonymize_images(
    input_path: str,
    output_path: Optional[str] = None,
    model_path: Optional[str] = None,
    **kwargs
) -> Union[str, List[str]]:
    """
    Convenience function to anonymize images.

    Args:
        input_path: Path to image or directory.
        output_path: Path for output. If None, overwrites input.
        model_path: Path to YOLO model. If None, uses default.
        **kwargs: Additional arguments passed to Anonymizer.

    Returns:
        Path to anonymized output (str for single image, list for directory).

    Example:
        >>> from landlensdb.process.anonymize import anonymize_images
        >>> anonymize_images("/path/to/streetview/", "/path/to/output/")
    """
    anonymizer = Anonymizer(model_path=model_path, **kwargs)

    if os.path.isfile(input_path):
        return anonymizer.anonymize_image(input_path, output_path)
    else:
        return anonymizer.anonymize_directory(input_path, output_path)
