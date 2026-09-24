"""GEO 工具箱共用模块：路径、配置、HTTP、正文抽取。

只依赖 requests / bs4 / lxml（标准 macOS Python 环境已有），不引入 yaml/jinja2。
"""

from __future__ import annotations

try:
    import fcntl          # POSIX：上游原本只有这条
except ImportError:       # Windows：改用 msvcrt 做等价的文件锁
    fcntl = None
    import msvcrt
import json
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"


def load_env(path: Path | None = None):
    """读项目根目录的 .env（已 gitignore）。已存在的环境变量优先，不覆盖。"""
    p = path or (ROOT / ".env")
    if not p.exists():
        return
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


load_env()

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 geo-skill/1.0"
)
# 403/406 回退用：不带 geo-skill 标记的纯浏览器 UA。很多 WAF 规则只拦
# 「带工具标记的 UA」，回退能区分「拦工具」还是「拦 IP」，这本身是诊断信号。
UA_BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------- 基础工具


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def slugify(text: str) -> str:
    text = re.sub(r"^https?://", "", (text or "").strip().lower())
    text = re.sub(r"[^a-z0-9一-鿿]+", "-", text).strip("-")
    return text[:48] or "project"


# 中文 Windows 的控制台默认 GBK，打印中文会变乱码、
# 打印 emoji 会直接 UnicodeEncodeError。显式切到 UTF-8，
# 省得用户每次都要设 PYTHONIOENCODING=utf-8。
# 失败不致命（有些环境不支持 reconfigure），静默跳过。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError, OSError):
        pass


def die(msg: str, code: int = 1):
    print(f"[geo] 错误：{msg}", file=sys.stderr)
    sys.exit(code)


def info(msg: str):
    print(f"[geo] {msg}", file=sys.stderr)


# ---------------------------------------------------------------- 项目目录

SLUG_OK = re.compile(r"^[a-z0-9一-鿿][a-z0-9一-鿿-]{0,47}$")


def project_dir(slug: str) -> Path:
    if not SLUG_OK.match(slug or ""):
        die(f"非法项目标识：{slug!r}")
    return WORK / slug


@contextmanager
def project_lock(slug: str):
    """项目级跨进程锁：load-modify-write 操作必须走它。

    POSIX 用 fcntl.flock；Windows 没有 fcntl，改用 msvcrt.locking 锁同一文件的首字节。
    语义等价（都是跨进程排它锁），只是 Windows 的锁记在字节范围上而不是整个 fd 上。
    """
    d = project_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    with _open_lock_file(d / ".lock") as fd:
        try:
            if fcntl:
                fcntl.flock(fd, fcntl.LOCK_EX)
            else:
                _win_lock(fd)
            yield
        finally:
            if fcntl:
                fcntl.flock(fd, fcntl.LOCK_UN)
            else:
                _win_unlock(fd)


def _open_lock_file(path, timeout: float = 10.0):
    """打开锁文件。Windows 上要重试。

    msvcrt 的锁记在字节区间上：另一个句柄持有首字节时，`open("w")` **这一步本身**
    就抛 PermissionError（不是加锁那一步、也轮不到这里的轮询）。实测同进程 8 线程
    并发走 publish.json 的读-改-写，只有 1 个成功、其余 7 个裸抛 —— 落到 HTTP 层
    就是 500。POSIX 的 flock 没这个问题，所以只在 Windows 上看得见。
    """
    end = time.monotonic() + timeout
    while True:
        try:
            return path.open("w")
        except PermissionError:
            if time.monotonic() >= end:
                die(f"等锁超时：{path} 一直被别的进程占着")
            time.sleep(0.05)


def _win_lock(fd):
    """Windows 侧的加锁。msvcrt 没有 flock 那种无限等待。

    LK_LOCK 大约 10 秒后抛 OSError，而长任务（大采样表导入要几十秒）持锁时
    等待方拿到的是裸 traceback 而不是排队 —— 改成自己轮询 LK_NBLCK。
    锁区间固定为首字节 [0,1)，解锁必须用同一区间。
    """
    fd.write("x")        # 让锁范围落在文件内（open("w") 会把文件截成 0 字节）
    fd.flush()
    fd.seek(0)
    while True:
        try:
            msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            time.sleep(0.05)


