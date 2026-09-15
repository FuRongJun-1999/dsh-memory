# -*- coding: utf-8 -*-
"""条件扰动反事实实验（P-T-42/43 · 理论仓 §15 命题的可执行化）。

理论命题（docs/theory/智能的公理化基石.md §15 + 附录二可证伪标准）：
  「如果保持候选能力不变，只改变条件词，路由归属按条件发生变化，
    那么路由控制因素就是条件，而不是单纯的语义相似度。」
  可证伪口径：在保持候选能力不变、仅改变条件词的实验中，
  路由结果不按条件变化 → 命题被推翻。

本测试把该命题落为确定性反事实对照（tempdir，可复现）：
  ① 结果变：同一节点，条件词互换 → judge 四态翻转（ACCEPT↔REJECT/DEFER），3/3 组
  ② 路由变：两节点正文逐字相同（除条件行）、仅条件空间域词不同 → bucket 不同，
     且镜像对称（互换构造后桶恰好互换）
  ③ 计划变：检索路线（T0/T1 桶路 ↔ T2/T3 全局路）与 top1 归属随条件词切换；
     无路由对照下两候选得分完全相等——「分数相同、归属不同」即路由控制因素
     =条件的直接证据（相似度无法区分它们）
  ④ 混合条件 BLINDSPOT：条件声明不完整（CCG 要素残缺）→ BLINDSPOT（停止猜测）；
     如实边界：要素齐全但条件行混域词面 → 非 BLINDSPOT（当前判定序无矛盾检测）

运行：python -m md_cg.test_ccg_perturb
"""
from __future__ import annotations

import os
import shutil
import tempfile

from .mdcg import (STATE_ACCEPT, STATE_BLINDSPOT, STATE_DEFER, STATE_REJECT,
                   MdCG, TIER_BUCKET_LIKE, TIER_BUCKET_SCAN,
                   TIER_GLOBAL_LIKE, TIER_GLOBAL_SCAN)
from .nodefile import condition_space_text

PASS = FAIL = 0
FAILS = []

# 3 组条件域对（3/3 切换口径）：域词 ≥2 字（_cond_terms 滤 len<2）
PAIRS = [("电路", "光学"), ("离线", "在线"), ("急救", "保健")]


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def node_body(domain: str, other: str, *, mix: bool = False,
              drop_exec: bool = False) -> str:
    """CCG 六要素正文。除条件两行外逐字相同（能力不变口径）：
    生效条件由 condition_space_text 四槽合成（唯一入口，不手写冒充），
    域词同时落在观测位置与约束槽，供 judge 正条件词面确认。"""
    cs = {"observation_position": f"{domain}实验台",
          "time_window": [0.0, 9999999999.0],
          "observation_tool": "规程走查",
          "existence_constraint": f"{domain}域，台面设备"}
    eff = condition_space_text(cs)
    assert eff, "四槽不全不构成生效条件（fail-closed）"
    cond_line = f"# 生效条件：{eff}"
    if mix:  # 混合域词面（要素齐全，用于④边界断言）
        cond_line += f"与{other}混合域"
    lines = [f"# 功能名：域路由实验规程\n\n",
             f"本规程在声明条件域内执行标准检查流程，输出结论与依据。\n\n",
             cond_line + "\n\n",
             f"# 子功能：条件识别；规程执行；结论输出\n\n",
             f"# 执行：确认条件域 → 执行规程 → 输出结论\n\n",
             f"# 验证方式：规程执行结果落在声明条件域内即通过（measurement）\n\n",
             f"# 不适用条件：{other}\n"]
    if drop_exec:
        lines = [l for l in lines if not l.startswith("# 执行：")]
    return "".join(lines)


def strip_cond_lines(content: str) -> str:
    """剥条件两行——「能力不变」的对照口径。"""
    return "\n".join(l for l in content.splitlines()
                     if not (l.startswith("# 生效条件：")
                             or l.startswith("# 不适用条件：")))


def _node(domain: str, other: str, **kw) -> dict:
    """judge 单元测输入：fm 显式负条件（不依赖盘上解析形态）。"""
    return {"frontmatter": {"verification_basis": "measurement",
                            "non_applicable_conditions": [other]},
            "content": node_body(domain, other, **kw)}


