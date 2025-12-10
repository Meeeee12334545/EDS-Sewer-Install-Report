import unittest
import json
import tempfile
import shutil
import base64
import re
from pathlib import Path
from datetime import datetime


# Replicate the essential functions from app.py for testing
def sanitize_filename(text):
    """Sanitize text for use in filenames."""
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '_', text)
    return text[:50]


def encode_binary_data(site_record):
    """Encode binary data (photos, diagrams) to base64 for JSON storage."""
    encoded = site_record.copy()
    
    if encoded.get("diagram") and encoded["diagram"].get("data"):
        encoded["diagram"] = encoded["diagram"].copy()
        encoded["diagram"]["data"] = base64.b64encode(
            encoded["diagram"]["data"]
        ).decode("utf-8")
    
    if encoded.get("photos"):
        encoded["photos"] = []
        for photo in site_record["photos"]:
            photo_copy = photo.copy()
            if photo_copy.get("data"):
                photo_copy["data"] = base64.b64encode(photo_copy["data"]).decode("utf-8")
            encoded["photos"].append(photo_copy)
    
    return encoded


def decode_binary_data(site_record):
    """Decode base64 binary data back to bytes."""
    decoded = site_record.copy()
    
    if decoded.get("diagram") and decoded["diagram"].get("data"):
        decoded["diagram"] = decoded["diagram"].copy()
        try:
            decoded["diagram"]["data"] = base64.b64decode(decoded["diagram"]["data"])
        except Exception:
            decoded["diagram"]["data"] = b""
    
    if decoded.get("photos"):
        decoded["photos"] = []
        for photo in site_record["photos"]:
            photo_copy = photo.copy()
            if photo_copy.get("data"):
                try:
                    photo_copy["data"] = base64.b64decode(photo_copy["data"])
                except Exception:
                    photo_copy["data"] = b""
            decoded["photos"].append(photo_copy)
    
    return decoded


def get_report_summary(report):
    """Get a summary string for a report."""
    project = report.get("project_name", "Unknown Project")
    site = report.get("site_name", "Unknown Site")
    date_str = report.get("install_date", "Unknown Date")
    return f"{project} - {site} ({date_str})"


class DatabaseFunctionsTests(unittest.TestCase):
    def setUp(self):
        """Create a temporary directory for testing."""
        self.test_dir = Path(tempfile.mkdtemp())
    
    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.test_dir)
    
    def test_sanitize_filename(self):
        """Test filename sanitization."""
        result = sanitize_filename("Test Project #123!")
        self.assertEqual(result, "Test_Project_123")
        
        result = sanitize_filename("Project with spaces and-dashes")
        self.assertEqual(result, "Project_with_spaces_and_dashes")
        
        # Test length limitation
        long_name = "a" * 100
        result = sanitize_filename(long_name)
        self.assertEqual(len(result), 50)
    
    def test_encode_decode_binary_data(self):
        """Test encoding and decoding of binary data."""
        site_record = {
            "site_name": "Test Site",
            "diagram": {
                "name": "test.png",
                "data": b"binary_image_data"
            },
            "photos": [
                {"name": "photo1.jpg", "data": b"photo_data_1"},
                {"name": "photo2.jpg", "data": b"photo_data_2"}
            ]
        }
        
        # Encode
        encoded = encode_binary_data(site_record)
        self.assertIsInstance(encoded["diagram"]["data"], str)
        self.assertIsInstance(encoded["photos"][0]["data"], str)
        
        # Decode
        decoded = decode_binary_data(encoded)
        self.assertEqual(decoded["diagram"]["data"], b"binary_image_data")
        self.assertEqual(decoded["photos"][0]["data"], b"photo_data_1")
        self.assertEqual(decoded["photos"][1]["data"], b"photo_data_2")
    
    def test_save_and_load_report(self):
        """Test saving and loading a report."""
        site_record = {
            "project_name": "Test Project",
            "site_name": "Test Site",
            "client": "Test Client",
            "install_date": "2023-12-10",
            "meter_model": "Test Meter",
            "calibration_rating": "Good"
        }
        
        # Generate filename
        project = sanitize_filename(site_record.get("project_name", "unknown"))
        site = sanitize_filename(site_record.get("site_name", "unknown"))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{project}_{site}_{timestamp}.json"
        filepath = self.test_dir / filename
        
        # Encode and save
        encoded = encode_binary_data(site_record)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(encoded, f, indent=2, default=str)
        
        self.assertTrue(filepath.exists())
        self.assertTrue("Test_Project" in filename)
        self.assertTrue("Test_Site" in filename)
        
        # Load and verify
        with open(filepath, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        
        self.assertEqual(loaded["project_name"], "Test Project")
        self.assertEqual(loaded["site_name"], "Test Site")
    
    def test_delete_report(self):
        """Test deleting a report."""
        site_record = {
            "project_name": "Delete Test",
            "site_name": "Delete Site",
        }
        
        # Create a test file
        filename = "Delete_Test_Delete_Site_20231210_120000.json"
        filepath = self.test_dir / filename
        
        encoded = encode_binary_data(site_record)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(encoded, f, indent=2, default=str)
        
        # Verify it exists
        self.assertTrue(filepath.exists())
        
        # Delete it
        filepath.unlink()
        
        # Verify it's gone
        self.assertFalse(filepath.exists())
    
    def test_get_report_summary(self):
        """Test generating report summary."""
        report = {
            "project_name": "Brisbane Project",
            "site_name": "MH123",
            "install_date": "2023-12-10"
        }
        
        summary = get_report_summary(report)
        self.assertEqual(summary, "Brisbane Project - MH123 (2023-12-10)")
        
        # Test with missing fields
        report = {}
        summary = get_report_summary(report)
        self.assertEqual(summary, "Unknown Project - Unknown Site (Unknown Date)")
    
    def test_multiple_reports(self):
        """Test saving and loading multiple reports."""
        reports_data = [
            {"project_name": "Project A", "site_name": "Site 1"},
            {"project_name": "Project B", "site_name": "Site 2"},
            {"project_name": "Project C", "site_name": "Site 3"},
        ]
        
        # Save multiple reports
        for i, report_data in enumerate(reports_data):
            project = sanitize_filename(report_data.get("project_name", "unknown"))
            site = sanitize_filename(report_data.get("site_name", "unknown"))
            filename = f"{project}_{site}_{i}.json"
            filepath = self.test_dir / filename
            
            encoded = encode_binary_data(report_data)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(encoded, f, indent=2, default=str)
        
        # Load all reports
        loaded = []
        for filepath in sorted(self.test_dir.glob("*.json")):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                loaded.append(data)
        
        self.assertEqual(len(loaded), 3)
        
        # Verify all project names are present
        project_names = [r["project_name"] for r in loaded]
        self.assertIn("Project A", project_names)
        self.assertIn("Project B", project_names)
        self.assertIn("Project C", project_names)


if __name__ == "__main__":
    unittest.main()
