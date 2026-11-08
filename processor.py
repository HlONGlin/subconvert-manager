import copy
import re
from typing import Dict, List


def _matches(name: str, pattern: str, mode: str) -> bool:
    if mode == "regex":
        patterns = [item.strip() for item in pattern.splitlines() if item.strip()]
        try:
            return any(re.search(item, name, re.IGNORECASE) for item in patterns)
        except re.error:
            return False
    patterns = re.split(r"[\n,，]+", pattern)
    terms = [item.lower() for item in patterns]
    return any(term in name.lower() for term in terms)


def _identity(proxy: Dict) -> tuple:
    item = dict(proxy)
    item.pop("name", None)
    return tuple(sorted((str(key), repr(value)) for key, value in item.items()))


def process_proxies(
    proxies: List[Dict],
    *,
    filter_include: str = "",
    filter_exclude: str = "",
    filter_mode: str = "keyword",
    rename_regex: str = "",
    rename_with: str = "",
    dedupe: bool = True,
    sort: str = "name",
) -> List[Dict]:
    include = (filter_include or "").strip()
    exclude = (filter_exclude or "").strip()
    mode = (filter_mode or "keyword").strip().lower()
    if mode not in ("keyword", "regex"):
        mode = "keyword"

    result: List[Dict] = []
    seen = set()
    used_names = set()
    for source in proxies or []:
        if not isinstance(source, dict):
            continue
        name = str(source.get("name") or source.get("type") or "proxy").strip()
        if include and not _matches(name, include, mode):
            continue
        if exclude and _matches(name, exclude, mode):
            continue

        proxy = copy.deepcopy(source)
        pattern = (rename_regex or "").strip()
        if pattern:
            try:
                proxy["name"] = re.sub(pattern, rename_with or "", name)
            except re.error:
                proxy["name"] = name
        else:
            proxy["name"] = name
        proxy["name"] = str(proxy.get("name") or "proxy").strip() or "proxy"

        identity = _identity(proxy)
        if dedupe and identity in seen:
            continue
        seen.add(identity)
        base_name = proxy["name"]
        suffix = 2
        while proxy["name"] in used_names:
            proxy["name"] = f"{base_name}-{suffix}"
            suffix += 1
        used_names.add(proxy["name"])
        result.append(proxy)

    order = (sort or "name").strip().lower()
    if order == "name":
        result.sort(key=lambda item: str(item.get("name") or ""))
    elif order == "name_desc":
        result.sort(key=lambda item: str(item.get("name") or ""), reverse=True)
    elif order == "protocol":
        result.sort(key=lambda item: (str(item.get("type") or ""), str(item.get("name") or "")))
    return result
