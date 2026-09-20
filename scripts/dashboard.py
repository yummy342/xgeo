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
import threading
import time
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

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
                     "url": r.get("url", ""), "at": r.get("at", "")})
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


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _cookie_value(cookie_header: str | None) -> str | None:
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k in (AUTH_COOKIE, LEGACY_COOKIE) and v:
            return v
    return None


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


_LOGIN_HTML = """<!doctype html><meta charset="utf-8"><title>XGEO</title>
<body style="background:#131622;color:#e8eaf2;font-family:system-ui;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0">
<form style="text-align:center" onsubmit="location='/?token='+encodeURIComponent(
document.getElementById('t').value);return false">
<div style="font-size:20px;margin-bottom:14px">X<span style="color:#9184d9">GEO</span></div>
<input id="t" type="password" placeholder="访问令牌 / Access token" autofocus
style="background:#1b1e2e;border:1px solid #3a3f55;border-radius:8px;color:#e8eaf2;
padding:10px 14px;font-size:14px;width:240px">
<button style="background:#9184d9;border:0;border-radius:8px;color:#101223;
padding:10px 18px;font-size:14px;margin-left:8px;cursor:pointer">进入</button>
</form></body>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    TOKEN: str | None = None          # run() 注入；None = 没有管理员令牌
    SCOPES: dict[str, set[str]] = {}  # run() 注入；分项目令牌 → 允许的项目
    _scope: set[str] | None = None    # 本请求命中的令牌的授权范围，_auth 里赋值

    def log_message(self, *a):  # 静音访问日志
        pass

    def _auth(self) -> bool:
        """True=放行；False=已自行响应（401 或换 cookie 的 302）。"""
        if not Handler.TOKEN and not Handler.SCOPES:
            self._scope = None
            return True
        u = urlparse(self.path)
        qt = (parse_qs(u.query).get("token") or [None])[0]
        # _auth 在 try 之外调用：这里抛异常就是连接被直接掐断，连 401 都回不去
        if qt and _match_token(Handler.TOKEN, Handler.SCOPES, None, query_token=qt):
            # 令牌换 cookie 后跳回干净地址，别让令牌留在地址栏和访问日志里
            self.send_response(302)
            self.send_header("Location", u.path or "/")
            self.send_header("Set-Cookie", f"{AUTH_COOKIE}={_token_digest(qt)}; "
                                           "HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        if auth_ok(Handler.TOKEN, Handler.SCOPES, self.headers.get("Cookie"),
                   header_token=_header_token(self.headers)):
            self._scope = scope_of(Handler.TOKEN, Handler.SCOPES, self.headers.get("Cookie"),
                                   header_token=_header_token(self.headers))
            return True
        if self.command == "GET":
            self._send(401, _LOGIN_HTML.encode("utf-8"), "text/html; charset=utf-8")
        else:
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

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # 内容类型由扩展名猜，猜错就等于让浏览器改按 HTML 解析
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

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

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if n > Handler.MAX_BODY:
            # 不设上限的话，一个声明了超大 Content-Length 的请求就能把内存吃满。
            # 连带把连接关掉：剩下的请求体不读了，留着会被当成下一个请求解析。
            self.close_connection = True
            raise ValueError(f"请求体过大：{n} 字节，上限 {Handler.MAX_BODY // 1024 // 1024}MB")
        return json.loads(self.rfile.read(n) or b"{}")

    # ------------------------------------------------------------ GET
    def do_GET(self):
        if not self._auth():
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
        if not self._auth():
            return
        p = unquote(urlparse(self.path).path)
        if self._deny(path_slug(p)):
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
                job = J.get(jid)
                if job and self._deny(job.get("slug")):
                    return
                return self._json({"ok": J.stop(jid)})

            if p.startswith("/api/config/"):
                slug = p[len("/api/config/"):]
                cur = G.read_json(G.project_dir(slug) / "geo.json", {})
                cur.update(body)          # 整体覆盖字段，前端传完整对象
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
                cfg = G.read_json(G.project_dir(slug) / "geo.json", {})
                pub = cfg.setdefault("publishing", {})
                pub[code] = {k: str(v or "").strip() for k, v in (body.get("cfg") or {}).items()
                             if k in keys}
                G.save_config(slug, cfg)
                return self._json({"ok": True})

            if p.startswith("/api/publish/"):
                # 发布 = 外发动作：只响应界面上用户的明确点击，服务端绝不自行调用
                import publish as P
                slug = p[len("/api/publish/"):]
                r = P.publish(slug, body.get("platform", ""), body.get("path", ""),
                              body.get("title", ""))
                return self._json(r, 200 if r.get("ok") else 400)

            if p.startswith("/api/distribution/"):
                # 分发打勾：记录某问题的内容已铺到某阵地（人工确认口径，非自动判定）
                slug = p[len("/api/distribution/"):]
                qid, ch = (body.get("qid") or "").strip(), (body.get("channel") or "").strip()
                if not qid or not ch:
                    return self._json({"ok": False, "error": "缺 qid / channel"}, 400)
                path = G.project_dir(slug) / "distribution.json"
                dist = G.read_json(path, {})
                if body.get("on"):
                    dist.setdefault(qid, {})[ch] = G.now_iso()
                else:
                    dist.get(qid, {}).pop(ch, None)
                    if not dist.get(qid):
                        dist.pop(qid, None)
                G.write_json(path, dist)
                return self._json({"ok": True, "distribution": dist})

            if p == "/api/questions-add":
                slug = body.get("slug") or ""
                items = body.get("items")
                if not slug or not isinstance(items, list) or not items:
                    return self._json({"ok": False, "error": "缺 slug / items"}, 400)
                if self._deny(slug):
                    return
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
    if host not in ("127.0.0.1", "localhost") and not token and not scoped:
        G.die(f"绑定到 {host} 会把看板暴露给网络上的所有人。"
              "先设置访问令牌再启动：export XGEO_TOKEN=$(openssl rand -hex 16)")
    Handler.TOKEN = token
    Handler.SCOPES = scoped
    J.reap_orphans()  # 回收上次服务留下的 running 僵尸记录，恢复并发保护
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
