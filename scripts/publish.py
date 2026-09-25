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
import posixpath
import re

import requests

import geolib as G

# 渠道注册表：env 是 .env 里的凭证变量；cfg 是存在项目 geo.json publishing.<code> 的非敏感配置。
# market：general 通用 / cn 国内 / global 海外，发布渠道页按此分组。
#
# 准入纪律：两条通路，按**平台规则**选，不按实现难度选。
#
# 1) 自动发布（_IMPL 里有实现 + env 凭证齐）：只接平台规则允许官方 API 自动推送的渠道。
# 2) 半自动（PUBLISHERS[code]["semi"] 规格在）：平台规则禁止自动推送、或没有个人可用的
#    发布接口时，工具只做「备好内容 + 一键复制 + 打开发布页」，**最后那一下发布由账号
#    主人自己点**。工具不代点、不模拟登录、不代持 Cookie。
#
# 第 2 档不是「怕 ToS 的妥协」，是唯一合规形态。以微博为例（都是它自家规则）：
#   · 发布类接口需要用户 OAuth2.0 授权，不只是企业开发者审核；
#   · 开放平台明文规定「用户授权确认后使用应用，不得直接将使用信息自动分享到用户微博，
#     需以浮层或明显提示让用户选择『分享』或『取消』」，并禁止「利用用户账号在不知情的
#     情况下发微博、发私信、发 @」；
#   · 禁止或难以过审的应用类型里点名列了「多微博平台同步类」——本产品正是这一类；
#     未审核应用仅限创建者 + 15 个测试用户调用，AccessToken 未审核 24 小时。
# 结论：自动代点在这些平台不是「技术上做不到」，是**平台规则本身禁止把发布动作交给应用**。
# 所以红线没有放松，只是划得更准了：**不代点发布**；接入的是「人工发布的正规化」——
# 内容备好、链接回填、发布状态可追溯。Cookie 模拟登录代发仍然一律不做。
#
# 不接的：微博（走 semi）、LinkedIn（三方 OAuth + token 60 天过期）、Facebook 个人主页
# （接口已废弃）、Instagram（需企业号且不支持纯文本）。
def _semi(**over) -> dict:
    """半自动规格：默认值 + 覆盖。

    默认值取多数平台的形态（富文本编辑器、要封面、带标签、正文接回链）；
    每个渠道只写它跟默认不同的项 —— 九个渠道各写满 15 个字段会把注册表埋掉。

    字段含义（消费点见 _prepare_payload 与前端 ManualPublishDialog）：
      publish_url   打开发布页的地址。放**稳定入口页**，深链接失效是常事，而它是数据。
                    留空 = 待核实，界面只提示不显示按钮。
      login_url     未登录时的提示链接。
      body_form     正文形态 html / markdown / text（"tbd" 按 text 处理，纯文本最不容易坏）。
      copy_as       剪贴板 flavor，可与 body_form 不同。
      title_max     标题上限；数字则超了截断并告警，"tbd"/None 只告警不截断。
      title_inline  True = 平台没有独立标题栏（微博），标题并入正文首行。
      tags          {max, format(plain|inline), prefix, suffix, sep}；max 为 "tbd" 只告警。
      cover         required / optional / False / "tbd"。
      backlink      正文尾部是否自动接上长文落点（复用 _latest_public_url）。
      dist          回填时顺带勾上的蓝图阵地 id（distribution.json）。
      api           {status: available|blocked|unverified, note}。blocked 时永不自动选 api 通路。
      editor_hint   粘贴前要做的动作；link_hint 回填时去哪复制公开链接。
    """
    s = {
        "publish_url": "", "login_url": "",
        "body_form": "html", "copy_as": "html",
        "title_max": "tbd", "title_inline": False,
        "tags": {"max": 5, "format": "plain", "prefix": "", "suffix": "", "sep": ","},
        "cover": "optional", "backlink": True, "dist": None,
        "api": {"status": "unverified", "note": ""},
        "editor_hint": "", "link_hint": "",
    }
    s.update(over)
    return s


