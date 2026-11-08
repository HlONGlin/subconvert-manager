import json
import os
import tempfile
import unittest

import yaml
from fastapi.testclient import TestClient

import app as appmod
from exporter import build_custom_clash_template, build_singbox_config
from processor import process_proxies
from storage import upsert_profile, upsert_source


class TestProxyProcessing(unittest.TestCase):
    def test_filter_rename_deduplicate_and_order(self):
        nodes = [
            {"name": "HK-2", "type": "ss", "server": "one.example", "port": 443},
            {"name": "HK-1", "type": "ss", "server": "one.example", "port": 443},
            {"name": "JP-1", "type": "ss", "server": "two.example", "port": 443},
        ]
        result = process_proxies(
            nodes, filter_include="HK", rename_regex="HK-", rename_with="Home-", sort="name"
        )
        self.assertEqual([item["name"] for item in result], ["Home-2"])
        self.assertEqual(nodes[0]["name"], "HK-2")

    def test_regex_filter_and_unique_tags(self):
        nodes = [
            {"name": "HK A", "type": "ss", "server": "one.example"},
            {"name": "HK B", "type": "ss", "server": "two.example"},
            {"name": "JP A", "type": "ss", "server": "three.example"},
        ]
        result = process_proxies(
            nodes, filter_include=r"^HK", filter_mode="regex", rename_regex=r"HK.*", rename_with="HK"
        )
        self.assertEqual([item["name"] for item in result], ["HK", "HK-2"])


class TestProfileExports(unittest.TestCase):
    def test_singbox_export_maps_tls_and_reports_expected_types(self):
        config = build_singbox_config([{
            "name": "Reality",
            "type": "vless",
            "server": "example.com",
            "port": 443,
            "uuid": "00000000-0000-0000-0000-000000000001",
            "tls": True,
            "servername": "cdn.example",
            "reality-opts": {"public-key": "key", "short-id": "abc"},
            "network": "ws",
            "ws-opts": {"path": "/tunnel", "headers": {"Host": "cdn.example"}},
        }])
        outbound = config["outbounds"][2]
        self.assertEqual(outbound["type"], "vless")
        self.assertEqual(outbound["tls"]["reality"]["public_key"], "key")
        self.assertEqual(outbound["transport"]["path"], "/tunnel")

    def test_custom_clash_template_keeps_rules_and_dns(self):
        doc = build_custom_clash_template(
            [{"name": "HK-1", "type": "ss"}],
            "dns:\n  enable: true\nrules:\n  - MATCH,Proxy\nproxy-groups:\n  - name: Proxy\n    type: select\n    proxies:\n      - HK-1\n",
        )
        self.assertTrue(doc["dns"]["enable"])
        self.assertEqual(doc["rules"], ["MATCH,Proxy"])
        self.assertEqual(doc["proxies"][0]["name"], "HK-1")


class TestProfileRoutes(unittest.TestCase):
    def setUp(self):
        self.old_data_file = appmod.DATA_FILE
        self.old_token = appmod.SUB_TOKEN
        self.old_overrides = dict(appmod.app.dependency_overrides)
        self.temp_dir = tempfile.TemporaryDirectory()
        appmod.DATA_FILE = os.path.join(self.temp_dir.name, "sources.json")
        appmod.SUB_TOKEN = "profile-test-token"
        appmod.app.dependency_overrides[appmod.require_admin_auth] = lambda: True
        db = {"sources": [], "profiles": []}
        upsert_source(db, {
            "id": "source-one", "name": "One", "kind": "v2ray_text",
            "value": "ss://aes-128-gcm:secret@one.example:443#HK-1",
        })
        upsert_source(db, {
            "id": "source-two", "name": "Two", "kind": "v2ray_text",
            "value": "ss://aes-128-gcm:secret@one.example:443#HK-duplicate\nss://aes-128-gcm:secret@two.example:443#JP-1",
        })
        upsert_profile(db, {
            "id": "daily", "name": "Daily", "source_ids": ["source-one", "source-two"],
            "filter_include": "", "filter_exclude": "", "filter_mode": "keyword",
            "dedupe": True, "sort": "name", "clash_template": "default",
        })
        appmod._save_db(db)
        self.client = TestClient(appmod.app)

    def tearDown(self):
        self.client.close()
        appmod.DATA_FILE = self.old_data_file
        appmod.SUB_TOKEN = self.old_token
        appmod.app.dependency_overrides.clear()
        appmod.app.dependency_overrides.update(self.old_overrides)
        self.temp_dir.cleanup()

    def test_profile_merges_sources_deduplicates_and_exports_clients(self):
        clash = self.client.get("/p/daily/clash")
        self.assertEqual(clash.status_code, 200, clash.text)
        self.assertEqual(len(yaml.safe_load(clash.text)["proxies"]), 2)

        singbox = self.client.get("/p/daily/singbox")
        self.assertEqual(singbox.status_code, 200, singbox.text)
        self.assertEqual(singbox.headers["content-type"], "application/json")
        config = json.loads(singbox.text)
        self.assertEqual(singbox.headers["X-Node-Count"], "2")
        self.assertEqual(len(config["outbounds"]) - 2, 2)

        public = self.client.get("/pub/p/daily/v2ray?token=profile-test-token")
        self.assertEqual(public.status_code, 200, public.text)
        self.assertEqual(self.client.get("/pub/p/daily/clash?token=bad").status_code, 401)

    def test_profile_save_requires_known_source_and_supports_checkbox_form(self):
        response = self.client.post("/profiles/save", data={
            "name": "Filtered", "source_ids": ["source-one", "source-two"],
            "filter_mode": "regex", "filter_include": "^HK", "dedupe": "1",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        saved = appmod._load_db()["profiles"][-1]
        self.assertEqual(saved["source_ids"], ["source-one", "source-two"])

    def test_invalid_regex_is_rejected_and_singbox_reports_skipped_nodes(self):
        invalid = self.client.post("/profiles/save", data={
            "name": "Bad regex", "source_ids": ["source-one"],
            "filter_mode": "regex", "filter_include": "(",
        })
        self.assertEqual(invalid.status_code, 400)

        db = appmod._load_db()
        upsert_source(db, {
            "id": "mixed-yaml", "name": "Mixed", "kind": "clash_yaml",
            "value": yaml.safe_dump({"proxies": [
                {"name": "Known", "type": "ss", "server": "valid.example", "port": 443,
                 "cipher": "aes-128-gcm", "password": "secret"},
                {"name": "Unsupported", "type": "ssr", "server": "legacy.example", "port": 443},
            ]}),
        })
        appmod._save_db(db)
        response = self.client.get("/pub/s/mixed-yaml/singbox?token=profile-test-token")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["X-Output-Skipped"], "1")
        self.assertEqual(json.loads(response.text)["outbounds"][2]["tag"], "Known")

    def test_manual_source_check_records_status(self):
        response = self.client.post("/sources/source-one/check", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        source = next(item for item in appmod._load_db()["sources"] if item["id"] == "source-one")
        self.assertEqual(source["last_status"], "ok")
        self.assertEqual(source["last_node_count"], 1)

    def test_management_and_profile_editor_render(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200, home.text)
        self.assertIn("sing-box JSON", home.text)
        editor = self.client.get("/profiles/daily/edit")
        self.assertEqual(editor.status_code, 200, editor.text)
        self.assertIn("source-one", editor.text)


if __name__ == "__main__":
    unittest.main()
