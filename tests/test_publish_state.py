"""发布可见性（state）与调用结果（ok）必须分开。

背景：dev.to 建草稿返回的也是成功，记录里写着 ok:true，界面据此显示「已发布」——
三篇成稿因此在 Drafts 里躺了几天没人发现，引用层拿不到任何东西。
state 说的是内容有没有对外可见，ok 只说这次调用没报错。
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import publish as P


class TestDefaultState(unittest.TestCase):
    def test_draft_channels_default_to_draft(self):
        for code in ("devto", "wordpress", "wechat_draft"):
            self.assertEqual(P.DEFAULT_STATE[code], "draft", code)

    def test_immediate_channels_default_to_published(self):
        for code in ("github", "reddit", "x", "webhook"):
            self.assertEqual(P.DEFAULT_STATE[code], "published", code)

    def test_every_publisher_declares_a_state(self):
        # 新增渠道时漏登记，前端就会把草稿显示成已发布——回到这次的病根
        for code in P.PUBLISHERS:
            self.assertIn(code, P.DEFAULT_STATE, f"渠道 {code} 没有声明默认可见性")


class TestStateOf(unittest.TestCase):
    """state 的取法本身：渠道报的优先，没报按默认，失败不给状态。"""

    def test_explicit_state_beats_the_channel_default(self):
        # 渠道自己报了就以它为准：github 默认 published，但它说 draft 就得是 draft
        self.assertEqual(P._state_of("github", {"ok": True, "state": "draft"}), "draft")

    def test_failed_call_has_no_state(self):
        # 失败没有可见性可言，前端不该拿它计数
        self.assertEqual(P._state_of("github", {"ok": False}), "")
        self.assertEqual(P._state_of("devto", {"ok": False, "state": "published"}), "")

    def test_falls_back_to_the_channel_default(self):
        self.assertEqual(P._state_of("devto", {"ok": True}), "draft")
        self.assertEqual(P._state_of("github", {"ok": True}), "published")


class TestDevtoState(unittest.TestCase):
    """dev.to 是唯一「建草稿与真发布共用同一接口」的渠道，必须自己报状态。"""

    def setUp(self):
        self._saved = os.environ.get("DEVTO_API_KEY")
        os.environ["DEVTO_API_KEY"] = "test-key"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("DEVTO_API_KEY", None)
        else:
            os.environ["DEVTO_API_KEY"] = self._saved

    def _call(self, cfg):
        with mock.patch.object(P, "requests") as rq:
            rq.post.return_value = mock.Mock(
                status_code=201, json=lambda: {"url": "https://dev.to/x"})
            res = P._pub_devto(cfg, "body", "title", "f.md")
            return res, rq

    def test_default_leaves_it_as_a_draft(self):
        res, rq = self._call({})
        self.assertTrue(res["ok"])
        self.assertEqual(res["state"], "draft")
        self.assertFalse(rq.post.call_args.kwargs["json"]["article"]["published"],
                         "未加 --published 时不能把请求体设成已发布")

    def test_publish_now_marks_published(self):
        res, rq = self._call({"_publish_now": True})
        self.assertEqual(res["state"], "published")
        self.assertTrue(rq.post.call_args.kwargs["json"]["article"]["published"])

if __name__ == "__main__":
    unittest.main()
