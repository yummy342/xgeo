"""可观测看板：GEO 是周期性工作，关键信息是「这一期相对上一期变了什么」。

  python3 scripts/geo.py ui            # 起服务并打开浏览器

服务本身只用标准库 http.server，但顶层 import geolib 需要第三方依赖
（requests / beautifulsoup4 / lxml），缺失时会给出安装提示。
前端是 frontend/ 下的 Svelte 工程，构建产物在 scripts/ui_dist/，数据走 /api，
工单状态可以直接在界面上改（写回 tasks.json）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import threading
import time
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests

try:
    import geolib as G
except ModuleNotFoundError as e:
    raise SystemExit(f"缺少依赖：{e.name}。请先 pip3 install requests beautifulsoup4 lxml") from e
import jobs as J
import tasks as T

# 前端构建产物（frontend/ 下的 Svelte 工程，Vite 输出到这里）。
# 缺失时 run() 会给出构建提示——服务本身照常起，只有页面打不开。
UI_DIST = Path(__file__).resolve().parent / "ui_dist"


# ---------------------------------------------------------------- 数据聚合

def list_projects() -> list[dict]:
    out = []
    if not G.WORK.exists():
        return out
    for d in sorted(G.WORK.iterdir()):
        cfg_path = d / "geo.json"
        if not cfg_path.exists():
            continue
        cfg = G.read_json(cfg_path, {})
        audit = G.read_json(d / "audit.json", {})
        td = G.read_json(d / "tasks.json", {})
        s = td.get("summary", {})
        out.append({
            "slug": d.name,
            "name": cfg.get("brand", {}).get("name", d.name),
            "site": cfg.get("brand", {}).get("site", ""),
            "market": cfg.get("market", "cn"),
            "avg_score": audit.get("avg_score"),
            "pages": audit.get("page_count"),
            "tasks_total": s.get("total", 0),
            "tasks_done": s.get("by_status", {}).get("done", 0),
            "p0_open": sum(1 for t in td.get("tasks", [])
                           if t["priority"] == "P0" and t["status"] != "done"),
        })
    return out


def project(slug: str) -> dict:
    pdir = G.project_dir(slug)
    cfg = G.load_config(slug)
    audit = G.read_json(pdir / "audit.json", {})
    td = G.read_json(pdir / "tasks.json", {"tasks": [], "summary": {}})

    verify_hist = []
    vdir = pdir / "verify"
    import verify as V
    for f in sorted(vdir.glob("*.json"), key=V.report_key) if vdir.exists() else []:
        v = G.read_json(f, {})
        rs = v.get("results", [])
        verify_hist.append({
            # date 只到天，同一天验收两次就重复了。前端拿它当 each 的 key，
            # 重复键会让整个视图崩掉，所以另给一个逐文件唯一的键。
            "key": f.stem,
            "date": (v.get("verified_at") or f.stem)[:10],
            "pass": sum(1 for r in rs if r["verdict"] == "通过"),
            "fail": sum(1 for r in rs if r["verdict"] == "未达标"),
            "manual": sum(1 for r in rs if r["verdict"] == "待人工"),
            "avg_score": v.get("audit_avg_score"),
        })

    deliveries = sorted((d.name for d in (pdir / "delivery").iterdir() if d.is_dir()),
                        reverse=True) if (pdir / "delivery").exists() else []

    lint = G.read_json(pdir / "assets" / "drafts" / "_lint.json", None)

    # 成稿发布状态：content/ 里的每篇成稿 ↔ publish.json 的成功记录。
    # 行动计划页的「成稿发布」卡和问题库的「已发布」标记都吃这份数据。
    content_pub = []
    cdir = pdir / "content"
    if cdir.exists():
        import re as _re
        pub_by_path: dict[str, list] = {}
        for r in G.read_json(pdir / "publish.json", []) or []:
            if r.get("ok"):
                pub_by_path.setdefault(r.get("path", ""), []).append(
                    {"platform": r.get("platform"), "platform_name": r.get("platform_name"),
                     "url": r.get("url", ""), "at": r.get("at", ""),
                     # 旧记录没有 state：那时不分草稿与发布，空值让前端按老办法显示
                     "state": r.get("state", "")})
        for f in sorted(cdir.glob("*.md")):
            if f.name == "facts.md":
                continue
            head = f.read_text("utf-8", "replace")[:800]
            m = _re.search(r"(?m)^#\s*(.+)$", head)
            content_pub.append({
                "path": f.name,
                "title": (m.group(1).strip() if m else f.name)[:80],
                "qids": _re.findall(r"\bq\d{3}\b", head),
                "published": pub_by_path.get(f"content/{f.name}", []),
            })

    return {
        "slug": slug,
        "brand": cfg.get("brand", {}),
        "market": cfg.get("market", "cn"),
        "audit": {"avg_score": audit.get("avg_score"), "page_count": audit.get("page_count"),
                  "grade_distribution": audit.get("grade_distribution", {}),
                  "language_coverage": audit.get("language_coverage", {}),
                  "site": audit.get("site", {}), "site_issues": audit.get("site_issues", []),
                  "layers": audit.get("layers", []),
                  "block_gap": audit.get("block_gap", []),
                  "pages": sorted(audit.get("pages", []), key=lambda p: p["score"])[:40]},
        "tasks": td.get("tasks", []),
        "verify_history": verify_hist,
        "deliveries": deliveries,
        "lint": {"total": (lint or {}).get("total_issues", 0), "high": (lint or {}).get("high", 0)},
        "content_pub": content_pub,
        "blueprint": G.read_json(pdir / "blueprint.json", None),
        "distribution": G.read_json(pdir / "distribution.json", {}),
        "question_count": len(cfg.get("questions", [])),
        "deliverables_files": sorted(f.name for f in (pdir / "deliverables").glob("*.html"))
                              if (pdir / "deliverables").exists() else [],
        "analytics": _analytics(slug),
        "facts_struct": _facts_struct(slug),
    }


def _facts_struct(slug: str):
    try:
        import generate
        f = generate.parse_facts(slug)
        f.pop("raw", None)
        return f
    except Exception:  # noqa: BLE001
        return {}


def workbench(slug: str, qid: str) -> dict:
    """内容工作台：定位某个问题现有的内容/草稿/大纲文件。"""
    pdir = G.project_dir(slug)
    cfg = G.load_config(slug)
    q = next((x for x in cfg.get("questions", []) if x.get("id") == qid), None)
    sources = []
    cdir = pdir / "content"
    if cdir.exists():
        for f in sorted(cdir.glob("*.md")):
            if qid and qid in f.read_text("utf-8", "replace")[:800]:
                sources.append({"kind": "content", "path": f.name})
    for kind, sub in (("draft", "drafts"), ("outline", "outlines")):
        f = pdir / "assets" / sub / f"{qid}.md"
        if f.exists():
            sources.append({"kind": kind, "path": f"{sub}/{qid}.md"})
    return {"question": q, "sources": sources}


def _analytics(slug: str):
    try:
        import analytics
        return analytics.build(slug)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- HTTP

def asset_tree(slug: str) -> list[dict]:
    """资产目录，供界面预览。只列文本类文件。"""
    adir = G.project_dir(slug) / "assets"
    out = []
    if not adir.exists():
        return out
    for f in sorted(adir.rglob("*")):
        if f.is_file() and f.suffix in (".txt", ".json", ".html", ".md"):
            rel = f.relative_to(adir).as_posix()
            out.append({"path": rel, "size": f.stat().st_size,
                        "group": rel.split("/")[0] if "/" in rel else "根目录"})
    return out


def read_asset(slug: str, rel: str) -> dict:
    base = (G.project_dir(slug) / "assets").resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise PermissionError(rel) from None
    if not target.is_file():
        raise FileNotFoundError(rel)
    return {"path": rel, "text": target.read_text("utf-8", "replace")}


def write_env(updates: dict[str, str]):
    """更新项目根目录 .env：值为空表示删除该行。同步进当前进程环境，让界面立即生效；
    任务子进程每次启动都重读 .env，天然生效。"""
    path = G.ROOT / ".env"
    lines = path.read_text("utf-8").splitlines() if path.exists() else []
    for k, v in updates.items():
        pat = re.compile(rf"\s*(export\s+)?{re.escape(k)}\s*=")
        lines = [ln for ln in lines if not pat.match(ln)]
        if v:
            lines.append(f"{k}={v}")
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), "utf-8")
    try:
        path.chmod(0o600)  # 密钥文件不给同机其他用户读
    except OSError:
        pass


def create_project(url: str, name: str, slug: str, market: str, max_pages: int) -> dict:
    import geo as CLI

    class A:  # 复用 CLI 的 init 逻辑，避免两份实现漂移
        pass
    a = A()
    a.url, a.name, a.slug, a.market, a.max_pages = url, name or None, slug or None, market, max_pages
    a.force = False          # 界面永不覆盖已有项目
    return CLI.cmd_init(a)


# ---------------------------------------------------------------- 访问令牌
# 看板默认只绑 127.0.0.1；要暴露到公网（XGEO_HOST=0.0.0.0）必须设令牌。
# 浏览器首次带 ?token= 访问后种 HttpOnly cookie（存摘要不存原文），之后正常访问；
# API 调用也可带 X-Xgeo-Token 头。
#
# 两种令牌：
#   XGEO_TOKEN          全局管理员，不受项目限制
#   XGEO_PROJECT_TOKENS 分项目租户，格式 'tok1:proj-a,proj-b;tok2:proj-c'
# 只设后者时，每个令牌只能碰自己名下的项目——这是多租户下的隔离边界。

AUTH_COOKIE = "xgeo_auth"
LEGACY_COOKIE = "glk_auth"   # 改名前的名字。过渡期一并接受，下个大版本删


def _env(name: str) -> str | None:
    """读环境变量；过渡期同时认旧名（XGEO_X ← GEOLOOK_X）。

    改名不该让已经部署好的实例升级后起不来——.env 里写的是旧名，
    service.sh 导出的也是旧名。下个大版本去掉这条回退。"""
    val = os.environ.get(name)
    if val or not name.startswith("XGEO_"):
        return val
    return os.environ.get("GEOLOOK_" + name[len("XGEO_"):])


def _header_token(headers) -> str | None:
    """请求头里的令牌。同样认旧名 X-Geolook-Token，理由见 _env。"""
    return headers.get("X-Xgeo-Token") or headers.get("X-Geolook-Token")


def parse_scoped_tokens(raw: str | None) -> dict[str, set[str]]:
    """'tok1:a,b;tok2:c' → {tok1:{a,b}, tok2:{c}}。缺令牌或缺项目的段整条丢弃。"""
    out: dict[str, set[str]] = {}
    for part in (raw or "").split(";"):
        tok, _, slugs = part.partition(":")
        names = {s.strip() for s in slugs.split(",") if s.strip()}
        tok = tok.strip()
        if tok and names:
            out[tok] = names
    return out


def host_name(value: str | None) -> str:
    """取 Host / Origin 里的主机名：去掉端口与 IPv6 的方括号。

    全文件必须只有这一套解析。`[::1]:8765` 用 `split(":")[0]` 会切出 `"["`，
    于是「Origin 与 Host 同源」恒不相等 —— 走 IPv6 字面量访问的实例登录永远 403，
    报的还是「跨站请求被拒绝」，排查会被引到 CSRF 上去。
    """
    h = (value or "").strip().lower()
    if h.startswith("["):
        return h[1:h.index("]")] if "]" in h else h
    return h.split(":")[0]


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _cookie_value(cookie_header: str | None) -> str | None:
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k in (AUTH_COOKIE, LEGACY_COOKIE) and v:
            return v
    return None


def _cookie_values(cookie_header: str | None) -> list[str]:
    """cookie 里所有候选值，**新名在前**。

    `_cookie_value` 只取第一个命中的名字，而浏览器同 path 下按创建时间升序发——
    从 geolook 改名过来的浏览器里，旧的 `glk_auth`（值多半已失效）排在
    `xgeo_auth` 前面，于是拿一个死值去比。会话档下表现为「登录 POST 回 200 并
    下发新 cookie，但之后每个请求都 401」，界面上完全看不出原因。
    令牌那条路仍走 `_cookie_value`（不动既有行为），会话这条路逐个试。
    """
    named: dict[str, list[str]] = {AUTH_COOKIE: [], LEGACY_COOKIE: []}
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if v and k in named:
            named[k].append(v)
    return named[AUTH_COOKIE] + named[LEGACY_COOKIE]


def _same(a: str, b: str) -> bool:
    """定长比较。先编码成字节——hmac.compare_digest 收到含非 ASCII 的 str 会直接
    抛 TypeError，而候选凭证来自 URL 和请求头，谁都能塞一个中文 token 进来。"""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _match_token(token: str | None, scoped: dict[str, set[str]],
                 cookie_header: str | None,
                 query_token: str | None = None,
                 header_token: str | None = None) -> str | None:
    """凭证 → 命中的令牌原文；都没命中返回 None。

    query 参数和请求头带的是令牌原文，cookie 里存的是摘要。
    纯函数便于测试。"""
    creds = [c for c in (query_token, header_token) if c]
    digest = _cookie_value(cookie_header)
    for tok in ([token] if token else []) + list(scoped):
        for cand in creds:
            if _same(cand, tok):
                return tok
        if digest and _same(digest, _token_digest(tok)):
            return tok
    return None


def auth_ok(token: str | None, scoped: dict[str, set[str]],
            cookie_header: str | None,
            query_token: str | None = None, header_token: str | None = None) -> bool:
    """未配置任何令牌时全放行；否则必须有凭证命中。"""
    if not token and not scoped:
        return True
    return _match_token(token, scoped, cookie_header, query_token, header_token) is not None


def scope_of(token: str | None, scoped: dict[str, set[str]],
             cookie_header: str | None,
             query_token: str | None = None, header_token: str | None = None) -> set[str] | None:
    """命中的令牌能访问哪些项目。None = 不受限（管理员）；空集合 = 未命中。"""
    hit = _match_token(token, scoped, cookie_header, query_token, header_token)
    if hit is None:
        return set()
    return None if hit == token else scoped[hit]


def config_shape_error(body: dict) -> str | None:
    """geo.json 的结构校验。

    save_config 只备份不校验，一次畸形写就能让看板全线崩掉：
    list_projects() 走 cfg.get("brand", {}).get("name", ...)，brand 被写成
    字符串就抛 AttributeError，/api/projects 整体 500——所有项目的列表都打不开。
    """
    if not isinstance(body, dict) or not body:
        return "请求体必须是对象"
    brand = body.get("brand")
    if brand is not None:
        if not isinstance(brand, dict):
            return "brand 必须是对象"
        if brand.get("name") is not None and not isinstance(brand["name"], str):
            return "brand.name 必须是字符串"
    for k in ("questions", "competitors"):
        v = body.get(k)
        if v is not None and not isinstance(v, list):
            return f"{k} 必须是数组"
    if body.get("market") is not None and not isinstance(body["market"], str):
        return "market 必须是字符串"
    return None


# 项目标识出现在路径里的路由前缀。集中列在这里而不是散在各个分支里——
# 授权漏检一次就是跨租户读数据，靠人逐个分支去记得加检查迟早会漏。
SLUG_PREFIXES = (
    "/api/p/", "/api/config/", "/api/facts/", "/api/assets/", "/api/asset/",
    "/api/workbench/", "/api/samples/", "/api/sample/", "/api/collect/",
    "/api/factcheck/", "/api/expand/", "/api/publish/", "/api/publishcfg/",
    "/api/content/", "/api/distribution/", "/api/files/", "/files/",
)


def path_slug(path: str) -> str | None:
    """从已解码的 URL 路径里取项目标识；非项目级路由返回 None。"""
    pre = "/api/collect/queue/"  # 收集队列的 slug 在第一段之后，单独处理
    if path.startswith(pre):
        return path[len(pre):].split("/")[0]
    for pre in SLUG_PREFIXES:
        if path.startswith(pre):
            return path[len(pre):].split("/")[0]
    return None


# ---------------------------------------------------------------- 账号登录（可选档）
# 与令牌档并存，不是替代：令牌那三条路（?token= 302 / X-Xgeo-Token 头 / 摘要 cookie）
# 一条都不动。工作台接 freemodel 的账号体系 —— 用户填自己的 FreeModel API Key，
# 服务端拿它调一次 `GET {AUTH_BASE}/me` 换出邮箱，再对允许名单。名单在 .env，
# 界面改不了（/api/keys 的白名单不含 XGEO_*，避免远端账号给自己提权）。
#
# 为什么凭据是 API Key 而不是邮箱密码：fm-auth 的 /login 在验密码**之前**强制校验
# Turnstile（服务端代调过不去），而在自家看板里接收用户的明文密码比接收 API Key 更糟。
#
# 会话在进程内（SESSIONS）：换来的好处是登出即时生效、零凭据落盘；代价是重启即掉线，
# 这条要写进 README。**不做「认证服务不可达就放行」** —— 那是永久后门。


def parse_accounts(raw: str | None) -> dict[str, dict]:
    """`a@b.com:*;c@d.com:proj-a,proj-b` → {邮箱: {admin, projects}}。

    `*` = 管理员（不受项目限制）；否则是租户，只能碰列出的项目。格式对齐
    parse_scoped_tokens。**裸邮箱（没有 `:`）整条丢弃** —— 允许名单是安全边界，
    写错的条目宁可当没写（fail closed），也不能默认给管理员。
    """
    out: dict[str, dict] = {}
    for part in (raw or "").split(";"):
        email, sep, scope = part.partition(":")
        email = email.strip().lower()
        if not email or not sep:
            continue
        # 项目名按小写归一：项目标识就是目录名，而 geolib.SLUG_OK 只允许小写。
        # 写成 `Proj-A` 今天的结果是「登进来了但什么都看不到」且没有任何报错。
        names = {s.strip().lower() for s in scope.split(",") if s.strip()}
        if "*" in names:
            out[email] = {"admin": True, "projects": set()}
        elif names:
            out[email] = {"admin": False, "projects": names}
    return out


def accounts() -> dict[str, dict]:
    """每次现读 —— 测试要能改环境变量，别在 import 时定死。

    **名单只能靠重启改**（它在进程环境里），而重启会清空 SESSIONS，所以
    「改了名单旧的会话还活着」这件事不会发生 —— 会话里存的那份 admin/projects
    快照因此不需要在每个请求上回查名单。
    """
    return parse_accounts(_env("XGEO_ACCOUNTS"))


def accounts_enabled() -> bool:
    return bool(accounts())


def _auth_base() -> str:
    return (_env("XGEO_AUTH_BASE") or "https://freemodel.online/api/auth").rstrip("/")


# /me 的响应形状是从 freemodel.online 的公开静态文件 console/js/auth.js 上读来的
# （它自己也调这条：`data.code === 200 && data.data.api_key`），线上实测
# `?token=` 是对的、`?key=` 报 Missing token。**但那个文件只用 api_key 字段，
# 没有「响应里有 email」的直接证据** —— 服务端代码不在本仓库、也不能去线上捞。
# 所以邮箱字段名按几种可能的形状都试一遍，全落空就明确报「没拿到邮箱」，
# 而不是含糊地回一句「不在允许名单里」（那会把字段改名说成权限问题）。
_EMAIL_KEYS = ("email", "user_email", "mail")


def email_from_me(payload) -> str:
    """从 /me 响应里取邮箱；取不到返回空串。"""
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    for src in (data, payload):
        for k in _EMAIL_KEYS + ("user_name",):     # user_name 兜底：按邮箱注册时它就是邮箱
            v = src.get(k)
            if isinstance(v, str) and "@" in v:
                return v.strip().lower()
    return ""


# /me 的响应体上限。上游是运维配的地址，这个数字压的是「上游被换掉/被串」
# 时的放大面：不带上限就是让对端决定我们读多少内存。
MAX_ME_BYTES = 64 * 1024


def _session_ttl() -> int:
    """会话有效期。**下限 60 秒** —— 写 0 或负数会让登录「成功」又立刻掉线，
    界面上没有任何错误提示，运维会去查网络。"""
    try:
        return max(60, int(_env("XGEO_SESSION_TTL") or 7 * 24 * 3600))
    except ValueError:
        return 7 * 24 * 3600


SESSIONS: dict[str, dict] = {}     # cookie 摘要 → {email, admin, projects, exp}
LOGIN_HITS: dict[str, list] = {}   # 客户端 IP → 尝试时间戳（进程内限流）


def session_new(email: str, acct: dict) -> str:
    """建会话，返回会话 id；cookie 里只放它的 sha256 摘要（沿用令牌那套）。"""
    now = time.time()
    for k, v in list(SESSIONS.items()):
        if v.get("exp", 0) < now:
            SESSIONS.pop(k, None)
    sid = secrets.token_urlsafe(32)
    SESSIONS[_token_digest(sid)] = {"email": email, "admin": bool(acct.get("admin")),
                                    "projects": set(acct.get("projects") or ()),
                                    "exp": now + _session_ttl()}
    return sid


def session_get(cookie_header: str | None) -> dict | None:
    for digest in _cookie_values(cookie_header):
        s = SESSIONS.get(digest)
        if s is None:
            continue
        if s.get("exp", 0) < time.time():
            SESSIONS.pop(digest, None)
            continue
        return s
    return None


def session_drop(cookie_header: str | None) -> bool:
    """删掉 cookie 里**所有**命中的会话。返回是否真删到了东西。"""
    hit = False
    for digest in _cookie_values(cookie_header):
        hit = bool(SESSIONS.pop(digest, None)) or hit
    return hit


def session_cookie(sid: str, secure: bool, max_age: int | None = None) -> str:
    """会话 cookie。**沿用 AUTH_COOKIE 这个名字** —— 值是另一个秘密的摘要，
    与令牌 cookie 靠「在不在 SESSIONS 里」区分，`_cookie_value` 一行不用改。"""
    age = _session_ttl() if max_age is None else max_age
    c = (f"{AUTH_COOKIE}={_token_digest(sid)}; HttpOnly; SameSite=Strict; "
         f"Path=/; Max-Age={age}")
    return c + "; Secure" if secure else c


def login_allowed(ip: str, limit: int = 10, window: int = 300) -> bool:
    """进程内限流。凭据是 48 位 hex 不可猜，这里挡的是「拿别人泄露的 key 试」这类。"""
    now = time.time()
    hits = [t for t in LOGIN_HITS.get(ip, []) if now - t < window]
    if hits:
        LOGIN_HITS[ip] = hits
    else:
        # 空桶不留键：这是进程级全局，只增不删会一直长（原实现连空列表都建键）
        LOGIN_HITS.pop(ip, None)
    if len(LOGIN_HITS) > 4096:
        # 兜底清扫：只在「对端不是反代」时才可能攒出这么多键，顺手收掉整桶过期的
        for k, v in list(LOGIN_HITS.items()):
            if not [t for t in v if now - t < window]:
                LOGIN_HITS.pop(k, None)
    return len(hits) < limit


def login_note(ip: str) -> None:
    LOGIN_HITS.setdefault(ip, []).append(time.time())


def _login_html(err: str = "") -> str:
    """登录页。**凭据走 POST body，不进 URL**。

    老表单把令牌拼进 `?token=`（那条路保留在下面的折叠里，README 也写着）；
    但账号档的凭据是长期 API Key，拼进 URL 就会留在 nginx access log 里 ——
    等于把一份可复用的钥匙抄进了日志。
    """
    e = (err or "").replace("&", "&amp;").replace("<", "&lt;")
    return f"""<!doctype html><meta charset="utf-8"><title>XGEO</title>
