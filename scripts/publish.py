"""发布渠道对接：把成稿/资产一键发到你自己的渠道，并留发布记录。

安全边界（刻意为之，别放松）：
- 凭证只放项目根目录 .env（与引擎 Key 同一套管理，界面可配，已 gitignore）；
- 发布动作只由界面上的明确点击或 CLI 显式命令触发，没有任何自动发布路径；
- 公众号只建草稿（后台人工预览群发）；WordPress 只建草稿文章；
- GitHub 是提交文件到你自己的仓库；Webhook 打到你自己配置的接收端。

发布记录写 work/<slug>/publish.json，效果验收的 external.any 检查器
可以用发布落点的域名做「已被引擎引用」判定，闭环到验收。
"""

from __future__ import annotations

import base64
import json
import os
import re

import requests

import geolib as G

# 渠道注册表：env 是 .env 里的凭证变量；cfg 是存在项目 geo.json publishing.<code> 的非敏感配置。
# market：general 通用 / cn 国内 / global 海外，发布渠道页按此分组。
#
# 准入纪律：只接有官方可用发布 API 的平台，宁缺毋滥。微博（开放平台发布接口需企业应用
# 审核）、搜狐号/头条号/小红书/B站专栏（无公开发布 API）、LinkedIn（三方 OAuth + token
# 60 天过期）、Facebook 个人主页（接口已废弃）、Instagram（需企业号且不支持纯文本）均不
# 接入——Cookie 模拟发布违反各家 ToS 且极易失效，不进本产品；这些平台走人工发布或用
# 自定义 Webhook 桥接你自己的工具。
PUBLISHERS = {
    "github": {
        "name": "GitHub 仓库", "market": "general", "env": ["GITHUB_TOKEN"],
        "cfg": [("repo", "owner/repo"), ("branch", "main"), ("dir", "docs/geo")],
        "note": "Contents API 提交 markdown 到你的仓库（配 Pages/静态站即上线）",
        "guide": {"url": 'https://github.com/settings/tokens', "steps": ['github.com/settings/tokens 生成 Token（Fine-grained 或 classic 勾 repo 权限），只授权目标仓库', 'GITHUB_TOKEN 填生成的 token；repo 填 owner/repo，dir 是仓库内目录', '仓库开 GitHub Pages（Settings→Pages）后，文章提交即上线，URL 记入发布记录']},
    },
    "wordpress": {
        "name": "WordPress", "market": "general", "env": ["WP_USER", "WP_APP_PASSWORD"],
        "cfg": [("site_url", "https://blog.example.com")],
        "note": "REST API 新建草稿文章，登录后台确认后再发布",
        "guide": {"url": 'https://wordpress.org/documentation/article/application-passwords/', "steps": ['WP 后台 → 用户 → 个人资料 → 底部「应用程序密码」生成一个（需 WP 5.6+）', 'WP_USER 填登录用户名，WP_APP_PASSWORD 填生成的密码（含空格原样填）', 'site_url 填站点根地址；发布后是草稿，登录后台确认再对外']},
    },
    "webhook": {
        "name": "自定义 Webhook", "market": "general", "env": ["PUBLISH_WEBHOOK_URL"],
        "cfg": [],
        "note": "POST JSON {title, markdown, html, slug, path} 到你自己的接收端——没有官方 API 的平台用它桥接",
        "guide": {"url": '', "steps": ['起一个能收 POST JSON 的 HTTP 端点（自己的服务、n8n、云函数都行）', 'PUBLISH_WEBHOOK_URL 填端点地址；收到 {title, markdown, html, path}', '端点返回 {"url": "..."} 时会记为发布落点链接']},
    },
    "wechat_draft": {
        "name": "公众号草稿箱", "market": "cn", "env": ["WECHAT_APPID", "WECHAT_APPSECRET"],
        "cfg": [("thumb_media_id", "永久素材封面 media_id（草稿必需）")],
        "note": "新建草稿，需在公众号后台预览并群发；服务器 IP 要在白名单",
        "guide": {"url": 'https://mp.weixin.qq.com', "steps": ['公众号后台 → 设置与开发 → 基本配置：拿 AppID / AppSecret', '同页「IP 白名单」加上本机出口 IP（不加会报 40164）', '素材库上传一张封面图，拿永久素材 media_id 填 thumb_media_id（草稿必需）', '发布后到后台「草稿箱」预览、群发']},
    },
    "devto": {
        "name": "dev.to", "market": "global", "env": ["DEVTO_API_KEY"],
        "cfg": [("tags", "最多 4 个标签，逗号分隔，只能字母数字"),
                ("canonical_url", "官网原文地址（可选）：避免重复内容，并把权重指回自有站点")],
        "note": "Forem API 发布文章；默认建草稿（去后台确认），加 --published 直接对外",
        "guide": {"url": 'https://dev.to/settings/extensions', "steps": [
            'dev.to → Settings → Extensions → DEV Community API Keys → Generate API Key',
            'DEVTO_API_KEY 填生成的 key（生成后只显示一次）',
            'tags 最多 4 个，只能字母数字（不能有连字符或空格）；留空则不自动带标签',
            'canonical_url 填官网原文地址——文章同时发在官网和 dev.to 时，这行告诉搜索引擎谁是原文',
            '默认建草稿，到 dev.to 后台（Posts → Drafts）确认再对外；加 --published 则直接发布']},
    },
    "x": {
        "name": "X（推文引流）", "market": "global",
        "env": ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"],
        "cfg": [("link_url", "文章公开链接（留空则自动用该文件最近一次 GitHub/WordPress 发布的 URL）")],
        "note": "API v2 发一条「标题 + 摘要 + 链接」的推文引流，不是发全文；developer.x.com 建应用取四个凭证",
        "guide": {"url": 'https://developer.x.com/en/portal/dashboard', "steps": ['developer.x.com 申请开发者账号（Free 档即可发推），创建一个 App', 'App 的 User authentication settings 里开启 Read and Write 权限', 'Keys and tokens 页生成四个值：API Key/Secret（Consumer）+ Access Token/Secret', '注意：权限改成 Read/Write 之后要重新生成 Access Token，否则仍是只读', 'link_url 留空时自动用该文件最近一次 GitHub/WordPress 发布的 URL 作回链']},
    },
    "reddit": {
        "name": "Reddit（全文自帖）", "market": "global",
        "env": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USERNAME", "REDDIT_PASSWORD"],
        "cfg": [("subreddit", "发到哪个 subreddit（不带 r/）")],
        "note": "script 应用密码授权，markdown 全文作为 self-post；注意目标社区的自我推广规则",
        "guide": {"url": 'https://www.reddit.com/prefs/apps', "steps": ['reddit.com/prefs/apps → create app → 类型选「script」', 'REDDIT_CLIENT_ID 是应用名下方那串字符，SECRET 在旁边', '用户名密码就是登录凭证；账号开了两步验证会失败，建议用专用账号', 'subreddit 先用自己的主页社区（u_你的用户名）试发，再进目标社区——先读对方的自我推广规则']},
    },
}