def run(verbose: bool = False):
    global PASS, FAIL
    # ---------- ① 结果变：条件词互换 → judge 四态翻转（3/3） ----------
    for x, y in PAIRS:
        jx = MdCG.judge_qualification(_node(x, y), f"问{x}域的规程", None)
        jy = MdCG.judge_qualification(_node(x, y), f"问{y}域的规程", None)
        ok(jx["state"] == STATE_ACCEPT and "生效条件已确认" in jx["reason"],
           f"①[{x}/{y}] 本域情境 → ACCEPT（reason 记录命中）")
        ok(jy["state"] == STATE_REJECT,
           f"①[{x}/{y}] 反域情境 → REJECT（负条件命中，翻转①结果变）")
        # 镜像节点对称：条件词互换后判定恰好互换
        mjx = MdCG.judge_qualification(_node(y, x), f"问{x}域的规程", None)
        mjy = MdCG.judge_qualification(_node(y, x), f"问{y}域的规程", None)
        ok(mjx["state"] == STATE_REJECT and mjy["state"] == STATE_ACCEPT,
           f"①[{x}/{y}] 镜像节点判定对称（双向反事实）")
    # 无验证基底 → 反域下 DEFER 而非 REJECT 的次序确认（负条件优先于基底检查）
    naker = {"frontmatter": {"non_applicable_conditions": ["光学"]},
             "content": node_body("电路", "光学")}
    j = MdCG.judge_qualification(naker, "问光学域的规程", None)
    ok(j["state"] == STATE_REJECT, "①负条件 REJECT 先于验证基底 DEFER（判定序）")

    # ---------- ②③ 写入库 + 路由变 + 计划变（链路） ----------
    root = tempfile.mkdtemp(prefix="mdcg_ccg_perturb_")
    try:
        cg = MdCG(root)
        buckets = {}
        for i, (x, y) in enumerate(PAIRS):
            for side, (dom, oth) in ((f"{i}a", (x, y)), (f"{i}b", (y, x))):
                nid = f"perturb_{side}_{dom}"
                cg.add(nid, node_body(dom, oth), layer="knowledge",
                       tags=[f"domain:{dom}"], condition_space=None,
                       verification_basis="measurement")
                e = cg.index["nodes"].get(nid) or {}
                buckets[nid] = e.get("bucket")
        # ② 路由变：同能力（剥条件行后逐字相同）、不同条件域 → 不同桶
        for i, (x, y) in enumerate(PAIRS):
            a, b = f"perturb_{i}a_{x}", f"perturb_{i}b_{y}"
            ca = strip_cond_lines(cg.get(a)["content"])
            cb = strip_cond_lines(cg.get(b)["content"])
            ok(ca == cb, f"②[{x}/{y}] 两节点剥条件行后正文逐字相同（能力不变）")
            ok(buckets[a] and buckets[b] and buckets[a] != buckets[b],
               f"②[{x}/{y}] 条件域词不同 → 路由桶不同（路由归属按条件变化）")
        # ③ 计划变：检索路线与 top1 归属随条件词切换
        # （context 带 tags 定路由桶 + scene 域词面供正条件确认——两者同属情境）
        for i, (x, y) in enumerate(PAIRS):
            a, b = f"perturb_{i}a_{x}", f"perturb_{i}b_{y}"
            res, meta = cg.search("问实验规程", k=5, record=False,
                                  context={"tags": [f"domain:{x}"],
                                           "scene": f"{x}域情境检查"})
            ok(meta["tier"] in (TIER_BUCKET_LIKE, TIER_BUCKET_SCAN),
               f"③[{x}/{y}] 条件路由开启 → T0/T1 桶路（检索路线随条件变）")
            ok(bool(res) and res[0][0]["id"] == a,
               f"③[{x}/{y}] {x} 情境 → top1={a}")
            ok(res and res[0][2]["state"] == STATE_ACCEPT,
               f"③[{x}/{y}] top1 资格 ACCEPT（条件已确认）")
            res2, meta2 = cg.search("问实验规程", k=5, record=False,
                                    context={"tags": [f"domain:{y}"],
                                             "scene": f"{y}域情境检查"})
            ok(bool(res2) and res2[0][0]["id"] == b,
               f"③[{x}/{y}] {y} 情境 → top1={b}（归属随条件切换）")
            # 无路由对照：context=None → 全局路；同文两候选得分完全相等
            res3, meta3 = cg.search("问实验规程", k=8, record=False, context=None)
            ok(meta3["tier"] in (TIER_GLOBAL_LIKE, TIER_GLOBAL_SCAN),
               f"③[{x}/{y}] 无情境 → T2/T3 全局路（路由关闭对照）")
            sc = {r[0]["id"]: r[1] for r in res3}
            ok(a in sc and b in sc and abs(sc[a] - sc[b]) < 1e-9,
               f"③[{x}/{y}] 无路由时两候选得分相等——"
               f"相似度无法区分，归属由条件决定（命题直接证据）")
        # ④ 混合条件 BLINDSPOT
        j = MdCG.judge_qualification(
            _node("电路", "光学", drop_exec=True), "问电路域的规程", None)
        ok(j["state"] == STATE_BLINDSPOT and "CCG 要素不全" in j["reason"],
           "④条件声明不完整（缺执行要素）→ BLINDSPOT 停止猜测")
        j = MdCG.judge_qualification(
            _node("电路", "光学", mix=True), "问电路域的规程", None)
        ok(j["state"] == STATE_ACCEPT,
           "④边界（如实）：要素齐全+混域词面 → 非 BLINDSPOT（判定序无矛盾检测）")
        cg.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    if verbose or FAIL:
        print(f"ccg_perturb: {PASS} passed, {FAIL} failed")
        for f in FAILS:
            print(f"  - {f}")
    return FAIL == 0


def main():
    okall = run(verbose=True)
    raise SystemExit(0 if okall else 1)


if __name__ == "__main__":
    main()
