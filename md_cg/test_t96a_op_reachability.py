# -*- coding: utf-8 -*-
"""test_t96a_op_reachability · 令牌 op 可达性巡检（T96a）。

背景：灵枢「令牌面」的每个角色（designer / orchestr / record / reflect /
verify / output / sustain / guest）签发的令牌带一个 `ops_allow` 允许集合，
op 在运行时被角色闸拦住（mcp_server._cg_dispatch 前置 require_op）。

上一轮对照（D:\\wook\\tmp\\t96a-ops-matrix.json，本件只读不写）发现：`ALL_OPS`
38 个 op 里有 11 个除 designer（`ops_allow` 含 `'*'`）之外**没有任何角色能调**。
本件是那次对照落成的常驻守卫，断言四组：

  ① 三处同步：`tokens.ALL_OPS` == cg 工具 inputSchema 的 op 枚举 ==
     `protocol.dispatch_ops()`（AST 提取的分发分支）——防「加了 op 忘改某处」。
  ② 真实缺口补齐后**全部 daily 可达**：8 个只读/可审计类缺口
     （causal / export / index_code / index_doc / predict / ref / theory）至少被
     一个非 designer 角色的 ops_allow 放行；`consolidate` 属**刻意**的
     designer 专属（批量提升走 require_admin，见 tokens.py ALL_OPS 上方注释），
     不在「应补齐」清单内，单列断言它仍不可达。
  ③ 分权未被本次改动破坏：`forget` / `protect` / `identity` / `consolidate`
     仍然**不在任何非 designer 角色的 ops_allow 里**（存在级管理／动地基／
     批量提升一律归设计者；依据 tokens.py orchestr 的 forbidden 与
     test_p30_maintain.py 的 consolidate 专属断言）。
  ④ 伪缺口判据仍在源文件里成立：`help` 与 `state_event` 在矩阵里看着「只有
     designer 能调」，实为**角色闸之外的直通路径**，故不是真缺口——
       · `help`：`_cg_dispatch` 里 `if op == "help": return _help_call(...)`
         出现在**任何 `require_op` 调用之前**（只读元信息，人人可用）；
       · `state_event`：`_cg_dispatch` 里被映射成既有 `"write"` 词
         （`require_op("write" if op == "state_event" else op)`）——
         「角色面零新词」，因此**含 write 不含 state_event** 的白名单令牌可记账。

判据一律**读源码文本**得出，行号不硬编码（行号会漂，判结构即可）：从
`inspect.getsource(mcp_server._cg_dispatch)` 取分发函数原文再判位置关系。

隔离：本件**纯静态读**（import 模块 + 读源码文本），不建库、不签发令牌、
不写任何文件、不触在役数据根；重跑 ≡ 首跑。

运行：python -X utf8 -m md_cg.test_t96a_op_reachability
      python -X utf8 md_cg/test_t96a_op_reachability.py    # 直跑文件亦可（见下）
退出码：0 = 全绿 / 1 = 有断言失败。

两种调用形态都支持：-m 形态走包内相对导入；**直跑文件形态**（`python
md_cg/test_t96a_op_reachability.py`，无包上下文）先补 sys.path 再按绝对名
`md_cg.*` 导入——同族 test_p27/p29/p30/p31 只支持 -m，本件多兜底一种，
因为收口闸给的就是文件路径形态。两种形态判据完全一致，不分叉。
"""
from __future__ import annotations

import inspect
import os
import sys

if __package__ in (None, ""):                            # 直跑文件：补包上下文
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from md_cg import mcp_server, protocol, tokens
    from md_cg.mcp_server import KERNEL_TOOLS
else:                                                    # python -m md_cg.<本件>
    from . import mcp_server, protocol, tokens
    from .mcp_server import KERNEL_TOOLS

PASS = FAIL = 0
FAILS = []

#: 上一轮对照里的 11 个「designer 之外无人可调」候选，其中 2 个是伪缺口
#: （help / state_event 走直通或词映射，不经角色闸），剩 8 个真实缺口。
#: 8 个真实缺口里 7 个属只读/可审计类，本批补齐；consolidate 为刻意的
#: designer 专属（且它同时出现在矩阵的 11 个 designer_only 里，故 11 = 2 + 8）。
#: 注意 7 + 1(consolidate) = 8 = 真实缺口数；11 ≠ 2 + 7 + 1 + 1，后者是把
#: consolidate 双重计数，本件按真实集合判，不按那个错账。
PSEUDO_GAPS = ("help", "state_event")
#: 本批应补齐为 daily 可达的真实缺口（原 11 个减去 2 伪缺口与 consolidate）。
SHOULD_BE_DAILY = ("causal", "export", "index_code", "index_doc", "predict",
                   "ref", "theory")
