import base64
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
from urllib.parse import urlparse

import requests
import yaml
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from converter import (
    build_clashplay_yaml,
    clash_yaml_to_v2ray_uris,
    split_v2ray_text,
    uris_to_v2ray_subscription_base64,
    v2ray_uris_to_clash_proxies,
)
from storage import delete_source, get_source, list_sources, load_json, save_json, upsert_source

app = FastAPI(title="SubConvert Manager")
logger = logging.getLogger(__name__)
APP_DIR = os.path.dirname(__file__)
CONFIG_ENV_FILE = os.path.join(APP_DIR, "config.env")
DEFAULT_BASIC_USER = "admin"
DEFAULT_BASIC_PASS = "change_me_please"


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
        if diff < 24 * 3600:
            hours = max(1, diff // 3600)
            return f"{hours} 小时前"
        return dt.strftime("%m-%d")
    except (TypeError, ValueError, OSError):
        return "-"


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

SESSION_SECRET = (os.environ.get("SESSION_SECRET") or "").strip() or "change_me_please_session_secret"
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

    if request.method in {"GET", "HEAD"}:
        target = _with_url_prefix(path)
        query = request.url.query
        if query:
            target = f"{target}?{query}"
        return RedirectResponse(url=target, status_code=307)

    return _render_http_error(request, 404, "目标资源不存在，可能已被删除或 URL 输入错误。")

_FETCH_CACHE: Dict[str, Tuple[float, str]] = {}
_FETCH_CACHE_LOCK = threading.Lock()
_FETCH_CACHE_TTL = max(0.0, _safe_float(os.environ.get("FETCH_CACHE_TTL", "5"), 5.0))
_FETCH_CACHE_MAX = _clamp(_safe_int(os.environ.get("FETCH_CACHE_MAX", "256"), 256), 16, 4096)
_LOGIN_FAIL_STATE: Dict[str, Tuple[int, float]] = {}
_LOGIN_FAIL_LOCK = threading.Lock()


def _prune_fetch_cache(now: Optional[float] = None) -> None:
    ts = time.monotonic() if now is None else now

    expired = [k for k, (exp, _) in _FETCH_CACHE.items() if exp <= ts]
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


def _fetch_text(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL")

    now = time.monotonic()
    with _FETCH_CACHE_LOCK:
        _prune_fetch_cache(now)
        cached = _FETCH_CACHE.get(url)
        if cached and cached[0] > now:
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
                    _FETCH_CACHE[url] = (time.monotonic() + _FETCH_CACHE_TTL, text)
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


@app.get("/", response_class=HTMLResponse)
def home(request: Request, _=Depends(require_admin_auth)):
    sources = list_sources(_load_db())
    sources = sorted(sources, key=lambda s: _safe_int((s or {}).get("updated_at"), 0), reverse=True)
    return templates.TemplateResponse(
        "home.html",
        _template_context(
            request,
            sources=sources,
            sub_token=SUB_TOKEN,
            url_suffix=URL_SUFFIX,
            suffix_enabled=bool(URL_SUFFIX),
            security_warn=(BASIC_PASS == DEFAULT_BASIC_PASS) or (not SUB_TOKEN) or (not URL_SUFFIX),
            token_enabled=bool(SUB_TOKEN),
        ),
    )


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
    uris = clash_yaml_to_v2ray_uris(doc)
    if not uris:
        raise HTTPException(status_code=422, detail="未解析到可转换节点")

    raw = "\n".join(uris) + "\n"
    b64 = uris_to_v2ray_subscription_base64(uris)
    output = b64 if out == "base64" else raw
    return templates.TemplateResponse(
        "result.html",
        _template_context(request, title="Clash -> V2Ray", source=source, count=len(uris), output=output),
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
    proxies = v2ray_uris_to_clash_proxies(uris)
    if not proxies:
        raise HTTPException(status_code=422, detail="未解析到可转换节点")

    doc = build_clashplay_yaml(proxies, rate_limit_mbps=rate_limit)

    y = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    return templates.TemplateResponse(
        "result.html",
        _template_context(request, title="V2Ray -> Clash", source="文本输入", count=len(proxies), output=y),
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

    if kind not in {"clash_url", "v2ray_text", "clash_yaml"}:
        raise HTTPException(status_code=400, detail="Invalid source type")

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
        },
    )
    _save_db(db)
    return RedirectResponse(url=_with_url_prefix("/?toast=保存成功"), status_code=303)


@app.post("/sources/{sid}/delete")
def source_delete(sid: str, _=Depends(require_admin_auth)):
    sid = _normalize_sid(sid)
    db = _load_db()
    delete_source(db, sid)
    _save_db(db)
    return RedirectResponse(url=_with_url_prefix("/?toast=删除成功"), status_code=303)


def _resolve_to_uris(src: dict) -> List[str]:
    kind = (src or {}).get("kind")
    value = (src or {}).get("value") or ""

    if kind == "clash_url":
        text = _fetch_text(str(value))
        doc = _parse_clash_yaml_text(text)
        return clash_yaml_to_v2ray_uris(doc)

    if kind == "clash_yaml":
        doc = _parse_clash_yaml_text(str(value))
        return clash_yaml_to_v2ray_uris(doc)

    if kind == "v2ray_text":
        return split_v2ray_text(str(value))

    return []


def _resolve_to_clash_yaml(src: dict, template: str = "") -> str:
    kind = (src or {}).get("kind")
    value = (src or {}).get("value") or ""
    _normalize_clash_template(template)

    if kind in ("clash_url", "clash_yaml"):
        if kind == "clash_url":
            return _fetch_text(str(value))
        return str(value)

    uris = split_v2ray_text(str(value))
    proxies = v2ray_uris_to_clash_proxies(uris)
    if not proxies:
        raise HTTPException(status_code=422, detail="No usable node")
    doc = build_clashplay_yaml(proxies, rate_limit_mbps=_safe_int((src or {}).get("rate_limit_mbps"), 0))
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def _source_or_404(sid: str) -> dict:
    sid = _normalize_sid(sid)
    src = get_source(_load_db(), sid)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    return src


@app.get("/s/{sid}/v2ray", response_class=PlainTextResponse)
def sub_v2ray_b64(sid: str, _=Depends(require_admin_auth)):
    uris = _resolve_to_uris(_source_or_404(sid))
    if not uris:
        raise HTTPException(status_code=422, detail="No usable node")
    return uris_to_v2ray_subscription_base64(uris)


@app.get("/s/{sid}/v2ray_raw", response_class=PlainTextResponse)
def sub_v2ray_raw(sid: str, _=Depends(require_admin_auth)):
    uris = _resolve_to_uris(_source_or_404(sid))
    if not uris:
        raise HTTPException(status_code=422, detail="No usable node")
    return "\n".join(uris) + "\n"


@app.get("/s/{sid}/clash", response_class=PlainTextResponse)
def sub_clash(sid: str, template: str = "", _=Depends(require_admin_auth)):
    y = _resolve_to_clash_yaml(_source_or_404(sid), template=template)
    return y if y.endswith("\n") else y + "\n"


@app.get("/pub/s/{sid}/v2ray", response_class=PlainTextResponse)
def pub_v2ray_b64(sid: str, token: str = ""):
    require_sub_token(token)
    uris = _resolve_to_uris(_source_or_404(sid))
    if not uris:
        raise HTTPException(status_code=422, detail="No usable node")
    return uris_to_v2ray_subscription_base64(uris)


@app.get("/pub/s/{sid}/v2ray_raw", response_class=PlainTextResponse)
def pub_v2ray_raw(sid: str, token: str = ""):
    require_sub_token(token)
    uris = _resolve_to_uris(_source_or_404(sid))
    if not uris:
        raise HTTPException(status_code=422, detail="No usable node")
    return "\n".join(uris) + "\n"


@app.get("/pub/s/{sid}/clash", response_class=PlainTextResponse)
def pub_clash(sid: str, token: str = "", template: str = ""):
    require_sub_token(token)
    y = _resolve_to_clash_yaml(_source_or_404(sid), template=template)
    return y if y.endswith("\n") else y + "\n"
