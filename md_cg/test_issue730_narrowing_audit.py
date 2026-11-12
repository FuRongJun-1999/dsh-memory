# -*- coding: utf-8 -*-
"""issue #730（D）：`narrowed_principal` 的**收窄面审计** + `sessions_read` 签发/派生回归。

## 病灶（#730）
`narrowed_principal` 是「as_unit 请求级身份」的唯一收窄点；它的安全性论证是
**单调性**（伪造 `as_unit` 最坏结果 ≤ owner 权限，不可能提权）。但收窄面是逐字段手写的——
`sessions_read` 就曾漏传（owner 带读面限制时，请求级收窄后读面静默变宽 = fail-open）。

## 本守卫钉什么
- A 签发：`issue(sessions_read=[...])` 落盘 rec 与 `verify_token` 的 Principal 都带该字段；
- B 派生收窄：`derive(parent, sessions_read=超集)` 得**交集**；交集为空 ⇒ `TokenError`（fail-closed，
  绝不退化成「不限制」）；
- C 传导：`narrowed_principal` 保留 owner 的 `sessions_read`（不放大）；
- D 收窄面清单：`NARROWING_FIELDS` 与函数体逐项对应，且每个字段的结果 ≤ owner。

运行：python -X utf8 -m md_cg.test_issue730_narrowing_audit
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import security, tokens   # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


def _rank(level):
    return security.SENSITIVITY_ORDER.index(level)


def _unrestricted(x):
    """None 或含 `*` ⇒ 不限（owner 不限时，单元的任何子集都不构成放大）。"""
    return x is None or "*" in tuple(x)


def main():
    print("=" * 68)
    print("issue #730 · 收窄面审计（narrowed_principal / sessions_read）")
    print("=" * 68)
    tmp = tempfile.mkdtemp(prefix="iss730_")
    path = os.path.join(tmp, "tokens.json")
    try:
        # ---- A 签发 ----
        tk = tokens.issue("designer", actor="t730", clearance="internal",
                          path=path, sessions_read=["s1"])["token"]
        p = tokens.verify_token(tk, path=path)
        ok(tuple(p.sessions_read or ()) == ("s1",), "A1 签发后 Principal.sessions_read 保留",
           getattr(p, "sessions_read", None))
        rec = (tokens._load(path).get("tokens") or {}).get(p.token_id) or {}
        ok(rec.get("sessions_read") == ["s1"], "A2 落盘 rec 带 sessions_read",
           rec.get("sessions_read"))

        # ---- B 派生收窄 ----
        tk2 = tokens.derive(tk, role="verifier", path=path,
                            sessions_read=["s1", "s2"])["token"]
        p2 = tokens.verify_token(tk2, path=path)
        ok(tuple(p2.sessions_read or ()) == ("s1",), "B1 派生按交集收窄（超集不得放大）",
           p2.sessions_read)
        raised = False
        try:
            tokens.derive(tk, role="verifier", path=path, sessions_read=["sX"])
        except tokens.TokenError:
            raised = True
        ok(raised, "B2 交集为空 ⇒ TokenError（fail-closed，不退化成不限制）")

        # ---- C 传导 ----
        q = tokens.narrowed_principal(p, "record")
        ok(tuple(getattr(q, "sessions_read", None) or ()) == ("s1",),
           "C1 narrowed_principal 保留 sessions_read（不放大）",
           getattr(q, "sessions_read", None))

        # ---- D 收窄面清单 ----
        ok(set(tokens.NARROWING_FIELDS) == {
            "clearance", "can_write", "can_admin", "layers_allow",
            "ops_allow", "sessions_read"},
           "D1 NARROWING_FIELDS 覆盖全部收窄型字段", tokens.NARROWING_FIELDS)
        ok(q.can_admin is False, "D2 can_admin 恒 False（请求级身份拿不到管理权）")
        ok(q.can_write is False or bool(p.can_write),
           "D3 can_write 与 owner 取与（owner 只读 ⇒ 单元不可能写）")
        ok(_rank(q.clearance) <= _rank(p.clearance),
           "D4 clearance ≤ owner", (q.clearance, p.clearance))
        ok(_unrestricted(p.layers_allow)
           or set(q.layers_allow or ()) <= set(p.layers_allow),
           "D5 layers_allow 是 owner 的子集（owner 不限时无此约束）",
           (q.layers_allow, p.layers_allow))
        ok(_unrestricted(p.ops_allow)
           or set(q.ops_allow or ()) <= set(p.ops_allow),
           "D6 ops_allow 是 owner 的子集（owner 不限时无此约束）",
           (q.ops_allow, p.ops_allow))

        # ---- E 未设 sessions_read ⇒ None（不限制，既有行为）----
        tk3 = tokens.issue("recorder", actor="t730b", path=path)["token"]
        p3 = tokens.verify_token(tk3, path=path)
        ok(getattr(p3, "sessions_read", None) is None,
           "E1 未声明 sessions_read ⇒ None（不限制，既有调用方不变）",
           getattr(p3, "sessions_read", None))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("issue #730：%d 项失败" % len(FAILS) if FAILS else "issue #730：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
