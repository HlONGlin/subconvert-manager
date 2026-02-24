import json
import os
import time
from typing import Any, Dict, List, Optional


def now_ts() -> int:
    return int(time.time())


def _normalize_data(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"sources": []}

    raw_sources = data.get("sources", [])
    if not isinstance(raw_sources, list):
        raw_sources = []

    sources = [s for s in raw_sources if isinstance(s, dict)]
    out = dict(data)
    out["sources"] = sources
    return out


def load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"sources": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _normalize_data(json.load(f))
    except (OSError, json.JSONDecodeError):
        return {"sources": []}


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
    return len(data["sources"]) != n0