# 半自动渠道共用同一套操作步骤（渲染在配置弹窗里）。渠道特有的注意点写在 _semi 的
# editor_hint / link_hint，不往这里堆 —— 这里只说流程，说一遍就够。
_SEMI_STEPS = [
    '点「备好并复制」：按本渠道的格式生成标题、正文、标签',
    '点「复制正文」（富文本渠道会连格式一起复制）',
    '点「打开发布页」，登录后粘贴；先读一眼弹窗里的「编辑器提示」',
    '发布完成后回到这里「贴回链接」—— 这一步别跳，回链与分发清单都靠它',
]

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
        # 公众号同时有两条路：配了凭证走 API 建草稿；没配（或想手排一次版）走半自动。
        "semi": _semi(
            publish_url="https://mp.weixin.qq.com/", login_url="https://mp.weixin.qq.com/",
            title_max=64, cover="required", dist="wechat",
            api={"status": "available",
                 "note": "草稿箱 API 通（需把服务器出口 IP 加进白名单）；草稿仍需到后台群发"},
            editor_hint="后台「新的创作 → 图文消息」，正文框可直接粘富文本；标题上限 64 字",
            link_hint="群发后点右上「…」→ 复制链接",
        ),
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
        # Reddit 也有两条路。API 那条风控严（新号）+ 要求披露；半自动让登录态留在
        # 你自己的浏览器里，反而更稳。publish_url 的 {subreddit} 从 cfg 取值。
        "semi": _semi(
            publish_url="https://www.reddit.com/r/{subreddit}/submit",
            publish_url_fallback="https://www.reddit.com/submit",
            login_url="https://www.reddit.com/login/",
            body_form="markdown", copy_as="markdown", title_max=300,
            tags={"max": None, "format": "plain"}, cover=False, dist="reddit",
            api={"status": "available", "note": "API 通（script 应用 + 密码授权），但风控严、要求披露身份"},
            editor_hint="正文框吃 Markdown；先选好目标子版，发前读一遍那版的自我推广规则",
            link_hint="发布后在帖子下方 share → copy link",
        ),
        "guide": {"url": 'https://www.reddit.com/prefs/apps', "steps": ['reddit.com/prefs/apps → create app → 类型选「script」', 'REDDIT_CLIENT_ID 是应用名下方那串字符，SECRET 在旁边', '用户名填 Reddit 用户名（不是登录邮箱），密码是账号密码；开了两步验证会失败，建议用专用账号', 'subreddit 先用自己的主页社区（u_你的用户名）试发，再进目标社区——先读对方的自我推广规则']},
    },

    # ---------------- 半自动（无可用自动发布通路，工具只备好、不代发） ----------------
    "toutiao": {
        "name": "头条号", "market": "cn", "env": [], "cfg": [],
        "note": "无个人可用的发布接口；备好标题与富文本正文，你到后台粘贴发布",
        "guide": {"url": 'https://mp.toutiao.com/', "steps": _SEMI_STEPS},
        "semi": _semi(
            publish_url="https://mp.toutiao.com/profile_v4/graphic/publish",
            login_url="https://mp.toutiao.com/",
            title_max=30, cover="required", dist="toutiao",
            api={"status": "blocked", "note": "平台无个人可用的发布接口"},
            editor_hint="标题 30 字上限（以编辑器实时计数为准，超了会被截）；正文粘贴富文本，图片要重新上传",
            link_hint="「内容管理」里点开刚发的文章，复制地址栏",
        ),
    },
    "sohu": {
        "name": "搜狐号", "market": "cn", "env": [], "cfg": [],
        "note": "无个人可用的发布接口；备好后人工粘贴",
        "guide": {"url": 'https://mp.sohu.com/', "steps": _SEMI_STEPS},
        "semi": _semi(
            publish_url="https://mp.sohu.com/", login_url="https://mp.sohu.com/",
            cover="optional", dist="media",
            api={"status": "blocked", "note": "平台无个人可用的发布接口"},
            editor_hint="创作中心 → 发文章；正文贴富文本，外链图不显示，要重新上传",
            link_hint="文章页复制地址栏",
        ),
    },
    "zhihu": {
        "name": "知乎", "market": "cn", "env": [], "cfg": [],
        "note": "专栏无公开的自动发布接口；备好后人工粘贴（Markdown 直粘）",
        "guide": {"url": 'https://zhuanlan.zhihu.com/write', "steps": _SEMI_STEPS},
        "semi": _semi(
            publish_url="https://zhuanlan.zhihu.com/write",
            login_url="https://www.zhihu.com/signin",
            body_form="markdown", copy_as="markdown",
            tags={"max": 5, "format": "plain", "sep": ","}, dist="zhihu",
            api={"status": "blocked", "note": "专栏无公开的自动发布接口"},
            editor_hint="专栏编辑器先切到 Markdown 模式再粘；标签最多 5 个",
            link_hint="发布后复制文章链接",
        ),
    },
    "csdn": {
        "name": "CSDN", "market": "cn", "env": [], "cfg": [],
        "note": "无公开的自动发布接口；备好后人工粘贴（Markdown 直粘）",
        "guide": {"url": 'https://editor.csdn.net/md/', "steps": _SEMI_STEPS},
        "semi": _semi(
            publish_url="https://editor.csdn.net/md/", login_url="https://passport.csdn.net/login",
            body_form="markdown", copy_as="markdown",
            tags={"max": 5, "format": "plain", "sep": ","}, dist="tech",
            api={"status": "blocked", "note": "无公开的自动发布接口"},
            editor_hint="编辑器默认 Markdown；标签最多 5 个，逗号分隔",
            link_hint="发布后复制博客链接",
        ),
    },
    "baijia": {
        "name": "百家号", "market": "cn", "env": [], "cfg": [],
        "note": "无个人可用的发布接口；备好后人工粘贴",
        "guide": {"url": 'https://baijiahao.baidu.com/', "steps": _SEMI_STEPS},
        "semi": _semi(
            publish_url="", login_url="https://baijiahao.baidu.com/",
            cover="required", dist="baijia",
            api={"status": "blocked", "note": "无个人可用的发布接口"},
            editor_hint="后台「发布 → 图文」；正文粘贴富文本，封面必填",
            link_hint="「内容管理」里点开文章复制链接",
        ),
    },
    "weibo": {
        "name": "微博", "market": "cn", "env": [], "cfg": [],
        "note": "平台规则禁止应用代发；备好正文（标题并入首行）后人工发布",
        "guide": {"url": 'https://weibo.com/', "steps": _SEMI_STEPS},
        "semi": _semi(
            publish_url="https://weibo.com/", login_url="https://weibo.com/login.php",
            body_form="text", copy_as="text",
            title_max=None, title_inline=True,
            tags={"max": "tbd", "format": "inline", "prefix": "#", "suffix": "#", "sep": " "},
            cover=False, dist=None,
            api={"status": "blocked",
                 "note": "平台规则禁止自动推送：发布接口需用户 OAuth2.0 授权；明文规定不得把"
                         "使用信息自动分享到用户微博；「多微博平台同步类」应用禁止或难以过审"},
            editor_hint="微博没有独立标题栏 —— 标题已并入正文首行；话题写成 #话题# 形式",
            link_hint="发布后点微博时间戳进详情页，复制地址栏",
        ),
    },
    "smzdm": {
        "name": "什么值得买", "market": "cn", "env": [], "cfg": [],
        "note": "发布接口未核实；先备好内容人工投递",
        "guide": {"url": 'https://www.smzdm.com/', "steps": _SEMI_STEPS},
        "semi": _semi(
            publish_url="", login_url="https://www.smzdm.com/",
            body_form="tbd", copy_as="text",
            api={"status": "unverified", "note": "是否存在可用的发布接口未核实"},
            editor_hint="发布入口与格式待核实：先打开站点确认投稿/发文位置，再决定正文形态",
            link_hint="发布后复制公开链接",
        ),
    },
}