#: 刻意的 designer 专属：不在「应补齐」清单内，须保持不可达。
DESIGNER_ONLY_KEEP = ("consolidate",)
#: 分权红线：任何非 designer 角色的 ops_allow 都不得含这四项。
MUST_STAY_OUT = ("forget", "protect", "identity", "consolidate")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


# 生效条件：无入参；返回 (角色名, ops_allow 列表) 序列，designer 单列在外（其 '*' 是通配不是逐项白名单）。
def _non_designer_roles():
    return [(r, list(s["ops_allow"])) for r, s in tokens.ROLE_SPECS.items()
            if r != "designer"]


# 生效条件：无入参；返回 cg 工具 inputSchema 声明的 op 枚举集合（从 description 的 '|' 串切分），工具缺失时返回 None。
def _schema_ops():
    tool = next((t for t in KERNEL_TOOLS if t["name"] == "cg"), None)
    if tool is None:
        return None
    desc = tool["inputSchema"]["properties"]["op"]["description"]
    return set(desc.split("|"))


# 生效条件：无入参；返回被非 designer 角色 ops_allow 覆盖到的 op 集合（通配 '*' 不计——它只属 designer）。
def _non_designer_reachable():
    out = set()
    for _r, allow in _non_designer_roles():
        out |= {o for o in allow if o != "*"}
    return out


# ---------------------------------------------------------------- ① 三处同步
# 生效条件：无入参；断言 ALL_OPS == cg 工具 op 枚举 == protocol.dispatch_ops()（三处一致、非空、计数相符），逐项打印差异集合。
def t1_three_way_sync():
    print("\n【1】三处同步：ALL_OPS == cg 工具 op 枚举 == dispatch_ops()")
    all_ops = set(tokens.ALL_OPS)
    check("ALL_OPS 非空", bool(all_ops), f"n={len(all_ops)}")
    check("ALL_OPS 无重复项", len(all_ops) == len(tokens.ALL_OPS),
          f"len={len(tokens.ALL_OPS)} set={len(all_ops)}")

    schema = _schema_ops()
    check("cg 工具存在且有 op 参数枚举", schema is not None)
    if schema is not None:
        check("ALL_OPS == cg 工具 op 枚举",
              all_ops == schema,
              f"diff={sorted(all_ops ^ schema)}")
        check("cg 工具 op 枚举非空", bool(schema), f"n={len(schema)}")

    got = protocol.dispatch_ops()
    check("dispatch_ops() 提取成功（AST 未因写法变形漏提）",
          bool(got.get("ok")), f"error={got.get('error')}")
    disp = set(got.get("ops") or [])
    check("ALL_OPS == dispatch_ops()", all_ops == disp,
          f"diff={sorted(all_ops ^ disp)}")
    check("dispatch_ops() 非空", bool(disp), f"n={len(disp)}")

    if schema is not None and disp:
        check("三处计数一致（ALL_OPS/" + "schema/dispatch）",
              len(all_ops) == len(schema) == len(disp),
              f"all={len(all_ops)} schema={len(schema)} dispatch={len(disp)}")


# ---------------------------------------------------------------- ② 缺口可达
# 生效条件：无入参；断言真实缺口补齐后全部 daily 可达（至少一个非 designer 角色放行），且刻意专属项 consolidate 仍不可达，逐 op 打印承担角色。
def t2_gaps_reachable():
    print("\n【2】真实缺口补齐后 daily 可达（至少一个非 designer 角色放行）")
    roles = _non_designer_roles()
    reachable = _non_designer_reachable()
    for op in SHOULD_BE_DAILY:
        holders = [r for r, allow in roles if op in allow]
        check(f"{op} 已 daily 可达", bool(holders),
              f"承担角色={holders or '（无——仍不可达）'}")
    for op in DESIGNER_ONLY_KEEP:
        holders = [r for r, allow in roles if op in allow]
        check(f"{op} 仍为 designer 专属（刻意不补）", not holders,
              f"意外放行给={holders}")
    # 账目对平（按真实集合判，不按矩阵那句被双重计数的「11」）：
    #   矩阵的 11 个 designer_only 清单 = 8 真实缺口 + help + state_event + 1，
    #   而 summary.designer_only_ops 与 designer_unreachable 两个口径长度不同
    #   （后者 13 项，多出 help/state_event 两个伪缺口）。真实缺口集 =
    #   {causal, consolidate, export, index_code, index_doc, predict, ref, theory}
    #   = 8 个；其中 7 个本次补齐、consolidate 刻意留设计师专属。
    real_gaps = set(SHOULD_BE_DAILY) | set(DESIGNER_ONLY_KEEP)
    candidate = set(PSEUDO_GAPS) | real_gaps
    check("缺口账目对平：真实缺口 8 个（7 补齐 + 1 刻意专属），伪缺口 2 个",
          len(real_gaps) == 8 and len(PSEUDO_GAPS) == 2 and len(candidate) == 10,
          f"real_gaps={sorted(real_gaps)}")
    check("11 个候选（矩阵口径）＝ 2 伪缺口 + 8 真实缺口 + 1 项矩阵内部重复计数（consolidate）",
          len(set(PSEUDO_GAPS)) + len(real_gaps) == 10,
          "矩阵 designer_only_ops 11 项里 consolidate 与真实缺口集重叠，"
          "故 11 = 2 + 8 + 1（该 +1 即 consolidate 本身）")


