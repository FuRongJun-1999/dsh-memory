# -*- coding: utf-8 -*-
"""层归位（P38 · G4 设计态验收）。

对照 `docs/认知图_G4-G8缺口裁定单_v0.1.md` §二：批次流水账（`note_`/`milestone_`/
`retest6_`）与感知产物（`imgpart_`/`vpipe_`）混在 knowledge 层，语义上属**情境**，
需归位到 `contextual` 且**保留可召回**。

验收覆盖：
  ① op 契约链：consolidate 新增 3 个 action 与 `prefixes` 参数已在工具 schema 声明；
  ② 无前缀 → 拒绝：不给白名单即报错，**拒绝对整层无差别改写**；
  ③ 预演：只出报表不写盘；targeted 按前缀命中数；
  ④ 落盘：layer 改写 + 落点迁到 `contextual/<id>.md` + 旧文件删除 + 正文不动 + 前缀外不动；
  ⑤ 可追溯：演化账本落 `layer_shift`（before/after 可对照）；
  ⑥ 可留痕：`_maintain.jsonl` 记 `action=contextualize` + batch；
  ⑦ 可回滚：按 batch 反向迁层，落回原层原路径，并记 `contextualize_rollback`；
  ⑧ 保留召回：归位后仍可被 `op=route` 检索到（不改层白名单）；
  ⑨ 权限：写层（can_admin=False）不可归位（管理操作 require_admin）；
  ⑩ 密文 fail-closed：密文节点跳过并计数，绝不解密回写；
  ⑪ 幂等：重跑 targeted=0；
  ⑫ 未知 action 不静默成功。

独立临时根，重跑 ≡ 首跑。

运行：python -m md_cg.test_p38_contextualize
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

from . import consolidate, tokens
from .mdcos import MdCGOS, MdCGSecure
from .mcp_server import KERNEL_TOOLS, call_tool
from .security import AccessDenied, Principal

PASS = FAIL = 0
FAILS = []

PREFIXES = ["note_", "imgpart_"]
KEK = b"0123456789abcdef0123456789abcdef"   # 32 字节（crypto 硬要求）


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


def ccg(subject):
    return (f"# 功能名：{subject}\n"
            "# 生效条件：默认满足\n"
            f"# 子功能：{subject} 的条件层\n"
            f"# 执行：检索 {subject} 的证据\n"
            "# 验证方式：test\n"
            "# 不适用条件：无需例外\n\n"
            f"{subject} 的正文（不得被归位改写）。\n")


def _seed(root):
    """造 5 条待归位（note_×3 + imgpart_×2）+ 1 条对照（kp_）+ 1 条既有情境 + 1 条密文。"""
    cg = MdCGOS(root)
    for i in range(3):
        cg.add(f"note_{i}", ccg(f"批次记录{i}"), layer="knowledge", tags=["batch"])
    for i in range(2):
        cg.add(f"imgpart_{i}", ccg(f"图像部件{i}"), layer="knowledge",
               tags=["vision", "part"])
    cg.add("kp_keep", ccg("长期知识点"), layer="knowledge", tags=["keep"])
    cg.add("ctx_seed", ccg("既有情境记忆"), layer="contextual", tags=["ctx"])
    cg.flush()
    # 密文节点：无密钥实例读不到正文 → 归位必须 fail-closed 跳过
    sec = MdCGSecure(root, principal=Principal(
        actor="p38s", clearance="private", can_write=True, can_admin=True),
        master_key=KEK)
    sec.add("note_secret", ccg("密文批次记录"), layer="knowledge",
            tags=["batch"], sensitivity="private")
    sec.flush()
    cg.rebuild_index()
    return cg


def _write_layer(plain, secret=None):
    """写层 principal：可写不可管（require_admin 应拦下）。"""
    s = tokens.role_spec("reflection")
    return Principal(tenant="default", actor="writer", clearance="internal",
                     can_write=True, can_admin=False, role="reflection",
                     layers_allow=s["layers_allow"], ops_allow=s["ops_allow"])


def main():
    global PASS, FAIL
    print("md 认知图 P38 验收 · 层归位（G4：情境性内容回迁 contextual）")
    print("=" * 68)
    tmp = tempfile.mkdtemp(prefix="mdcg_p38_")
    ROOT = os.path.join(tmp, "root")
    try:
        from . import corpus
        corpus.reset_root(ROOT)
        cg = _seed(ROOT)
        cg.principal = Principal(tenant="default", actor="p38",
                                 clearance="private", can_write=True,
                                 can_admin=True, role="designer")

        # ------------------------------------------------ ① 契约链
        print("\n【1】op 契约链（防漏改）")
        tool = next(t for t in KERNEL_TOOLS if t["name"] == "cg")
        prop = tool["inputSchema"]["properties"]
        act_desc = prop["action"]["description"]
        ok(all(a in act_desc for a in ("contextualize", "contextualize_rollback",
                                       "contextualize_history")),
           "①consolidate 新增 action 已在 schema 声明")
        ok("prefixes" in prop, "①prefixes 参数已声明")

        # ------------------------------------------------ ② 无前缀拒绝
        print("\n【2】无白名单 → 拒绝对整层改写")
        try:
            call_tool(cg, "cg", {"op": "consolidate", "action": "contextualize",
                                 "apply": True})
            ok(False, "②无 prefixes 必须拒绝")
        except ValueError as e:
            ok("prefixes" in str(e), "②无 prefixes 拒绝整层改写")
        fmk0, _ = cg._read(cg.index["nodes"]["kp_keep"])
        ok(fmk0.get("layer") == "knowledge", "②拒绝后无副作用")

        # ------------------------------------------------ ③ 预演
        print("\n【3】预演不写盘")
        dry = call_tool(cg, "cg", {"op": "consolidate", "action": "contextualize",
                                   "prefixes": PREFIXES})
        ok(dry.get("dry_run") is True, "③dry_run=True")
        ok(dry.get("targeted") == 5, f"③targeted=5（实测 {dry.get('targeted')}）")
        ok(dry.get("skipped_locked") == 1,
           f"③密文节点计入 skipped_locked（实测 {dry.get('skipped_locked')}）")
        e0 = cg.index["nodes"]["note_0"]
        old_path = e0["path"]
        fm, _ = cg._read(e0)
        ok(fm.get("layer") == "knowledge" and e0["path"] == old_path,
           "③预演未改层、未迁目录")

        # ------------------------------------------------ ④ 归位落盘
        print("\n【4】归位落盘（layer + 落点；正文不动）")
        body_before = cg._read(e0)[1]
        ap = call_tool(cg, "cg", {"op": "consolidate", "action": "contextualize",
                                  "prefixes": PREFIXES, "apply": True,
                                  "reason": "G4 层归位（P38 验收）"})
        ok(ap.get("written") == 5, f"④归位 5 条（实测 {ap.get('written')}）")
        cg2 = MdCGOS(ROOT)                      # 重新加载，验证盘上结果
        e0b = cg2.index["nodes"]["note_0"]
        fm, body_after = cg2._read(e0b)
        ok(fm.get("layer") == "contextual", "④layer → contextual")
        ok(fm.get("contextualized_from") == "knowledge", "④记录来源层")
        ok(fm.get("contextualization_basis", {}).get("batch") == ap.get("batch"),
           "④记录批次依据")
        ok(e0b["path"] == "contextual/note_0.md",
           f"④落点为 contextual/<id>.md（实测 {e0b['path']}）")
        ok(not os.path.exists(os.path.join(ROOT, old_path)), "④旧文件已删除")
        ok(body_after == body_before, "④正文一字未动")
        fmk, _ = cg2._read(cg2.index["nodes"]["kp_keep"])
        ok(fmk.get("layer") == "knowledge", "④前缀外节点不动")
        fmc, _ = cg2._read(cg2.index["nodes"]["ctx_seed"])
        ok(fmc.get("layer") == "contextual", "④既有情境记忆不动")

        # ------------------------------------------------ ⑤ 演化账本
        print("\n【5】可追溯（layer_shift）")
        ev = call_tool(cg2, "cg", {"op": "evolution", "action": "entries",
                                   "limit": 100})
        blob = json.dumps(ev, ensure_ascii=False)
        ok("layer_shift" in blob, "⑤演化账本落 layer_shift")
        ok("note_0" in blob, "⑤账本可按节点追溯")

        # ------------------------------------------------ ⑥ 台账
        print("\n【6】可留痕（_maintain.jsonl）")
        recs = [r for r in consolidate._read_maintain(ROOT)
                if r.get("action") == "contextualize"]
        ok(len(recs) == 5, f"⑥台账 5 条（实测 {len(recs)}）")
        ok(all(r.get("batch") == ap.get("batch") for r in recs), "⑥批次号一致")
        ok(all(r.get("from") == "knowledge" and r.get("to") == "contextual"
               for r in recs), "⑥记录 from/to")

        # ------------------------------------------------ ⑧ 保留召回
        print("\n【7】保留可召回（不改层白名单）")
        ok("contextual" in tokens.ALL_LAYERS, "⑦contextual 仍在层白名单")
        rt = call_tool(cg2, "cg", {"op": "route", "query": "批次记录0 的正文"})
        ok("note_0" in json.dumps(rt, ensure_ascii=False)[:20000],
           "⑦归位后仍可被 route 检索到")

        # ------------------------------------------------ ⑪ 幂等
        print("\n【8】幂等")
        again = call_tool(cg2, "cg", {"op": "consolidate", "action": "contextualize",
                                      "prefixes": PREFIXES, "apply": True})
        ok(again.get("targeted") == 0 and again.get("written") == 0,
           f"⑧重跑 targeted=0（实测 {again.get('targeted')}）")

        # ------------------------------------------------ ⑨ 权限
        print("\n【9】权限分档（管理操作）")
        cg2.principal = _write_layer(cg2)
        denied(lambda: call_tool(cg2, "cg", {"op": "consolidate",
                                             "action": "contextualize",
                                             "prefixes": PREFIXES, "apply": True}),
               "⑨写层不可归位")
        cg2.principal = Principal(tenant="default", actor="p38",
                                  clearance="private", can_write=True,
                                  can_admin=True, role="designer")

        # ------------------------------------------------ ⑦ 回滚
        print("\n【10】可回滚（按批次）")
        rb = call_tool(cg2, "cg", {"op": "consolidate",
                                   "action": "contextualize_rollback",
                                   "batch": ap.get("batch")})
        ok(rb.get("reverted") == 5, f"⑩回滚 5 条（实测 {rb.get('reverted')}）")
        cg3 = MdCGOS(ROOT)
        e0c = cg3.index["nodes"]["note_0"]
        fmc, body_back = cg3._read(e0c)
        ok(fmc.get("layer") == "knowledge", "⑩layer 回到 knowledge")
        ok(e0c["path"] == old_path, f"⑩路径回到原处（实测 {e0c['path']}）")
        ok(body_back == body_before, "⑩回滚后正文仍一致")
        rb2 = [r for r in consolidate._read_maintain(ROOT)
               if r.get("action") == "contextualize_rollback"]
        ok(len(rb2) == 5, f"⑩回滚留痕 5 条（实测 {len(rb2)}）")
        hist = call_tool(cg3, "cg", {"op": "consolidate",
                                     "action": "contextualize_history"})
        ok(len(hist.get("records") or []) >= 10, "⑩history 可回读批次记录")

        # ------------------------------------------------ ⑫ 未知 action
        print("\n【11】未知 action 不静默成功")
        try:
            call_tool(cg3, "cg", {"op": "consolidate", "action": "contextualize_x"})
            ok(False, "⑪未知 action 必须报错")
        except ValueError as e:
            ok("未知 action" in str(e), "⑪未知 action 报错且列出可选值")

        # ------------------------------------------------ ⑫ 定向 id 对称
        print("\n【12】定向 id 补迁（回滚的对称操作）")
        t1 = call_tool(cg3, "cg", {"op": "consolidate", "action": "contextualize",
                                   "ids": ["note_1"], "apply": True})
        ok(t1.get("written") == 1 and t1.get("targeted") == 1,
           f"⑫定向 id 归位 1 条（实测 {t1.get('written')}）")
        cg4 = MdCGOS(ROOT)
        e1 = cg4.index["nodes"]["note_1"]
        ok(e1["path"] == "contextual/note_1.md", "⑫定向归位落点正确")
        rb1 = call_tool(cg4, "cg", {"op": "consolidate",
                                    "action": "contextualize_rollback",
                                    "batch": t1.get("batch")})
        ok(rb1.get("reverted") == 1, "⑫定向批次可单独回滚")
        cg5 = MdCGOS(ROOT)
        ok(cg5.index["nodes"]["note_1"]["path"].startswith("knowledge/"),
           "⑫定向回滚路径正确")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"P38 结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        print("未通过：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
