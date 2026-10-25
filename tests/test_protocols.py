import base64
import copy
import json
import unittest
from urllib.parse import quote, urlencode, urlsplit, parse_qs

from converter import (
    build_clashplay_yaml, clash_proxy_to_uri, clash_yaml_to_v2ray_uris,
    split_v2ray_text, uris_to_v2ray_subscription_base64,
    v2ray_uris_to_clash_proxies,
)
from protocols import SUPPORTED_PROTOCOLS, YAML_ONLY_PROTOCOLS


KEY = base64.b64encode(bytes(range(32))).decode("ascii")
UUID = "00000000-0000-0000-0000-000000000001"
PASSWORD = "secret:/@?#%+ &"


def b64(text):
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def fixtures():
    common = {"name": "test", "server": "2001:db8::1", "port": 443}
    options = {
        "vmess": {"uuid": UUID, "alterId": 0, "cipher": "auto", "tls": True,
                  "network": "ws", "ws-opts": {"path": "/ws?a=1", "headers": {"Host": "cdn.example"}},
                  "alpn": ["h2", "http/1.1"], "skip-cert-verify": False},
        "vless": {"uuid": UUID, "tls": True, "flow": "xtls-rprx-vision",
                  "reality-opts": {"public-key": "public-key", "short-id": "abc123"},
                  "client-fingerprint": "chrome", "network": "tcp"},
        "trojan": {"password": PASSWORD, "network": "grpc",
                   "grpc-opts": {"grpc-service-name": "service/test"},
                   "sni": "tls.example", "alpn": ["h2"], "skip-cert-verify": False,
                   "client-fingerprint": "chrome"},
        "ss": {"password": PASSWORD, "cipher": "aes-128-gcm",
               "plugin": "v2ray-plugin", "plugin-opts": {"mode": "websocket", "host": "cdn.example",
                                                        "path": "/test?a=b", "tls": True, "mux": False}},
        "ssr": {"password": PASSWORD, "cipher": "aes-128-cfb", "protocol": "auth_aes128_sha1",
                "obfs": "tls1.2_ticket_auth", "obfs-param": "tls.example", "protocol-param": "1:test"},
        "socks5": {"username": "user@/+", "password": PASSWORD, "udp": True, "tls": False},
        "http": {"username": "user@/+", "password": PASSWORD, "tls": True,
                 "sni": "tls.example", "skip-cert-verify": False},
        "hysteria": {"auth-str": PASSWORD, "protocol": "udp", "obfs": "test",
                     "up": "50", "down": "100", "sni": "tls.example", "alpn": ["h3"],
                     "skip-cert-verify": False},
        "hysteria2": {"password": PASSWORD, "obfs": "salamander", "obfs-password": PASSWORD,
                      "ports": "443,1000-1010", "sni": "tls.example", "fingerprint": "pin",
                      "up": "100", "down": "200", "alpn": ["h3"], "skip-cert-verify": False},
        "tuic": {"uuid": UUID, "password": PASSWORD, "congestion-controller": "bbr",
                 "udp-relay-mode": "native", "disable-sni": False, "reduce-rtt": True,
                 "sni": "tls.example", "alpn": ["h3"], "skip-cert-verify": False},
        "anytls": {"password": PASSWORD, "sni": "tls.example", "fingerprint": "pin",
                   "skip-cert-verify": False},
        "mieru": {"username": "user@/+", "password": PASSWORD, "transport": "TCP",
                  "handshake-mode": "HANDSHAKE_NO_WAIT", "multiplexing": "MULTIPLEXING_OFF",
                  "traffic-pattern": "test+/="},
        "wireguard": {"private-key": KEY, "public-key": KEY, "pre-shared-key": KEY,
                      "ip": "10.0.0.2/32", "ipv6": "fd00::2/128", "mtu": 1420,
                      "reserved": [0, 127, 255], "dns": ["1.1.1.1", "2606:4700:4700::1111"]},
        "ssh": {"username": "user@/+", "password": PASSWORD},
    }
    return [dict(common, type=kind, **opts) for kind, opts in options.items()]


