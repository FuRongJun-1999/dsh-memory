"""Issue #88: cross-form conclusion parity and write-path regression coverage.

Run: python -X utf8 -m md_cg.test_issue88_execution_conflicts
"""
import tempfile
import unittest

from .mdcos import MdCGOS


def card(port="5432", form="inline", verification="读取服务配置",
         condition="服务进程启动且配置已加载", function="服务监听端口",
         body=""):
    fields = (("功能名", function), ("生效条件", condition),
              ("子功能", "端口取值"), ("执行", "端口是 " + port),
              ("验证方式", verification), ("不适用条件", "无"))
    if form == "bare":
        text = "\n".join("# " + k + "\n" + v for k, v in fields)
    else:
        sep = ":" if form == "ascii" else "："
        text = "\n".join("# " + k + sep + v for k, v in fields)
    return text + "\n" + body


class ExecutionConflictTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ccg_execution_")
        self.addCleanup(self.temp.cleanup)
        self.cg = MdCGOS(self.temp.name)
        self.addCleanup(self.cg.close)

    def check_pair(self, old, new):
        self.cg.add("old_port", old, layer="knowledge")
        return self.cg.check_consistency(new, layer="knowledge",
                                         auto_flywheel=False)

    def test_pure_ccg_different_execution_defers(self):
        for form in ("ascii", "bare"):
            with self.subTest(form=form):
                result = self.check_pair(card(form=form), card("6543", form))
                self.assertEqual(result["verdict"], "DEFER", result)
                self.assertTrue(any(c["type"] == "same_condition_divergence"
                                    for c in result["conflicts"]), result)

    def test_identical_execution_accepts_across_forms(self):
        for form in ("inline", "ascii", "bare"):
            with self.subTest(form=form):
                result = self.check_pair(card(), card(form=form))
                self.assertEqual(result["verdict"], "ACCEPT", result)

    def test_verification_change_alone_is_not_a_conclusion_conflict(self):
        result = self.check_pair(card(), card(verification="连接数据库查询端口"))
        self.assertEqual(result["verdict"], "ACCEPT", result)

    def test_equal_free_body_cannot_hide_execution_conflict(self):
        result = self.check_pair(card(body="读取配置后连接服务。"),
                                 card("6543", body="读取配置后连接服务。"))
        self.assertEqual(result["verdict"], "DEFER", result)

    def test_whitespace_only_difference_accepts(self):
        result = self.check_pair(card(), card(port="5 4 3 2").replace("\n", "\r\n"))
        self.assertEqual(result["verdict"], "ACCEPT", result)

    def test_legacy_free_body_matches_same_execution_value(self):
        old = card().replace("# 执行：端口是 5432\n", "") + "端口是 5432"
        result = self.check_pair(old, card())
        self.assertEqual(result["verdict"], "ACCEPT", result)

    def test_different_condition_does_not_create_divergence(self):
        result = self.check_pair(card(), card("6543", condition="月面无人站离线维护"))
        self.assertFalse(any(c["type"] == "same_condition_divergence"
                             for c in result["conflicts"]), result)

    def test_write_records_divergence_and_preserves_existing_node(self):
        old = card()
        self.cg.add("old_port", old, layer="knowledge")
        out = self.cg.add("new_port", card("6543"), layer="knowledge",
                          consistency=True, on_conflict="defer")
        # Existing add() contract records DEFER; only REJECT/BLINDSPOT defer writes.
        self.assertEqual(out, "new_port")
        saved = self.cg.get("new_port")["frontmatter"]["consistency"]
        self.assertEqual(saved["verdict"], "DEFER", saved)
        self.assertEqual(self.cg.get("old_port")["content"], old)


if __name__ == "__main__":
    unittest.main()
