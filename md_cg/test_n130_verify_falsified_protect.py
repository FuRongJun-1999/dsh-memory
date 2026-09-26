# -*- coding: utf-8 -*-
"""N130 守卫：verify(verdict="falsified") 的删除必须过「不可遗忘」保护。

缺陷形态（2026-09-25 引擎域新发现，编号 N130，high）：verify() 的 falsified
分支（mdcg.py:3188-3195）对原节点 os.remove **永久硬删**，全程不经
protect.guard_forget / require_layer_write / override——self/anchor 层、
protected 标记、importance≥0.7 的受保护节点可被一次 verify 调用一键删除，
无快照、无留痕、不进 trash；对照 forget 路径（mdcos.py:2294）同一个删除
动作需 require_admin + guard_forget 双闸（旧版本先快照、动作全程留痕）。

攻击面：任何持 verify op 的主体（verify 角色 ops_allow 即含 verify，
designer ops=["*"] 天然含）对任意 node_id 调 cg(op=verify,
verdict=falsified) 一次调用永久删除；无需 override 无需 admin。

修复：①falsified 分支在任何副作用（add_rejected / os.remove）之前接
protect.guard_forget（受保护节点需显式 override=True——旧版本自动快照 +
_protected_audit 留痕，与 forget 路径同一语义；拒绝抛 ProtectionError，
原节点原样保留）；②MdCGSecure.verify 对 falsified 按原节点层做
require_layer_write（与 add/add_rejected 同一闸口——verify 角色
layers_allow=["rejected","contextual"]，本就「不得改被验证内容」，
tokens.py:171 显式 forbidden）。

红项 = R1-R7（四类受保护节点一键硬删复现 + secure 面层写缺口）；
G 项锁语义不变（普通节点 falsified 负记忆化、override 显式放行 + 快照留痕）。
运行：python -m md_cg.test_n130_verify_falsified_protect
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


_BODY = "# 功能名：N130 守卫\n\n# 生效条件：无条件\n\n正文。\n"


def _exists(cg, nid):
    """索引条目在且盘面文件在（硬删后两者都会消失）。"""
    e = (cg.index.get("nodes") or {}).get(nid)
    return (e is not None
            and os.path.exists(os.path.join(cg.root, e["path"])))


def _falsified_must_reject(cg, nid, label):
    """对 nid 做 falsified：期望 ProtectionError 且节点原样保留。"""
    raised = None
    try:
        cg.verify(nid, "N130 守卫的反例证据", "falsified")
    except protect.ProtectionError as exc:
        raised = exc
    ok(raised is not None, f"{label}1 falsified 受保护节点被拒（ProtectionError）")
    ok(_exists(cg, nid), f"{label}2 拒绝后索引与盘面文件原样保留")


def _seed(cg):
    """四类受保护节点 + 一类普通节点（对照）。"""
    cg.add("n_self", _BODY, layer="self")
    cg.add("n_anchor", _BODY, layer="anchor")
    cg.add("n_prot", _BODY, layer="knowledge")
    protect.mark(cg, "n_prot", "N130 守卫：显式保护标记")
    cg.add("n_imp", _BODY, layer="knowledge", importance=0.9)
    cg.add("n_plain", _BODY, layer="knowledge")


def _base_shape(tmp):
    """A：基类引擎面（无令牌）——四类受保护节点不得被 falsified 一键硬删。"""
    print("--- A 基类引擎面：guard_forget 前置")
    root = os.path.join(tmp, "base")
    cg = MdCGOS(root)
    _seed(cg)

    _falsified_must_reject(cg, "n_self", "R1_self")
    _falsified_must_reject(cg, "n_anchor", "R2_anchor")
    _falsified_must_reject(cg, "n_prot", "R3_protected")
    _falsified_must_reject(cg, "n_imp", "R4_importance0.9")

    ok(all(_exists(cg, n) for n in
           ("n_self", "n_anchor", "n_prot", "n_imp")),
       "R5 四次拒绝后四个受保护节点全部健在")
    ok(not os.path.isdir(os.path.join(cg.root, protect.HISTORY_DIR)),
       "R6 拒绝路径零副作用（未创建 _protected_history）")

    # G1：普通节点 falsified 语义不变（负记忆化 + 原节点移除）
    r = cg.verify("n_plain", "普通节点反例", "falsified")
    ok(r.get("action") == "falsified", "G1a 普通 knowledge 节点 falsified 照常放行")
    ok(not _exists(cg, "n_plain"), "G1b 原 knowledge 节点按负记忆化移除（语义不变）")
    neg = [e for e in (cg.index.get("nodes") or {}).values()
           if e.get("layer") == "rejected"]
    ok(len(neg) == 1, "G1c rejected 层出现负记忆条目（语义不变）")

    # G2：override=True 显式放行 + 快照留痕（与 forget 路径同一能力面）
    r2 = cg.verify("n_prot", "显式 override 的反例", "falsified", override=True)
    ok(r2.get("action") == "falsified", "G2a override=True 显式放行 falsified")
    ok(not _exists(cg, "n_prot"), "G2b override 放行后原节点移除")
    hist = protect.history(cg, "n_prot")
    ok(len(hist) == 1, "G2c override 放行前旧版本已快照进 _protected_history")
    audit = os.path.join(cg.root, protect.AUDIT_FILE)
    ok(os.path.exists(audit) and "override_forget" in open(
        audit, encoding="utf-8").read(),
       "G2d override_forget 动作已留痕 _protected_audit.jsonl")
    cg.close()


def _secure_shape(tmp):
    """B：MdCGSecure 面——falsified 删除按原节点层做 require_layer_write。"""
    print("--- B 安全面：层写权限校验")
    root = os.path.join(tmp, "secure")
    verify_p = Principal(actor="verifier-1", role="verify", can_write=True,
                         can_admin=False, clearance="internal",
                         layers_allow=["rejected", "contextual"],
                         ops_allow=["info", "read", "verify"])
    designer_p = Principal(actor="designer-1", role="designer", can_write=True,
                           can_admin=True, clearance="secret")
    # 预置用 designer（knowledge 层只有可写该层的身份能建），攻击用 verify 角色
    cg = MdCGSecure(root, principal=designer_p, master_key=bytes(range(32)))
    cg.add("s_kn", _BODY, layer="knowledge")            # verify 角色无权写 knowledge
    cg.add("s_ctx", _BODY, layer="contextual")          # verify 角色本职可写
    cg.close()

    # R7：verify 角色 falsified knowledge 节点 → 层写拒绝，节点原样保留
    cg = MdCGSecure(root, principal=verify_p, master_key=bytes(range(32)))
    raised = None
    try:
        cg.verify("s_kn", "verify 角色反例", "falsified")
    except AccessDenied as exc:
        raised = exc
    ok(raised is not None, "R7a verify 角色 falsified knowledge 层被拒（AccessDenied）")
    ok(_exists(cg, "s_kn"), "R7b 拒绝后 knowledge 节点索引与盘面原样保留")

    # G3：verify 角色 falsified contextual 节点 → 本职可写，照常负记忆化
    r = cg.verify("s_ctx", "verify 角色反例（contextual）", "falsified")
    ok(r.get("action") == "falsified", "G3a verify 角色 falsified contextual 层放行")
    ok(not _exists(cg, "s_ctx"), "G3b contextual 节点按负记忆化移除（语义不变）")
    cg.close()

    # R8：designer（层写不限）falsified self 层节点仍被 guard_forget 拦截
    cg = MdCGSecure(root, principal=designer_p, master_key=bytes(range(32)))
    cg.add("s_self", _BODY, layer="self")
    _falsified_must_reject(cg, "s_self", "R8_designer_self")
    cg.close()


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_n130_guard_")
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
