# -*- coding: utf-8 -*-
"""issue #678 守卫：AccessDenied 文案要区分「角色不含」与「令牌被收窄」。"""
from __future__ import annotations

from .security import AccessDenied, Principal


def main():
    ok = bad = 0

    def chk(cond, label):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  PASS", label)
        else:
            bad += 1
            print("  FAIL", label)

    def denied(fn):
        try:
            fn()
        except AccessDenied as exc:
            return exc
        return None

    # ① 令牌被收窄：角色 designer 本身 ops_allow=["*"]，但令牌只给读面
    narrowed = Principal(actor="dsh-memory", role="designer", can_admin=True,
                         ops_allow=("info", "route", "read", "write", "recent"))
    e = denied(lambda: narrowed.require_op("forget"))
    msg = str(e or "")
    hint = (e.hint if e else "") or ""
    chk(e is not None, "#678 收窄令牌执行 forget 仍被拒（闸门不放松）")
    chk("本令牌" in msg, "#678 文案改说「本令牌的 ops 作用域不含」")
    chk("本身**含**该 op" in msg, "#678 明确告知角色本身含该 op（不被误读成角色缺陷）")
    chk("--ops-allow" in hint and "重新签发" in hint, "#678 hint 指向重新签发而非改角色")
    chk("无权执行 op=forget" not in msg, "#678 不再用「角色 X 无权」的误导句式")

    # ② 角色本身不含：recorder 的角色白名单里没有 forget —— 仍走原口径
    rec = Principal(actor="demo", role="recorder",
                    ops_allow=("read", "write", "recent"), can_write=True)
    e2 = denied(lambda: rec.require_op("forget"))
    h2 = (e2.hint if e2 else "") or ""
    chk(e2 is not None and "无权执行 op=forget" in str(e2),
        "#678 角色本身不含该 op 时保留原口径（不误报成收窄）")
    chk("--ops-allow" in h2 and "重新签发" in h2, "#678 该分支 hint 仍可用")

    # ③ guest 分支不变
    # 注意：ops_allow=None 表示「不限」，guest 的真实形态是显式只读白名单
    guest = Principal(actor="anon", role="guest", can_write=False,
                      ops_allow=("info", "route", "read", "recent"))
    e3 = denied(lambda: guest.require_op("write"))
    chk(e3 is not None and "MDCG_TOKEN" in ((e3.hint if e3 else "") or ""),
        "#678 guest 仍走配凭据 hint")

    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
