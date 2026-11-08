from typing import Dict, List

SINGBOX_SUPPORTED_TYPES = {
    "ss", "vmess", "vless", "trojan", "hysteria2", "tuic", "anytls",
    "socks5", "http", "wireguard",
}


def build_singbox_config(proxies: List[Dict]) -> Dict:
    outbounds = []
    tags = []
    for source in proxies or []:
        item = dict(source)
        kind = str(item.get("type") or "").lower()
        if not is_singbox_supported(item):
            continue
        name = str(item.get("name") or kind or "proxy")
        base = {"tag": name, "server": item.get("server"), "server_port": item.get("port")}

        if kind == "ss":
            outbound = {
                **base, "type": "shadowsocks",
                "method": item.get("cipher"),
                "password": item.get("password") or item.get("pass"),
            }
        elif kind == "socks5":
            outbound = {**base, "type": "socks", "version": "5"}
            if item.get("username"):
                outbound["username"] = item["username"]
            if item.get("password"):
                outbound["password"] = item["password"]
            _add_tls(outbound, item)
        elif kind == "http":
            outbound = {**base, "type": "http"}
            if item.get("username"):
                outbound["username"] = item["username"]
            if item.get("password"):
                outbound["password"] = item["password"]
            _add_tls(outbound, item)
        elif kind == "wireguard":
            outbound = {
                **base, "type": "wireguard",
                "private_key": item.get("private-key"),
                "peer_public_key": item.get("public-key"),
                "local_address": [value for value in (item.get("ip"), item.get("ipv6")) if value],
            }
            if item.get("pre-shared-key"):
                outbound["pre_shared_key"] = item["pre-shared-key"]
            if item.get("mtu"):
                outbound["mtu"] = item["mtu"]
        elif kind in ("vmess", "vless", "trojan"):
            outbound = {**base, "type": kind}
            if kind == "vmess":
                outbound.update({
                    "uuid": item.get("uuid"),
                    "security": item.get("cipher") or "auto",
                    "alter_id": int(item.get("alterId") or 0),
                })
            elif kind == "vless":
                outbound["uuid"] = item.get("uuid")
                if item.get("flow"):
                    outbound["flow"] = item["flow"]
            else:
                outbound["password"] = item.get("password") or item.get("pass")
            _add_tls(outbound, item)
            _add_transport(outbound, item)
        elif kind == "hysteria2":
            outbound = {
                **base, "type": "hysteria2",
                "password": item.get("password") or item.get("pass"),
            }
            _add_tls(outbound, item)
            if item.get("obfs"):
                outbound["obfs"] = {
                    "type": item["obfs"],
                    "password": item.get("obfs-password") or "",
                }
            if item.get("up") is not None:
                outbound["up_mbps"] = item["up"]
            if item.get("down") is not None:
                outbound["down_mbps"] = item["down"]
        elif kind == "tuic":
            outbound = {
                **base, "type": "tuic",
                "uuid": item.get("uuid"),
                "password": item.get("password") or item.get("pass"),
            }
            _add_tls(outbound, item, required=True)
            if item.get("congestion-controller"):
                outbound["congestion_control"] = item["congestion-controller"]
            if item.get("udp-relay-mode"):
                outbound["udp_relay_mode"] = item["udp-relay-mode"]
        elif kind == "anytls":
            outbound = {
                **base, "type": "anytls",
                "password": item.get("password") or item.get("pass"),
            }
            _add_tls(outbound, item, required=True)
        else:
            continue

        outbounds.append(outbound)
        tags.append(name)

    selector = {"type": "selector", "tag": "proxy", "outbounds": ["direct"] + tags}
    return {
        "log": {"level": "info"},
        "outbounds": [{"type": "direct", "tag": "direct"}, selector] + outbounds,
        "route": {"final": "proxy"},
    }


def _add_tls(outbound: Dict, proxy: Dict, required: bool = False) -> None:
    reality = proxy.get("reality-opts")
    if not (required or proxy.get("tls") or reality):
        return
    tls = {"enabled": True}
    server_name = proxy.get("sni") or proxy.get("servername")
    if server_name:
        tls["server_name"] = server_name
    if proxy.get("skip-cert-verify") is not None:
        value = proxy.get("skip-cert-verify")
        tls["insecure"] = value.strip().lower() in ("1", "true", "yes", "on") if isinstance(value, str) else bool(value)
    if isinstance(reality, dict):
        tls["reality"] = {
            "enabled": True,
            "public_key": reality.get("public-key") or reality.get("public_key"),
            "short_id": reality.get("short-id") or reality.get("short_id") or "",
        }
    outbound["tls"] = tls


def is_singbox_supported(proxy: Dict) -> bool:
    kind = str(proxy.get("type") or "").lower()
    if kind not in SINGBOX_SUPPORTED_TYPES:
        return False
    if kind == "ss" and proxy.get("plugin"):
        return False
    if kind == "wireguard" and (proxy.get("peers") or proxy.get("amnezia-wg-option")):
        return False
    if kind in ("vmess", "vless", "trojan"):
        network = str(proxy.get("network") or "tcp").lower()
        if network not in ("tcp", "ws", "grpc", "httpupgrade"):
            return False
    return True


def _add_transport(outbound: Dict, proxy: Dict) -> None:
    network = str(proxy.get("network") or "").lower()
    if network == "ws":
        options = proxy.get("ws-opts") or {}
        transport = {"type": "ws", "path": options.get("path") or "/"}
        headers = options.get("headers") or {}
        host = headers.get("Host") or headers.get("host")
        if host:
            transport["headers"] = {"Host": host}
        outbound["transport"] = transport
    elif network == "grpc":
        options = proxy.get("grpc-opts") or {}
        outbound["transport"] = {
            "type": "grpc",
            "service_name": options.get("grpc-service-name") or "",
        }
    elif network == "httpupgrade":
        options = proxy.get("ws-opts") or {}
        outbound["transport"] = {"type": "httpupgrade", "path": options.get("path") or "/"}


def build_custom_clash_template(proxies: List[Dict], template_text: str) -> Dict:
    import yaml
    doc = yaml.safe_load(template_text) if (template_text or "").strip() else {}
    if not isinstance(doc, dict):
        raise ValueError("Clash template must be a YAML mapping")
    names = [str(item.get("name") or "") for item in proxies if item.get("name")]
    doc["proxies"] = proxies
    if not isinstance(doc.get("proxy-groups"), list) or not doc["proxy-groups"]:
        doc["proxy-groups"] = [{"name": "选择代理节点", "type": "select", "proxies": ["DIRECT"] + names}]
    if not isinstance(doc.get("rules"), list) or not doc["rules"]:
        doc["rules"] = ["MATCH,选择代理节点"]
    return doc
