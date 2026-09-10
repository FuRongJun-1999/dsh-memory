# -*- coding: utf-8 -*-
"""CCG 四要素接线 + 检索键分区（P33 · 设计态验收）。

对照交付计划：
  ① 契约层：VERIFICATION_BASIS 扩 textbook/public_kb，且显式分「可复现档 / 来源一致性档」
  ② 回填来源：功能名补 state_attributes.name（旧白名单漏掉的来源），title 仅作回退
  ③ 占位排除：骨架占位标记绝不渲染成正文事实，且单独计数（转待填充工单）
  ④ 接线：四要素写正文规范行 → 词面召回立即命中；幂等 + 可回滚
  ⑤ 检索键分区：`# 不适用条件：` 是反例声明，LIKE 与 fuzzy 两路都不作召回键
  ⑥ 反例的正确去向：仍由 judge_qualification 读 frontmatter 走 REJECT（不靠召回键）

独立临时根，重跑 ≡ 首跑；全程只读真实库之外的东西。

运行：python -m md_cg.test_p33_ccg_wiring
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

from . import backfill, forgetting, nodefile, tokens, weights
from .mdcg import (STATE_ACCEPT, STATE_BLINDSPOT, STATE_REJECT, TIER_GLOBAL_LIKE,
                   TIER_GLOBAL_SCAN, MdCG)
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def ids(res):
    """从 search/fuzzy 结果里取节点 id（frontmatter.id 缺失时回退文件名）。"""
    out = []
    for r in res:
        fm = r[0].get("frontmatter") or {}
        nid = fm.get("id") or os.path.splitext(
            os.path.basename(r[0].get("path") or ""))[0]
        out.append(nid)
    return out


PH = "[历史·高中] 骨架锚点，内容待填充"

# ④ 触发词只写在 comment.生效条件 里，正文没有 → apply 后才会进入检索键
GAP_DOC = "# 功能名：某专业知识点\n\n该节点正文不含触发词。\n"
# ⑤⑥ 正条件 / 正负条件对照：负条件用 # 不适用条件： 行承载
POS_DOC = ("# 功能名：正条件节点\n# 生效条件：问ZXQ7\n# 子功能：子功能说明\n"
           "# 执行：执行说明\n# 验证方式：编译器/静态检查通过\n"
           "# 不适用条件：问完全无关主题\n")
POSFX_DOC = ("# 功能名：正负条件节点\n# 生效条件：问通用流程\n# 子功能：子功能说明\n"
             "# 执行：执行说明\n# 验证方式：编译器/静态检查通过\n"
             "# 不适用条件：问ZXQ7\n")
PH_DOC = "# 功能名：骨架节点\n\n迁移期空壳节点。\n"


def _seed(root):
    cg = MdCGOS(root)
    cg.add("wire_gap", GAP_DOC, layer="knowledge", verification_basis="test",
           non_applicable_conditions=["问其它主题"],
           state_attributes={"comment": {"生效条件": ["问某某特殊主题"],
                                         "子功能": "子功能说明",
                                         "执行": "执行步骤说明"}})
    cg.add("wire_pos", POS_DOC, layer="knowledge", verification_basis="compiler",
           non_applicable_conditions=["问完全无关主题"])
    cg.add("wire_posfx", POSFX_DOC, layer="knowledge",
           verification_basis="compiler",
           non_applicable_conditions=["问ZXQ7"])
    cg.add("wire_ph", PH_DOC, layer="knowledge",
           verification_basis="test",
           non_applicable_conditions=["问其它主题"],
           state_attributes={"comment": {"生效条件": ["问骨架"],
                                         "子功能": PH, "执行": PH}})
    cg.add("wire_name", "无 CCG 行的正文。\n", layer="knowledge",
           verification_basis="data",
           non_applicable_conditions=["问其它主题"],
           state_attributes={"name": "规范功能名",
                             "comment": {"生效条件": ["问规范名"],
                                         "子功能": "子功能说明",
                                         "执行": "执行步骤说明"}})
    cg.flush()
    return cg


def main():
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="mdcg_p33_")
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root, exist_ok=True)
        cg = _seed(root)

        # ---------- ① 契约层：枚举扩展 + 两档划分 ----------
        ok("textbook" in nodefile.VERIFICATION_BASIS
           and "public_kb" in nodefile.VERIFICATION_BASIS,
           "①VERIFICATION_BASIS 扩 textbook/public_kb")
        rep, cons = set(nodefile.REPRODUCIBLE_BASIS), set(nodefile.CONSISTENCY_BASIS)
        ok(not (rep & cons), "①可复现档与来源一致性档互斥")
        ok(rep | cons | {"other"} == set(nodefile.VERIFICATION_BASIS),
           "①两档 + other 恰好覆盖枚举（无漏网值）")
        ok(nodefile.verification_basis_valid({"verification_basis": "textbook"})
           and nodefile.verification_basis_valid({"verification_basis": "public_kb"}),
           "①新档值通过 verification_basis_valid 校验")
        ok(set(backfill.BASIS_TEXT) <= set(nodefile.VERIFICATION_BASIS),
           "①BASIS_TEXT 只含合法枚举值")
        ok(all(backfill.BASIS_TEXT[v] != backfill.BASIS_TEXT["other"]
               for v in nodefile.CONSISTENCY_BASIS),
           "①新档有独立文本（不退化到 other）")
        ok(all(v in weights.BASIS_TRUST for v in nodefile.CONSISTENCY_BASIS),
           "①weights.BASIS_TRUST 认账新档（否则权重按缺失算）")
        ok(weights.BASIS_TRUST["textbook"] > weights.BASIS_TRUST["public_kb"]
           > weights.BASIS_TRUST["other"],
           "①可信度排序：教材 > 公开知识库 > other")
        ok(all(v in forgetting.VERIFIED_BASES
               for v in nodefile.CONSISTENCY_BASIS),
           "①长期分层认账新档（避免「白箱可 ACCEPT、分层算未验证」）")
        ok(not (set(nodefile.CONSISTENCY_BASIS) & set(forgetting.DETERMINISTIC_BASIS)),
           "①来源一致性 ≠ 内部确定性（两轴不混用）")

        # ---------- ③ 占位识别（纯函数） ----------
        ok(nodefile.is_placeholder_text(PH), "③骨架占位标记被识别")
        ok(nodefile.is_placeholder_text("内容待填充"), "③裸占位短语被识别")
        ok(not nodefile.is_placeholder_text("论语（语录体，孔子）"),
           "③真实事实不被误判为占位")
        ok(nodefile.is_placeholder_text("") and nodefile.is_placeholder_text(None),
           "③空值不可渲染为事实")

        # ---------- ②④ name 来源优先级 + 占位过滤（单元级，精确定位） ----------
        d = backfill.derive_fields(
            {"title": "标题功能名", "state_attributes": {"name": "规范功能名"}},
            "正文\n", None)
        ok(d["功能名"] == ("规范功能名", "state_attributes.name"),
           "②功能名优先取 state_attributes.name")
        d2 = backfill.derive_fields({"title": "标题功能名"}, "正文\n", None)
        ok(d2["功能名"] == ("标题功能名", "frontmatter.title"),
           "②缺 state_attributes.name 时回退 frontmatter.title")
        ph_out = []
        d3 = backfill.derive_fields(
            {"state_attributes": {"comment": {
                "执行": PH, "子功能": PH, "生效条件": ["问真实条件"]}},
             "non_applicable_conditions": ["问其它"]},
            "正文\n", None, placeholder_out=ph_out)
        ok("执行" not in d3 and "子功能" not in d3,
           "③占位字段不进入推导结果（绝不渲染成事实）")
        ok(set(ph_out) == {"执行", "子功能"}, "③占位字段逐名记录（可出待填充工单）")
        ok("生效条件" in d3 and "不适用条件" in d3,
           "③同节点内真实字段照常推导（不因占位而整体放弃）")
        ok(backfill.derive_fields({"state_attributes": {"comment": {"执行": PH}}},
                                  "正文\n", None) == {},
           "③placeholder_out 为可选出参（缺省不报错）")

        # ---------- ⑤ 检索键分区：positive_body / _like ----------
        ok("ZXQ7" not in nodefile.positive_body(POSFX_DOC),
           "⑤positive_body 剥离 `# 不适用条件：` 行")
        ok("问通用流程" in nodefile.positive_body(POSFX_DOC),
           "⑤正条件行原样保留")
        plain = "正文提到不适用条件这个词，但不是 CCG 行。\n"
        ok(nodefile.positive_body(plain) == plain,
           "⑤只剥 CCG 行，不误伤普通句子")
        ok(MdCG._like(POSFX_DOC, {}, ["ZXQ7"]) is False,
           "⑤_like 不把反例当召回键")
        ok(MdCG._like(POSFX_DOC, {}, ["通用流程"]) is True,
           "⑤_like 正条件照常命中")
        ok(MdCG._like(POSFX_DOC, {"tags": ["ZXQ7"]}, ["ZXQ7"]) is True,
           "⑤tags 仍参与匹配（分区只作用于正文）")

        # ---------- ④ 接线前：触发词只在 comment，LIKE 层不命中 ----------
        res0, meta0 = cg.search("某某特殊主题")
        ok(meta0["tier"] != TIER_GLOBAL_LIKE,
           "④接线前：comment 里的触发词尚未进入检索键")

        p0 = backfill.plan(cg)
        ok("wire_gap" in p0["planned_ids"], "④有来源节点进入可回填清单")
        ok(p0["nodes_with_placeholder"] >= 1, "③占位节点单独计数（不静默混入）")
        pp = backfill.plan(cg, include_partial=True)
        it_ph = next(i for i in pp["items"] if i["id"] == "wire_ph")
        ok(it_ph["class"] == "partial" and set(it_ph["placeholder_fields"])
           == {"执行", "子功能"}, "③占位节点被标 partial 且注明占位字段")

        # ---------- ④ 接线落盘：四要素入正文 → 纳入检索键 ----------
        a1 = backfill.apply(cg, ids=["wire_gap", "wire_name"], batch="p33a",
                            actor="tester")
        ok(a1["written"] >= 2, "④apply 写入非零")
        _, c_gap = cg._read(cg.index["nodes"]["wire_gap"])
        ok("# 生效条件：问某某特殊主题" in c_gap,
           "④生效条件渲染为正文规范行")
        ok(nodefile.ccg_completeness(c_gap)["complete"] is True,
           "④接线后 6 要素齐全（含生效条件；从仅可检索升级为可判定）")
        ok(nodefile.ccg_completeness(
               "# 功能名：X\n# 子功能：y\n# 执行：z\n"
               "# 验证方式：test\n# 不适用条件：n\n")["complete"] is False,
           "④生效条件列入必填：缺之即 not complete（不再可隐含）")
        res1, meta1 = cg.search("某某特殊主题")
        ok(meta1["tier"] == TIER_GLOBAL_LIKE,
           "④接线后：正文触发词进入 LIKE 检索层")
        ok("wire_gap" in ids(res1), "④接线后该节点被召回")

        _, c_name = cg._read(cg.index["nodes"]["wire_name"])
        ok("# 功能名：规范功能名" in c_name,
           "②功能名由 state_attributes.name 写入正文")
        ok("# 执行：" in c_name, "④执行渲染为正文规范行")

        # 幂等
        a2 = backfill.apply(cg, ids=["wire_gap"], batch="p33a", actor="tester")
        ok(a2["written"] == 0, "④幂等：已完成节点不重复写")

        # ---------- ④ 回滚：真逆操作 ----------
        rb = backfill.rollback(cg, batch="p33a", actor="tester")
        ok(rb["reverted"] >= 2, "④回滚撤销非零")
        _, c_gap2 = cg._read(cg.index["nodes"]["wire_gap"])
        ok("# 生效条件：" not in c_gap2, "④回滚移除正文规范行")
        res2, meta2 = cg.search("某某特殊主题")
        ok(meta2["tier"] != TIER_GLOBAL_LIKE,
           "④回滚后触发词退出检索键（接线可逆）")

        # ---------- ⑤ 集成：反例不作召回键，正条件照常 ----------
        res3, meta3 = cg.search("ZXQ7")
        ok(meta3["tier"] == TIER_GLOBAL_LIKE, "⑤ZXQ7 在 LIKE 层有命中")
        ok("wire_pos" in ids(res3), "⑤正条件命中被召回")
        ok("wire_posfx" not in ids(res3),
           "⑤仅反例命中的节点不被召回（分区生效）")
        res4, _ = cg.search("通用流程")
        ok("wire_posfx" in ids(res4), "⑤正条件仍作召回键")

        fz, _ = cg._path_fuzzy("ZXQ7", cg._candidates())
        ok("wire_pos" in ids(fz), "⑤fuzzy 路召回正条件命中")
        ok("wire_posfx" not in ids(fz), "⑤fuzzy 路同样不召回反例")

        # ---------- ⑥ 反例的正确去向：judge 走 REJECT ----------
        fm_pfx, c_pfx = cg._read(cg.index["nodes"]["wire_posfx"])
        j_rej = MdCG.judge_qualification({"frontmatter": fm_pfx, "content": c_pfx},
                                        "问ZXQ7", {"query": "问ZXQ7"})
        ok(j_rej["state"] == STATE_REJECT,
           "⑥反例命中走 REJECT（不依赖召回键，靠 frontmatter 负条件）")
        fm_pos, c_pos = cg._read(cg.index["nodes"]["wire_pos"])
        j_acc = MdCG.judge_qualification({"frontmatter": fm_pos, "content": c_pos},
                                        "问ZXQ7", {"query": "问ZXQ7"})
        ok(j_acc["state"] == STATE_ACCEPT, "⑥正条件命中 + 基底已声明 → ACCEPT")
        fm_ph, c_ph = cg._read(cg.index["nodes"]["wire_ph"])
        j_bl = MdCG.judge_qualification({"frontmatter": fm_ph, "content": c_ph},
                                        "问骨架", {"query": "问骨架"})
        ok(j_bl["state"] == STATE_BLINDSPOT,
           "⑥要素不全仍 BLINDSPOT（占位排除后不冒充齐全）")

        # ---------- ③ 占位节点端到端：include_partial 也不会写进占位 ----------
        backfill.apply(cg, ids=["wire_ph"], batch="p33ph",
                       include_partial=True, actor="tester")
        _, c_ph2 = cg._read(cg.index["nodes"]["wire_ph"])
        ok("内容待填充" not in c_ph2, "③正文绝不出现占位标记")
        ok("# 执行：" not in c_ph2, "③占位字段不渲染成 `# 执行：` 行")
        ok("# 生效条件：问骨架" in c_ph2, "③同节点真实字段照常接线")

        # ---------- ⑦ 范围收窄：prefix 收窄 + 内部层出局 ----------
        cg.add("note_x", "派生记忆正文。\n", layer="knowledge",
               verification_basis="test",
               state_attributes={"comment": {"生效条件": ["问派生主题"]}})
        cg.add("anchor_x", "锚点脚手架正文。\n", layer="anchor",
               verification_basis="test",
               state_attributes={"comment": {"生效条件": ["问锚点主题"]}})
        p_kp = backfill.plan(cg, prefix="wire_")
        ok("wire_gap" in p_kp["planned_ids"], "⑦prefix 内节点照常入列")
        ok("note_x" not in p_kp["planned_ids"], "⑦prefix 外节点出局（不混入工单）")
        p_all = backfill.plan(cg)
        ok("anchor_x" not in p_all["planned_ids"]
           and p_all["skipped_internal"] >= 1,
           "⑦内部 anchor/self 层出局并单独计数")
        ok(backfill.exempt_plan(cg)["skipped_internal"] >= 1,
           "⑦摘豁免同样排除内部层（不改写脚手架）")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nPASS={PASS} FAIL={FAIL}")
    if FAILS:
        print("FAILED:")
        for f in FAILS:
            print("  -", f)
        raise SystemExit(1)
    print("全部通过：P33 四要素接线 + 检索键分区")


if __name__ == "__main__":
    main()
