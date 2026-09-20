# -*- coding: utf-8 -*-
"""ccgc 验收：对话记录 → CCG 六要素编译器（V1-V20）。

运行：python -m md_cg.test_ccgc

三条判据在实现层为何是**机械可判定**的（不依赖自觉）：
  ① 「LLM 不得自己验证自己」——候选结构里没有签章字段，且 attest 机械比对
     `verifier != compiled_by`（E041）；link 再挡一次（双闸）。
  ② 「幻觉」——名实门 E010/E011：每个写入值必须是源文本字面子串，零灰区。
  ③ 「缺参数」——是编译错误（E001-E004）而非 DEFER，`success = (errors == [])`。

V16-V20 覆盖**跨调用形态**（三次独立 MCP 调用传不动对象，只能落盘）：
  候选与签章绑定在 `_ccgc_pending/`（hash 防篡改）+ 复核通道三态 + 蜂巢契约
  端到端（假执行器模拟 serve，无网络无密钥也能确定性验收「通道与签章」）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time

from . import audit, backfill, ccgc, nodefile, units
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []

DIALOG = ("文件摄取分派：按扩展名把文件路由到对应摄取器"
          "。该方法使用扩展名映射表进行路由"
          "。此功能在本地文件系统中生效"
          "。仅对本地可读文件生效"
          "。2026-09-16"
          "。通过回放测试验证"
          "。二进制文件不适用")

SLOTS = {
    "observation_position": {"value": "此功能在本地文件系统中生效"},
    "observation_tool": {"value": "该方法使用扩展名映射表进行路由"},
    "time_window": {"value": [0.0, 9999999999.0]},
    "existence_constraint": {"value": "仅对本地可读文件生效"},
}

MARKS = {
    "功能名": {"value": "文件摄取分派：按扩展名把文件路由到对应摄取器"},
    "子功能": {"value": "按扩展名把文件路由到对应摄取器"},
    "执行": {"value": "使用扩展名映射表进行路由"},
    "验证方式": {"value": "回放测试", "basis": "test"},
    "不适用条件": {"value": "二进制文件不适用"},
}


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print("  FAIL " + label)


def _has(errs, code):
    return any(str(e).startswith(code) for e in (errs or []))


def _seed(root):
    cg = MdCGOS(root)
    cg.add("tgt", "# 功能名：待编译节点\n\n占位正文。\n", layer="knowledge")
    cg.flush()
    cg.rebuild_index()
    return cg


def _fake_serve(jobs, stop, seen):
    """假蜂巢执行器：读 spec.json 写 result.json（契约与 hive 的 LLM 委托型一致）。

    用线程模拟 serve 侧的单元执行，使**复核通道与签章搬运**在无网络无密钥下
    可确定性验收——被测的是通道契约，不是模型质量。seen 记录 spec 形态供断言。
    """
    while not stop.is_set():
        try:
            names = sorted(os.listdir(jobs))
        except OSError:
            names = []
        for jid in names:
            d = os.path.join(jobs, jid)
            sp = os.path.join(d, units.SPEC_FILE)
            rp = os.path.join(d, units.RESULT_FILE)
            if not jid.startswith("h") or not os.path.isfile(sp) or os.path.exists(rp):
                continue
            try:
                with open(sp, encoding="utf-8") as f:
                    spec = json.load(f)
            except (OSError, ValueError):
                continue
            prompt = str(spec.get("user_prompt") or spec.get("prompt") or "")
            seen.update({"role": spec.get("role"), "model": spec.get("model"),
                         "prompt_len": len(prompt),
                         "prompt_has_dialog": "文件摄取分派" in prompt})
            payload = {"verdict": seen.get("verdict") or "accept",
                       "reason": "假单元复核：候选与对话原文一致",
                       "slot_corrections": {}}
            try:
                with open(rp, "w", encoding="utf-8") as f:
                    json.dump({"ok": True, "model": spec.get("model"),
                               "content": json.dumps(payload, ensure_ascii=False)},
                              f, ensure_ascii=False)
            except OSError:
                continue
        time.sleep(0.05)


def _import_mcp():
    """延迟导入工具面（避免测试顶部把 server 依赖一并拉起）。"""
    try:
        from . import mcp_server
        return mcp_server
    except Exception:                                       # noqa: BLE001
        return None


def main():
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="mdcg_ccgc_")
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root, exist_ok=True)
        cg = _seed(root)

        # ---------- V1 缺参即编译错误（裁定 B） ----------
        r = ccgc.compile_dialog("", "tgt", "agent:a1")
        ok((not r.success) and _has(r.errors, "E001"), "V1a 缺 dialog → E001")
        r = ccgc.compile_dialog(DIALOG, "", "agent:a1")
        ok((not r.success) and _has(r.errors, "E002"), "V1b 缺 node_id → E002")
        r = ccgc.compile_dialog(DIALOG, "tgt", "")
        ok((not r.success) and _has(r.errors, "E003"), "V1c 缺 actor → E003")
        r = ccgc.compile_dialog(DIALOG, "nope", "agent:a1", cg=cg)
        ok((not r.success) and _has(r.errors, "E002"), "V1d 节点不存在 → E002")
        ok(bool(r.verdict) and r.verdict.get("authority") == "VERIFICATION_UNIT",
           "V1e 终裁 authority=VERIFICATION_UNIT")

        # ---------- V2 名实门：幻觉在编译期被机械检出 ----------
        bad_slots = dict(SLOTS)
        bad_slots["observation_tool"] = {"value": "该方法使用神经网络进行路由",
                                         "span": "该方法使用神经网络进行路由"}
        r_bad = ccgc.compile_dialog(DIALOG, "tgt", "agent:a1",
                                    slots=bad_slots, marks=MARKS, cg=cg)
        ok((not r_bad.success) and _has(r_bad.errors, "E011"), "V2a 捏造值 → E011")
        ok(len(r_bad.ungrounded) >= 1, "V2b 未过门项进入 ungrounded 台账")

        bad2 = dict(SLOTS)
        bad2["observation_position"] = {"value": "此功能在本地文件系统中生效",
                                        "span": "不存在的引用文本"}
        r2 = ccgc.compile_dialog(DIALOG, "tgt", "agent:a1",
                                 slots=bad2, marks=MARKS, cg=cg)
        ok((not r2.success) and _has(r2.errors, "E010"), "V2c 引用定位失败 → E010")

        class EvilParser(object):
            """冒充 LLM 通道：给出看起来合理但源文本里没有的值。"""

            def candidates(self, dialog, ctx):
                return {"marks": dict(MARKS), "slots": dict(bad_slots)}

        r3 = ccgc.compile_dialog(DIALOG, "tgt", "agent:a1",
                                 parser=EvilParser(), cg=cg)
        ok((not r3.success) and _has(r3.errors, "E011"),
           "V2d 外部 parser 幻觉同样被 E011 拦截（结构级阻断）")

        # ---------- V3 四槽强制 ----------
        r4 = ccgc.compile_dialog(DIALOG, "tgt", "agent:a1",
                                 slots={"observation_position": SLOTS["observation_position"]},
                                 marks=MARKS, cg=cg)
        ok((not r4.success) and _has(r4.errors, "E020"), "V3a 四槽不全 → E020")

        # ---------- V4/V5 唯一合成入口 + 六要素齐备 ----------
        plain_slots = {k: v.get("value") for k, v in SLOTS.items()}
        r = ccgc.compile_dialog(DIALOG, "tgt", "agent:a1",
                                slots=SLOTS, marks=MARKS, cg=cg)
        ok(r.success, "V4a 完整入参编译成功")
        ok(r.lines.get("生效条件") == nodefile.condition_space_text(plain_slots),
           "V4b 生效条件 == nodefile.condition_space_text（唯一入口）")
        ok(set(r.lines) == set(nodefile.CCG_MARKS), "V5a 六要素齐备")
        ok(r.sources.get("verification_basis") == "test", "V5b 验证基底 test")

        # ---------- V7 自证拒绝（裁定 A 核心） ----------
        a_self = ccgc.attest("tgt", ccgc.ACCEPT, "agent:a1", "agent:a1", cg=cg)
        ok((not a_self.ok) and "E041" in a_self.error, "V7a 验证方==编译方 → E041")
        a_defer = ccgc.attest("tgt", ccgc.DEFER, "designer", "agent:a1", cg=cg)
        ok((not a_defer.ok) and "E042" in a_defer.error, "V7b DEFER 不构成签章")
        a_ok = ccgc.attest("tgt", ccgc.ACCEPT, "designer", "agent:a1",
                           evidence="设计者核对原文一致", cg=cg)
        ok(a_ok.ok and bool(a_ok.token), "V7c 编外验证方 ACCEPT → 有效签章")

        # ---------- V8 无章不写 ----------
        l0 = ccgc.link(r, None, cg=cg, apply=True)
        ok((not l0.ok) and any("E040" in e for e in l0.errors), "V8a 无签章 → E040 拒绝")
        l1 = ccgc.link(r, a_self, cg=cg, apply=True)
        ok(not l1.ok, "V8b 自证签章 → link 拒绝")
        l2 = ccgc.link(r, a_ok, cg=cg, apply=False)
        ok(l2.ok and l2.dry_run and l2.written == 0, "V8c dry-run 不写入")
        _fm_b, c_before = cg._read(cg.index["nodes"]["tgt"])
        ok(not nodefile.ccg_completeness(c_before)["complete"], "V5c link 前六要素不全")

        # ---------- link 落库 ----------
        l3 = ccgc.link(r, a_ok, cg=cg, apply=True)
        ok(l3.ok and l3.written == 6, "V8d 签章通过 → 写入六行")
        fm_after, c_after = cg._read(cg.index["nodes"]["tgt"])
        ok(nodefile.ccg_completeness(c_after)["complete"],
           "V5d link 后六要素齐备（可判定性提升）")
        ok(fm_after.get("condition_space") == plain_slots, "V4c condition_space 落 frontmatter")
        ok(fm_after.get("verification_basis") == "test", "V5e verification_basis 落盘")

        # ---------- V6 未制造条件污染 ----------
        rep = backfill.verify_conditions(cg)
        ok(rep.get("legacy_position") == 0, "V6a 弱等价残留 legacy_position == 0")
        ok(rep.get("from_synthesis", 0) >= 1, "V6b 生效条件来源=合成")

        # ---------- V9 缺验证器恒 DEFER（能力外置） ----------
        v = audit.audit("ccg_marks", {"node": "tgt"}, {})
        ok(v.get("state") == "DEFER", "V9a 未注入验证器 → DEFER（不假装通过）")
        ok(audit.kinds()["ccg_marks"]["basis"] == "test", "V9b ccg_marks 基底建议=test")

        # ---------- V11 用后续验证修正生效条件 ----------
        rc = ccgc.recalibrate("tgt", {"existence_constraint": "仅对本地可读文件生效"},
                              "agent:a1", "agent:a1", cg=cg, apply=False)
        ok(any("E041" in e for e in rc.errors), "V11a 修正方==编译方 → E041")
        rc = ccgc.recalibrate("tgt", {"生效条件": "手写条件"}, "designer", "agent:a1",
                              cg=cg, apply=False)
        ok(any("E043" in e for e in rc.errors), "V11b 非四槽键 → E043（无第二通路）")
        rc = ccgc.recalibrate("tgt", {"observation_tool": "该方法使用扩展名映射表进行路由"},
                              "designer", "agent:a1", evidence="实测复核：方法槽无误",
                              cg=cg, apply=True)
        ok(rc.ok, "V11c 编外验证方修正获准")
        _fm_r, c_r = cg._read(cg.index["nodes"]["tgt"])
        ok(nodefile.ccg_completeness(c_r)["complete"], "V11d 修正后仍齐备")
        logs = ccgc._read_jsonl(ccgc._log_path(cg))
        ok(any(x.get("action") == "ccgc_recalibrate" and x.get("slots_before") is not None
               and x.get("slots_after") is not None for x in logs),
           "V11e 修正留痕含 before/after（可溯源）")
        ok(any(x.get("action") == "ccgc_attest" for x in logs), "V11f 签章留痕可查")

        # ---------- V13 内生规则解析器：诚实下界 ----------
        r_rule = ccgc.compile_dialog(DIALOG, "tgt", "agent:a1", cg=cg)
        ok(any("下界能力" in w for w in r_rule.warnings), "V13a 未注入解析器时如实声明下界")
        bad_spans = [s for arr in r_rule.spans.values() for s in arr
                     if s and s not in DIALOG]
        ok(not bad_spans, "V13b 内生解析器引用全部 grounded")

        # ---------- V14 产物无占位残留 ----------
        ok(not any(nodefile.is_placeholder_text(x) for x in r.lines.values()),
           "V14 产物无占位残留")

        # ---------- V15 裁定 B 术语落地：单一真源 + 六要素一一对应 ----------
        ok(ccgc.CONTRACT_ROLES is nodefile.CCG_CONTRACT_ROLES,
           "V15a 术语真源唯一（ccgc 引用 nodefile，不另定义一份）")
        ok(tuple(nodefile.CCG_CONTRACT_ROLES) == tuple(nodefile.CCG_MARKS),
           "V15b 契约角色与六要素一一对应（顺序一致）")
        ok(nodefile.CCG_CONTRACT_ROLES["生效条件"] == "前置条件 precondition",
           "V15c 生效条件角色 = precondition（裁定 B）")

        # ---------- V16 pending：候选与签章绑定（跨 MCP 三次独立调用形态） ----------
        p_path = ccgc.pending_path(cg, "tgt")
        ok(bool(p_path) and ccgc.PENDING_DIR in p_path, "V16a pending 落 LAYERS 之外的冷区")
        sv = ccgc.save_pending(cg, r)
        ok(bool(sv.get("ok")) and os.path.isfile(sv["path"]) and bool(sv.get("hash")),
           "V16b 候选落盘并留内容摘要")
        got = ccgc.load_pending(cg, "tgt")
        ok(bool(got.get("ok")) and bool(got.get("hash_ok")), "V16c 读回摘要一致（原件未被改写）")
        ok(got["compiled"].lines == r.lines, "V16d 读回六行 == 编译产物（无损搬运）")
        with open(sv["path"], encoding="utf-8") as f:
            rec = json.load(f)
        rec["compiled"]["lines"]["功能名"] = "被篡改的功能名"
        with open(sv["path"], "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        lx = ccgc.link_pending(cg, "tgt", apply=True)
        ok((not lx.ok) and any("hash" in e for e in lx.errors),
           "V16e 候选被改写 → hash 不符，拒绝写入（签章只忠于原件）")
        sv = ccgc.save_pending(cg, r, a_ok)
        lz = ccgc.link_pending(cg, "tgt", apply=True, actor="agent:a1")
        ok(lz.ok and lz.written == 6, "V16f 读回原件+签章 → 落库成功")
        ok(not os.path.isfile(sv["path"]), "V16g 落库成功即清 pending（暂存非存档）")
        ok(not any(ccgc.PENDING_DIR in str(k) for k in (cg.index.get("nodes") or {})),
           "V16h pending 不进索引（冷区对检索隐身）")

        # ---------- V17 闸门：只认编外裁决，绝不假装通过 ----------
        v = audit.audit("ccg_marks", {"node_id": "tgt", "unit_verdict": "ACCEPT",
                                      "verifier": "hive:reflect:h1",
                                      "evidence": "假单元复核：与原文一致"}, {})
        ok(v.get("state") == "ACCEPT", "V17a 编外裁决+依据 → ACCEPT")
        v = audit.audit("ccg_marks", {"node_id": "tgt", "unit_verdict": "ACCEPT",
                                      "verifier": "hive:reflect:h1"}, {})
        ok(v.get("state") == "DEFER", "V17b ACCEPT 但无依据 → DEFER（无依据不通过）")
        v = audit.audit("ccg_marks", {"node_id": "tgt", "unit_verdict": "ACCEPT",
                                      "verifier": "agent:a1", "evidence": "我自己验的"},
                        {"compiled_by": "agent:a1"})
        ok(v.get("state") == "REJECT", "V17c 自证 → REJECT（E041 在闸门层再挡一次）")
        v = audit.audit("ccg_marks", {"node_id": "tgt", "unit_verdict": "ACCEPT",
                                      "evidence": "无验证方"}, {})
        ok(v.get("state") == "DEFER", "V17d 有裁决缺验证方标识 → DEFER")
        v = audit.audit("ccg_marks", {"node_id": "tgt"}, {})
        d = v.get("detail") or {}
        ok(v.get("state") == "DEFER" and bool(d.get("next")) and d.get("channel_state") in units.STATES,
           "V17e 无裁决 → DEFER 且给出下一步通道（不阻塞写路径）")
        v = audit.audit("ccg_marks", {}, {})
        ok(v.get("state") == "DEFER", "V17f 缺 node_id → DEFER")

        # ---------- V18 复核通道：三态如实 + 来源标识结构上非编译者 ----------
        ok(units.transport_name(units.HIVE, units.REFLECT, "h1") == "hive:reflect:h1",
           "V18a 蜂巢来源标识 = hive:<role>:<job>")
        ok(units.transport_name(units.HIVE, units.REFLECT, "h1") != "agent:a1",
           "V18b 来源标识结构上不可能等于编译者（裁定 A 不被误伤）")
        u = units.verdict_of('前置说明\n```json\n{"verdict":"accept","reason":"一致"}\n```')
        ok(u["verdict"] == units.ACCEPT and bool(u["parsed"]), "V18c 围栏 JSON 可解析 → ACCEPT")
        u = units.verdict_of("我无法判断这件事")
        ok(u["verdict"] == units.DEFER and not u["parsed"], "V18d 解析不出 → DEFER（不猜测）")
        u = units.verdict_of({"verdict": "drop", "reason": "与原文不符",
                              "slot_corrections": {"observation_tool": "x"}})
        ok(u["verdict"] == units.REJECT and bool(u["slot_corrections"]),
           "V18e drop → REJECT（四槽修正随裁决带回）")
        aa = units.to_attest_args({"verdict": units.ACCEPT, "reason": "一致"}, state=units.HIVE,
                                  role=units.REFLECT, job_id="h1",
                                  compiled_by=units.transport_name(units.HIVE, units.REFLECT, "h1"))
        ok(aa.get("self_verify") is True, "V18f 万一自证 → 显式标记（供上层拒绝）")
        aa = units.to_attest_args({"verdict": units.ACCEPT, "reason": "一致"}, state=units.HIVE,
                                  role=units.REFLECT, job_id="h1", compiled_by="agent:a1")
        ok(not aa.get("self_verify") and aa["verifier"].startswith("hive:reflect:"),
           "V18g 非自证：verifier 取蜂巢来源标识（不设自证标记）")
        pr = units.probe(jobs=os.path.join(tmp, "nojobs"))
        ok(pr["state"] == units.CONFIGURE and units.ENV_MODEL in pr["hint"],
           "V18h 蜂巢不可用 → 返回配置指引（不自动拉起、不假装可用）")
        pr = units.probe(jobs=os.path.join(tmp, "nojobs"), allow_degrade=True)
        ok(pr["state"] == units.SUBAGENT, "V18i 显式 allow_degrade → 子代理降级（不冒充 hive）")

        # ---------- V19/V20 端到端：假蜂巢 → 编外裁决 → 签章 → 落库 ----------
        jobs = os.path.join(tmp, "jobs")
        os.makedirs(jobs, exist_ok=True)
        # 假 serve 是**本进程内的线程**，故「该 pid 是本程序」如实为真——把本程序
        # 口径指向本进程映像名即可（v14 缺陷 E 修复后 units 判活含**身份层**：
        # 旧写法心跳 pid=本进程却让 EXE 口径指向 hive.exe，身份层判假 → 通道不可用，
        # 那不是被测缺陷而是测试自身要与新口径对齐）。
        _old_exe = os.environ.get(units.ENV_EXE)
        os.environ[units.ENV_EXE] = sys.executable
        with open(os.path.join(jobs, units.SERVE_FILE), "w", encoding="utf-8") as f:
            json.dump({"ts": int(time.time() * 1000), "pid": os.getpid()}, f)
        seen = {}
        stop = threading.Event()
        th = threading.Thread(target=_fake_serve, args=(jobs, stop, seen), daemon=True)
        th.start()
        _old_model = os.environ.get(units.ENV_MODEL)
        os.environ[units.ENV_MODEL] = "fake-unit-model"
        try:
            pr = units.probe(jobs=jobs)
            ok(pr["state"] == units.HIVE, "V19a 心跳新鲜+模型已配 → HIVE 可派发")
            rv = units.review(digest=r, dialog=DIALOG, role=units.REFLECT, node_id="tgt",
                              jobs=jobs, blocking=True, wait_s=30, cg=cg, actor="agent:a1")
            ok(rv["state"] == units.HIVE and bool(rv.get("unit")), "V19b 派发并取回编外裁决")
            ok((rv["unit"] or {}).get("verdict") == units.ACCEPT, "V19c 单元裁决解析为 ACCEPT")
            ok(seen.get("role") == units.REFLECT and seen.get("model") == "fake-unit-model"
               and seen.get("prompt_has_dialog"),
               "V19d spec 形态合蜂巢契约（role/model/复核包正文）")
            ok(str((rv.get("attest") or {}).get("verifier") or "").startswith("hive:reflect:"),
               "V19e 签章方 = 蜂巢单元标识（结构上非编译者）")
            at = ccgc.attest("tgt", rv["attest"]["verdict"], rv["attest"]["verifier"],
                             "agent:a1", evidence=rv["attest"]["evidence"] or "单元复核",
                             cg=cg)
            ok(at.ok, "V19f 蜂巢裁决可直接签章（E041 不被误伤）")
            logs = ccgc._read_jsonl(os.path.join(str(cg.root), units.LOG_NAME))
            ok(any(x.get("action") == "review" and x.get("job_id") for x in logs),
               "V19g 派发留痕（job_id 可追溯）")

            # --- V20 MCP 工具面：compile → review → attest/link 三段式 ---
            mcp = _import_mcp()
            ok(mcp is not None, "V20a 工具面可加载")
            c1 = mcp._ccg_call(cg, {"ccg": {"action": "catalog"}})
            ok(c1["ok"] and "compile" in c1["actions"] and "E041" in c1["errors"],
               "V20b catalog 自描述（动作清单 + 错误码）")
            c2 = mcp._ccg_call(cg, {"ccg": {"action": "compile", "node_id": "tgt",
                                            "dialog": DIALOG, "marks": MARKS, "slots": SLOTS}})
            ok(c2["ok"] and c2["compiled"]["success"] and c2["pending"]["ok"],
               "V20c compile 成功并落 pending（不当场写库）")
            ok("E041" in c2["hint"], "V20d hint 指向编外复核（裁定 A 对调用方可见）")
            c3 = mcp._ccg_call(cg, {"ccg": {"action": "attest", "node_id": "tgt",
                                            "verdict": "ACCEPT", "verifier": c2["compiled_by"],
                                            "compiled_by": c2["compiled_by"],
                                            "evidence": "我自己验的"}})
            ok((not c3["ok"]) and "E041" in str(c3["attest"]["error"]),
               "V20e MCP 面自证 → E041（机械拒绝，不靠自觉）")
            c4 = mcp._ccg_call(cg, {"ccg": {"action": "link", "node_id": "tgt", "apply": True}})
            ok(not c4["ok"], "V20f 自证章不构成准入 → link 拒绝")
            c5 = mcp._ccg_call(cg, {"ccg": {"action": "review", "node_id": "tgt",
                                            "jobs": jobs, "blocking": True, "wait_s": 30}})
            ok(c5["state"] == units.HIVE and c5["verdict"] == "ACCEPT" and c5["passed"] is True,
               "V20g review 取回裁决：ok/verdict/passed 三者分离")
            ok(bool((c5.get("attest") or {}).get("ok")), "V20h 拿到裁决即自动签章")
            c7 = mcp._ccg_call(cg, {"ccg": {"action": "review", "node_id": "tgt",
                                            "jobs": jobs, "blocking": False}})
            ok(c7["state"] == units.HIVE and c7["verdict"] is None and c7["passed"] is False,
               "V20j 非阻塞：派发成功但裁决未回（verdict=None，不冒充通过）")
            c6 = mcp._ccg_call(cg, {"ccg": {"action": "link", "node_id": "tgt", "apply": True}})
            ok(c6["ok"] and c6["link"]["written"] == 6, "V20i link 落库（三段式闭环）")
            c10 = mcp._ccg_call(cg, {"ccg": {"action": "link", "node_id": "tgt", "apply": True}})
            ok(not c10["ok"], "V20m 落库后 pending 已清 → 再 link 明确报错（暂存非存档）")
            c8 = mcp._ccg_call(cg, {"ccg": {"action": "units", "jobs": jobs, "doctor": True}})
            ok(c8["ok"] and c8["action"] == "units", "V20k units/doctor 走三级链体检")
            c9 = mcp._ccg_call(cg, {"ccg": {"action": "nope"}})
            ok(not c9["ok"], "V20l 未知 action → 明确报错（不静默降级）")
        finally:
            stop.set()
            th.join(timeout=3)
            if _old_model is None:
                os.environ.pop(units.ENV_MODEL, None)
            else:
                os.environ[units.ENV_MODEL] = _old_model
            if _old_exe is None:
                os.environ.pop(units.ENV_EXE, None)
            else:
                os.environ[units.ENV_EXE] = _old_exe

    finally:
        print()
        print("ccgc: PASS=%d FAIL=%d" % (PASS, FAIL))
        if FAILS:
            print("FAILS: " + "; ".join(FAILS))
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
