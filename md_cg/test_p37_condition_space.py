# -*- coding: utf-8 -*-
"""条件空间合成与生效条件口径（P37 · 设计态验收）。

口径：**观测位置 ≠ 生效条件**。生效条件是**整条条件空间声明的合成**——
「什么智能载体、在什么时间、使用什么方法、在什么位置、得出什么结论」这一完整
坐标；结论即「功能名」，不进生效条件。旧版取 `condition_space.observation_position`
单槽加前缀「观测位置：」冒充生效条件（真实库 109 条），本轮废止。

验收覆盖：
  ① 合成纯函数 `nodefile.condition_space_text`：槽序固定、缺失槽不写、
     四槽不全不构成声明、多值用「、」不污染槽分隔、全时窗可读化、
     具体时间窗渲染 UTC、占位槽不冒充
  ② `backfill.derive_fields` **无单槽回退**：四槽不齐 → 不生成生效条件
  ③ 生效条件进入必填口径：缺它 → `ccg_completeness.complete=False`
     → `judge_qualification` 落 BLINDSPOT（而非静默 ACCEPT）
  ④ 待补台账 `conditions_pending`：缺声明且推不出的节点可见、缺失槽可数
  ⑤ 存量清洗 `fix_conditions_*`：rewrite / drop 分流、留痕、幂等、真逆回滚
  ⑥ 复算 `verify_conditions`：弱等价残留（legacy_position）归零

运行：python -m md_cg.test_p37_condition_space
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import backfill, nodefile
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []

LEGACY_TEXT = "观测位置：某个外部观测位"


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def _full_cs():
    return {
        "observation_position": "本地文件系统（摄取器内部观测位）",
        "observation_tool": "扩展名映射表 + Ingestor",
        "time_window": [0.0, 9999999999.0],
        "existence_constraint": "仅对本地可读文件生效",
    }


def _seed(root):
    """造：四槽齐备 / 单槽 / 旧口径四槽 / 旧口径单槽，四类对照。"""
    cg = MdCGOS(root)
    cg.add("cx_full",
           "# 功能名：文件摄取分派\n\n按扩展名把文件路由到对应摄取器。\n",
           layer="knowledge", condition_space=_full_cs(),
           verification_basis="test", non_applicable_conditions=["二进制文件"],
           state_attributes={"comment": {
               "子功能": "按扩展名路由", "执行": "读映射表→调用 Ingestor"}})
    cg.add("cx_posonly",
           "# 功能名：只有观测位置的历史记忆\n\n条件空间只声明了一维。\n",
           layer="knowledge",
           condition_space={"observation_position": "某个外部观测位"},
           state_attributes={"comment": {
               "子功能": "待补：条件空间其余三维", "执行": "待补"}})
    # 旧口径落地形态：正文行与 comment 里都是「观测位置：…」单槽冒充
    cg.add("cx_legacy",
           f"# 功能名：旧口径四槽记忆\n# 生效条件：{LEGACY_TEXT}\n\n历史迁移。\n",
           layer="knowledge", condition_space=_full_cs(),
           verification_basis="test", non_applicable_conditions=["无"],
           state_attributes={"comment": {
               "生效条件": LEGACY_TEXT, "子功能": "s", "执行": "e"}})
    cg.add("cx_legacy_drop",
           f"# 功能名：旧口径单槽记忆\n# 生效条件：{LEGACY_TEXT}\n\n历史迁移。\n",
           layer="knowledge",
           condition_space={"observation_position": "某个外部观测位"})
    cg.flush()
    cg.rebuild_index()
    return cg


def _inject_legacy_log(cg, nodes):
    """把「我们自己写下的旧口径行」补进留痕——清洗的真源是留痕，不是猜测。"""
    for nid in nodes:
        backfill.append_jsonl(backfill._log_path(cg), {
            "action": "backfill", "ts": 1.0, "batch": "legacy",
            "entry_id": "legacy|" + nid, "write_id": "w|" + nid,
            "node": nid, "layer": "knowledge",
            "fields": {"生效条件": {
                "before": None, "after": LEGACY_TEXT,
                "basis": backfill.LEGACY_CONDITION_BASIS}}})


def main():
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="mdcg_p37_")
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root, exist_ok=True)
        cg = _seed(root)

        # ---------- ① 合成纯函数 ----------
        cs = {"observation_position": "观测位P",
              "observation_tool": ["工具A", "工具B"],
              "time_window": [1787914173.0, 1787917773.0],
              "existence_constraint": "仅限X"}
        t = nodefile.condition_space_text(cs)
        ok(t.startswith("载体/位置：观测位P；时间："),
           "①以「载体/位置」起头（载体与位置同源合并）")
        ok("；方法：工具A、工具B；约束：仅限X" in t,
           "①槽序固定；多值用「、」，不污染槽分隔符")
        ok(t.count("；") == 3, "①四槽 → 三段分隔（无重复段）")
        ok(nodefile.condition_space_text({"observation_position": "P"}) == "",
           "①四槽不全 → 空串（部分槽不构成条件空间声明）")
        ok(nodefile.condition_space_text({"observation_position": "P"},
                                        require_full=False) == "载体/位置：P",
           "①require_full=False 仅渲染已声明槽（展示用，非生效条件来源）")
        ok("全时窗（任意时刻成立）" in nodefile.condition_space_text({
            "observation_position": "P", "observation_tool": "T",
            "time_window": [0.0, 9999999999.0],
            "existence_constraint": "E"}),
           "①[0, 1e10] 渲染为「全时窗」（合法声明，非空占位）")
        ok("2026-" in nodefile.time_window_text([1787914173.0, 1787917773.0])
           and "（UTC）" in nodefile.time_window_text([1787914173.0, 1787917773.0]),
           "①具体时间窗渲染为 UTC 时刻（不落裸数字进召回键）")
        ok(nodefile.condition_space_text({
            "observation_position": "骨架锚点", "observation_tool": "T",
            "time_window": [0.0, 1.0], "existence_constraint": "E"}) == "",
           "①占位槽不冒充已声明（整体 fail-closed 为不可合成）")
        ok(nodefile.is_legacy_position_condition(LEGACY_TEXT)
           and not nodefile.is_legacy_position_condition(t),
           "①旧口径识别只认前缀形态（不做语义猜测）")

        # ---------- ② derive 无单槽回退 ----------
        fm_po, c_po = cg._read(cg.index["nodes"]["cx_posonly"])
        d_po = backfill.derive_fields(fm_po, c_po)
        ok("生效条件" not in d_po, "②单槽 observation_position 不生成生效条件")
        ok(bool(d_po.get("子功能")) and bool(d_po.get("执行")),
           "②其余可推字段仍照补（一项缺证据不停摆整批）")
        fm_f, c_f = cg._read(cg.index["nodes"]["cx_full"])
        d_f = backfill.derive_fields(fm_f, c_f)
        ok(d_f.get("生效条件", ("", ""))[1] == backfill.BASIS_CONDITION_SYNTH,
           "②四槽齐备 → 来源标记为「条件空间四槽合成」")
        ok(d_f["生效条件"][0] == nodefile.condition_space_text(
               fm_f.get("condition_space")),
           "②合成值 == 唯一入口 condition_space_text 的输出")

        # ---------- ③ 必填口径：缺生效条件 → BLINDSPOT ----------
        ok(nodefile.CCG_REQUIRED == nodefile.CCG_MARKS,
           "③门槛即全部 MARKS（生效条件不再可隐含）")
        ok(nodefile.ccg_completeness(c_po)["complete"] is False,
           "③缺生效条件 → complete 为 False")
        ok("生效条件" in (set(nodefile.CCG_REQUIRED)
                         - set(nodefile.ccg_completeness(c_po)["required_present"])),
           "③缺失项被精确归因到「生效条件」")
        j_po = cg.judge_qualification(
            {"frontmatter": fm_po, "content": c_po}, query="")
        ok(j_po["state"] == "BLINDSPOT",
           "③缺生效条件 → BLINDSPOT（不静默 ACCEPT）")
        ok("生效条件" in j_po.get("reason", ""), "③判定理由点名缺失项")
        # 齐全节点的正文须含全部 6 行 MARKS（ccg_completeness 只读正文）
        c_full = ("# 功能名：文件摄取分派\n"
                  f"# 生效条件：{nodefile.condition_space_text(fm_f.get('condition_space'))}\n"
                  "# 子功能：按扩展名路由\n"
                  "# 执行：读映射表→调用 Ingestor\n"
                  "# 验证方式：test（单测覆盖扩展名分派）\n"
                  "# 不适用条件：二进制文件\n\n按扩展名把文件路由到对应摄取器。\n")
        j_f = cg.judge_qualification(
            {"frontmatter": fm_f, "content": c_full}, query="")
        ok(j_f["state"] != "BLINDSPOT", "③四槽齐备且齐全 → 不误判 BLINDSPOT")

        # ---------- ④ 待补台账 ----------
        pend = backfill.conditions_pending(cg, prefix="cx_")
        ok(pend["dry_run"] is True, "④台账标记 dry_run（只读）")
        ids = [i["id"] for i in pend["items"]]
        ok("cx_posonly" in ids, "④单槽节点进台账")
        ok("cx_full" not in ids, "④四槽齐备节点不进台账")
        it_po = next(i for i in pend["items"] if i["id"] == "cx_posonly")
        # mdcos.add 在调用方未给 time_window 时以写入时刻锚定 1 小时观测窗
        # （mdcg.OBSERVATION_WINDOW_SEC），故此处缺的是方法 + 约束两维
        ok(it_po["missing_slots"] == ["observation_tool", "existence_constraint"],
           "④缺失槽逐条列出（供后续补充，不靠猜）")
        ok("BLINDSPOT" in it_po["fallback"], "④台账写明兜底裁决口径")

        # ---------- ⑤ 存量清洗：rewrite / drop ----------
        _inject_legacy_log(cg, ["cx_legacy", "cx_legacy_drop"])
        p = backfill.fix_conditions_plan(cg)
        ok(p["dry_run"] is True and p["legacy"] >= 2,
           "⑤预演识别留痕里的旧口径行")
        ok(p["rewrite"] >= 1 and p["drop"] >= 1,
           "⑤分流：四槽可合成→rewrite / 仍不全→drop")
        ok(LEGACY_TEXT in cg._read(cg.index["nodes"]["cx_legacy"])[1],
           "⑤预演不改盘")

        a = backfill.fix_conditions_apply(cg, batch="p37fix", actor="tester")
        ok(a["rewritten"] >= 1 and a["dropped"] >= 1, "⑤清洗写入非零且有留痕")
        fm_l, c_l = cg._read(cg.index["nodes"]["cx_legacy"])
        synth_l = nodefile.condition_space_text(fm_l.get("condition_space"))
        ok(f"# 生效条件：{synth_l}" in c_l,
           "⑤rewrite：冒充行改写为四槽合成声明")
        ok(fm_l["state_attributes"]["comment"]["生效条件"] == synth_l,
           "⑤rewrite：frontmatter.comment 同步到同一口径")
        fm_d, c_d = cg._read(cg.index["nodes"]["cx_legacy_drop"])
        ok("# 生效条件" not in c_d, "⑤drop：补不全的冒充行被删除")
        ok("生效条件" not in (fm_d.get("state_attributes", {}).get("comment") or {}),
           "⑤drop：comment 里的同一污染副本一并还原")
        ok(nodefile.ccg_completeness(c_d)["complete"] is False,
           "⑤drop 后节点不再「假装」齐全")
        a2 = backfill.fix_conditions_apply(cg, batch="p37fix", actor="tester")
        ok(a2["rewritten"] == 0 and a2["dropped"] == 0,
           "⑤幂等：清洗后不再有候选行")
        pend2 = backfill.conditions_pending(cg, prefix="cx_")
        ok(pend2["by_missing"].get("缺方法+约束", 0) >= 1,
           "⑤drop 转入待补台账（缺哪几维可见）")
        ok(any(r.get("action") == "condition_pending"
               for r in backfill.history(cg)["records"]),
           "⑤待补登记落留痕（可追溯，不丢证据）")

        # ---------- ⑥ 复算 + 回滚 ----------
        v = backfill.verify_conditions(cg, prefix="cx_")
        ok(v["legacy_position"] == 0, "⑥复算：弱等价残留归零（验收指标）")
        ok(v["from_synthesis"] >= 1, "⑥复算：至少一条来自四槽合成")
        r = backfill.fix_conditions_rollback(cg, batch="p37fix", actor="tester")
        ok(r["reverted"] >= 2, "⑥清洗可回滚（真逆操作，非暴力删除）")
        ok(LEGACY_TEXT in cg._read(cg.index["nodes"]["cx_legacy"])[1],
           "⑥回滚恢复被改写的旧值")
        ok(LEGACY_TEXT in cg._read(cg.index["nodes"]["cx_legacy_drop"])[1],
           "⑥回滚重建被删除的行")
        v2 = backfill.verify_conditions(cg, prefix="cx_")
        ok(v2["legacy_position"] >= 2, "⑥回滚后残留计数如实回升（复算可信）")

        print(f"\nP37 结果：{PASS} 通过 / {FAIL} 失败")
        if FAILS:
            print("失败项：")
            for f in FAILS:
                print(f"  - {f}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