class TestProtocolRoundTrips(unittest.TestCase):
    def test_every_supported_protocol_preserves_connection_fields(self):
        nodes = fixtures()
        self.assertEqual(set(SUPPORTED_PROTOCOLS), {p["type"] for p in nodes})
        for node in nodes:
            with self.subTest(protocol=node["type"]):
                before = copy.deepcopy(node)
                issues = []
                uris = clash_yaml_to_v2ray_uris({"proxies": [node]}, issues)
                self.assertEqual(len(uris), 1, issues)
                parsed = v2ray_uris_to_clash_proxies(uris, issues)
                self.assertEqual(len(parsed), 1, issues)
                for field, value in node.items():
                    self.assertEqual(parsed[0].get(field), value, field)
                self.assertEqual(node, before)
                self.assertEqual(issues, [])

    def test_mixed_base64_subscription(self):
        uris = clash_yaml_to_v2ray_uris({"proxies": fixtures()})
        raw = uris_to_v2ray_subscription_base64(uris)
        proxies = v2ray_uris_to_clash_proxies(split_v2ray_text(raw))
        self.assertEqual(len(proxies), len(SUPPORTED_PROTOCOLS))
        self.assertEqual(len({p["name"] for p in proxies}), len(proxies))
        self.assertEqual({p["type"] for p in proxies}, set(SUPPORTED_PROTOCOLS))

    def test_no_input_mutation_on_error(self):
        node = dict(fixtures()[0], alterId="bad")
        original = copy.deepcopy(node)
        self.assertFalse(clash_proxy_to_uri(node)[0])
        self.assertEqual(node, original)