<body style="background:#131622;color:#e8eaf2;font-family:system-ui;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center;max-width:320px">
<div style="font-size:20px;margin-bottom:14px">X<span style="color:#9184d9">GEO</span></div>
<input id="k" type="password" placeholder="FreeModel API Key（sk-fm-…）" autofocus
style="background:#1b1e2e;border:1px solid #3a3f55;border-radius:8px;color:#e8eaf2;
padding:10px 14px;font-size:14px;width:100%;box-sizing:border-box">
<button id="go" onclick="xgLogin()" style="background:#9184d9;border:0;border-radius:8px;
color:#101223;padding:10px 18px;font-size:14px;margin-top:8px;width:100%;cursor:pointer">
进入</button>
<div id="e" style="color:#e08a8a;font-size:12px;margin-top:8px;min-height:16px">{e}</div>
<details style="margin-top:14px;text-align:left">
<summary style="cursor:pointer;font-size:12px;color:#8b90a5">用访问令牌登录</summary>
<div style="display:flex;gap:8px;margin-top:8px">
<input id="t" type="password" placeholder="访问令牌 / Access token"
style="background:#1b1e2e;border:1px solid #3a3f55;border-radius:8px;color:#e8eaf2;
padding:10px 14px;font-size:14px;width:100%;box-sizing:border-box">
<button onclick="location='/?token='+encodeURIComponent(document.getElementById('t').value)"
style="background:#2a2f45;border:0;border-radius:8px;color:#e8eaf2;padding:10px 14px;
font-size:14px;cursor:pointer">进入</button>
</div>
</details>
<div style="font-size:11px;color:#6b7085;margin-top:12px;line-height:1.6">
登录用 FreeModel 控制台拿到的 API Key。认证服务不可达时可以改用访问令牌。
</div>
</div>
<script>
async function xgLogin() {{
  const k = document.getElementById('k').value.trim()
  if (!k) return
  const out = document.getElementById('e')
  out.textContent = ''
  try {{
    const r = await fetch('/api/auth/login', {{method: 'POST',
      headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{credential: k}})}})
    const j = await r.json().catch(() => ({{}}))
    if (r.ok) {{ location.href = '/'; return }}
    out.textContent = j.error || ('HTTP ' + r.status)
  }} catch (e) {{
    // 没有这一层，fetch 一 reject（网络断了、服务重启）就是「点了没反应」：
    // 界面不给任何回话，用户只会反复点。
    out.textContent = '连不上本机看板（' + (e && e.message ? e.message : e) + '）'
  }}
}}
</script></body>"""



class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    TOKEN: str | None = None          # run() 注入；None = 没有管理员令牌
    SCOPES: dict[str, set[str]] = {}  # run() 注入；分项目令牌 → 允许的项目
    _scope: set[str] | None = None    # 本请求命中的令牌的授权范围，_auth 里赋值
    _mode: str = ""                   # 本请求是怎么过的鉴权：token / account / open
    _email: str = ""                  # 账号档下当前登录的邮箱
    BIND_PUBLIC: bool = False         # run() 注入；绑的地址不是回环时为 True

    def log_message(self, *a):  # 静音访问日志
        pass

    # ------------------------------------------------------------ 反向代理
    # 判据是**对端是不是回环**：仓库自带的 deploy.sh 把 nginx 和看板放同一台机
    # （proxy_pass http://127.0.0.1:$PORT），只有它会从回环打进来，而且它用
    # `$remote_addr` 覆写 X-Real-IP，客户端伪造不过去。直连时对端不是回环，
    # 这两个头一律不认 —— 否则谁都能换掉自己的限流桶、或骗到一个只该在
    # https 下发的 Secure cookie。
    def _proxied(self) -> bool:
        peer = (self.client_address[0] if self.client_address else "") or ""
        return peer in ("127.0.0.1", "::1", "localhost")

    def _client_ip(self) -> str:
        """限流用的桶键。不是日志意义上的真实 IP，只要「同一来源稳定落在同一个桶」。
        反代下取 X-Real-IP，否则所有用户（含管理员）共用一个桶，任何人连错
        10 次就能把全站登录挡 5 分钟。"""
        if self._proxied():
            real = (self.headers.get("X-Real-IP") or "").strip()
            if real:
                return real
        return (self.client_address[0] if self.client_address else "") or "?"

    def _https(self) -> bool:
        """本次请求是不是 https。**只在确认过反代时才信 `X-Forwarded-Proto`** ——
        否则直连时伪造这个头就能决定 cookie 带不带 Secure；反过来说，运维自写的
        nginx 若忘了设它，https 站点的会话 cookie 就不带 Secure。两条都靠
        `_proxied()` 这个前提框住：本机 http 不加 Secure，否则浏览器会丢掉 cookie。"""
        return self._proxied() and \
            (self.headers.get("X-Forwarded-Proto") or "").lower() == "https"

    def _do_login(self, body: dict) -> tuple[dict, int, str | None]:
        """用 FreeModel API Key 换一次本地会话。返回 (响应体, HTTP 码, 会话 id)。

        会话 id 单独返回而不是塞进响应体：它是凭据，只该进 Set-Cookie。"""
        ip = self._client_ip()
        if not login_allowed(ip):
            return {"ok": False, "error": "尝试过于频繁，稍后再试"}, 429, None
        # 登录 CSRF：Origin 存在且与 Host 不同源时拒掉 —— 否则第三方页面能把
        # 受害者「登进攻击者的账号」，之后他上传的东西全落在攻击者名下。
        org = self.headers.get("Origin")
        if org and (urlparse(org).hostname or "").lower() != host_name(self.headers.get("Host")):
            return {"ok": False, "error": "跨站请求被拒绝"}, 403, None
        if not accounts_enabled():
            return {"ok": False,
                    "error": "这个实例没有配账号登录（XGEO_ACCOUNTS 为空），请用访问令牌"}, 403, None
        cred = body.get("credential")
        if not isinstance(cred, str) or not cred.strip():
            return {"ok": False, "error": "请填 FreeModel API Key"}, 400, None
        login_note(ip)
        # 凭据进上游 query（`?token=`）是 fm-auth 的接口形状，改不了 —— 这条链上
        # 「凭据不进 URL」只对「浏览器 → 本服务」那一段成立，到 fm-auth 的
        # access log 里仍会有它。计划里已承认这是过路凭据，别记成已解决。
        try:
            # 不跟随跳转（上游被换掉时不给它把我们带去别处）、不整包读（对端不该
            # 决定我们读多少内存），超时 8s。
            with requests.get(f"{_auth_base()}/me", params={"token": cred.strip()},
                              timeout=8, allow_redirects=False, stream=True) as r:
                code = r.status_code
                raw = r.raw.read(MAX_ME_BYTES + 1, decode_content=True) if code == 200 else b""
        except Exception as e:  # noqa: BLE001
            # 认证服务不可达 ≠ 凭据错。**不自动放行**（那是永久后门），但要说清
            # 可以改走令牌，别让人以为是 key 错了。
            return {"ok": False, "error": f"认证服务不可达（{type(e).__name__}），"
                                          f"可改用访问令牌登录"}, 503, None
        if code in (401, 403):
            return {"ok": False, "error": "凭据无效（FreeModel API Key 不对或已失效）"}, 401, None
        if code != 200:
            return {"ok": False, "error": f"认证服务返回 {code}，稍后再试"}, 503, None
        if len(raw) > MAX_ME_BYTES:
            return {"ok": False, "error": "认证服务响应过大"}, 502, None
        try:
            payload = json.loads(raw or b"{}") or {}
        except Exception:  # noqa: BLE001
            payload = {}
        email = email_from_me(payload)
        if not email:
            # 与「不在名单里」分开报：字段名一变，含糊的那句会把故障指向权限，
            # 排查的人会去翻允许名单，而问题其实在响应形状上。
            return {"ok": False, "error": "认证服务没返回邮箱（接口字段可能变了）"}, 502, None
        acct = accounts().get(email)
        if not acct:
            # 只有持有效 key 的人才会看到这句，不构成信息泄露
            return {"ok": False, "error": "该 FreeModel 账号不在本工作台的允许名单里"}, 403, None
        sid = session_new(email, acct)
        # 凭据不进日志、不落盘、不进记录：本次用它换到邮箱之后就不再需要它
        return ({"ok": True, "email": email, "admin": bool(acct.get("admin"))}, 200, sid)

    def _host_ok(self) -> bool:
        """默认档（不设令牌）下只接受本机 Host。

        那时浏览器里任何一个网页都能用 evil.com（DNS rebinding 解析到
        127.0.0.1）发起同源请求，读写全部接口——包括 /api/keys 和发布接口。
        校验 Host 是这类本地服务的通用挡法；顺带拒掉带外站 Origin 的请求
        （那是从别的页面打过来的 CSRF，Host 会是 127.0.0.1 拦不住）。

        配了令牌就不再限 Host：鉴权已经挡住未认证请求，而且这时用户可能
        故意绑 0.0.0.0 从别的机器访问。
        """
        if Handler.TOKEN or Handler.SCOPES:
            return True
        if accounts_enabled() and Handler.BIND_PUBLIC:
            # 账号档 + 绑了非本机地址：用户是从别的机器上的浏览器访问的，
            # 限 Host 会把登录页本身 403 掉。
            return True
        # 只配账号档、仍绑本机时不跳过 Host 校验。令牌档跳过它没关系（攻击者
        # 拿不到合法令牌），账号档的威胁模型不同：攻击者**自带**合法凭据，能把
        # 受害者登进自己的账号（之后他上传的东西全落在攻击者名下），而这时唯一
        # 的防线就是「Origin == Host」—— DNS rebinding 恰好能让浏览器同时伪造
        # 两者（它以为自己在跟 evil.com 说话）。下面的本机白名单不影响
        # 127.0.0.1 下打开登录页。
        h = host_name(self.headers.get("Host"))
        if h not in ("127.0.0.1", "localhost", "::1"):
            self._json({"error": "只接受本机访问：Host 不是本机地址"}, 403)
            return False
        org = self.headers.get("Origin")
        # chrome-extension:// 必须放行：采样助手插件的侧栏 POST 回传会带这个源，
        # 它不是「别的网站」。请求已经过了 Host 校验，确实打在本机上。
        if org and not org.startswith("chrome-extension://") \
                and (urlparse(org).hostname or "").lower() not in ("127.0.0.1", "localhost", "::1"):
            self._json({"error": "已拒绝跨站请求"}, 403)
            return False
        return True

    def _auth(self) -> bool:
        """True=放行；False=已自行响应（401 或换 cookie 的 302）。"""
        # 账号档也算「配了东西」：只配 XGEO_ACCOUNTS 不配令牌时（全新自托管实例
        # 正是这形态），少这个条件会让 auth_ok(None, {}, …) 返回 True → 所有人放行、
        # 允许名单形同虚设。
        # 每个请求都从零开始：Handler 实例在 keep-alive 上是复用的，_email 只在
        # 账号分支赋值，不重置就会把上一个请求的身份带到 /api/auth/me 的响应里。
        self._scope, self._mode, self._email = None, "", ""
        if not Handler.TOKEN and not Handler.SCOPES and not accounts_enabled():
            self._mode = "open"
            return True
        u = urlparse(self.path)
        qt = (parse_qs(u.query).get("token") or [None])[0]
        # _auth 在 try 之外调用：这里抛异常就是连接被直接掐断，连 401 都回不去
        if qt and _match_token(Handler.TOKEN, Handler.SCOPES, None, query_token=qt):
            # 令牌换 cookie 后跳回干净地址，别让令牌留在地址栏和访问日志里
            self.send_response(302)
            loc = u.path or "/"
            # 只接受站内绝对路径。`GET /\evil.com?token=…` 的 u.path 就是
            # `/\evil.com`，浏览器按 WHATWG 会把反斜杠归一成 `/` → `//evil.com`
            # → 跳到外站（预存在问题，改到这行顺手收掉；要有效令牌才触发）。
            if not loc.startswith("/") or loc.startswith("//") or loc.startswith("/\\"):
                loc = "/"
            self.send_header("Location", loc)
            self.send_header("Set-Cookie", f"{AUTH_COOKIE}={_token_digest(qt)}; "
                                           "HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        # 括号不能省：auth_ok 在「两个令牌变量都没配」时恒返回 True，
        # 而配了账号档却没配令牌的实例正好落在这个分支上。
        if (Handler.TOKEN or Handler.SCOPES) and auth_ok(
                Handler.TOKEN, Handler.SCOPES, self.headers.get("Cookie"),
                header_token=_header_token(self.headers)):
            self._scope = scope_of(Handler.TOKEN, Handler.SCOPES, self.headers.get("Cookie"),
                                   header_token=_header_token(self.headers))
            self._mode = "token"
            return True
        # 账号会话。顺序在令牌之后：显式带头的 API 客户端意图更明确，
        # 且升级后老的令牌 cookie 继续有效（老用户不会被登出）。
        sess = session_get(self.headers.get("Cookie"))
        if sess:
            self._scope = None if sess["admin"] else set(sess["projects"])
            self._mode = "account"
            self._email = sess["email"]
            return True
        if self.command == "GET":
            self._send(401, _login_html().encode("utf-8"), "text/html; charset=utf-8")
        else:
            # 先读走请求体再回 401：带着未读数据关 socket 的 RST 会把 401 吞掉，
            # 客户端只看到「连接被中止」（见 _drain）。
            self._drain()
            self._json({"error": "未授权：需要 X-Xgeo-Token 头或先在浏览器登录"}, 401)
        return False

    def _deny(self, slug: str | None) -> bool:
        """项目级授权。True = 已响应 403，调用方直接 return。

        slug 为空表示这条路由不归属任何项目（前端产物、/api/projects 等），
        不在这里拦——跨项目的列表泄漏由各路由自己筛。"""
        if self._scope is None or not slug or slug in self._scope:
            return False
        self._json({"error": f"无权访问项目 {slug}"}, 403)
        return True

    def _deny_admin(self, what: str) -> bool:
        """管理员专属接口：分项目令牌一律不给。True = 已响应 403。"""
        if self._scope is None:
            return False
        self._json({"error": f"{what}只有管理员令牌可用"}, 403)
        return True

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8",
              headers: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        # 内容类型由扩展名猜，猜错就等于让浏览器改按 HTML 解析
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200, extra: dict | None = None):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   headers=extra)

    def _static(self, base: Path, rel: str, force_text: bool = False):
        """从 base 目录下取静态文件，解析后必须仍落在 base 内（防目录穿越）。

        force_text：把能被浏览器执行的类型（html/svg/xml）降级成纯文本。
        用于 assets/ 这类**可写**目录——不降级的话，写接口就等于拿到了同源
        脚本执行权（存储型 XSS）。"""
        target = (base / rel).resolve()
        try:
            target.relative_to(base.resolve())
        except ValueError:
            return self._send(403, b"forbidden", "text/plain")
        if not target.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if force_text and ctype not in ("text/plain", "text/markdown", "application/json"):
            ctype = "text/plain"
        if ctype.startswith("text/") or ctype in ("application/json",):
            ctype += "; charset=utf-8"
        return self._send(200, target.read_bytes(), ctype)

    MAX_BODY = 8 * 1024 * 1024   # 请求体上限：接口全在本机，8MB 够贴一篇长文
    # 登录/登出单独设上限：它们**未认证可达**，8MB 的量级足够拿去耗内存与线程
    # （一连接一线程，读满再限流等于没限）。登录体就是 {"credential": "…"}。
    AUTH_MAX_BODY = 4 * 1024


    def _drain(self) -> None:
        """把还没读的请求体读走丢掉。

        **带着未读数据关 socket 会发 RST**，而 RST 会把已经写出去的响应一起丢掉：
        客户端读到的是「连接被中止」而不是那个 400/401/403。Windows 上实测约
        1/3 概率，表现为测试里随机的 `ConnectionAbortedError`、线上表现为
        「服务端明明回话了，客户端却说断连」。所以每条早退路径（没走到读体那一步
        就返回的）都要先 drain 一次。

        超过 MAX_BODY 的不读、直接标记关连接：那种量级宁可断，也不能替对端
        分配内存。chunked 同理（解析它要另写一层）。
        """
        if (self.headers.get("Transfer-Encoding") or "").strip().lower() == "chunked":
            self.close_connection = True
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > Handler.MAX_BODY:
            self.close_connection = True
            return
        if n:
            self.rfile.read(n)

    def _body(self, max_bytes: int | None = None) -> dict:
        if (self.headers.get("Transfer-Encoding") or "").strip().lower() == "chunked":
            # 分块体不读走的话字节留在 socket 里，会被当成下一个请求行解析
            self.close_connection = True
            raise ValueError("不支持 chunked 请求体")   # 分块体不解析，连接已标记要断
        n = int(self.headers.get("Content-Length", 0))
        cap = Handler.MAX_BODY if max_bytes is None else max_bytes
        if n > cap:
            # 不设上限的话，一个声明了超大 Content-Length 的请求就能把内存吃满。
            # 这里先把体读走再报错：带着未读数据关连接会让这个 400 被 RST 吞掉
            # （见 _drain）。超过 MAX_BODY 的它自己会拒读并标记关连接。
            self._drain()
            label = f"{cap // 1024 // 1024}MB" if cap >= 1024 * 1024 else f"{cap // 1024}KB"
            raise ValueError(f"请求体过大：{n} 字节，上限 {label}")
        return json.loads(self.rfile.read(n) or b"{}")

    # ------------------------------------------------------------ GET
    def do_GET(self):
        if not self._host_ok():
            self.close_connection = True
            return
        if not self._auth():
            self.close_connection = True
            return
        u = urlparse(self.path)
        p, q = unquote(u.path), parse_qs(u.query)
        # 项目级授权统一在这里判，各个分支不再各自检查
        if self._deny(path_slug(p)):
            return
        try:
            if p in ("/", "/index.html"):
                return self._send(200, (UI_DIST / "index.html").read_bytes(),
                                  "text/html; charset=utf-8")
            if p == "/api/projects":
                rows = list_projects()
                if self._scope is not None:
                    rows = [r for r in rows if r["slug"] in self._scope]
                return self._json(rows)
            if p == "/api/actions":
                return self._json(J.ACTIONS)
            if p.startswith("/api/p/"):
                return self._json(project(p[len("/api/p/"):]))
            if p.startswith("/api/config/"):
                slug = p[len("/api/config/"):]
                return self._json(G.read_json(G.project_dir(slug) / "geo.json", {}))
            if p.startswith("/api/facts/"):
                slug = p[len("/api/facts/"):]
                f = G.project_dir(slug) / "content" / "facts.md"
                return self._json({"exists": f.exists(),
                                   "text": f.read_text("utf-8") if f.exists() else ""})
            if p.startswith("/api/assets/"):
                return self._json(asset_tree(p[len("/api/assets/"):]))
            if p.startswith("/api/asset/"):
                slug = p[len("/api/asset/"):]
                return self._json(read_asset(slug, q.get("path", [""])[0]))
            if p.startswith("/api/workbench/"):
                slug = p[len("/api/workbench/"):]
                return self._json(workbench(slug, q.get("qid", [""])[0]))
            if p.startswith("/api/samples/"):
                import sample as S
                slug = p[len("/api/samples/"):]
                try:
                    limit = max(1, min(2000, int(q.get("limit", ["300"])[0])))
                except ValueError:
                    limit = 300
                return self._json(S.list_samples(
                    slug, date=q.get("date", [""])[0], platform=q.get("platform", [""])[0],
                    qid=q.get("qid", [""])[0], flag=q.get("flag", [""])[0], limit=limit))
            if p.startswith("/api/sample/"):
                import sample as S
                slug = p[len("/api/sample/"):]
                r = S.get_sample(slug, q.get("key", [""])[0])
                return self._json(r or {"error": "找不到该样本"}, 200 if r else 404)
            if p.startswith("/api/collect/queue/"):
                # 浏览器插件的采样队列：按意图分组挑题 + 需人工采的平台
                import sample as S
                slug = p[len("/api/collect/queue/"):]
                cfg = G.load_config(slug)
                try:
                    limit = max(1, min(200, int(q.get("limit", ["20"])[0])))
                except ValueError:
                    limit = 20
                intent = q.get("intent", [""])[0]
                picked = [g for g in (q.get("groups", [""])[0] or "").split(",") if g.strip()]
                if not picked and intent == "buyer":
                    picked = sorted(S.BUYER_GROUPS)
                allq = cfg.get("questions", [])
                qs = [x for x in allq if not picked or x.get("group") in picked][:limit]
                counts: dict[str, int] = {}
                for x in allq:
                    g2 = x.get("group") or "未分组"
                    counts[g2] = counts.get(g2, 0) + 1
                groups = [{"name": g2, "count": c,
                           "buyer": g2 in S.BUYER_GROUPS} for g2, c in
                          sorted(counts.items(), key=lambda kv: -kv[1])]
                plats = [{"code": c, "label": lb, "market": mk}
                         for c, (lb, mk) in S.MANUAL_ONLY.items()]
                plats += [{"code": c, "label": s2["name"], "market": s2["market"]}
                          for c, s2 in S.PROVIDERS.items() if not S.available(c)]
                return self._json({"slug": slug, "brand": cfg.get("brand", {}).get("name", ""),
                                   "questions": qs, "platforms": plats,
                                   "groups": groups, "selected": picked})
            if p == "/api/keys":
                import sample as S
                if self._deny_admin("密钥配置"):
                    return
                rows = []
                for code, spec in S.PROVIDERS.items():
                    key = os.environ.get(spec["key_env"], "")
                    menv = spec.get("model_env")
                    rows.append({"code": code, "label": spec["name"], "market": spec["market"],
                                 "search": spec.get("search", False), "env": spec["key_env"],
                                 "ok": S.available(code),
                                 "key_tail": key[-4:] if len(key) >= 8 else "",
                                 "model": os.environ.get(menv) or spec.get("model", "") if menv else spec.get("model", ""),
                                 "model_env": menv,
                                 "model_set": bool(menv and os.environ.get(menv)),
                                 "note": spec.get("note", "")})
                for code, (label, mk) in S.MANUAL_ONLY.items():
                    rows.append({"code": code, "label": label, "market": mk,
                                 "search": True, "env": None, "ok": None})
                return self._json(rows)
            if p.startswith("/api/factcheck/"):
                slug = p[len("/api/factcheck/"):]
                return self._json(G.read_json(G.project_dir(slug) / "factcheck.json", []) or [])
            if p.startswith("/api/expand/"):
                slug = p[len("/api/expand/"):]
                return self._json(G.read_json(G.project_dir(slug) / "expand.json", {}) or {})
            if p == "/api/auth/me":
                # 身份三件套：怎么进来的、是谁、是不是管理员。侧栏按 admin 决定
                # 要不要给「只有管理员能用」的入口（engines / settings 都读
                # /api/keys，租户点进去只吃 403）。**这只是体验** —— 真正的判权
                # 在服务端每个路由上，前端隐藏不作为边界。
                # projects 不放这里：要在意的项目清单走 /api/projects，那条已经
                # 按 _scope 过滤过了，两个出口报同一件事只会漂移。
                return self._json({"ok": True, "mode": self._mode or "token",
                                   "email": self._email,
                                   "admin": self._scope is None})

            if p.startswith("/api/publish/"):
                import publish as P
                slug = p[len("/api/publish/"):]
                pubs = []
                for code, spec in P.PUBLISHERS.items():
                    cfg = P._cfg(slug, code)
                    pubs.append({"code": code, "name": spec["name"], "note": spec["note"],
                                 "market": spec.get("market", "general"),
                                 "guide": spec.get("guide") or {},
                                 "env": spec["env"], "missing": P.missing_env(code),
                                 # 通路：api / semi。前端按它分组 —— 半自动渠道的交互是
                                 # 「备好 + 复制 + 打开发布页」，与「勾选后统一提交」不兼容，
                                 # 所以不能跟自动渠道挤在同一个列表里。
                                 "paths": P.paths_of(code), "path": P.resolve_path(code, slug),
                                 "semi": P.semi_spec(code, slug),
                                 "cfg": [{"key": k, "hint": h, "value": cfg.get(k, "")}
                                         for k, h in spec["cfg"]]})
                return self._json({"publishers": pubs, "records": P.records(slug)})
            if p.startswith("/api/content/"):
                slug = p[len("/api/content/"):]
                base = (G.project_dir(slug) / "content").resolve()
                rel = q.get("path", [""])[0]
                if rel:
                    target = (base / rel).resolve()
                    try:
                        target.relative_to(base)
                    except ValueError:
                        return self._json({"error": "非法路径"}, 403)
                    if not target.is_file():
                        return self._json({"error": "文件不存在"}, 404)
                    return self._json({"path": rel, "text": target.read_text("utf-8", "replace")})
                files = sorted(f.name for f in base.glob("*.md")) if base.exists() else []
                return self._json({"files": files})
            if p == "/api/jobs":
                slug = q.get("slug", [None])[0]
                if slug and self._deny(slug):
                    return
                jobs = J.recent(slug)
                if self._scope is not None:
                    # 不带 slug 时 recent() 返回所有项目的任务，按授权范围筛掉别人的
                    jobs = [j for j in jobs if j.get("slug") in self._scope]
                return self._json({"jobs": jobs,
                                   "running": J.running_for(slug) if slug else None})
            if p.startswith("/api/job/"):
                jid = p[len("/api/job/"):]
                if not J.is_valid_id(jid):
                    return self._json({"error": "非法任务标识"}, 400)
                job = J.get(jid)
                if not job:
                    return self._json({"error": "job not found"}, 404)
                if self._deny(job.get("slug")):
                    return
                try:
                    off = int(q.get("offset", ["0"])[0])
                except ValueError:
                    return self._json({"error": "offset 必须是整数"}, 400)
                text, new_off = J.tail(jid, off)
                return self._json({"job": job, "log": text, "offset": new_off})
            if p.startswith("/api/files/"):
                slug = p[len("/api/files/"):]
                pdir = G.project_dir(slug)
                def ls(sub, pat="*"):
                    d = pdir / sub
                    return sorted((x.name for x in d.glob(pat)), reverse=True) if d.exists() else []
                dv = pdir / "deliverables"
                return self._json({
                    "reports": [d for d in ls("reports") if d.startswith("2")],
                    "deliveries": [d for d in ls("delivery") if d.startswith("2")],
                    "samples": ls("samples", "*.md"),
                    "deliverables": sorted(f.name for f in dv.glob("*.html")) if dv.exists() else [],
                    "content": sorted(f.name for f in (pdir / "content").glob("*.md"))
                               if (pdir / "content").exists() else [],
                })
            if p.startswith("/files/"):
                rel = p[len("/files/"):]
                # assets/ 是可写目录，按 HTML 发出去等于给了写接口同源脚本执行权
                return self._static(G.WORK, rel, force_text="/assets/" in rel)
            if p.startswith("/assets/"):
                # 前端构建产物。URL /assets/x.js 对应文件 ui_dist/assets/x.js
                # （Vite 默认把产物放进 assets/，index.html 也按这个路径引用）
                return self._static(UI_DIST, "assets/" + p[len("/assets/"):])
            return self._send(404, b"not found", "text/plain")
        except FileNotFoundError:
            return self._json({"error": "文件不存在"}, 404)
        except PermissionError:
            return self._json({"error": "非法路径"}, 403)
        except SystemExit:
            return self._json({"error": "项目不存在"}, 404)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    # ------------------------------------------------------------ POST
    def do_POST(self):
        # 早退路径也要掐连接：请求体还没读，留着会被当成下一个请求行解析，
        # keep-alive 下表现为同一条连接上的下一个正常请求莫名 400。
        if not self._host_ok():
            # Host/Origin 被拒时它的 403 已经写出去了，但请求体还没读 —— 不读走就关
            # 连接会发 RST，把那个 403 一起吞掉（见 _drain）。
            self._drain()
            self.close_connection = True
            return
        p = unquote(urlparse(self.path).path)
        # 登录/登出必须在 _auth() **之前**：登录本来就发生在还没有凭据的时候。
        if p in ("/api/auth/login", "/api/auth/logout"):
            # 这两个分支**未认证可达**，所以请求体不能有未接住的异常：坏 JSON /
            # chunked / 超大 Content-Length 三种输入都会让 ValueError 穿出
            # do_POST，socketserver 只打 traceback 再掐连接、一个字节的响应都不发
            # （登录页的 fetch 直接 reject，表现成「点了没反应」）。其它路由都在
            # try 里按同一口径回 JSON，这里补齐；体量按 4KB 卡死（登录体就一句）。
            try:
                body = self._body(Handler.AUTH_MAX_BODY)
            except (ValueError, RuntimeError):
                self.close_connection = True
                return self._json({"error": "请求体不合法（要 JSON 对象，且不超过 4KB）"}, 400)
            if not isinstance(body, dict):
                return self._json({"error": "请求体要 JSON 对象"}, 400)
            if p == "/api/auth/logout":
                # 没开账号档就不处理：它清的是 AUTH_COOKIE，而令牌档的凭据正是
                # 同一个 cookie 名 —— 无条件下发清除就等于给令牌档加了一个
                # 「任何人一发就把别人登出」的入口。顺带与登录同样校 Origin。
                if not accounts_enabled():
                    return self._json({"error": "这个实例没有账号登录"}, 404)
                org = self.headers.get("Origin")
                if org and (urlparse(org).hostname or "").lower() != host_name(self.headers.get("Host")):
                    return self._json({"error": "跨站请求被拒绝"}, 403)
                session_drop(self.headers.get("Cookie"))
                # Max-Age=0 让浏览器立刻丢掉它；路径/属性要与下发时一致，否则删不掉
                self._json({"ok": True}, 200,
                           extra={"Set-Cookie": session_cookie("x", self._https(), max_age=0)})
                return
            res, code, sid = self._do_login(body)
            self._json(res, code,
                       extra={"Set-Cookie": session_cookie(sid, self._https())} if sid else None)
            return
        if not self._auth():
            self._drain()
            self.close_connection = True
            return
        p = unquote(urlparse(self.path).path)
        if self._deny(path_slug(p)):
            self._drain()
            self.close_connection = True
            return
        try:
            body = self._body()

            if p == "/api/task":
                missing = [k for k in ("slug", "id", "status") if k not in body]
                if missing:
                    return self._json({"error": f"缺参数：{', '.join(missing)}"}, 400)
                if self._deny(body["slug"]):
                    return
                valid = ("todo", "doing", "done", "blocked", "wontfix")  # 与 tasks.py 汇总口径一致
                if body["status"] not in valid:
                    return self._json({"ok": False, "error": f"非法状态：{body['status']}",
                                       "valid": list(valid)}, 400)
                try:
                    t = T.set_status(body["slug"], body["id"], body["status"], body.get("note", ""))
                except KeyError as e:
                    return self._json({"error": e.args[0] if e.args else str(e)}, 404)
                return self._json({"ok": True, "task": t})

            if p == "/api/init":
                if self._deny_admin("新建项目"):
                    return
                url = (body.get("url") or "").strip()
                if not url:
                    return self._json({"ok": False, "error": "请填写官网地址"}, 400)
                cfg = create_project(url, body.get("name", ""), body.get("slug", ""),
                                     body.get("market", "cn"), int(body.get("max_pages", 25)))
                return self._json({"ok": True, "slug": cfg["slug"]})

            if p == "/api/run":
                slug = body.get("slug")
                if not slug:
                    return self._json({"ok": False, "error": "缺 slug"}, 400)
                if self._deny(slug):
                    return
                job = J.start(slug, body["action"], body.get("params") or {})
                return self._json({"ok": True, "job": job})

            if p.startswith("/api/sample/"):
                import sample as S
                slug = p[len("/api/sample/"):]
                key = body.get("key") or ""
                if not key:
                    return self._json({"ok": False, "error": "缺少 key"}, 400)
                res = S.patch_sample(slug, key, body.get("patch") or {})
                return self._json(res, 200 if res.get("ok") else 400)

            if p.startswith("/api/collect/"):
                # 浏览器插件回传样本。服务只绑 127.0.0.1，来源即本机用户。
                import sample as S
                slug = p[len("/api/collect/"):]
                records = body.get("records")
                if not isinstance(records, list) or not records:
                    return self._json({"ok": False, "error": "records 必须是非空数组"}, 400)
                if len(records) > 200:
                    return self._json({"ok": False, "error": "单次最多 200 条"}, 400)
                # 采样/导入类任务运行中会写同一份当日样本文件，先挡回避免并发写丢行
                jid = J.running_for(slug)
                job = J.get(jid) if jid else None
                if job and job.get("action") in ("sample", "sample-import", "serve", "cycle", "autopilot"):
                    return self._json({"ok": False,
                                       "error": f"任务「{job.get('label') or job.get('action')}」正在运行，"
                                                "会写同一份样本文件——等它结束后再上传"}, 409)
                with G.project_lock(slug):
                    res = S.collect_import(slug, records)
                return self._json(res, 200 if res.get("ok") else 400)

            if p.startswith("/api/job/") and p.endswith("/stop"):
                jid = p[len("/api/job/"):-len("/stop")]
                if not J.is_valid_id(jid):
                    return self._json({"error": "非法任务标识"}, 400)
                job = J.get(jid)
                if job and self._deny(job.get("slug")):
                    return
                return self._json({"ok": J.stop(jid)})

            if p.startswith("/api/config/"):
                slug = p[len("/api/config/"):]
                bad = config_shape_error(body)
                if bad:
                    return self._json({"ok": False, "error": bad}, 400)
                # 读-改-写必须持锁：bootstrap / autopilot 末端也整体写这份
                # geo.json，不持锁就是后写者赢，问题库这类人工投入会静默消失。
                with G.project_lock(slug):
                    cur = G.read_json(G.project_dir(slug) / "geo.json", {})
                    cur.update(body)      # 整体覆盖字段，前端传完整对象
                    G.save_config(slug, cur)
                return self._json({"ok": True})

            if p.startswith("/api/facts/"):
                slug = p[len("/api/facts/"):]
                f = G.project_dir(slug) / "content" / "facts.md"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(body.get("text", ""), "utf-8")
                return self._json({"ok": True})

            if p.startswith("/api/asset/"):
                slug = p[len("/api/asset/"):]
                rel = str(body.get("path") or "")
                if not rel:
                    return self._json({"ok": False, "error": "缺 path"}, 400)
                base = (G.project_dir(slug) / "assets").resolve()
                target = (base / rel).resolve()
                try:
                    target.relative_to(base)
                except ValueError:
                    return self._json({"ok": False, "error": "非法路径"}, 403)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body.get("text", ""), "utf-8")
                return self._json({"ok": True})

            if p == "/api/precheck":
                import analytics
                return self._json(analytics.precheck(body.get("text", "")))

            if p.startswith("/api/factcheck/"):
                slug = p[len("/api/factcheck/"):]
                items = body.get("items")
                if not isinstance(items, list):
                    return self._json({"ok": False, "error": "items 必须是数组"}, 400)
                G.write_json(G.project_dir(slug) / "factcheck.json", items)
                return self._json({"ok": True, "count": len(items)})

            if p.startswith("/api/content/"):
                slug = p[len("/api/content/"):]
                base = (G.project_dir(slug) / "content").resolve()
                rel = (body.get("path") or "").strip()
                # 文件名允许中文（现有成稿即中文名），只挡路径分隔符和隐藏文件；
                # 问题归属靠文件头的 qid 注释识别，不靠文件名
                if ("/" in rel or "\\" in rel or ".." in rel or rel.startswith(".")
                        or not rel.endswith(".md") or len(rel) <= 3):
                    return self._json({"ok": False, "error": "文件名须是 .md，不能包含路径"}, 400)
                base.mkdir(parents=True, exist_ok=True)
                (base / rel).write_text(body.get("text", ""), "utf-8")
                return self._json({"ok": True})

            if p == "/api/keys":
                import publish as P
                import sample as S
                if self._deny_admin("密钥配置"):
                    return
                allowed = set()
                for spec in S.PROVIDERS.values():
                    allowed.add(spec["key_env"])
                    if spec.get("model_env"):
                        allowed.add(spec["model_env"])
                for spec in P.PUBLISHERS.values():
                    allowed.update(spec["env"])
                updates = body.get("updates")
                if not isinstance(updates, dict) or not updates:
                    return self._json({"ok": False, "error": "updates 必须是非空对象"}, 400)
                bad = [k for k in updates if k not in allowed]
                if bad:
                    return self._json({"ok": False,
                                       "error": f"不允许的变量：{', '.join(bad)}"}, 400)
                clean = {k: str(v or "").strip() for k, v in updates.items()}
                if any("\n" in v or "\r" in v for v in clean.values()):
                    return self._json({"ok": False, "error": "值不能包含换行"}, 400)
                write_env(clean)
                return self._json({"ok": True})

            if p.startswith("/api/publishcfg/"):
                import publish as P
                slug = p[len("/api/publishcfg/"):]
                code = body.get("platform")
                if code not in P.PUBLISHERS:
                    return self._json({"ok": False, "error": f"未知渠道 {code}"}, 400)
                keys = {k for k, _ in P.PUBLISHERS[code]["cfg"]}
                with G.project_lock(slug):
                    cfg = G.read_json(G.project_dir(slug) / "geo.json", {})
                    pub = cfg.setdefault("publishing", {})
                    pub[code] = {k: str(v or "").strip() for k, v in (body.get("cfg") or {}).items()
                                 if k in keys}
                    G.save_config(slug, cfg)
                return self._json({"ok": True})

            # 半自动：备好（**不外发**）与回填。必须排在下面那条 /api/publish/<slug> 之前，
            # 否则 slug 会取成 "alpha/prepare"（那条不管后缀，整个尾串都当 slug）。
            # 用 partition 取尾段而不是 endswith：项目 slug 恰好叫 prepare/manual 时
            # `/api/publish/prepare` 没有尾段，endswith 会把它当成 slug="prepare" 的
            # prepare 请求（slug 被切成空串），那次真发布就永远发不出去。
            _pub_rest = p[len("/api/publish/"):] if p.startswith("/api/publish/") else ""
            _pub_slug, _sep, _pub_tail = _pub_rest.partition("/")
            if _pub_slug and _sep and _pub_tail in ("prepare", "manual"):
                import publish as P
                # platform 必须是字符串：body 里塞 dict/list 会让 `code not in PUBLISHERS`
                # 抛 TypeError（不可哈希）→ 500。这里挡成 400。
                plat = body.get("platform") or ""
                if not isinstance(plat, str):
                    return self._json({"ok": False, "error": "platform 要是字符串"}, 400)
                rel = body.get("path") or ""
                if _pub_tail == "prepare":
                    r = P.prepare(_pub_slug, plat, rel, body.get("title") or "",
                                  force=body.get("force"))
                else:
                    # 回填 = 人工发布完成后登记公开链接（或作废待办）。写入不算外发动作。
                    r = P.record_manual(_pub_slug, plat, rel, body.get("id") or "",
                                        url=body.get("url") or "", note=body.get("note") or "",
                                        cancel=bool(body.get("cancel")))
                return self._json(r, 200 if r.get("ok") else 400)

            if p.startswith("/api/publish/"):
                # 发布 = 外发动作：只响应界面上用户的明确点击，服务端绝不自行调用
                import publish as P
                slug = p[len("/api/publish/"):]
                r = P.publish(slug, body.get("platform", ""), body.get("path", ""),
                              body.get("title", ""),
                              publish_now=bool(body.get("published")))
                return self._json(r, 200 if r.get("ok") else 400)

            if p.startswith("/api/distribution/"):
                # 分发打勾：记录某问题的内容已铺到某阵地（人工确认口径，非自动判定）
                slug = p[len("/api/distribution/"):]
                qid, ch = (body.get("qid") or "").strip(), (body.get("channel") or "").strip()
                if not qid or not ch:
                    return self._json({"ok": False, "error": "缺 qid / channel"}, 400)
                path = G.project_dir(slug) / "distribution.json"
                # 读-改-写必须持锁：半自动回填（publish.record_manual）也写这个文件，
                # 两个标签页并发打勾同样会后写覆盖先写。之前这里没锁，会丢掉
                # 「回填时顺带勾上的那一项」——现象是打勾了但刷新后没了。
                with G.project_lock(slug):
                    dist = G.read_json(path, {})
                    if body.get("on"):
                        dist.setdefault(qid, {})[ch] = G.now_iso()
                    else:
                        dist.get(qid, {}).pop(ch, None)
                        if not dist.get(qid):
                            dist.pop(qid, None)
                    # 写也在锁内：光把读-改圈进去只把窗口变窄，另一个写者仍可能在这
                    # 之后读到旧快照再写回，把这一次的改动吃掉。
                    G.write_json(path, dist)
                return self._json({"ok": True, "distribution": dist})

            if p == "/api/questions-add":
                slug = body.get("slug") or ""
                items = body.get("items")
                if not slug or not isinstance(items, list) or not items:
                    return self._json({"ok": False, "error": "缺 slug / items"}, 400)
                if self._deny(slug):
                    return
                # 整个「读 → 算未占用 id → 追加 → 写」都在锁里：不持锁时
                # 两个并发的添加请求会算出同一批 qid，后写者覆盖先写者。
                with G.project_lock(slug):
                    cfg = G.read_json(G.project_dir(slug) / "geo.json", {})
                    qs = cfg.setdefault("questions", [])
                    existing = {q.get("text", "").strip() for q in qs}
                    series = {"cn": 1, "global": 101, "both": 901}
                    used = {int(m.group(1)) for q in qs
                            if (m := re.match(r"q(\d+)$", str(q.get("id", ""))))}
                    added = []
                    for it in items:
                        text = str(it.get("text") or "").strip()
                        mk = it.get("market") if it.get("market") in series else "cn"
                        grp = str(it.get("group") or "场景").strip() or "场景"
                        if not text or text in existing:
                            continue
                        n = series[mk]
                        while n in used:
                            n += 1
                        used.add(n)
                        q = {"id": f"q{n:03d}", "group": grp, "market": mk, "text": text,
                             "source": "expand"}
                        qs.append(q)
                        existing.add(text)
                        added.append(q)
                    if added:
                        G.save_config(slug, cfg)
                return self._json({"ok": True, "added": len(added),
                                   "ids": [q["id"] for q in added]})

            if p == "/api/sample-import":
                import sample as S
                slug = str(body.get("slug") or "")
                name = str(body.get("file") or "").strip()
                if not slug or not name:
                    return self._json({"ok": False, "error": "缺 slug / file"}, 400)
                if self._deny(slug):
                    return
                # name 直接拼进路径，必须挡住分隔符——否则可以写到 work/ 之外
                # （界面传来的永远是 samples/ 下的 .md 文件名）
                if ("/" in name or "\\" in name or ".." in name or name.startswith(".")
                        or not name.endswith(".md") or len(name) <= 3):
                    return self._json({"ok": False, "error": "file 必须是文件名形式的 .md"}, 400)
                path = G.project_dir(slug) / "samples" / name
                if body.get("text") is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(str(body["text"]), "utf-8")
                elif not path.is_file():
                    return self._json({"ok": False, "error": f"采样表不存在：{name}"}, 404)
                S.sample_import(slug, str(path))
                return self._json({"ok": True})

            return self._send(404, b"not found", "text/plain")
        except SystemExit:  # G.die 会 sys.exit
            return self._json({"ok": False, "error": "操作失败（常见原因：项目标识已被占用）"}, 400)
        except (ValueError, RuntimeError) as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)


def _monitor_tick():
    """周期复跑：geo.json 的 monitor.next_run 到期就自动跑完整一期。

    GEO 是周期性工作——只在看板服务运行时触发（单机自托管，没有独立守护进程），
    服务停着的那几天不补跑，到期后下次启动时跑一次。"""
    for d in (G.WORK.iterdir() if G.WORK.exists() else []):
        cfg_path = d / "geo.json"
        if not cfg_path.exists():
            continue
        cfg = G.read_json(cfg_path, {})
        mon = cfg.get("monitor") or {}
        every = mon.get("every_days")
        if not every or (mon.get("next_run") or "") > G.today():
            continue
        if J.running_for(d.name):
            continue  # 有任务在跑，下个 tick 再看
        try:
            J.start(d.name, "serve", {})
            mon["next_run"] = (date.today() + timedelta(days=int(every))).isoformat()
            cfg["monitor"] = mon
            G.save_config(d.name, cfg)
            G.info(f"周期复跑触发：{d.name}，下次 {mon['next_run']}")
        except (ValueError, RuntimeError) as e:
            G.info(f"周期复跑跳过 {d.name}：{e}")


def _monitor_loop():
    while True:
        try:
            _monitor_tick()
        except Exception as e:  # noqa: BLE001  调度线程绝不能死
            G.info(f"周期复跑检查出错：{type(e).__name__}: {e}")
        time.sleep(1800)


def run(port: int = 8765, open_browser: bool = True,
        host: str | None = None, token: str | None = None):
    host = host or _env("XGEO_HOST") or "127.0.0.1"
    token = token or _env("XGEO_TOKEN") or None
    scoped = parse_scoped_tokens(_env("XGEO_PROJECT_TOKENS"))
    if host not in ("127.0.0.1", "localhost") and not token and not scoped             and not accounts_enabled():
        G.die(f"绑定到 {host} 会把看板暴露给网络上的所有人。"
              "先设置访问令牌再启动：export XGEO_TOKEN=$(openssl rand -hex 16)")
    Handler.TOKEN = token
    Handler.SCOPES = scoped
    # _host_ok 要知道这个实例是不是只服务本机：账号档下「绑本机」与「绑公网」
    # 的威胁模型不同（见那里的注释），而 host 只在这里知道。
    Handler.BIND_PUBLIC = host not in ("127.0.0.1", "localhost", "::1")
    J.reap_orphans()  # 回收上次服务留下的 running 僵尸记录，恢复并发保护
    J.prune_jobs()    # 清过期任务记录：列表接口每次要读所有 json，攒多了会越来越慢
    threading.Thread(target=_monitor_loop, daemon=True).start()
    srv = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}/"
    auth_note = ("，访问需令牌（XGEO_TOKEN）" if token
                 else f"，访问需项目令牌（{len(scoped)} 个）" if scoped else "")
    G.info(f"看板已启动：{url}（Ctrl+C 退出）{auth_note}")
    if not (UI_DIST / "index.html").is_file():
        G.info("未找到前端构建产物，页面会打不开。构建：npm --prefix frontend run build")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        G.info("看板已停止")
    finally:
        srv.server_close()
