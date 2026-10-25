"""Proxy share-link codecs. Never log URI bodies: they contain credentials.

Formats follow Mihomo common/convert, SIP002, and upstream share-link specs.
Only protocols with an interoperable share-link representation belong here.
"""

import base64
import binascii
import copy
import ipaddress
import json
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit


SUPPORTED_PROTOCOLS = (
    "vmess", "vless", "trojan", "ss", "ssr", "socks5", "http",
    "hysteria", "hysteria2", "tuic", "anytls", "mieru", "wireguard", "ssh",
)
SCHEME_TYPES = {name: name for name in SUPPORTED_PROTOCOLS}
SCHEME_TYPES.update({
    "shadowsocks": "ss", "socks": "socks5", "socks5h": "socks5",
    "https": "http", "hy2": "hysteria2", "mierus": "mieru",
})
YAML_ONLY_PROTOCOLS = (
    "snell", "shadowquic", "gost-relay",
    "sudoku", "masque", "trusttunnel", "openvpn", "tailscale",
    "zerotier", "easytier",
)


class ProtocolError(ValueError):
    """An actionable conversion error, without embedding secrets."""


def _b64e(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _b64d(value: str) -> str:
    compact = re.sub(r"\s+", "", unquote(value))
    try:
        return base64.b64decode(compact + "=" * (-len(compact) % 4),
                                altchars=b"-_", validate=True).decode("utf-8")
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ProtocolError("invalid Base64 payload") from exc


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip().lower()
    if value in (1, "1", "true", "yes", "on"):
        return True
    if value in (0, None, "", "0", "false", "no", "off"):
        return False
    raise ProtocolError("invalid boolean option")


def _port(value) -> int:
    try:
        if isinstance(value, bool):
            raise ValueError
        result = int(str(value))
        if not 1 <= result <= 65535:
            raise ValueError
        return result
    except (ValueError, TypeError) as exc:
        raise ProtocolError("port must be between 1 and 65535") from exc


def _first(query, *keys, default=None):
    for key in keys:
        values = query.get(key)
        if values:
            return values[0]
    return default


def _required(proxy, key):
    value = proxy.get(key)
    if value is None or value == "":
        raise ProtocolError("missing " + key)
    return str(value)


def _host(server) -> str:
    if not isinstance(server, str) or not server or re.search(r"[\s/@?#]", server):
        raise ProtocolError("invalid server")
    host = server.strip("[]")
    if ":" in host:
        try:
            ipaddress.IPv6Address(host)
        except ValueError as exc:
            raise ProtocolError("invalid IPv6 server") from exc
    return "[" + host + "]" if ":" in host else host


def _uri(scheme, proxy, auth="", params=None, port=None) -> str:
    authority = _host(proxy.get("server"))
    if port is False:
        pass
    elif port is not None:
        authority += ":" + str(port)
    else:
        authority += ":" + str(_port(proxy.get("port")))
    query = urlencode(params or {}, doseq=True)
    return (scheme + "://" + (auth + "@" if auth else "") + authority
            + ("?" + query if query else "")
            + "#" + quote(str(proxy.get("name") or scheme), safe=""))


def _issue(issues, index, protocol, reason, severity="error"):
    if issues is not None:
        issues.append({"index": index, "protocol": protocol,
                       "reason": reason, "severity": severity})


def _port_ranges(value):
    text = str(value)
    for item in text.split(","):
        bounds = item.split("-")
        if len(bounds) not in (1, 2):
            raise ProtocolError("invalid port range")
        numbers = [_port(v) for v in bounds]
        if len(numbers) == 2 and numbers[0] > numbers[1]:
            raise ProtocolError("invalid port range")
    return text


def _base(uri, kind):
    parsed = urlsplit(uri)
    server = parsed.hostname
    _host(server)
    query = parse_qs(parsed.query, keep_blank_values=True)
    ports = None
    if kind == "hysteria2":
        authority = parsed.netloc.rsplit("@", 1)[-1]
        tail = authority.rsplit(":", 1)[-1] if ":" in authority and not authority.endswith("]") else ""
        if "," in tail or "-" in tail:
            ports = _port_ranges(tail)
            port = _port(re.split("[,-]", ports)[0])
        else:
            port = parsed.port if parsed.port is not None else 443
    elif kind == "mieru":
        port = None  # Each port/protocol pair is expanded separately below.
    else:
        default = {"anytls": 443, "http": 443 if parsed.scheme.lower() == "https" else 80,
                   "socks5": 1080, "ssh": 22}.get(kind)
        port = parsed.port if parsed.port is not None else default
    proxy = {"name": unquote(parsed.fragment) or kind + "-" + server,
             "type": kind, "server": server}
    if port is not None:
        proxy["port"] = _port(port)
    elif kind != "mieru":
        raise ProtocolError("missing port")
    if ports:
        proxy["ports"] = ports
    return proxy, parsed, query


def _tls_in(proxy, query):
    kind = proxy["type"]
    sni = _first(query, "sni", "servername", "peer")
    if sni:
        proxy["servername" if kind in ("vmess", "vless") else "sni"] = sni
    if "alpn" in query:
        proxy["alpn"] = [v for item in query["alpn"] for v in item.split(",") if v]
    insecure = _first(query, "insecure", "allowInsecure", "allow_insecure", "skip-cert-verify")
    if insecure is not None:
        proxy["skip-cert-verify"] = _bool(insecure)
    fp = _first(query, "fp", "client-fingerprint")
    if fp:
        proxy["client-fingerprint"] = fp
    pin = _first(query, "pinSHA256", "hpkp", "pcs")
    if pin:
        proxy["fingerprint"] = pin
    if kind in ("vmess", "vless", "trojan"):
        security = _first(query, "security", default="tls" if kind == "trojan" else "none").lower()
        if security not in ("none", "tls", "reality", ""):
            raise ProtocolError("unsupported TLS security mode")
        proxy["tls"] = security in ("tls", "reality") or _bool(_first(query, "tls"))
        pbk = _first(query, "pbk", "public-key")
        sid = _first(query, "sid", "short-id")
        if security == "reality" or pbk:
            if not pbk:
                raise ProtocolError("Reality requires a public key")
            proxy["tls"] = True
            proxy["reality-opts"] = {"public-key": pbk}
            if sid is not None:
                proxy["reality-opts"]["short-id"] = sid
            if "support-x25519mlkem768" in query:
                proxy["reality-opts"]["support-x25519mlkem768"] = _bool(query["support-x25519mlkem768"][0])


def _tls_out(proxy):
    params = {}
    sni = proxy.get("servername") or proxy.get("sni")
    if sni:
        params["sni"] = sni
    if "alpn" in proxy:
        value = proxy["alpn"]
        params["alpn"] = ",".join(value) if isinstance(value, list) else str(value)
    if "skip-cert-verify" in proxy:
        params["insecure"] = "1" if _bool(proxy["skip-cert-verify"]) else "0"
    if proxy.get("client-fingerprint"):
        params["fp"] = proxy["client-fingerprint"]
    if proxy.get("fingerprint"):
        key = {"hysteria2": "pinSHA256", "anytls": "hpkp"}.get(proxy["type"], "pcs")
        params[key] = proxy["fingerprint"]
    if proxy["type"] in ("vmess", "vless", "trojan"):
        reality = proxy.get("reality-opts") or {}
        params["security"] = "reality" if reality else "tls" if _bool(proxy.get("tls", proxy["type"] == "trojan")) else "none"
        if reality:
            params["pbk"] = _required(reality, "public-key")
            if "short-id" in reality:
                params["sid"] = reality["short-id"]
            if "support-x25519mlkem768" in reality:
                params["support-x25519mlkem768"] = str(_bool(reality["support-x25519mlkem768"])).lower()
    return params


# Common Xray XHTTP extra fields and their Mihomo equivalents.
_XHTTP_EXTRA = {
    "headers": "headers", "noGRPCHeader": "no-grpc-header", "xPaddingBytes": "x-padding-bytes",
    "xPaddingObfsMode": "x-padding-obfs-mode", "xPaddingKey": "x-padding-key",
    "xPaddingHeader": "x-padding-header", "xPaddingPlacement": "x-padding-placement",
    "xPaddingMethod": "x-padding-method", "uplinkHTTPMethod": "uplink-http-method",
    "sessionIDPlacement": "session-placement", "sessionIDKey": "session-key",
    "sessionIDTable": "session-table", "sessionIDLength": "session-length",
    "seqPlacement": "seq-placement", "seqKey": "seq-key",
    "uplinkDataPlacement": "uplink-data-placement", "uplinkDataKey": "uplink-data-key",
    "uplinkChunkSize": "uplink-chunk-size", "scMaxEachPostBytes": "sc-max-each-post-bytes",
    "scMinPostsIntervalMs": "sc-min-posts-interval-ms",
}
_XMUX = {"maxConnections": "max-connections", "maxConcurrency": "max-concurrency",
         "cMaxReuseTimes": "c-max-reuse-times", "hMaxRequestTimes": "h-max-request-times",
         "hMaxReusableSecs": "h-max-reusable-secs", "hKeepAlivePeriod": "h-keep-alive-period"}


def _transport_in(proxy, query):
    network = _first(query, "type", default="tcp").lower()
    if network == "tcp" and _first(query, "headerType") == "http":
        network = "http"
    elif network == "http":
        network = "h2"
    if network not in ("tcp", "ws", "grpc", "http", "h2", "httpupgrade", "xhttp"):
        raise ProtocolError("unsupported transport")
    proxy["network"] = network
    host = _first(query, "host", default="")
    path = _first(query, "path", default="")
    if network in ("ws", "httpupgrade"):
        opts = {"path": path, "headers": {"Host": host} if host else {}}
        if "ed" in query:
            early = int(query["ed"][0])
            if early < 0:
                raise ProtocolError("invalid early-data size")
            if network == "ws":
                opts.update({"max-early-data": early, "early-data-header-name": "Sec-WebSocket-Protocol"})
            else:
                opts["v2ray-http-upgrade-fast-open"] = bool(early)
        if "eh" in query:
            opts["early-data-header-name"] = query["eh"][0]
        proxy["ws-opts"] = opts
    elif network == "grpc":
        proxy["grpc-opts"] = {"grpc-service-name": _first(query, "serviceName", default="")}
    elif network == "h2":
        proxy["h2-opts"] = {"path": path or "/", "host": [host] if host else []}
    elif network == "http":
        proxy["http-opts"] = {"path": [path or "/"], "headers": {"Host": [host]} if host else {}}
        if "method" in query:
            proxy["http-opts"]["method"] = query["method"][0]
    elif network == "xhttp":
        opts = {"path": path, "host": host}
        if "mode" in query:
            opts["mode"] = query["mode"][0]
        if "extra" in query:
            extra = json.loads(query["extra"][0])
            if not isinstance(extra, dict) or set(extra) - set(_XHTTP_EXTRA) - {"xmux"}:
                raise ProtocolError("unsupported XHTTP extra settings; retain native YAML")
            opts.update({dst: extra[src] for src, dst in _XHTTP_EXTRA.items() if src in extra})
            if "xmux" in extra:
                if not isinstance(extra["xmux"], dict) or set(extra["xmux"]) - set(_XMUX):
                    raise ProtocolError("unsupported XHTTP reuse settings")
                opts["reuse-settings"] = {dst: (value if dst == "h-keep-alive-period" else str(value))
                                         for src, value in extra["xmux"].items() for dst in [_XMUX[src]]}
        proxy["xhttp-opts"] = opts
    packet = _first(query, "packetEncoding")
    if packet == "packet":
        proxy["packet-addr"] = True
    elif packet == "xudp":
        proxy["xudp"] = True


def _transport_out(proxy):
    network = str(proxy.get("network") or "tcp").lower()
    params = {"type": network}
    if network in ("ws", "httpupgrade"):
        opts = proxy.get("ws-opts") or {}
        params["path"] = opts.get("path", "")
        headers = opts.get("headers") or {}
        if set(headers) - {"Host", "host"}:
            raise ProtocolError("non-Host WebSocket headers require native YAML")
        if headers.get("Host") or headers.get("host"):
            params["host"] = headers.get("Host") or headers["host"]
        if "max-early-data" in opts:
            params["ed"] = opts["max-early-data"]
        elif opts.get("v2ray-http-upgrade-fast-open"):
            params["ed"] = 1
        if opts.get("early-data-header-name"):
            params["eh"] = opts["early-data-header-name"]
    elif network == "grpc":
        opts = proxy.get("grpc-opts") or {}
        params["serviceName"] = opts.get("grpc-service-name", "")
    elif network in ("http", "h2"):
        opts = proxy.get(network + "-opts") or {}
        hosts = (opts.get("headers") or {}).get("Host", []) if network == "http" else opts.get("host", [])
        paths = opts.get("path", "/")
        if isinstance(hosts, list) and len(hosts) > 1 or isinstance(paths, list) and len(paths) > 1:
            raise ProtocolError("multiple transport hosts or paths require native YAML")
        params["host"] = hosts[0] if isinstance(hosts, list) and hosts else hosts or ""
        params["path"] = paths[0] if isinstance(paths, list) and paths else paths or "/"
        params["type"] = "tcp" if network == "http" else "http"
        if network == "http":
            params["headerType"] = "http"
            if opts.get("method"):
                params["method"] = opts["method"]
    elif network == "xhttp":
        opts = proxy.get("xhttp-opts") or {}
        known = {"path", "host", "mode", "reuse-settings"} | set(_XHTTP_EXTRA.values())
        if set(opts) - known:
            raise ProtocolError("unsupported XHTTP options; retain native YAML")
        params.update({k: opts[k] for k in ("path", "host", "mode") if k in opts})
        extra = {src: opts[dst] for src, dst in _XHTTP_EXTRA.items() if dst in opts}
        reuse = opts.get("reuse-settings") or {}
        if set(reuse) - set(_XMUX.values()):
            raise ProtocolError("unsupported XHTTP reuse settings")
        if reuse:
            extra["xmux"] = {src: reuse[dst] for src, dst in _XMUX.items() if dst in reuse}
        if extra:
            params["extra"] = json.dumps(extra, ensure_ascii=False, separators=(",", ":"))
    elif network != "tcp":
        raise ProtocolError("unsupported transport; retain native YAML")
    if proxy.get("packet-addr"):
        params["packetEncoding"] = "packet"
    elif proxy.get("xudp"):
        params["packetEncoding"] = "xudp"
    return params


def _parse_ss(uri):
    body = uri.split("://", 1)[1]
    body, _, fragment = body.partition("#")
    body, _, query_text = body.partition("?")
    body = body.rstrip("/")
    if "@" not in body:
        body = _b64d(body)
    user, separator, address = body.rpartition("@")
    if not separator:
        raise ProtocolError("missing SS credentials or endpoint")
    credentials = unquote(user) if ":" in user else _b64d(user)
    cipher, separator, password = credentials.partition(":")
    if not separator or not cipher or not password:
        raise ProtocolError("missing SS cipher or password")
    proxy, _, _ = _base("ss://" + address + "#" + fragment, "ss")
    proxy.update({"cipher": cipher, "password": password})
    query = parse_qs(query_text, keep_blank_values=True)
    if _first(query, "uot", "udp-over-tcp") is not None:
        proxy["udp-over-tcp"] = _bool(_first(query, "uot", "udp-over-tcp"))
    plugin = _first(query, "plugin")
    if plugin:
        parts = plugin.split(";")
        options = {}
        for part in parts[1:]:
            key, sep, value = part.partition("=")
            options[key] = value if sep else True
        if parts[0] in ("obfs", "obfs-local", "simple-obfs"):
            proxy["plugin"] = "obfs"
            proxy["plugin-opts"] = {"mode": options.get("obfs", "http"), "host": options.get("obfs-host", "")}
            if set(options) - {"obfs", "obfs-host"}:
                raise ProtocolError("unsupported obfs plugin options")
        elif parts[0] == "v2ray-plugin":
            if set(options) - {"mode", "host", "path", "tls", "mux", "skip-cert-verify"}:
                raise ProtocolError("unsupported v2ray-plugin options")
            proxy["plugin"] = "v2ray-plugin"
            proxy["plugin-opts"] = {k: _bool(v) if k in ("tls", "mux", "skip-cert-verify") else v
                                     for k, v in options.items()}
        else:
            raise ProtocolError("unsupported SS plugin; retain native YAML")
    return [proxy]


def _parse_ssr(uri):
    body = _b64d(uri.split("://", 1)[1])
    endpoint, _, query_text = body.partition("/?")
    values = endpoint.rsplit(":", 5)
    if len(values) != 6:
        raise ProtocolError("invalid SSR payload")
    server, port, protocol, cipher, obfs, password = values
    _host(server)
    query = parse_qs(query_text, keep_blank_values=True)
    proxy = {"name": _b64d(_first(query, "remarks")) if _first(query, "remarks") else "ssr-" + server,
             "type": "ssr", "server": server.strip("[]"), "port": _port(port), "protocol": protocol,
             "cipher": cipher, "obfs": obfs, "password": _b64d(password)}
    for source, target in (("obfsparam", "obfs-param"), ("protoparam", "protocol-param")):
        if source in query:
            proxy[target] = _b64d(query[source][0])
    if "uot" in query:
        proxy["udp-over-tcp"] = _bool(query["uot"][0])
    for key in ("password", "cipher", "protocol", "obfs"):
        _required(proxy, key)
    return [proxy]


def _parse_vmess(uri):
    body = uri.split("://", 1)[1]
    if "@" in body:
        return _parse_url(uri, "vmess")
    obj = json.loads(_b64d(body))
    if not isinstance(obj, dict):
        raise ProtocolError("VMess payload must be a JSON object")
    server = obj.get("add")
    _host(server)
    proxy = {"name": obj.get("ps") or "vmess-" + server, "type": "vmess",
             "server": server.strip("[]"), "port": _port(obj.get("port")),
             "uuid": _required(obj, "id"), "alterId": int(obj.get("aid") or 0),
             "cipher": obj.get("scy") or "auto"}
    if proxy["alterId"] < 0:
        raise ProtocolError("invalid VMess alterId")
    query = {"type": [str(obj.get("net") or "tcp")], "host": [obj.get("host") or ""],
             "path": [obj.get("path") or ""], "security": ["tls" if str(obj.get("tls", "")).lower() == "tls" else "none"]}
    if obj.get("type") == "http":
        query.update({"type": ["tcp"], "headerType": ["http"]})
    if query["type"][0] == "grpc":
        query["serviceName"] = query["path"]
    for key in ("sni", "alpn", "fp", "allowInsecure", "insecure", "ed", "eh", "method"):
        if key in obj:
            query[key] = [str(obj[key])]
    _tls_in(proxy, query)
    _transport_in(proxy, query)
    return [proxy]


def _parse_url(uri, kind):
    proxy, parsed, query = _base(uri, kind)
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if kind in ("vmess", "vless"):
        if not username:
            raise ProtocolError("missing uuid")
        proxy["uuid"] = username
        proxy["udp"] = True
        if kind == "vmess":
            proxy.update({"alterId": 0, "cipher": _first(query, "encryption", default="auto")})
        else:
            encryption = _first(query, "encryption", default="none")
            if encryption != "none":
                proxy["encryption"] = encryption
            if "flow" in query:
                proxy["flow"] = query["flow"][0]
        _transport_in(proxy, query)
    elif kind in ("trojan", "anytls", "hysteria2"):
        if kind == "hysteria2":
            # Hysteria authentication is the complete userinfo, including any colon.
            proxy["password"] = unquote(parsed.netloc.rsplit("@", 1)[0]) if "@" in parsed.netloc else ""
        elif kind == "anytls":
            proxy["password"] = password if parsed.password is not None else username
        else:
            proxy["password"] = username
            _transport_in(proxy, query)
        _required(proxy, "password")
        proxy["udp"] = True
    elif kind in ("socks5", "http"):
        if username and parsed.password is None:
            try:
                decoded = _b64d(username)
                if ":" in decoded:
                    username, password = decoded.split(":", 1)
            except ProtocolError:
                pass  # Plain usernames without passwords are also valid.
        if parsed.username is not None:
            proxy.update({"username": username, "password": password})
        if kind == "http":
            proxy["tls"] = parsed.scheme.lower() == "https"
        elif "tls" in query:
            proxy["tls"] = _bool(query["tls"][0])
    elif kind == "tuic":
        if parsed.password is None:
            proxy["token"] = username
            _required(proxy, "token")
        else:
            proxy.update({"uuid": username, "password": password})
            _required(proxy, "uuid")
            _required(proxy, "password")
        proxy["udp"] = True
        for source, target in (("congestion_control", "congestion-controller"), ("udp_relay_mode", "udp-relay-mode")):
            value = _first(query, source, target)
            if value is not None:
                proxy[target] = value
        for source, target in (("disable_sni", "disable-sni"), ("reduce_rtt", "reduce-rtt")):
            value = _first(query, source, target)
            if value is not None:
                proxy[target] = _bool(value)
    elif kind == "ssh":
        if not username or not password:
            raise ProtocolError("SSH share links require username and password; use YAML for key authentication")
        proxy.update({"username": username, "password": password})
    elif kind == "wireguard":
        proxy["private-key"] = username
        proxy["public-key"] = _first(query, "publickey", "public-key")
        for key in ("private-key", "public-key"):
            _wireguard_key(_required(proxy, key))
        psk = _first(query, "presharedkey", "pre-shared-key")
        if psk:
            _wireguard_key(psk)
            proxy["pre-shared-key"] = psk
        addresses = _first(query, "address", default="")
        for value in addresses.split(","):
            if value.strip():
                address = ipaddress.ip_interface(value.strip())
                target = "ip" if address.version == 4 else "ipv6"
                if target in proxy:
                    raise ProtocolError("multiple WireGuard addresses of the same family require native YAML")
                proxy[target] = str(address)
        if not proxy.get("ip") and not proxy.get("ipv6"):
            raise ProtocolError("WireGuard requires an interface address")
        if "reserved" in query:
            raw = query["reserved"][0]
            if re.fullmatch(r"[0-9]+,[0-9]+,[0-9]+", raw):
                reserved = [int(value) for value in raw.split(",")]
            else:
                reserved = list(base64.b64decode(raw, validate=True))
            if len(reserved) != 3 or any(not 0 <= value <= 255 for value in reserved):
                raise ProtocolError("WireGuard reserved must contain three bytes")
            proxy["reserved"] = reserved
        if "mtu" in query:
            mtu = int(query["mtu"][0])
            if not 576 <= mtu <= 65535:
                raise ProtocolError("invalid WireGuard MTU")
            proxy["mtu"] = mtu
        if "dns" in query:
            proxy["dns"] = [str(ipaddress.ip_address(v.strip())) for v in query["dns"][0].split(",")]
        if "fm" in query:
            raise ProtocolError("Xray finalmask settings have no Mihomo equivalent")
    elif kind == "hysteria":
        for target, aliases in {"auth-str": ("auth", "auth_str"), "protocol": ("protocol",),
                                "obfs": ("obfs",), "up": ("up", "upmbps"), "down": ("down", "downmbps")}.items():
            value = _first(query, *aliases)
            if value is not None:
                proxy[target] = value
    elif kind == "mieru":
        if not username or not password:
            raise ProtocolError("missing Mieru username or password")
        proxy.update({"username": username, "password": password})
        ports = query.get("port") or ([str(parsed.port)] if parsed.port else [])
        transports = query.get("protocol") or ["TCP"] * len(ports)
        if not ports or len(ports) != len(transports):
            raise ProtocolError("Mieru port/protocol counts do not match")
        for key in ("multiplexing", "handshake-mode", "traffic-pattern"):
            if key in query:
                proxy[key] = query[key][0]
        proxies = []
        for index, (port, transport) in enumerate(zip(ports, transports), 1):
            item = dict(proxy)
            transport = transport.upper()
            if transport not in ("TCP", "UDP"):
                raise ProtocolError("unsupported Mieru transport")
            item["transport"] = transport
            if "-" in port:
                item["port-range"] = _port_ranges(port)
            else:
                item["port"] = _port(port)
            if len(ports) > 1:
                item["name"] += "-" + str(index)
            proxies.append(item)
        return proxies
    _tls_in(proxy, query)
    if kind == "hysteria2":
        for key in ("obfs", "obfs-password", "up", "down", "hop-interval"):
            if key in query:
                proxy[key] = query[key][0]
        ports = _first(query, "mport", "ports")
        if ports:
            proxy["ports"] = _port_ranges(ports.replace(":", "-"))
    if "udp" in query:
        proxy["udp"] = _bool(query["udp"][0])
    return [proxy]


def parse_uri(uri):
    if not isinstance(uri, str) or "://" not in uri:
        raise ProtocolError("expected a proxy share URI")
    uri = uri.strip()
    if re.search(r"[\x00-\x20\x7f]", uri):
        raise ProtocolError("URI contains unescaped whitespace or control characters")
    scheme, body = uri.strip().split("://", 1)
    kind = SCHEME_TYPES.get(scheme.lower())
    if kind is None:
        raise ProtocolError("unsupported share-link protocol; retain native YAML")
    # Normalize the scheme only; credentials and case-sensitive paths stay intact.
    normalized = scheme.lower() + "://" + body
    if kind == "ss":
        return _parse_ss(normalized)
    if kind == "ssr":
        return _parse_ssr(normalized)
    if kind == "vmess":
        return _parse_vmess(normalized)
    return _parse_url(normalized, kind)


def export_uri(proxy):
    if not isinstance(proxy, dict):
        raise ProtocolError("node must be a mapping")
    proxy = copy.deepcopy(proxy)
    kind = str(proxy.get("type") or "").lower()
    kind = {"shadowsocks": "ss", "https": "http", "socks": "socks5", "hy2": "hysteria2"}.get(kind, kind)
    if kind not in SUPPORTED_PROTOCOLS:
        raise ProtocolError("no interoperable share-link codec; retain native YAML")
    proxy["type"] = kind
    if "password" not in proxy and "pass" in proxy:
        proxy["password"] = proxy["pass"]
    if isinstance(proxy.get("reality-opts"), dict):
        reality = proxy["reality-opts"]
        for source, target in (("public_key", "public-key"), ("short_id", "short-id")):
            if source in reality and target not in reality:
                reality[target] = reality[source]
    if kind in ("vmess", "vless", "trojan"):
        network = str(proxy.get("network") or "tcp").lower()
        if network in ("ws", "httpupgrade"):
            opts = proxy.setdefault("ws-opts", {}) or {}
            proxy["ws-opts"] = opts
            if "path" not in opts and proxy.get("path"):
                opts["path"] = proxy["path"]
            if proxy.get("host") and not (opts.get("headers") or {}).get("Host"):
                opts.setdefault("headers", {})["Host"] = proxy["host"]
        elif network == "grpc" and proxy.get("serviceName"):
            proxy.setdefault("grpc-opts", {}).setdefault("grpc-service-name", proxy["serviceName"])
        if kind == "vmess" and proxy.get("host") and not proxy.get("servername") and not proxy.get("sni"):
            proxy["servername"] = proxy["host"]
    if any(proxy.get(key) for key in ("ech-opts", "certificate", "realm-opts")):
        raise ProtocolError("ECH, custom certificates, or realm settings require native YAML")
    if kind not in ("ssh", "wireguard") and proxy.get("private-key"):
        raise ProtocolError("client certificate authentication requires native YAML")
    _host(proxy.get("server"))
    if kind != "mieru" or not proxy.get("port-range"):
        _port(proxy.get("port"))
    if kind == "ssh":
        if any(proxy.get(key) for key in ("private-key", "private-key-passphrase", "host-key", "host-key-algorithms")):
            raise ProtocolError("SSH keys and host-key verification require native YAML")
        auth = quote(_required(proxy, "username"), safe="") + ":" + quote(_required(proxy, "password"), safe="")
        return _uri("ssh", proxy, auth)
    if kind == "wireguard":
        if any(proxy.get(key) for key in ("peers", "amnezia-wg-option")):
            raise ProtocolError("multi-peer or Amnezia WireGuard settings require native YAML")
        private = _required(proxy, "private-key")
        public = _required(proxy, "public-key")
        _wireguard_key(private)
        _wireguard_key(public)
        params = {"publickey": public}
        if proxy.get("pre-shared-key"):
            _wireguard_key(proxy["pre-shared-key"])
            params["presharedkey"] = proxy["pre-shared-key"]
        addresses = [str(ipaddress.ip_interface(proxy[k])) for k in ("ip", "ipv6") if proxy.get(k)]
        if not addresses:
            raise ProtocolError("WireGuard requires an interface address")
        params["address"] = ",".join(addresses)
        if "reserved" in proxy:
            values = proxy["reserved"]
            if not isinstance(values, list) or len(values) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in values):
                raise ProtocolError("WireGuard reserved must contain three bytes")
            params["reserved"] = ",".join(map(str, values))
        if "mtu" in proxy:
            params["mtu"] = int(proxy["mtu"])
            if not 576 <= params["mtu"] <= 65535:
                raise ProtocolError("invalid WireGuard MTU")
        if proxy.get("dns"):
            params["dns"] = ",".join(str(ipaddress.ip_address(v)) for v in proxy["dns"])
        return _uri(kind, proxy, quote(private, safe=""), params)
    if kind == "ss":
        cipher, password = _required(proxy, "cipher"), _required(proxy, "password")
        auth = (quote(cipher, safe="") + ":" + quote(password, safe="") if cipher.startswith("2022-")
                else _b64e(cipher + ":" + password))
        params = {}
        if "udp-over-tcp" in proxy:
            params["uot"] = "1" if _bool(proxy["udp-over-tcp"]) else "0"
        if proxy.get("plugin"):
            plugin, opts = proxy["plugin"], proxy.get("plugin-opts") or {}
            if plugin in ("obfs", "obfs-local", "simple-obfs"):
                if set(opts) - {"mode", "host"}:
                    raise ProtocolError("unsupported obfs plugin options; retain native YAML")
                values = ["obfs-local", "obfs=" + str(opts.get("mode", "http")), "obfs-host=" + str(opts.get("host", ""))]
            elif plugin == "v2ray-plugin":
                if set(opts) - {"mode", "host", "path", "tls", "mux", "skip-cert-verify"}:
                    raise ProtocolError("unsupported v2ray-plugin options; retain native YAML")
                values = ["v2ray-plugin"]
                for key, value in opts.items():
                    if isinstance(value, bool):
                        values.append(key if value else key + "=false")
                    else:
                        values.append(key + "=" + str(value))
            else:
                raise ProtocolError("unsupported SS plugin; retain native YAML")
            if any(";" in value for value in values):
                raise ProtocolError("plugin values containing semicolons require native YAML")
            params["plugin"] = ";".join(values)
        return _uri("ss", proxy, auth, params)
    if kind == "ssr":
        params = {"remarks": _b64e(str(proxy.get("name") or "ssr"))}
        for key, target in (("obfs-param", "obfsparam"), ("protocol-param", "protoparam")):
            if key in proxy:
                params[target] = _b64e(str(proxy[key]))
        if "udp-over-tcp" in proxy:
            params["uot"] = "1" if _bool(proxy["udp-over-tcp"]) else "0"
        body = ":".join([_host(proxy["server"]), str(_port(proxy["port"])),
                         _required(proxy, "protocol"), _required(proxy, "cipher"),
                         _required(proxy, "obfs"), _b64e(_required(proxy, "password"))])
        return "ssr://" + _b64e(body + "/?" + urlencode(params))
    if kind in ("vmess", "vless", "trojan"):
        params = _tls_out(proxy)
        params.update(_transport_out(proxy))
        if kind == "vless":
            auth = quote(str(proxy.get("uuid") or proxy.get("id") or ""), safe="")
            if not auth:
                raise ProtocolError("missing uuid")
            params["encryption"] = proxy.get("encryption") or "none"
            if proxy.get("flow"):
                params["flow"] = proxy["flow"]
        elif kind == "trojan":
            auth = quote(_required(proxy, "password"), safe="")
        else:
            uuid = str(proxy.get("uuid") or proxy.get("id") or "")
            if not uuid:
                raise ProtocolError("missing uuid")
            aid = int(proxy.get("alterId") or 0)
            if aid < 0:
                raise ProtocolError("invalid VMess alterId")
            advanced = (proxy.get("network") == "xhttp" or proxy.get("reality-opts")
                        or proxy.get("packet-addr") or proxy.get("xudp") or proxy.get("fingerprint")
                        or (proxy.get("http-opts") or {}).get("method")
                        or (proxy.get("ws-opts") or {}).get("max-early-data")
                        or (proxy.get("ws-opts") or {}).get("early-data-header-name"))
            if advanced:
                if aid:
                    raise ProtocolError("VMess AEAD sharing requires alterId=0")
                params["encryption"] = proxy.get("cipher") or "auto"
                return _uri("vmess", proxy, quote(uuid, safe=""), params)
            network = str(proxy.get("network") or "tcp").lower()
            obj = {"v": "2", "ps": str(proxy.get("name") or "vmess"), "add": proxy["server"],
                   "port": str(_port(proxy["port"])), "id": uuid, "aid": str(aid),
                   "scy": proxy.get("cipher") or "auto", "net": "http" if network == "h2" else "tcp" if network == "http" else network,
                   "type": "http" if network == "http" else "gun" if network == "grpc" else "none",
                   "host": params.get("host", ""), "path": params.get("serviceName", "") if network == "grpc" else params.get("path", ""),
                   "tls": "tls" if params["security"] == "tls" else "", "sni": params.get("sni", "")}
            for key in ("alpn", "fp", "insecure", "ed", "eh", "method"):
                if key in params:
                    obj[key] = params[key]
            return "vmess://" + base64.b64encode(json.dumps(obj, ensure_ascii=False).encode("utf-8")).decode("ascii")
        if "udp" in proxy:
            params["udp"] = "1" if _bool(proxy["udp"]) else "0"
        return _uri(kind, proxy, auth, params)
    if kind == "mieru":
        params = {"port": _port_ranges(proxy["port-range"]) if proxy.get("port-range") else _port(proxy["port"]),
                  "protocol": str(proxy.get("transport") or "TCP").upper()}
        if params["protocol"] not in ("TCP", "UDP"):
            raise ProtocolError("unsupported Mieru transport")
        for key in ("multiplexing", "handshake-mode", "traffic-pattern"):
            if key in proxy:
                params[key] = proxy[key]
        auth = quote(_required(proxy, "username"), safe="") + ":" + quote(_required(proxy, "password"), safe="")
        return _uri("mierus", proxy, auth, params, port=False)
    params = _tls_out(proxy)
    auth = ""
    scheme = kind
    if kind in ("socks5", "http"):
        if "username" in proxy or "password" in proxy:
            auth = quote(str(proxy.get("username") or ""), safe="") + ":" + quote(str(proxy.get("password") or ""), safe="")
        if kind == "http" and _bool(proxy.get("tls")):
            scheme = "https"
        if kind == "socks5" and "tls" in proxy:
            params["tls"] = "1" if _bool(proxy["tls"]) else "0"
    elif kind in ("hysteria2", "anytls"):
        auth = quote(_required(proxy, "password"), safe="")
        if kind == "hysteria2":
            for key in ("obfs", "obfs-password", "up", "down", "hop-interval"):
                if key in proxy:
                    params[key] = proxy[key]
            if proxy.get("ports"):
                params["mport"] = _port_ranges(proxy["ports"])
    elif kind == "hysteria":
        for source, target in (("auth-str", "auth"), ("auth_str", "auth"), ("up", "up"), ("down", "down"), ("obfs", "obfs"), ("protocol", "protocol")):
            if source in proxy:
                params[target] = proxy[source]
        if proxy.get("auth"):
            # Mihomo's auth is Base64 binary authentication, distinct from auth-str.
            raise ProtocolError("binary Hysteria authentication requires native YAML")
    elif kind == "tuic":
        if proxy.get("token"):
            auth = quote(str(proxy["token"]), safe="")
        else:
            auth = quote(_required(proxy, "uuid"), safe="") + ":" + quote(_required(proxy, "password"), safe="")
        for source, target in (("congestion-controller", "congestion_control"), ("udp-relay-mode", "udp_relay_mode")):
            if source in proxy:
                params[target] = proxy[source]
        for source, target in (("disable-sni", "disable_sni"), ("reduce-rtt", "reduce_rtt")):
            if source in proxy:
                params[target] = "1" if _bool(proxy[source]) else "0"
    if "udp" in proxy:
        params["udp"] = "1" if _bool(proxy["udp"]) else "0"
    return _uri(scheme, proxy, auth, params)


