"""Optional sing-box 1.12 schema checks; set SINGBOX_BINARY to the executable."""

import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from exporter import build_singbox_config


KEY = base64.b64encode(bytes(range(32))).decode("ascii")


@unittest.skipUnless(os.environ.get("SINGBOX_BINARY"), "SINGBOX_BINARY not configured")
class TestSingboxSchema(unittest.TestCase):
    def test_golden_protocol_configs_pass_singbox_check(self):
        nodes = [
            {"name": "reality", "type": "vless", "server": "example.com", "port": 443,
             "uuid": "00000000-0000-0000-0000-000000000001", "tls": True,
             "client-fingerprint": "firefox", "reality-opts": {"public-key": KEY, "short-id": "abcd"}},
            {"name": "vmess-ws-tls", "type": "vmess", "server": "example.com", "port": 443,
             "uuid": "00000000-0000-0000-0000-000000000001", "cipher": "auto", "tls": True,
             "network": "ws", "ws-opts": {"path": "/ws", "headers": {"Host": "example.com"}}},
            {"name": "trojan", "type": "trojan", "server": "example.com", "port": 443,
             "password": "secret", "tls": True},
            {"name": "ss2022", "type": "ss", "server": "example.com", "port": 8388,
             "cipher": "2022-blake3-aes-128-gcm", "password": base64.b64encode(b"s" * 16).decode()},
            {"name": "hysteria2", "type": "hysteria2", "server": "example.com", "port": 443,
             "password": "secret", "tls": True},
            {"name": "tuic", "type": "tuic", "server": "example.com", "port": 443,
             "uuid": "00000000-0000-0000-0000-000000000001", "password": "secret", "tls": True},
            {"name": "wireguard", "type": "wireguard", "server": "example.com", "port": 51820,
             "private-key": KEY, "public-key": KEY, "ip": "10.0.0.2/32"},
        ]
        binary = os.environ["SINGBOX_BINARY"]
        with tempfile.TemporaryDirectory(prefix="subconvert-singbox-") as directory:
            for node in nodes:
                with self.subTest(protocol=node["type"], name=node["name"]):
                    config = Path(directory) / (node["name"] + ".json")
                    config.write_text(json.dumps(build_singbox_config([node])), encoding="utf-8")
                    result = subprocess.run([binary, "check", "-c", str(config)], capture_output=True, timeout=40)
                    output = result.stdout.decode("utf-8", errors="replace") + result.stderr.decode("utf-8", errors="replace")
                    self.assertEqual(result.returncode, 0, output)

    def test_bare_outbounds_is_an_array(self):
        config = build_singbox_config([{
            "name": "node", "type": "trojan", "server": "example.com", "port": 443,
            "password": "secret", "tls": True,
        }], bare=True)
        self.assertIsInstance(config, list)


if __name__ == "__main__":
    unittest.main()