class TestExternalShareFormats(unittest.TestCase):
    def parse(self, uri):
        issues = []
        nodes = v2ray_uris_to_clash_proxies([uri], issues)
        self.assertTrue(nodes, issues)
        return nodes[0]

    def test_hysteria2_upstream_auth_and_default_port(self):
        node = self.parse("hy2://user:pass%2Bword@example.com/?sni=tls.example&insecure=0")
        self.assertEqual(node["type"], "hysteria2")
        self.assertEqual(node["password"], "user:pass+word")
        self.assertEqual(node["port"], 443)
        self.assertFalse(node["skip-cert-verify"])

    def test_hysteria2_port_hopping_authority_ipv4_and_ipv6(self):
        for endpoint, expected in (("example.com", "example.com"), ("[2001:db8::1]", "2001:db8::1")):
            node = self.parse("hysteria2://pass@" + endpoint + ":443,2000-2010/?obfs=salamander&obfs-password=secret")
            self.assertEqual(node["ports"], "443,2000-2010")
            self.assertEqual(node["port"], 443)
            self.assertEqual(node["server"], expected)

    def test_tuic_v4_token(self):
        node = self.parse("tuic://token%3Asecret@example.com:443?disable_sni=1&alpn=h3")
        self.assertEqual(node["token"], "token:secret")
        self.assertTrue(node["disable-sni"])
        self.assertEqual(node["alpn"], ["h3"])
        ok, uri = clash_proxy_to_uri(node)
        self.assertTrue(ok, uri)
        self.assertEqual(self.parse(uri), node)

    def test_anytls_official_default_port(self):
        node = self.parse("anytls://letmein@example.com/?sni=real.example.com")
        self.assertEqual(node["password"], "letmein")
        self.assertEqual(node["port"], 443)

    def test_anytls_user_password_variant(self):
        self.assertEqual(self.parse("anytls://user:pass@example.com:443")["password"], "pass")

    def test_ss_legacy_full_base64(self):
        node = self.parse("ss://" + b64("aes-128-gcm:secret@[2001:db8::1]:8388") + "#legacy")
        self.assertEqual(node["server"], "2001:db8::1")
        self.assertEqual(node["password"], "secret")
        self.assertEqual(node["port"], 8388)

    def test_ss_2022_plain_credentials(self):
        key = KEY + ":" + KEY
        node = self.parse("ss://2022-blake3-aes-128-gcm:" + quote(key, safe="") + "@example.com:8388")
        self.assertEqual(node["password"], key)
        ok, uri = clash_proxy_to_uri(node)
        self.assertTrue(ok)
        self.assertIn("2022-blake3-aes-128-gcm:", uri)
        self.assertEqual(self.parse(uri)["password"], key)

    def test_ss_sip002_obfs(self):
        node = self.parse("ss://" + b64("aes-256-gcm:secret") + "@example.com:8388/?" +
                          urlencode({"plugin": "obfs-local;obfs=http;obfs-host=cdn.example"}) + "#obfs")
        self.assertEqual(node["plugin"], "obfs")
        self.assertEqual(node["plugin-opts"], {"mode": "http", "host": "cdn.example"})
        self.assertEqual(self.parse(clash_proxy_to_uri(node)[1]), node)

    def test_ssr_external_payload(self):
        payload = "example.com:8388:auth_sha1_v4:aes-128-cfb:plain:" + b64("password") + "/?" + urlencode({
            "remarks": b64("SSR node"), "obfsparam": b64("host.example"), "protoparam": b64("123:secret")})
        node = self.parse("ssr://" + b64(payload))
        self.assertEqual(node["name"], "SSR node")
        self.assertEqual(node["protocol"], "auth_sha1_v4")
        self.assertEqual(node["protocol-param"], "123:secret")

    def test_socks5_base64_auth(self):
        node = self.parse("socks://" + b64("user:password:more") + "@example.com:1080")
        self.assertEqual(node["type"], "socks5")
        self.assertEqual(node["username"], "user")
        self.assertEqual(node["password"], "password:more")

    def test_proxy_without_auth_and_http_defaults(self):
        for uri, kind, port, tls in (
            ("https://example.com", "http", 443, True),
            ("http://example.com", "http", 80, False),
            ("socks5h://example.com", "socks5", 1080, None),
        ):
            node = self.parse(uri)
            self.assertEqual(node["type"], kind)
            self.assertEqual(node["port"], port)
            self.assertEqual(node.get("tls"), tls)
            self.assertNotIn("username", node)

    def test_trojan_implies_tls_without_query(self):
        self.assertTrue(self.parse("trojan://password@example.com:443")["tls"])

    def test_false_tls_string_is_not_truthy(self):
        node = {"type": "vless", "name": "test", "server": "example.com", "port": 80, "uuid": UUID, "tls": "false"}
        uri = clash_proxy_to_uri(node)[1]
        self.assertEqual(parse_qs(urlsplit(uri).query)["security"], ["none"])
        self.assertFalse(self.parse(uri)["tls"])

    def test_mieru_multiple_pairs_and_ranges(self):
        nodes = v2ray_uris_to_clash_proxies([
            "mierus://user:secret@example.com?port=1000-1010&protocol=TCP&port=2000&protocol=UDP#multi"
        ])
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0]["port-range"], "1000-1010")
        self.assertEqual(nodes[1]["port"], 2000)
        self.assertEqual(nodes[1]["transport"], "UDP")
        self.assertEqual([p["name"] for p in nodes], ["multi-1", "multi-2"])
        ok, uri = clash_proxy_to_uri(nodes[0])
        self.assertTrue(ok, uri)
        self.assertEqual(self.parse(uri), nodes[0])

    def test_vmess_urlsafe_json(self):
        obj = {"ps": "external", "add": "example.com", "port": "443", "id": UUID,
               "aid": "0", "net": "grpc", "path": "service", "tls": "tls", "alpn": "h2"}
        node = self.parse("VMESS://" + b64(json.dumps(obj)))
        self.assertEqual(node["grpc-opts"], {"grpc-service-name": "service"})
        self.assertEqual(node["alpn"], ["h2"])

    def test_vmess_aead_uri(self):
        node = self.parse("vmess://" + UUID + "@example.com:443?encryption=auto&security=tls&type=ws&path=%2Fws")
        self.assertEqual(node["uuid"], UUID)
        self.assertTrue(node["tls"])
        self.assertEqual(node["ws-opts"]["path"], "/ws")

    def test_wireguard_v2rayn_format(self):
        uri = "wireguard://" + quote(KEY, safe="") + "@example.com:51820?" + urlencode({
            "publickey": KEY, "presharedkey": KEY, "address": "10.0.0.2/32,fd00::2/128",
            "reserved": "1,2,3", "mtu": "1420", "dns": "1.1.1.1"})
        node = self.parse(uri)
        self.assertEqual(node["private-key"], KEY)
        self.assertEqual(node["reserved"], [1, 2, 3])
        self.assertEqual(node["ipv6"], "fd00::2/128")
        self.assertEqual(self.parse(clash_proxy_to_uri(node)[1]), node)

    def test_ssh_password_link(self):
        node = self.parse("ssh://user:pass%40word@example.com")
        self.assertEqual(node["port"], 22)
        self.assertEqual(node["password"], "pass@word")


