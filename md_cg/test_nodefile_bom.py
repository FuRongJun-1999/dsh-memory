"""R-202 / P0-5 回归：BOM 与 CRLF 节点文件必须切得出 frontmatter，切不出时不许默认合法。

修前病象（审计 P0-5，2026-11-10 实测）：
  `loads` 首字符判据 `startswith("---\\n")` 对 `'\\ufeff---\\n…'` 为假 ⇒ 返回
  `({}, 全文)`；而 `frontmatter_problem({})` 缺省一律合法 ⇒ 静默接受。之后治理
  回写 `dumps({}, 整个旧文件)` 把旧头嵌进正文，正文里的两条 `---` 又把
  `id:`/`layer:` 逐层吃掉（节点一次带 BOM 的编辑降一级）。

本文件钉三件事：
  1. 剥 BOM + 认 CRLF（`loads` 入口同一判据）；
  2. 空 fm 且正文以 `---` 开头 ⇒ `frontmatter_problem` 判损坏（不再「缺省合法」）；
  3. 往返恒等：`loads(dumps(fm, body)) == (fm, body)`（BOM / CRLF / 正文含分隔线）。

负控（人工执行，见修理表 R-202）：注释掉 `nodefile.loads` 里剥 BOM 那一行
（`if text[:1] == _BOM: text = text.lstrip(_BOM)`），G1/G3 必须红、返回 `({}, 全文)`。

Run: python -X utf8 -m md_cg.test_nodefile_bom
"""
import unittest

from . import nodefile

BOM = "\ufeff"


class LoadsEncodingPrefixTests(unittest.TestCase):
    """G1/G2：编码前缀与行尾形态都不许让 frontmatter 静默丢失。"""

    def test_g1_bom_frontmatter_is_parsed(self):
        fm, body = nodefile.loads(BOM + "---\nid: x\n---\nbody\n")
        self.assertEqual(fm, {"id": "x"})
        self.assertEqual(body, "body\n")
        self.assertNotIn("---", body)

    def test_g2_crlf_frontmatter_is_parsed(self):
        fm, body = nodefile.loads("---\r\nid: x\r\n---\r\nbody\r\n")
        self.assertEqual(fm, {"id": "x"})
        self.assertTrue(body.rstrip("\r\n") == "body", body)
        self.assertNotIn("---", body)

    def test_g2b_bom_plus_crlf(self):
        """两种前缀叠加（记事本在 CRLF 文件上重存）——修前双双失效。"""
        fm, body = nodefile.loads(BOM + "---\r\nid: x\r\nlayer: knowledge\r\n---\r\nbody\r\n")
        self.assertEqual(fm, {"id": "x", "layer": "knowledge"})
        self.assertNotIn("---", body)

    def test_g1b_bom_body_does_not_keep_the_marker(self):
        """BOM 不得漏进正文：否则 `dumps({}, 正文)` 会把 BOM 写进正文首字节。"""
        _fm, body = nodefile.loads(BOM + "无 frontmatter 的裸文件\n")
        self.assertFalse(body.startswith(BOM), repr(body))
        self.assertEqual(body, "无 frontmatter 的裸文件\n")

    def test_g1c_lf_unchanged(self):
        """既有 LF 口径逐位不变。"""
        self.assertEqual(nodefile.loads("---\nid: x\n---\nbody\n"),
                         ({"id": "x"}, "body\n"))


class EmptyFrontmatterTests(unittest.TestCase):
    """G4：空 fm + 起始分隔行 ⇒ 判损坏（P0-5 的「缺省合法」漏口）。"""

    def test_g4_unparsed_head_is_a_problem(self):
        for content in ("---\nid: x\n---\nbody\n",      # LF 无闭合的形态
                        "---\r\nid: x\r\n---\r\nbody\r\n",  # CRLF 无闭合的形态
                        BOM + "---\nid: x\n",           # 带 BOM 的残头
                        "---\n"):
            with self.subTest(content=content):
                self.assertTrue(nodefile.frontmatter_problem({}, content),
                                "空 fm + 起始分隔行必须判损坏：%r" % (content,))

    def test_g4b_bare_markdown_still_legal(self):
        """真正的裸 md（无 frontmatter、正文不以 --- 开头）照旧合法——
        `_scan_nodes` 以文件名登入的旧例不得被误伤。"""
        for content in ("# 标题\n正文\n", "", None, "  --- 缩进的横线\n"):
            with self.subTest(content=content):
                self.assertEqual(nodefile.frontmatter_problem({}, content), [])

    def test_g4c_parsed_frontmatter_unaffected(self):
        """有 fm 的文件不受新判据影响（判据只看「空 fm」）。"""
        fm, body = nodefile.loads(BOM + "---\nid: x\n---\nbody\n")
        self.assertEqual(nodefile.frontmatter_problem(fm, body), [])


class RoundTripTests(unittest.TestCase):
    """G5：`loads(dumps(fm, body)) == (fm, body)`——三种输入形态都必须成立。"""

    CASES = (
        ("含 BOM", BOM + "---\nid: x\n---\nbody\n"),
        ("含 CRLF", "---\r\nid: x\r\n---\r\nbody\r\n"),
        ("正文含分隔线", "---\nid: x\n---\na\n---\nb\n"),
    )

    def test_g5_roundtrip(self):
        for name, text in self.CASES:
            with self.subTest(name=name):
                parsed = nodefile.loads(text)
                self.assertEqual(nodefile.loads(nodefile.dumps(*parsed)), parsed)

    def test_g5b_roundtrip_from_scratch(self):
        """不依赖源文本：任意 (fm, body) 写出去再读回来恒等（落盘形态）。"""
        for fm, body in (({"id": "x"}, "body\n"),
                         ({"id": "x", "layer": "knowledge"}, "a\n---\nb\n"),
                         ({"id": "x", "tags": ["a"]}, "多行\n正文\n")):
            with self.subTest(fm=fm):
                self.assertEqual(nodefile.loads(nodefile.dumps(fm, body)), (fm, body))

    def test_g5c_no_head_nesting(self):
        """P0-5 的降级链：修后一次回写不得把旧头嵌进正文（正文里只许有一对
        由 `dumps` 生成的分隔线）。"""
        text = BOM + "---\nid: x\nlayer: knowledge\n---\nbody\n"
        for _ in range(3):                      # 连续三次治理回写
            fm, body = nodefile.loads(text)
            text = nodefile.dumps(fm, body)
        self.assertEqual(text.count("---"), 2, text)
        self.assertEqual(nodefile.loads(text),
                         ({"id": "x", "layer": "knowledge"}, "body\n"))


if __name__ == "__main__":
    unittest.main()
