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
        outbound = next(item for item in config["outbounds"] if item["tag"] == "Reality")
        self.assertEqual(outbound["type"], "vless")
        self.assertEqual(outbound["tls"]["utls"], {"enabled": True, "fingerprint": "chrome"})
        self.assertEqual(outbound["tls"]["reality"]["public_key"], "key")
        self.assertEqual(outbound["transport"]["path"], "/tunnel")

    def test_singbox_export_maps_wireguard_to_endpoint(self):
        config = build_singbox_config([{
            "name": "WireGuard",
            "type": "wireguard",
            "server": "vpn.example",
            "port": 51820,
            "private-key": "private",
            "public-key": "public",
            "pre-shared-key": "psk",
            "ip": "10.0.0.2/32",
            "ipv6": "fd00::2/128",
            "reserved": [1, 2, 3],
            "mtu": 1280,
        }])
        endpoint = config["endpoints"][0]
        self.assertEqual(endpoint["type"], "wireguard")
        self.assertEqual(endpoint["tag"], "WireGuard")
        self.assertEqual(endpoint["address"], ["10.0.0.2/32", "fd00::2/128"])
        self.assertEqual(endpoint["private_key"], "private")
        self.assertEqual(endpoint["mtu"], 1280)
        self.assertEqual(endpoint["peers"][0], {
            "address": "vpn.example",
            "port": 51820,
            "public_key": "public",
            "allowed_ips": ["0.0.0.0/0", "::/0"],
            "pre_shared_key": "psk",
            "reserved": [1, 2, 3],
        })

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
        self.assertEqual(sum(item["type"] == "shadowsocks" for item in config["outbounds"]), 2)

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
        self.assertIn("Known", [item["tag"] for item in json.loads(response.text)["outbounds"]])

    def test_singbox_bare_mode_returns_only_outbounds(self):
        response = self.client.get("/pub/s/source-one/singbox?token=profile-test-token&mode=bare")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsInstance(response.json(), list)

    def test_profile_preview_shows_renamed_nodes_and_skips_filtered_nodes(self):
        response = self.client.post("/profiles/preview", data={
            "source_ids": ["source-one", "source-two"], "filter_include": "HK",
            "filter_mode": "keyword", "rename_regex": "HK-", "rename_with": "Home-", "dedupe": "1",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["names"], ["Home-1"])
        self.assertIn("JP-1", response.json()["skipped"])

    def test_settings_page_and_backup_import_export(self):
        self.assertEqual(self.client.get("/admin/settings").status_code, 200)
        backup = self.client.get("/admin/settings/backup")
        self.assertEqual(backup.status_code, 200)
        self.assertEqual(len(backup.json()["sources"]), 2)
        imported = self.client.post("/admin/settings/backup", files={
            "file": ("sources.json", json.dumps({"sources": [], "profiles": []}), "application/json"),
        }, follow_redirects=False)
        self.assertEqual(imported.status_code, 303)
        self.assertEqual(appmod._load_db()["sources"], [])

    def test_settings_save_updates_runtime_values_and_persists_env(self):
        names = ("CONFIG_ENV_FILE", "TIMEOUT", "DATA_FILE", "SUB_TOKEN", "URL_SUFFIX",
                 "LOGIN_MAX_FAILS", "LOGIN_LOCK_SECONDS", "MAX_REMOTE_BYTES", "UPDATE_BRANCH", "_FETCH_CACHE_TTL")
        previous = {name: getattr(appmod, name) for name in names}
        env_names = ("PORT", "TIMEOUT", "DATA_FILE", "SUB_TOKEN", "URL_SUFFIX", "LOGIN_MAX_FAILS",
                     "LOGIN_LOCK_SECONDS", "MAX_REMOTE_BYTES", "FETCH_CACHE_TTL", "UPDATE_BRANCH")
        old_env = {name: os.environ.get(name) for name in env_names}
        appmod.CONFIG_ENV_FILE = os.path.join(self.temp_dir.name, "settings.env")
        try:
            response = self.client.post("/admin/settings", data={
                "port": "8123", "timeout": "12", "data_file": appmod.DATA_FILE,
                "sub_token": "new-test-token", "url_suffix": "xyz", "login_max_fails": "4",
                "login_lock_seconds": "1200", "max_remote_bytes": "3145728",
                "fetch_cache_ttl": "300", "update_branch": "main", "username": appmod.BASIC_USER,
            }, follow_redirects=False)
            self.assertEqual(response.status_code, 303, response.text)
            self.assertEqual(appmod.TIMEOUT, 12)
            self.assertEqual(appmod.SUB_TOKEN, "new-test-token")
            with open(appmod.CONFIG_ENV_FILE, encoding="utf-8") as saved:
                self.assertIn("PORT=8123", saved.read())
        finally:
            for name, value in previous.items():
                setattr(appmod, name, value)
            for name, value in old_env.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

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