def missing_env(code: str) -> list[str]:
    return [e for e in PUBLISHERS[code]["env"] if not os.environ.get(e)]


def _cfg(slug: str, code: str) -> dict:
    return (G.load_config(slug).get("publishing") or {}).get(code) or {}


# ---------------------------------------------------------------- markdown → html
# 公众号/WordPress 要 HTML。只做最小转换（标题/加粗/链接/列表/代码块/段落），
# 不引第三方库；表格等复杂结构原样进 <p>，发布前在渠道后台肉眼过一遍。

def md2html(md: str) -> str:
    md = G.strip_comments(md)
    out, in_code, in_list = [], False, False

    def inline(s):
        # 双引号必须一起转：链接目标会拼进 href="..."，不转的话
        # `[x](https://a.com/?q=1" onmouseover="alert(1))` 能往 <a> 注入属性，
        # 而这段 HTML 会发到 WordPress 正文、公众号草稿和 webhook 接收端。
        # report.py 那条链走 html.escape（含引号），只有发布这条链漏了。
        s = (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
              .replace('"', "&quot;"))
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        return s

    for line in md.splitlines():
        if line.strip().startswith("```"):
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(line.replace("&", "&amp;").replace("<", "&lt;"))
            continue
        m = re.match(r"(#{1,6})\s+(.*)", line)
        li = re.match(r"\s*[-*]\s+(.*)", line) or re.match(r"\s*\d+[.、]\s+(.*)", line)
        if in_list and not li:
            out.append("</ul>")
            in_list = False
        if m:
            n = min(len(m.group(1)) + 1, 6)  # 文内 # 降一级，标题留给渠道的 title 字段
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
        elif li:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(li.group(1))}</li>")
        elif line.strip():
            out.append(f"<p>{inline(line.strip())}</p>")
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