class TestTransports(unittest.TestCase):
    def test_vless_and_trojan_transports_preserve_options(self):
        transports = [
            {"network": "tcp"},
            {"network": "ws", "ws-opts": {"path": "/ws", "headers": {"Host": "cdn.example"},
                                          "max-early-data": 2048, "early-data-header-name": "Sec-WebSocket-Protocol"}},
            {"network": "grpc", "grpc-opts": {"grpc-service-name": "service"}},
            {"network": "h2", "h2-opts": {"path": "/h2", "host": ["cdn.example"]}},
            {"network": "http", "http-opts": {"path": ["/http"], "headers": {"Host": ["cdn.example"]}, "method": "GET"}},
            {"network": "httpupgrade", "ws-opts": {"path": "/up", "headers": {"Host": "cdn.example"},
                                                   "v2ray-http-upgrade-fast-open": True}},
            {"network": "xhttp", "xhttp-opts": {"path": "/x", "host": "cdn.example", "mode": "auto",
                                               "headers": {"X-Test": "value"}, "no-grpc-header": True,
                                               "reuse-settings": {"max-connections": "2"}}},
        ]
        for kind in ("vless", "trojan", "vmess"):
            for transport in transports:
                with self.subTest(kind=kind, transport=transport["network"]):
                    node = {"type": kind, "server": "example.com", "port": 443, "name": "test",
                            "tls": True, "uuid": UUID, "password": PASSWORD, **transport}
                    ok, uri = clash_proxy_to_uri(node)
                    self.assertTrue(ok, uri)
                    back = v2ray_uris_to_clash_proxies([uri])[0]
                    for key, value in transport.items():
                        self.assertEqual(back[key], value)

    def test_reality_flow_and_fingerprint_round_trip(self):
        uri = ("vless://" + UUID + "@example.com:443?security=reality&pbk=public&sid=abc123"
               "&flow=xtls-rprx-vision&fp=chrome&support-x25519mlkem768=true&packetEncoding=xudp")
        first = v2ray_uris_to_clash_proxies([uri])[0]
        ok, exported = clash_proxy_to_uri(first)
        self.assertTrue(ok, exported)
        self.assertEqual(v2ray_uris_to_clash_proxies([exported])[0], first)


