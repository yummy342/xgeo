"""后台任务：让界面能触发管线命令并看到实时日志。

用**子进程**而不是线程跑命令——管线里有 requests、文件写入和模块级状态，
子进程隔离最干净，也不会因为一个任务崩掉整个服务。

每个任务一份日志文件，界面轮询增量拉取。同一项目同时只允许一个任务在跑，
避免 crawl 和 verify 抢同一份 audit.json。
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import geolib as G

JOBS_DIR = G.ROOT / ".jobs"
GEO_PY = G.ROOT / "scripts" / "geo.py"

# 界面上可触发的动作。参数经过白名单，不接受任意命令。
ACTIONS: dict[str, dict] = {
    "crawl":    {"label": "抓取站点", "args": ["--max-pages"], "desc": "重新抓取官网页面"},
    "audit":    {"label": "页面体检", "args": [], "desc": "六维打分"},
    "sample":   {"label": "AI 答案采样", "args": ["--limit", "--repeat", "--platforms"],
                 "desc": "打问题库到各平台", "slow": True},
    "bootstrap":{"label": "自动推导底座", "args": ["--skip-llm"],
                 "desc": "从官网正文推出品牌事实、竞品、问题库", "slow": True},
    "deliverables":{"label": "出三份交付物", "args": [], "desc": "诊断报告 / 优化方案 / 执行方案"},
    "plan":     {"label": "生成工单", "args": [], "desc": "诊断结果 → 带验收标准的工单"},
    "expand":   {"label": "拓词扩题", "args": ["--no-llm"],
                 "desc": "下拉词扩出真实需求候选题（入库需手动勾选）"},
    "blueprint":{"label": "生成建设蓝图", "args": [], "desc": "在哪些平台建、建什么内容、覆盖度"},
    "generate": {"label": "生成资产", "args": ["--asset", "--draft", "--draft-limit"],
                 "desc": "llms.txt / JSON-LD / 片段 / 大纲"},
    "lint":     {"label": "初稿风险检查", "args": [], "desc": "查 AI 初稿的编造风险"},
    "report":   {"label": "生成报告", "args": [], "desc": "Markdown + HTML"},
    "verify":   {"label": "自动验收", "args": ["--no-recrawl"], "desc": "重抓并判定工单是否闭环",
                 "slow": True},
    "deliver":  {"label": "打包交付", "args": [], "desc": "客户交付包"},
    "sample-sheet": {"label": "导出人工采样表", "args": [], "desc": "无 API 平台用"},
    "autopilot":{"label": "全自动引导", "args": ["--no-sample", "--limit", "--skip-llm"],
                 "desc": "推导底座 → 采样 → 工单 → 资产 → 三份交付物", "slow": True},
    "serve":    {"label": "跑完整周期", "args": ["--max-pages", "--limit", "--no-sample",
                                                 "--draft", "--draft-limit"],
                 "desc": "抓取→体检→采样→工单→资产→报告→验收→交付", "slow": True},
}

FLAG_ARGS = {"--no-recrawl", "--draft", "--no-sample", "--skip-llm", "--no-llm"}  # 布尔开关，无值

_lock = threading.Lock()
_running: dict[str, str] = {}   # slug -> job_id
_procs: dict[str, subprocess.Popen] = {}
_stopping: set[str] = set()     # 收到过停止信号、还没收尾的 job

# 任务 id 是 uuid4().hex[:12]。校验它是安全边界，不是格式洁癖：
# /api/job/<jid> 把用户输入原样喂进 _job_path，不拦的话 jid="../work/<slug>/geo"
# 会拼出 .jobs 之外的路径（读到 geo.json 里的渠道凭据），再经 stop() 的兜底
# 分支对任意 pid 发 SIGTERM。
_ID_RE = re.compile(r"[0-9a-f]{12}")


def is_valid_id(job_id: str) -> bool:
    return bool(job_id) and _ID_RE.fullmatch(job_id) is not None


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _log_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.log"


def _write(job: dict):
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    G.write_json(_job_path(job["id"]), job)


def get(job_id: str) -> dict | None:
    if not is_valid_id(job_id):
        return None
    p = _job_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:  # noqa: BLE001  损坏的 job 文件不该把轮询打成 500
        return None


def tail(job_id: str, offset: int = 0) -> tuple[str, int]:
    """返回 (增量文本, 新 offset)。界面按 offset 轮询，不重复拉。"""
    if not is_valid_id(job_id):
        return "", offset
    p = _log_path(job_id)
    if not p.exists():
        return "", offset
    # 按 offset 只读增量：整份读进来再切片的话，轮询一个长任务的日志
    # 每次都把整个文件过一遍内存，日志越大越慢。
    with p.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        if offset >= size:          # 含日志被重建（offset 落在文件外）的情况
            return "", size
        f.seek(offset)
        chunk = f.read()
    return chunk.decode("utf-8", "replace"), size


def _live_job(slug: str) -> str | None:
    """本项目正在跑的任务 id。调用方必须已持有 _lock。

    状态以 job 文件为准：服务重启后 _running 是空的，只能看文件。
    只看内存的话重启后并发保护会归零——reap_orphans 对 pid 存活的记录
    走 continue、不重新登记，于是同一项目能起出两个管线进程，
    同时写 audit.json / samples/*.jsonl。"""
    jid = _running.get(slug)
    if jid:
        j = get(jid)
        return jid if j and j["status"] == "running" else None
    for f in sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            j = json.loads(f.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if j.get("slug") == slug and j.get("status") == "running":
            _running[slug] = j["id"]   # 重新登记，之后走内存快路径
            return j["id"]
    return None


def running_for(slug: str) -> str | None:
    with _lock:
        return _live_job(slug)


def recent(slug: str | None = None, limit: int = 12) -> list[dict]:
    if not JOBS_DIR.exists():
        return []
    out = []
    for f in sorted(JOBS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            j = json.loads(f.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if slug and j.get("slug") != slug:
            continue
        j.pop("cmd", None)
        out.append(j)
        if len(out) >= limit:
            break
    return out


def start(slug: str, action: str, params: dict | None = None) -> dict:
    if action not in ACTIONS:
        raise ValueError(f"不支持的动作：{action}")

    spec = ACTIONS[action]
    cmd = [sys.executable, "-u", str(GEO_PY), action, "--slug", slug]
    for k, v in (params or {}).items():
        flag = k if k.startswith("--") else "--" + k
        if flag not in spec["args"]:
            continue
        if flag in FLAG_ARGS:
            if v:
                cmd.append(flag)
        elif v not in (None, "", []):
            cmd += [flag, str(v)]

    job = {
        "id": uuid.uuid4().hex[:12], "slug": slug, "action": action,
        "label": spec["label"], "status": "running",
        "started_at": G.now_iso(), "finished_at": None, "exit_code": None,
        "cmd": " ".join(cmd[2:]),
    }
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    # 检查-占位必须在同一把锁里。分开写的话，两个请求同时进来会双双通过
    # 「有没有在跑」的检查，起出两个任务抢同一份 audit.json。
    # 落盘也放进来：running_for 判的是 job 文件的状态，文件没写完就等于没占位。
    with _lock:
        if _live_job(slug):
            raise RuntimeError("该项目已有任务在运行，等它结束或先停止")
        _write(job)
        _running[slug] = job["id"]
    logf = _log_path(job["id"]).open("wb")
    logf.write(f"$ geo {' '.join(cmd[3:])}\n".encode())
    logf.flush()

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    try:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                                cwd=str(G.ROOT), env=env, start_new_session=True)
    except Exception as e:  # noqa: BLE001  Popen 挂了不能留下永远 running 的僵尸记录
        try:
            logf.close()
        except OSError:
            pass
        job["status"] = "failed"
        job["error"] = f"{type(e).__name__}: {e}"
        job["finished_at"] = G.now_iso()
        _write(job)
        with _lock:  # 放掉占位，否则这个项目再也起不了新任务
            if _running.get(slug) == job["id"]:
                _running.pop(slug, None)
        raise
    job["pid"] = proc.pid
    _write(job)
    with _lock:
        _procs[job["id"]] = proc

    def waiter():
        # 这个线程是唯一的收尾人：它一旦异常退出，job 就永远停在 running，
        # 并发保护会把整个项目堵死。所以每一步都不能让异常漏出去。
        code = None
        error = None
        try:
            code = proc.wait()
        except Exception as e:  # noqa: BLE001
            error = f"等待子进程失败：{type(e).__name__}: {e}"
        finally:
            try:
                logf.close()
            except OSError:
                pass
        with _lock:
            asked_to_stop = job["id"] in _stopping
            _stopping.discard(job["id"])
        try:
            j = get(job["id"]) or job
            # 用户点了停止就是「已停止」，别报成失败。只看退出码不够：
            # POSIX 被杀返回负码，Windows 的 TerminateProcess 返回的是正数。
            j["status"] = "done" if code == 0 else (
                "stopped" if asked_to_stop or (code and code < 0) else "failed")
            if error:
                j["error"] = error
            j["exit_code"] = code
            j["finished_at"] = G.now_iso()
            _write(j)
        finally:
            with _lock:
                if _running.get(slug) == job["id"]:
                    _running.pop(slug, None)
                _procs.pop(job["id"], None)

    threading.Thread(target=waiter, daemon=True).start()
    return job


def _terminate_tree(pid: int) -> bool:
    """结束整个进程组：任务会自己再起子进程（抓取、采样），只杀父进程会留下
    还在写文件的孤儿。Windows 没有进程组，退回单进程 terminate。"""
    if hasattr(os, "getpgid"):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            return True
        except Exception:  # noqa: BLE001
            pass
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:  # noqa: BLE001
        return False


def _kill_tree(pid: int) -> bool:
    """SIGTERM 之后的兜底。子进程忽略 SIGTERM 时只发信号杀不掉，
    stop() 却会报成功——界面显示「已停止」而它还在写文件。"""
    if hasattr(os, "killpg"):
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            return True
        except Exception:  # noqa: BLE001
            pass
    if hasattr(signal, "SIGKILL"):   # Windows 没有 SIGKILL
        try:
            os.kill(pid, signal.SIGKILL)
            return True
        except Exception:  # noqa: BLE001
            return False
    try:                             # Windows 上 os.kill 走 TerminateProcess，即最强手段
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:  # noqa: BLE001
        return False


def stop(job_id: str) -> bool:
    if not is_valid_id(job_id):
        return False
    with _lock:
        proc = _procs.get(job_id)
    if proc:
        with _lock:
            _stopping.add(job_id)   # 让收尾线程知道这是用户主动停的，不是自己崩的
        if not _terminate_tree(proc.pid):
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        # 不在这里等：stop 跑在 HTTP 请求线程上，同步等 N 秒等于把界面卡住。
        # 改成延迟强杀——给了体面退出的时间，超时还没走说明它忽略 SIGTERM，
        # 而只发信号是杀不掉的：界面会显示「已停止」而它还在写文件，
        # _running 也不释放，这个项目会被「已有任务在运行」永久挡住。
        def _kill_if_alive():
            if proc.poll() is None:   # 已经退了就别碰，pid 可能已被复用
                _kill_tree(proc.pid)

        killer = threading.Timer(5.0, _kill_if_alive)
        killer.daemon = True
        killer.start()
        return True
    # 服务重启后 _procs 是空的，按 job 文件里落的 pid 兜底杀整组
    job = get(job_id)
    pid = (job or {}).get("pid")
    if not pid or job.get("status") != "running":
        return False
    if not _terminate_tree(pid):
        return False
    job["status"] = "stopped"  # 本进程没有 waiter，自己回写，免得列表里永远 running
    job["finished_at"] = G.now_iso()
    _write(job)
    return True


def reap_orphans() -> int:
    """启动时回收孤儿 job：上次服务还在跑时留下的 status=running 记录，
    进程已死就回写 interrupted——不回收的话并发保护会永远挡住新项目。"""
    if not JOBS_DIR.exists():
        return 0
    reaped = 0
    for f in JOBS_DIR.glob("*.json"):
        try:
            job = json.loads(f.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if job.get("status") != "running":
            continue
        pid = job.get("pid")
        if not pid and time.time() - f.stat().st_mtime < 60:
            continue  # start() 先落 running 再补 pid，毫秒级窗口内别误杀刚启动的 job
        alive = False
        if pid:
            try:
                os.kill(pid, 0)
                alive = True
            except PermissionError:
                alive = True   # 进程在，只是不属于本用户
            except OSError:
                # Windows 上死 pid 抛的是 OSError(WinError 87)，不是
                # ProcessLookupError。只认后者的话记录原地留在 running，
                # 并发保护永久挡住这个项目，看板自己都起不来。
                alive = False
        if alive:
            continue
        job["status"] = "interrupted"
        job["finished_at"] = G.now_iso()
        _write(job)
        reaped += 1
    if reaped:
        G.info(f"回收了 {reaped} 个中断的任务记录")
    return reaped


def prune_jobs(keep_days: int = 30) -> int:
    """清掉过期的任务记录与日志。

    任务 json 与 log 原来永不删除，而列表接口每次都要 stat + 读所有 json，
    历史攒多了界面会一轮比一轮慢。只删「已结束且超过保留期」的，
    还在跑的绝不碰。
    """
    if not JOBS_DIR.exists():
        return 0
    cutoff = time.time() - keep_days * 86400
    removed = 0
    for f in JOBS_DIR.glob("*.json"):
        try:
            if f.stat().st_mtime >= cutoff:
                continue
            job = json.loads(f.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if job.get("status") == "running":
            continue
        _log_path(f.stem).unlink(missing_ok=True)
        f.unlink(missing_ok=True)
        removed += 1
    if removed:
        G.info(f"清理了 {removed} 条过期任务记录（保留 {keep_days} 天）")
    return removed
