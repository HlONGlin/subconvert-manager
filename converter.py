import base64
import json
import re
import urllib.parse
from typing import Dict, List, Tuple, Optional


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




# ------------------ ClashPlay 濠碉紕鍋涢鍛偓娑掓櫊閹囧箹娴ｅ湱鍘愰悗骞垮劚濞层劑寮搁崒鐐寸厽闁靛繈鍨归弸鎴︽煕閵婏箑鍝洪柡浣哥Ч瀹曞ジ濮€閳╁啯顓瑰┑鐐茬摠缁瞼鑺遍崼鏇炵劦妞ゆ帊鑳堕惌鎺楁煕鎼粹槅鍤熺紒杈ㄦ楠炴捇骞掗弬鍝勪壕闁绘垼妫勯悘铏節婵犲嫮澹攁sh YAML闂?------------------

import locale

# 闂備礁鎼張顒勫礉閹烘棁濮虫繛宸簼閸嬫繃銇勯弽銊ュ毈闁哄棙姊圭换娑氫沪缁嬪灝鈷夊┑鐘亾?zh_CN.UTF-8闂備焦瀵х粙鎴炵附閺冨倹顫曢柟娈垮枓閸嬫挻鎷呴崘顭戞闂?locale.Error闂備焦瀵х粙鎺旂矙閺嶎偅宕查柡宥庡幗閻撳倿鎮橀悙璺盒撻柡鍛偢閺屾盯寮埀顒傜矙閺嶎収鏁婇柡鍥╁Х绾剧偓銇勯弴鐐搭棤缂佲偓婢跺鐔嗛柟顖涘缁ㄥ潡鎮峰▎娆戠暤鐎规洘鑹鹃埢搴ㄥ箻閹碱厸鍋撻弽顐ょ＜闁绘瑦鐟ょ拋鏌ュ磻?
try:
    locale.setlocale(locale.LC_ALL, "zh_CN.UTF-8")
    _LOCALE_OK = True
except Exception:
    _LOCALE_OK = False


def _extract_number_for_sort(name: str) -> int:
    m = re.search(r"\d+", name or "")
    return int(m.group()) if m else 10**12


