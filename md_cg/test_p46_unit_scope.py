# -*- coding: utf-8 -*-
"""md_cg · 第 46 篇：请求级单元收窄（单进程多身份 · as_unit）

设计口径（2026-09-11）
--------------------
两个身份维度**职责分离**：
  · env 身份（MDCG_TOKEN）—— 「谁装了这个大脑」，进程级恒定，是权限**上限**；
  · 请求参数 `as_unit`  —— 「这一次调用以哪个单元执行」，请求级、可缺省。

与第 45 篇不冲突：第 45 篇确立「不靠多令牌 / 多实例提权」；本篇是**单令牌内收窄**
——`as_unit` 参与授权时**只做减法**（与 owner 求交 + 管理权恒 False），故伪造
`as_unit` 的最坏结果等于不传，**不可能提权**。`unit` 字段本身仍是归因维度。

`as_unit`（受限枚举，参与授权，未知值 fail-closed 报错）与 `unit`（自由文本，
仅归因）职责分离：拼错单元名必须报错，**绝不静默退回 owner 全权**。

覆盖
----
A narrowed_principal：单元 → ROLE_SPECS 收窄（层 / op / 密级 / 写权 / 管理权）
B 不放大不变量：五单元逐一 can_admin=False；只读 owner 收不成可写；求交语义
C fail-closed：未知单元报错；大小写 / 角色别名归一
D call_tool 包装：as_unit 生效 / 调用后 principal 复原 / 非法值拒绝 / 缺省不变
E 真实闸门联动：收窄后的 require_layer_write / require_op / require_admin 拦得住

运行：python -m md_cg.test_p46_unit_scope
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import mcp_server as ms
from md_cg import tokens
from md_cg.security import AccessDenied, Principal, _rank

_N = {"pass": 0, "fail": 0}


def check(name, cond, detail=""):
    if cond:
        _N["pass"] += 1
        print(f"  PASS  {name}")
    else:
        _N["fail"] += 1
        print(f"  FAIL  {name}" + (f"  <- {detail}" if detail else ""))


def _designer(**kw):
    """owner：设计者载体全权（模拟 env 身份 = MDCG_TOKEN 的权限域）。"""
    base = dict(actor="dsh", role="designer", clearance="secret",
                can_write=True, can_admin=True,
                layers_allow=["*"], ops_allow=["*"])
    base.update(kw)
    return Principal(**base)


def test_a_unit_scope():
    print("[A] narrowed_principal 单元收窄")
    p = _designer()
    rec = tokens.narrowed_principal(p, "record")
    check("A1 unit 与 role 均记为执行单元",
          rec.unit == "record" and rec.role == "record",
          f"unit={rec.unit} role={rec.role}")
    check("A2 管理权被剥夺（单元永无管理权）", rec.can_admin is False)
    check("A3 写权保留（record 可写）", rec.can_write is True)
    check("A4 层白名单 = record spec（含 contextual，不含 self）",
          rec.allows_layer("contextual") and not rec.allows_layer("self"),
          f"layers={list(rec.layers_allow or ())}")
    check("A5 op 白名单 = record spec（含 write，不含 verify）",
          rec.allows_op("write") and not rec.allows_op("verify"),
          f"ops={list(rec.ops_allow or ())}")
    check("A6 密级被 spec 上限夹紧（secret -> internal）",
          rec.clearance == "internal", f"clearance={rec.clearance}")

    out = tokens.narrowed_principal(p, "output")
    check("A7 output 只读（can_write False）", out.can_write is False)
    check("A8 output 层白名单为空", not out.allows_layer("knowledge"))

    sus = tokens.narrowed_principal(p, "sustain")
    check("A9 sustain 仅可写 self 层",
          sus.allows_layer("self") and not sus.allows_layer("knowledge"),
          f"layers={list(sus.layers_allow or ())}")

    ver = tokens.narrowed_principal(p, "verify")
    check("A10 verify 可执行 verify op", ver.allows_op("verify"))
    # 取证修正（2026-09-11）：verify.ops_allow **含** write（验证器要写裁决证据
    # rejected/contextual），故「无 write op」是错误假设；真正的护栏在**层白名单**。
    check("A11 verify 可写但仅限 rejected/contextual（不得写 knowledge）",
          ver.allows_layer("rejected") and ver.allows_layer("contextual")
          and not ver.allows_layer("knowledge"),
          f"layers={list(ver.layers_allow or ())}")

    ref = tokens.narrowed_principal(p, "reflect")
    check("A14 reflect 仅可写 contextual（不得写 knowledge）",
          ref.allows_layer("contextual") and not ref.allows_layer("knowledge"),
          f"layers={list(ref.layers_allow or ())}")
    check("A15 record 可写 knowledge 但不得写 self 层",
          rec.allows_layer("knowledge") and not rec.allows_layer("self"))

    check("A12 归因维度继承（actor/session/tenant 不变）",
          rec.actor == p.actor and rec.session == p.session and rec.tenant == p.tenant)
    check("A13 令牌溯源保留（token_id/parent 与 owner 一致）",
          rec.token_id == p.token_id and rec.parent == p.parent)


def test_b_no_escalation():
    print("[B] 不放大不变量（核心安全论证）")
    p = _designer()
    for u in tokens.POSITION_ROLES:
        n = tokens.narrowed_principal(p, u)
        check(f"B1.{u} 管理权恒 False", n.can_admin is False)
        check(f"B2.{u} 密级 <= owner",
              _rank(n.clearance) <= _rank(p.clearance),
              f"{n.clearance} vs {p.clearance}")

    g = Principal(actor="g", role="guest", clearance="internal",
                  can_write=False, can_admin=False, layers_allow=[], ops_allow=["read"])
    for u in tokens.POSITION_ROLES:
        check(f"B3.{u} 只读 owner 收不成可写",
              tokens.narrowed_principal(g, u).can_write is False)

    lim = _designer(ops_allow=["read"])
    n = tokens.narrowed_principal(lim, "record")
    check("B4 op 求交（owner 限 read -> 收窄后仍只有 read）",
          n.allows_op("read") and not n.allows_op("write"),
          f"ops={list(n.ops_allow or ())}")

    lim2 = _designer(layers_allow=["knowledge"])
    n2 = tokens.narrowed_principal(lim2, "record")
    check("B5 层求交（owner 限 knowledge -> 不含 contextual）",
          n2.allows_layer("knowledge") and not n2.allows_layer("contextual"),
          f"layers={list(n2.layers_allow or ())}")

    low = _designer(clearance="internal")
    check("B6 密级不会因单元而上浮",
          tokens.narrowed_principal(low, "record").clearance == "internal")

    # 强 owner（*）经收窄后，对每个单元都不得比 owner 更宽
    check("B7 收窄结果恒为 spec 与 owner 的并集下界（抽查 output/record 不相交扩张）",
          not tokens.narrowed_principal(p, "output").allows_op("forget")
          and not tokens.narrowed_principal(p, "record").allows_op("forget"))


def test_c_failclosed():
    print("[C] fail-closed 与归一")
    p = _designer()
    # 'root' / 'admin' 是 designer 的别名 -> 归一后不在五单元内 -> 必须拒绝
    for bad in ("root", "admin", "designer", "", "   ", "recorder2", "executor"):
        try:
            tokens.narrowed_principal(p, bad)
            check(f"C1 未知单元 {bad!r} 必须报错", False, "未抛 TokenError")
        except tokens.TokenError:
            check(f"C1 未知单元 {bad!r} 报错", True)
    check("C2 大小写归一（RECORD -> record）",
          tokens.narrowed_principal(p, "RECORD").unit == "record")
    check("C3 角色别名归一（recorder -> record）",
          tokens.narrowed_principal(p, "recorder").unit == "record")
    check("C4 空白归一（' verify ' -> verify）",
          tokens.narrowed_principal(p, " verify ").unit == "verify")
    check("C5 verifier 别名归一（verifier -> verify）",
          tokens.narrowed_principal(p, "verifier").unit == "verify")


class _ProbeCG:
    """最小 cg 替身：只供 call_tool 收窄 / 复原验证，不触碰磁盘。

    字段恰好满足 `mdcg_service_info` 的读取需求
    （root / actor / index["nodes"] / principal.as_dict()）。
    """
    root = "."
    actor = "probe"
    index = {"nodes": {}}

    def __init__(self, principal):
        self.principal = principal


def test_d_call_tool_wrapper():
    print("[D] call_tool 包装：生效 / 复原 / 拒绝")
    owner = _designer()
    cg = _ProbeCG(owner)

    ok = ms.call_tool(cg, "mdcg_service_info", {"as_unit": "record"})
    pr = (ok or {}).get("principal") or {}
    check("D1 as_unit 生效（返回身份为执行单元）", pr.get("unit") == "record",
          f"principal={pr}")
    check("D2 收窄后管理权 False", pr.get("can_admin") is False)
    check("D3 调用结束后 principal 复原（不泄漏到后续调用）",
          cg.principal is owner)

    nxt = ms.call_tool(cg, "mdcg_service_info", {})
    pr2 = (nxt or {}).get("principal") or {}
    check("D4 缺省 as_unit 不改身份（等价改动前行为）",
          pr2.get("unit") is None and pr2.get("can_admin") is True,
          f"principal={pr2}")

    bad = ms.call_tool(cg, "mdcg_service_info", {"as_unit": "root"})
    check("D5 非法 as_unit fail-closed",
          isinstance(bad, dict) and bad.get("ok") is False
          and "as_unit" in str(bad.get("error", "")), f"resp={bad}")
    check("D6 非法 as_unit 不改变 principal", cg.principal is owner)

    # 空串 / 纯空白视为「未声明」，走 owner 全权（不报错）
    for blank in ("", "   "):
        r = ms.call_tool(cg, "mdcg_service_info", {"as_unit": blank})
        pr3 = (r or {}).get("principal") or {}
        check(f"D7 空白 as_unit={blank!r} 视为缺省",
              pr3.get("unit") is None and cg.principal is owner)


def test_e_gates():
    print("[E] 真实权限闸门联动（收窄后确实拦得住）")
    p = _designer()
    rec = tokens.narrowed_principal(p, "record")

    rec.require_layer_write("contextual", "internal")
    check("E1 record 可写 contextual", True)

    try:
        rec.require_layer_write("self", "internal")
        check("E2 record 不可写 self 层", False, "未抛 AccessDenied")
    except AccessDenied:
        check("E2 record 不可写 self 层", True)

    try:
        rec.require_admin("forget")
        check("E3 record 无管理权", False, "未抛 AccessDenied")
    except AccessDenied:
        check("E3 record 无管理权", True)

    try:
        rec.require_op("verify")
        check("E4 record 不可执行 verify op", False, "未抛 AccessDenied")
    except AccessDenied:
        check("E4 record 不可执行 verify op", True)

    out = tokens.narrowed_principal(p, "output")
    try:
        out.require_write("internal")
        check("E5 output 不可写", False, "未抛 AccessDenied")
    except AccessDenied:
        check("E5 output 不可写", True)

    rec.require_op("read")
    check("E6 record 仍可读（未误伤读路径）", True)

    sus = tokens.narrowed_principal(p, "sustain")
    sus.require_layer_write("self", "internal")
    check("E7 sustain 可写 self（互维维护路径未被误伤）", True)
    try:
        sus.require_layer_write("knowledge", "internal")
        check("E8 sustain 不可写 knowledge", False, "未抛 AccessDenied")
    except AccessDenied:
        check("E8 sustain 不可写 knowledge", True)


def main():
    print("=" * 68)
    print("md_cg 第 46 篇 · 请求级单元收窄（as_unit）—— 单进程多身份")
    print("=" * 68)
    test_a_unit_scope()
    test_b_no_escalation()
    test_c_failclosed()
    test_d_call_tool_wrapper()
    test_e_gates()
    print("-" * 68)
    print(f"PASS {_N['pass']} / FAIL {_N['fail']}")
    return 1 if _N["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