class TestFailuresAndBatchHandling(unittest.TestCase):
    def test_invalid_nodes_are_isolated(self):
        bad = [
            "vmess://invalid", "vmess://" + b64("[]"), "ss://invalid", "ssr://invalid",
            "vless://@example.com:443", "trojan://@example.com:443",
            "hy2://pass@example.com:0", "tuic://@example.com:443", "anytls://@example.com",
            "mierus://user:pass@example.com?port=1&port=2&protocol=TCP",
            "http://example.com:99999", "socks5://example.com:-1", "ssh://user@example.com",
            "wireguard://bad@example.com:51820?publickey=bad&address=10.0.0.1",
            "vless://id@example.com:443?security=reality",
            "vless://id@example.com:443?type=kcp",
        ]
        issues = []
        good = "anytls://secret@example.com:443#good"
        nodes = v2ray_uris_to_clash_proxies(bad + [good], issues)
        self.assertEqual(len(nodes), 1, issues)
        self.assertEqual(nodes[0]["name"], "good")
        self.assertEqual(len(issues), len(bad))

    def test_error_diagnostics_do_not_contain_credentials(self):
        secret = "TOP_SECRET_123"
        issues = []
        v2ray_uris_to_clash_proxies([
            "unknown://" + secret + "@example.com:443",
            "http://" + secret + "@example.com:bad",
            "anytls://" + secret + "@example.com:443?insecure=" + secret,
        ], issues)
        self.assertEqual(len(issues), 3)
        self.assertNotIn(secret, json.dumps(issues))

    def test_export_invalid_entries_does_not_break_valid_nodes(self):
        issues = []
        nodes = [None, 3, [], {}, {"type": "vmess", "server": "example.com", "port": 443, "alterId": "bad"}]
        nodes += [{"type": kind, "server": "example.com", "port": 443} for kind in YAML_ONLY_PROTOCOLS]
        nodes += [fixtures()[0]]
        result = clash_yaml_to_v2ray_uris({"proxies": nodes}, issues)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(issues), len(nodes) - 1)

    def test_unknown_ss_plugin_is_explicitly_rejected(self):
        issues = []
        uri = "ss://" + b64("aes-128-gcm:password") + "@example.com:443?plugin=unknown%3Bkey%3Dvalue"
        self.assertEqual(v2ray_uris_to_clash_proxies([uri], issues), [])
        self.assertIn("plugin", issues[0]["reason"])

    def test_unsupported_fields_reported(self):
        node = dict(fixtures()[0], **{"tfo": True, "routing-mark": 100})
        issues = []
        self.assertEqual(len(clash_yaml_to_v2ray_uris({"proxies": [node]}, issues)), 1)
        self.assertEqual(issues[0]["severity"], "warning")
        self.assertIn("routing-mark", issues[0]["reason"])

    def test_ssh_host_keys_are_not_silently_discarded(self):
        node = dict(fixtures()[-1], **{"host-key": ["pinned-key"]})
        ok, reason = clash_proxy_to_uri(node)
        self.assertFalse(ok)
        self.assertIn("native YAML", reason)

    def test_duplicate_and_reserved_names(self):
        uris = ["anytls://pass@example.com#DIRECT", "anytls://pass@example.com#test",
                "anytls://pass@example.com#test-2", "anytls://pass@example.com#test"]
        nodes = v2ray_uris_to_clash_proxies(uris)
        names = [p["name"] for p in nodes]
        self.assertEqual(len(names), len(set(names)))
        self.assertNotIn("DIRECT", names)
        doc = build_clashplay_yaml(nodes)
        self.assertEqual(set(doc["proxy-groups"][0]["proxies"]), {"DIRECT", *names})

    def test_concatenated_base64_and_unknown_lines(self):
        raw = "anytls://p@example.com#onehy2://p@example.com#two"
        self.assertEqual(len(split_v2ray_text(b64(raw))), 2)
        records = split_v2ray_text("# comment\n" + raw + "\nunknown://x@example.com\n; ignored")
        issues = []
        self.assertEqual(len(v2ray_uris_to_clash_proxies(records, issues)), 2)
        self.assertEqual(len(issues), 1)

    def test_nested_url_in_query_not_split(self):
        raw = "vless://id@example.com:443?type=ws&path=/ws?target=http://nested.example#test"
        self.assertEqual(split_v2ray_text(raw), [raw])

    def test_legacy_export_aliases_still_work(self):
        node = {"type": "trojan", "server": "example.com", "port": 443, "pass": PASSWORD,
                "network": "ws", "path": "/legacy", "host": "cdn.example"}
        ok, uri = clash_proxy_to_uri(node)
        self.assertTrue(ok, uri)
        back = v2ray_uris_to_clash_proxies([uri])[0]
        self.assertEqual(back["password"], PASSWORD)
        self.assertEqual(back["ws-opts"], {"path": "/legacy", "headers": {"Host": "cdn.example"}})

    def test_nested_omitted_fields_are_reported(self):
        node = copy.deepcopy(fixtures()[0])
        node["ws-opts"]["max-message-size"] = 1000
        issues = []
        self.assertEqual(len(clash_yaml_to_v2ray_uris({"proxies": [node]}, issues)), 1)
        self.assertIn("ws-opts.max-message-size", issues[0]["reason"])

    def test_custom_certificate_is_not_discarded(self):
        node = dict(fixtures()[0], certificate="certificate-data")
        self.assertFalse(clash_proxy_to_uri(node)[0])


if __name__ == "__main__":
    unittest.main()
