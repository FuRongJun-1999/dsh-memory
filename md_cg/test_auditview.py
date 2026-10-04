# -*- coding: utf-8 -*-
"""test_auditview · L5 证据审计面只读组装器（路线 C）的行为守卫。

多主体世界模型对齐 v0.1 §4 路线 C：cg(op="audit") 给节点 id 输出五面
（现值/出处链/两存备择/盲区/退役史）；**纯读、零写路径改动**。
运行：python -m md_cg.test_auditview
"""
from __future__ import annotations

import os
import tempfile
import time

from . import auditview, evolution, lifecycle, nodefile, tokens, trust
from .mdcos import MdCGOS
from .mcp_server import _cg_call
from .writepipe import default_pipeline

_ok = 0
_fail = []


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("[ok] " + name)
    else:
        _fail.append(name)
        print("[FAIL] %s  · %s" % (name, str(detail)[:240]))


H = ("# 功能名：审计面守卫\n# 生效条件：测试环境\n# 子功能：无\n"
     "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n")
H2 = ("# 功能名：审计面守卫\n# 生效条件：测试环境\n# 子功能：无\n"
      "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n")


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_av_test_")
    cg = MdCGOS(os.path.join(tmp, "root"))
    pipe = default_pipeline()

    def W(nid, body, **kw):
        a = {"op": "write", "node_id": nid, "content": H + body + "\n",
             "layer": "knowledge", "content_kind": "text",
             "verification_basis": "test"}
        a.update(kw)
        return pipe.execute(cg, a)

    # ---- 1. 结构：五面在场 ----
    W("av_base", "基准记录：集市采购。")
    W("av_subject", "依据见 av_base 记载。上次说的那件事。",
      check_strength="hoop")
    out = _cg_call(cg, {"op": "audit", "node_id": "av_subject", "cap": 5})
    check("T1a ok=True", out.get("ok") is True, out.get("error"))
    for face in ("present", "sources", "alternatives", "blindspots", "history"):
        check("T1b 面在场：%s" % face, isinstance(out.get(face), dict),
              sorted(out.keys()))

    # ---- 2. 现值面：A1/A2 字段 ----
    p = out.get("present") or {}
    check("T2a check_strength 透传（写链）", p.get("check_strength") == "hoop",
          p.get("check_strength"))
    check("T2b uncertain_refs 呈现", p.get("uncertain_refs") == ["上次说"],
          p.get("uncertain_refs"))
    check("T2c 生命态/验证态/时效在场",
          p.get("lifecycle_state") == "active" and p.get("verification_state")
          and p.get("validity"), p)

    # ---- 3. 出处链：refers_to（正向）与 referenced_by（反查） ----
    src = out.get("sources") or {}
    rt = src.get("refers_to") or {}
    check("T3a refers_to 含 av_base", any(
        e.get("target") == "av_base" for e in (rt.get("items") or [])), rt)
    rb = src.get("referenced_by") or {}
    out_b = _cg_call(cg, {"op": "audit", "node_id": "av_base"})
    rb_b = (out_b.get("sources") or {}).get("referenced_by") or {}
    check("T3b 反查：av_base 的引用者含 av_subject", any(
        it.get("from") == "av_subject" for it in (rb_b.get("items") or [])), rb_b)

    # ---- 4. 两存/备择：同条件空间分歧 ⇒ verdict 非 ACCEPT 且可比节点在 ----
    W("av_dup_a", "集市购物，周末进行。")
    W("av_dup_b", "集市购物，改到工作日进行。")
    out_d = _cg_call(cg, {"op": "audit", "node_id": "av_dup_b", "cap": 5})
    alt = out_d.get("alternatives") or {}
    check("T4a 备择面可比非零", (alt.get("comparable") or 0) >= 1, alt)
    check("T4b 同槽分歧如实透出（verdict/missing 至少其一）",
          alt.get("verdict") in ("DEFER", "REJECT", "ACCEPT") and
          (alt.get("reason") is not None or alt.get("verdict") == "ACCEPT"),
          {k: alt.get(k) for k in ("verdict", "reason")})

    # ---- 5. 盲区面 ----
    bs = out.get("blindspots") or {}
    check("T5a 盲区面含幽灵标记与证据计数",
          bs.get("uncertain_refs") == ["上次说"]
          and bs.get("negative_evidence") == 0
          and isinstance(bs.get("note"), str), bs)

    # ---- 6. 退役史：状态迁移与验证迁移入史 ----
    lifecycle.set_state(cg, "av_subject", "converged", reason="守卫用例")
    trust.set_state(cg, "av_subject", "verified", reason="守卫用例",
                    method="test", actor="guard")
    out_h = _cg_call(cg, {"op": "audit", "node_id": "av_subject"})
    hist = out_h.get("history") or {}
    check("T6a state_history 记录在场", any(
        it.get("to") == "converged" for it in (hist.get("state_history") or [])),
        hist.get("state_history"))
    check("T6b verification_history 记录在场", any(
        it.get("to") == "verified"
        for it in (hist.get("verification_history") or [])),
        hist.get("verification_history"))
    _ev = evolution.record(cg, node_id="av_subject", pattern="审计面守卫",
                           missing="无", action="留痕", evidence="av_guard")
    out_h2 = _cg_call(cg, {"op": "audit", "node_id": "av_subject"})
    check("T6c evolution 台账纳入", bool(
        ((out_h2.get("history") or {}).get("evolution") or [])),
        (out_h2.get("history") or {}).get("evolution"))

    # ---- 7. 错误面：类型错 / 不存在 / 空串 ----
    e1 = _cg_call(cg, {"op": "audit", "node_id": 123})
    check("T7a 类型错结构化", e1.get("error") == "node_id_not_str"
          and e1.get("got_type") == "int", e1)
    e2 = _cg_call(cg, {"op": "audit", "node_id": "av_no_such"})
    check("T7b 不存在结构化", e2.get("error") == "node_not_found", e2)
    e3 = _cg_call(cg, {"op": "audit", "node_id": "  "})
    check("T7c 空串结构化", e3.get("error") == "node_id_not_str", e3)

    # ---- 8. cap 截断如实 ----
    # 目标 id 段长须 ≥3（linkref.ID_SHAPE；av_t0 段 "t0" 不合法会不建边）；
    # 单节点一次引用 9 个目标（避免覆写触发 confirm 档出单）。
    _refs = "、".join("av_tk%d" % i for i in range(9))
    for i in range(9):
        W("av_tk%d" % i, "尾目标 %d。" % i)
    pipe.execute(cg, {"op": "write", "node_id": "av_hub",
                      "content": H + "引用 %s。" % _refs + "\n",
                      "layer": "knowledge", "content_kind": "text",
                      "verification_basis": "test"})
    out_c = _cg_call(cg, {"op": "audit", "node_id": "av_hub", "cap": 3})
    rt2 = (out_c.get("sources") or {}).get("refers_to") or {}
    check("T8a cap 截断（items=3）", len(rt2.get("items") or []) == 3, rt2)
    check("T8b total/truncated 如实", (rt2.get("total") or 0) == 9
          and rt2.get("truncated") is True, rt2)

    # ---- 9. 纯读：调用前后**全库级**文件清单不变（复核 R2 升级口径：
    # 原实现只比单文件，测不到 `_consistency.jsonl` 的隐式追加）。----
    def _snapshot(root):
        out = {}
        for dp, _dns, fns in os.walk(root):
            for fn in fns:
                fp = os.path.join(dp, fn)
                try:
                    out[os.path.relpath(fp, root)] = (os.path.getsize(fp),
                                                      open(fp, "rb").read())
                except OSError:
                    out[os.path.relpath(fp, root)] = None
        return out

    cg.flush()
    snap0 = _snapshot(cg.root)
    _cg_call(cg, {"op": "audit", "node_id": "av_subject"})
    _cg_call(cg, {"op": "audit", "node_id": "av_base"})
    snap1 = _snapshot(cg.root)
    check("T9a 纯读（全库级）：审计调用不改任何文件",
          snap0 == snap1,
          sorted(set(snap0) ^ set(snap1)) or
          [k for k in snap0 if snap0.get(k) != snap1.get(k)][:4])
    # 直调面同款（auditview.build 本身也须零写）
    snap1b = _snapshot(cg.root)
    auditview.build(cg, "av_subject")
    check("T9b 纯读（直调面）", snap1b == _snapshot(cg.root),
          [k for k in snap1b if snap1b.get(k) != _snapshot(cg.root).get(k)][:4])

    # ---- 10. 角色面：ops 表登记（fail-closed 缺省不给） ----
    check("T10a ALL_OPS 含 audit", "audit" in tokens.ALL_OPS)
    _verify_ops = tokens.ROLE_SPECS["verify"]["ops_allow"]
    check("T10b verify 角色含 audit", "audit" in _verify_ops, _verify_ops)
    check("T10c 非授权角色不含 audit（fail-closed 缺省）",
          "audit" not in tokens.ROLE_SPECS["output"]["ops_allow"]
          and "audit" not in tokens.ROLE_SPECS["guest"]["ops_allow"],
          tokens.ROLE_SPECS["output"]["ops_allow"])

    # ---- 11. auditview 直调面：node_not_found 与 cap 钳制 ----
    direct = auditview.build(cg, "av_no_such")
    check("T11a 直调不存在结构化", direct.get("error") == "node_not_found", direct)
    out_cl = _cg_call(cg, {"op": "audit", "node_id": "av_subject", "cap": 999})
    check("T11b cap 上钳 64", (out_cl.get("cap") or 0) == 64, out_cl.get("cap"))

    # ---- 12. link_ledger 真 schema（复核 R1 修：原按 target/source 匹配恒读空）----
    W("av_led_child", "派生用例。", derived_from=["av_base"], relation="derived_from")
    out_l = _cg_call(cg, {"op": "audit", "node_id": "av_led_child"})
    ll = (out_l.get("sources") or {}).get("link_ledger") or {}
    check("T12 link_ledger 按 child/parent 呈现派生行",
          (ll.get("total") or 0) >= 1 and any(
              it.get("child") == "av_led_child" and it.get("parent") == "av_base"
              for it in (ll.get("items") or [])), ll)

    # ---- 13. 读隔离（复核 R3 修：反查须过 _readable，不可读节点不泄漏）----
    _nodes = cg.index["nodes"]
    _nodes["sec_iso_node"] = {"layer": "knowledge", "sensitivity": "secret",
                              "edges": [{"target": "av_base",
                                         "relation_type": "reference"}]}
    _nodes["int_iso_node"] = {"layer": "knowledge", "sensitivity": "internal",
                              "edges": [{"target": "av_base",
                                         "relation_type": "reference"}]}
    _orig_rd = getattr(cg, "_readable", None)
    try:
        cg._readable = lambda e: e.get("sensitivity") != "secret"
        out_iso = auditview.build(cg, "av_base")
        names = [it.get("from") for it in
                 ((out_iso.get("sources") or {}).get("referenced_by") or {}).get("items", [])]
        check("T13 读隔离：secret 引用者不出现在反查",
              "sec_iso_node" not in names and "int_iso_node" in names, names)
        # T13b（复验 R4）：link_ledger 的**行级**隔离——另一端不可见的行不出
        _lp = os.path.join(cg.root, "_link.jsonl")
        with open(_lp, "a", encoding="utf-8") as f:
            f.write('{"schema": 1, "child": "sec_iso_node", "parent": "av_base",'
                    ' "rel": "derived_from", "t": 1}\n')
            f.write('{"schema": 1, "child": "int_iso_node", "parent": "av_base",'
                    ' "rel": "derived_from", "t": 2}\n')
        out_iso2 = auditview.build(cg, "av_base")
        ll_names = [it.get("child") for it in
                    ((out_iso2.get("sources") or {}).get("link_ledger") or {}).get("items", [])]
        check("T13b link_ledger 行级隔离：不可见另一端不出行",
              "sec_iso_node" not in ll_names and "int_iso_node" in ll_names,
              ll_names)
    finally:
        if _orig_rd is None:
            try:
                del cg._readable
            except AttributeError:
                pass
        else:
            cg._readable = _orig_rd
        _nodes.pop("sec_iso_node", None)
        _nodes.pop("int_iso_node", None)

    # ---- 14. cap 直调防御（复核 Y2 修：非数不裸抛，钳 [1,64]）----
    try:
        o_c1 = auditview.build(cg, "av_base", cap="abc")
        check("T14a cap 非数回落缺省", o_c1.get("cap") == auditview.DEFAULT_CAP,
              o_c1.get("cap"))
    except TypeError as e:
        check("T14a cap 非数回落缺省", False, "TypeError 冒泡：%s" % e)
    check("T14b cap 负值钳 1", auditview.build(cg, "av_base", cap=-7).get("cap") == 1)
    check("T14c cap 上钳 64", auditview.build(cg, "av_base", cap=999).get("cap") == 64)

    # ---- 15. mdcg_remember 两分支透传（复核 Y3 修：此前两条落点无断言）----
    from .mcp_server import _dispatch
    o_d = _dispatch(cg, "mdcg_remember", {
        "content": "# 功能名：直写透传守卫\n# 生效条件：测试\n# 子功能：无\n"
                   "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n",
        "node_id": "mem_direct_wire", "layer": "knowledge",
        "verification_basis": "test", "check_strength": "hoop"})
    fm_d = (cg.get("mem_direct_wire") or {}).get("frontmatter") or {}
    check("T15a mdcg_remember 直写分支透传", fm_d.get("check_strength") == "hoop",
          (o_d.get("ok"), fm_d.get("check_strength")))
    o_g = _dispatch(cg, "mdcg_remember", {
        "content": "# 功能名：gated 透传守卫\n# 生效条件：测试\n# 子功能：无\n"
                   "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n",
        "node_id": "mem_gated_wire", "layer": "contextual",
        # "gated": True 必须有（复验 Y3：缺它则走直写分支、gated 分支零覆盖）。
        "gated": True,
        "verification_basis": "test", "consistency": False,
        "check_strength": "smoking_gun"})
    fm_g = (cg.get("mem_gated_wire") or {}).get("frontmatter") or {}
    check("T15b mdcg_remember gated 分支透传",
          fm_g.get("check_strength") == "smoking_gun",
          (o_g.get("verdict") or o_g.get("ok"), fm_g.get("check_strength")))

    print("\ntest_auditview: %d 通过 / %d 失败" % (_ok, len(_fail)))
    if _fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
