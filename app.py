import base64
import json
import logging
import os
import re
import secrets
import subprocess
import threading
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

import requests
import yaml
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from exporter import build_custom_clash_template, build_singbox_config, is_singbox_supported
from processor import process_proxies
from converter import (
    build_clashplay_yaml,
    clash_yaml_to_v2ray_uris,
    split_v2ray_text,
    uris_to_v2ray_subscription_base64,
    v2ray_uris_to_clash_proxies,
)
from protocols import SCHEME_TYPES, YAML_ONLY_PROTOCOLS
from storage import (
    delete_profile,
    delete_source,
    get_profile,
    get_source,
    list_profiles,
    list_sources,
    load_json,
    save_json,
    upsert_profile,
    upsert_source,
    update_source_fields,
)

app = FastAPI(title="SubConvert Manager")
logger = logging.getLogger(__name__)
APP_DIR = os.path.dirname(__file__)
CONFIG_ENV_FILE = os.path.join(APP_DIR, "config.env")
DEFAULT_BASIC_USER = "admin"
DEFAULT_BASIC_PASS = "change_me_please"


def _app_version() -> str:
    try:
        with open(os.path.join(APP_DIR, "VERSION"), "r", encoding="utf-8") as version_file:
            return version_file.read().strip() or "unknown"
    except OSError:
        return "unknown"


