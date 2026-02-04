"""
Tests for the anonymize module.

Note: These tests require optional dependencies (ultralytics, opencv-python).
Run with: pip install landlensdb[anonymize]
"""

import os
import pytest
import warnings

# Check if anonymize dependencies are available
try:
    from ultralytics import YOLO
    import cv2
    ANONYMIZE_AVAILABLE = True
except ImportError:
    ANONYMIZE_AVAILABLE = False


@pytest.mark.skipif(not ANONYMIZE_AVAILABLE, reason="Anonymize dependencies not installed")
class TestAnonymizer:
    """Tests for the Anonymizer class."""
    
    def test_import_anonymizer(self):
        """Test that Anonymizer can be imported."""
        from landlensdb.process.anonymize import Anonymizer
        assert Anonymizer is not None
    
    def test_import_anonymize_images(self):
        """Test that anonymize_images function can be imported."""
        from landlensdb.process.anonymize import anonymize_images
        assert anonymize_images is not None
    
    def test_get_default_model_path(self):
        """Test get_default_model_path function."""
        from landlensdb.process.anonymize import get_default_model_path
        
        # May return None if model not installed
        result = get_default_model_path()
        assert result is None or os.path.exists(result)
    
    def test_list_found_models(self):
        """Test list_found_models function."""
        from landlensdb.process.anonymize import list_found_models
        
        result = list_found_models()
        assert "model" in result
        assert "search_paths" in result
        assert isinstance(result["search_paths"], list)
    
    def test_check_dependencies(self):
        """Test dependency checking function."""
        from landlensdb.process.anonymize import _check_yolo_available
        
        result = _check_yolo_available()
        assert result == ANONYMIZE_AVAILABLE
    
    def test_get_device(self):
        """Test device detection."""
        from landlensdb.process.anonymize import _get_device
        
        device = _get_device()
        assert device in ["cpu", "cuda:0"]


class TestAnonymizerIntegration:
    """Integration tests that require model files."""
    
    @pytest.mark.skipif(not ANONYMIZE_AVAILABLE, reason="Anonymize dependencies not installed")
    def test_anonymize_image_with_model(self, tmp_path):
        """Test anonymize_image if model is available."""
        from landlensdb.process.anonymize import Anonymizer, get_default_model_path
        import numpy as np
        
        model_path = get_default_model_path()
        if model_path is None:
            pytest.skip("Model not available")
        
        # Create a dummy image
        dummy_image = np.zeros((100, 100, 3), dtype=np.uint8)
        image_path = tmp_path / "test_image.jpg"
        cv2.imwrite(str(image_path), dummy_image)
        
        anonymizer = Anonymizer(model_path=model_path, auto_download=False)
        output_path = tmp_path / "output.jpg"
        result = anonymizer.anonymize_image(str(image_path), str(output_path))
        
        assert os.path.exists(result)


class TestLocalLoadImagesAnonymize:
    """Tests for Local.load_images with anonymize option."""
    
    def test_load_images_anonymize_false(self):
        """Test that load_images works normally with anonymize=False."""
        from landlensdb.handlers.image import Local
        
        # This should work without anonymize dependencies
        test_dir = "test_data/local"
        if os.path.exists(test_dir):
            gif = Local.load_images(test_dir, anonymize=False)
            assert gif is not None
            assert len(gif) > 0
    
    def test_load_images_parameter_exists(self):
        """Test that anonymize parameters exist in load_images."""
        from landlensdb.handlers.image import Local
        import inspect
        
        sig = inspect.signature(Local.load_images)
        params = list(sig.parameters.keys())
        
        assert "anonymize" in params
        assert "anonymize_output_dir" in params
        assert "model_path" in params


class TestAnonymizeModule:
    """Tests for the anonymize module structure."""
    
    def test_process_init_lazy_import(self):
        """Test that process __init__ supports lazy import."""
        # This should not raise ImportError even without dependencies
        from landlensdb import process
        
        # These should be available
        assert hasattr(process, "snap_to_road_network")
        assert hasattr(process, "get_osm_lines")
    
    @pytest.mark.skipif(not ANONYMIZE_AVAILABLE, reason="Anonymize dependencies not installed")
    def test_process_init_anonymizer_import(self):
        """Test that Anonymizer can be imported from process module."""
        from landlensdb.process import Anonymizer
        assert Anonymizer is not None
    
    @pytest.mark.skipif(not ANONYMIZE_AVAILABLE, reason="Anonymize dependencies not installed")
    def test_process_init_anonymize_images_import(self):
        """Test that anonymize_images can be imported from process module."""
        from landlensdb.process import anonymize_images
        assert anonymize_images is not None
    
    @pytest.mark.skipif(not ANONYMIZE_AVAILABLE, reason="Anonymize dependencies not installed")
    def test_download_model_function(self):
        """Test that download_model function exists."""
        from landlensdb.process.anonymize import download_model
        assert download_model is not None
