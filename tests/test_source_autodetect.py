import base64
import os
import tempfile
import unittest

import yaml
from fastapi.testclient import TestClient

import app as appmod


class TestSourceAutodetection(unittest.TestCase):
    def setUp(self):
        self.old_data_file = appmod.DATA_FILE
        self.old_overrides = dict(appmod.app.dependency_overrides)
        self.temp_dir = tempfile.TemporaryDirectory()
        appmod.DATA_FILE = os.path.join(self.temp_dir.name, "sources.json")
        appmod.app.dependency_overrides[appmod.require_admin_auth] = lambda: True
        self.client = TestClient(appmod.app)

    def tearDown(self):
        self.client.close()
        appmod.DATA_FILE = self.old_data_file
        appmod.app.dependency_overrides.clear()
        appmod.app.dependency_overrides.update(self.old_overrides)
        self.temp_dir.cleanup()

    def save_source(self, value, files=None):
        return self.client.post("/sources/save", data={
            "name": "Detected source",
            "kind": "auto",
            "value": value,
        }, files=files, follow_redirects=False)

    def saved_kind(self):
        return appmod._load_db()["sources"][-1]["kind"]

    def test_detects_remote_url_v2ray_text_and_clash_yaml(self):
        cases = [
            ("https://example.com/feed", "clash_url"),
            ("vless://00000000-0000-0000-0000-000000000001@example.com:443#node", "v2ray_text"),
            (base64.b64encode(b"trojan://secret@example.com:443#node").decode(), "v2ray_text"),
            (yaml.safe_dump({"proxies": []}), "clash_yaml"),
        ]
        for value, expected in cases:
            with self.subTest(expected=expected):
                response = self.save_source(value)
                self.assertEqual(response.status_code, 303, response.text)
                self.assertEqual(self.saved_kind(), expected)

    def test_uploaded_file_is_detected_as_clash_yaml(self):
        content = yaml.safe_dump({"proxies": []})
        response = self.save_source("", files={"file": ("nodes.yaml", content, "text/yaml")})
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(self.saved_kind(), "clash_yaml")

    def test_rejects_content_that_cannot_be_detected(self):
        response = self.save_source("not a supported subscription")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unable to detect source type", response.text)

    def test_new_source_form_defaults_to_auto_detection(self):
        response = self.client.get("/sources/new")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('<option value="auto" selected>自动识别</option>', response.text)

        home = self.client.get("/")
        self.assertEqual(home.status_code, 200, home.text)
        self.assertEqual(home.text.count('class="add-subscription-menu"'), 1)
        self.assertEqual(home.text.count("/sources/new"), 1)
        self.assertEqual(home.text.count("/profiles/new"), 1)
        self.assertIn('data-home-tab="sources">订阅源</button>', home.text)
        self.assertIn('aria-controls="panel-profiles" aria-selected="false" tabindex="-1" data-home-tab="profiles">', home.text)
        self.assertIn('data-state-region="profiles" hidden', home.text)
        self.assertIn("/static/app.js?v=home-sidebar-20261108", home.text)


if __name__ == "__main__":
    unittest.main()
