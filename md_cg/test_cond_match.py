# -*- coding: utf-8 -*-
"""正条件参与资格判定（judge_qualification v2 · 设计态验收）。

背景（外部评审 + 取证结论）：v1 的 ACCEPT 只查「六要素齐全 + 负条件未命中 +
验证基底已声明」，**生效条件（正条件）完全不参与匹配**——「没发现拒绝理由」
被冒充成「确认适用」。v2 补上正条件确认：

  ① 情境 = query + context 合成；情境为空 → 跳过正条件段不降级
     （「无情境」不能被误判成「不适用」，保 v1 兼容）。
  ② 生效条件词面（剥槽标签、按短语切、滤全时窗哨兵）任一命中情境 → 确认。
  ③ 有情境且一条都不命中 → DEFER（reason 点名未命中的条件短语）。
  ④ 整行「无条件」声明 → 合法豁免。
  ⑤ search→_emit 链路把 query 贯通进 judge（v1 恒传空串）。

运行：python -m md_cg.test_cond_match
"""
from __future__ import annotations

import os
import shutil
import tempfile

from .mdcg import (STATE_ACCEPT, STATE_BLINDSPOT, STATE_DEFER, STATE_REJECT,
                   MdCG)
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


def _doc(cond_line="# 生效条件：问浮力", neg_line="# 不适用条件：问完全无关主题"):
    return ("# 功能名：浮力计算\n" + cond_line + "\n# 子功能：按阿基米德原理算\n"
            "# 执行：代入公式\n# 验证方式：编译器/静态检查通过\n" + neg_line + "\n")


def _node(fm_extra=None, doc=None):
    fm = {"verification_basis": "compiler"}
    if fm_extra:
        fm.update(fm_extra)
    return {"frontmatter": fm, "content": doc or _doc()}


CS = {"observation_position": "本机进程", "time_window": [0, 9999999999.0],
      "observation_tool": "代码走查", "existence_constraint": "仅测试库"}


