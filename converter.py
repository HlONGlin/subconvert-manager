import base64
import json
import locale
import re
import urllib.parse
from typing import Dict, List, Optional, Tuple


# ------------------ utils ------------------

def b64e(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("utf-8")


def b64d(s: str) -> str:
    return base64.b64decode(s + "==="[: (4 - len(s) % 4) % 4]).decode("utf-8", errors="ignore")


def b64_urlsafe_no_pad(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")


def b64_urlsafe_decode(s: str) -> bytes:
    s2 = s + "==="[: (4 - len(s) % 4) % 4]
    return base64.urlsafe_b64decode(s2.encode("utf-8"))


def safe_get(d: Dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _q(s: str) -> str:
    return urllib.parse.quote(s) if s else ""


# ------------------ Clash -> V2Ray URIs ------------------

def clash_proxy_to_uri(p: Dict) -> Tuple[bool, str]:
    t = (p.get("type") or "").lower()
    name = p.get("name", "")
    server = p.get("server")
    port = p.get("port")

    if not server or not port:
        return False, "missing server/port"

    if t == "vmess":
        uuid = safe_get(p, "uuid", "id")
        if not uuid:
            return False, "vmess missing uuid"
        alter_id = int(safe_get(p, "alterId", default=0) or 0)
        cipher = safe_get(p, "cipher", default="auto")
        tls = bool(p.get("tls") or (str(p.get("tls")).lower() == "true"))
        sni = safe_get(p, "servername", "sni", "host")
        network = safe_get(p, "network", default="tcp")

        ws_opts = p.get("ws-opts") or {}
        grpc_opts = p.get("grpc-opts") or {}
        path = ""
        host = ""
        service_name = ""

        if network == "ws":
            path = safe_get(ws_opts, "path", default=safe_get(p, "path", default="")) or ""
            headers = ws_opts.get("headers") or {}
            host = headers.get("Host") or headers.get("host") or safe_get(p, "host", default="") or ""
        elif network == "grpc":
            service_name = safe_get(grpc_opts, "grpc-service-name", "serviceName", default=safe_get(p, "serviceName", default="")) or ""

        vmess_obj = {
            "v": "2",
            "ps": name,
            "add": server,
            "port": str(port),
            "id": uuid,
            "aid": str(alter_id),
            "scy": cipher if cipher else "auto",
            "net": network,
            "type": "none",
            "host": host,
            "path": path if network != "grpc" else service_name,
            "tls": "tls" if tls else "",
            "sni": sni or "",
        }
        if network == "grpc":
            vmess_obj["type"] = "gun"

        return True, "vmess://" + b64e(json.dumps(vmess_obj, ensure_ascii=False))

    if t == "vless":
        uuid = safe_get(p, "uuid", "id")
        if not uuid:
            return False, "vless missing uuid"
        tls = bool(p.get("tls") or (str(p.get("tls")).lower() == "true"))
        sni = safe_get(p, "servername", "sni")
        flow = safe_get(p, "flow")
        encryption = safe_get(p, "encryption", default="none") or "none"
        network = safe_get(p, "network", default="tcp")

        params = {"encryption": encryption, "type": network}
        security = "tls"
        reality_opts = p.get("reality-opts") or {}
        reality_public_key = safe_get(reality_opts, "public-key", "public_key")
        reality_short_id = safe_get(reality_opts, "short-id", "short_id")
        client_fingerprint = safe_get(p, "client-fingerprint")
        if reality_public_key:
            security = "reality"
        if tls or security == "reality":
            params["security"] = security
        if sni:
            params["sni"] = sni
        if flow:
            params["flow"] = flow
        if reality_public_key:
            params["pbk"] = reality_public_key
        if reality_short_id:
            params["sid"] = reality_short_id
        if client_fingerprint:
            params["fp"] = client_fingerprint

        ws_opts = p.get("ws-opts") or {}
        grpc_opts = p.get("grpc-opts") or {}

        if network == "ws":
            path = safe_get(ws_opts, "path", default=safe_get(p, "path", default=""))
            headers = ws_opts.get("headers") or {}
            host = headers.get("Host") or headers.get("host") or safe_get(p, "host")
            if host:
                params["host"] = host
            if path:
                params["path"] = path

        if network == "grpc":
            service_name = safe_get(grpc_opts, "grpc-service-name", "serviceName", default=safe_get(p, "serviceName"))
            if service_name:
                params["serviceName"] = service_name

        query = urllib.parse.urlencode(params, doseq=True, safe=":/")
        return True, f"vless://{uuid}@{server}:{port}?{query}#{_q(name)}"

    if t == "trojan":
        password = safe_get(p, "password", "pass")
        if not password:
            return False, "trojan missing password"

        sni = safe_get(p, "sni", "servername", "peer")
        alpn = safe_get(p, "alpn")
        network = safe_get(p, "network", default="tcp")

        params = {"security": "tls", "type": network}
        if sni:
            params["sni"] = sni
        if alpn:
            params["alpn"] = alpn

        ws_opts = p.get("ws-opts") or {}
        if network == "ws":
            path = safe_get(ws_opts, "path", default=safe_get(p, "path"))
            headers = ws_opts.get("headers") or {}
            host = headers.get("Host") or headers.get("host") or safe_get(p, "host")
            if host:
                params["host"] = host
            if path:
                params["path"] = path

        query = urllib.parse.urlencode(params, doseq=True, safe=":/")
        return True, f"trojan://{urllib.parse.quote(password)}@{server}:{port}?{query}#{_q(name)}"

    if t in ("ss", "shadowsocks"):
        cipher = safe_get(p, "cipher", default="")
        password = safe_get(p, "password", "pass", default="")
        if not cipher or not password:
            return False, "ss missing cipher/password"

        userinfo = f"{cipher}:{password}".encode("utf-8")
        user_b64 = b64_urlsafe_no_pad(userinfo)
        return True, f"ss://{user_b64}@{server}:{port}#{_q(name)}"

    return False, f"unsupported type: {t}"


def clash_yaml_to_v2ray_uris(doc: Dict) -> List[str]:
    proxies = doc.get("proxies") or []
    out: List[str] = []
    for p in proxies:
        ok, uri = clash_proxy_to_uri(p)
        if ok:
            out.append(uri)
    return out


def uris_to_v2ray_subscription_base64(uris: List[str]) -> str:
    text = "\n".join([u.strip() for u in uris if u.strip()]).strip() + ("\n" if uris else "")
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")


# ------------------ V2Ray URIs -> Clash proxies ------------------

def _parse_vmess(uri: str) -> Optional[Dict]:
    # vmess://base64(json)
    try:
        b64 = uri[len("vmess://"):]
        obj = json.loads(b64d(b64))
        name = obj.get("ps") or "vmess"
        server = obj.get("add")
        port = int(obj.get("port"))
        uuid = obj.get("id")
        alterId = int(obj.get("aid") or 0)
        cipher = obj.get("scy") or "auto"
        net = obj.get("net") or "tcp"
        tls = (obj.get("tls") == "tls")
        sni = obj.get("sni") or obj.get("host") or ""
        host = obj.get("host") or ""
        path = obj.get("path") or ""

        p = {
            "name": name,
            "type": "vmess",
            "server": server,
            "port": port,
            "uuid": uuid,
            "alterId": alterId,
            "cipher": cipher,
            "tls": tls,
            "network": net,
        }
        if sni:
            p["servername"] = sni
        if net == "ws":
            p["ws-opts"] = {"path": path, "headers": {"Host": host} if host else {}}
        if net == "grpc":
            p["grpc-opts"] = {"grpc-service-name": path} if path else {}
        return p
    except Exception:
        return None


def _parse_ss(uri: str) -> Optional[Dict]:
    # ss://<base64(method:pass)>@host:port#name  (also allow ss://method:pass@host:port)
    try:
        raw = uri[len("ss://"):]
        name = ""
        if "#" in raw:
            raw, frag = raw.split("#", 1)
            name = urllib.parse.unquote(frag)
        # remove plugin part if exists (not supported)
        if "?" in raw:
            raw, _ = raw.split("?", 1)

        if "@" in raw:
            userinfo, hostport = raw.split("@", 1)
            if ":" in userinfo and not re.fullmatch(r"[A-Za-z0-9\-_]+", userinfo):
                # already method:pass
                method, password = userinfo.split(":", 1)
            else:
                decoded = b64_urlsafe_decode(userinfo).decode("utf-8", errors="ignore")
                method, password = decoded.split(":", 1)
            host, port_s = hostport.rsplit(":", 1)
            return {
                "name": name or f"ss-{host}",
                "type": "ss",
                "server": host,
                "port": int(port_s),
                "cipher": method,
                "password": password,
            }
        return None
    except Exception:
        return None


def _parse_vless_or_trojan(uri: str, t: str) -> Optional[Dict]:
    # vless://uuid@host:port?query#name
    # trojan://pass@host:port?query#name
    try:
        parsed = urllib.parse.urlparse(uri)
        name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else t
        server = parsed.hostname
        port = parsed.port
        if not server or not port:
            return None

        q = urllib.parse.parse_qs(parsed.query)
        def q1(k): 
            v = q.get(k)
            return v[0] if v else None

        network = (q1("type") or "tcp").lower()
        security = (q1("security") or "").lower()
        tls = security in ("tls", "reality") or (q1("tls") or "").lower() in ("1", "true", "yes")
        sni = q1("sni") or q1("servername")
        fingerprint = q1("fp") or q1("client-fingerprint")
        reality_public_key = q1("pbk") or q1("public-key")
        reality_short_id = q1("sid") or q1("short-id")

        if t == "vless":
            uuid = parsed.username
            if not uuid:
                return None
            p = {"name": name, "type": "vless", "server": server, "port": int(port), "uuid": uuid, "network": network}
            # VLESS in Clash generally uses UDP by default.
            p["udp"] = True
            enc = (q1("encryption") or "none").strip()
            if enc and enc.lower() != "none":
                p["encryption"] = enc
            if sni:
                p["servername"] = sni
            flow = q1("flow")
            if flow:
                p["flow"] = flow
            if security == "reality" or reality_public_key or reality_short_id:
                ro = {}
                if reality_public_key:
                    ro["public-key"] = reality_public_key
                if reality_short_id:
                    ro["short-id"] = reality_short_id
                if ro:
                    p["reality-opts"] = ro
            if fingerprint:
                p["client-fingerprint"] = fingerprint
        else:
            # trojan
            password = parsed.username
            if not password:
                return None
            p = {"name": name, "type": "trojan", "server": server, "port": int(port), "password": urllib.parse.unquote(password), "network": network}
            p["udp"] = True
            if sni:
                p["sni"] = sni
            if fingerprint:
                p["client-fingerprint"] = fingerprint

        # ws
        if network == "ws":
            host = q1("host")
            path = q1("path")
            ws = {"path": path or "", "headers": {"Host": host} if host else {}}
            p["ws-opts"] = ws
        if network == "grpc":
            sn = q1("serviceName")
            if sn:
                p["grpc-opts"] = {"grpc-service-name": sn}

        # tls flag for clash
        p["tls"] = bool(tls)
        return p
    except Exception:
        return None


def v2ray_uris_to_clash_proxies(uris: List[str]) -> List[Dict]:
    out: List[Dict] = []
    for u in uris:
        u = u.strip()
        if not u:
            continue
        if u.startswith("vmess://"):
            p = _parse_vmess(u)
            if p: out.append(p)
        elif u.startswith("vless://"):
            p = _parse_vless_or_trojan(u, "vless")
            if p: out.append(p)
        elif u.startswith("trojan://"):
            p = _parse_vless_or_trojan(u, "trojan")
            if p: out.append(p)
        elif u.startswith("ss://"):
            p = _parse_ss(u)
            if p: out.append(p)
        # ignore unknown
    return out


def build_clash_yaml(proxies: List[Dict]) -> Dict:
    names = [p.get("name", "") for p in proxies if p.get("name")]
    group = {
        "name": "AUTO",
        "type": "select",
        "proxies": names or ["DIRECT"],
    }
    return {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": True,
        "mode": "rule",
        "log-level": "info",
        "proxies": proxies,
        "proxy-groups": [group],
        "rules": ["MATCH,AUTO"],
    }




# ------------------ ClashPlay YAML builder ------------------

# Prefer locale-aware sorting for Chinese names when available.
try:
    locale.setlocale(locale.LC_ALL, "zh_CN.UTF-8")
    _LOCALE_OK = True
except Exception:
    _LOCALE_OK = False


def _extract_number_for_sort(name: str) -> int:
    m = re.search(r"\d+", name or "")
    return int(m.group()) if m else 10**12


def _extract_keyword_for_group(name: str) -> Tuple[str, str]:
    """Extract Chinese and English keyword fragments from a proxy name."""
    chinese = ''.join(re.findall(r"[\u4e00-\u9fff]+", name or ""))
    english = ''.join(re.findall(r"[A-Za-z]+", name or "")).lower()
    return chinese, english


def _keyword_sort_key(name: str):
    zh, en = _extract_keyword_for_group(name)
    if _LOCALE_OK:
        return (locale.strxfrm(zh), en, _extract_number_for_sort(name))
    return (zh, en, _extract_number_for_sort(name))


def build_clashplay_yaml(
    proxies: List[Dict],
    *,
    rate_limit_mbps: int = 0,
    test_url: str = "https://www.gstatic.com/generate_204",
    interval_sec: int = 300,
    tolerance_ms: int = 50,
) -> Dict:
    """
    Build a ClashPlay-style YAML document from parsed proxies.

    Current behavior:
    - generate grouped load-balance and url-test strategy groups
    - add a top-level select group
    - optionally apply a global rate limit
    """
    # 1) sanitize input proxies and sort by keyword + number
    cleaned = []
    for p in proxies or []:
        if not isinstance(p, dict):
            continue
        name = (p.get('name') or '').strip()
        if not name or name == 'REJECT':
            continue
        p2 = dict(p)
        p2['name'] = name
        cleaned.append(p2)

    # fallback when no valid proxies
    if not cleaned:
        return build_clash_yaml([])

    cleaned.sort(key=lambda x: _keyword_sort_key(x.get('name') or ''))

    # 2) generate grouped strategy groups and the final select group
    grouped: Dict[Tuple[str, str], List[str]] = {}
    for p in cleaned:
        k = _extract_keyword_for_group(p.get('name') or '')
        grouped.setdefault(k, []).append(p['name'])

    proxy_groups: List[Dict] = []
    all_proxy_names = [p['name'] for p in cleaned]

    for (zh, en), names in grouped.items():
        group_name = f"{zh}{en}" if zh else (en or "\u7ebf\u8def")
        proxy_groups.append({
            'name': f"{group_name}-\u8d1f\u8f7d\u5747\u8861",
            'type': 'load-balance',
            'url': test_url,
            'interval': int(interval_sec),
            'strategy': 'round-robin',
            'proxies': names,
        })
        proxy_groups.append({
            'name': f"{group_name}-\u81ea\u52a8\u9009\u62e9",
            'type': 'url-test',
            'url': test_url,
            'interval': int(interval_sec),
            'tolerance': int(tolerance_ms),
            'proxies': names,
        })
    select_proxies = ['DIRECT'] + all_proxy_names + [g['name'] for g in proxy_groups]
    proxy_groups.append({
        'name': '\U0001f30d\u9009\u62e9\u4ee3\u7406\u8282\u70b9',
        'type': 'select',
        'proxies': select_proxies,
    })

    rules = [
        'GEOIP,CN,DIRECT',
        'DOMAIN-SUFFIX,cn,DIRECT',
        'DOMAIN-SUFFIX,126.com,DIRECT',
        'DOMAIN-SUFFIX,163.com,DIRECT',
        'DOMAIN-SUFFIX,360.cn,DIRECT',
        'DOMAIN-SUFFIX,alipay.com,DIRECT',
        'DOMAIN-SUFFIX,baidu.com,DIRECT',
        'DOMAIN-SUFFIX,bilibili.com,DIRECT',
        'DOMAIN-SUFFIX,douban.com,DIRECT',
        'DOMAIN-SUFFIX,douyin.com,DIRECT',
        'DOMAIN-SUFFIX,iqiyi.com,DIRECT',
        'DOMAIN-SUFFIX,jd.com,DIRECT',
        'DOMAIN-SUFFIX,meituan.com,DIRECT',
        'DOMAIN-SUFFIX,qq.com,DIRECT',
        'DOMAIN-SUFFIX,taobao.com,DIRECT',
        'DOMAIN-SUFFIX,tencent.com,DIRECT',
        'DOMAIN-SUFFIX,weibo.com,DIRECT',
        'DOMAIN-SUFFIX,weixin.com,DIRECT',
        'DOMAIN-SUFFIX,xiaomi.com,DIRECT',
        'DOMAIN-SUFFIX,zhihu.com,DIRECT',
        'DOMAIN-SUFFIX,360.com,DIRECT',
        'DOMAIN-SUFFIX,51job.com,DIRECT',
        'DOMAIN-SUFFIX,58.com,DIRECT',
        'DOMAIN-SUFFIX,amap.com,DIRECT',
        'DOMAIN-SUFFIX,auto.sina.com.cn,DIRECT',
        'DOMAIN-SUFFIX,autohome.com.cn,DIRECT',
        'DOMAIN-SUFFIX,autohome.com,DIRECT',
        'DOMAIN-SUFFIX,bankofchina.com,DIRECT',
        'DOMAIN-SUFFIX,zhipin.com,DIRECT',
        'DOMAIN-SUFFIX,cctv.com,DIRECT',
        'DOMAIN-SUFFIX,chinabank.com.cn,DIRECT',
        'DOMAIN-SUFFIX,chinacourt.org,DIRECT',
        'DOMAIN-SUFFIX,chinadaily.com.cn,DIRECT',
        'DOMAIN-SUFFIX,chinaint.cn,DIRECT',
        'DOMAIN-SUFFIX,chinaunix.net,DIRECT',
        'DOMAIN-SUFFIX,chinaso.com,DIRECT',
        'DOMAIN-SUFFIX,chinaz.com,DIRECT',
        'DOMAIN-SUFFIX,ck101.com,DIRECT',
        'DOMAIN-SUFFIX,clouddn.com,DIRECT',
        'DOMAIN-SUFFIX,cmbchina.com,DIRECT',
        'DOMAIN-SUFFIX,cnblogs.com,DIRECT',
        'DOMAIN-SUFFIX,cnbeta.com,DIRECT',
        'DOMAIN-SUFFIX,cnnic.cn,DIRECT',
        'DOMAIN-SUFFIX,ctrip.com,DIRECT',
        'DOMAIN-SUFFIX,cqu.edu.cn,DIRECT',
        'DOMAIN-SUFFIX,csdn.net,DIRECT',
        'DOMAIN-SUFFIX,ctrip.hk,DIRECT',
        'DOMAIN-SUFFIX,ctripcorp.com,DIRECT',
        'DOMAIN-SUFFIX,10010.com,DIRECT',
        'DOMAIN-SUFFIX,10086.cn,DIRECT',
        'DOMAIN-SUFFIX,189.cn,DIRECT',
        'DOMAIN-SUFFIX,dianping.com,DIRECT',
        'DOMAIN-SUFFIX,ele.me,DIRECT',
        'DOMAIN-SUFFIX,ifeng.com,DIRECT',
        'DOMAIN-SUFFIX,feng.com,DIRECT',
        'DOMAIN-SUFFIX,hexun.com,DIRECT',
        'DOMAIN-SUFFIX,hupu.com,DIRECT',
        'DOMAIN-SUFFIX,newrank.cn,DIRECT',
        'DOMAIN-SUFFIX,people.com.cn,DIRECT',
        'DOMAIN-SUFFIX,globaltimes.cn,DIRECT',
        'DOMAIN-SUFFIX,takungpao.com,DIRECT',
        'DOMAIN-SUFFIX,gmw.cn,DIRECT',
        'DOMAIN-SUFFIX,ynet.com,DIRECT',
        'DOMAIN-SUFFIX,ce.cn,DIRECT',
        'DOMAIN-SUFFIX,xinhuanet.com,DIRECT',
        'DOMAIN-SUFFIX,xinhua.org,DIRECT',
        'DOMAIN-SUFFIX,qqmail.com,DIRECT',
        'DOMAIN-SUFFIX,foxmail.com,DIRECT',
        'DOMAIN-SUFFIX,gtimg.cn,DIRECT',
        'DOMAIN-SUFFIX,qpic.cn,DIRECT',
        'DOMAIN-SUFFIX,qzone.com,DIRECT',
        'DOMAIN-SUFFIX,maoyan.com,DIRECT',
        'DOMAIN-SUFFIX,dpurl.cn,DIRECT',
        'DOMAIN-SUFFIX,qunar.com,DIRECT',
        'DOMAIN-SUFFIX,vip.com,DIRECT',
        'DOMAIN-SUFFIX,yhd.com,DIRECT',
        'DOMAIN-SUFFIX,kaola.com,DIRECT',
        'DOMAIN-SUFFIX,dangdang.com,DIRECT',
        'DOMAIN-SUFFIX,amazon.cn,DIRECT',
        'DOMAIN-SUFFIX,gome.com.cn,DIRECT',
        'DOMAIN-SUFFIX,jumei.com,DIRECT',
        'DOMAIN-SUFFIX,yanxuan.com,DIRECT',
        'DOMAIN-SUFFIX,mogujie.com,DIRECT',
        'DOMAIN-SUFFIX,meilishuo.com,DIRECT',
        'DOMAIN-SUFFIX,dhgate.com,DIRECT',
        'DOMAIN-SUFFIX,aliexpress.com,DIRECT',
        'DOMAIN-SUFFIX,made-in-china.com,DIRECT',
        'DOMAIN-SUFFIX,tenpay.com,DIRECT',
        'DOMAIN-SUFFIX,unionpay.com,DIRECT',
        'DOMAIN-SUFFIX,chinaunionpay.com,DIRECT',
        'DOMAIN-SUFFIX,huawei.com,DIRECT',
        'DOMAIN-SUFFIX,oppo.com,DIRECT',
        'DOMAIN-SUFFIX,vivo.com,DIRECT',
        'DOMAIN-SUFFIX,meizu.com,DIRECT',
        'DOMAIN-SUFFIX,realme.com,DIRECT',
        'DOMAIN-SUFFIX,oneplus.com,DIRECT',
        'DOMAIN-SUFFIX,icbc.com.cn,DIRECT',
        'DOMAIN-SUFFIX,ccb.com,DIRECT',
        'DOMAIN-SUFFIX,abchina.com,DIRECT',
        'DOMAIN-SUFFIX,boc.cn,DIRECT',
        'DOMAIN-SUFFIX,psbc.com,DIRECT',
        'DOMAIN-SUFFIX,ecitic.com,DIRECT',
        'DOMAIN-SUFFIX,cebbank.com,DIRECT',
        'DOMAIN-SUFFIX,pingan.com,DIRECT',
        'DOMAIN-SUFFIX,pingan.cn,DIRECT',
        'DOMAIN-SUFFIX,pinganbank.cn,DIRECT',
        'DOMAIN-SUFFIX,creditcard.com.cn,DIRECT',
        'DOMAIN-SUFFIX,alicloud.com,DIRECT',
        'DOMAIN-SUFFIX,aliyun.com,DIRECT',
        'DOMAIN-SUFFIX,netease.com,DIRECT',
        'DOMAIN-SUFFIX,126.net,DIRECT',
        'DOMAIN-SUFFIX,163yun.com,DIRECT',
        'DOMAIN-SUFFIX,gtimg.com,DIRECT',
        'DOMAIN-SUFFIX,wx.qq.com,DIRECT',
        'DOMAIN-SUFFIX,wechat.com,DIRECT',
        'DOMAIN-SUFFIX,csdn.com,DIRECT',
        'DOMAIN-SUFFIX,oschina.net,DIRECT',
        'DOMAIN-SUFFIX,github.cn,DIRECT',
        'DOMAIN-SUFFIX,gitee.com,DIRECT',
        'DOMAIN-SUFFIX,juejin.cn,DIRECT',
        'DOMAIN-SUFFIX,jianshu.com,DIRECT',
        'DOMAIN-SUFFIX,zhimg.com,DIRECT',
        'DOMAIN-SUFFIX,sina.cn,DIRECT',
        'DOMAIN-SUFFIX,weibo.cn,DIRECT',
        'DOMAIN-SUFFIX,umeng.com,DIRECT',
        'DOMAIN-SUFFIX,huanqiu.com,DIRECT',
        'DOMAIN-SUFFIX,qyer.com,DIRECT',
        'DOMAIN-SUFFIX,kuaidi100.com,DIRECT',
        'DOMAIN-SUFFIX,baidustatic.com,DIRECT',
        'DOMAIN-SUFFIX,bdstatic.com,DIRECT',
        'DOMAIN-SUFFIX,hm.baidu.com,DIRECT',
        'DOMAIN-SUFFIX,bce.baidu.com,DIRECT',
        'DOMAIN-SUFFIX,tmall.com,DIRECT',
        'DOMAIN-SUFFIX,tmall.hk,DIRECT',
        'DOMAIN-SUFFIX,etao.com,DIRECT',
        'DOMAIN-SUFFIX,alicdn.com,DIRECT',
        'DOMAIN-SUFFIX,alimama.com,DIRECT',
        'DOMAIN-SUFFIX,taobaocdn.com,DIRECT',
        'DOMAIN-SUFFIX,wangwang.com,DIRECT',
        'DOMAIN-SUFFIX,mmstat.com,DIRECT',
        'DOMAIN-SUFFIX,xiami.com,DIRECT',
        'DOMAIN-SUFFIX,cnzz.com,DIRECT',
        'DOMAIN-SUFFIX,cnzz.net,DIRECT',
        'DOMAIN-SUFFIX,tongji.com,DIRECT',
        'DOMAIN-SUFFIX,tongji.cn,DIRECT',
        'DOMAIN-SUFFIX,anjuke.com,DIRECT',
        'DOMAIN-SUFFIX,fang.com,DIRECT',
        'DOMAIN-SUFFIX,fangtianxia.com,DIRECT',
        'DOMAIN-SUFFIX,house365.com,DIRECT',
        'DOMAIN-SUFFIX,ke.com,DIRECT',
        'DOMAIN-SUFFIX,lianjia.com,DIRECT',
        'DOMAIN-SUFFIX,futu5.com,DIRECT',
        'DOMAIN-SUFFIX,futunn.com,DIRECT',
        'DOMAIN-SUFFIX,qihoo.com,DIRECT',
        'DOMAIN-SUFFIX,so.com,DIRECT',
        'DOMAIN-SUFFIX,haosou.com,DIRECT',
        'DOMAIN-SUFFIX,sogoucdn.com,DIRECT',
        'DOMAIN-SUFFIX,wps.cn,DIRECT',
        'DOMAIN-SUFFIX,wps.com,DIRECT',
        'DOMAIN-SUFFIX,kingsoft.com,DIRECT',
        'DOMAIN-SUFFIX,kugou.com,DIRECT',
        'DOMAIN-SUFFIX,kuwo.cn,DIRECT',
        'DOMAIN-SUFFIX,qianqian.com,DIRECT',
        'DOMAIN-SUFFIX,douyu.com,DIRECT',
        'DOMAIN-SUFFIX,huya.com,DIRECT',
        'DOMAIN-SUFFIX,egame.qq.com,DIRECT',
        'DOMAIN-SUFFIX,tsinghua.edu.cn,DIRECT',
        'DOMAIN-SUFFIX,pku.edu.cn,DIRECT',
        'DOMAIN-SUFFIX,fudan.edu.cn,DIRECT',
        'DOMAIN-SUFFIX,zju.edu.cn,DIRECT',
        'DOMAIN-SUFFIX,ecnu.edu.cn,DIRECT',
        'DOMAIN-SUFFIX,nju.edu.cn,DIRECT',
        'DOMAIN-SUFFIX,sohu.com,DIRECT',
        'DOMAIN-SUFFIX,39.net,DIRECT',
        'DOMAIN-SUFFIX,120ask.com,DIRECT',
        'DOMAIN-SUFFIX,haodf.com,DIRECT',
        'DOMAIN-SUFFIX,dxy.cn,DIRECT',
        'DOMAIN-SUFFIX,icourse163.org,DIRECT',
        'DOMAIN-SUFFIX,gov.cn,DIRECT',
        'DOMAIN-SUFFIX,yicai.com,DIRECT',
        'DOMAIN-SUFFIX,21jingji.com,DIRECT',
        'DOMAIN-SUFFIX,bjnews.com.cn,DIRECT',
        'DOMAIN-SUFFIX,cbnweek.com,DIRECT',
        'DOMAIN-SUFFIX,caixin.com,DIRECT',
        'DOMAIN-SUFFIX,jiemian.com,DIRECT',
        'DOMAIN-SUFFIX,tmtpost.com,DIRECT',
        'DOMAIN-SUFFIX,leiphone.com,DIRECT',
        'DOMAIN-SUFFIX,36kr.com,DIRECT',
        'DOMAIN-SUFFIX,geekpark.net,DIRECT',
        'DOMAIN-SUFFIX,ifanr.com,DIRECT',
        'DOMAIN-SUFFIX,mop.com,DIRECT',
        'DOMAIN-SUFFIX,tieba.baidu.com,DIRECT',
        'DOMAIN-SUFFIX,tiebaimg.com,DIRECT',
        'DOMAIN-SUFFIX,guokr.com,DIRECT',
        'DOMAIN-SUFFIX,sspai.com,DIRECT',
        'DOMAIN-SUFFIX,zol.com.cn,DIRECT',
        'DOMAIN-SUFFIX,cnmo.com,DIRECT',
        'DOMAIN-SUFFIX,ithome.com,DIRECT',
        'DOMAIN-SUFFIX,yesky.com,DIRECT',
        'DOMAIN,local,DIRECT',
        'DOMAIN-SUFFIX,lan,DIRECT',
        'DOMAIN-SUFFIX,localhost,DIRECT',
        'MATCH,\U0001f30d\u9009\u62e9\u4ee3\u7406\u8282\u70b9',
    ]
    doc: Dict = {
        'port': 7890,
        'allow-lan': True,
        'mode': 'rule',
        'log-level': 'info',
        'unified-delay': True,
        'global-client-fingerprint': 'chrome',
        'dns': {
            'enable': True,
            'listen': ':53',
            'ipv6': True,
            'enhanced-mode': 'fake-ip',
            'fake-ip-range': '198.18.0.1/16',
            'default-nameserver': ['223.5.5.5', '8.8.8.8'],
            'nameserver': [
                'https://dns.alidns.com/dns-query',
                'https://doh.pub/dns-query',
                'https://doh.360.cn/dns-query',
            ],
            'fallback': [
                'https://doh.360.cn/dns-query',
                'https://dns.alidns.com/dns-query',
                'https://zns.lehu.in/dns/vmKXrTy_U4n06Ff1PD_YxQ',
            ],
            'fallback-filter': {
                'geoip': True,
                'geoip-code': 'CN',
                'ipcidr': ['240.0.0.0/4'],
            },
        },
        'proxies': cleaned,
        'proxy-groups': proxy_groups,
        'rules': rules,
    }

    if rate_limit_mbps and rate_limit_mbps > 0:
        doc['rate-limit'] = int(rate_limit_mbps)

    return doc


def split_v2ray_text(text: str) -> List[str]:
    # accept base64 subscription or raw uris
    t = text.strip()
    if not t:
        return []
    # Heuristic: if no scheme and mostly base64 chars, treat as subscription base64
    if "://" not in t and re.fullmatch(r"[A-Za-z0-9+/=\s_-]+", t):
        compact = re.sub(r"\s+", "", t)
        candidates = [compact]
        swapped = compact.replace("-", "+").replace("_", "/")
        if swapped != compact:
            candidates.append(swapped)

        for candidate in candidates:
            for decoder in (
                lambda s: base64.b64decode(s + "==="[: (4 - len(s) % 4) % 4]),
                b64_urlsafe_decode,
            ):
                try:
                    decoded = decoder(candidate).decode("utf-8", errors="ignore")
                except Exception:
                    continue
                lines = [x.strip() for x in decoded.splitlines() if x.strip()]
                if lines and any("://" in x for x in lines):
                    return lines
    return [x.strip() for x in t.splitlines() if x.strip()]
