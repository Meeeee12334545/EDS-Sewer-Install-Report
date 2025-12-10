import base64
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import (  # noqa: E402
    build_site_report_bundle,
    generate_site_storage_path,
    slugify_path_component,
    upload_site_report_to_github,
)


def sample_site_record():
    return {
        "project_name": "Northside Expansion",
        "site_name": "MH-27 / River Road",
        "install_date": "2024-11-03",
        "install_time": "09:15",
        "gps_lat": "-27.470000",
        "gps_lon": "153.025100",
        "photos": [
            {
                "name": " Invert",
                "mime": "image/jpeg",
                "data": b"photo-bytes",
            }
        ],
        "diagram": {
            "name": "Site sketch",
            "mime": "image/png",
            "data": b"diagram-bytes",
        },
    }


class GitHubStorageHelpersTests(unittest.TestCase):
    def test_slugify_path_component_normalises_text(self):
        self.assertEqual(slugify_path_component("My Awesome Project"), "my-awesome-project")
        self.assertEqual(slugify_path_component("   ", fallback="Default"), "default")

    def test_generate_site_storage_path(self):
        site = {"project_name": "Stage 2", "site_name": "MH-05"}
        path = generate_site_storage_path(site, base_folder="reports")
        self.assertEqual(path, "reports/stage-2/mh-05.json")

    def test_build_site_report_bundle_includes_metadata_and_pdf(self):
        site = sample_site_record()
        pdf = b"%PDF-1.4 test"
        bundle = build_site_report_bundle(site, pdf)

        self.assertEqual(bundle["bundle_version"], 1)
        self.assertIn("site", bundle)
        self.assertIn("pdf_base64", bundle)

        decoded_pdf = base64.b64decode(bundle["pdf_base64"])
        self.assertEqual(decoded_pdf, pdf)

        photos_meta = bundle["site"].get("photos_metadata")
        self.assertIsInstance(photos_meta, list)
        self.assertEqual(len(photos_meta), 1)
        self.assertEqual(
            photos_meta[0]["sha256"],
            hashlib.sha256(b"photo-bytes").hexdigest(),
        )

        diagram_meta = bundle["site"].get("diagram_metadata")
        self.assertIsInstance(diagram_meta, dict)
        self.assertEqual(
            diagram_meta["sha256"],
            hashlib.sha256(b"diagram-bytes").hexdigest(),
        )


class GitHubUploadTests(unittest.TestCase):
    def setUp(self):
        self.site = sample_site_record()
        self.pdf = b"%PDF-1.7 example"

    def test_upload_creates_new_file(self):
        mock_session = mock.Mock()
        mock_session.get.return_value.status_code = 404
        mock_session.put.return_value.status_code = 201
        mock_session.put.return_value.json.return_value = {
            "content": {"html_url": "https://github.com/org/repo/blob/main/reports/northside-expansion/mh-27-river-road.json"},
            "commit": {"sha": "abc123"},
        }

        result = upload_site_report_to_github(
            self.site,
            self.pdf,
            "org/repo",
            token="dummy-token",
            session=mock_session,
        )

        expected_url = "https://api.github.com/repos/org/repo/contents/reports/northside-expansion/mh-27-river-road.json"
        mock_session.get.assert_called_once()
        self.assertEqual(mock_session.get.call_args.args[0], expected_url)
        self.assertEqual(mock_session.get.call_args.kwargs["params"], {"ref": "main"})

        mock_session.put.assert_called_once()
        put_kwargs = mock_session.put.call_args.kwargs
        self.assertEqual(put_kwargs["headers"]["Authorization"], "Bearer dummy-token")
        payload = put_kwargs["json"]
        self.assertEqual(payload["message"], "Add installation report for MH-27 / River Road")
        self.assertEqual(payload["branch"], "main")
        self.assertNotIn("sha", payload)
        json.loads(base64.b64decode(payload["content"]).decode("utf-8"))

        self.assertEqual(result["commit_sha"], "abc123")

    def test_upload_updates_existing_file(self):
        mock_session = mock.Mock()
        mock_session.get.return_value.status_code = 200
        mock_session.get.return_value.json.return_value = {"sha": "existing-sha"}
        mock_session.put.return_value.status_code = 200
        mock_session.put.return_value.json.return_value = {
            "content": {"html_url": "https://github.com/org/repo/blob/main/reports/file.json"},
            "commit": {"sha": "def456"},
        }

        result = upload_site_report_to_github(
            self.site,
            self.pdf,
            "org/repo",
            token="dummy-token",
            session=mock_session,
        )

        payload = mock_session.put.call_args.kwargs["json"]
        self.assertEqual(payload["message"], "Update installation report for MH-27 / River Road")
        self.assertEqual(payload["sha"], "existing-sha")
        self.assertEqual(mock_session.get.call_args.kwargs["params"], {"ref": "main"})
        self.assertEqual(result["commit_sha"], "def456")


if __name__ == "__main__":
    unittest.main()