def main():
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="mdcg_cond_match_")
    try:
        # ---------- ① 纯函数：_cond_terms 确定性切分 ----------
        terms = MdCG._cond_terms(
            "载体/位置：本机进程；时间：全时窗（任意时刻成立）；"
            "方法：代码走查；约束：仅测试库")
        ok("载体/位置" not in terms and "时间" not in terms,
           "①槽标签（载体/位置、时间）被剥离，不参与命中")
        ok("本机进程" in terms and "代码走查" in terms and "仅测试库" in terms,
           "①四槽实质短语保留")
        ok(all("全时窗" not in t and "任意时刻" not in t for t in terms),
           "①全时窗哨兵短语被过滤（时间维无信息量不降级）")
        ok(MdCG._cond_terms("") == [], "①空条件 → 空词面（无从匹配即跳过）")

        # ---------- ② 判定：无情境 → 跳过正条件段（v1 兼容） ----------
        j = MdCG.judge_qualification(_node(), "", None)
        ok(j["state"] == STATE_ACCEPT and "未做正条件确认" in j["reason"],
           "②无 query 无 context → ACCEPT 且 reason 诚实标注未确认")

        # ---------- ③ 判定：query 命中正条件 → ACCEPT 且 reason 确认 ----------
        j = MdCG.judge_qualification(_node(), "问浮力", None)
        ok(j["state"] == STATE_ACCEPT and "生效条件已确认" in j["reason"],
           "③query 命中生效条件短语 → ACCEPT（reason 记录命中）")

        # ---------- ④ 判定：仅 context 命中 → ACCEPT ----------
        j = MdCG.judge_qualification(_node(), "", {"scene": "上下文提到问浮力"})
        ok(j["state"] == STATE_ACCEPT and "生效条件已确认" in j["reason"],
           "④context 命中 → ACCEPT")

        # ---------- ⑤ 判定：有情境零命中 → DEFER（核心行为变更） ----------
        j = MdCG.judge_qualification(_node(), "问电磁感应", None)
        ok(j["state"] == STATE_DEFER and "生效条件未在情境确认" in j["reason"],
           "⑤有情境但零命中 → DEFER（不再冒充 ACCEPT）")
        ok("问浮力" in j["reason"], "⑤reason 点名未命中的条件短语（可审计）")

        # ---------- ⑥ 整行「无条件」→ 豁免 ----------
        j = MdCG.judge_qualification(
            _node(doc=_doc(cond_line="# 生效条件：无条件")), "随便问点啥", None)
        ok(j["state"] == STATE_ACCEPT, "⑥显式无条件声明 → 豁免正条件匹配")

        # ---------- ⑦ frontmatter condition_space 兜底（正文行为空值） ----------
        j = MdCG.judge_qualification(
            _node(fm_extra={"condition_space": CS},
                  doc=_doc(cond_line="# 生效条件：")),
            "用代码走查核对", None)
        ok(j["state"] == STATE_ACCEPT and "生效条件已确认" in j["reason"],
           "⑦正文条件行空值时回退 condition_space 四槽合成")

        # ---------- ⑧ 负条件仍 REJECT（v1 回归） ----------
        j = MdCG.judge_qualification(
            _node(fm_extra={"non_applicable_conditions": ["问ZXQ7"]}),
            "问ZXQ7", {"query": "问ZXQ7"})
        ok(j["state"] == STATE_REJECT, "⑧负条件命中仍先于正条件走 REJECT")

        # ---------- ⑨ CCG 不全仍 BLINDSPOT（v1 回归） ----------
        bad = ("# 功能名：残缺\n# 生效条件：问浮力\n# 子功能：x\n"
               "# 执行：y\n# 不适用条件：z\n")          # 缺验证方式行
        j = MdCG.judge_qualification(
            {"frontmatter": {"verification_basis": "compiler"}, "content": bad},
            "问浮力", None)
        ok(j["state"] == STATE_BLINDSPOT, "⑨六要素不全仍 BLINDSPOT")

        # ---------- ⑩ 正条件命中但无基底 → 仍 DEFER（信任根基优先级） ----------
        no_basis = _node(doc=_doc())
        no_basis["frontmatter"] = {}
        j = MdCG.judge_qualification(no_basis, "问浮力", None)
        ok(j["state"] == STATE_DEFER and "验证基底" in j["reason"],
           "⑩正条件命中但未声明验证基底 → DEFER（不因条件确认而放行）")

        # ---------- ⑪ search→judge 链路：query 贯通（v1 恒传空串） ----------
        root = os.path.join(tmp, "root")
        os.makedirs(root, exist_ok=True)
        cg = MdCGOS(root)
        cg.add("cm_a", _doc(), layer="knowledge", verification_basis="compiler")
        cg.add("cm_b", _doc(cond_line="# 生效条件：问电磁"),
               layer="knowledge", verification_basis="compiler")
        res, _meta = cg.search("问浮力", judge=True)
        states = {r[0]["id"]: r[2] for r in res if r[0].get("id") in ("cm_a", "cm_b")}
        ok("cm_a" in states and states["cm_a"]["state"] == STATE_ACCEPT
           and "生效条件已确认" in states["cm_a"]["reason"],
           "⑪search 链路：命中节点 ACCEPT 且正条件已确认")
        if "cm_b" in states:
            ok(states["cm_b"]["state"] != STATE_ACCEPT,
               "⑪search 链路：条件无关节点不再冒充 ACCEPT")
        else:
            ok(True, "⑪search 链路：条件无关节点未进入 top-k（等效）")

        # mdcos 子类：ccg_exempt 短路优先（legacy 行为回归）
        cg.add("cm_legacy", "自由文本 legacy 节点。\n", layer="knowledge",
               ccg_exempt=True)
        e = cg.index["nodes"]["cm_legacy"]
        fm, c = cg._read(e)
        j = MdCGOS.judge_qualification({"frontmatter": fm, "content": c},
                                       "问浮力", {"query": "问浮力"})
        ok(j["state"] == STATE_DEFER, "⑫legacy ccg_exempt 仍短路 DEFER（不被正条件段覆盖）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\ncond_match: {PASS} passed, {FAIL} failed")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
