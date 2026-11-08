import json
import os
import time
from typing import Any, Dict, List, Optional


def now_ts() -> int:
    return int(time.time())


def _normalize_data(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"sources": [], "profiles": []}

    raw_sources = data.get("sources", [])
    if not isinstance(raw_sources, list):
        raw_sources = []

    sources = [s for s in raw_sources if isinstance(s, dict)]
    out = dict(data)
    raw_profiles = data.get("profiles", [])
    if not isinstance(raw_profiles, list):
        raw_profiles = []
    out["sources"] = sources
    out["profiles"] = [item for item in raw_profiles if isinstance(item, dict)]
    return out


def load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"sources": [], "profiles": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _normalize_data(json.load(f))
    except (OSError, json.JSONDecodeError):
        return {"sources": [], "profiles": []}


def save_json(path: str, data: Dict[str, Any]) -> None:
    dirpath = os.path.dirname(path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_normalize_data(data), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def list_sources(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _normalize_data(data)["sources"]


def get_source(data: Dict[str, Any], sid: str) -> Optional[Dict[str, Any]]:
    sid = (sid or "").strip()
    if not sid:
        return None
    for s in list_sources(data):
        if str(s.get("id") or "").strip() == sid:
            return s
    return None


def upsert_source(data: Dict[str, Any], src: Dict[str, Any]) -> None:
    if not isinstance(src, dict):
        return

    sid = str(src.get("id") or "").strip()
    if not sid:
        return

    src = dict(src)
    src["id"] = sid
    src["updated_at"] = now_ts()

    xs = list_sources(data)
    for i, s in enumerate(xs):
        if str(s.get("id") or "").strip() == sid:
            for key in ("last_checked_at", "last_success_at", "last_status", "last_node_count", "last_error"):
                if key in s:
                    src[key] = s[key]
            xs[i] = src
            data["sources"] = xs
            return

    xs.append(src)
    data["sources"] = xs


def delete_source(data: Dict[str, Any], sid: str) -> bool:
    sid = (sid or "").strip()
    if not sid:
        return False

    xs = list_sources(data)
    n0 = len(xs)
    data["sources"] = [s for s in xs if str(s.get("id") or "").strip() != sid]
    for profile in list_profiles(data):
        source_ids = profile.get("source_ids") or []
        if sid in source_ids:
            profile["source_ids"] = [item for item in source_ids if item != sid]
    data["profiles"] = list_profiles(data)
    return len(data["sources"]) != n0


def list_profiles(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _normalize_data(data)["profiles"]


def get_profile(data: Dict[str, Any], pid: str) -> Optional[Dict[str, Any]]:
    pid = (pid or "").strip()
    return next((item for item in list_profiles(data) if str(item.get("id") or "") == pid), None)


def upsert_profile(data: Dict[str, Any], profile: Dict[str, Any]) -> None:
    pid = str(profile.get("id") or "").strip()
    if not pid:
        return
    item = dict(profile)
    item["id"] = pid
    item["updated_at"] = now_ts()
    profiles = list_profiles(data)
    for index, current in enumerate(profiles):
        if str(current.get("id") or "").strip() == pid:
            profiles[index] = item
            break
    else:
        profiles.append(item)
    data["profiles"] = profiles


def delete_profile(data: Dict[str, Any], pid: str) -> bool:
    profiles = list_profiles(data)
    data["profiles"] = [item for item in profiles if str(item.get("id") or "") != (pid or "")]
    return len(data["profiles"]) != len(profiles)

def update_source_fields(data: Dict[str, Any], sid: str, fields: Dict[str, Any]) -> bool:
    sid = (sid or "").strip()
    if not sid or not isinstance(fields, dict):
        return False
    sources = list_sources(data)
    for index, source in enumerate(sources):
        if str(source.get("id") or "").strip() != sid:
            continue
        item = dict(source)
        item.update(fields)
        sources[index] = item
        data["sources"] = sources
        return True
    return False