def _extract_keyword_for_group(name: str) -> Tuple[str, str]:
    """
    濠电偛顕慨鏉戭潩閿旀垝绻嗘い鎾卞灪閸婄兘鏌ｉ悢鍝勵暭闁稿﹤鍟块埥澶愬箼閸愩劌绠烘繝鐢靛仜閿曨亜鐣烽敐澶婂唨闁靛牆鍊告禍鐐節婵炴儳浜鹃梺鐓庣仛閸ㄥ灝顕ｉ鍕倞妞ゆ巻鍋撻柛鏂诲劦閺?+ 闂備礁鍚嬪Σ鎺撱仈閹间礁鍑犻柛鎰靛枟閻掗箖鏌曟繛鍨姎闁诲骸顭烽弻宥夊Ψ閿斿墽顔囩紓浣介哺缁诲牓骞冩禒瀣╅柕鍫濇穿婢规﹢姊洪崨濠傜瑨婵☆偅绋撻崚?闂備礁婀遍崕銈囨暜閹烘棁濮虫い鎾卞灩杩?
    濠电偞鍨堕幑浣割浖閵娧冨灊闁割偆鍠撻埢鏇㈡煕椤愵剛绉垫繛璇х秮瀵爼鍩￠崒婊勫櫏缂備胶濮烽崑銈呯暦閹存繍娼╅柛鎾楀懐宕?    - 闂備胶绮划宥咁熆濮椻偓閹潡宕熼娑氬帓闁诲繒鍋熼弲顐﹀矗閹存繍鐔嗛柤鍝ユ暩椤ｅ弶绻濊閸嬫捇姊洪棃鈺冪暢婵℃ぜ鍔庡Σ鎰閺夋垶宓嶉梺闈涱焾閸斿矁鐏愰梻浣虹帛閸旀骞婇幘璇茬畺闁哄洢鍨洪悡鍌炴倶閻愭潙绀冪紒灞芥健閺屾稑顫濋鍌氼暤闂侀€炲苯澧紒顔艰嫰闇夋俊銈呭暊閸?缂傚倷鐒﹀畷姗€宕曟繝姘剹闁绘劦鍓涢埢鏃€銇勯幘璺烘瀾闁?+ 缂傚倷鐒﹀畷姗€宕曟繝姘剹濡わ絽鍟崵鎰板级閸稑濡介柣?缂傚倸鍊搁崐褰掓偋閺嚶颁汗闁秆勵殔閻忚櫕绻濋崹顐ｅ暗缂佲偓?      闂備胶鍎甸弲娑㈡偤閵娧勬殰闁圭虎鍠栫粻鏉款熆鐠虹尨鍔熼柟鐣屽枔缁辨帒螖鐎ｎ剛绐楅柣鐔告礀濡繈鐛幒妤€绠抽柟瀵稿Х椤ｅ弶绻涢弶鎴濇倯闁肩懓澧藉▎銏ゅ閿涘嫧鏋欓梺瑙勫絻椤戝洭鐛姀銈呯骇闁冲搫鍊婚幊鍥煕閿濆妫戝ù婊冩啞缁傛帞鈧綆浜濋锟犳煟閻樿精顔夐柡鍛洴楠炲啴骞樼€电硶鏋栭梺閫炲苯澧伴柣銉邯閹虫顢涘鍛暥闂備浇澹堟ご鎼佹嚌閹嶈€挎い蹇撴噽閳绘棃鏌嶈閸撴盯骞愯瀹曟瑩濡堕崶鈺婃Х濠电偞鎸婚懝楣冨Φ濡壈濮虫い鎺戝閻掕顭跨捄渚剰妞ゅ繈鍎遍埥澶愬箻閾忣偅宕冲┑鐑囩秵閸ｏ綁鐛惔銊ノч柛鎰剁到娴?    """
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
    闂備焦鐪归崹濠氬窗閹版澘鍨傛慨妯挎硾閸楁娊鎮楀☉娅亝寰勫澶婄骇?ClashPlay 闂備焦鐪归崝宀€鈧皜鍥х劦妞ゆ帊鑳堕惌濠勬喐閻楀牏鍙€闁诡垰瀚埀顒佺⊕閿氬璺虹Ч濮婃椽顢欓崫鍕瀷闁荤姳鐒﹂悡锟犲垂閹€鏀介柛顐ゅ枔閺?Clash 闂傚倷鐒﹀妯肩矓閸洘鍋柛鈩冪☉杩?
    闂佽崵濮抽悞锕€鐣峰鈧、姗€骞栨担鐟板壆濡炪倖姊婚弲顐﹀垂婵傚憡鐓?    - 濠电偞鍨堕幐鍝ョ矓閻㈢鏋佸┑鍌滎焾閻?subconvert-manager 闂備焦鐪归崝宀€鈧凹鍙冮幃褏鈧湱濮烽悿鈧梺鍛婂姦閸樺ジ宕㈤幘顔界厱闁哄啠鍋撻柛鎰吹濡叉劕鈻庨幇顕呮锤闂佸湱鍎ゅú妯肩矈?闂佽崵濮抽梽宥夊垂閽樺）锝夊礋椤掍胶绉堕梺瑙勫劤閸熷灝袙婢舵劖鐓?    - 濠碘槅鍋嗘晶妤冩崲閸岀倛鍥ㄧ節濮橆剛顔岄梺褰掑亰娴滅偞娼婚弬搴撴闁圭虎鍨版禍鐐箾閹寸偞鎯勫ù婊勭墵閸┾偓妞ゆ帊鑳堕惌鎺楁煕鎼粹槅鍤熺紒杈ㄦ楠炴捇骞掗弬鍝勪壕鐎瑰嫭瀚堥悢鐓庣労闁告劏鏅濋崙锟犳⒑閻愯棄鍔滅紒缁樺姉濡叉劖瀵肩€涙ê娈滃銈呯箰鐎氼剝顤勯梻浣告啞鐢帒螞濞戞艾鍨?+ 闂佽崵濮甸崝妤呭窗閺囩伝褰掑炊椤掆偓闁裤倝鏌涢妷顔荤暗闁逞屽厴閸?+ 闂備胶鍘ч〃搴㈢濠婂嫭鍙忛柍杞版€ラ崷顓涘亾閿濆骸鏋撻柛?+ 闂備礁鎼ú锕€顭囧▎鎾村仼妞ゆ帒瀚弸渚€鎮楅棃娑欏暈闁伙綁浜堕幃宄扳枎韫囨搩浠奸梺鍓茬厛閸ㄩ亶銆冮妷鈺佄╅柨鏂垮綖濡?
    婵犵數鍋涢ˇ顓㈠礉瀹ュ绀堝ù鐓庣摠閺?    - 闂佽崵鍠愰悷銉р偓姘煎墴瀹曞綊顢涘鈧悞濠偯归悩宸剰婵炲懌鍊曡彁闁搞儯鍔庣粻鏍倵閸偅鈷掗柍褜鍓涢弫濠氬焵椤掍胶銆掗柣鐔哥箞閺?Clash 闂備礁鎲￠崝鏇㈠箠韫囨稒鍋嬮柟鎯版缁€鍌炴煟閹惧啿鐦ㄩ柛鐔锋喘閺屻劌鈽夊Ο鐓庘叺婵炴潙鐨烽弲鐘茬暦濡も偓椤撳ジ宕熼锛勨敍闂?GEOSITE 缂傚倷鐒︾粙鎴λ囬悧鍫熸珷閻犳亽鍔嬪▽顏堟煛閸ユ湹绨界紒鈧崱娑欑厪?    - 濠电姷顣介埀顒€鍟块埀顒€鐏濋妴鎺楀醇閺囩喎娈滃銈呯箰鐎氼噣寮抽弶搴撴闁哄倹顑欏Σ鍏笺亜椤愩埄妯€鐎?闂備礁鎲＄敮鎺懳涘☉姘灊鐎广儱顦伴弲顒傗偓鍏夊亾闁告劖鍎冲▓鏌ユ⒑闂堚晞绀嬮柛鏂跨Ч椤㈡鈹戠€ｎ亞顦╅梺鍏间航閸庢彃鈻撻崼鏇熺厱闁冲搫瀚鐘炽亜閵忕姵鍣虹紒瀣槹缁绘繈宕橀妸銏″瘶闂佽绻掗崑鐐裁洪埡鍐╊潟婵犻潧顑嗛崵鈧柣蹇曞仩閸嬫劙鎮峰┑瀣厸闁告洟娼ч悘锟犳煛娴ｆ悶鍋㈢€规洘绻堟俊鎼佹晜閺傘倗绀堥梻?build_clash_yaml闂備焦瀵х粙鎴︽偋婵犲倶鈧帡宕滄担椋庡墾闂婎偄娲ら柊锝夊汲閸涘瓨鐓曢煫鍥ь儏閸旂數绱掓潏銊ュ摵濠?    """
    # --- 1) 闂備胶纭堕弲鐐测枍閿濆鈧線宕ㄩ婧惧亾閹烘宸濇い鏃傝檸濡差垱绻涢幋鐐村碍閻庢稈鏅濋弫顕€骞樼€涙ê鍔?---
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

    # --- 2) 闂備胶顭堢换鎴炵箾婵犲洤鏋佹い鎾跺У鐎氭氨鈧箍鍎遍幊搴ㄦ倵閼姐倗纾?-> 闂佽崵濮甸崝妤呭窗閺囩伝褰掑炊椤掆偓闁裤倝鏌涢妷顔荤暗闁逞屽厴閸?/ 闂備胶鍘ч〃搴㈢濠婂嫭鍙忛柍鍝勬噺閻掕顭跨捄渚剰妞?---
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
        try:
            decoded = base64.b64decode(t + "==="[: (4 - len(t) % 4) % 4]).decode("utf-8", errors="ignore")
            lines = [x.strip() for x in decoded.splitlines() if x.strip()]
            if lines and any("://" in x for x in lines):
                return lines
        except Exception:
            pass
    return [x.strip() for x in t.splitlines() if x.strip()]