def normalize_proxy_names(proxies):
    names = {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "COMPATIBLE", "GLOBAL", "🌍选择代理节点"}
    result = []
    for proxy in proxies:
        item = dict(proxy)
        base = str(item.get("name") or item.get("type") or "proxy").strip() or "proxy"
        name = base
        index = 2
        while name in names:
            name = base + "-" + str(index)
            index += 1
        names.add(name)
        item["name"] = name
        result.append(item)
    return result


def v2ray_uris_to_clash_proxies(uris: List[str], issues: Optional[List[Dict]] = None) -> List[Dict]:
    result = []
    for index, uri in enumerate(uris, 1):
        if isinstance(uri, str) and not uri.strip():
            continue
        scheme = str(uri).split("://", 1)[0].lower()
        safe_scheme = scheme if re.fullmatch(r"[a-z][a-z0-9+.-]{0,31}", scheme) else "unknown"
        try:
            result.extend(parse_uri(uri))
        except ProtocolError as exc:
            _issue(issues, index, safe_scheme, str(exc))
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
            _issue(issues, index, safe_scheme, "malformed protocol parameters")
    return normalize_proxy_names(result)


def clash_proxy_to_uri(proxy: Dict) -> Tuple[bool, str]:
    try:
        value = export_uri(proxy)
        parse_uri(value)
        return True, value
    except ProtocolError as exc:
        return False, str(exc)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        return False, "malformed protocol parameters"


