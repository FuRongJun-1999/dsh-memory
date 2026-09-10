# -*- coding: utf-8 -*-
"""真实库对齐（P32 · 设计态验收）。

对照 docs §五 / 交付计划：P32 交付 **CCG 回填 + 能力标签注入 + 时间线预览脱敏**。
验收覆盖：
  ① op 契约链：maintain 新增 6 个 action，工具 schema 已同步声明
  ② backfill 预演：只出报表不写盘；按「有来源才补」四态分流（可补/不全/无源/密文/脚手架）
  ③ backfill 落盘：补完即 CCG 要素齐全（6 行） + 生效条件由条件空间四槽合成
    + frontmatter 同步 + 留痕 + 幂等；单槽 observation_position **不得**冒充生效条件
  ④ backfill 回滚：按留痕反向应用；人工改写后不覆盖（守卫）
  ⑤ 密文节点 fail-closed：回填/cap 一律跳过，绝不解密回写
  ⑥ cap 注入：关键词启发式 → cap 标签 + 命中依据 + 置信度；route 返回建议能力
  ⑦ cap 回滚 / 幂等
  ⑧ 预览脱敏：时间线不回显密文碎片；有权限给明文 / 无权限给占位符
  ⑨ 权限分档：写层可预演、不可 apply/rollback

批量改写均可预演 / 可留痕 / 可回滚；独立临时根，重跑 ≡ 首跑。

运行：python -m md_cg.test_p32_backfill
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

from . import backfill, crypto, nodefile, stg, tokens
from .mdcos import MdCGOS, MdCGSecure
from .mcp_server import KERNEL_TOOLS, call_tool
from .security import AccessDenied, Principal

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


def denied(fn, label):
    try:
        fn()
    except AccessDenied:
        ok(True, label)
        return
    ok(False, label)


BF_OK = "# 功能名：文件摄取分派\n\n按扩展名把文件路由到对应摄取器。\n"
BF_NONE = "# 功能名：无来源历史记忆\n\n迁移入库，未留下任何条件声明。\n"
BF_PARTIAL = "# 功能名：半来源历史记忆\n\n只有验证基底，没有子功能与执行。\n"
BF_HINT = "# 功能名：盲区线索\n\n非既有事实，待补条件。\n"
CAP_DOC = ("# 功能名：全库导出\n# 生效条件：本地离线环境\n"
           "# 子功能：把整库导出为可搬运 JSONL\n# 执行：流式写 JSONL\n"
           "# 验证方式：实测数据（benchmark / 采样）\n# 不适用条件：无持久化介质\n")

KEK = b"0123456789abcdef0123456789abcdef"   # 32 字节（crypto 硬要求）


def _seed(root):
    """造 6 类节点 + 1 条密文节点，覆盖回填分流的所有分支。"""
    cg = MdCGOS(root)
    # 四槽齐备 → 生效条件可由条件空间合成（唯一合法结构化来源）
    cg.add("bf_ok", BF_OK, layer="knowledge",
           condition_space={
               "observation_position": "本地文件系统（摄取器内部观测位）",
               "observation_tool": "扩展名映射表 + Ingestor",
               "time_window": [0.0, 9999999999.0],
               "existence_constraint": "仅对本地可读文件生效"},
           verification_basis="test",
           non_applicable_conditions=["二进制文件", "超过 50MB 的文件"],
           state_attributes={"comment": {
               "子功能": "按扩展名路由到对应摄取器",
               "执行": "读后缀映射表→调用对应 Ingestor"}})
    # 只有单槽 → **不得**冒充生效条件（观测位置 ≠ 生效条件）
    cg.add("bf_posonly",
           "# 功能名：只有观测位置的历史记忆\n\n条件空间只声明了一维。\n",
           layer="knowledge",
           condition_space={"observation_position": "某个外部观测位"},
           state_attributes={"comment": {
               "子功能": "待补：条件空间其余三维",
               "执行": "待补"}})
    cg.add("bf_none", BF_NONE, layer="knowledge")
    cg.add("bf_partial", BF_PARTIAL, layer="knowledge", verification_basis="data")
    cg.add("bf_hint", BF_HINT, layer="contextual", tags=["gap_hint"])
    cg.add("cap_export", CAP_DOC, layer="knowledge", verification_basis="test")
    cg.flush()

    sec = MdCGSecure(root, principal=Principal(
        actor="p32", clearance="private", can_write=True, can_admin=True),
        master_key=KEK)
    sec.add("bf_lock", "# 功能名：私有密文记忆\n\n敏感正文，不进回填。\n",
            layer="knowledge", sensitivity="private")
    sec.flush()
    cg.rebuild_index()   # 让明文实例也看见密文节点（否则计数缺失）
    return cg


def main():
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="mdcg_p32_")
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root, exist_ok=True)
        cg = _seed(root)

        # ---------- ① op 契约链 ----------
        blob = json.dumps(KERNEL_TOOLS, ensure_ascii=False)
        ok("backfill" in blob and "cap_history" in blob,
           "①工具 schema 声明 maintain 的 backfill/cap action")
        ok(all(a in MdCGOS.MAINTAIN_ACTIONS for a in backfill.ACTIONS),
           "①ALL_OPS 之外的 action 真源 == MAINTAIN_ACTIONS")
        ok(set(backfill.CAP_RULES) <= set(tokens.ALL_OPS),
           "①cap 规则只含真实 op（不注入无效能力名）")

        # ---------- ② backfill 预演（不改盘） ----------
        p1 = backfill.plan(cg)
        ok(p1["dry_run"] is True, "②预演标记 dry_run")
        ok("bf_ok" in p1["planned_ids"], "②有来源节点进入可回填清单")
        ok(p1["targeted"] >= 1, "②targeted 计数非零")
        ok(p1["skipped_locked"] >= 1, "②密文节点计入 skipped_locked")
        ok(p1["unfillable"] >= 1, "②无来源节点计入 unfillable（不编造）")
        ok(p1["skipped_derived"] >= 1, "②gap_hint 脚手架计入 skipped_derived")
        ok(p1["skipped_partial"] >= 1, "②补完仍不全者默认跳过（partial）")
        item = next(i for i in p1["items"] if i["id"] == "bf_ok")
        ok(item["class"] == "backfillable", "②bf_ok 判定为 backfillable")
        ok(item["fill"]["验证方式"]["basis"].startswith(
            "frontmatter.verification_basis"), "②验证方式来源可追溯（basis）")
        fm0, c0 = cg._read(cg.index["nodes"]["bf_ok"])
        ok("# 子功能：" not in c0, "②预演不改盘（正文无新增 CCG 行）")

        # 口径修正防回归：单槽 observation_position **不得**冒充生效条件
        fm_po, c_po = cg._read(cg.index["nodes"]["bf_posonly"])
        ok("生效条件" not in backfill.derive_fields(fm_po, c_po),
           "②单槽 observation_position 不生成生效条件（观测位置 ≠ 生效条件）")
        ok(nodefile.condition_space_text(
            fm_po.get("condition_space")) == "",
           "②四槽不全时合成函数返回空串（部分槽不构成声明）")

        # 待补台账：缺声明且推不出的节点必须可见，不得静默 ACCEPT
        pend = backfill.conditions_pending(cg)
        ok(pend["dry_run"] is True, "②待补台账标记 dry_run")
        po = next((i for i in pend["items"] if i["id"] == "bf_posonly"), None)
        # add 在未给 time_window 时以写入时刻锚定 1 小时观测窗，故缺方法 + 约束
        ok(po is not None and po["missing_slots"] == [
            "observation_tool", "existence_constraint"],
           "②单槽节点进待补台账并逐条列出缺失槽")
        ok("bf_ok" not in [i["id"] for i in pend["items"]],
           "②四槽齐备节点不进待补台账")

        # ---------- ③ backfill 落盘 ----------
        fm_pre = json.loads(json.dumps(cg._read(
            cg.index["nodes"]["bf_ok"])[0].get("state_attributes")))
        a1 = backfill.apply(cg, batch="p32a", actor="tester")
        ok(a1["written"] >= 1, "③apply 写入非零")
        fm1, c1 = cg._read(cg.index["nodes"]["bf_ok"])
        ok(nodefile.ccg_completeness(c1)["complete"] is True,
           "③bf_ok 回填后 CCG 要素齐全（6 行缺一不可）")
        synth = nodefile.condition_space_text(fm1.get("condition_space"))
        ok(f"# 生效条件：{synth}" in c1,
           "③生效条件 == 条件空间四槽合成（唯一口径）")
        ok("观测位置：" not in c1, "③正文不再出现单槽冒充形态")
        ok(nodefile.is_full_time_window(
            (fm1.get("condition_space") or {}).get("time_window")),
           "③前置：全时窗哨兵（[0, 1e10] 表示任意时刻成立）")
        ok("全时窗（任意时刻成立）" in c1,
           "③全时窗渲染为可读声明（不落裸数组进召回键）")
        ok(fm1.get("state_attributes", {}).get("comment", {}).get("子功能")
           == "按扩展名路由到对应摄取器", "③frontmatter.comment 同步")
        ok(fm1.get("non_applicable_conditions") == ["二进制文件", "超过 50MB 的文件"],
           "③不适用条件同步为列表")
        h = backfill.history(cg, action="backfill")
        ok(h["total"] >= 1, "③留痕 _backfill.jsonl 非空")
        it = next(r for r in h["records"] if r["node"] == "bf_ok")
        ok("basis" in it["fields"]["执行"] and it["fields"]["执行"]["after"],
           "③留痕含 before/after/依据")

        # 幂等：再跑一次不重复写
        a2 = backfill.apply(cg, batch="p32a", actor="tester")
        ok(a2["written"] == 0, "③幂等：已完成节点不重复写")

        # ---------- ④ 回滚（真逆操作：还原而非暴力删除） ----------
        rb = backfill.rollback(cg, batch="p32a", actor="tester")
        ok(rb["reverted"] >= 1, "④回滚撤销非零")
        fm2, c2 = cg._read(cg.index["nodes"]["bf_ok"])
        ok("# 子功能：" not in c2, "④回滚移除 CCG 行")
        ok(fm2.get("state_attributes") == fm_pre,
           "④frontmatter 还原到改写前（comment 不被误删）")
        ok(backfill.apply(cg, batch="p32a2", actor="tester")["written"] >= 1,
           "④还原后可再次回填（回滚为真逆操作）")
        backfill.rollback(cg, batch="p32a2", actor="tester")

        # 守卫：回填后再人工改写 → 不覆盖
        backfill.apply(cg, batch="p32b", actor="tester")
        e = cg.index["nodes"]["bf_ok"]
        fm3, c3 = cg._read(e)
        c3 = c3.replace("# 执行：读后缀映射表→调用对应 Ingestor",
                        "# 执行：人工改写过的执行方式")
        cg._write_node("bf_ok", os.path.join(root, e["path"]), fm3, c3,
                       durable=True)
        cg.rebuild_index()
        rb2 = backfill.rollback(cg, batch="p32b", actor="tester")
        fm4, c4 = cg._read(cg.index["nodes"]["bf_ok"])
        ok("人工改写过的执行方式" in c4, "④回滚守卫：人工改写字段不被撤销")
        ok(rb2["conflict"] >= 1, "④回滚守卫计入 conflict")

        # ---------- ⑤ 密文 fail-closed ----------
        e5 = cg.index["nodes"]["bf_lock"]
        _, c5 = cg._read(e5)
        ok(crypto.is_encrypted(c5), "⑤前置：bf_lock 正文确为密文")
        ok("bf_lock" not in backfill.plan(cg)["planned_ids"], "⑤回填跳过密文节点")
        ok("bf_lock" not in backfill.cap_plan(cg)["planned_ids"], "⑤cap 跳过密文节点")

        # ---------- ⑥ cap 注入 ----------
        cp = backfill.cap_plan(cg)
        ok(cp["dry_run"] is True, "⑥cap 预演标记 dry_run")
        hit = next((i for i in cp["items"] if i["id"] == "cap_export"), None)
        ok(hit is not None, "⑥关键词命中节点进入 cap 清单")
        exp = next(h for h in hit["caps"] if h["cap"] == "export")
        ok("导出" in exp["matched_by"], "⑥cap 命中依据（matched_by）可核查")
        ok(0.0 < exp["confidence"] <= 1.0, "⑥cap 置信度落在 (0,1]")
        ca = backfill.cap_apply(cg, batch="p32cap", actor="tester")
        ok(ca["written"] >= 1, "⑥cap_apply 写入非零")
        fm6, _ = cg._read(cg.index["nodes"]["cap_export"])
        ok("cap:export" in (fm6.get("tags") or []), "⑥cap:export 注入 frontmatter.tags")
        ca2 = backfill.cap_apply(cg, batch="p32cap", actor="tester")
        ok(ca2["written"] == 0, "⑥cap 幂等：重复注入不重复写")
        rt = call_tool(cg, "cg", {"op": "route", "query": "全库导出 JSONL"})
        caps = rt.get("suggested_capabilities") or []
        ok("export" in caps, "⑥route 返回建议能力名（cap: 标签生效）")
        crb = backfill.cap_rollback(cg, batch="p32cap", actor="tester")
        fm7, _ = cg._read(cg.index["nodes"]["cap_export"])
        ok("cap:export" not in (fm7.get("tags") or []), "⑦cap_rollback 移除标签")
        ok(crb["reverted"] >= 1, "⑦cap_rollback 计数非零")

        # ---------- ⑧ 预览脱敏 ----------
        plain = MdCGOS(root)
        tl = stg.timeline(plain, limit=100)
        pv = next((i["preview"] for i in tl["items"] if i["id"] == "bf_lock"), None)
        ok(pv == stg.PLACEHOLDER_LOCKED, "⑧无密钥：密文节点预览为占位符")
        ok(pv is not None and "ENC1" not in pv and "封" not in pv,
           "⑧预览不回显密文碎片")
        sec_pub = MdCGSecure(root, principal=Principal(
            actor="p32pub", clearance="internal", can_write=False),
            master_key=KEK)
        tl2 = stg.timeline(sec_pub, limit=100)
        pv2 = next((i["preview"] for i in tl2["items"] if i["id"] == "bf_lock"), None)
        ok(pv2 == stg.PLACEHOLDER_DENIED, "⑧密级不足：预览为无权限占位符")
        sec_ok = MdCGSecure(root, principal=Principal(
            actor="p32", clearance="private", can_write=True, can_admin=True),
            master_key=KEK)
        tl3 = stg.timeline(sec_ok, limit=100)
        pv3 = next((i["preview"] for i in tl3["items"] if i["id"] == "bf_lock"), None)
        ok(pv3 is not None and "敏感正文" in pv3, "⑧有密钥且有权限：预览为明文")

        # ---------- ⑨ 权限分档 ----------
        wp = Principal(role="reflection", actor="p32w", clearance="internal",
                       can_write=True, can_admin=False, ops_allow=("maintain",))
        wcg = MdCGSecure(root, principal=wp)
        ok(call_tool(wcg, "cg", {"op": "maintain", "action": "backfill"})
           .get("dry_run") is True, "⑨写层可预演 backfill")
        ok(call_tool(wcg, "cg", {"op": "maintain", "action": "cap"})
           .get("dry_run") is True, "⑨写层可预演 cap")
        denied(lambda: call_tool(wcg, "cg", {"op": "maintain",
                                             "action": "backfill", "apply": True}),
               "⑨写层不可 apply backfill（需管理权）")
        denied(lambda: call_tool(wcg, "cg", {"op": "maintain",
                                             "action": "cap", "apply": True}),
               "⑨写层不可 apply cap（需管理权）")
        denied(lambda: call_tool(wcg, "cg", {"op": "maintain",
                                             "action": "cap_rollback"}),
               "⑨写层不可 cap_rollback（需管理权）")
        try:
            call_tool(cg, "cg", {"op": "maintain", "action": "backfill_nope"})
            ok(False, "⑨未知 action 应报错而非静默成功")
        except Exception:                              # noqa: BLE001
            ok(True, "⑨未知 action 报错")

        # ---------- 收尾 ----------
        print(f"\nP32 结果：{PASS} 通过 / {FAIL} 失败")
        if FAILS:
            print("失败项：")
            for f in FAILS:
                print(f"  - {f}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