# ---------------------------------------------------------------- 各渠道实现

def _pub_github(cfg, text, title, fname):
    repo, branch = cfg.get("repo", ""), cfg.get("branch", "main")
    if not repo or "/" not in repo:
        return {"ok": False, "error": "先在设置里配置 repo（owner/repo）"}
    path = (cfg.get("dir", "").strip("/") + "/" + fname).lstrip("/")
    H = {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
         "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    body = {"message": f"geo: publish {title}", "branch": branch,
            "content": base64.b64encode(text.encode()).decode()}
    r0 = requests.get(url, headers=H, params={"ref": branch}, timeout=30)
    if r0.status_code == 200:  # 已存在→更新
        body["sha"] = r0.json().get("sha")
    r = requests.put(url, headers=H, json=body, timeout=30)
    if r.status_code in (200, 201):
        return {"ok": True, "url": r.json().get("content", {}).get("html_url", "")}
    return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}


def _pub_wordpress(cfg, text, title, fname):
    site = (cfg.get("site_url") or "").rstrip("/")
    if not site:
        return {"ok": False, "error": "先在设置里配置 site_url"}
    r = requests.post(f"{site}/wp-json/wp/v2/posts",
                      auth=(os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"]),
                      json={"title": title, "content": md2html(text), "status": "draft"},
                      timeout=30)
    if r.status_code == 201:
        return {"ok": True, "url": r.json().get("link", ""),
                "note": "已建为草稿，到 WordPress 后台确认发布"}
    return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}


def _pub_wechat(cfg, text, title, fname):
    thumb = cfg.get("thumb_media_id", "")
    if not thumb:
        return {"ok": False, "error": "缺封面：先在设置里配置 thumb_media_id（永久素材）"}
    tr = requests.get("https://api.weixin.qq.com/cgi-bin/token",
                      params={"grant_type": "client_credential",
                              "appid": os.environ["WECHAT_APPID"],
                              "secret": os.environ["WECHAT_APPSECRET"]}, timeout=30).json()
    tok = tr.get("access_token")
    if not tok:
        return {"ok": False, "error": f"取 token 失败：{tr.get('errmsg', tr)}"}
    art = {"title": title[:60], "content": md2html(text), "thumb_media_id": thumb,
           "digest": re.sub(r"\s+", " ", text)[:100]}
    r = requests.post(f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={tok}",
                      data=json.dumps({"articles": [art]}, ensure_ascii=False).encode(),
                      timeout=30).json()
    if r.get("media_id"):
        return {"ok": True, "url": "", "note": "已进草稿箱，到公众号后台预览群发"}
    return {"ok": False, "error": f"draft/add 失败：{r.get('errmsg', r)}"}