def clash_yaml_to_v2ray_uris(doc: Dict, issues: Optional[List[Dict]] = None) -> List[str]:
    if not isinstance(doc, dict) or not isinstance(doc.get("proxies"), list):
        _issue(issues, 0, "unknown", "missing proxies list")
        return []
    result = []
    for index, proxy in enumerate(doc["proxies"], 1):
        ok, value = clash_proxy_to_uri(proxy)
        kind = str(proxy.get("type") or "unknown") if isinstance(proxy, dict) else "unknown"
        kind = kind if re.fullmatch(r"[a-zA-Z0-9+.-]{1,32}", kind) else "unknown"
        if ok:
            result.append(value)
            # Report fields outside the URI vocabulary instead of promising lossless conversion.
            back = parse_uri(value)[0]
            omitted = _omitted_fields(proxy, back)
            if omitted:
                _issue(issues, index, kind, "share link omits fields: " + ", ".join(omitted), "warning")
        else:
            _issue(issues, index, kind, value)
    return result


def _omitted_fields(original, converted, prefix=""):
    omitted = []
    aliases = {"id": "uuid", "pass": "password", "auth_str": "auth-str",
               "servername": "sni", "sni": "servername",
               "public_key": "public-key", "short_id": "short-id"}
    for key, value in original.items():
        safe_key = str(key)
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", safe_key):
            safe_key = "(custom field)"
        path = prefix + safe_key
        target = key if key in converted else aliases.get(key, key)
        if target not in converted:
            omitted.append(path)
        elif isinstance(value, dict) and isinstance(converted[target], dict):
            omitted.extend(_omitted_fields(value, converted[target], path + "."))
    return sorted(omitted)


def split_v2ray_text(text: str) -> List[str]:
    if not isinstance(text, str):
        return []
    text = text.strip().lstrip("\ufeff")
    if not text:
        return []
    if "://" not in text and re.fullmatch(r"[A-Za-z0-9+/=_\s-]+", text):
        try:
            decoded = _b64d(text)
            if "://" in decoded:
                text = decoded
        except ProtocolError:
            pass
    # Split lines first so unknown schemes remain separate and can be reported.
    schemes = sorted(set(SCHEME_TYPES) | set(YAML_ONLY_PROTOCOLS), key=len, reverse=True)
    boundary = re.compile(r"(?=(?:" + "|".join(map(re.escape, schemes)) + r")://)", re.IGNORECASE)
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        start = 0
        for match in boundary.finditer(line):
            if match.start() > start and "#" in line[start:match.start()]:
                records.append(line[start:match.start()].strip())
                start = match.start()
        records.append(line[start:].strip())
    return [value for value in records if value]


def _wireguard_key(value):
    try:
        if len(base64.b64decode(value, validate=True)) != 32:
            raise ValueError
    except (ValueError, TypeError, binascii.Error) as exc:
        raise ProtocolError("WireGuard keys must be Base64-encoded 32-byte values") from exc
