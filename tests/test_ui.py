# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the selector layer (no device, no adb)."""
from __future__ import annotations

import unittest

from droidkit import ui

XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout"
        content-desc="" clickable="false" enabled="true" bounds="[0,0][1080,1920]">
    <node text="登录" resource-id="com.example:id/login" class="android.widget.Button"
          content-desc="" clickable="true" enabled="true" bounds="[80,1600][1000,1720]" />
    <node text="" resource-id="com.example:id/avatar" class="android.widget.ImageView"
          content-desc="头像" clickable="true" enabled="true" bounds="[40,80][200,240]" />
    <node text="登录遇到问题？" resource-id="" class="android.widget.TextView"
          content-desc="" clickable="false" enabled="true" bounds="[80,1740][600,1800]" />
    <node text="隐藏" resource-id="com.example:id/ghost" class="android.widget.TextView"
          content-desc="" clickable="false" enabled="true" visible-to-user="false"
          bounds="[0,0][100,100]" />
  </node>
</hierarchy>"""


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.nodes = ui.parse(XML)

    def test_parses_all_bounded_nodes(self):
        self.assertEqual(len(self.nodes), 5)

    def test_bounds_and_center(self):
        btn = ui.find(self.nodes, rid="com.example:id/login")[0]
        self.assertEqual(btn.bounds, (80, 1600, 1000, 1720))
        self.assertEqual(btn.center, (540, 1660))
        self.assertEqual(btn.width, 920)
        self.assertEqual(btn.height, 120)
        self.assertTrue(btn.clickable)

    def test_garbage_input_is_not_fatal(self):
        self.assertEqual(ui.parse(""), [])
        self.assertEqual(ui.parse("not xml at all"), [])
        self.assertEqual(ui.parse("<hierarchy><node bounds='' /></hierarchy>"), [])


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.nodes = ui.parse(XML)

    def test_exact_text(self):
        hits = ui.resolve(self.nodes, "text:登录")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].rid, "com.example:id/login")

    def test_contains_text(self):
        hits = ui.resolve(self.nodes, "text~:登录")
        self.assertEqual(len(hits), 2)  # 登录 and 登录遇到问题？

    def test_bare_string_is_contains(self):
        hits = ui.resolve(self.nodes, "遇到问题")
        self.assertEqual(len(hits), 1)

    def test_resource_id(self):
        hits = ui.resolve(self.nodes, "id:com.example:id/avatar")
        self.assertEqual(hits[0].desc, "头像")

    def test_content_desc(self):
        hits = ui.resolve(self.nodes, "desc:头像")
        self.assertEqual(hits[0].rid, "com.example:id/avatar")

    def test_missing_selector_returns_empty(self):
        self.assertEqual(ui.resolve(self.nodes, "id:nope"), [])
        self.assertEqual(ui.resolve(self.nodes, ""), [])

    def test_visible_nodes_rank_first(self):
        hits = ui.find(self.nodes, text="隐藏")
        self.assertFalse(hits[0].visible)

    def test_describe_lists_labelled_nodes_only(self):
        text = ui.describe(self.nodes)
        self.assertIn("登录", text)
        self.assertIn("click", text)


class GeometryTests(unittest.TestCase):
    def test_area_prefers_bigger_element(self):
        nodes = ui.parse("""<hierarchy>
            <node text="共享" resource-id="a" class="b" clickable="true" enabled="true"
                  bounds="[0,0][100,100]" />
            <node text="共享" resource-id="c" class="b" clickable="true" enabled="true"
                  bounds="[0,0][400,400]" />
        </hierarchy>""")
        self.assertEqual(ui.find(nodes, text="共享")[0].rid, "c")


class GesturePayloadTests(unittest.TestCase):
    """Every injected frame must be a complete contact."""

    def _capture(self, **kw):
        from droidkit.uinput_touch import Touch

        class FakeAdb:
            def shell(self, *a, **k): return ""
            def sh(self, *a, **k): return ""
            def run(self, *a, **k): return ""

        class Recorder(Touch):
            sent = []

            def _send(self, lines):
                Recorder.sent.append(lines)

            def _screen(self):
                return (1080, 1920)

        Recorder.sent.clear()
        t = Recorder(FakeAdb(), human=False, **kw)
        return t, Recorder.sent

    def test_swipe_steps_carry_pressure_and_size(self):
        t, sent = self._capture()
        t.swipe(100, 100, 500, 500, ms=120)
        lines = sent[-1]
        moves = [l for l in lines if l.startswith("move ")]
        self.assertTrue(moves)
        for line in moves:
            parts = line.split()
            self.assertEqual(len(parts), 5, line)          # move x y pressure major
            self.assertGreater(int(parts[3]), 0, line)
            self.assertGreater(int(parts[4]), 0, line)

    def test_swipe_closes_with_up(self):
        t, sent = self._capture()
        t.swipe(100, 100, 500, 500, ms=80)
        self.assertEqual(sent[-1][-1], "up")

    def test_tap_is_down_sleep_up(self):
        t, sent = self._capture()
        t.tap(300, 300)
        self.assertEqual([l.split()[0] for l in sent[-1]], ["down", "sleep", "up"])

    def test_warmup_can_be_disabled(self):
        import os
        t, sent = self._capture()
        os.environ["DROIDKIT_NO_WARMUP"] = "1"
        try:
            self.assertFalse(t.warmup())
        finally:
            del os.environ["DROIDKIT_NO_WARMUP"]
        self.assertFalse(sent)


if __name__ == "__main__":
    unittest.main()