def _pub_devto(cfg, text, title, fname):
    """dev.to（Forem）建草稿。发布前到 dev.to 后台确认。
    canonical_url 不是可选项的细节：同一篇同时发在官网和 dev.to 时，它决定搜索引擎认谁是原文。"""
    tags = [t.strip() for t in (cfg.get("tags") or "").split(",") if t.strip()][:4]
    now = bool(cfg.get("_publish_now"))
    art = {"title": title, "body_markdown": text, "published": now, "tags": tags}
    if cfg.get("canonical_url"):
        art["canonical_url"] = cfg["canonical_url"]
    r = requests.post("https://dev.to/api/articles",
                      headers={"api-key": os.environ["DEVTO_API_KEY"],
                               "Content-Type": "application/json"},
                      json={"article": art}, timeout=30)
    if r.status_code == 201:
        return {"ok": True, "url": r.json().get("url", ""),
                "note": "已直接发布" if now else "已建为草稿，到 dev.to 后台确认发布",
                "state": "published" if now else "draft"}
    return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}


def _pub_webhook(cfg, text, title, fname):
    r = requests.post(os.environ["PUBLISH_WEBHOOK_URL"],
                      json={"title": title, "markdown": text, "html": md2html(text),
                            "path": fname}, timeout=30)
    if 200 <= r.status_code < 300:
        url = ""
        try:
            url = (r.json() or {}).get("url", "")
        except Exception:  # noqa: BLE001  接收端不回 JSON 也算成功
            pass
        return {"ok": True, "url": url}
    return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}


# ---------------------------------------------------------------- X (OAuth 1.0a)

def _oauth1_header(method: str, url: str, ck: str, cs: str, tk: str, ts: str) -> str:
    """OAuth 1.0a 签名头（HMAC-SHA1，纯标准库）。v2 发推的请求体是 JSON，
    不参与签名，只签 oauth_* 参数本身。"""
    import hashlib
    import hmac
    import secrets
    import time as _t
    from urllib.parse import quote

    q = lambda s: quote(str(s), safe="~")
    p = {
        "oauth_consumer_key": ck, "oauth_token": tk,
        "oauth_signature_method": "HMAC-SHA1", "oauth_version": "1.0",
        "oauth_timestamp": str(int(_t.time())), "oauth_nonce": secrets.token_hex(16),
    }
    base = "&".join([method.upper(), q(url),
                     q("&".join(f"{q(k)}={q(v)}" for k, v in sorted(p.items())))])
    key = f"{q(cs)}&{q(ts)}"
    sig = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    p["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{q(k)}="{q(v)}"' for k, v in sorted(p.items()))


def _latest_public_url(recs: list, rel: str) -> str:
    """该文件最近一次长文渠道（GitHub/WordPress/Webhook）发布成功的 URL——
    社交渠道引流的默认回链：先发长文，再发社交。

    按完整相对路径匹配，不能按 basename：assets/outlines/q001.md 与
    assets/drafts/q001.md 同名，先发大纲再发初稿时推文会链到另一份文档。
    """
    for r in reversed(recs or []):
        p = str(r.get("path", ""))
        if r.get("ok") and r.get("url") and (p == rel or p.endswith("/" + rel)) \
                and r.get("platform") in ("github", "wordpress", "webhook"):
            return r["url"]
    return ""


def _x_len(s: str) -> int:
    """X 的加权长度：CJK/全角计 2，其余计 1（URL 另算固定 23）。"""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in s)


def _x_trim(s: str, budget: int) -> str:
    out, used = [], 0
    for c in s:
        w = 2 if ord(c) > 0x2E80 else 1
        if used + w > budget:
            break
        out.append(c)
        used += w
    return "".join(out)