def missing_env(code: str) -> list[str]:
    return [e for e in PUBLISHERS[code]["env"] if not os.environ.get(e)]


def _cfg(slug: str, code: str) -> dict:
    return (G.load_config(slug).get("publishing") or {}).get(code) or {}


# ---------------------------------------------------------------- markdown → html
# 公众号/WordPress 要 HTML。只做最小转换（标题/加粗/链接/列表/代码块/段落），
# 不引第三方库；表格等复杂结构原样进 <p>，发布前在渠道后台肉眼过一遍。

def _esc(s: str) -> str:
    """HTML 转义（文本与属性共用，含引号）。发布这条链唯一的转义入口。"""
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _linkable(url: str) -> bool:
    """能不能当链接目标：只认 http(s) 与站内相对路径。

    为什么要拦 scheme（而不只是转义字符）：`[x](javascript:…)` 出来的 `<a href>`
    会被前端 `{@html}` 渲染成可点链接，也会发到 WordPress 正文、公众号草稿、
    webhook 接收端。转义只挡住「拼出属性」，挡不住 scheme 本身 —— 而
    `content/*.md` 是能经 `POST /api/content/` 写入的，等于把 XSS 交给内容作者。
    百分号编码也绕不过：Chromium 执行前会解码 `javascript:`。
    """
    s = str(url or "").strip()
    # `//evil.com/x` 是协议相对地址：`^(/|...)` 会放过它，但它不是「站内相对路径」，
    # 浏览器会去外站。注释说「只认站内相对路径」，那就把这一支也挡掉。
    if s.startswith("//"):
        return False
    return bool(re.match(r"^(https?://|/)", s, re.I))


