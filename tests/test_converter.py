import base64
import unittest

from converter import build_clash_yaml, build_clashplay_yaml, split_v2ray_text, v2ray_uris_to_clash_proxies


class TestConverter(unittest.TestCase):
    def test_split_v2ray_text_base64(self):
        raw = "vmess://abc\nvless://def\n"
        b64 = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
        out = split_v2ray_text(b64)
        self.assertEqual(out, ["vmess://abc", "vless://def"])

    def test_split_v2ray_text_raw(self):
        out = split_v2ray_text("\n\nvmess://a\n\n")
        self.assertEqual(out, ["vmess://a"])

    def test_split_v2ray_text_urlsafe_base64(self):
        # urlsafe base64 payload that contains '-' and used to fail decode.
        raw = "vmess://>\nvless://>\n"
        b64 = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8").rstrip("=")
        self.assertIn("-", b64)
        out = split_v2ray_text(b64)
        self.assertEqual(out, ["vmess://>", "vless://>"])

    def test_build_clash_yaml_empty(self):
        doc = build_clash_yaml([])
        self.assertIn("proxy-groups", doc)
        self.assertIn("rules", doc)

    def test_build_clashplay_yaml_groups(self):
        proxies = [
            {"name": "HK-1", "type": "ss", "server": "1.1.1.1", "port": 443, "cipher": "aes-128-gcm", "password": "x"},
            {"name": "HK-2", "type": "ss", "server": "2.2.2.2", "port": 443, "cipher": "aes-128-gcm", "password": "x"},
            {"name": "JP-1", "type": "ss", "server": "3.3.3.3", "port": 443, "cipher": "aes-128-gcm", "password": "x"},
        ]
        doc = build_clashplay_yaml(proxies, rate_limit_mbps=100)
        self.assertTrue(any(g.get("type") == "load-balance" for g in doc.get("proxy-groups", [])))
        self.assertTrue(any(g.get("type") == "url-test" for g in doc.get("proxy-groups", [])))
        self.assertIn("rate-limit", doc)

    def test_parse_vless_reality_to_clash(self):
        uri = (
            "vless://775da98a-8741-459e-8d34-2391e2cc74b6@128.241.251.87:10200"
            "?type=tcp"
            "&security=reality"
            "&sni=www.nazhumi.com"
            "&flow=xtls-rprx-vision"
            "&pbk=iunmVK9yBgHKPHGHsEBWuxjvQHbWQ1N9mohCcEMTvCI"
            "&sid=cd685a52b98fd3a6"
            "&fp=chrome"
            "#us-1"
        )
        proxies = v2ray_uris_to_clash_proxies([uri])
        self.assertEqual(len(proxies), 1)
        p = proxies[0]
        self.assertEqual(p.get("type"), "vless")
        self.assertTrue(p.get("tls"))
        self.assertTrue(p.get("udp"))
        self.assertEqual(p.get("servername"), "www.nazhumi.com")
        self.assertEqual(p.get("flow"), "xtls-rprx-vision")
        self.assertEqual(p.get("client-fingerprint"), "chrome")
        self.assertEqual(
            (p.get("reality-opts") or {}).get("public-key"),
            "iunmVK9yBgHKPHGHsEBWuxjvQHbWQ1N9mohCcEMTvCI",
        )
        self.assertEqual((p.get("reality-opts") or {}).get("short-id"), "cd685a52b98fd3a6")
        self.assertNotIn("encryption", p)


if __name__ == "__main__":
    unittest.main()