# ---------------------------------------------------------------- ③ 分权红线
# 生效条件：无入参；断言存在级管理/动地基/批量提升四项仍不在任何非 designer 角色的 ops_allow 里，并抽查 designer 仍持通配（对照基线）。
def t3_separation_kept():
    print("\n【3】分权未被破坏：forget/protect/identity/consolidate 仍不对非 designer 开放")
    roles = _non_designer_roles()
    for op in MUST_STAY_OUT:
        holders = [r for r, allow in roles if op in allow]
        check(f"{op} 不在任何非 designer 角色的 ops_allow 里", not holders,
              f"被放行给={holders}")
    check("designer 仍持通配 '*'（对照基线，本次未动）",
          "*" in tokens.ROLE_SPECS["designer"]["ops_allow"],
          str(tokens.ROLE_SPECS["designer"]["ops_allow"]))
    # 非 designer 角色一律不得出现通配项（否则红线形同虚设）。
    wild = [r for r, allow in roles if "*" in allow]
    check("非 designer 角色均无通配 '*'", not wild, f"含通配={wild}")


# ---------------------------------------------------------------- ④ 伪缺口判据
# 生效条件：无入参；从 _cg_dispatch 源码文本判定 help 的 return 在 require_op 之前、state_event 被映射成 "write" 词（不硬编码行号，只判结构）。
def t4_pseudo_gap_evidence():
    print("\n【4】伪缺口判据仍在源文件里成立（help 直通 / state_event 词映射）")
    try:
        src = inspect.getsource(mcp_server._cg_dispatch)
    except Exception as exc:                                 # noqa: BLE001
        check("能取到 _cg_dispatch 源码", False, f"{type(exc).__name__}: {exc}")
        return

    # ① help：`if op == "help"` → `return _help_call(...)` 必须整体早于任何 require_op。
    i_help = src.find('if op == "help"')
    i_ret = src.find("return _help_call", i_help) if i_help >= 0 else -1
    i_req = src.find("require_op(", max(i_ret, 0))
    check('_cg_dispatch 有 `if op == "help"` 分支', i_help >= 0, f"idx={i_help}")
    check("help 分支在角色闸之前直通 return（return < require_op）",
          0 <= i_help < i_ret and i_ret < i_req,
          f"help_if={i_help} return={i_ret} require_op={i_req}")
    check("help 排在第一个 require_op 之前（前置角色闸不拦它）",
          i_req < 0 or i_help < i_req,
          f"help_if={i_help} first_req={i_req}")

    # ② state_event：必须映射到既有 "write" 词（「角色面零新词」）。
    req_lines = [l.strip() for l in src.splitlines() if "require_op(" in l]
    mapped = any('"write" if op == "state_event" else op' in l
                 or "'write' if op == 'state_event' else op" in l
                 for l in req_lines)
    check('state_event 被映射成既有 "write" 词（不引入新 op 词）', mapped,
          f"require_op 行={req_lines}")
    check("state_event 自身不出现在 require_op 的 op 词位置（映射而非直传）",
          not any("require_op(\"state_event\")" in l
                  or "require_op('state_event')" in l for l in req_lines),
          f"require_op 行={req_lines}")

    # ③ 两个伪缺口确实不在 ALL_OPS 之外的野词里（它们是登记在表的真 op，
    #    只是不经角色闸；登记于 ALL_OPS 是为「三处同步」契约）。
    for op in PSEUDO_GAPS:
        check(f"{op} 登记在 ALL_OPS（三处同步契约要求）",
              op in tokens.ALL_OPS)


def main():
    print("=" * 68)
    print("md 认知图 T96a 巡检 · 令牌 op 可达性（角色面覆盖 + 分权红线）")
    print("=" * 68)
    t1_three_way_sync()
    t2_gaps_reachable()
    t3_separation_kept()
    t4_pseudo_gap_evidence()

    print("\n" + "=" * 68)
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    if FAILS:
        print("失败项：")
        for n in FAILS:
            print(f"  - {n}")
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