def md2html(md: str) -> str:
    md = G.strip_comments(md)
    out, in_code, in_list = [], False, False

    def inline(s):
        # 双引号必须一起转：链接目标会拼进 href="..."，不转的话
        # `[x](https://a.com/?q=1" onmouseover="alert(1))` 能往 <a> 注入属性，
        # 而这段 HTML 会发到 WordPress 正文、公众号草稿和 webhook 接收端。
        # report.py 那条链走 html.escape（含引号），只有发布这条链漏了。
        s = _esc(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)

        def _link(m):
            label, url = m.group(1), m.group(2).strip()
            # 认不出 scheme 就退化成纯文本（标签 + 括号里的地址），别丢信息
            return f'<a href="{url}">{label}</a>' if _linkable(url) else f"{label}（{url}）"

        return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, s)

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


# ---------------------------------------------------------------- markdown → 纯文本


def md2text(md: str) -> str:
    """把 markdown 压成纯文本：给没有富文本/Markdown 支持的发布框用。

    **有损且不可逆**：表格、图片、嵌套结构都会退化。所以调用方必须把结果先给人看
    再进剪贴板 —— 猜错的表现是「贴进去格式全乱」，那时人已经花时间了。
    """
    text = G.strip_comments(md or "")
    out: list[str] = []
    in_code = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            out.append(("    " + line.strip()) if line.strip() else "")
            continue
        s = line.strip()
        if not s:
            out.append("")
            continue
        s = re.sub(r"^#{1,6}\s*", "", s)                       # 标题去井号
        s = re.sub(r"^>\s*", "", s)                            # 引用
        s = re.sub(r"^[-*+]\s+", "· ", s)                      # 无序列表
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)                 # 粗体
        s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", s)       # 斜体
        s = re.sub(r"`([^`]+)`", r"\1", s)                      # 行内代码
        s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1 \2", s)    # 图片
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1（\2）", s)   # 链接
        if s.startswith("|") and s.endswith("|"):               # 表格
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells if c):
                continue                                        # 分隔行丢掉
            s = "  ".join(cells)
        out.append(s)
    res, blank = [], False
    for l in out:
        if not l.strip():
            if blank:
                continue
            blank = True
        else:
            blank = False
        res.append(l)
    return "\n".join(res).strip()


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
    # Reddit 要 `platform:app-id:version (by /u/user)` 格式，generic UA 会被挡
    ua = "xgeo:publisher:0.1 (by /u/%s)" % os.environ["REDDIT_USERNAME"]
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
    # 半自动渠道：从不外发，state 由 prepare(prepared) / record_manual(published) 显式写。
    # 登记成 draft 是硬要求 —— 漏登记会让前端把「备好了」显示成已发布（tests/test_publish_state.py
    # 遍历 PUBLISHERS 断言覆盖，漏一个就红；另有断言要求带 semi 规格的必须是 draft）。
    "toutiao": "draft",
    "sohu": "draft",
    "zhihu": "draft",
    "csdn": "draft",
    "baijia": "draft",
    "weibo": "draft",
    "smzdm": "draft",
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


