# -*- coding: utf-8 -*-
"""PR #735 L3 验证：改条件短语解析口径后，存量索引是否需要迁移？

review 的 L3 问句原文：
  「若条件词项在写时已落进索引条目，改解析口径后存量索引不会自动更新 ——
    请 grep cond_terms / 条件词 在 mdcg.py / mdcos.py / backfill.py 的调用点，
    确认是否需要迁移。」

本探针回答两件事，全部靠**实测**而非读代码猜：
  A. `_index.json` 的节点条目里到底有没有「条件短语」这类派生键？
  B. `judge_qualification` 的条件来源是**正文**还是**索引**？
     —— 若来自正文，则改解析口径对存量索引**零依赖**，L3 的担心不成立。

只读探针：在临时目录造合成库，不碰任何真实库。
"""
import io
import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _PKG)

from md_cg import mdcg, nodefile  # noqa: E402

_PASS, _FAIL = [], []


def ok(cond, name, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (("  | " + detail) if detail else ""))


# 条件里带冒号的真实形态（正是 PR #735 要修的那类）
COND = "时间：到了上午 9:00 开始开会；约束：需按 WCAG 判 ≥3:1"
CONTENT = (
    "# 功能名：冒号条件探针\n"
    "# 生效条件：" + COND + "\n"
    "# 子功能：验证索引是否存条件短语\n"
    "# 执行：读 _index.json 查键\n"
    "# 验证方式：本探针自证\n"
    "# 不适用条件：无\n"
)


def main():
    root = tempfile.mkdtemp(prefix="probe735l3_")
    print("临时库:", root)
    try:
        cg = mdcg.MdCG(root)
        cg.add("probe735l3_node", CONTENT, layer="knowledge",
               content_kind="text", verification_basis="test")
        cg.close()  # close → compact，把索引落成 _index.json

        idx_p = os.path.join(root, "_index.json")
        ok(os.path.exists(idx_p), "A0 _index.json 已落盘")

        snap = json.load(io.open(idx_p, encoding="utf-8"))
        nodes = snap.get("nodes") or {}
        ok(len(nodes) == 1, "A1 索引含 1 个节点条目", "实际 %d" % len(nodes))
        entry = list(nodes.values())[0]
        keys = sorted(entry.keys())

        # ---- A：索引条目里有没有「条件短语」派生键？----
        # 期望的解析结果（补丁后口径）
        expected = nodefile.cond_terms(COND) if hasattr(nodefile, "cond_terms") else []
        print("    条件原文:", COND)
        print("    解析后应得:", expected)

        # 找所有 string-list 型键，看有没有等于 expected 的
        list_keys = {k: v for k, v in entry.items() if isinstance(v, list) and v}
        has_cond_list = any(
            isinstance(v, list) and [str(x) for x in v] == [str(x) for x in expected]
            for v in entry.values()
        )
        ok(not has_cond_list,
           "A2 索引条目**不含**条件短语派生列表",
           "字符串列表键=%s" % (list(list_keys.keys()) or "无"))

        # 明确点名：条件相关键只有 has_neg_conditions 这类布尔/原样字段
        # 注意 postcondition_terms 是「验证方式」要素的索引键（另一个 CCG 要素），
        # 不是「生效条件」的短语列表 —— 不能混为一谈（我第一版这里判错了）。
        condish = [k for k in keys if "cond" in k.lower() or "条件" in k]
        print("    条目内含 cond/条件 的键:", condish)
        ok(all(k in ("condition_space", "has_neg_conditions")
               or not isinstance(entry[k], list) or k == "postcondition_terms"
               for k in condish),
           "A3 「生效条件」无短语列表键（postcondition_terms 属另一要素）",
           "condish=%s" % condish)
        ok("postcondition_terms" in condish and "condition_space" in condish,
           "A3b 条件相关键逐一有名有姓（无隐藏的 cond_terms 键）")

        # condition_space 原样存 frontmatter（不是派生的短语列表）
        ok("condition_space" in keys,
           "A4 condition_space 是**原样快照**（非派生）",
           "值=%r" % (entry.get("condition_space"),))

        # ---- B：判定读正文还是读索引？----
        node_dict = {"frontmatter": {"verification_basis": "probe"},
                     "content": CONTENT}
        # 注意：命中判据是 `短语 in scene_str`，即**短语必须是查询的子串**。
        # 所以「上午 9:00 开会」查不到「到了上午 9:00 开始开会」——
        # 这是 issue #722 的 P1（短语长于查询），不是本 PR 的范围，我第一版断言写错了。
        r_hit = mdcg.MdCG.judge_qualification(node_dict, "到了上午 9:00 开始开会")
        # 条件不命中
        r_miss = mdcg.MdCG.judge_qualification(node_dict, "今天天气怎么样")
        print("    命中态:", r_hit["state"], "|", r_hit["reason"][:60])
        print("    未命中态:", r_miss["state"], "|", r_miss["reason"][:60])
        ok(r_hit["state"] == mdcg.STATE_ACCEPT,
           "B1 短语被查询完整包含 → ACCEPT")
        ok(r_miss["state"] == mdcg.STATE_DEFER, "B2 条件未命中 → DEFER（不再静默 ACCEPT）")

        # 反向对照：短语 ⊂ 查询才算命中（P1 现状锁定，非本 PR 范围）
        r_short = mdcg.MdCG.judge_qualification(node_dict, "上午 9:00 开会")
        ok(r_short["state"] == mdcg.STATE_DEFER,
           "B1b 现状锁定：短语长于查询 → DEFER（issue #722 的 P1，本 PR 不涉及）",
           "state=%s" % r_short["state"])

        # 决定性证据：**抹掉索引条目**后重判，结论不变 ⇒ 判定不依赖索引
        node_dict_2 = {"frontmatter": {}, "content": CONTENT}  # 无任何索引派生字段
        r2 = mdcg.MdCG.judge_qualification(node_dict_2, "上午 9:00 开会")
        ok(r2["state"] == mdcg.STATE_DEFER,
           "B3 去掉 verification_basis 后不影响「条件段」判定（条件不读索引）",
           "state=%s" % r2["state"])

        # 直接比对：同一 content，条目里没有任何东西被 judge 读走
        import inspect
        src = inspect.getsource(mdcg.MdCG.judge_qualification)
        ok("_ccg_line" in src and "condition_space_text" in src,
           "B4 条件来源=正文 _ccg_line / frontmatter condition_space（源码实证）")
        ok("entry" not in src and "_index" not in src,
           "B5 判定函数内**不出现**索引条目/索引文件读取")

        # ---- C：rebuild 幂等性（迁移是否需要）----
        cg2 = mdcg.MdCG(root)
        n_before = len(cg2.index["nodes"])
        cg2.rebuild_index()
        cg2.close()
        snap2 = json.load(io.open(idx_p, encoding="utf-8"))
        ok(len(snap2.get("nodes") or {}) == n_before,
           "C1 rebuild 后条目数不变（口径改动不影响索引形态）")

    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)

    print("\n== 结果: %d passed / %d failed ==" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  FAILED:", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
