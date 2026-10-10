"""Guard CCG heading semantics and retrieval parity when optimizing the parser.

Run: python -X utf8 -m md_cg.test_ccg_heading_parser
"""
import re
import tempfile
import unittest
from unittest import mock

from . import nodefile
from .mdcos import MdCGOS


def reference_heading(line, mark):
    """The existing policy regex, kept as a differential oracle for this test."""
    match = re.match(r"^#\s*" + re.escape(mark), line or "")
    return (line or "")[match.end():] if match else None


class HeadingParserTests(unittest.TestCase):
    def test_policy_heading_boundaries(self):
        cases = (("#执行：v", "：v"), ("# 执行:v", ":v"),
                 ("#\t执行", ""), ("#\u3000执行 v", " v"),
                 ("# 执行（备注）", "（备注）"),
                 ("## 执行：v", None), ("  # 执行：v", None),
                 ("正文 # 执行：v", None), ("", None), (None, None))
        for line, expected in cases:
            with self.subTest(line=line):
                self.assertEqual(nodefile._ccg_heading_rest(line, "执行"), expected)

    def test_differential_regex_semantics(self):
        marks = nodefile.CCG_MARKS + ("custom", "a+b", "[x]", "", "执行（注）")
        prefixes = ("#", "# ", "#\t", "#\u3000", "## ", " # ", "text ")
        suffixes = ("", ":value", "：值", "suffix", "\r", "\nbody")
        for mark in marks:
            for prefix in prefixes:
                for suffix in suffixes:
                    line = prefix + mark + suffix
                    self.assertEqual(nodefile._ccg_heading_rest(line, mark),
                                     reference_heading(line, mark), (line, mark))

    def test_first_heading_and_bare_value_contract(self):
        text = "# 执行\n\n首值\n# 执行：后值\n正文"
        self.assertEqual(nodefile.ccg_field_value(text, "执行"), "首值")
        self.assertEqual(nodefile._strip_ccg_segments(text), "正文")
        self.assertEqual(nodefile.ccg_field_value("# 执行\n# 验证方式：读回", "执行"), "")

    def test_real_retrieval_matches_reference_parser(self):
        with tempfile.TemporaryDirectory(prefix="heading_parity_") as tmp:
            cg = MdCGOS(tmp)
            try:
                for i in range(30):
                    fields = (("功能名", "网关心跳参数"),
                              ("生效条件", "网关在线且心跳已启用"),
                              ("子功能", "端口取值"), ("执行", "监听端口 %d" % (9000 + i)),
                              ("验证方式", "读取网关配置"), ("不适用条件", "网关离线"))
                    separator = "\n" if i % 2 else "："
                    text = "\n".join("# " + k + separator + v for k, v in fields)
                    cg.add("port_%02d" % i, text, layer="knowledge")
                cg.flush()
                for method in (cg.search, cg.search_rrf):
                    for query in ("网关心跳", "监听端口", "无关联的词语"):
                        with self.subTest(method=method.__name__, query=query):
                            with mock.patch.object(nodefile, "_ccg_heading_rest", reference_heading):
                                before, _ = method(query, k=10, record=False)
                            after, _ = method(query, k=10, record=False)
                            self.assertEqual(after, before)
            finally:
                cg.close()


if __name__ == "__main__":
    unittest.main()