# ---------------------------------------------------------------- 半自动：备好，不代发
#
# 这条链只做三件事：按渠道格式把内容备好 → 人复制粘贴发布 → 回填公开链接。
# **它不发任何外发请求、不模拟登录、不代持 Cookie** —— 平台规则不允许（见文件头的
# 准入纪律注释）。所以它不写「已发布」，只写「已备好待粘贴」，回填后才转已发布。

SEMI_STATE = "prepared"   # 备好待人工粘贴。既不是 draft（渠道里建了草稿）也不是 published


def record_id() -> str:
    """给每条备好记录一个短 id，供「备好 → 回填」配对。"""
    return os.urandom(4).hex()


def _norm_rel(rel: str) -> str:
    """归一化相对路径。

    `content/a.md` / `content//a.md` / `content/./a.md` 是同一个文件，但 `_open_record`
    按字符串比 —— 不归一化时同一份文件能备出好几条待办（「反复点不刷待办」失效，
    回填该用哪个 id 也说不清）。穿越形态（`../x`）留给 `_read_source` 的归属校验去拒。
    """
    return posixpath.normpath(str(rel or "").strip())


def paths_of(code: str) -> list[str]:
    """该渠道现在有哪几条路，按优先级。api 看 _IMPL 有没有实现，semi 看规格在不在。"""
    out = []
    if code in _IMPL:
        out.append("api")
    if (PUBLISHERS.get(code) or {}).get("semi"):
        out.append("semi")
    return out


def resolve_path(code: str, slug: str | None = None, force: str | None = None) -> str:
    """这个渠道这次走哪条路：api / semi / ""（两条都不通）。

    判据是**能力**，不是**就绪** —— 这条线一开始被我写混了：
      · 「有没有 api 通路」看 _IMPL 有没有实现、规格里有没有标 blocked。
      · 「凭证/cfg 齐不齐」是**就绪**，该由 publish() 去报（「缺凭证：WP_USER」比
        「没有可用的发布通路」有用得多），前端另有 missing 字段表达。
    所以只有 api 通路的渠道**恒返回 api**，让它去撞真实错误；缺凭证时 path 不该变成空
    （那会让 GET 里 paths=["api"] 与 path="" 自相矛盾，也会把 prepare 的拒绝理由说错）。

    双路渠道（Reddit/公众号）例外：凭证或必备 cfg 缺时**让位给半自动** —— 那正是
    半自动存在的理由（不联网发布也能把内容铺出去）。
    """
    paths = paths_of(code)
    if force in paths:
        return force
    blocked = ((PUBLISHERS.get(code) or {}).get("semi") or {}).get("api", {}).get("status") == "blocked"
    if "api" not in paths or blocked:
        return "semi" if "semi" in paths else ""
    if "semi" not in paths:
        return "api"
    if missing_env(code):
        return "semi"
    # 注：这里把「注册表声明了 cfg」当作「cfg 必需」。对现有渠道成立（reddit 的
    # subreddit 是真必需），但注册表里也有可选键（devto 的 tags/canonical_url、x 的
    # link_url）。今天不出错是因为那些渠道没有半自动规格、走不到这里；哪天给它们加
    # semi 规格时，得先给 cfg 加「必需/可选」的标记，否则没填可选项就会被静默降级。
    cfg_keys = [k for k, _ in (PUBLISHERS[code].get("cfg") or [])]
    if not cfg_keys:
        return "api"
    cfg = _cfg(slug, code) if slug else {}
    return "api" if all(str(cfg.get(k) or "").strip() for k in cfg_keys) else "semi"


# 占位值归一。Reddit 的 subreddit 填 `r/xgeo` 也能用 —— 模板里已经含 `/r/`，
# 而 API 路径 `_pub_reddit` 也 removeprefix("r/")，两处口径要一致（否则发布页会
# 变成 `https://www.reddit.com/r/r/xgeo/submit`）。
_PLACEHOLDER_NORM = {"subreddit": lambda v: re.sub(r"^r/", "", v, flags=re.I)}


