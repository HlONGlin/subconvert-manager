"""Optional schema integration check: set MIHOMO_BINARY to a local Mihomo executable."""

import base64
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

from converter import clash_yaml_to_v2ray_uris, v2ray_uris_to_clash_proxies
from tests.test_protocols import KEY, fixtures


@unittest.skipUnless(os.environ.get("MIHOMO_BINARY"), "MIHOMO_BINARY not configured")
class TestMihomoSchema(unittest.TestCase):
    def test_generated_nodes_accepted_by_real_core(self):
        nodes = fixtures()
        for node in nodes:
            node["name"] = node["type"] + "-test"
            if "reality-opts" in node:
                node["reality-opts"]["public-key"] = KEY.replace("+", "-").replace("/", "_").rstrip("=")
            if "fingerprint" in node:
                node["fingerprint"] = "ab" * 32
            if node["type"] == "mieru":
                node["traffic-pattern"] = "CIXu+asFEAAiCAgBEAEYBCAIKgUIABCAATICCAA="
        issues = []
        uris = clash_yaml_to_v2ray_uris({"proxies": nodes}, issues)
        self.assertEqual(len(uris), len(nodes), issues)
        imported = v2ray_uris_to_clash_proxies(uris, issues)
        self.assertEqual(len(imported), len(nodes), issues)
        with tempfile.TemporaryDirectory(prefix="subconvert-mihomo-") as directory:
            config = Path(directory) / "config.yaml"
            config.write_text(yaml.safe_dump({
                "mode": "rule", "log-level": "silent", "proxies": imported,
                "proxy-groups": [{"name": "PROXY", "type": "select", "proxies": [n["name"] for n in imported]}],
                "rules": ["MATCH,DIRECT"],
            }), encoding="utf-8")
            result = subprocess.run(
                [os.environ["MIHOMO_BINARY"], "-t", "-d", directory, "-f", str(config)],
                capture_output=True, timeout=40,
            )
            self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8", errors="replace") +
                             result.stderr.decode("utf-8", errors="replace"))


if __name__ == "__main__":
    unittest.main()