def _pub_x(cfg, text, title, fname):
    link = (cfg.get("link_url") or "").strip() \
        or _latest_public_url(cfg.get("_records") or [], cfg.get("_rel") or fname)
    # 摘要：正文第一段非标题文本
    para = next((ln.strip() for ln in text.splitlines()
                 if ln.strip() and not ln.startswith("#")), "")
    # 预算 280 加权单位：链接固定折算 23 + 换行，再留 2 个单位余量防边界
    budget = 280 - (25 if link else 0) - 2
    tweet = _x_trim(title, budget)
    room = budget - _x_len(tweet) - 2   # 减去两个换行
    if para and room > 40:
        tweet += "\n\n" + _x_trim(para, room)
    if link:
        tweet += "\n" + link
    hdr = _oauth1_header("POST", "https://api.x.com/2/tweets",
                         os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
                         os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_SECRET"])
    r = requests.post("https://api.x.com/2/tweets", json={"text": tweet},
                      headers={"Authorization": hdr, "Content-Type": "application/json"},
                      timeout=30)
    if r.status_code == 201:
        tid = (r.json().get("data") or {}).get("id", "")
        return {"ok": True, "url": f"https://x.com/i/web/status/{tid}" if tid else "",
                "note": "" if link else "未带回链（该文件还没有长文渠道的公开 URL）"}
    return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}


# ---------------------------------------------------------------- Reddit (script app)

def _pub_reddit(cfg, text, title, fname):
    sub = (cfg.get("subreddit") or "").strip().removeprefix("r/")
    if not sub:
        return {"ok": False, "error": "先在设置里配置 subreddit"}
    ua = "xgeo-publisher/0.1 by " + os.environ["REDDIT_USERNAME"]
    tok = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(os.environ["REDDIT_CLIENT_ID"], os.environ["REDDIT_CLIENT_SECRET"]),
        data={"grant_type": "password", "username": os.environ["REDDIT_USERNAME"],
              "password": os.environ["REDDIT_PASSWORD"]},
        headers={"User-Agent": ua}, timeout=30)
    if tok.status_code != 200 or "access_token" not in (tok.json() or {}):
        return {"ok": False, "error": f"取 token 失败 HTTP {tok.status_code}: {tok.text[:150]}"}
    r = requests.post(
        "https://oauth.reddit.com/api/submit",
        data={"sr": sub, "kind": "self", "title": title, "text": text,
              "api_type": "json"},
        headers={"Authorization": "bearer " + tok.json()["access_token"], "User-Agent": ua},
        timeout=30)
    j = (r.json() or {}).get("json", {}) if r.status_code == 200 else {}
    if r.status_code == 200 and not j.get("errors"):
        return {"ok": True, "url": (j.get("data") or {}).get("url", "")}
    err = "; ".join("/".join(map(str, e)) for e in j.get("errors", [])) or f"HTTP {r.status_code}"
    return {"ok": False, "error": err[:200]}



def _state_of(code: str, res: dict) -> str:
    """这次发布之后，内容到底对外可见了没有。

    渠道自己报了状态就用它的（dev.to 会区分草稿与直发）；没报就按渠道语义取默认。
    调用失败时给空串——失败没有可见性可言，前端也不该拿它计数。
    """
    if not res.get("ok"):
        return ""
    return res.get("state") or DEFAULT_STATE.get(code, "")


# 渠道的默认对外可见性。ok 只说调用没报错，state 才说内容有没有公开——
# 两者混为一谈过：三篇文章在 dev.to 的 Drafts 里躺着，记录和界面都显示已发布。
DEFAULT_STATE = {
    "devto": "draft",         # 默认只建草稿，加 --published 直发
    "wordpress": "draft",     # REST API 建的是草稿，要人工去后台确认
    "wechat_draft": "draft",  # 同上，只建草稿
    "github": "published",    # 提交进仓库即公开
    "reddit": "published",
    "x": "published",
    "webhook": "published",
}

_IMPL = {"github": _pub_github, "wordpress": _pub_wordpress,
         "wechat_draft": _pub_wechat, "webhook": _pub_webhook,
         "devto": _pub_devto, "x": _pub_x, "reddit": _pub_reddit}


# ---------------------------------------------------------------- 入口与记录

def _read_source(slug: str, rel: str) -> tuple[str, str]:
    """rel 限定在 content/ 或 assets/ 下，返回 (文本, 文件名)。

    校验解析后的真实路径归属，防 content/../ 这类穿越。"""
    pdir = G.project_dir(slug).resolve()
    target = (pdir / rel).resolve()
    if not any(target.is_relative_to(pdir / d) for d in ("content", "assets")):
        raise ValueError("只允许发布 content/ 或 assets/ 下的文件")
    return target.read_text("utf-8"), target.name


