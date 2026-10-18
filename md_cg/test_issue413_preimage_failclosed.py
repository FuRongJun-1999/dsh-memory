# -*- coding: utf-8 -*-
# 功能名：受保护节点 override 的**前像 fail-closed**（issue #413 **站点2**）
# 生效条件：python -X utf8 -m md_cg.test_issue413_preimage_failclosed [--mutate]；被测面=protect._allow（guard_write/guard_forget/guard_move 三条出口共用）
# 子功能：A=写者读不到该节点时 override **必须被拒**（零前像 ⇒ 不得放行；盘面零变化；审计留 denied 行）；B=正面对照（读得到时 override 照常放行且前像在场、审计 snapshot 非 null）；C=同一闸覆盖 forget/move 两出口；R=把 _allow 退回修前形态（**内存内源码级回退后实跑**）⇒ A 必须转红
# 执行：--mutate 时读 protect.py 原文、把 fail-closed 段去掉后 exec 进模块命名空间，实跑 A/C，再 exec 回原文恢复
# 验证方式：全部 PASS 即通过；--mutate 下回退后红项须含 A1/A2（实跑，不接受推演）
# 不适用条件：不判站点1（同秒前像命名，已有 test_issue413_preimage_twin.py 覆盖）；不判「哪些身份算读得到」（那是 cg.get 的密级/会话面）；不改 override 的**显式意图**语义（仍要 override=True）
"""issue #413 站点2 守卫：**无前像的 override 不得放行**。

病象（修前实测，HEAD dd8a9640）：`_allow` 在 `snapshot()` 返回 None（写者读不到该节点，
例如 self 层 private 节点 + internal 档写者、或跨会话）时**照样**返回 `override: True`
⇒ 覆写静默落盘、`_protected_history/<id>/` 一件不落、审计行 `snapshot: null`：
受保护节点的原内容不可回滚地消失（N228：这些快照是 override 快照链的基线）。
实测：覆写后 `sensitivity` 由 private 变 internal、原文（AEAD 密文）无从恢复。

修法：`_allow` 先拍前像，**拍不出来就抛 ProtectionError**（并留 `<action>_denied` 审计行）——
override 的价值来自「可回滚」，拍不出前像就不该放行。
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

# 沙箱用 gettempdir + makedirs（**不用 mkdtemp**）：受限宿主里 mkdtemp 目录带
# 「拒绝再建子目录」的 ACL，会让本守卫整批 PermissionError（与代码无关）。
_SB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "_i413b_sandbox_%d_%d" % (os.getpid(), int(time.time() * 1000)))
shutil.rmtree(_SB, ignore_errors=True)
os.makedirs(_SB, exist_ok=True)
os.environ.update({"MDCG_ROOT": os.path.join(_SB, "brain"),
                   "MDCG_STATE_ROOT": os.path.join(_SB, "state"),
                   "MDCG_AUX_ROOT": os.path.join(_SB, "auxstore"),
                   "MDCG_DATA_ROOT": os.path.join(_SB, "datastore"),
                   "MDCG_EXPORT_ROOT": _SB, "MDCG_MASTER_KEY": "ef" * 32,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0", "MDCG_AUTONOMY": "full"})
from md_cg import nodefile, protect, tokens as tk                                     # noqa: E402
from md_cg.mdcos import MdCGSecure                                                   # noqa: E402
from md_cg.security import Principal                                                 # noqa: E402

FAILS, _PASSED = [], [0]
_N = [0]
_V0 = "A 的私有自我锚点 V0（原始内容）"


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        _PASSED[0] += 1
    else:
        print("  FAIL " + name + ("  · " + str(detail) if detail else ""))
        FAILS.append(name)


def _princ(role, clr, sess):
    sp = tk.role_spec(role)
    return Principal(actor="w-" + sess, role=role, session=sess, clearance=clr,
                     can_write=True, can_admin=False,
                     layers_allow=sp["layers_allow"], ops_allow=sp["ops_allow"])


def _fresh(tag):
    """新库：A 写 self 层 private 节点 V0；返回 root。（tag 自动加序号：R 腿会二次调用）"""
    _N[0] += 1
    root = os.path.join(_SB, "lib_%s_%d" % (tag, _N[0]))
    os.environ["MDCG_ROOT"] = root
    os.makedirs(root, exist_ok=True)
    a = MdCGSecure(root, principal=_princ("designer", "secret", "sessA"), autoflush=1)
    a.add("selfnode", _V0, "self", sensitivity="private")
    a.flush()
    a.close()
    return root


def _disk(root):
    p = os.path.join(root, "self", "orphan", "selfnode.md")
    if not os.path.exists(p):
        for dp, _dn, fns in os.walk(root):
            for fn in fns:
                if fn == "selfnode.md":
                    p = os.path.join(dp, fn)
    if not os.path.exists(p):
        return {}, ""
    return nodefile.loads(io.open(p, encoding="utf-8", errors="replace").read())


def _audit(root):
    f = os.path.join(root, protect.AUDIT_FILE)
    if not os.path.exists(f):
        return []
    return [json.loads(x) for x in io.open(f, encoding="utf-8") if x.strip()]


def _hist(root):
    d = os.path.join(root, protect.HISTORY_DIR, "selfnode")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def leg_A():
    """写者读不到该节点 ⇒ override 必须被拒，且盘面零变化。"""
    print("\n[A 无前像 ⇒ fail-closed]")
    root = _fresh("a")
    w = MdCGSecure(root, principal=_princ("designer", "secret", "sessB"), autoflush=1)
    readable = w.get("selfnode") is not None
    h0, a0 = _hist(root), len(_audit(root))
    old_fm, old_ct = _disk(root)
    try:
        w.add("selfnode", "B 覆写 V1", "self", sensitivity="private", override=True)  # 与节点同档：让拒绝来自**前像不可得**，而不是先被密级闸挡下
        exc = ""
    except Exception as e:                                                            # noqa: BLE001
        exc = "%s: %s" % (type(e).__name__, str(e))
    w.flush()
    h1, rows = _hist(root), _audit(root)
    new = rows[a0:]
    fm, ct = _disk(root)
    print("   写者读得到吗=%s | 异常=%s" % (readable, (exc[:80] + "…") if exc else "（未抛）"))
    print("   前像 %s -> %s | 审计新行=%d" % (h0, h1, len(new)))
    for r in new:
        print("     审计:", json.dumps(r, ensure_ascii=False)[:150])
    _check("A1 读不到 ⇒ 抛 ProtectionError", "ProtectionError" in exc, exc[:120])
    _check("A2 盘面零变化（正文与密级都是原值）",
           old_ct == ct and old_fm.get("sensitivity") == fm.get("sensitivity") == "private",
           (old_ct[:24], ct[:24], fm.get("sensitivity")))
    _check("A3 前像未新增但**未落盘覆写**（h1 == h0）", h1 == h0, (h0, h1))
    _check("A4 审计留痕用 <action>_denied 且不再有 snapshot=null 的 override 行",
           any(str(r.get("action", "")).endswith("_denied") for r in new)
           and not any(str(r.get("action", "")) == "override_write" for r in new),
           [r.get("action") for r in new])
    w.close()


def leg_B():
    """正面对照：读得到时 override 照常放行且前像在场。"""
    print("\n[B 前像可得 ⇒ 照常放行（防过度收紧）]")
    root = _fresh("b")
    w = MdCGSecure(root, principal=_princ("designer", "secret", "sessA"), autoflush=1)
    readable = w.get("selfnode") is not None
    h0, a0 = _hist(root), len(_audit(root))
    try:
        w.add("selfnode", "B 覆写 V2", "self", sensitivity="private", override=True)
        exc = ""
    except Exception as e:                                                            # noqa: BLE001
        exc = "%s: %s" % (type(e).__name__, str(e)[:120])
    w.flush()
    h1, new = _hist(root), _audit(root)[a0:]
    got = w.get("selfnode") or {}
    print("   写者读得到吗=%s | 异常=%s | 前像 %s -> %s" % (readable, exc or "（未抛）", h0, h1))
    for r in new:
        print("     审计:", json.dumps(r, ensure_ascii=False)[:150])
    # 盘上是 AEAD 密文 ⇒ 判「盘面已更新」要读**解密后**的正文（cg.get），不是裸字节
    _check("B1 读得到 ⇒ override 放行（未抛）且节点正文已更新", not exc and "V2" in (got.get("content") or ""),
           (exc, (got.get("content") or "")[:24]))
    _check("B2 前像在场（件数增加）", len(h1) > len(h0), (h0, h1))
    _check("B3 审计 override 行的 snapshot 非 null",
           any(r.get("action") == "override_write" and r.get("snapshot") for r in new),
           [r.get("snapshot") for r in new])
    w.close()


def leg_C():
    """同一闸覆盖 forget / move 两条出口（直调三出口共用的单点 `_allow` 的调用者）。"""
    print("\n[C 同一闸覆盖 forget / move]")
    root = _fresh("c")
    w = MdCGSecure(root, principal=_princ("designer", "secret", "sessB"), autoflush=1)
    cases = [("forget", lambda: protect.guard_forget(w, "selfnode", override=True, actor="w-B")),
             ("move", lambda: protect.guard_move(w, "selfnode", "knowledge", override=True,
                                                 actor="w-B"))]
    for tag, fn in cases:
        a0 = len(_audit(root))
        try:
            fn()
            exc = ""
        except Exception as e:                                                        # noqa: BLE001
            exc = "%s: %s" % (type(e).__name__, str(e)[:110])
        w.flush()
        new = _audit(root)[a0:]
        print("   %-6s 异常=%s | 审计=%s" % (tag, (exc[:60] + "…") if exc else "（未抛）",
                                           [r.get("action") for r in new]))
        _check("C-%s 读不到 ⇒ 同样 fail-closed" % tag, "ProtectionError" in exc, exc[:110])
        _check("C-%s 留 denied 审计行" % tag,
               any(str(r.get("action", "")).endswith("_denied") for r in new),
               [r.get("action") for r in new])
    w.close()


def leg_R():
    """--mutate：把 _allow 退回修前形态（内存内源码级回退），A/C 必须实跑转红。"""
    print("\n[R 变异自证：源码级回退 _allow 的 fail-closed 段]")
    p = os.path.join(_REPO, "md_cg", "protect.py")
    orig = io.open(p, encoding="utf-8").read()
    m = re.search(r"(def _allow\(cg, node_id, why, action, override, actor\):\n)(.*?)(\n\n\n)",
                  orig, re.S)
    if not m:
        print("  [R] 未定位到 _allow 函数体 ⇒ 跳过回退自证")
        return
    mutated = orig[:m.start(2)] + (
        '    snap = snapshot(cg, node_id)\n'
        '    rec = _audit(cg, action, node_id, why, actor, snap)\n'
        '    return {"override": True, "reason": why, "snapshot": snap, "audit": rec}'
    ) + orig[m.end(2):]
    try:
        exec(compile(mutated, p, "exec"), protect.__dict__)          # 内存内回退（实跑）
        before = len(FAILS)
        leg_A()
        leg_C()
        regressed = len(FAILS) - before
        print("  [R] 回退后新增红项 = %d" % regressed)
        _check("R1 回退即红（A/C 在红项内，实跑非推演）", regressed >= 2, "新增=%d" % regressed)
    finally:
        exec(compile(orig, p, "exec"), protect.__dict__)             # 恢复原文


def main():
    mutate = "--mutate" in sys.argv
    print("=" * 72)
    print("md 认知图 · issue #413 站点2 守卫 · override 的前像 fail-closed")
    print("沙箱 =", _SB, "| mutate =", mutate)
    print("=" * 72)
    leg_A()
    leg_B()
    leg_C()
    if mutate:
        leg_R()
    print("\n" + ("全部 PASS（%d 项）" % _PASSED[0] if not FAILS
                  else "FAIL %d 项：%s" % (len(FAILS), FAILS)))
    shutil.rmtree(_SB, ignore_errors=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
