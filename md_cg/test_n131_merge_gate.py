# -*- coding: utf-8 -*-
"""N131 守卫：review_decide(merge) 的目标写入必须过 add 同款双闸。

缺陷形态（2026-09-25 引擎域新发现，编号 N131，high）：review_decide 的
merge 分支（mdcos.py:2221-2255）把提案内容直接 _write_node 追加进任意
merge_into 目标节点，绕过 guard_write 与 require_layer_write——accept/edit
走 self.add()（:2211）有 MdCGSecure.add :3769 require_layer_write 与基类
add mdcg.py:1311 guard_write 双闸，merge 直写零闸；mcp_server review_decide
注释「accept/edit 落节点时的层写仍由下游 require_layer_write 拦截」对 merge
不成立，orchestr 角色 forbidden「anchor/self/goals/knowledge 层」
（tokens.py:123）被打穿。

攻击面：持 review+write op 的令牌（orchestr 的 ops_allow 两者皆含，
tokens.py:120；designer 全权）——propose 任意内容 → review_decide(pid,
decision="merge", merge_into=<self/anchor/immutable/knowledge 任意节点 id>)
注入任意文本。

修复：merge 分支在 _write_node 之前接与 add 同款双闸——principal 在位先
require_layer_write(目标层, 目标敏感度)（与 MdCGSecure.add 同序同错型），
再 guard_write（self/anchor 层、immutable 标记，对照 add :1311；override
显式传参时快照+留痕放行，与 add 能力面对齐）；闸在 _record_decision 之前
抛出——裁决不落库、提案留 pending（审计节点写入本就在 try/except 内，
闸放那里会被吞成 record_error，形同虚设）。

红项 = R1-R4（self/immutable 目标引擎面 + knowledge/self 目标 orchestr 面
注入复现）；G 项锁语义不变（普通目标 merge 追加、orchestr 本职 contextual
目标放行、designer override 放行）+ 两对照（orchestr add self 被拒 /
designer add 覆 immutable 被拒——闸原本就在，只是 merge 绕过）。
运行：python -m md_cg.test_n131_merge_gate
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

try:
    from . import protect
    from .mdcos import MdCGOS, MdCGSecure
    from .security import AccessDenied, Principal
except ImportError:                                  # 直接脚本运行
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from md_cg import protect
    from md_cg.mdcos import MdCGOS, MdCGSecure
    from md_cg.security import AccessDenied, Principal

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


_MARK = "攻击者注入段落"


def _body(name):
    return (f"# 功能名：{name}\n# 生效条件：无条件\n# 子功能：无\n"
            f"# 执行：无\n# 验证方式：test\n# 不适用条件：无\n\n原始正文。")


def _content_of(cg, nid):
    n = cg.get(nid)
    return (n or {}).get("content") or ""


def _merge_must_reject(cg, pid, target, exc_type, label):
    """merge 进 target：期望 exc_type 且目标内容原样。"""
    raised = None
    try:
        cg.review_decide(pid, "merge", merge_into=target)
    except exc_type as exc:
        raised = exc
    ok(raised is not None, f"{label}1 merge 进 {target} 被拒（{exc_type.__name__}）")
    ok(_MARK not in _content_of(cg, target),
       f"{label}2 拒绝后 {target} 正文无注入内容")


def _base_shape(tmp):
    """A：基类引擎面（无令牌）——self/immutable 目标不得被 merge 直写。"""
    print("--- A 基类引擎面：guard_write 闸")
    root = os.path.join(tmp, "base")
    cg = MdCGOS(root)
    cg.add("tgt_self", _body("自我目标"), layer="self")
    cg.add("tgt_imm", _body("不可覆盖目标"), layer="knowledge", immutable=True)
    cg.add("tgt_plain", _body("普通目标"), layer="knowledge")
    ok(protect.is_immutable(cg, "tgt_imm")[0],
       "A0 预置生效：tgt_imm 判定为不可覆盖")
    for nid in ("p_self", "p_imm", "p_plain"):
        cg.propose(nid, _body(nid) + "\n" + _MARK + "\n", layer="knowledge")

    _merge_must_reject(cg, next(r["pid"] for r in cg.review_list()
                                if r["id"] == "p_self"),
                       "tgt_self", protect.ProtectionError, "R1_self")
    _merge_must_reject(cg, next(r["pid"] for r in cg.review_list()
                                if r["id"] == "p_imm"),
                       "tgt_imm", protect.ProtectionError, "R2_immutable")

    # G1：普通目标 merge 照常放行（test_merge_upsert / test_p2 语义不变）
    pid_plain = next(r["pid"] for r in cg.review_list() if r["id"] == "p_plain")
    r = cg.review_decide(pid_plain, "merge", merge_into="tgt_plain")
    ok(r.get("ok") and r.get("node_id") == "tgt_plain",
       "G1a 普通 knowledge 目标 merge 照常放行")
    ok(_MARK in _content_of(cg, "tgt_plain"),
       "G1b 追加内容进入目标正文（merge 本职不变）")
    cg.close()


def _secure_shape(tmp):
    """B：MdCGSecure 面——merge 按目标层做 require_layer_write（orchestr 面）。"""
    print("--- B 安全面：orchestr 层写校验")
    root = os.path.join(tmp, "secure")
    designer_p = Principal(actor="designer-1", role="designer", can_write=True,
                           can_admin=True, clearance="secret")
    orch_p = Principal(actor="orch-1", role="orchestr", can_write=True,
                       can_admin=False, clearance="internal",
                       layers_allow=["contextual", "unresolved", "rejected"],
                       ops_allow=["info", "route", "read", "write", "review"])
    cg = MdCGSecure(root, principal=designer_p, master_key=bytes(range(32)))
    cg.add("t_kn", _body("知识目标"), layer="knowledge")
    cg.add("t_ctx", _body("情境目标"), layer="contextual")
    cg.add("t_self", _body("自我目标"), layer="self")
    cg.close()

    # 对照 R3：orchestr 直接 add 写 self 层被拒（身份确实受限，闸原本就在）
    cg = MdCGSecure(root, principal=orch_p, master_key=bytes(range(32)))
    denied = None
    try:
        cg.add("x_self", _body("越权"), layer="self")
    except AccessDenied as exc:
        denied = exc
    ok(denied is not None, "R3 对照：orchestr add 写 self 层被拒（AccessDenied）")

    # R4/R5：orchestr merge 注入 knowledge / self 层目标——旧码双写路径全绕
    #（提案内容须互异：propose 按 payload_hash 幂等去重，同内容返回既有 pid）
    pid_kn = cg.propose("a_kn", _body("提案注入知识") + "\n" + _MARK + "知识\n",
                        layer="contextual")
    _merge_must_reject(cg, pid_kn, "t_kn", AccessDenied, "R4_orch_knowledge")
    pid_self = cg.propose("a_self", _body("提案注入自我") + "\n" + _MARK + "自我\n",
                          layer="contextual")
    _merge_must_reject(cg, pid_self, "t_self", AccessDenied, "R5_orch_self")

    # G2：orchestr 本职可写层（contextual）目标 merge 照常放行
    pid_ctx = cg.propose("a_ctx", _body("提案注入情境") + "\n" + _MARK + "情境\n",
                         layer="contextual")
    r = cg.review_decide(pid_ctx, "merge", merge_into="t_ctx")
    ok(r.get("ok") and _MARK in _content_of(cg, "t_ctx"),
       "G2 orchestr merge 进本职 contextual 目标放行且内容追加（本职不变）")
    cg.close()

    # 对照 R6：designer add 覆写 immutable 既有节点被拒（guard_write 对照）+
    # G3：designer merge 带 override 进 immutable 目标显式放行（快照+留痕）
    cg = MdCGSecure(root, principal=designer_p, master_key=bytes(range(32)))
    cg.add("t_imm2", _body("不可覆盖"), layer="knowledge", immutable=True)
    prot = None
    try:
        cg.add("t_imm2", _body("覆写"), layer="knowledge")
    except protect.ProtectionError as exc:
        prot = exc
    ok(prot is not None, "R6 对照：designer add 覆写 immutable 节点被拒"
                         "（ProtectionError）")
    cg.close()

    cg = MdCGSecure(root, principal=designer_p, master_key=bytes(range(32)))
    pid_ov = cg.propose("a_ov", _body("提案") + "\n" + _MARK + "\n",
                        layer="knowledge")
    r = cg.review_decide(pid_ov, "merge", merge_into="t_imm2", override=True)
    ok(r.get("ok") and _MARK in _content_of(cg, "t_imm2"),
       "G3a designer override=True merge 进 immutable 目标显式放行")
    hist = protect.history(cg, "t_imm2")
    ok(len(hist) >= 1, "G3b override 放行前旧版本已快照 _protected_history")
    audit = os.path.join(cg.root, protect.AUDIT_FILE)
    ok(os.path.exists(audit) and "override_write" in open(
        audit, encoding="utf-8").read(),
       "G3c override_write 动作已留痕 _protected_audit.jsonl")
    cg.close()


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_n131_guard_")
    try:
        _base_shape(tmp)
        _secure_shape(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
