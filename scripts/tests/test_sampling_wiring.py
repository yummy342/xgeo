"""回归：采样层的三处接线，删了不会报错、只会让采样静默失真。

2026-09-24 合并国内线与服务器线时漏掉的四处里有三处在这条路径上（第四处是
分析层的思维链剥离，另有测试）。漏了之后**没有任何测试变红** —— 因为产物级对比
只覆盖分析层：把真实样本离线重算一遍指标，结果一模一样，而这三处影响的是
「怎么去问模型」，不影响「拿回来的答案怎么算分」。

  · 注册表 timeout 没接线 → 豆包这类慢档卡在 120s 默认值上，先超时再重试两轮
  · ModelNotOpen 没放行   → responses 端点说「模型未开通」时直接判失败，
                            而 chat/completions 可能通（实测 turbo 就是这样），
                            等于把一条能采的链路掐掉。刚开内容插件那段时间尤其要紧
  · skip_temperature 没接线 → kimi-k3 带 temperature 直接 400

跑法：.venv/bin/python -m unittest discover -s scripts/tests
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import sample as S         # noqa: E402

PLAT = "t-wiring"


def ok_chat_response(text: str = "answer"):
    r = mock.Mock()
    r.status_code = 200
    r.text = ""
    r.json = lambda: {"choices": [{"message": {"content": text}}],
                      "model": "m", "usage": {}}
    return r


def entry(**over):
    p = {"name": "T", "market": "cn", "base": "http://ark.test/v1",
         "model": "m", "key_env": "T_WIRING_KEY"}
    p.update(over)
    return p


class AskHonorsRegistryTimeout(unittest.TestCase):
    def _run(self, **entry_over):
        seen = {}

        def fake_post(url, **kw):
            seen["timeout"] = kw.get("timeout")
            seen["json"] = kw.get("json")
            return ok_chat_response()

        with mock.patch.dict(S.PROVIDERS, {PLAT: entry(**entry_over)}), \
                mock.patch.dict(os.environ, {"T_WIRING_KEY": "k"}), \
                mock.patch.object(S.requests, "post", side_effect=fake_post):
            out = S.ask(PLAT, "q")
        self.assertTrue(out["ok"], out)
        return seen

    def test_registry_timeout_wins_over_default(self):
        """注册表写了 300 就得用 300，不能听 ask() 的默认 120。"""
        seen = self._run(timeout=300)
        self.assertEqual(seen["timeout"], 300)

    def test_falls_back_to_default_when_registry_says_nothing(self):
        seen = self._run()
        self.assertEqual(seen["timeout"], 120)


class SkipTemperatureOmitsTheParameter(unittest.TestCase):
    def _body(self, **entry_over):
        seen = {}

        def fake_post(url, **kw):
            seen["json"] = kw.get("json")
            return ok_chat_response()

        with mock.patch.dict(S.PROVIDERS, {PLAT: entry(**entry_over)}), \
                mock.patch.dict(os.environ, {"T_WIRING_KEY": "k"}), \
                mock.patch.object(S.requests, "post", side_effect=fake_post):
            S.ask(PLAT, "q")
        return seen["json"]

    def test_skip_temperature_drops_the_field(self):
        """kimi-k3 带 temperature 直接 400 —— 标了就一个参数都别带。"""
        body = self._body(skip_temperature=True)
        self.assertNotIn("temperature", body)

    def test_normal_platform_still_sends_temperature(self):
        body = self._body()
        self.assertEqual(body.get("temperature"), 0.7)


class ArkModelNotOpenDegrades(unittest.TestCase):
    def test_modelnotopen_falls_back_to_chat(self):
        """responses 说 ModelNotOpen ≠ 这条链路不能用，交给降级那次判。"""
        err = mock.Mock()
        err.status_code = 400
        err.text = '{"code":"ModelNotOpen","message":"model not open"}'
        p = entry(protocol="ark", search=True)
        with mock.patch.object(S.requests, "post",
                               side_effect=[err, ok_chat_response("degraded answer")]) as mp:
            out = S.ask_ark(p, "k", "q", 300)
        self.assertTrue(out["ok"], out)
        self.assertFalse(out["searched"], "降级那条就不该标成联网")
        self.assertEqual(out["answer"], "degraded answer")
        self.assertEqual(mp.call_count, 2)
        self.assertTrue(mp.call_args_list[1].args[0].endswith("/chat/completions"))

    def test_real_failure_still_returns_error(self):
        """别的错（比如鉴权失败）不该被当成「可以降级」放过去。"""
        err = mock.Mock()
        err.status_code = 401
        err.text = '{"code":"AuthenticationError"}'
        p = entry(protocol="ark", search=True)
        with mock.patch.object(S.requests, "post",
                               side_effect=[err, ok_chat_response("x")]):
            out = S.ask_ark(p, "k", "q", 300)
        self.assertFalse(out["ok"], out)


if __name__ == "__main__":
    unittest.main()
