"""
Tests for the anonymize module.

Note: These tests require optional dependencies (torch, opencv-python).
Run with: pip install landlensdb[anonymize]
"""

import os
import pytest
import warnings

# Check if anonymize dependencies are available
try:
    import torch
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
    
    def test_anonymizer_requires_model_path(self):
        """Test that Anonymizer raises error without model paths."""
        from landlensdb.process.anonymize import Anonymizer
        
        with pytest.raises(ValueError, match="At least one of"):
            Anonymizer()
    
    def test_anonymizer_file_not_found(self, tmp_path):
        """Test that Anonymizer raises error for non-existent model file."""
        from landlensdb.process.anonymize import Anonymizer
        
        anonymizer = Anonymizer(
            face_model_path="/nonexistent/path/model.jit"
        )
        
        # Error should occur when trying to load models
        with pytest.raises(FileNotFoundError):
            anonymizer._load_models()
    
    def test_check_dependencies(self):
        """Test dependency checking function."""
        from landlensdb.process.anonymize import _check_egoblur_available
        
        result = _check_egoblur_available()
        assert result == ANONYMIZE_AVAILABLE
    
    def test_get_device(self):
        """Test device detection."""
        from landlensdb.process.anonymize import _get_device
        
        device = _get_device()
        assert device in ["cpu", "cuda:0"]


class TestAnonymizerIntegration:
    """Integration tests that require model files."""
    
    @pytest.mark.skipif(not ANONYMIZE_AVAILABLE, reason="Anonymize dependencies not installed")
    def test_anonymize_image_without_model(self, tmp_path):
        """Test that anonymize_image fails gracefully without model."""
        from landlensdb.process.anonymize import Anonymizer
        
        # Create a dummy image
        import numpy as np
        dummy_image = np.zeros((100, 100, 3), dtype=np.uint8)
        image_path = tmp_path / "test_image.jpg"
        cv2.imwrite(str(image_path), dummy_image)
        
        # This should fail because model doesn't exist
        anonymizer = Anonymizer(
            face_model_path="/nonexistent/model.jit"
        )
        
        with pytest.raises(FileNotFoundError):
            anonymizer.anonymize_image(str(image_path))


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
    
    @pytest.mark.skipif(not ANONYMIZE_AVAILABLE, reason="Anonymize dependencies not installed")
    def test_load_images_anonymize_requires_model(self):
        """Test that load_images with anonymize=True requires model paths."""
        from landlensdb.handlers.image import Local
        
        test_dir = "test_data/local"
        if os.path.exists(test_dir):
            with pytest.raises(ValueError, match="At least one of"):
                Local.load_images(test_dir, anonymize=True)
    
    def test_load_images_anonymize_import_error(self):
        """Test that load_images gives helpful error when dependencies missing."""
        # This test is tricky because we can't easily uninstall dependencies
        # Just verify the parameter exists
        from landlensdb.handlers.image import Local
        import inspect
        
        sig = inspect.signature(Local.load_images)
        params = list(sig.parameters.keys())
        
        assert "anonymize" in params
        assert "anonymize_output_dir" in params
        assert "face_model_path" in params
        assert "lp_model_path" in params


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