def semi_spec(code: str, slug: str | None = None) -> dict | None:
    """注册表里的规格 → 前端要的字典：填掉 cfg 占位、算出 publish_url、带上 api 状态。"""
    p = PUBLISHERS.get(code) or {}
    spec = p.get("semi")
    if not spec:
        return None
    cfg = _cfg(slug, code) if slug else {}
    url, missing = str(spec.get("publish_url") or ""), []
    for name in re.findall(r"\{(\w+)\}", url):
        val = str(cfg.get(name) or "").strip()
        norm = _PLACEHOLDER_NORM.get(name)
        if val and norm:
            val = norm(val)
        if not val:
            missing.append(name)
        url = url.replace("{" + name + "}", val)
    if missing:
        # 占位没填就别给一个会把 {subreddit} 原样打开的地址；有兜底页就用兜底页
        url = str(spec.get("publish_url_fallback") or "")
    return {**spec, "code": code, "name": p.get("name", code),
            "publish_url": url, "missing_placeholders": missing,
            "paths": paths_of(code), "path": resolve_path(code, slug),
            "steps": (p.get("guide") or {}).get("steps") or _SEMI_STEPS}


def _tags_text(tags: dict, proj: dict, cfg: dict) -> str:
    """按渠道格式生成标签串。标签内容取渠道 cfg 覆盖，没有就用项目 keywords 前 N 个。"""
    n = tags.get("max")
    if n is None:
        return ""
    items = [str(s).strip() for s in (cfg.get("tags") or proj.get("keywords") or []) if str(s).strip()]
    if isinstance(n, int):
        items = items[:n]
    if not items:
        return ""
    fmt = tags.get("format") or "plain"
    if fmt == "inline":
        pre, suf = tags.get("prefix") or "#", tags.get("suffix") or ""
        return (tags.get("sep") or " ").join(f"{pre}{t}{suf}" for t in items)
    return (tags.get("sep") or ",").join(items)


def _prepare_payload(code: str, spec: dict, text: str, title: str, rel: str,
                     cfg: dict, recs: list, proj: dict) -> dict:
    """按规格把一篇成稿组装成可以直接粘贴的形态。不外发，纯组装。"""
    form = spec.get("body_form")
    if form == "tbd":            # 规格里写明「tbd 按 text 处理」；别把内部占位符
        form = "text"            # 送到界面（"正文 · tbd" 会被当成坏数据看）
    head = (title or "").strip()
    src = text
    if spec.get("title_inline"):
        # 这类渠道没有独立标题栏，标题要并进正文首行；而 markdown 正文的第一行往往
        # 就是同一个 H1，md2text/md2html 会把文字留着（只去掉 # 号）—— 不摘掉它就会
        # 「标题 / 标题 / 正文」。摘一行就好，别做全文去重（正文里重复提到标题是正常的）。
        src = re.sub(r"\A\s*#{1,6}[ \t]+[^\n]*\n?", "", text, count=1)
    if form == "markdown":
        body = src
    elif form == "html":
        body = md2html(src)
    else:                       # text / tbd：纯文本最不容易坏
        body = md2text(src)

    warn: list[str] = []
    if spec.get("title_inline") and head:
        body = (head + "\n\n" + body).strip()
    tmax = spec.get("title_max")
    if isinstance(tmax, int):
        if len(head) > tmax:
            warn.append(f"标题 {len(head)} 字，超过该渠道上限 {tmax}，已截断")
            head = head[:tmax]
    elif tmax == "tbd" and head:
        warn.append("该渠道的标题上限未核实 —— 发布前在编辑器里看一眼字数")
    if not head and not spec.get("title_inline"):
        warn.append("标题为空 —— 该渠道需要独立标题")

    tags = spec.get("tags") or {}
    tags_text = _tags_text(tags, proj, cfg)
    if tags.get("max") == "tbd" and tags_text:
        warn.append("标签上限未核实 —— 先少带几个，被拒再加")

    backlink = ""
    if spec.get("backlink"):
        backlink = (cfg.get("link_url") or "").strip() or _latest_public_url(recs, rel)
        if backlink:
            if form == "html":
                # 这里必须转义 + 认 scheme：backlink 来自 cfg.link_url（界面可填）
                # 或渠道响应里的 url（webhook 接收端可控），而这段会进 {@html} ——
                # 不转的话 `<img src=x onerror=…>` 是不用点击的 XSS。
                esc = _esc(backlink)
                body = (body.rstrip() + f'\n<p>原文：<a href="{esc}">{esc}</a></p>'
                        if _linkable(backlink)
                        else body.rstrip() + f"\n<p>原文：{esc}</p>")
            else:
                body = body.rstrip() + f"\n\n原文：{backlink}"
    return {"title": head, "body": body, "body_form": form or "text",
            "copy_as": spec.get("copy_as") or form or "text",
            "tags_text": tags_text, "backlink": backlink,
            "cover": spec.get("cover"), "warnings": warn,
            "editor_hint": spec.get("editor_hint") or "",
            "link_hint": spec.get("link_hint") or "",
            "api_status": (spec.get("api") or {}).get("status") or "unverified",
            "api_note": (spec.get("api") or {}).get("note") or "",
            "publish_url": spec.get("publish_url") or "",
            "login_url": spec.get("login_url") or "",
            "missing_placeholders": spec.get("missing_placeholders") or [],
            "steps": spec.get("steps") or _SEMI_STEPS, "dist": spec.get("dist")}


