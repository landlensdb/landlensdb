"""
Image anonymization module for blurring faces and license plates.

This module provides functionality to detect and blur privacy-sensitive
information (faces and license plates) in street-level imagery using
the EgoBlur library from Meta.
"""

import os
import warnings
from typing import Optional, List, Union

import numpy as np
from PIL import Image
from tqdm import tqdm


# Lazy import flag for optional dependencies
_EGOBLUR_AVAILABLE = None


def _check_egoblur_available():
    """Check if egoblur and its dependencies are available.
    
    Returns:
        bool: True if egoblur is available, False otherwise.
    """
    global _EGOBLUR_AVAILABLE
    if _EGOBLUR_AVAILABLE is None:
        try:
            import torch
            import cv2
            _EGOBLUR_AVAILABLE = True
        except ImportError:
            _EGOBLUR_AVAILABLE = False
    return _EGOBLUR_AVAILABLE


def _get_device() -> str:
    """Auto-detect the best available device for inference.
    
    Returns:
        str: Device string ('cuda:0' or 'cpu').
    """
    import torch
    return "cuda:0" if torch.cuda.is_available() else "cpu"


class Anonymizer:
    """
    A class to anonymize images by blurring faces and license plates.
    
    This class uses the EgoBlur library from Meta for detection and blurring.
    Requires optional dependencies: pip install landlensdb[anonymize]
    
    Attributes:
        face_model_path (str): Path to the face detection model.
        lp_model_path (str): Path to the license plate detection model.
        device (str): Device to run inference on ('cpu' or 'cuda:X').
    
    Example:
        >>> from landlensdb.process.anonymize import Anonymizer
        >>> anonymizer = Anonymizer(
        ...     face_model_path="/path/to/ego_blur_face.jit",
        ...     lp_model_path="/path/to/ego_blur_lp.jit"
        ... )
        >>> anonymizer.anonymize_image("input.jpg", "output.jpg")
    """
    
    def __init__(
        self,
        face_model_path: Optional[str] = None,
        lp_model_path: Optional[str] = None,
        face_score_threshold: float = 0.5,
        lp_score_threshold: float = 0.5,
        nms_iou_threshold: float = 0.3,
        scale_factor: float = 1.1,
        device: Optional[str] = None,
    ):
        """
        Initialize the Anonymizer.
        
        Args:
            face_model_path: Path to face detection model (.jit file).
            lp_model_path: Path to license plate detection model (.jit file).
            face_score_threshold: Confidence threshold for face detection (0.0-1.0).
            lp_score_threshold: Confidence threshold for license plate detection (0.0-1.0).
            nms_iou_threshold: IoU threshold for non-maximum suppression.
            scale_factor: Factor to scale detection boxes (>1.0 for larger blur area).
            device: Device for inference ('cpu', 'cuda:0', etc.). 
                If None, auto-detects.
        
        Raises:
            ImportError: If required dependencies are not installed.
            ValueError: If neither face_model_path nor lp_model_path is provided.
        """
        if not _check_egoblur_available():
            raise ImportError(
                "Anonymization requires additional dependencies. "
                "Install with: pip install landlensdb[anonymize]"
            )
        
        if face_model_path is None and lp_model_path is None:
            raise ValueError(
                "At least one of face_model_path or lp_model_path must be provided."
            )
        
        self.face_model_path = face_model_path
        self.lp_model_path = lp_model_path
        self.face_score_threshold = face_score_threshold
        self.lp_score_threshold = lp_score_threshold
        self.nms_iou_threshold = nms_iou_threshold
        self.scale_factor = scale_factor
        self.device = device or _get_device()
        
        self._face_model = None
        self._lp_model = None
        self._models_loaded = False
    
    def _load_models(self):
        """Lazy-load detection models."""
        if self._models_loaded:
            return
        
        import torch
        
        if self.face_model_path is not None:
            if not os.path.exists(self.face_model_path):
                raise FileNotFoundError(
                    f"Face model not found: {self.face_model_path}"
                )
            self._face_model = torch.jit.load(
                self.face_model_path, map_location=self.device
            )
            self._face_model.eval()
        
        if self.lp_model_path is not None:
            if not os.path.exists(self.lp_model_path):
                raise FileNotFoundError(
                    f"License plate model not found: {self.lp_model_path}"
                )
            self._lp_model = torch.jit.load(
                self.lp_model_path, map_location=self.device
            )
            self._lp_model.eval()
        
        self._models_loaded = True
    
    def _detect_and_blur(self, image: np.ndarray) -> np.ndarray:
        """Detect faces and license plates, then apply blur.
        
        Args:
            image: Input image as numpy array (BGR format).
        
        Returns:
            Blurred image as numpy array.
        """
        import cv2
        import torch
        
        self._load_models()
        
        # Convert to tensor
        image_tensor = torch.from_numpy(
            image.transpose(2, 0, 1)
        ).to(self.device).float()
        
        all_boxes = []
        
        # Detect faces
        if self._face_model is not None:
            with torch.no_grad():
                face_boxes = self._run_detection(
                    image_tensor, self._face_model, self.face_score_threshold
                )
                all_boxes.extend(face_boxes)
        
        # Detect license plates
        if self._lp_model is not None:
            with torch.no_grad():
                lp_boxes = self._run_detection(
                    image_tensor, self._lp_model, self.lp_score_threshold
                )
                all_boxes.extend(lp_boxes)
        
        # Apply blur to detected regions
        result = image.copy()
        h, w = image.shape[:2]
        
        for box in all_boxes:
            x1, y1, x2, y2 = self._scale_box(box, w, h)
            x1, y1 = max(0, int(x1)), max(0, int(y1))
            x2, y2 = min(w, int(x2)), min(h, int(y2))
            
            if x2 > x1 and y2 > y1:
                roi = result[y1:y2, x1:x2]
                # Apply strong Gaussian blur
                blur_size = max(51, ((x2 - x1) // 4) * 2 + 1)
                blurred_roi = cv2.GaussianBlur(roi, (blur_size, blur_size), 0)
                result[y1:y2, x1:x2] = blurred_roi
        
        return result
    
    def _run_detection(self, image_tensor, model, score_threshold) -> List[List[float]]:
        """Run detection model and return bounding boxes.
        
        Args:
            image_tensor: Input image tensor.
            model: Detection model.
            score_threshold: Confidence threshold.
        
        Returns:
            List of bounding boxes [x1, y1, x2, y2].
        """
        import torch
        import torchvision
        
        # Run inference
        with torch.no_grad():
            # Add batch dimension if needed
            if image_tensor.dim() == 3:
                image_tensor = image_tensor.unsqueeze(0)
            
            outputs = model(image_tensor)
        
        # Parse outputs - handle different model output formats
        boxes = []
        
        if isinstance(outputs, (list, tuple)):
            # Handle tuple/list outputs (common for detection models)
            if len(outputs) >= 2:
                pred_boxes = outputs[0]
                pred_scores = outputs[1] if len(outputs) > 1 else None
                
                if pred_boxes is not None and pred_boxes.numel() > 0:
                    # Flatten if needed
                    if pred_boxes.dim() > 2:
                        pred_boxes = pred_boxes.squeeze(0)
                    if pred_scores is not None and pred_scores.dim() > 1:
                        pred_scores = pred_scores.squeeze(0)
                    
                    # Apply NMS
                    if pred_scores is not None and pred_scores.numel() > 0:
                        keep = torchvision.ops.nms(
                            pred_boxes, pred_scores, self.nms_iou_threshold
                        )
                        pred_boxes = pred_boxes[keep]
                        pred_scores = pred_scores[keep]
                        
                        # Filter by score threshold
                        mask = pred_scores > score_threshold
                        pred_boxes = pred_boxes[mask]
                    
                    boxes = pred_boxes.cpu().numpy().tolist()
        
        elif isinstance(outputs, dict):
            # Handle dict outputs
            if 'boxes' in outputs:
                pred_boxes = outputs['boxes']
                pred_scores = outputs.get('scores', None)
                
                if pred_scores is not None:
                    mask = pred_scores > score_threshold
                    pred_boxes = pred_boxes[mask]
                
                boxes = pred_boxes.cpu().numpy().tolist()
        
        return boxes
    
    def _scale_box(
        self, box: List[float], max_width: int, max_height: int
    ) -> List[float]:
        """Scale a bounding box by the scale factor.
        
        Args:
            box: Bounding box [x1, y1, x2, y2].
            max_width: Maximum width (image width).
            max_height: Maximum height (image height).
        
        Returns:
            Scaled bounding box.
        """
        x1, y1, x2, y2 = box
        w = x2 - x1
        h = y2 - y1
        
        xc = x1 + w / 2
        yc = y1 + h / 2
        
        w = self.scale_factor * w
        h = self.scale_factor * h
        
        x1 = max(xc - w / 2, 0)
        y1 = max(yc - h / 2, 0)
        x2 = min(xc + w / 2, max_width)
        y2 = min(yc + h / 2, max_height)
        
        return [x1, y1, x2, y2]
    
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
                    output_path = input_path
                else:
                    # Preserve directory structure
                    rel_path = os.path.relpath(input_path, input_dir)
                    output_path = os.path.join(output_dir, rel_path)
                
                result_path = self.anonymize_image(input_path, output_path)
                output_paths.append(result_path)
                
            except Exception as e:
                warnings.warn(f"Error processing {input_path}: {str(e)}")
        
        return output_paths


def anonymize_images(
    input_path: str,
    output_path: Optional[str] = None,
    face_model_path: Optional[str] = None,
    lp_model_path: Optional[str] = None,
    **kwargs
) -> Union[str, List[str]]:
    """
    Convenience function to anonymize images.
    
    Args:
        input_path: Path to image or directory.
        output_path: Path for output. If None, overwrites input.
        face_model_path: Path to face detection model.
        lp_model_path: Path to license plate detection model.
        **kwargs: Additional arguments passed to Anonymizer.
    
    Returns:
        Path to anonymized output (str for single image, list for directory).
    
    Example:
        >>> from landlensdb.process.anonymize import anonymize_images
        >>> anonymize_images(
        ...     "/path/to/streetview/",
        ...     "/path/to/output/",
        ...     face_model_path="/path/to/face_model.jit",
        ...     lp_model_path="/path/to/lp_model.jit"
        ... )
    """
    anonymizer = Anonymizer(
        face_model_path=face_model_path,
        lp_model_path=lp_model_path,
        **kwargs
    )
    
    if os.path.isfile(input_path):
        return anonymizer.anonymize_image(input_path, output_path)
    else:
        return anonymizer.anonymize_directory(input_path, output_path)