def load_env() -> None:
    if not os.path.exists(CONFIG_ENV_FILE):
        return

    try:
        with open(CONFIG_ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = (line or "").strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        return


def _safe_int(v: object, default: int) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _safe_float(v: object, default: float) -> float:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return default


def _clamp(v: int, low: int, high: int) -> int:
    return max(low, min(high, v))


def _normalize_sid(sid: str) -> str:
    sid = (sid or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", sid):
        raise HTTPException(status_code=404, detail="Source not found")
    return sid


def _normalize_token(token: Optional[str]) -> str:
    return (token or "").strip()


def _normalize_clash_template(template: Optional[str]) -> str:
    template = (template or "play").strip().lower()
    if template != "play":
        raise HTTPException(status_code=400, detail="Unsupported Clash template")
    return template


def _is_initial_setup_required() -> bool:
    return BASIC_USER == DEFAULT_BASIC_USER and BASIC_PASS == DEFAULT_BASIC_PASS


def _save_env_values(values: Dict[str, str]) -> None:
    lines: List[str] = []
    if os.path.exists(CONFIG_ENV_FILE):
        with open(CONFIG_ENV_FILE, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

    seen = set()
    out: List[str] = []
    for line in lines:
        stripped = (line or "").strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue

        key, _ = line.split("=", 1)
        key = key.strip()
        if key in values:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)

    for key, value in values.items():
        if key not in seen:
            out.append(f"{key}={value}")

    data = "\n".join(out).rstrip("\n") + "\n"
    tmp = CONFIG_ENV_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, CONFIG_ENV_FILE)


def _set_admin_credentials(username: str, password: str) -> None:
    global BASIC_USER, BASIC_PASS
    BASIC_USER = username
    BASIC_PASS = password
    os.environ["BASIC_AUTH_USER"] = username
    os.environ["BASIC_AUTH_PASS"] = password


def _validate_setup_credentials(username: str, password: str, confirm_password: str) -> Optional[str]:
    if not username or not password or not confirm_password:
        return "Please fill username and password"

    if ":" in username:
        return "Username cannot contain ':'"

    if len(username) < 3 or len(username) > 64:
        return "Username length must be 3-64"

    if len(password) < 8 or len(password) > 128:
        return "Password length must be 8-128"

    if password != confirm_password:
        return "Two passwords do not match"

    if username == DEFAULT_BASIC_USER and password == DEFAULT_BASIC_PASS:
        return "Do not keep default credentials"

    return None


def _format_ts(value: object) -> str:
    try:
        ts = int(value)
        if ts <= 0:
            return "-"
        dt = datetime.fromtimestamp(ts)
        diff = max(0, int(time.time()) - ts)
        if diff < 30 * 60:
            return "刚刚更新"
        if diff < 24 * 3600:
            hours = max(1, diff // 3600)
            return f"{hours} 小时前"
        return dt.strftime("%m-%d")
    except (TypeError, ValueError, OSError):
        return "-"


def _format_bytes(value: object) -> str:
    size = float(max(0, _safe_int(value, 0)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return "0 B"


def _format_reset(value: object) -> str:
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        number = int(value)
        if number >= 1_000_000_000:
            return _format_ts(number)
        if 1 <= number <= 31:
            return f"每月 {number} 日"
    return str(value or "未提供")


def _url_suffix_value() -> str:
    return (URL_SUFFIX or "").strip().strip("/")


def _url_prefix() -> str:
    suffix = _url_suffix_value()
    if not suffix:
        return ""
    return f"/{suffix}"


def _with_url_prefix(path: str) -> str:
    raw = (path or "").strip()
    if not raw:
        raw = "/"
    if not raw.startswith("/"):
        raw = "/" + raw

    prefix = _url_prefix()
    if not prefix:
        return raw

    if raw == prefix or raw.startswith(prefix + "/"):
        return raw

    if raw == "/":
        return prefix

    return prefix + raw


def _template_context(request: Request, **extra: object) -> Dict[str, object]:
    ctx: Dict[str, object] = {
        "request": request,
        "url_prefix": _url_prefix(),
    }
    ctx.update(extra)
    return ctx


load_env()

_raw_session_secret = (os.environ.get("SESSION_SECRET") or "").strip()
SESSION_SECRET = _raw_session_secret if _raw_session_secret else secrets.token_hex(32)
TIMEOUT = _clamp(_safe_int(os.environ.get("TIMEOUT", "15"), 15), 1, 20)
DATA_FILE = (os.environ.get("DATA_FILE") or "data/sources.json").strip() or "data/sources.json"
BASIC_USER = (os.environ.get("BASIC_AUTH_USER") or DEFAULT_BASIC_USER).strip() or DEFAULT_BASIC_USER
BASIC_PASS = (os.environ.get("BASIC_AUTH_PASS") or DEFAULT_BASIC_PASS).strip() or DEFAULT_BASIC_PASS
SUB_TOKEN = (os.environ.get("SUB_TOKEN") or "").strip()
URL_SUFFIX = (os.environ.get("URL_SUFFIX") or "").strip()
UPDATE_BRANCH = (os.environ.get("UPDATE_BRANCH") or "main").strip() or "main"
LOGIN_MAX_FAILS = _clamp(_safe_int(os.environ.get("LOGIN_MAX_FAILS", "3"), 3), 1, 10)
LOGIN_LOCK_SECONDS = _clamp(_safe_int(os.environ.get("LOGIN_LOCK_SECONDS", "900"), 900), 60, 86400)
MAX_REMOTE_BYTES = _clamp(_safe_int(os.environ.get("MAX_REMOTE_BYTES", "2097152"), 2097152), 262144, 10 * 1024 * 1024)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.filters["fmt_ts"] = _format_ts
templates.env.filters["fmt_bytes"] = _format_bytes
templates.env.filters["fmt_reset"] = _format_reset
security = HTTPBasic()


@app.middleware("http")
async def suffix_path_middleware(request: Request, call_next):
    prefix = _url_prefix()
    if not prefix:
        return await call_next(request)

    path = request.scope.get("path") or "/"
    if path == prefix:
        request.scope["path"] = "/"
        return await call_next(request)

    if path.startswith(prefix + "/"):
        request.scope["path"] = path[len(prefix) :] or "/"
        return await call_next(request)

    return _render_http_error(request, 404, "当前已启用 URL_SUFFIX，请使用带安全后缀的完整地址访问。")

_FETCH_CACHE: Dict[str, Tuple[float, str, str]] = {}
_FETCH_CACHE_LOCK = threading.Lock()
_FETCH_CACHE_TTL = max(0.0, _safe_float(os.environ.get("FETCH_CACHE_TTL", "300"), 300.0))
_FETCH_CACHE_MAX = _clamp(_safe_int(os.environ.get("FETCH_CACHE_MAX", "256"), 256), 16, 4096)
AUTO_CHECK_INTERVAL = _clamp(_safe_int(os.environ.get("AUTO_CHECK_INTERVAL", "21600"), 21600), 0, 604800)
_SOURCE_STATUS_LOCK = threading.Lock()
_SOURCE_STATUS_CACHE: Dict[str, Tuple[str, int, float]] = {}
_LOGIN_FAIL_STATE: Dict[str, Tuple[int, float]] = {}
_LOGIN_FAIL_LOCK = threading.Lock()
_ACCESS_STATS_LOCK = threading.Lock()
_AUTO_CHECK_STOP = threading.Event()
_AUTO_CHECK_THREAD: Optional[threading.Thread] = None


def _prune_fetch_cache(now: Optional[float] = None) -> None:
    ts = time.monotonic() if now is None else now

    expired = [k for k, (exp, _, _) in _FETCH_CACHE.items() if exp <= ts]
    for k in expired:
        _FETCH_CACHE.pop(k, None)

    overflow = len(_FETCH_CACHE) - _FETCH_CACHE_MAX
    if overflow <= 0:
        return

    # Drop entries with the earliest expiration first.
    for k, _ in sorted(_FETCH_CACHE.items(), key=lambda item: item[1][0])[:overflow]:
        _FETCH_CACHE.pop(k, None)


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


def require_basic_auth(credentials: HTTPBasicCredentials = Depends(security)) -> bool:
    u_ok = secrets.compare_digest((credentials.username or "").strip(), BASIC_USER)
    p_ok = secrets.compare_digest((credentials.password or "").strip(), BASIC_PASS)
    if not (u_ok and p_ok):
        raise HTTPException(status_code=401, detail="Authentication failed", headers={"WWW-Authenticate": "Basic"})
    return True


def _basic_auth_if_present(request: Request) -> Optional[bool]:
    auth = request.headers.get("authorization", "")
    if not auth or not auth.lower().startswith("basic "):
        return None

    try:
        raw = base64.b64decode(auth.split(" ", 1)[1].strip()).decode("utf-8", errors="ignore")
        username, password = raw.split(":", 1)
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid auth header") from e

    u_ok = secrets.compare_digest((username or "").strip(), BASIC_USER)
    p_ok = secrets.compare_digest((password or "").strip(), BASIC_PASS)
    if not (u_ok and p_ok):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return True


def require_admin_auth(request: Request) -> bool:
    if _is_initial_setup_required():
        raise HTTPException(status_code=307, detail="redirect_setup")

    if request.session.get("is_admin"):
        return True

    mode = (os.environ.get("AUTH_MODE", "both") or "both").strip().lower()
    if mode in ("basic", "both") and _basic_auth_if_present(request):
        return True

    raise HTTPException(status_code=307, detail="redirect_login")


def _wants_html(request: Request) -> bool:
    path = request.url.path or ""
    accept = (request.headers.get("accept") or "").lower()

    if path.startswith("/s/") or path.startswith("/pub/"):
        return "text/html" in accept

    if "application/json" in accept and "text/html" not in accept:
        return False

    return True


def _render_http_error(request: Request, status_code: int, detail: str):
    if _wants_html(request):
        return templates.TemplateResponse(
            "error.html",
            _template_context(request, status_code=status_code, detail=detail),
            status_code=status_code,
        )
    return JSONResponse(status_code=status_code, content={"detail": detail})


@app.exception_handler(HTTPException)
async def fastapi_http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 307 and str(exc.detail) == "redirect_login":
        return RedirectResponse(url=_with_url_prefix("/login"), status_code=302)
    if exc.status_code == 307 and str(exc.detail) == "redirect_setup":
        return RedirectResponse(url=_with_url_prefix("/setup"), status_code=302)

    detail = str(exc.detail or "Request failed")
    if exc.status_code == 401 and detail.lower() == "not authenticated":
        detail = "Authentication required"
    return _render_http_error(request, exc.status_code, detail)


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 307 and str(exc.detail) == "redirect_login":
        return RedirectResponse(url=_with_url_prefix("/login"), status_code=302)
    if exc.status_code == 307 and str(exc.detail) == "redirect_setup":
        return RedirectResponse(url=_with_url_prefix("/setup"), status_code=302)

    detail = str(exc.detail or "Request failed")
    if exc.status_code == 401 and detail.lower() == "not authenticated":
        detail = "Authentication required"
    return _render_http_error(request, exc.status_code, detail)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception for %s %s", request.method, request.url.path, exc_info=exc)
    return _render_http_error(request, 500, "Internal server error")


def require_sub_token(token: Optional[str]) -> bool:
    token = _normalize_token(token)
    if not SUB_TOKEN:
        raise HTTPException(status_code=500, detail="SUB_TOKEN is not configured")
    if not token or not secrets.compare_digest(token, SUB_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid token")
    return True


def _resource_collection(db: dict, kind: str) -> List[dict]:
    return list_sources(db) if kind == "source" else list_profiles(db)


def _find_subscription(db: dict, kind: str, resource_id: str) -> Optional[dict]:
    return next((item for item in _resource_collection(db, kind)
                 if str(item.get("id") or "") == resource_id), None)


def _ensure_resource_tokens(db: dict) -> bool:
    with _ACCESS_STATS_LOCK:
        changed = False
        for kind in ("source", "profile"):
            for item in _resource_collection(db, kind):
                if not item.get("access_token"):
                    item["access_token"] = secrets.token_urlsafe(32)
                    item.setdefault("access_count", 0)
                    changed = True
        if changed:
            _save_db(db)
        return changed


def require_resource_token(token: Optional[str], kind: str, resource_id: str) -> bool:
    item = _find_subscription(_load_db(), kind, resource_id)
    if item and item.get("access_token"):
        candidate = _normalize_token(token)
        if not candidate or not secrets.compare_digest(candidate, str(item["access_token"])):
            raise HTTPException(status_code=401, detail="Invalid subscription token")
    else:
        require_sub_token(token)
    with _ACCESS_STATS_LOCK:
        db = _load_db()
        current = _find_subscription(db, kind, resource_id)
        if current:
            current["access_count"] = _safe_int(current.get("access_count"), 0) + 1
            current["last_access_at"] = int(time.time())
            _save_db(db)
    return True


def require_url_suffix(suffix: Optional[str]) -> bool:
    expected = (URL_SUFFIX or "").strip()
    if not expected:
        return True

    candidate = _normalize_token(suffix)
    if not candidate or not secrets.compare_digest(candidate, expected):
        raise HTTPException(status_code=401, detail="Invalid suffix")
    return True


def _login_key(request: Request, username: str) -> str:
    ip = ""
    if request.client and request.client.host:
        ip = request.client.host
    return f"{(username or '').strip().lower()}@{ip}"


def _login_lock_remaining(key: str) -> int:
    now = time.time()
    with _LOGIN_FAIL_LOCK:
        state = _LOGIN_FAIL_STATE.get(key)
        if not state:
            return 0

        _, locked_until = state
        if locked_until <= now:
            _LOGIN_FAIL_STATE.pop(key, None)
            return 0

        return int(max(1, locked_until - now))


def _record_login_failure(key: str) -> int:
    now = time.time()
    with _LOGIN_FAIL_LOCK:
        fail_count, locked_until = _LOGIN_FAIL_STATE.get(key, (0, 0.0))
        if locked_until > now:
            return int(max(1, locked_until - now))

        fail_count += 1
        if fail_count >= LOGIN_MAX_FAILS:
            locked_until = now + LOGIN_LOCK_SECONDS
            _LOGIN_FAIL_STATE[key] = (fail_count, locked_until)
            return LOGIN_LOCK_SECONDS

        _LOGIN_FAIL_STATE[key] = (fail_count, 0.0)
        return 0


def _clear_login_failure(key: str) -> None:
    with _LOGIN_FAIL_LOCK:
        _LOGIN_FAIL_STATE.pop(key, None)


def _run_git_command(args: List[str], timeout_sec: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=APP_DIR, text=True, capture_output=True, timeout=timeout_sec)


def _git_error_message(proc: subprocess.CompletedProcess) -> str:
    msg = (proc.stderr or proc.stdout or "").strip()
    if not msg:
        msg = "unknown error"
    return msg.splitlines()[0][:180]


def _parse_subscription_userinfo(value: str) -> Dict[str, object]:
    fields: Dict[str, str] = {}
    for part in (value or "").split(";"):
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        fields[key.strip().lower()] = raw.strip()
    result: Dict[str, object] = {}
    for key in ("upload", "download", "total", "expire"):
        if fields.get(key, "").isdigit():
            result[key] = int(fields[key])
    reset = fields.get("reset") or fields.get("reset_at") or fields.get("reset_day")
    if reset:
        result["reset"] = int(reset) if reset.isdigit() else reset
    return result


def _fetch_text(
    url: str, metadata: Optional[Dict[str, str]] = None, force_refresh: bool = False
) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL")

    now = time.monotonic()
    if not force_refresh:
        with _FETCH_CACHE_LOCK:
            _prune_fetch_cache(now)
            cached = _FETCH_CACHE.get(url)
            if cached and cached[0] > now:
                if metadata is not None:
                    metadata["subscription_userinfo"] = cached[2]
                return cached[1]

    try:
        with requests.get(
            url,
            timeout=(5, TIMEOUT),
            headers={"User-Agent": "subconvert-manager/1.2"},
            allow_redirects=True,
            stream=True,
        ) as r:
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Remote returned HTTP {r.status_code}")
            userinfo = r.headers.get("Subscription-Userinfo", "")
            if metadata is not None:
                metadata["subscription_userinfo"] = userinfo

            buf = bytearray()
            for chunk in r.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                buf.extend(chunk)
                if len(buf) > MAX_REMOTE_BYTES:
                    raise HTTPException(status_code=413, detail="Remote content too large")

            text = buf.decode("utf-8", errors="ignore")
            if _FETCH_CACHE_TTL > 0:
                with _FETCH_CACHE_LOCK:
                    _FETCH_CACHE[url] = (time.monotonic() + _FETCH_CACHE_TTL, text, userinfo)
                    _prune_fetch_cache()
            return text
    except HTTPException:
        raise
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="Upstream request timeout")
    except requests.ConnectionError:
        raise HTTPException(status_code=502, detail="Cannot connect to upstream")
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="Upstream request failed")


def _parse_clash_yaml_text(text: str) -> dict:
    try:
        doc = yaml.safe_load(text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"YAML parse failed: {e}") from e

    if not isinstance(doc, dict):
        raise HTTPException(status_code=400, detail="Invalid Clash YAML document")

    proxies = doc.get("proxies")
    if not isinstance(proxies, list):
        raise HTTPException(status_code=400, detail="Invalid Clash YAML: missing proxies list")
    return doc


def _detect_source_kind(value: str, has_file: bool = False) -> str:
    if has_file:
        return "clash_yaml"

    text = (value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme.lower() in ("http", "https") and parsed.netloc:
        return "clash_url"

    try:
        document = yaml.safe_load(text)
    except Exception:
        document = None
    if isinstance(document, dict) and isinstance(document.get("proxies"), list):
        return "clash_yaml"

    known_schemes = set(SCHEME_TYPES) | set(YAML_ONLY_PROTOCOLS)
    if any(uri.split("://", 1)[0].lower() in known_schemes for uri in split_v2ray_text(text)):
        return "v2ray_text"

    raise HTTPException(
        status_code=400,
        detail="Unable to detect source type. Provide a subscription URL, V2Ray URI/Base64, or Clash YAML.",
    )


def _source_proxies(
    src: dict, issues: Optional[List[dict]] = None, metadata: Optional[Dict[str, str]] = None,
    force_refresh: bool = False,
) -> List[dict]:
    kind = (src or {}).get("kind")
    value = str((src or {}).get("value") or "")
    if kind == "clash_url":
        value = _fetch_text(value, metadata, force_refresh=force_refresh)
    if kind in ("clash_url", "clash_yaml"):
        return list(_parse_clash_yaml_text(value).get("proxies") or [])
    if kind == "v2ray_text":
        return v2ray_uris_to_clash_proxies(split_v2ray_text(value), issues=issues)
    return []


def _profile_or_404(pid: str, db: Optional[dict] = None) -> dict:
    pid = _normalize_sid(pid)
    profile = get_profile(db or _load_db(), pid)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


def _profile_proxies(profile: dict, issues: List[dict]) -> List[dict]:
    db = _load_db()
    nodes: List[dict] = []
    for source_id in profile.get("source_ids") or []:
        src = get_source(db, str(source_id))
        if not src:
            issues.append({"index": 0, "protocol": "source", "reason": f"missing source {source_id}", "severity": "error"})
            continue
        local_issues: List[dict] = []
        try:
            source_nodes = _checked_source_proxies(src, local_issues)
            nodes.extend(source_nodes)
            if not source_nodes:
                issues.append({"index": 0, "protocol": "source", "reason": "source has no usable nodes", "severity": "error"})
        except HTTPException:
            issues.append({"index": 0, "protocol": "source", "reason": "source fetch or parse failed", "severity": "error"})
        issues.extend(local_issues)
    return process_proxies(
        nodes,
        filter_include=profile.get("filter_include") or "",
        filter_exclude=profile.get("filter_exclude") or "",
        filter_mode=profile.get("filter_mode") or "keyword",
        rename_regex=profile.get("rename_regex") or "",
        rename_with=profile.get("rename_with") or "",
        dedupe=bool(profile.get("dedupe", True)),
        sort=profile.get("sort") or "name",
    )


def _conversion_failure(issues: List[dict]) -> HTTPException:
    reasons = "; ".join(
        f"#{item['index']} {item['protocol']}: {item['reason']}"
        for item in issues[:8]
    )
    return HTTPException(
        status_code=422,
        detail="未解析到可转换节点" + (": " + reasons if reasons else ""),
    )


def _conversion_response(body: str, issues: List[dict]) -> PlainTextResponse:
    skipped = sum(item["severity"] == "error" for item in issues)
    warnings = sum(item["severity"] == "warning" for item in issues)
    return PlainTextResponse(body, headers={
        "X-Conversion-Skipped": str(skipped),
        "X-Conversion-Warnings": str(warnings),
        "Cache-Control": "no-store",
    })


def _record_source_result(
    sid: str,
    ok: bool,
    node_count: int = 0,
    partial: bool = False,
    force: bool = False,
    userinfo: str = "",
) -> None:
    status = "warning" if ok and partial else "ok" if ok else "failed"
    checked_at = int(time.time())
    now = time.monotonic()
    with _SOURCE_STATUS_LOCK:
        cached = _SOURCE_STATUS_CACHE.get(sid)
        if not force and not userinfo and cached and cached[:2] == (status, node_count) and now - cached[2] < 60:
            return
        db = _load_db()
        current = get_source(db, sid) or {}
        last_checked = _safe_int(current.get("last_checked_at"), 0)
        if (
            not force
            and current.get("last_status") == status
            and _safe_int(current.get("last_node_count"), 0) == node_count
            and checked_at - last_checked < 60
            and not userinfo
        ):
            _SOURCE_STATUS_CACHE[sid] = (status, node_count, now)
            return
        fields = {
            "last_checked_at": checked_at,
            "last_success_at": checked_at if ok else current.get("last_success_at", 0),
            "last_status": status,
            "last_node_count": node_count,
            "last_error": "部分节点无法转换" if partial else "" if ok else "订阅获取或解析失败",
        }
        health = _parse_subscription_userinfo(userinfo)
        if health:
            fields.update({
                "traffic_upload": health.get("upload", current.get("traffic_upload", 0)),
                "traffic_download": health.get("download", current.get("traffic_download", 0)),
                "traffic_total": health.get("total", current.get("traffic_total", 0)),
                "traffic_expire": health.get("expire", current.get("traffic_expire", 0)),
                "traffic_reset": health.get("reset", current.get("traffic_reset", "")),
                "traffic_checked_at": checked_at,
            })
        if update_source_fields(db, sid, fields):
            _save_db(db)
            _SOURCE_STATUS_CACHE[sid] = (status, node_count, now)


def _checked_source_proxies(
    src: dict, issues: Optional[List[dict]] = None, force: bool = False
) -> List[dict]:
    sid = str((src or {}).get("id") or "")
    metadata: Dict[str, str] = {}
    try:
        nodes = _source_proxies(src, issues, metadata, force_refresh=force)
        if sid:
            has_errors = bool(issues and any(item.get("severity") == "error" for item in issues))
            _record_source_result(sid, bool(nodes), len(nodes), partial=bool(nodes) and has_errors,
                                  force=force, userinfo=metadata.get("subscription_userinfo", ""))
        return nodes
    except Exception:
        if sid:
            _record_source_result(sid, False, force=force, userinfo=metadata.get("subscription_userinfo", ""))
        raise


def run_scheduled_source_checks() -> None:
    for src in list_sources(_load_db()):
        issues: List[dict] = []
        try:
            _checked_source_proxies(src, issues, force=True)
        except Exception:
            logger.exception("Scheduled subscription check failed for %s", src.get("id"))


def _auto_check_worker() -> None:
    last_check = time.monotonic()
    while not _AUTO_CHECK_STOP.wait(1):
        interval = AUTO_CHECK_INTERVAL
        if interval > 0 and time.monotonic() - last_check >= interval:
            run_scheduled_source_checks()
            last_check = time.monotonic()


@app.on_event("startup")
def start_auto_check_worker() -> None:
    global _AUTO_CHECK_THREAD
    if _AUTO_CHECK_THREAD and _AUTO_CHECK_THREAD.is_alive():
        return
    _AUTO_CHECK_STOP.clear()
    _AUTO_CHECK_THREAD = threading.Thread(target=_auto_check_worker, name="subscription-checker", daemon=True)
    _AUTO_CHECK_THREAD.start()


@app.on_event("shutdown")
def stop_auto_check_worker() -> None:
    _AUTO_CHECK_STOP.set()


def _profile_response(profile: dict, fmt: str, issues: List[dict], mode: str = "") -> PlainTextResponse:
    nodes = _profile_proxies(profile, issues)
    if not nodes:
        raise _conversion_failure(issues)
    fmt = (fmt or "clash").strip().lower()
    if fmt in ("v2ray", "v2ray_raw"):
        uris = clash_yaml_to_v2ray_uris({"proxies": nodes}, issues)
        if not uris:
            raise _conversion_failure(issues)
        raw = "\n".join(uris) + "\n"
        body = uris_to_v2ray_subscription_base64(uris) if fmt == "v2ray" else raw
    elif fmt == "singbox":
        return _singbox_response(nodes, issues, mode)
    else:
        template = profile.get("custom_template") or ""
        if template:
            try:
                doc = build_custom_clash_template(nodes, template)
            except (yaml.YAMLError, ValueError):
                raise HTTPException(status_code=422, detail="Invalid Clash template")
        else:
            doc = build_clashplay_yaml(
                nodes,
                rate_limit_mbps=_safe_int(profile.get("rate_limit_mbps"), 0),
                sort_nodes=False,
            )
        body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    if not body.endswith("\n"):
        body += "\n"
    response = _conversion_response(body, issues)
    response.headers["X-Node-Count"] = str(len(nodes))
    return response


def _singbox_response(nodes: List[dict], issues: List[dict], mode: str = "") -> Response:
    prepared = process_proxies(nodes, dedupe=False, sort="source")
    supported = [item for item in prepared if is_singbox_supported(item)]
    if not supported:
        raise HTTPException(status_code=422, detail="No nodes in this subscription are supported by the sing-box exporter")
    body = json.dumps(build_singbox_config(supported, bare=mode == "bare"), ensure_ascii=False, indent=2) + "\n"
    response = Response(body, media_type="application/json")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Node-Count"] = str(len(supported))
    response.headers["X-Output-Skipped"] = str(len(nodes) - len(supported))
    response.headers["X-Conversion-Skipped"] = str(sum(item.get("severity") == "error" for item in issues))
    response.headers["X-Conversion-Warnings"] = str(sum(item.get("severity") == "warning" for item in issues))
    return response


def _load_db() -> Dict[str, object]:
    db = load_json(DATA_FILE)
    if not isinstance(db, dict):
        return {"sources": []}
    return db


def _save_db(db: Dict[str, object]) -> None:
    save_json(DATA_FILE, db)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if _is_initial_setup_required():
        return RedirectResponse(url=_with_url_prefix("/setup"), status_code=302)

    if request.session.get("is_admin"):
        return RedirectResponse(url=_with_url_prefix("/"), status_code=302)
    return templates.TemplateResponse("login.html", _template_context(request, error=""))


def _parse_source_ids(values: Optional[List[str]]) -> List[str]:
    result: List[str] = []
    for value in values or []:
        for item in str(value).split(","):
            item = item.strip()
            if item and item not in result:
                result.append(item)
    return result


def _validate_profile_form(
    name: str,
    source_ids: List[str],
    filter_mode: str,
    filter_include: str,
    filter_exclude: str,
    rename_regex: str,
    rename_with: str,
    rate_limit_mbps: str,
) -> tuple:
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required")
    if len(name) > 80:
        raise HTTPException(status_code=400, detail="Profile name is too long")
    if not source_ids:
        raise HTTPException(status_code=400, detail="Select at least one source")
    mode = (filter_mode or "keyword").strip().lower()
    if mode not in ("keyword", "regex"):
        raise HTTPException(status_code=400, detail="Invalid filter mode")
    if mode == "regex":
        for value in (filter_include, filter_exclude):
            for item in (value or "").splitlines():
                if item.strip():
                    try:
                        re.compile(item.strip())
                    except re.error as exc:
                        raise HTTPException(status_code=400, detail=f"Invalid filter regex: {exc}")
    pattern = (rename_regex or "").strip()
    if pattern:
        try:
            re.compile(pattern)
            re.sub(pattern, rename_with or "", "")
        except re.error as exc:
            raise HTTPException(status_code=400, detail=f"Invalid rename regex: {exc}")
    replacement = rename_with or ""
    rate = _safe_int(rate_limit_mbps, 0)
    if not 0 <= rate <= 10000:
        raise HTTPException(status_code=400, detail="Invalid rate limit")
    return name, mode, pattern, replacement, rate


@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    if not _is_initial_setup_required():
        return RedirectResponse(url=_with_url_prefix("/login?toast=Setup already completed"), status_code=302)

    return templates.TemplateResponse(
        "setup.html",
        _template_context(request, error="", username=DEFAULT_BASIC_USER),
    )


@app.post("/setup", response_class=HTMLResponse)
def setup_submit(
    request: Request,
    username: str = Form(default=""),
    password: str = Form(default=""),
    confirm_password: str = Form(default=""),
):
    if not _is_initial_setup_required():
        return RedirectResponse(url=_with_url_prefix("/login?toast=Setup already completed"), status_code=302)

    username = (username or "").strip()
    password = (password or "").strip()
    confirm_password = (confirm_password or "").strip()

    error = _validate_setup_credentials(username, password, confirm_password)
    if error:
        return templates.TemplateResponse(
            "setup.html",
            _template_context(request, error=error, username=username),
            status_code=400,
        )

    _save_env_values(
        {
            "BASIC_AUTH_USER": username,
            "BASIC_AUTH_PASS": password,
        }
    )
    _set_admin_credentials(username, password)

    # Persist a strong session secret on first setup if one isn't already in the env file.
    if not (os.environ.get("SESSION_SECRET") or "").strip():
        new_secret = secrets.token_hex(32)
        _save_env_values({"SESSION_SECRET": new_secret})

    request.session.clear()
    request.session["is_admin"] = True
    request.session["username"] = username
    return RedirectResponse(url=_with_url_prefix("/?toast=Initial setup completed"), status_code=302)


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(default=""),
    password: str = Form(default=""),
):
    if _is_initial_setup_required():
        return RedirectResponse(url=_with_url_prefix("/setup"), status_code=302)

    username = (username or "").strip()
    password = (password or "").strip()
    login_key = _login_key(request, username)

    if not username or not password:
        return templates.TemplateResponse(
            "login.html",
            _template_context(request, error="请输入账号和密码"),
            status_code=400,
        )

    remaining = _login_lock_remaining(login_key)
    if remaining > 0:
        return templates.TemplateResponse(
            "login.html",
            _template_context(request, error=f"连续失败次数过多，请 {remaining} 秒后再试"),
            status_code=429,
        )

    if not (secrets.compare_digest(username, BASIC_USER) and secrets.compare_digest(password, BASIC_PASS)):
        lock_seconds = _record_login_failure(login_key)
        if lock_seconds > 0:
            msg = f"连续失败 {LOGIN_MAX_FAILS} 次，已锁定 {LOGIN_LOCK_SECONDS} 秒"
            code = 429
        else:
            msg = "账号或密码错误"
            code = 401
        return templates.TemplateResponse(
            "login.html",
            _template_context(request, error=msg),
            status_code=code,
        )

    _clear_login_failure(login_key)
    request.session["is_admin"] = True
    request.session["username"] = username
    return RedirectResponse(url=_with_url_prefix("/?toast=登录成功"), status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url=_with_url_prefix("/login?toast=已退出登录"), status_code=302)


@app.post("/admin/update_from_github")
def admin_update_from_github(_=Depends(require_admin_auth)):
    if not os.path.isdir(os.path.join(APP_DIR, ".git")):
        raise HTTPException(status_code=500, detail="当前目录不是 Git 仓库，无法自动更新")

    try:
        fetch_proc = _run_git_command(["git", "fetch", "origin", UPDATE_BRANCH])
        if fetch_proc.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Git fetch failed: {_git_error_message(fetch_proc)}")

        pull_proc = _run_git_command(["git", "pull", "--ff-only", "origin", UPDATE_BRANCH])
        if pull_proc.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Git pull failed: {_git_error_message(pull_proc)}")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="服务器未安装 git")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="更新超时，请稍后重试")

    return RedirectResponse(url=_with_url_prefix("/?toast=已从 GitHub 拉取最新代码，请重启服务生效"), status_code=303)


@app.post("/security/suffix/rotate")
def rotate_security_suffix(_=Depends(require_admin_auth)):
    global URL_SUFFIX

    suffix_len = 3 + secrets.randbelow(3)
    URL_SUFFIX = secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:suffix_len]
    if len(URL_SUFFIX) < 3:
        URL_SUFFIX = uuid.uuid4().hex[:3]

    _save_env_values({"URL_SUFFIX": URL_SUFFIX})
    os.environ["URL_SUFFIX"] = URL_SUFFIX
    return RedirectResponse(url=_with_url_prefix("/?toast=安全后缀已更新，旧公共链接将失效"), status_code=303)


@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings(request: Request, _=Depends(require_admin_auth)):
    return templates.TemplateResponse("settings.html", _template_context(request, settings={
        "PORT": os.environ.get("PORT", ""), "TIMEOUT": TIMEOUT, "DATA_FILE": DATA_FILE,
        "SUB_TOKEN": SUB_TOKEN, "URL_SUFFIX": URL_SUFFIX, "LOGIN_MAX_FAILS": LOGIN_MAX_FAILS,
        "LOGIN_LOCK_SECONDS": LOGIN_LOCK_SECONDS, "MAX_REMOTE_BYTES": MAX_REMOTE_BYTES,
        "FETCH_CACHE_TTL": int(_FETCH_CACHE_TTL), "UPDATE_BRANCH": UPDATE_BRANCH,
        "AUTO_CHECK_INTERVAL": AUTO_CHECK_INTERVAL,
        "BASIC_AUTH_USER": BASIC_USER,
    }))


@app.post("/admin/settings")
def save_admin_settings(
    port: str = Form(""), timeout: str = Form("15"), data_file: str = Form("data/sources.json"),
    sub_token: str = Form(""), url_suffix: str = Form(""), login_max_fails: str = Form("3"),
    login_lock_seconds: str = Form("900"), max_remote_bytes: str = Form("2097152"),
    fetch_cache_ttl: str = Form("300"), update_branch: str = Form("main"),
    auto_check_interval: str = Form("21600"),
    username: str = Form(""), password: str = Form(""), confirm_password: str = Form(""),
    _=Depends(require_admin_auth),
):
    global TIMEOUT, DATA_FILE, SUB_TOKEN, URL_SUFFIX, LOGIN_MAX_FAILS, LOGIN_LOCK_SECONDS
    global MAX_REMOTE_BYTES, UPDATE_BRANCH, _FETCH_CACHE_TTL, AUTO_CHECK_INTERVAL
    port = port.strip()
    timeout_value, fails_value = _safe_int(timeout, -1), _safe_int(login_max_fails, -1)
    lock_value, bytes_value = _safe_int(login_lock_seconds, -1), _safe_int(max_remote_bytes, -1)
    cache_value = _safe_int(fetch_cache_ttl, -1)
    auto_check_value = _safe_int(auto_check_interval, -1)
    if (port and not (port.isdigit() and 1 <= int(port) <= 65535)) or not 1 <= timeout_value <= 20:
        raise HTTPException(status_code=400, detail="Invalid port or timeout")
    if not 1 <= fails_value <= 10 or not 60 <= lock_value <= 86400:
        raise HTTPException(status_code=400, detail="Invalid login lock settings")
    if not 262144 <= bytes_value <= 10 * 1024 * 1024 or not 0 <= cache_value <= 86400:
        raise HTTPException(status_code=400, detail="Invalid size limit or cache TTL")
    if not 0 <= auto_check_value <= 604800:
        raise HTTPException(status_code=400, detail="Invalid automatic check interval")
    if not data_file.strip():
        raise HTTPException(status_code=400, detail="DATA_FILE is required")
    username = username.strip()
    if password or confirm_password or username != BASIC_USER:
        error = _validate_setup_credentials(username, password, confirm_password)
        if error:
            raise HTTPException(status_code=400, detail=error)
    values = {
        "PORT": port, "TIMEOUT": str(timeout_value), "DATA_FILE": data_file.strip(),
        "SUB_TOKEN": sub_token.strip(), "URL_SUFFIX": url_suffix.strip().strip("/"),
        "LOGIN_MAX_FAILS": str(fails_value), "LOGIN_LOCK_SECONDS": str(lock_value),
        "MAX_REMOTE_BYTES": str(bytes_value), "FETCH_CACHE_TTL": str(cache_value),
        "UPDATE_BRANCH": update_branch.strip() or "main",
        "AUTO_CHECK_INTERVAL": str(auto_check_value),
    }
    if password:
        values.update({"BASIC_AUTH_USER": username, "BASIC_AUTH_PASS": password})
    _save_env_values(values)
    for key, value in values.items():
        os.environ[key] = value
    TIMEOUT, DATA_FILE, SUB_TOKEN = timeout_value, data_file.strip(), sub_token.strip()
    URL_SUFFIX = values["URL_SUFFIX"]
    LOGIN_MAX_FAILS, LOGIN_LOCK_SECONDS = fails_value, lock_value
    MAX_REMOTE_BYTES, UPDATE_BRANCH, _FETCH_CACHE_TTL = bytes_value, values["UPDATE_BRANCH"], float(cache_value)
    AUTO_CHECK_INTERVAL = auto_check_value
    if password:
        _set_admin_credentials(username, password)
    with _FETCH_CACHE_LOCK:
        _FETCH_CACHE.clear()
    return RedirectResponse(url=_with_url_prefix("/admin/settings?toast=settings-saved"), status_code=303)


@app.post("/admin/settings/token/rotate")
def rotate_subscription_token(_=Depends(require_admin_auth)):
    global SUB_TOKEN
    SUB_TOKEN = secrets.token_urlsafe(32)
    os.environ["SUB_TOKEN"] = SUB_TOKEN
    _save_env_values({"SUB_TOKEN": SUB_TOKEN})
    return RedirectResponse(url=_with_url_prefix("/admin/settings?toast=token-rotated"), status_code=303)


@app.get("/admin/settings/backup")
def export_backup(_=Depends(require_admin_auth)):
    return Response(json.dumps(_load_db(), ensure_ascii=False, indent=2) + "\n", media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=sources.json"})


@app.post("/admin/settings/backup")
async def import_backup(file: UploadFile = File(...), _=Depends(require_admin_auth)):
    try:
        data = json.loads((await file.read()).decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Backup must be valid UTF-8 JSON")
    if not isinstance(data, dict) or not isinstance(data.get("sources", []), list) or not isinstance(data.get("profiles", []), list):
        raise HTTPException(status_code=400, detail="Backup must contain sources/profiles arrays")
    _save_db({"sources": data.get("sources", []), "profiles": data.get("profiles", [])})
    return RedirectResponse(url=_with_url_prefix("/admin/settings?toast=backup-imported"), status_code=303)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, _=Depends(require_admin_auth)):
    db = _load_db()
    _ensure_resource_tokens(db)
    sources = list_sources(db)
    sources = sorted(sources, key=lambda s: _safe_int((s or {}).get("updated_at"), 0), reverse=True)
    profiles = sorted(list_profiles(db), key=lambda s: _safe_int((s or {}).get("updated_at"), 0), reverse=True)
    current_time = int(time.time())
    for source in sources:
        source["traffic_used"] = _safe_int(source.get("traffic_upload"), 0) + _safe_int(source.get("traffic_download"), 0)
        total = _safe_int(source.get("traffic_total"), 0)
        source["traffic_remaining"] = max(0, total - source["traffic_used"]) if total else 0
        expire = _safe_int(source.get("traffic_expire"), 0)
        source["traffic_expiring"] = bool(expire and current_time < expire <= current_time + 7 * 86400)
    return templates.TemplateResponse(
        "home.html",
        _template_context(
            request,
            sources=sources,
            profiles=profiles,
            sub_token=SUB_TOKEN,
            url_suffix=URL_SUFFIX,
            source_count=len(sources),
            failed_source_count=sum(1 for source in sources if source.get("last_status") == "failed"),
            failed_sources=[source for source in sources if source.get("last_status") == "failed"],
            profile_count=len(profiles),
            node_count=sum(_safe_int(source.get("last_node_count"), 0) for source in sources),
            now_ts=current_time,
            version=_app_version(),
        ),
    )


@app.get("/profiles/new", response_class=HTMLResponse)
def profile_new(request: Request, _=Depends(require_admin_auth)):
    return templates.TemplateResponse(
        "profile_edit.html",
        _template_context(request, profile=None, sources=list_sources(_load_db()), error=None),
    )


@app.get("/profiles/{pid}/edit", response_class=HTMLResponse)
def profile_edit(request: Request, pid: str, _=Depends(require_admin_auth)):
    profile = _profile_or_404(pid)
    return templates.TemplateResponse(
        "profile_edit.html",
        _template_context(request, profile=profile, sources=list_sources(_load_db()), error=None),
    )


@app.post("/profiles/preview")
def profile_preview(
    source_ids: List[str] = Form([]), filter_include: str = Form(""), filter_exclude: str = Form(""),
    filter_mode: str = Form("keyword"), rename_regex: str = Form(""), rename_with: str = Form(""),
    dedupe: str = Form(""), sort: str = Form("name"), _=Depends(require_admin_auth),
):
    db = _load_db()
    sources = {str(source.get("id") or ""): source for source in list_sources(db)}
    requested = _parse_source_ids(source_ids)
    if not requested or any(sid not in sources for sid in requested):
        raise HTTPException(status_code=400, detail="Select existing subscription sources")
    _validate_profile_form("preview", requested, filter_mode, filter_include, filter_exclude,
                           rename_regex, rename_with, "0")
    nodes, skipped = [], []
    for sid in requested:
        try:
            local_issues = []
            parsed = _source_proxies(sources[sid], local_issues)
            nodes.extend(parsed)
            if local_issues:
                skipped.extend(issue.get("reason", "部分节点无法解析") for issue in local_issues)
        except HTTPException:
            skipped.append(str(sources[sid].get("name") or sid) + "：获取或解析失败")
    all_nodes = process_proxies(nodes, dedupe=False, sort="source")
    candidates = process_proxies(nodes, filter_include=filter_include, filter_exclude=filter_exclude,
                                 filter_mode=filter_mode, dedupe=False, sort="source")
    retained_names = {str(item.get("name") or "") for item in candidates}
    skipped.extend(str(item.get("name") or "proxy") for item in all_nodes
                   if str(item.get("name") or "") not in retained_names)
    filtered = process_proxies(nodes, filter_include=filter_include, filter_exclude=filter_exclude,
        filter_mode=filter_mode, rename_regex=rename_regex, rename_with=rename_with,
        dedupe=bool(dedupe), sort=sort)
    return JSONResponse({"count": len(filtered), "names": [item.get("name") for item in filtered], "skipped": skipped})


@app.post("/profiles/save")
def profile_save(
    pid: str = Form(""),
    name: str = Form(""),
    source_ids: List[str] = Form([]),
    filter_include: str = Form(""),
    filter_exclude: str = Form(""),
    filter_mode: str = Form("keyword"),
    rename_regex: str = Form(""),
    rename_with: str = Form(""),
    dedupe: str = Form(""),
    sort: str = Form("name"),
    clash_template: str = Form("default"),
    custom_template: str = Form(""),
    rate_limit_mbps: str = Form("0"),
    _=Depends(require_admin_auth),
):
    name, mode, pattern, replacement, rate = _validate_profile_form(
        name, _parse_source_ids(source_ids), filter_mode,
        filter_include, filter_exclude, rename_regex, rename_with, rate_limit_mbps
    )
    if sort not in ("name", "name_desc", "protocol", "source"):
        sort = "name"
    if clash_template not in ("default", "custom"):
        clash_template = "default"
    custom = custom_template.strip()
    if clash_template == "custom":
        if not custom:
            raise HTTPException(status_code=400, detail="Custom Clash template is empty")
        try:
            custom_doc = yaml.safe_load(custom)
            if not isinstance(custom_doc, dict):
                raise ValueError
        except (yaml.YAMLError, ValueError):
            raise HTTPException(status_code=400, detail="Clash template must be a YAML mapping")
    else:
        custom = ""
    db = _load_db()
    if pid:
        profile = _profile_or_404(pid, db)
    else:
        pid = uuid.uuid4().hex[:10]
        profile = {}
    known = {str(item.get("id") or "") for item in list_sources(db)}
    requested = _parse_source_ids(source_ids)
    if any(item not in known for item in requested):
        raise HTTPException(status_code=400, detail="One or more selected sources no longer exist")
    selected = requested
    profile = {
        **profile,
        "id": pid,
        "name": name,
        "source_ids": selected,
        "filter_include": filter_include.strip(),
        "filter_exclude": filter_exclude.strip(),
        "filter_mode": mode,
        "rename_regex": pattern,
        "rename_with": replacement,
        "dedupe": bool(dedupe),
        "sort": sort,
        "clash_template": clash_template,
        "custom_template": custom,
        "rate_limit_mbps": rate,
        "access_token": profile.get("access_token") or secrets.token_urlsafe(32),
        "access_count": _safe_int(profile.get("access_count"), 0),
        "last_access_at": _safe_int(profile.get("last_access_at"), 0),
    }
    upsert_profile(db, profile)
    _save_db(db)
    return RedirectResponse(url=_with_url_prefix("/?toast=组合订阅已保存"), status_code=303)


@app.post("/profiles/{pid}/delete")
def profile_delete(pid: str, _=Depends(require_admin_auth)):
    db = _load_db()
    _profile_or_404(pid, db)
    delete_profile(db, pid)
    _save_db(db)
    return RedirectResponse(url=_with_url_prefix("/?toast=组合订阅已删除"), status_code=303)


@app.get("/convert", response_class=HTMLResponse)
def convert_page(request: Request, _=Depends(require_admin_auth)):
    return templates.TemplateResponse("convert.html", _template_context(request))


@app.post("/convert/clash_to_v2ray", response_class=HTMLResponse)
async def clash_to_v2ray_web(
    request: Request,
    url: str = Form(""),
    file: UploadFile = File(None),
    out: str = Form("base64"),
    _=Depends(require_admin_auth),
):
    out = (out or "base64").strip().lower()
    if out not in {"base64", "raw"}:
        out = "base64"

    if file is not None and file.filename:
        text = (await file.read()).decode("utf-8", errors="ignore")
        source = f"文件: {file.filename}"
    else:
        url = (url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="请提供 Clash 订阅 URL 或上传 YAML 文件")
        text = _fetch_text(url)
        source = "远程链接"

    doc = _parse_clash_yaml_text(text)
    issues: List[dict] = []
    uris = clash_yaml_to_v2ray_uris(doc, issues=issues)
    if not uris:
        raise _conversion_failure(issues)

    raw = "\n".join(uris) + "\n"
    b64 = uris_to_v2ray_subscription_base64(uris)
    output = b64 if out == "base64" else raw
    return templates.TemplateResponse(
        "result.html",
        _template_context(request, title="Clash -> URI", source=source, count=len(uris), output=output, issues=issues),
    )


@app.post("/convert/v2ray_to_clash", response_class=HTMLResponse)
async def v2ray_to_clash_web(
    request: Request,
    text: str = Form(""),
    out: str = Form("yaml"),
    template: str = Form("play"),
    rate_limit_mbps: str = Form("0"),
    _=Depends(require_admin_auth),
):
    out = (out or "yaml").strip().lower()
    if out != "yaml":
        raise HTTPException(status_code=400, detail="Unsupported output format")
    _normalize_clash_template(template)

    rate_limit = _safe_int(rate_limit_mbps, 0)
    if rate_limit < 0 or rate_limit > 10000:
        raise HTTPException(status_code=400, detail="Invalid rate limit")

    uris = split_v2ray_text((text or "").strip())
    issues: List[dict] = []
    proxies = v2ray_uris_to_clash_proxies(uris, issues=issues)
    if not proxies:
        raise _conversion_failure(issues)

    doc = build_clashplay_yaml(proxies, rate_limit_mbps=rate_limit)

    y = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    return templates.TemplateResponse(
        "result.html",
        _template_context(request, title="URI -> Clash", source="文本输入", count=len(proxies), output=y, issues=issues),
    )


@app.get("/sources/new", response_class=HTMLResponse)
def source_new(request: Request, _=Depends(require_admin_auth)):
    return templates.TemplateResponse("source_edit.html", _template_context(request, src=None))


@app.get("/sources/{sid}/edit", response_class=HTMLResponse)
def source_edit(request: Request, sid: str, _=Depends(require_admin_auth)):
    sid = _normalize_sid(sid)
    src = get_source(_load_db(), sid)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    return templates.TemplateResponse("source_edit.html", _template_context(request, src=src))


@app.post("/sources/save")
async def source_save(
    sid: str = Form(""),
    name: str = Form(...),
    kind: str = Form(...),
    value: str = Form(""),
    clash_template: str = Form("play"),
    rate_limit_mbps: str = Form("0"),
    file: UploadFile = File(None),
    _=Depends(require_admin_auth),
):
    db = _load_db()

    sid = (sid or "").strip()
    if sid:
        sid = _normalize_sid(sid)
    else:
        sid = uuid.uuid4().hex[:10]

    name = (name or "").strip()
    kind = (kind or "").strip().lower()
    value = (value or "").strip()
    clash_template = _normalize_clash_template(clash_template)
    rate_limit = _safe_int(rate_limit_mbps, 0)

    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if len(name) > 80:
        raise HTTPException(status_code=400, detail="Name is too long")

    if kind not in {"auto", "clash_url", "v2ray_text", "clash_yaml"}:
        raise HTTPException(status_code=400, detail="Invalid source type")

    if kind == "auto":
        kind = _detect_source_kind(value, has_file=bool(file is not None and file.filename))

    if rate_limit < 0 or rate_limit > 10000:
        raise HTTPException(status_code=400, detail="Invalid rate limit")

    if kind == "clash_yaml":
        if file is not None and file.filename:
            value = (await file.read()).decode("utf-8", errors="ignore").strip()
        if not value:
            raise HTTPException(status_code=400, detail="Clash YAML cannot be empty")
        _parse_clash_yaml_text(value)

    if kind == "clash_url":
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(status_code=400, detail="Invalid Clash URL")

    if kind == "v2ray_text":
        if not value:
            raise HTTPException(status_code=400, detail="V2Ray text cannot be empty")
        if not split_v2ray_text(value):
            raise HTTPException(status_code=400, detail="V2Ray text has no valid URI")

    upsert_source(
        db,
        {
            "id": sid,
            "name": name,
            "kind": kind,
            "value": value,
            "clash_template": clash_template,
            "rate_limit_mbps": rate_limit,
            "access_token": (get_source(db, sid) or {}).get("access_token") or secrets.token_urlsafe(32),
        },
    )
    _save_db(db)
    with _SOURCE_STATUS_LOCK:
        _SOURCE_STATUS_CACHE.pop(sid, None)
    return RedirectResponse(url=_with_url_prefix("/?toast=保存成功"), status_code=303)


@app.post("/sources/{sid}/delete")
def source_delete(sid: str, _=Depends(require_admin_auth)):
    sid = _normalize_sid(sid)
    db = _load_db()
    delete_source(db, sid)
    _save_db(db)
    with _SOURCE_STATUS_LOCK:
        _SOURCE_STATUS_CACHE.pop(sid, None)
    return RedirectResponse(url=_with_url_prefix("/?toast=删除成功"), status_code=303)


@app.post("/sources/{sid}/check")
def source_check(sid: str, _=Depends(require_admin_auth)):
    src = _source_or_404(sid)
    issues: List[dict] = []
    try:
        nodes = _checked_source_proxies(src, issues, force=True)
        if not nodes:
            message = "订阅检查失败：没有可用节点"
        else:
            message = f"订阅检查成功：{len(nodes)} 个节点"
    except HTTPException:
        message = "订阅检查失败，请检查来源地址和内容"
    return RedirectResponse(url=_with_url_prefix("/?toast=" + quote(message)), status_code=303)


def _resolve_to_uris(src: dict, issues: Optional[List[dict]] = None) -> List[str]:
    kind = (src or {}).get("kind")
    value = (src or {}).get("value") or ""

    if kind == "clash_url":
        text = _fetch_text(str(value))
        doc = _parse_clash_yaml_text(text)
        return clash_yaml_to_v2ray_uris(doc, issues=issues)

    if kind == "clash_yaml":
        doc = _parse_clash_yaml_text(str(value))
        return clash_yaml_to_v2ray_uris(doc, issues=issues)

    if kind == "v2ray_text":
        return split_v2ray_text(str(value))

    return []


def _resolve_to_clash_yaml(src: dict, template: str = "", issues: Optional[List[dict]] = None) -> str:
    kind = (src or {}).get("kind")
    value = (src or {}).get("value") or ""
    _normalize_clash_template(template)

    if kind in ("clash_url", "clash_yaml"):
        if kind == "clash_url":
            return _fetch_text(str(value))
        return str(value)

    uris = split_v2ray_text(str(value))
    proxies = v2ray_uris_to_clash_proxies(uris, issues=issues)
    if not proxies:
        raise _conversion_failure(issues or [])
    doc = build_clashplay_yaml(proxies, rate_limit_mbps=_safe_int((src or {}).get("rate_limit_mbps"), 0))
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def _source_uris(src: dict, nodes: List[dict], issues: List[dict]) -> List[str]:
    if src.get("kind") == "v2ray_text":
        result = split_v2ray_text(str(src.get("value") or ""))
    else:
        result = clash_yaml_to_v2ray_uris({"proxies": nodes}, issues)
    return result


def _source_or_404(sid: str) -> dict:
    sid = _normalize_sid(sid)
    src = get_source(_load_db(), sid)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    return src


@app.get("/s/{sid}/v2ray", response_class=PlainTextResponse)
def sub_v2ray_b64(sid: str, _=Depends(require_admin_auth)):
    issues: List[dict] = []
    src = _source_or_404(sid)
    nodes = _checked_source_proxies(src, issues)
    uris = _source_uris(src, nodes, issues)
    if not uris:
        raise _conversion_failure(issues)
    return _conversion_response(uris_to_v2ray_subscription_base64(uris), issues)


@app.get("/s/{sid}/v2ray_raw", response_class=PlainTextResponse)
def sub_v2ray_raw(sid: str, _=Depends(require_admin_auth)):
    issues: List[dict] = []
    src = _source_or_404(sid)
    nodes = _checked_source_proxies(src, issues)
    uris = _source_uris(src, nodes, issues)
    if not uris:
        raise _conversion_failure(issues)
    return _conversion_response("\n".join(uris) + "\n", issues)


@app.get("/s/{sid}/clash", response_class=PlainTextResponse)
def sub_clash(sid: str, template: str = "", _=Depends(require_admin_auth)):
    issues: List[dict] = []
    src = _source_or_404(sid)
    nodes = _checked_source_proxies(src, issues)
    if src.get("kind") == "v2ray_text":
        doc = build_clashplay_yaml(nodes, rate_limit_mbps=_safe_int(src.get("rate_limit_mbps"), 0))
        y = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    else:
        y = _resolve_to_clash_yaml(src, template=template, issues=issues)
    return _conversion_response(y if y.endswith("\n") else y + "\n", issues)


@app.get("/s/{sid}/singbox")
def sub_singbox(sid: str, mode: str = "", _=Depends(require_admin_auth)):
    issues: List[dict] = []
    nodes = _checked_source_proxies(_source_or_404(sid), issues)
    return _singbox_response(nodes, issues, mode)


@app.get("/pub/s/{sid}/v2ray", response_class=PlainTextResponse)
def pub_v2ray_b64(sid: str, token: str = ""):
    require_resource_token(token, "source", sid)
    issues: List[dict] = []
    src = _source_or_404(sid)
    nodes = _checked_source_proxies(src, issues)
    uris = _source_uris(src, nodes, issues)
    if not uris:
        raise _conversion_failure(issues)
    return _conversion_response(uris_to_v2ray_subscription_base64(uris), issues)


@app.get("/pub/s/{sid}/v2ray_raw", response_class=PlainTextResponse)
def pub_v2ray_raw(sid: str, token: str = ""):
    require_resource_token(token, "source", sid)
    issues: List[dict] = []
    src = _source_or_404(sid)
    nodes = _checked_source_proxies(src, issues)
    uris = _source_uris(src, nodes, issues)
    if not uris:
        raise _conversion_failure(issues)
    return _conversion_response("\n".join(uris) + "\n", issues)


@app.get("/pub/s/{sid}/clash", response_class=PlainTextResponse)
def pub_clash(sid: str, token: str = "", template: str = ""):
    require_resource_token(token, "source", sid)
    issues: List[dict] = []
    src = _source_or_404(sid)
    nodes = _checked_source_proxies(src, issues)
    if src.get("kind") == "v2ray_text":
        doc = build_clashplay_yaml(nodes, rate_limit_mbps=_safe_int(src.get("rate_limit_mbps"), 0))
        y = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    else:
        y = _resolve_to_clash_yaml(src, template=template, issues=issues)
    return _conversion_response(y if y.endswith("\n") else y + "\n", issues)


@app.get("/pub/s/{sid}/singbox")
def pub_singbox(sid: str, token: str = "", mode: str = ""):
    require_resource_token(token, "source", sid)
    issues: List[dict] = []
    nodes = _checked_source_proxies(_source_or_404(sid), issues)
    return _singbox_response(nodes, issues, mode)


@app.get("/p/{pid}/clash", response_class=PlainTextResponse)
def profile_clash(pid: str, _=Depends(require_admin_auth)):
    return _profile_response(_profile_or_404(pid), "clash", [])


@app.get("/p/{pid}/v2ray", response_class=PlainTextResponse)
def profile_v2ray(pid: str, _=Depends(require_admin_auth)):
    return _profile_response(_profile_or_404(pid), "v2ray", [])


@app.get("/p/{pid}/v2ray_raw", response_class=PlainTextResponse)
def profile_v2ray_raw(pid: str, _=Depends(require_admin_auth)):
    return _profile_response(_profile_or_404(pid), "v2ray_raw", [])


@app.get("/p/{pid}/singbox", response_class=PlainTextResponse)
def profile_singbox(pid: str, mode: str = "", _=Depends(require_admin_auth)):
    return _profile_response(_profile_or_404(pid), "singbox", [], mode)


@app.get("/pub/p/{pid}/{fmt}", response_class=PlainTextResponse)
def pub_profile(pid: str, fmt: str, token: str = "", mode: str = ""):
    require_resource_token(token, "profile", pid)
    if fmt not in ("clash", "v2ray", "v2ray_raw", "singbox"):
        raise HTTPException(status_code=404, detail="Unsupported profile output")
    return _profile_response(_profile_or_404(pid), fmt, [], mode)