def _open_record(rows: list, code: str, rel: str) -> dict | None:
    """同渠道 + 同文件、还没回填的那条记录。反复点「备好」不该刷出一串待办。"""
    for r in reversed(rows or []):
        if r.get("platform") == code and r.get("path") == rel and r.get("state") == SEMI_STATE:
            return r
    return None


def prepare(slug: str, code: str, rel: str, title: str = "", force: str | None = None) -> dict:
    """备好一篇待人工发布的内容。**不外发**，写一条 state=prepared 的待办。"""
    if not isinstance(code, str) or code not in PUBLISHERS:
        # isinstance 那半是防 body 里塞 dict/list：`{"a":1} not in PUBLISHERS`
        # 会抛 TypeError（不可哈希）→ HTTP 500。调用方也该挡，这里是兜底。
        return {"ok": False, "error": f"未知渠道 {code!r}"}
    rel = _norm_rel(rel)
    if resolve_path(code, slug, force) != "semi":
        if "api" in paths_of(code):
            return {"ok": False, "error": f"「{PUBLISHERS[code]['name']}」当前走自动发布通路，"
                                         f"用发布按钮或 geo.py publish 即可"}
        # 两条路都没有（semi 规格是空 dict 之类）不能说成「走自动发布通路」——
        # 那是一句把人引向不存在的按钮的话。
        return {"ok": False, "error": f"「{PUBLISHERS[code]['name']}」没有任何可用通路"
                                     f"（既没有自动发布实现，也没有半自动规格）"}
    try:
        text, fname = _read_source(slug, rel)
    except (ValueError, FileNotFoundError, OSError) as e:
        return {"ok": False, "error": f"文件不可用：{rel}（{type(e).__name__}）"}
    proj = G.load_config(slug)
    spec = semi_spec(code, slug) or {}
    title = title or _title_of(text, fname)
    payload = _prepare_payload(code, spec, text, title, rel, _cfg(slug, code),
                              records(slug), proj)
    with G.project_lock(slug):
        rows = records(slug)
        prev = _open_record(rows, code, rel)
        if prev:                       # 幂等：同一条待办更新，不追加
            rid = prev.get("id") or record_id()
            prev.update({"id": rid, "at": G.now_iso(), "title": payload["title"],
                         "mode": "semi", "ok": True, "state": SEMI_STATE,
                         "note": "已备好（重新生成），待人工粘贴"})
            entry = prev
        else:
            rid = record_id()
            entry = {"at": G.now_iso(), "id": rid, "mode": "semi", "platform": code,
                     "platform_name": PUBLISHERS[code]["name"], "path": rel,
                     "title": payload["title"], "ok": True, "state": SEMI_STATE,
                     "url": "", "error": "",
                     "note": "已备好，待人工粘贴到 " + PUBLISHERS[code]["name"]}
            rows.append(entry)
        G.write_json(G.project_dir(slug) / "publish.json", rows[-200:])
    return {"ok": True, "mode": "semi", "id": rid, "code": code,
            "name": PUBLISHERS[code]["name"], "record": entry, **payload}


