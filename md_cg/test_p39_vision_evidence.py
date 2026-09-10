# -*- coding: utf-8 -*-
"""视觉证据回填（P39 · G5 设计态验收）。

对照 `docs/认知图_G4-G8缺口裁定单_v0.1.md` §三：视觉节点证据面恒为 `{}`，
根因是产出侧只取 `model_evidence`（白箱部件不带该键）——即**证据口径未定义**。
本轮以**库外只读归档**（逐部件结构化结果）为证据源，按三档映射回填，脱敏、
不读图像、不重跑视觉。

验收覆盖：
  ① op 契约链：maintain 新增 3 个 action + `aeis_root` 参数已在工具 schema 声明；
  ② 三档映射：白箱齐备 → WHITEBOX（六字段）；缺字段/verdict 不一致 → BLINDSPOT 且不编造；
  ③ 根节点不承载四态裁定 → BLINDSPOT（root_no_verdict）；
  ④ 无归档家族 / 无家族根 → BLINDSPOT（no_source_archive / no_family_root）；
  ⑤ 脱敏：证据只落结构化字段 + 图集编号引用，目录名不进库；
  ⑥ 密文 fail-closed：密文节点跳过并计数，绝不解密回写；
  ⑦ 预演不写盘；落盘只改 frontmatter 证据面、正文一字不动；前缀外不动；
  ⑧ 可留痕：`_vision_evidence.jsonl`；⑨ 幂等：重跑 written=0；
  ⑩ 权限分档：预演放行写层、apply 走 require_admin；⑪ 回滚：按批次删证据键；
  ⑫ 未知 action 不静默成功。

独立临时根 + 临时 AEIS 证据源，重跑 ≡ 首跑。

运行：python -m md_cg.test_p39_vision_evidence
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

from . import tokens, vision_evidence as ve
from .mdcos import MdCGOS, MdCGSecure
from .mcp_server import KERNEL_TOOLS, call_tool
from .security import AccessDenied, Principal

PASS = FAIL = 0
FAILS = []
KEK = b"0123456789abcdef0123456789abcdef"


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


def _body(line):
    return line + "\n"


def _seed_sources(aeis):
    """造 AEIS 只读证据源：图集_0（parts_0.json）与图集_1（vision_nahida_1.json）。"""
    d0 = os.path.join(aeis, "data", "vision", "灵枢人物全身立绘_0")
    os.makedirs(d0, exist_ok=True)
    json.dump({
        "image_id": "0", "algo": "m0_part_extract-test",
        "parts": [
            {"type": "torso", "bbox": [100, 100, 300, 400], "confidence": 0.9,
             "cond_hash": "aaaa111122223333", "verdict": "ACCEPT",
             "verdict_reason": "condition satisfied", "fg_ratio": 0.71,
             "occluded": False, "algo": "m0_part_extract-test"},
            {"type": "upper_leg_L", "bbox": [178, 671, 409, 992],
             "confidence": 0.8, "cond_hash": "bbbb222233334444",
             "verdict": "ACCEPT", "verdict_reason": "condition satisfied",
             "fg_ratio": 0.62, "occluded": False,
             "algo": "m0_part_extract-test"},
            # 缺 occluded → 必须判 missing_field，不得编造
            {"type": "lower_arm_L", "bbox": [46, 475, 348, 671],
             "confidence": 0.7, "cond_hash": "cccc333344445555",
             "verdict": "DEFER", "verdict_reason": "clothing/occlusion covers",
             "fg_ratio": 0.51, "algo": "m0_part_extract-test"},
        ],
    }, open(os.path.join(d0, "parts_0.json"), "w", encoding="utf-8"),
        ensure_ascii=False)
    d1 = os.path.join(aeis, "data", "vision", "通用验证_纳西妲_1")
    os.makedirs(d1, exist_ok=True)
    json.dump({
        "image_id": "nahida_1", "algo": "vision_generic-test",
        "identity": {"content_hash": "deadbeefdeadbeef",
                     "cond_hash": "b457a1e26c672344"},
        "parts": [
            {"type": "head", "bbox": [10, 10, 50, 60], "confidence": 0.95,
             "cond_hash": "dddd444455556666", "verdict": "DEFER",
             "verdict_reason": "occlusion covers", "fg_ratio": 0.42,
             "occluded": True, "algo": "vision_generic-test"},
        ],
    }, open(os.path.join(d1, "vision_nahida_1.json"), "w", encoding="utf-8"),
        ensure_ascii=False)


def _seed_root(root):
    cg = MdCGOS(root)
    # 白箱齐备（imgpart，cond_hash 精确连接）
    cg.add("imgpart_t1", _body(
        "img0 部件 torso: bbox=[100, 100, 300, 400] cond_hash=aaaa111122223333 "
        "verdict=ACCEPT reason=condition satisfied fg=0.71"),
        layer="contextual", tags=["vision", "img0", "part", "torso"])
    # verdict 与归档不一致 → 不得落半可信证据
    cg.add("imgpart_t2", _body(
        "img0 部件 upper_leg_L: bbox=[178, 727, 409, 1019] "
        "cond_hash=bbbb222233334444 verdict=DEFER "
        "reason=clothing/occlusion covers fg=0.60"),
        layer="contextual", tags=["vision", "img0", "part", "upper_leg_L"])
    # 归档缺 occluded → missing_field
    cg.add("imgpart_t3", _body(
        "img0 部件 lower_arm_L: bbox=[46, 475, 348, 671] "
        "cond_hash=cccc333344445555 verdict=DEFER "
        "reason=clothing/occlusion covers fg=0.51"),
        layer="contextual", tags=["vision", "img0", "part", "lower_arm_L"])
    # 根节点：不承载四态裁定
    cg.add("imgpart_root", _body(
        "img0 人体部件树根：躯干+四肢, cond_hash=6521fde5edb09d40, 3 部件"),
        layer="contextual",
        tags=["vision", "img0", "figure_root", "6521fde5edb09d40"])
    # imgpart：无对应图集归档
    cg.add("imgpart_t9", _body(
        "img9 部件 torso: bbox=[1, 1, 2, 2] cond_hash=eeee555566667777 "
        "verdict=ACCEPT reason=x fg=0.5"),
        layer="contextual", tags=["vision", "img9", "part", "torso"])
    # vpipe：按家族根 cond_hash 定位归档
    cg.add("vpipe_root", _body(
        "图像 nahida_1 部件树根：content_hash=deadbeefdeadbeef "
        "cond_hash=b457a1e26c672344 观测域={}, 1 部件, 保护分级=pass"),
        layer="contextual", tags=["vision", "vpipe", "figure_root", "nahida_1"])
    cg.add("vpipe_p1", _body(
        "图像 nahida_1 部件 head: bbox=[10, 10, 50, 60] verdict=DEFER "
        "reason=occlusion covers fg=0.42 evidence={}"),
        layer="contextual", tags=["vision", "vpipe", "part", "head", "nahida_1"])
    # 无家族根
    cg.add("vpipe_p_orphan", _body(
        "图像 orphan_9 部件 head: bbox=[1, 1, 2, 2] verdict=ACCEPT "
        "reason=y fg=0.3 evidence={}"),
        layer="contextual", tags=["vision", "vpipe", "part", "head", "orphan_9"])
    # 有家族根但无归档
    cg.add("vpipe_root_ghost", _body(
        "图像 ghost_7 部件树根：content_hash=9988 cond_hash=99887766aabbccdd "
        "观测域={}, 1 部件, 保护分级=pass"),
        layer="contextual", tags=["vision", "vpipe", "figure_root", "ghost_7"])
    cg.add("vpipe_p_nosrc", _body(
        "图像 ghost_7 部件 head: bbox=[1, 1, 2, 2] verdict=ACCEPT "
        "reason=y fg=0.3 evidence={}"),
        layer="contextual", tags=["vision", "vpipe", "part", "head", "ghost_7"])
    # 前缀外对照（不得被扫到）
    cg.add("note_ctx", _body("情境笔记正文。"), layer="contextual", tags=["note"])
    # 跨层不漏：视觉节点若仍留在 knowledge（G4 fail-closed 未迁）也必须被扫到
    cg.add("vpipe_p_klayer", _body(
        "图像 klayer_3 部件 head: bbox=[1, 1, 2, 2] verdict=ACCEPT "
        "reason=y fg=0.3 evidence={}"),
        layer="knowledge", tags=["vision", "vpipe", "part", "head", "klayer_3"])
    cg.flush()
    # 密文节点：无密钥读不到正文 → 必须 fail-closed 跳过
    sec = MdCGSecure(root, principal=Principal(
        actor="p39s", clearance="private", can_write=True, can_admin=True),
        master_key=KEK)
    sec.add("imgpart_sec", _body(
        "img0 部件 torso: bbox=[1, 1, 2, 2] cond_hash=ffff666677778888 "
        "verdict=ACCEPT reason=z fg=0.9"),
        layer="contextual", tags=["vision", "img0", "part", "torso"],
        sensitivity="private")
    sec.flush()
    cg.rebuild_index()
    return cg


def _write_layer():
    s = tokens.role_spec("reflection")
    return Principal(tenant="default", actor="writer", clearance="internal",
                     can_write=True, can_admin=False, role="reflect",
                     layers_allow=s["layers_allow"], ops_allow=s["ops_allow"])


def main():
    global PASS, FAIL
    print("md 认知图 P39 验收 · 视觉证据回填（G5：库外只读归档 → 三档映射）")
    print("=" * 68)
    tmp = tempfile.mkdtemp(prefix="mdcg_p39_")
    ROOT = os.path.join(tmp, "root")
    AEIS = os.path.join(tmp, "aeis")
    try:
        from . import corpus
        corpus.reset_root(ROOT)
        _seed_sources(AEIS)
        cg = _seed_root(ROOT)
        cg.principal = Principal(tenant="default", actor="p39",
                                 clearance="private", can_write=True,
                                 can_admin=True, role="designer")
        AR = {"aeis_root": AEIS}

        # ------------------------------------------------ ① 契约链
        print("\n【1】op 契约链（防漏改）")
        tool = next(t for t in KERNEL_TOOLS if t["name"] == "cg")
        prop = tool["inputSchema"]["properties"]
        desc = prop["action"]["description"]
        ok(all(a in desc for a in ("vision_evidence", "vision_evidence_rollback",
                                   "vision_evidence_history")),
           "①maintain 新增 3 个 action 已在 schema 声明")
        ok("aeis_root" in prop, "①aeis_root 参数已声明")
        ok(all(a in MdCGOS.MAINTAIN_ACTIONS
               for a in ("vision_evidence", "vision_evidence_rollback",
                         "vision_evidence_history")),
           "①三个 action 已在 MAINTAIN_ACTIONS 注册")

        # ------------------------------------------------ ⑦ 预演
        print("\n【2】预演不写盘 + 三档分流")
        dry = call_tool(cg, "cg", {"op": "maintain", "action": "vision_evidence",
                                   **AR})
        ok(dry.get("dry_run") is True, "②dry_run=True")
        ok(dry.get("nodes_scanned") == 12,
           f"②扫到 12 条视觉节点（实测 {dry.get('nodes_scanned')}）")
        ok(dry.get("targeted") == 2,
           f"②白箱 2 条（实测 {dry.get('targeted')}）")
        ok(dry.get("blindspot") == 9,
           f"②盲区 9 条（实测 {dry.get('blindspot')}）")
        ok(dry.get("skipped_locked") == 1,
           f"②密文计入 skipped_locked（实测 {dry.get('skipped_locked')}）")
        bmap = {b["id"]: b for b in dry["blindspot_items"]}
        ok("vpipe_p_klayer" in bmap and bmap["vpipe_p_klayer"]["layer"] == "knowledge",
           "②层外视觉节点不漏（layer=None 全层扫描）")
        br = dry.get("blindspot_by_reason") or {}
        for r in ("verdict_mismatch", "missing_field:occluded",
                  "root_no_verdict", "no_source_archive", "no_family_root"):
            ok(br.get(r, 0) >= 1, f"②盲区归因含 {r}")
        fm0, _ = cg._read(cg.index["nodes"]["imgpart_t1"])
        ok("evidence_status" not in fm0, "②预演未写盘")

        # ------------------------------------------------ ② 六字段
        print("\n【3】白箱证据六字段（有源才落）")
        it = {i["id"]: i for i in dry["items"]}
        ev = it["imgpart_t1"]["evidence"]
        ok(ev.get("algo") == "m0_part_extract-test", "③algo 取自归档")
        ok(abs(ev.get("confidence") - 0.9) < 1e-9, "③confidence 取自归档")
        ok(ev.get("cond_hash") == "aaaa111122223333", "③cond_hash 精确连接命中")
        ok(abs(ev.get("fg_ratio") - 0.71) < 1e-9, "③fg_ratio 取节点实测")
        ok(ev.get("occluded") is False, "③occluded 取自归档")
        ok(ev.get("verdict_reason") == "condition satisfied",
           "③verdict_reason 取节点实测")
        vp = it["vpipe_p1"]["evidence"]
        ok(vp.get("cond_hash") == "dddd444455556666",
           "③vpipe 由归档补 cond_hash")
        ok(vp.get("occluded") is True and vp.get("confidence") == 0.95,
           "③vpipe 归档字段补齐")
        ok(it["vpipe_p1"]["joined_by"] == "type", "③vpipe 连接键为 type")

        # ------------------------------------------------ ⑤ 脱敏
        print("\n【4】脱敏（目录名不进库）")
        blob = json.dumps(dry, ensure_ascii=False)
        ok("纳西妲" not in blob, "④报表不含图集目录名")
        ok(it["imgpart_t1"]["source"] == "图集_0", "④白箱来源为编号引用")
        ok(it["vpipe_p1"]["source"] == "图集_1", "④vpipe 来源为编号引用")

        # ------------------------------------------------ ⑦ 落盘
        print("\n【5】落盘（只改 frontmatter 证据面 / 正文不动）")
        body0 = cg._read(cg.index["nodes"]["imgpart_t1"])[1]
        ap = call_tool(cg, "cg", {"op": "maintain", "action": "vision_evidence",
                                  "apply": True, **AR})
        ok(ap.get("written") == 11,
           f"⑤写入 11 条（白箱 2 + 盲区 9；实测 {ap.get('written')}）")
        ok(ap.get("blindspot_written") == 9, "⑤盲区计入 blindspot_written")
        ok(len(ap.get("entry_ids") or []) == 11, "⑤返回逐条留痕 id")
        cg2 = MdCGOS(ROOT)
        fm1, body1 = cg2._read(cg2.index["nodes"]["imgpart_t1"])
        ok(fm1.get("evidence_status") == "WHITEBOX", "⑤WHITEBOX 状态")
        ok(fm1.get("evidence_tier") == 2, "⑤tier=2")
        ok(fm1.get("evidence_source") == "aeis:vision:图集_0", "⑤来源脱敏编号")
        ok(fm1.get("evidence_doc") == ve.AUTHORITY_DOC, "⑤登记权威口径文档")
        ok((fm1.get("evidence") or {}).get("cond_hash") == "aaaa111122223333",
           "⑤证据写入 frontmatter")
        ok(body1 == body0, "⑤正文一字未动")
        fm2, _ = cg2._read(cg2.index["nodes"]["imgpart_t2"])
        ok(fm2.get("evidence_status") == "BLINDSPOT"
           and "evidence" not in fm2, "⑤verdict 不一致 → 证据保持空")
        ok(fm2.get("evidence_blindspot_reason") == "verdict_mismatch",
           "⑤盲区归因落库")
        fmi, _ = cg2._read(cg2.index["nodes"]["note_ctx"])
        ok("evidence_status" not in fmi, "⑤前缀外节点不动")

        # ------------------------------------------------ ⑧ 留痕
        print("\n【6】可留痕（_vision_evidence.jsonl）")
        log = [r for r in ve.read_jsonl(ve._log_path(ROOT))
               if r.get("action") == "vision_evidence"]
        ok(len(log) == 11, f"⑥留痕 11 条（实测 {len(log)}）")
        ok(all(r.get("batch") == ap.get("batch") for r in log), "⑥批次号一致")
        ok("纳西妲" not in json.dumps(log, ensure_ascii=False),
           "⑥留痕不落图集目录名")
        hist = call_tool(cg2, "cg", {"op": "maintain",
                                     "action": "vision_evidence_history"})
        ok((hist.get("total") or 0) >= 11, "⑥history 可回读")

        # ------------------------------------------------ ⑨ 幂等
        print("\n【7】幂等")
        again = call_tool(cg2, "cg", {"op": "maintain",
                                      "action": "vision_evidence",
                                      "apply": True, **AR})
        ok(again.get("written") == 0 and again.get("skipped_already") == 11,
           f"⑦重跑 written=0（实测 {again.get('written')}/"
           f"{again.get('skipped_already')}）")

        # ------------------------------------------------ ⑩ 权限
        print("\n【8】权限分档（预演放行 / apply 走 require_admin）")
        cg2.principal = _write_layer()
        ok(isinstance(call_tool(cg2, "cg", {"op": "maintain",
                                            "action": "vision_evidence", **AR}),
                      dict), "⑧写层可预演")
        denied(lambda: call_tool(cg2, "cg", {"op": "maintain",
                                             "action": "vision_evidence",
                                             "apply": True, **AR}),
               "⑧写层不可 apply")
        denied(lambda: call_tool(cg2, "cg", {"op": "maintain",
                                             "action": "vision_evidence_rollback",
                                             "batch": ap.get("batch")}),
               "⑧写层不可回滚")
        cg2.principal = Principal(tenant="default", actor="p39",
                                  clearance="private", can_write=True,
                                  can_admin=True, role="designer")

        # ------------------------------------------------ ⑪ 回滚
        print("\n【9】可回滚（按批次反向删证据键）")
        rb = call_tool(cg2, "cg", {"op": "maintain",
                                   "action": "vision_evidence_rollback",
                                   "batch": ap.get("batch")})
        ok(rb.get("reverted") == 11, f"⑨回滚 11 条（实测 {rb.get('reverted')}）")
        cg3 = MdCGOS(ROOT)
        fmr, bodyr = cg3._read(cg3.index["nodes"]["imgpart_t1"])
        ok("evidence" not in fmr and "evidence_status" not in fmr,
           "⑨证据键已清除")
        ok(bodyr == body0, "⑨回滚后正文仍一致")
        ok(len([r for r in ve.read_jsonl(ve._log_path(ROOT))
                if r.get("action") == "vision_evidence_rollback"]) == 11,
           "⑨回滚留痕 11 条")
        rb2 = call_tool(cg3, "cg", {"op": "maintain",
                                    "action": "vision_evidence_rollback",
                                    "batch": ap.get("batch")})
        ok(rb2.get("reverted") == 0, "⑨重复回滚不重复写")

        # ------------------------------------------------ ⑫ 未知 action
        print("\n【10】未知 action 不静默成功")
        try:
            call_tool(cg3, "cg", {"op": "maintain",
                                  "action": "vision_evidence_x"})
            ok(False, "⑩未知 action 必须报错")
        except ValueError as e:
            ok("未知 action" in str(e), "⑩未知 action 报错且列出可选值")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"P39 结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        print("未通过：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
