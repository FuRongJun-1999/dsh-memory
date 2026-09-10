# -*- coding: utf-8 -*-
"""G7 · 自主演化巡检（把「有能力」变成「有驱动」）（P41 设计态验收）。

对照 `docs/认知图_G4-G8缺口裁定单_v0.1.md` §五 G7：固化 / 重要性 / 去污染三类自我
演化动作早已具备，但**没有任何驱动源**周期性问「现在有多少该固化 / 该重算的候选」，
于是能力被饿死。本项给常驻循环挂上**只读**演化巡检 + **受控**自愈。

覆盖：
  ① 契约链：catalog/描述/schema 暴露 evolve 及 allow_evolve/auto_evolve/evolve_interval；
  ② 只读盘点：`evolve_check` 标 readonly/dry_run、零写盘、零改节点、代理指标显式声明；
  ③ 确定性：两次盘点候选数一致（可复核）；
  ④ 诊断集成：`diagnose()` 带 evolve 段与 info 级 issue（候补多 ≠ 库有毛病，ok 不受影响）；
  ⑤ 自愈默认关闭：`heal()` 不带 allow_evolve → 演化动作 applied=False 且给出 reason；
  ⑥ 自愈受控放行：带 allow_evolve → 只放行**确定性**动作（重要性重算）且漂移归零；
  ⑦ LLM 依赖永不自动：固化（consolidate_run）无 reflect_fn 时恒 applied=False；
  ⑧ 循环挂载：`evolve_interval` 生效、`auto_evolve=False` 时只记账；
  ⑨ 失败不拖垮常驻：巡检抛错时循环仍活着、心跳照常、last_evolve 不被污染；
  ⑩ MCP 接入：op=sustain action=evolve / catalog / heal(allow_evolve)；
  ⑪ 未知 action 不静默成功。

独立临时根，重跑 ≡ 首跑。运行：python -m md_cg.test_p41_evolve_patrol
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time

from . import sustain
from . import weights as W
from .mdcg import MdCG
from .mcp_server import KERNEL_TOOLS, call_tool

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  [FAIL] {label}")


def _digest(cg, nid):
    e = cg.index["nodes"][nid]
    with open(os.path.join(cg.root, e["path"]), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _patch(cg, nid, fm):
    """直接改写节点 frontmatter（模拟「重要性漂移」），同步索引快照。"""
    e = cg.index["nodes"][nid]
    node = cg.get(nid)
    f = dict(node["frontmatter"])
    f.update(fm)
    cg._write_node(nid, os.path.join(cg.root, e["path"]), f,
                   node.get("content") or "")
    e["importance"] = f.get("importance", e.get("importance"))


def main():
    print("md 认知图 P41 验收 · G7 自主演化巡检（只读盘点 + 受控自愈）")
    print("=" * 70)
    net = tempfile.mkdtemp(prefix="mdcg_p41_net_")
    os.environ["MDCG_SUSTAIN_DIR"] = net
    root = None
    try:
        root = tempfile.mkdtemp(prefix="mdcg_p41_")
        cg = MdCG(root)
        cg.add("n_a", "# 功能名：甲\n# 生效条件：条件 A\n\n正文甲的说明。",
               tags=["g7"])
        cg.add("n_b", "# 功能名：乙\n# 生效条件：条件 B\n\n正文乙的说明。",
               tags=["g7"])
        cg.add("n_c", "# 功能名：丙\n# 生效条件：条件 C\n\n正文丙的说明。",
               tags=["g7"])
        cg.rebuild_index()

        # ------------------------------------------------ ① 契约链
        print("\n【1】契约链（防「能力在、入口无」）")
        tool = next(t for t in KERNEL_TOOLS if t["name"] == "cg")
        prop = tool["inputSchema"]["properties"]
        desc = (tool["description"] + prop["op"]["description"]
                + prop["action"]["description"])
        ok("evolve" in desc, "①sustain 契约描述含 evolve")
        for k in ("allow_evolve", "auto_evolve", "evolve_interval"):
            ok(k in prop, f"①schema 声明 {k}")
        cat = call_tool(cg, "cg", {"op": "sustain", "action": "catalog"})
        ok("evolve" in cat["actions"], "①catalog 列出 evolve")
        ok(cat["evolve_fixes"] == {"ccg_backlog": "consolidate_run",
                                   "importance_drift": "importance"},
           "①候补项→修复动作映射显式声明")
        ok(cat["evolve_interval"] == sustain.DEFAULT_EVOLVE_INTERVAL,
           "①演化巡检间隔有默认值（不再靠人工想起来）")

        # ------------------------------------------------ ② 只读盘点
        print("\n【2】只读盘点（零写盘 / 零改节点 / 代理指标显式）")
        before = {nid: _digest(cg, nid) for nid in cg.index["nodes"]}
        ev = call_tool(cg, "cg", {"op": "sustain", "action": "evolve"})
        after = {nid: _digest(cg, nid) for nid in cg.index["nodes"]}
        ok(ev["readonly"] is True and ev["dry_run"] is True,
           "②标 readonly/dry_run")
        ok(before == after, "②节点逐字节不变")
        ok(ev["ccg_backlog"]["proxy"] is True, "②固化候补标为索引代理指标")
        ok(ev["ccg_backlog"]["n"] == 3, f"②3 条无验证基底/负条件（实测 {ev['ccg_backlog']['n']}）")
        ok(ev["importance_drift"]["scanned"] == 3, "②重要性扫全库（索引级、不读文件）")
        ok(ev["candidates"] == ev["ccg_backlog"]["n"] + ev["importance_drift"]["n"],
           "②候补总量 = 各项之和")
        ok(ev["by_fix"]["consolidate_run"] == ev["ccg_backlog"]["n"]
           and ev["by_fix"]["importance"] == ev["importance_drift"]["n"],
           "②按修复动作可归口")

        # ------------------------------------------------ ③ 确定性
        print("\n【3】确定性（可复核）")
        ev2 = sustain.evolution_candidates(cg, top=3)
        ok(ev2["ccg_backlog"]["n"] == ev["ccg_backlog"]["n"]
           and ev2["importance_drift"]["n"] == ev["importance_drift"]["n"],
           "③两次盘点候选数一致")

        # ------------------------------------------------ ④ 诊断集成
        print("\n【4】诊断集成（候补多 ≠ 库有毛病）")
        dg = call_tool(cg, "cg", {"op": "sustain", "action": "diagnose"})
        ok(dg["evolve"] is not None
           and dg["stats"]["evolve_candidates"] == ev["candidates"],
           "④diagnose 带 evolve 段与 stats")
        codes = {i["code"]: i for i in dg["issues"]}
        ok("ccg_backlog" in codes and codes["ccg_backlog"]["severity"] == "info",
           "④固化候补以 info 级呈现（不是故障）")
        ok(codes["ccg_backlog"]["fix"] == "consolidate_run"
           and codes["ccg_backlog"]["proxy"] is True, "④issue 带 fix 与代理标记")
        ok("importance_drift" in codes and codes["importance_drift"]["severity"] == "info",
           "④重要性漂移 issue")
        ok(dg["ok"] is True, "④候补多不翻转 ok（无 warning）")

        # ------------------------------------------------ ⑤ 自愈默认关闭
        print("\n【5】自愈默认关闭（不显式放行就不动）")
        hl = call_tool(cg, "cg", {"op": "sustain", "action": "heal"})
        acts = {a["code"]: a for a in hl["actions"]}
        ok(acts["consolidate_run"]["applied"] is False
           and acts["consolidate_run"]["reason"] == "needs_llm",
           "⑤固化候补不自动执行（需 LLM）")
        ok(acts["importance"]["applied"] is False
           and acts["importance"]["reason"] == "evolve_disabled",
           "⑤重要性重算默认关闭")
        ok({nid: _digest(cg, nid) for nid in cg.index["nodes"]} == before,
           "⑤heal 未改任何节点")

        # ------------------------------------------------ ⑥ 受控放行
        print("\n【6】受控放行（只放确定性动作，且漂移归零）")
        _patch(cg, "n_a", {"importance": 0.99})
        ok(W.recalc(cg)["changed"] >= 1, "⑥制造漂移（n_a 手工置 0.99）")
        hl2 = call_tool(cg, "cg", {"op": "sustain", "action": "heal",
                                   "allow_evolve": True})
        acts2 = {a["code"]: a for a in hl2["actions"]}
        ok(acts2["importance"]["applied"] is True
           and acts2["importance"]["ok"] is True,
           "⑥重要性重算被放行且执行成功")
        ok(W.recalc(cg)["changed"] == 0, "⑥漂移归零（收敛）")
        ok(acts2["consolidate_run"]["applied"] is False,
           "⑦LLM 依赖的固化仍不自动跑")

        # ------------------------------------------------ ⑧ 循环挂载
        print("\n【8】常驻循环挂载（默认只记账）")
        lp = sustain.ensure_loop(cg, "p41loop", beat_interval=0.05,
                                 heal_interval=0.05, scrub_interval=0.05,
                                 evolve_interval=0.05, auto_evolve=False, d=net)
        lp.start()
        time.sleep(0.8)
        ok(lp.last_evolve is not None, "⑧演化巡检周期触发")
        ok(lp.last_evolve["applied"] == [], "⑧auto_evolve=False → 只记账不动库")
        ok(lp.status()["evolve_interval"] == 0.05
           and lp.status()["auto_evolve"] is False, "⑧status 暴露演化字段")
        ok(sustain.summary(cg)["evolve"]["candidates"] >= 0, "⑧summary 含演化摘要")
        lp.stop()

        # ------------------------------------------------ ⑨ 失败不拖垮常驻
        print("\n【9】巡检失败不拖垮常驻")
        orig = W.recalc
        W.recalc = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            lp2 = sustain.ensure_loop(cg, "p41boom", beat_interval=0.05,
                                      heal_interval=99.0, scrub_interval=99.0,
                                      evolve_interval=0.05, d=net)
            lp2.start()
            time.sleep(0.6)
            ok(lp2.status()["running"] is True, "⑨循环仍存活")
            ok(lp2.beats >= 2, f"⑨心跳照常（beats={lp2.beats}）")
            ok(lp2.last_evolve is None, "⑨失败巡检不写脏记录")
            lp2.stop()
        finally:
            W.recalc = orig
        ok(sustain.evolution_candidates(cg)["importance_drift"]["n"] >= 0,
           "⑨恢复后巡检可用")

        # ------------------------------------------------ ⑩ 未知 action
        print("\n【10】未知 action 不静默成功")
        try:
            call_tool(cg, "cg", {"op": "sustain", "action": "evolve_x"})
            ok(False, "⑩必须报错")
        except ValueError as e:
            ok("未知 action" in str(e), "⑩未知 action 报错")
    finally:
        os.environ.pop("MDCG_SUSTAIN_DIR", None)
        sustain.stop_all()
        for d in (net, root):
            if d:
                shutil.rmtree(d, ignore_errors=True)

    print("\n" + "=" * 70)
    print(f"P41 结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        print("未通过：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
