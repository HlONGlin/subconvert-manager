import base64
import unittest
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

import app as appmod
from tests.test_protocols import fixtures


class TestConversionRoutes(unittest.TestCase):
    def setUp(self):
        self.old_suffix = appmod.URL_SUFFIX
        self.old_overrides = dict(appmod.app.dependency_overrides)
        appmod.URL_SUFFIX = ""
        appmod.app.dependency_overrides[appmod.require_admin_auth] = lambda: True
        self.client = TestClient(appmod.app)

    def tearDown(self):
        self.client.close()
        appmod.URL_SUFFIX = self.old_suffix
        appmod.app.dependency_overrides.clear()
        appmod.app.dependency_overrides.update(self.old_overrides)

    def test_web_import_mixed_good_bad_shows_diagnostics(self):
        response = self.client.post("/convert/v2ray_to_clash", data={
            "text": "hy2://secret@example.com#new\nunknown://TOP_SECRET@example.com:443",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("hysteria2", response.text)
        self.assertIn("unknown", response.text)
        self.assertNotIn("TOP_SECRET", response.text)
        self.assertIn("转换记录", response.text)

    def test_web_export_includes_all_14_protocols_and_yaml_only_notice(self):
        nodes = fixtures() + [{"type": "snell", "server": "example.com", "port": 443, "psk": "secret"}]
        response = self.client.post("/convert/clash_to_v2ray",
                                    files={"file": ("test.yaml", yaml.safe_dump({"proxies": nodes}), "text/yaml")},
                                    data={"out": "raw"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("数量：14", response.text)
        for kind in ("hysteria2", "tuic", "anytls", "wireguard", "ssh", "ssr"):
            self.assertIn(kind + "://", response.text)
        self.assertIn("snell", response.text)
        self.assertIn("已跳过", response.text)

    def test_all_invalid_returns_actionable_422(self):
        response = self.client.post("/convert/v2ray_to_clash",
                                    data={"text": "anytls://SECRET@example.com:bad"},
                                    headers={"accept": "application/json"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("anytls", response.json()["detail"])
        self.assertNotIn("SECRET", response.text)

    def test_private_and_public_subscription_conversion_headers(self):
        src = {"kind": "v2ray_text", "value": "anytls://secret@example.com#one\nunsupported://secret@example.com"}
        with patch.object(appmod, "_source_or_404", return_value=src), patch.object(appmod, "SUB_TOKEN", "test-token"):
            for path in ("/s/test/clash", "/pub/s/test/clash?token=test-token"):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.headers["X-Conversion-Skipped"], "1")
                self.assertEqual(response.headers["X-Conversion-Warnings"], "0")
                self.assertEqual(yaml.safe_load(response.text)["proxies"][0]["type"], "anytls")

    def test_subscription_export_raw_and_base64_both_private_and_public(self):
        nodes = fixtures() + [{"type": "snell", "server": "example.com", "port": 443, "psk": "secret"}]
        src = {"kind": "clash_yaml", "value": yaml.safe_dump({"proxies": nodes})}
        with patch.object(appmod, "_source_or_404", return_value=src), patch.object(appmod, "SUB_TOKEN", "test-token"):
            for prefix in ("/s/test/", "/pub/s/test/"):
                for output in ("v2ray", "v2ray_raw"):
                    path = prefix + output + ("?token=test-token" if prefix.startswith("/pub") else "")
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.headers["X-Conversion-Skipped"], "1")
                    payload = base64.b64decode(response.text).decode("utf-8") if output == "v2ray" else response.text
                    self.assertEqual(len(payload.splitlines()), 14)

    def test_subscription_yaml_passthrough_keeps_all_native_fields(self):
        native = yaml.safe_dump({"proxies": [
            {"type": "snell", "name": "snell", "server": "example.com", "port": 443, "psk": "secret"},
            {"type": "wireguard", "name": "wg", "peers": [{"server": "one.example"}, {"server": "two.example"}]},
        ]})
        for kind in ("clash_yaml", "clash_url"):
            src = {"kind": kind, "value": native if kind == "clash_yaml" else "https://example.com/sub"}
            with patch.object(appmod, "_source_or_404", return_value=src), patch.object(appmod, "_fetch_text", return_value=native):
                response = self.client.get("/s/test/clash")
                self.assertEqual(response.text, native)
                self.assertEqual(response.headers["X-Conversion-Skipped"], "0")

    def test_public_subscriptions_still_require_token(self):
        with patch.object(appmod, "SUB_TOKEN", "correct-token"):
            for output in ("clash", "v2ray", "v2ray_raw"):
                response = self.client.get("/pub/s/test/" + output + "?token=wrong",
                                           headers={"accept": "application/json"})
                self.assertEqual(response.status_code, 401)

    def test_optional_yaml_fields_expose_warning_count(self):
        nodes = [dict(fixtures()[0], **{"tfo": True})]
        src = {"kind": "clash_yaml", "value": yaml.safe_dump({"proxies": nodes})}
        with patch.object(appmod, "_source_or_404", return_value=src):
            response = self.client.get("/s/test/v2ray_raw")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Conversion-Warnings"], "1")

    def test_prefix_routes_still_convert(self):
        appmod.URL_SUFFIX = "test-prefix"
        response = self.client.post("/test-prefix/convert/v2ray_to_clash",
                                    data={"text": "anytls://secret@example.com"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("/test-prefix/static/style.css", response.text)


if __name__ == "__main__":
    unittest.main()