def record_manual(slug: str, code: str, rel: str, rid: str, url: str = "",
                  note: str = "", cancel: bool = False) -> dict:
    """人工发布完成后的回填（或作废）。

    回填的 URL 是 X 自动回链与分发清单的唯一来源 —— 跳过这一步，那条内容在系统里
    就永远停在「已备好」。
    """
    if not isinstance(code, str):
        return {"ok": False, "error": f"未知渠道 {code!r}"}
    rel = _norm_rel(rel) if rel else ""
    with G.project_lock(slug):
        rows = records(slug)
        ent = next((r for r in rows
                    if r.get("id") == rid and r.get("platform") == code
                    and (not rel or r.get("path") == rel)), None)
        if not ent:
            return {"ok": False, "error": f"找不到待回填的记录 {rid}（可能已回填或已作废）"}
        if cancel:
            # 已回填的记录不许作废：删掉的不只是这一条，还抽掉了 `_latest_public_url`
            # 的回链来源与分发依据（前端只在 prepared 那行给按钮，所以这是接口面的口子）。
            if ent.get("state") == "published":
                return {"ok": False, "error": "这条已经回填了公开链接，不能作废"}
            rows = [r for r in rows if r is not ent]
            G.write_json(G.project_dir(slug) / "publish.json", rows[-200:])
            return {"ok": True, "cancelled": True, "id": rid}
        url = (url or "").strip()
        if not url:
            return {"ok": False, "error": "回填需要一条公开链接"}
        # 只收 http(s)。这条 URL 是用户输入，会进 publish.json 并渲染成链接
        # （发布记录表、待发布清单），还会被 _latest_public_url 拿去当回链 ——
        # 存进去一个 javascript: 就等于在别人的待发布清单里放了一个可点的脚本。
        # 前端有 safeUrl 守卫，但守的是渲染；入口这里也要挡一道。
        if not re.match(r"^https?://", url, re.I):
            return {"ok": False, "error": "回填的链接要以 http:// 或 https:// 开头（公开页面地址）"}
        ent.update({"state": "published", "url": url, "at": G.now_iso(),
                    "note": note or "人工发布并回填", "error": ""})
        ticked: list[str] = []
        spec = (PUBLISHERS.get(code) or {}).get("semi") or {}
        if spec.get("dist"):
            # 顺带把蓝图里的分发清单勾上：原来那是另一条人工链（没 URL、不写 publish.json），
            # 两条并成一条，回链与分发记录就不会各说各话。
            try:
                text, _ = _read_source(slug, ent.get("path") or "")
            except (ValueError, FileNotFoundError, OSError):
                text = ""
            qids = sorted(set(re.findall(r"\bq\d{3}\b", (text or "")[:800])))
            if qids:
                dpath = G.project_dir(slug) / "distribution.json"
                dist = G.read_json(dpath, {}) or {}
                for q in qids:
                    dist.setdefault(q, {})[spec["dist"]] = G.now_iso()
                    ticked.append(q)
                G.write_json(dpath, dist)
        G.write_json(G.project_dir(slug) / "publish.json", rows[-200:])
    return {"ok": True, "id": rid, "url": url, "state": "published", "dist_ticked": ticked}


def publish(slug: str, code: str, rel: str, title: str = "", publish_now: bool = False,
            force: str | None = None) -> dict:
    if code not in PUBLISHERS:
        return {"ok": False, "error": f"未知渠道 {code}"}
    miss = missing_env(code)
    if miss:
        # 有半自动规格的渠道：缺凭证不是死路，补一句指路
        extra = ("；也可以走「备好并复制」的半自动通路（同一命令会打印备好的内容）"
                 if PUBLISHERS[code].get("semi") else "")
        return {"ok": False, "error": "缺凭证：" + "、".join(miss) + extra}
    # 通路判定放在读文件之前：半自动渠道压根没有可外发的实现，读一遍文件再报错是白读。
    _mode = resolve_path(code, slug, force)
    if _mode == "semi":
        return {"ok": False, "mode": "semi",
                "error": f"「{PUBLISHERS[code]['name']}」没有可用的自动发布通路"
                         f"（平台规则不允许代发，或没有公开接口）——"
                         f"请用「备好并复制」：同一命令会打印可直接粘贴的标题/正文/标签"}
    if _mode == "":
        return {"ok": False, "error": f"「{PUBLISHERS[code]['name']}」没有可用的发布通路"}
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
