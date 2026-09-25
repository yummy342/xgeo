"""deploy.sh 的冒烟：用一个**假远端**把它真跑一遍，断言它发了什么、单元写成什么。

为什么需要：`scripts/deploy.sh` 到今天为止零自动化验证 —— 今天在那上面修的三处
（默认不发项目数据、重新部署要 restart、daemon-reload 不能吞错）全靠代码读 + 手工
复现。而它的失效方式很贵：解包覆盖远端活数据、服务没重启（"部署了但没生效"）、
坏配置留在 sites-enabled 里等下次 nginx 重启才炸。

做法：临时目录里放一组 ssh/scp/systemctl 的垫片（PATH 前置），垫片把收到的命令逐行
记进日志、并按需要回一个像样的输出（存活检查要 401）。脚本本身一行不改。
"""
import json
import os
import shutil
import subprocess
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
DEPLOY = REPO / "scripts" / "deploy.sh"

SHIM = """#!/bin/sh
# 假远端：把命令记下来，按命令类型回一个像样的输出。
printf '%s\\n' "$*" >> "$FAKE_LOG"
case "$*" in
  *"curl "*)
    # 存活检查读的是 stdout 的状态码；配了凭据的实例回 401 也算活着
    printf '%s' "${FAKE_HTTP_CODE:-401}" ;;
esac
exit 0
"""


class DeployScriptSmoke(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.log = self.root / "remote.log"
        bindir = self.root / "bin"
        bindir.mkdir()
        for name in ("ssh", "scp", "sudo", "systemctl", "curl"):
            p = bindir / name
            p.write_text(SHIM, "utf-8")
            p.chmod(0o755)
        self.env = dict(os.environ,
                        PATH=str(bindir) + os.pathsep + os.environ.get("PATH", ""),
                        FAKE_LOG=str(self.log),
                        FAKE_HTTP_CODE="401")
        # 脚本的 SELF_DIR 取自它自己的路径 → 把 scripts/ 拷进临时目录，
        # 这样「打包什么」也是假的，不会碰到真仓库的 work/
        self.home = self.root / "src"
        shutil.copytree(REPO / "scripts", self.home / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__", "ui_dist"))
        (self.home / "work" / "proj").mkdir(parents=True)
        (self.home / "work" / "proj" / "geo.json").write_text('{"brand":{}}', "utf-8")
        (self.home / "work" / "proj" / "samples").mkdir()
        (self.home / "work" / "proj" / "samples" / "2026-09-25.jsonl").write_text("{}\n", "utf-8")
        self.addCleanup(self.tmp.cleanup)

    def _run(self, *args, expect=0):
        r = subprocess.run(["bash", str(self.home / "scripts" / "deploy.sh"), *args],
                           cwd=str(self.home), env=self.env,
                           capture_output=True, text=True, timeout=180,
                           encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, expect,
                         f"退出码 {r.returncode}\n--- stdout\n{r.stdout}\n--- stderr\n{r.stderr}")
        return r

    def _sent(self):
        return self.log.read_text("utf-8") if self.log.exists() else ""

    # 打包：默认只发 scripts/（远端 work/ 是活数据，覆盖就是静默丢数据）
    def test_default_package_excludes_project_data(self):
        r = self._run("deploy", "--host", "fake@example", "--domain", "x.test",
                      "--project", "proj", "--dir", str(self.home / "remote"))
        self.assertIn("只发 scripts/", r.stdout)
        self.assertIn("work/proj", r.stdout, "要说清远端的项目数据没动")
        # 包是本地打的，垫片不拦 tar —— 直接看脚本有没有把 work/ 放进路径列表
        self.assertNotIn("work/proj' 'work", self._sent())

    def test_with_project_flag_announces_the_overwrite(self):
        r = self._run("deploy", "--host", "fake@example", "--domain", "x.test",
                      "--project", "proj", "--dir", str(self.home / "remote"),
                      "--with-project")
        self.assertIn("会覆盖远端的同名文件", r.stdout)

    # 重新部署必须 restart：单元文件每次都重写，而 enable --now 对已跑的服务是空操作
    def test_redeploy_restarts_the_service(self):
        self._run("deploy", "--host", "fake@example", "--domain", "x.test",
                  "--project", "proj", "--dir", str(self.home / "remote"))
        sent = self._sent()
        self.assertIn("systemctl restart xgeo", sent, "没重启 → 新代码躺在磁盘上")
        self.assertIn("daemon-reload", sent)
        self.assertIn("EnvironmentFile=", sent, "单元没写 EnvironmentFile")
        self.assertIn("Restart=always", sent)
        self.assertIn("nginx -t", sent, "没有先检查再重载")
        # 只看**命令行**（注释里提到 enable --now 是说明，不算命令）
        cmds = chr(10).join(l for l in sent.splitlines()
                            if l.strip() and not l.strip().startswith("#"))
        self.assertNotIn("enable --now", cmds, "enable --now 对已跑的服务等于没启")
        self.assertIn("systemctl enable xgeo", cmds)

    # 参数：单引号会穿过两层 shell；--host 不带用户名要补成 ubuntu@
    @unittest.skipIf(os.name == "nt",
                     "Windows/msys 在 Python→bash 传参时会把单引号吃掉（o'brien → obrien），"
                     "这条只能在真 shell 里验 —— 本机已手工验过：直接 bash 跑该参数退出 2 并"
                     "打「参数里不能含单引号」。Linux/macOS 上这条照常跑。")
    def test_single_quote_is_refused(self):
        r = self._run("deploy", "--host", "fake@example", "--domain", "x.test",
                      "--dir", "/home/o'brien/xgeo", expect=2)
        self.assertIn("单引号", r.stderr)

    def test_host_without_user_gets_ubuntu(self):
        self._run("deploy", "--host", "1.2.3.4", "--domain", "x.test",
                  "--project", "proj", "--dir", "/home/ubuntu/xgeo")
        sent = self._sent()
        self.assertIn("ubuntu@1.2.3.4", sent, "ssh 没带上用户名 → 会用本地账号登录")
        self.assertIn("/home/ubuntu/xgeo", sent)

    # 部署说明里的必设项：反代形态要带 www
    def test_hint_mentions_www_public_host(self):
        r = self._run("deploy", "--host", "fake@example", "--domain", "x.test",
                      "--project", "proj", "--dir", str(self.home / "remote"))
        self.assertIn("XGEO_PUBLIC_HOST=x.test,www.x.test", r.stdout)

    def test_missing_domain_exits_2(self):
        r = self._run("deploy", "--host", "fake@example", expect=2)
        self.assertIn("缺 --domain", r.stderr)

    def test_help_exits_zero(self):
        for form in (["--help"], ["help"]):
            r = self._run(*form)
            self.assertIn("deploy.sh deploy", r.stdout, form)
