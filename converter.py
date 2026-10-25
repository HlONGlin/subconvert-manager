import base64
import locale
import re
import urllib.parse
from typing import Dict, List, Tuple

from protocols import (
    SUPPORTED_PROTOCOLS, YAML_ONLY_PROTOCOLS, clash_proxy_to_uri,
    clash_yaml_to_v2ray_uris, normalize_proxy_names, split_v2ray_text,
    v2ray_uris_to_clash_proxies,
)


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


def uris_to_v2ray_subscription_base64(uris: List[str]) -> str:
    text = "\n".join(u.strip() for u in uris if u.strip())
    if text:
        text += "\n"
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def build_clash_yaml(proxies: List[Dict]) -> Dict:
    proxies = normalize_proxy_names(proxies)
    names = [p.get("name", "") for p in proxies if p.get("name")]
    group = {
        "name": "🌍选择代理节点",
        "type": "select",
        "proxies": ["DIRECT"] + names,
    }
    return {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": True,
        "mode": "rule",
        "log-level": "info",
        "proxies": proxies,
        "proxy-groups": [group],
        "rules": ["MATCH,🌍选择代理节点"],
    }




# ------------------ ClashPlay YAML builder ------------------

# Prefer locale-aware sorting for Chinese names when available.
# Only set LC_COLLATE to avoid affecting other locale-sensitive operations
# (e.g., number formatting, date parsing) in the same process.
try:
    locale.setlocale(locale.LC_COLLATE, "zh_CN.UTF-8")
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
        if not name:
            continue
        p2 = dict(p)
        p2['name'] = name
        cleaned.append(p2)

    # fallback when no valid proxies
    if not cleaned:
        return build_clash_yaml([])

    cleaned = normalize_proxy_names(cleaned)
    cleaned.sort(key=lambda x: _keyword_sort_key(x.get('name') or ''))

    # 2) keep every node as an individual selectable entry.
    # Do not generate url-test or load-balance groups.
    all_proxy_names = [p['name'] for p in cleaned]
    proxy_groups = [{
        'name': '🌍选择代理节点',
        'type': 'select',
        'proxies': ['DIRECT'] + all_proxy_names,
    }]

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