def _win_unlock(fd):
    try:
        fd.seek(0)       # 必须和加锁同一区间：seek 位置不对等于根本没解锁
        msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


def load_config(slug: str) -> dict:
    p = project_dir(slug) / "geo.json"
    if not p.exists():
        die(f"找不到项目配置 {p}，先运行：python3 scripts/geo.py init --url <网址>")
    return json.loads(p.read_text("utf-8"))


def has_site(cfg: dict) -> bool:
    """项目有没有自有网站。无站点项目（电商商品、线下品牌、小程序等）同样能做 GEO：
    抓取/体检/站内资产这几步不适用，但采样、竞品、阵地、内容、验收全都照常。
    判据只看 brand.site 是否为空——不引入第二个真相源。"""
    return bool((cfg.get("brand") or {}).get("site", "").strip())


def _atomic_write(path: Path, write):
    """先写同目录下的临时文件再 os.replace：中断时目标文件要么是旧内容、
    要么是新内容，不会是半截。这几个文件都是整套流程的真相源，半截就等于丢掉一期。

    临时名带随机串而不是 pid——同一进程里两个线程写同一个文件时 pid 会撞名。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        write(tmp)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def save_config(slug: str, cfg: dict):
    """写配置前先备份。geo.json 里是一期的人工投入（问题库、竞品、口径），
    被误覆盖的代价远大于留几个备份文件。"""
    p = project_dir(slug) / "geo.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        bak = p.parent / ".geo.bak"
        bak.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (bak / f"geo-{stamp}.json").write_text(p.read_text("utf-8"), "utf-8")
        old = sorted(bak.glob("geo-*.json"))
        for f in old[:-10]:
            f.unlink()
    _atomic_write(p, lambda t: t.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8"))


def write_json(path: Path, data):
    _atomic_write(path, lambda t: t.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), "utf-8"))


def read_json(path: Path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text("utf-8"))
    except json.JSONDecodeError:
        info(f"警告：{p} 已损坏，使用默认值")
        return default


def write_jsonl(path: Path, rows):
    def dump(tmp: Path):
        with tmp.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    _atomic_write(path, dump)


def read_jsonl(path: Path):
    p = Path(path)
    if not p.exists():
        return []
    out, bad = [], 0
    # 必须按 "\n" 切，不能用 splitlines()：后者还会在 U+2028/U+2029/U+0085/\v/\f
    # 处断行，而 json.dumps 不转义这些字符，抓到含 U+2028 的页面就会把一条记录
    # 劈成两半 → JSONDecodeError，整期体检中断。
    for line in p.read_text("utf-8").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # 一行坏（进程被杀导致的末尾截断、磁盘写坏）不该让整期工作全灭，
            # 跳过它并留下痕迹，剩下的记录照常参与统计
            bad += 1
    if bad:
        info(f"警告：{p} 有 {bad} 行损坏，已跳过")
    return out


# ---------------------------------------------------------------- HTTP

MAX_BYTES = 4_000_000  # 单页最多读 4MB，防止一头扎进安装包/大文件把管线拖死

# 一看就不是网页的路径，直接跳过（安装包、媒体、静态资源等）
SKIP_EXT = re.compile(
    r"\.(zip|gz|tgz|bz2|7z|rar|dmg|pkg|exe|msi|apk|ipa|deb|rpm|bin|iso"
    r"|mp4|mov|avi|mkv|mp3|wav|flac|png|jpe?g|gif|webp|svg|ico|bmp|tiff"
    r"|woff2?|ttf|eot|css|js|csv|xlsx?|docx?|pptx?|pdf)(\?|$)",
    re.I,
)
SKIP_PATH = re.compile(r"/(downloads?|dl|releases?|assets|static|cdn)/", re.I)


def is_fetchable(url: str) -> bool:
    if SKIP_EXT.search(url) or SKIP_PATH.search(url):
        return False
    tail = url.rstrip("/").rsplit("/", 1)[-1].lower()
    return tail not in {"download", "dl"}



def fetch(url: str, timeout: int = 12, retries: int = 1, ua: str | None = None) -> dict:
    """返回 {url, final_url, status, html, x_robots_tag, elapsed, error}。只读网页，且有体积上限。
    ua 可换成 AI 爬虫的 User-Agent 做差异探测（WAF/CDN 是否单独拦 AI 爬虫）。"""
    if not is_fetchable(url):
        return {"url": url, "final_url": url, "status": 0, "html": "", "content_type": "",
                "x_robots_tag": "", "elapsed": 0, "error": "跳过：不是网页（下载/媒体/静态资源）"}
    last = ""
    # 调用方没指定 UA 时，默认 UA 被 403/406 拦截后换纯浏览器 UA 再试一轮：
    # 站长在自己站上做诊断，绕过自家 WAF 的工具规则是合理的，且结果会标注出来
    ua_plan = [ua or UA] + ([UA_BROWSER] if ua is None else [])
    for ua_idx, cur_ua in enumerate(ua_plan):
      for attempt in range(retries + 1):
        try:
            t0 = time.time()
            headers = {"User-Agent": cur_ua, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
            if ua_idx > 0:
                headers["Accept"] = ("text/html,application/xhtml+xml,application/xml;"
                                     "q=0.9,image/avif,image/webp,*/*;q=0.8")
            r = requests.get(
                url,
                timeout=timeout,
                headers=headers,
                allow_redirects=True,
                stream=True,
            )
            # 5xx / 429 多是临时故障（服务端抖动、限流），值得按异常同样的节奏重试
            if (r.status_code >= 500 or r.status_code == 429) and attempt < retries:
                r.close()
                time.sleep(1.5)
                continue
            # 默认 UA 被拦（403/406 是 WAF 的典型手势）→ 跳出内层，换浏览器 UA
            if r.status_code in (403, 406) and ua_idx + 1 < len(ua_plan):
                r.close()
                last = f"HTTP {r.status_code}（默认 UA 被拦）"
                break
            ctype = r.headers.get("Content-Type", "")
            xrobots = r.headers.get("X-Robots-Tag", "")
            if ctype and not any(k in ctype.lower() for k in ("html", "text/plain", "xml")):
                r.close()
                return {"url": url, "final_url": r.url, "status": r.status_code, "html": "",
                        "content_type": ctype, "x_robots_tag": xrobots,
                        "elapsed": round(time.time() - t0, 2),
                        "error": f"跳过非网页内容（{ctype.split(';')[0]}）"}
            chunks, size = [], 0
            try:
                for chunk in r.iter_content(65536):
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_BYTES:
                        break
            finally:
                # 中途断流（ChunkedEncodingError、读超时）时也要归还连接：
                # 同函数其他分支都显式 close，只有这条异常路径漏了。批量抓取时
                # 同一 host 反复断流会攒下不还池的连接，连接池复用被破坏。
                r.close()
            raw = b"".join(chunks)
            enc = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else None
            if not enc:
                m = re.search(rb'charset=["\']?([\w\-]+)', raw[:4000], re.I)
                enc = m.group(1).decode("ascii", "ignore") if m else "utf-8"
            return {
                "url": url,
                "final_url": r.url,
                "status": r.status_code,
                "html": raw.decode(enc, "replace"),
                "content_type": ctype,
                "x_robots_tag": xrobots,
                "elapsed": round(time.time() - t0, 2),
                # error 是文档化的失败通道，HTTP 错误却让它空着的话调用方只能
                # 靠 status 分辨，已有两处踩到：crawl 把 500/404 的错误页当快照
                # 存进 evidence/，geo init 用 404 页的 <title> 推断品牌名。
                "error": f"HTTP {r.status_code}" if r.status_code >= 400 else None,
                "ua_fallback": ua_idx > 0,
            }
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            if attempt < retries:
                time.sleep(1.5)
    return {"url": url, "final_url": url, "status": 0, "html": "", "content_type": "",
            "x_robots_tag": "", "elapsed": 0, "error": last}


def fetch_text(url: str, timeout: int = 8, max_bytes: int = 8_000_000,
               retries: int = 2) -> str | None:
    """站点级小文件（robots.txt / llms.txt / sitemap）的读取。

    带体积上限：大站的 sitemap 常有几十 MB，不带 stream 会把整个 body 读进
    内存，apparent_encoding 还要对全量字节跑一遍编码探测。

    三种返回要分清（这是本函数存在的全部理由）：
      200  → 文件内容
      404  → ""，站点确实没有这个文件
      其余（超时 / 连接错 / 5xx / 403）→ None，「这次没拿到」，不下任何结论

    以前失败也返回 ""，调用方分不出「没有」和「没抓到」，一次抖动就写成
    「站点没有 /llms.txt」这种假 P2。robots.txt 那侧早已改用 fetch 区分
    （见 crawl.run 里的注释），其余三个调用点一直没跟上——2026-09-24 实测
    llms.txt 在线上 200 / 2849 字节，audit 却报「没有 /llms.txt」。
    404 是真不存在，不重试；其余非 200 与网络错按退避重试。
    """
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": UA}, stream=True)
            try:
                if r.status_code == 404:
                    return ""
                if r.status_code != 200:
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                raw = b""
                for chunk in r.iter_content(65536):
                    raw += chunk
                    if len(raw) >= max_bytes:
                        break
            finally:
                r.close()
            # header 声明的 charset 优先，没有就找正文里的声明，最后退回 utf-8。
            enc = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else None
            if not enc:
                m = re.search(rb'charset=["\']?([\w\-]+)', raw[:4000], re.I)
                enc = m.group(1).decode("ascii", "ignore") if m else "utf-8"
            return raw.decode(enc, "replace")
        except Exception:  # noqa: BLE001
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    return None


# ---------------------------------------------------------------- robots.txt
# 按 RFC 9309 语义解析，而不是逐行正则：三个最容易误判的点——
#   1. 多个 User-agent 行共享同一组规则（组内第一个 UA 后面的会被逐行正则漏掉）
#   2. 具体 UA 组存在时通配符组整组失效（specificity，不看先后顺序）
#   3. 规则按最长路径匹配定胜负，同长时 Allow 胜出；支持 * 与 $ 通配符
# 所以「User-agent: * / Disallow: /」会封掉所有没有专属组的 AI 爬虫，
# 而「User-agent: GPTBot / Allow: /」会让 GPTBot 无视通配符组里的任何 Disallow。


def robots_parse(txt: str) -> list[dict]:
    """解析成 [{agents: [ua...], rules: [(allow, path)]}]。空 Disallow 值 = 全放行，不算规则。"""
    groups: list[dict] = []
    cur = None
    last_was_agent = False
    for raw in (txt or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if cur is None or not last_was_agent:
                cur = {"agents": [], "rules": []}
                groups.append(cur)
            cur["agents"].append(value.lower())
            last_was_agent = True
        elif field in ("allow", "disallow"):
            last_was_agent = False
            if cur is not None and value:
                cur["rules"].append((field == "allow", value))
        else:
            last_was_agent = False
    return groups


def _robots_rule_rx(pattern: str) -> re.Pattern:
    rx = re.escape(pattern).replace(r"\*", ".*")
    if rx.endswith(r"\$"):
        rx = rx[:-2] + "$"
    return re.compile("^" + rx)


def robots_decision(groups: list[dict], ua: str, path: str) -> tuple[bool, str | None]:
    """某个爬虫（产品名，如 'GPTBot'）能否抓某路径。返回 (允许?, 命中的规则文本)。"""
    ua_l = (ua or "").lower()
    specific, spec_len, wildcard = None, -1, None
    for g in groups:
        for a in g["agents"]:
            if a == "*":
                if wildcard is None:
                    wildcard = g
            elif a == ua_l and len(a) > spec_len:
                # RFC 9309 要求产品名整体匹配（大小写不敏感）。原来是双向子串：
                # User-agent: Baiduspider-image 的组会命中 Baiduspider，又因为
                # 名字更长而抢先，于是「只封图片爬虫」被读成「整站封禁」——
                # 客户报告里出现错误的 P0，而且那条工单永远无法闭环。
                # 需要覆盖派生爬虫时，在 crawl.AI_BOTS 里显式列出。
                specific, spec_len = g, len(a)
    g = specific or wildcard
    if not g:
        return True, None
    path = path or "/"
    match_len, allowed, rule = -1, True, None
    for allow, pat in g["rules"]:
        if _robots_rule_rx(pat).match(path):
            plen = len(pat)
            # 最长匹配优先；同长时 Allow 胜出
            if plen > match_len or (plen == match_len and allow and not allowed):
                match_len, allowed = plen, allow
                rule = ("Allow: " if allow else "Disallow: ") + pat
    return allowed, rule


def same_site(a: str, b: str) -> bool:
    ha, hb = urlparse(a).netloc.lower(), urlparse(b).netloc.lower()
    ha, hb = ha.removeprefix("www."), hb.removeprefix("www.")
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)


# 跟踪参数：同一个页面挂不同参数会被当成多个 URL 重复抓，先剥掉
TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "msclkid", "igshid", "mc_cid", "mc_eid",
                   "ref", "spm", "scm"}


def normalize_url(base: str, href: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    u = urljoin(base, href)
    u, _, _ = u.partition("#")
    parts = urlparse(u)
    if parts.query:
        qs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
              if not (k.lower().startswith("utm_") or k.lower() in TRACKING_PARAMS)]
        u = urlunparse(parts._replace(query=urlencode(qs)))
    return u


# ---------------------------------------------------------------- 正文抽取

_DROP_TAGS = ["script", "style", "noscript", "svg", "iframe", "form", "template"]
_BOILER = re.compile(r"(nav|header|footer|sidebar|menu|breadcrumb|cookie|banner|advert)", re.I)


def parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "lxml")


def main_text(soup: BeautifulSoup) -> str:
    # 恰好一个 <article> 才当正文容器；多个 <article>（列表页/分节页）时取 <main>
    # 整体，否则只保留第一节，数字/步骤/FAQ 全部丢失，正文评分被严重低估。
    articles = soup.find_all("article")
    body = (articles[0] if len(articles) == 1 else None) \
        or soup.find("main") or soup.body or soup
    clone = BeautifulSoup(str(body), "lxml")
    for t in clone(_DROP_TAGS):
        t.decompose()
    for t in clone.find_all(attrs={"class": _BOILER}):
        t.decompose()
    for t in clone.find_all(attrs={"id": _BOILER}):
        t.decompose()
    text = clone.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


CJK = re.compile(r"[一-鿿]")
KANA = re.compile(r"[぀-ヿ]")


def cjk_ratio(text: str) -> float:
    """中文字符占「中文字符 + 英文单词」的比例，用来判断这页到底是中文页还是英文页。"""
    cjk = len(CJK.findall(text))
    latin = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", text))
    total = cjk + latin
    return round(cjk / total, 3) if total else 0.0


def page_language(text: str, lang_attr: str = "") -> str:
    """返回 zh / ja / en / mixed / unknown。html lang 属性只作参考，正文说了算。"""
    if len(text) < 80:
        la = (lang_attr or "").lower()
        return ("zh" if la.startswith("zh") else "en" if la.startswith("en")
                else "ja" if la.startswith("ja") else "unknown")
    # 日文：假名够多且占（假名 + 汉字）比例明显，避免把引用了一两个日语词的中文页判成 ja
    kana = len(KANA.findall(text))
    if kana >= 5 and kana / (kana + len(CJK.findall(text))) > 0.2:
        return "ja"
    r = cjk_ratio(text)
    return "zh" if r >= 0.5 else "en" if r <= 0.1 else "mixed"


def word_count(text: str) -> int:
    """中英日混排统一折算成「词」：CJK 1.6 字算 1 词（接近中英信息密度比）。
    假名并入 CJK 统计：假名为主的日文页不算的话词数会被严重低估。"""
    cjk = len(CJK.findall(text)) + len(KANA.findall(text))
    latin = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", text))
    return int(cjk / 1.6 + latin)


# 内容页判据：「这页是不是给人读的内容页」。抓取层用它决定槽位怎么分，
# 审计层用它决定算不算内容质量——一个判据两处共用，不然阈值改一处漏一处。
FUNC_PAGE_PATH = re.compile(
    r"/(login|signin|signup|register|cart|checkout|account|auth|contact)(/|$)", re.I)
MIN_CONTENT_WORDS = 120

REASON_NON_DOCUMENT = "non_document"
REASON_SPA_SHELL = "spa_shell"

NON_CONTENT_REASON_LABEL = {
    REASON_NON_DOCUMENT: "非网页内容（API / 文件端点）",
    REASON_SPA_SHELL: "SPA 外壳（静态 HTML 无正文）",
}


def non_content_reason(page: dict) -> str:
    """非内容页的原因；是内容页返回空串。

    1) status 非 200 的页不在这里判：它们走「抓取失败」那条路，原因不同，
       混进来会把「这次没抓到」静默改写成「这页不是内容页」。
    2) non_document：响应不是网页（application/json 这类 API 端点）。
       AI 读 JSON 比读 HTML 更顺，这是资产不是缺陷，所以不给 issue_codes。
    3) spa_shell：静态 HTML 里没有正文（纯前端渲染），curl 拿到的是空壳，
        AI 抓取器同样读不到——这条是真缺陷，调用方据此出工单。
    4) 登录/注册/购物车这类功能页内容少属正常，不算非内容页，仍走原有的
       LOW_CONTENT_PAGE 口径。
    """
    if (page.get("status") or 0) != 200:
        return ""
    ctype = page.get("content_type") or ""
    if ctype and not any(k in ctype.lower() for k in ("html", "text/plain", "xml")):
        return REASON_NON_DOCUMENT
    if (page.get("word_count") or 0) >= MIN_CONTENT_WORDS:
        return ""
    if FUNC_PAGE_PATH.search(urlparse(page.get("url") or "").path):
        return ""
    return REASON_SPA_SHELL


def strip_comments(text: str) -> str:
    """去掉 <!-- --> 注释，保持 re.sub(r"<!--.*?-->", "", text, re.S) 的语义。

    不用那个正则：输入里塞满 `<!--` 而结尾没有 `-->` 时，每个起始位置都要一路
    扫到末尾才有结论，复杂度是 O(n²)。预检接口吃的正是用户粘贴的正文，
    一条请求就能把服务拖住。这里是线性扫描。"""
    if "<!--" not in text:
        return text
    out, i = [], 0
    while True:
        j = text.find("<!--", i)
        if j < 0:
            out.append(text[i:])
            return "".join(out)
        k = text.find("-->", j + 4)
        if k < 0:
            # 没有闭合的注释，正则那版也原样保留（从这里到结尾都不动）
            out.append(text[i:])
            return "".join(out)
        out.append(text[i:j])
        i = k + 3


def jsonld(soup: BeautifulSoup) -> list:
    out = []
    for tag in soup.find_all("script", type=lambda v: v and "ld+json" in v):
        try:
            data = json.loads(tag.string or "{}")
        except Exception:  # noqa: BLE001
            continue
        out.extend(data if isinstance(data, list) else [data])
    return out


def jsonld_types(blocks: list) -> list[str]:
    types = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        t = b.get("@type")
        if isinstance(t, list):
            types.extend(str(x) for x in t)
        elif t:
            types.append(str(t))
        for sub in b.get("@graph", []) or []:
            if isinstance(sub, dict) and sub.get("@type"):
                st = sub["@type"]
                types.extend(st if isinstance(st, list) else [st])
    return sorted(set(types))
