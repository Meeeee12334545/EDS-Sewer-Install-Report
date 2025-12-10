import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import merge_photo_records


class MergePhotoRecordsTests(unittest.TestCase):
    def test_existing_duplicates_collapse_to_single_record(self):
        existing = [
            {"name": "Photo before rename", "data": b"image-bytes", "mime": "image/jpeg"},
            {"name": "Photo after rename", "data": b"image-bytes", "mime": "image/jpeg"},
        ]

        merged = merge_photo_records(existing, [])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["name"], "Photo after rename")
        self.assertEqual(merged[0]["data"], b"image-bytes")

    def test_new_photo_with_same_binary_updates_metadata_only(self):
        existing = [
            {"name": "Before", "data": b"same-bytes", "mime": "image/jpeg"},
        ]
        new = [
            {"name": "After", "data": b"same-bytes", "mime": "image/png"},
        ]

        merged = merge_photo_records(existing, new)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["name"], "After")
        self.assertEqual(merged[0]["mime"], "image/png")

    def test_unique_new_photo_is_appended(self):
        existing = [
            {"name": "First", "data": b"first", "mime": "image/jpeg"},
        ]
        new = [
            {"name": "Second", "data": b"second", "mime": "image/png"},
        ]

        merged = merge_photo_records(existing, new)

        self.assertEqual(len(merged), 2)
        self.assertEqual([m["name"] for m in merged], ["First", "Second"])

    def test_names_are_trimmed_and_defaulted(self):
        existing = [
            {"name": "   ", "data": b"bytes"},
        ]
        new = [
            {"name": "  New  ", "data": b"new-bytes"},
        ]

        merged = merge_photo_records(existing, new)

        self.assertEqual(merged[0]["name"], "Site photo")
        self.assertEqual(merged[1]["name"], "New")


if __name__ == "__main__":
    unittest.main()