def _title_of(text: str, fname: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else fname.rsplit(".", 1)[0]


_SECRET_RX = re.compile(r"(access_token|token|key|secret|password|api_key)=[^&\s\"']+", re.I)


def _scrub(s: str) -> str:
    """给异常串脱敏。

    requests 的连接错误会把完整 URL 塞进消息里，而公众号的 access_token 只能
    拼在 query 上（微信不支持 header 传），于是 token 会经 /api/publish 的 500
    出口直接显示在界面上、留在服务端日志里。webhook 的 URL 常带密钥，同理。
    """
    return _SECRET_RX.sub(r"\1=***", s or "")


def records(slug: str) -> list[dict]:
    return G.read_json(G.project_dir(slug) / "publish.json", []) or []


def publish(slug: str, code: str, rel: str, title: str = "", publish_now: bool = False) -> dict:
    if code not in PUBLISHERS:
        return {"ok": False, "error": f"未知渠道 {code}"}
    miss = missing_env(code)
    if miss:
        return {"ok": False, "error": "缺凭证：" + "、".join(miss)}
    try:
        text, fname = _read_source(slug, rel)
    except (ValueError, FileNotFoundError, OSError) as e:
        # OSError 也要接住：rel 指向目录（IsADirectoryError）或权限不足时会裸抛到
        # /api/publish 的 500，用户看到的是英文异常名而不是「文件不可用」。
        return {"ok": False, "error": f"文件不可用：{rel}（{type(e).__name__}）"}
    title = title or _title_of(text, fname)
    # 发布记录随 cfg 传入（不用模块级全局：看板是多线程服务，
    # 并发发布不同项目时全局会互相污染回链归属）
    cfg = dict(_cfg(slug, code))
    cfg["_records"] = records(slug)
    cfg["_rel"] = rel          # 回链按完整相对路径匹配，不用 basename
    # 直发开关。默认 False 时 dev.to 只建草稿，等人工去后台点发布——那个步骤
    # 漏过一次（两篇成稿在 Drafts 里躺了三天没人点），所以给 CLI 一条显式直发的路。
    cfg["_publish_now"] = publish_now
    try:
        res = _IMPL[code](cfg, text, title, fname)
    except Exception as e:  # noqa: BLE001
        # 外发动作必须留痕。裸抛的话 publish.json 里既没有成功也没有失败记录，
        # 用户无从判断「到底发出去没有」，而再点一次就是重复帖 —— 各渠道都没有
        # 幂等键。最典型的情形恰恰是「回调超时，但服务端其实已经收下」。
        G.info(f"发布失败（{code}）：{type(e).__name__}: {_scrub(str(e))}")
        res = {"ok": False, "error": f"{type(e).__name__}: {_scrub(str(e))}",
               "note": "状态未知：可能已经发出，先去渠道后台确认，再决定要不要重发"}
    # state 是「对外可见性」，跟 ok 分开：ok 只说这次调用没报错。
    # 渠道自己报了就用它的（dev.to 会区分草稿与直发），没报就按渠道语义取默认值。
    entry = {"at": G.now_iso(), "platform": code, "platform_name": PUBLISHERS[code]["name"],
             "path": rel, "title": title, "ok": res.get("ok", False),
             "state": _state_of(code, res),
             "url": res.get("url", ""), "note": res.get("note", ""),
             "error": _scrub(str(res.get("error", "")))}
    # 读-改-写必须持锁：ThreadingHTTPServer 下两个标签页并发发布会后写覆盖先写，
    # 丢一条记录 —— 回链选择和看板的「已发布」标记都跟着错。
    with G.project_lock(slug):
        rows = records(slug)
        rows.append(entry)
        G.write_json(G.project_dir(slug) / "publish.json", rows[-200:])
    return {**res, "record": entry}
