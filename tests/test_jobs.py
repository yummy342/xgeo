import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import geolib as G
import jobs as J


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_dir = J.JOBS_DIR
        J.JOBS_DIR = Path(self.tmp.name) / ".jobs"
        self.addCleanup(setattr, J, "JOBS_DIR", self._orig_dir)
        J._running.clear()
        J._procs.clear()
        J._stopping.clear()
        self.addCleanup(J._running.clear)
        self.addCleanup(J._procs.clear)
        self.addCleanup(J._stopping.clear)

    def _settle(self, job_id, timeout=5):
        """等收尾线程写完终态。

        不等的话 teardown 清临时目录会撞上正在写文件的 waiter，
        在 Windows 上表现为「目录不是空的」——偶发红，跟被测代码无关。"""
        deadline = time.time() + timeout
        while time.time() < deadline and (J.get(job_id) or {}).get("status") == "running":
            time.sleep(0.02)

    def _write_job(self, job_id, **kw):
        job = {"id": job_id, "slug": "x", "action": "audit", "label": "页面体检",
               "status": "running", "started_at": "2026-07-28T10:00:00",
               "finished_at": None, "exit_code": None}
        job.update(kw)
        J.JOBS_DIR.mkdir(parents=True, exist_ok=True)
        (J.JOBS_DIR / f"{job_id}.json").write_text(json.dumps(job), "utf-8")
        return job

    def test_reap_orphans_dead_pid(self):
        self._write_job("deadbeef0001", pid=999999)
        with mock.patch.object(J.os, "kill", side_effect=ProcessLookupError):
            n = J.reap_orphans()
        self.assertEqual(n, 1)
        j = J.get("deadbeef0001")
        self.assertEqual(j["status"], "interrupted")
        self.assertTrue(j["finished_at"])

    def test_reap_orphans_treats_plain_oserror_as_dead(self):
        """POSIX 上死 pid 抛 ProcessLookupError，Windows 上抛的是普通 OSError
        (WinError 87)。只 catch 前者的写法在 Windows 上会让记录原地留在 running，
        并发保护永久挡住这个项目——看板连启动都会被这条炸掉。"""
        self._write_job("deadbeef0002", pid=999999)
        with mock.patch.object(J.os, "kill", side_effect=OSError(22, "Invalid argument")):
            n = J.reap_orphans()
        self.assertEqual(n, 1)
        self.assertEqual(J.get("deadbeef0002")["status"], "interrupted")

    def test_reap_orphans_live_pid_untouched(self):
        self._write_job("deadbeef0003", pid=os.getpid())
        n = J.reap_orphans()
        self.assertEqual(n, 0)
        self.assertEqual(J.get("deadbeef0003")["status"], "running")

    def test_reap_orphans_skips_non_running(self):
        self._write_job("deadbeef0004", status="done", pid=999999)
        with mock.patch.object(J.os, "kill", side_effect=ProcessLookupError):
            n = J.reap_orphans()
        self.assertEqual(n, 0)
        self.assertEqual(J.get("deadbeef0004")["status"], "done")

    def test_start_popen_failure_marks_failed(self):
        with mock.patch.object(J.subprocess, "Popen", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                J.start("x", "audit")
        jobs = list(J.JOBS_DIR.glob("*.json"))
        self.assertEqual(len(jobs), 1)
        j = json.loads(jobs[0].read_text("utf-8"))
        self.assertEqual(j["status"], "failed")
        self.assertIn("boom", j["error"])
        self.assertTrue(j["finished_at"])
        self.assertNotIn(j["id"], J._procs)
        self.assertNotIn("x", J._running)

    def test_start_writes_pid(self):
        proc = mock.Mock()
        proc.pid = 424242
        proc.wait.return_value = 0
        with mock.patch.object(J.subprocess, "Popen", return_value=proc):
            job = J.start("x", "audit")
        self._settle(job["id"])
        j = J.get(job["id"])
        self.assertEqual(j["pid"], 424242)

    def test_stop_fallback_by_pid(self):
        """服务重启后 _procs 是空的，只能按 job 文件里落的 pid 兜底杀。

        杀进程本身用真的子进程验（见 test_terminate_tree_kills_a_real_process），
        这里只验 stop 的流程：读 pid、杀、回写状态。"""
        self._write_job("deadbeef0005", pid=31337)
        with mock.patch.object(J, "_terminate_tree", return_value=True) as k:
            ok = J.stop("deadbeef0005")
        self.assertTrue(ok)
        k.assert_called_once_with(31337)
        j = J.get("deadbeef0005")
        self.assertEqual(j["status"], "stopped")
        self.assertTrue(j["finished_at"])

    def test_stop_returns_false_when_kill_fails(self):
        self._write_job("deadbeef0006", pid=31337)
        with mock.patch.object(J, "_terminate_tree", return_value=False):
            self.assertFalse(J.stop("deadbeef0006"))
        self.assertEqual(J.get("deadbeef0006")["status"], "running")

    def test_terminate_tree_kills_a_real_process(self):
        """真起一个子进程再杀，两个平台都要过。

        以前这里写死 os.getpgid/os.killpg——Windows 没有这两个接口，
        stop() 直接掉进 except 返回 False，界面上「停止」按钮点了没反应。"""
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True)
        try:
            self.assertTrue(J._terminate_tree(proc.pid))
            self.assertIsNotNone(proc.wait(timeout=15))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=15)

    def test_reap_skips_young_job_without_pid(self):
        self._write_job("deadbeef0007")  # 刚落盘、还没来得及补 pid
        self.assertEqual(J.reap_orphans(), 0)
        self.assertEqual(J.get("deadbeef0007")["status"], "running")

    def test_reap_old_job_without_pid(self):
        p = J.JOBS_DIR / "deadbeef0008.json"
        self._write_job("deadbeef0008")
        old = 1700000000  # 2023 年，远超 60s 窗口
        os.utime(p, (old, old))
        self.assertEqual(J.reap_orphans(), 1)
        self.assertEqual(J.get("deadbeef0008")["status"], "interrupted")

    def test_start_is_not_a_check_then_set_race(self):
        """两个请求同时进来，只许起一个任务。

        检查（有没有在跑）和占位（记下自己在跑）分开写的话，两边会双双通过
        检查，起出两个进程抢同一份 audit.json。这里让 Popen 慢一拍，
        把那个窗口拉大——没有锁的话这条必红。"""
        started = []

        class SlowProc:
            def __init__(self, *a, **kw):
                time.sleep(0.3)
                self.pid = 4242
                started.append(1)

            def wait(self):
                return 0

        results = []

        def run():
            try:
                results.append(J.start("race", "audit"))
            except RuntimeError as e:
                results.append(e)

        with mock.patch.object(J.subprocess, "Popen", SlowProc):
            threads = [threading.Thread(target=run) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        ok = [r for r in results if isinstance(r, dict)]
        self.assertEqual(len(ok), 1, f"并发起了 {len(ok)} 个任务：{results}")
        self.assertEqual(len(started), 1, "起了两个子进程")

    def test_waiter_releases_the_slot_even_if_finalizing_fails(self):
        """收尾线程一旦异常退出，job 永远停在 running，这个项目就再也起不了
        新任务。所以收尾出错也必须放掉占位。"""
        proc = mock.Mock()
        proc.pid = 424242
        proc.wait.return_value = 0
        done = threading.Event()
        real_write = J._write

        def flaky_write(job):
            real_write(job)
            if job.get("status") == "done":
                done.set()
                raise OSError("disk full")

        # 收尾线程抛出的异常正是这条测试的输入，收住它，别把 traceback 刷进测试输出
        hooked = []
        orig = threading.excepthook
        threading.excepthook = lambda a: hooked.append(a.exc_type)
        self.addCleanup(setattr, threading, "excepthook", orig)

        with mock.patch.object(J.subprocess, "Popen", return_value=proc), \
             mock.patch.object(J, "_write", flaky_write):
            job = J.start("x", "audit")
            self.assertTrue(done.wait(5), "收尾线程没跑到写回那一步")
        deadline = time.time() + 5
        while time.time() < deadline and J.running_for("x") is not None:
            time.sleep(0.05)
        self.assertIsNone(J.running_for("x"), "占位没被放掉，项目被永久堵死")
        self.assertNotIn("x", J._running)

    def test_stop_labels_the_job_stopped_not_failed(self):
        """用户点了停止就该报「已停止」。只看退出码不够：POSIX 被信号杀掉返回
        负码，Windows 的 TerminateProcess 返回正数，会被当成失败。"""
        gate = threading.Event()
        proc = mock.Mock()
        proc.pid = 424242
        proc.wait.side_effect = lambda: (gate.wait(5), 15)[1]   # 卡住，等测试放开

        with mock.patch.object(J.subprocess, "Popen", return_value=proc), \
             mock.patch.object(J, "_terminate_tree", return_value=True):
            job = J.start("x", "audit")
            self.assertTrue(J.stop(job["id"]))
            gate.set()
            deadline = time.time() + 5
            while time.time() < deadline and J.get(job["id"])["status"] == "running":
                time.sleep(0.05)

        j = J.get(job["id"])
        self.assertEqual(j["status"], "stopped", f"退出码 15 被当成了失败：{j}")
        self.assertEqual(j["exit_code"], 15)

    def test_stop_unknown_job(self):
        self.assertFalse(J.stop("000000000000"))

    def test_get_corrupt_json_returns_none(self):
        # id 必须是合法格式：否则 get() 会因为 id 校验返回 None，
        # 这条测试就会因为错误的原因通过，json 容错那行根本没被跑到。
        J.JOBS_DIR.mkdir(parents=True, exist_ok=True)
        (J.JOBS_DIR / "bad000000001.json").write_text("{not json", "utf-8")
        self.assertIsNone(J.get("bad000000001"))

    def test_job_id_must_be_hex12(self):
        """id 校验是安全边界：/api/job/<jid> 把用户输入直接拼进路径。

        "../work/<slug>/geo" 这类 id 能读到 .jobs 之外的 geo.json（内含
        发布渠道凭据），经 stop() 的兜底分支还能对任意 pid 发信号。
        """
        for bad in ("../work/x/geo", "a/b", "..", "abc", "A1B2C3D4E5F6",
                    "deadbeef0001.json", "deadbeef00010", ""):
            self.assertFalse(J.is_valid_id(bad), f"{bad!r} 不该被当成合法 id")
            self.assertIsNone(J.get(bad), f"{bad!r} 不该读到任何 job")
            self.assertFalse(J.stop(bad), f"{bad!r} 不该能停任何 job")
        self.assertTrue(J.is_valid_id("deadbeef0001"))

    def test_prune_keeps_running_and_recent(self):
        """过期清理只删「已结束」且超过保留期的记录 —— 还在跑的绝不碰。"""
        old_t = time.time() - 40 * 86400

        def aged(job_id, **kw):
            self._write_job(job_id, **kw)
            os.utime(J.JOBS_DIR / f"{job_id}.json", (old_t, old_t))

        aged("deadbeef0009", status="done")       # 过期 + 已结束 → 删
        self._write_job("deadbeef000a", status="done")   # 新记录 → 留
        aged("deadbeef000b", status="running")    # 过期但在跑 → 绝不删

        self.assertEqual(J.prune_jobs(), 1)
        self.assertIsNone(J.get("deadbeef0009"))
        self.assertIsNotNone(J.get("deadbeef000a"))
        self.assertIsNotNone(J.get("deadbeef000b"))


if __name__ == "__main__":
    unittest.main()
