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


    def test_split_concatenated_uri_records(self):
        text = "vless://a@one.example:443#日本1ss://b@two.example:443#美国1"
        self.assertEqual(
            split_v2ray_text(text),
            ["vless://a@one.example:443#日本1", "ss://b@two.example:443#美国1"],
        )

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
        groups = doc.get("proxy-groups", [])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("type"), "select")
        self.assertNotIn("load-balance", [g.get("type") for g in groups])
        self.assertNotIn("url-test", [g.get("type") for g in groups])
        self.assertEqual(groups[0].get("proxies"), ["DIRECT", "HK-1", "HK-2", "JP-1"])
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

class TestMieru(unittest.TestCase):
    def test_parse_mierus_to_mihomo(self):
        uri = (
            "mierus://user:secret@120.253.251.130?"
            "handshake-mode=HANDSHAKE_NO_WAIT&mtu=1400&"
            "multiplexing=MULTIPLEXING_OFF&port=6802&profile=default&"
            "protocol=TCP&traffic-pattern=CIXu%2BasFEAAiCAgBEAEYBCAIKgUIABCAATICCAA%3D"
        )
        proxies = v2ray_uris_to_clash_proxies([uri])
        self.assertEqual(len(proxies), 1)
        proxy = proxies[0]
        self.assertEqual(proxy["type"], "mieru")
        self.assertEqual(proxy["server"], "120.253.251.130")
        self.assertEqual(proxy["port"], 6802)
        self.assertEqual(proxy["username"], "user")
        self.assertEqual(proxy["password"], "secret")
        self.assertEqual(proxy["handshake-mode"], "HANDSHAKE_NO_WAIT")
        self.assertNotIn("mtu", proxy)
        self.assertEqual(proxy["multiplexing"], "MULTIPLEXING_OFF")
        self.assertNotIn("profile", proxy)
        self.assertEqual(proxy["transport"], "TCP")
        self.assertEqual(proxy["traffic-pattern"], "CIXu+asFEAAiCAgBEAEYBCAIKgUIABCAATICCAA=")

class TestMixedMieruNames(unittest.TestCase):
    def test_mieru_fragment_name_is_preserved_with_vless(self):
        mieru = (
            "mierus://user:testpass@120.253.251.130?port=6802&protocol=TCP"
            "#日本1(ie)"
        )
        vless = (
            "vless://00000000-0000-0000-0000-000000000001@127.0.0.1:443"
            "?security=reality&sni=example.com&pbk=key&sid=id#美国1(lt)"
        )
        proxies = v2ray_uris_to_clash_proxies([mieru, vless])
        self.assertEqual([p["name"] for p in proxies], ["日本1(ie)", "美国1(lt)"])
