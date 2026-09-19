# -*- coding: utf-8 -*-
"""md_cg · 记忆动词协议 v1（单一真源 · draft 期未冻结）

目的（工作计划 §3.4）：把 MCP 记忆工具面的**动词与 I/O 形状**冻结成可裁决的声明，
使三端（本仓 MCP / DSH 内建基元 / 第三方客户端）能各自实现客户端而不必读源码；
再由 `conformance.py` 的静态对账把「声明 ↔ 实现」钉死：

    · 声明为 live 却在 MCP 面无分支        → FAIL（说了没做）
    · reserved 动词在 MCP 面出现实现分支   → FAIL（预留位被静默实现，协议形同虚设）
    · 协议外 op 分支                       → 报告（扩展能力面，不是违例）

范围（先行收窄）：route / read / write / supersede / forget 五动词。

**协议面 ≠ MCP 面全量**（2026-09-19 实测）：`_cg_dispatch` 现有 35 个 op 分支，
其中 30 个（ccg / review / protect / verify / whitebox …）属**扩展能力面**——它们是能力，
不是协议违例。把「协议覆盖范围」当成「MCP 面全量」会让协议每加一个 op 就永久红灯，
故反向对账降级为 `extension_ops` 报告项（清单可见、不 FAIL）；扩展面的文档一致性由
README 认知图 + `docs/mdcg/功能调用映射表` 的 cogmap 门禁承担（已在 CI）。

三条纪律：
1. **本文件是协议唯一真源**——文档 `docs/mdcg/灵枢记忆动词协议_v1.0-draft.md`
   与 `conformance.py` 的断言均从本文件取值，不另立第二份清单。
2. **不冒充**——未实现的动词登记 `status="reserved"` 并给出 `map_to` 现状映射证据，
   不得写 live；live 的形状取**代码实测**（executor / 分支 return），不取设想。
3. **draft 期（FROZEN=False）**——形状可破坏性调整；冻结是单向门，须三端实测收敛后
   由使用者拍板（工作计划 §9 风险 3）。

用法：
    python -m md_cg.protocol          # 打印静态对账结论（只读，零写入）
"""
from __future__ import annotations

import argparse
import ast
import inspect
import json
import textwrap

PROTOCOL_VERSION = 1
#: 冻结开关：True 后形状变更须走版本号递增（v1 → v2），不得原地改 v1 的形状
FROZEN = False
PROTOCOL_DOC = "docs/mdcg/灵枢记忆动词协议_v1.0-draft.md"
SURFACE_MODULE = "md_cg.mcp_server"
DISPATCH_FUNC = "_cg_dispatch"
CALL_FUNC = "_cg_call"

#: 协议声明的动词全集（顺序即文档呈现顺序）
VERBS = ("route", "read", "write", "supersede", "forget")

#: write 返回**铁律**：任一形态必含此三键——客户端据此判定「是否落盘」而非猜测。
#: 这是协议对三端客户端最有价值的一条：ok/committed 分离表达「闸门行为 ≠ 工具故障」。
WRITE_TRIO = ("ok", "id", "committed")

#: op 推导兜底（`_cg_call` wrapper，2026-09-13 防呆落地）：op 漏传时按入参签名推导。
#: 协议侧只作**文档化声明**（供客户端理解兜底语义），不做静态对账——
#: 推导实现散落在 wrapper 分支里，强做正则对账会误报（宁可少断言，不可假绿灯）。
OP_DERIVE = (
    {"when": "content", "op": "write"},
    {"when": "query", "op": "read"},
    {"when": "node_id", "op": "read"},
    {"when": "intent", "op": "route"},
    {"when": "(无签名)", "op": "read"},
)

#: op 推导发生时**追加透出**的键（实测）：additive，不破坏各形态 required 子集判定。
#: 协议语义：客户端看到这些键即知道「本次 op 是猜的」——据此可要求调用方补显式 op。
DERIVE_EXTRA_KEYS = ("op", "op_derived", "hint")

#: 校验裁决（verdict）的字段集——写路径闸门短路时随返回透出（实测）。
#: state 取值 = ACCEPT / REJECT / DEFER / BLINDSPOT（四态资格裁决）。
VERDICT_FIELDS = ("state", "kind", "basis", "evidence", "detail")

VERB_SPECS = {
    "route": {
        "status": "live",
        "mutating": False,
        "impl": ("mcp_server", "_cg_dispatch"),
        "requires_any": (("intent", "query"),),
        "optional": ("k", "context"),
        "shapes": {
            "default": {
                "when": "恒",
                "required": ("knowledge", "meta"),
                "optional": ("suggested_capabilities", "note"),
            },
        },
        "semantics": "只给知识与建议能力名，不执行；由调用方决定下一步",
    },
    "read": {
        "status": "live",
        "mutating": False,
        "impl": ("mcp_server", "_cg_dispatch"),
        "requires_any": (("node_id",), ("query", "intent"), ("budget_tokens",)),
        "optional": ("offset", "k", "context", "goal", "include_recent", "limit",
                     "session", "validity", "layer", "branch"),
        "shapes": {
            "node": {
                "when": "node_id 非空且目标存在且可见",
                "required": ("id", "path", "frontmatter", "content",
                             "verification_state"),
                "optional": ("truncated", "content_lines", "content_bytes",
                             "offset", "next_offset", "note"),
            },
            "node_missing": {
                "when": "node_id 非空但目标不存在 / 不可见 / 已软删",
                "returns_null": True,
                "required": (),
                "optional": (),
                "note": "**实测返回 null**（不是错误对象）——客户端须先判空再解析，"
                        "把 null 当异常会误报；把 null 当空内容会静默吞未知",
            },
            "list": {
                "when": "budget_tokens 为空",
                "required": ("meta", "results"),
                "optional": (),
            },
            "pack": {
                "when": "budget_tokens 非空（优先于 node_id 之外的 query 路径）",
                "required": ("pack", "tokens_used", "budget", "skipped", "recent",
                             "meta"),
                "optional": (),
            },
        },
        "semantics": "读动词三分态：单节点视图 / 检索结果列表 / token 预算包",
    },
    "write": {
        "status": "live",
        "mutating": True,
        "impl": ("writepipe", "default_pipeline"),
        "requires_any": (("content",),),
        "optional": ("content_kind", "layer", "tags", "importance",
                     "verification_basis", "condition_space",
                     "non_applicable_conditions", "depends_on", "derived_from",
                     "relation", "valid_from", "valid_until", "verification_state",
                     "consistency", "on_conflict", "gated", "override",
                     "importance_hint", "semantic", "node_id"),
        "shapes": {
            "committed": {
                "when": "链尾执行器落盘",
                "required": WRITE_TRIO,
                "optional": ("verdict", "consistency", "propagation"),
            },
            "gate_short_circuit": {
                "when": "任一 before 闸门短路（审核 REJECT / DEFER / 冲突）",
                "required": WRITE_TRIO + ("moved_to", "verdict", "hint"),
                "optional": ("pid", "dedup", "dup_of", "dup_status", "consistency"),
            },
            "gate_hard_reject": {
                "when": "契约缺失硬拒（依赖声明闸 E050/E051）",
                "required": WRITE_TRIO + ("gate", "error", "hint"),
                "optional": ("missing", "verdict"),
            },
            "gate_gated": {
                "when": "主动遗忘闸（gated=true）替代落盘路径",
                "required": WRITE_TRIO + ("gate", "verdict"),
                "optional": ("consistency", "moved_to", "propagation"),
            },
        },
        "semantics": "写动词多形态：committed=已落盘；未 committed 时 moved_to/gate 说明去向，"
                     "hint 说明「闸门正常行为、不是工具故障、重试同样结果」",
    },
    "supersede": {
        "status": "reserved",
        "mutating": True,
        "impl": None,
        "requires_any": (("node_id",), ("superseded_by",)),
        "optional": ("reason", "inherit_verification", "propagate"),
        "shapes": {
            "planned": {
                "when": "（预留位，尚未实现）",
                "required": ("ok", "id", "superseded_by"),
                "optional": ("supersedes", "propagation", "verdict"),
            },
        },
        "semantics": "以新节点取代旧节点：旧节点保留可审计但退出默认检索面，取代关系可追溯",
        "map_to": (
            {"verb": "write", "note": "新节点写入本身走 write（五动词不重复造写入通道）"},
            {"verb": "review/verify", "note": "现有撤回体系由校验（verify 验伪）与审核"
                                             "（review 的 delete/merge）承担，无独立取代动词"},
            {"field": "nodefile.believed_at", "note": "取代语义的锚字段已就位（写侧注释），"
                                                      "缺的是动词入口与检索面过滤"},
        ),
        "reserved_reason": "取代会改变默认检索面（被取代节点是否可见），属行为变更，"
                           "须先冻结协议再落实现——避免三端各自发明可见性口径",
    },
    "forget": {
        "status": "live",
        "mutating": True,
        "impl": ("mdcos", "MdCG.forget"),
        "requires_any": (("node_id",),),
        "optional": ("reason", "override", "action"),
        "shapes": {
            "forgotten": {
                "when": "action 缺省或非 restore",
                "required": ("ok", "id", "tombstone"),
                "optional": (),
            },
            "restored": {
                "when": "action == 'restore'",
                "required": ("ok", "id", "forced"),
                "optional": (),
            },
            "failed": {
                "when": "目标不存在 / 已 tombstone（未 force）/ trash 无文件 / OSError",
                "required": ("ok", "error"),
                "optional": ("reason", "t", "action", "action_derived",
                             "hint_action"),
            },
        },
        "semantics": "软删除与恢复：文件移入 trash/、写删除清单、摘索引；受保护节点需 override",
    },
}


# 生效条件：node 为 ast 表达式节点；沿 Attribute/Call 递归剥到 Name，命中 Name("op") 返回 True，落到其它节点类型（含常量/字面量）返回 False；
def _is_op_expr(node) -> bool:
    """判断 AST 表达式是否指向 `op`（兼容 `op.strip().lower()` 形态）。"""
    cur = node
    while True:
        if isinstance(cur, ast.Name):
            return cur.id == "op"
        if isinstance(cur, ast.Attribute):
            cur = cur.value
            continue
        if isinstance(cur, ast.Call):
            cur = cur.func
            continue
        return False


# 生效条件：src 为字符串源码（缩进任意，内部先 dedent）；ast.parse 成功返回按出现序去重的 op 字面量列表（识别 `op == "x"` 与 `op in ("x","y")` 两种形态，op 侧兼容 `op.strip().lower()`），解析失败（SyntaxError/TypeError/任意异常）返回空列表，不抛异常；
def _ops_from_source(src: str) -> list:
    """从源码文本提取 op 分支名（dispatch_ops 与测试共用；测试可直接喂合成源码）。"""
    try:
        tree = ast.parse(textwrap.dedent(src or ""))
    except Exception:                                       # noqa: BLE001
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or not _is_op_expr(node.left):
            continue
        for opnode, comp in zip(node.ops, node.comparators):
            items = []
            if isinstance(opnode, ast.Eq):
                items = [comp]
            elif isinstance(opnode, ast.In) and isinstance(
                    comp, (ast.Tuple, ast.List, ast.Set)):
                items = list(comp.elts)
            for it in items:
                if isinstance(it, ast.Constant) and isinstance(it.value, str):
                    if it.value not in out:
                        out.append(it.value)
    return out


# 生效条件：module 缺省取 SURFACE_MODULE、func 缺省取 DISPATCH_FUNC；导入模块 / 取属性 / getsource 任一抛异常，返回 {"ok": False, "error": "<类型>: <消息>", "ops": []}；成功返回 {"ok": True, "module", "func", "ops": 按出现序去重的 op 字面量列表}；
def dispatch_ops(module: str = None, func: str = None) -> dict:
    """从分发函数源码用 **AST** 提取 op 分支（`if op == "x"` 与 `op in ("x","y")`）。

    为何用 AST 而非正则：正则对单引号/换行/`op.strip().lower()` 形态会静默漏提，
    而「漏提」在本协议里等于假绿灯（cogmap 已有同类教训）。AST 结构性识别不依赖写法。
    """
    mod_name = module or SURFACE_MODULE
    fn_name = func or DISPATCH_FUNC
    try:
        m = __import__(mod_name, fromlist=[fn_name])
        obj = getattr(m, fn_name)
        src = inspect.getsource(obj)
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "ops": []}
    return {"ok": True, "module": mod_name, "func": fn_name,
            "ops": _ops_from_source(src)}


# 生效条件：module/func 透传 dispatch_ops（默认面取模块常量）；始终返回 dict，含 protocol_version/frozen/doc/live/reserved/declared/actual/has_impl/missing_impl/extension_ops/reserved_leaked/shape_errors/derive/errors/ok，任一静态对账项失败则 ok=False 且失败明细进 errors；
def audit(module: str = None, func: str = None) -> dict:
    """静态对账：协议声明 ↔ MCP 面实现（不连库、不执行，纯源码事实）。"""
    got = dispatch_ops(module, func)
    actual = list(got.get("ops") or [])
    declared = list(VERBS)
    live = [v for v in declared if VERB_SPECS[v].get("status") == "live"]
    reserved = [v for v in declared if VERB_SPECS[v].get("status") == "reserved"]
    has_impl = [v for v in declared if v in actual]
    missing_impl = [v for v in live if v not in actual]
    # 协议 v1 只冻结五动词；MCP 面其余 op 属**扩展能力面**——它们是能力不是违例。
    # 反向对账降级为报告项（extension_ops），理由见模块 docstring。
    extension_ops = [v for v in actual if v not in declared]
    reserved_leaked = [v for v in reserved if v in actual]
    shape_errors = []
    for v in declared:
        spec = VERB_SPECS[v]
        if spec.get("status") not in ("live", "reserved"):
            shape_errors.append(f"{v}: status 取值非法 {spec.get('status')!r}")
        shapes = spec.get("shapes") or {}
        if not shapes:
            shape_errors.append(f"{v}: 未声明任何形状")
        for sname, sh in shapes.items():
            if not sh.get("required") and not sh.get("returns_null"):
                shape_errors.append(
                    f"{v}.{sname}: required 为空且未声明 returns_null")
            if not sh.get("when"):
                shape_errors.append(f"{v}.{sname}: 缺 when（何时走该形态）")
        if spec.get("status") == "reserved" and not spec.get("map_to"):
            shape_errors.append(f"{v}: reserved 但未声明 map_to 现状映射证据")
        if spec.get("status") == "live" and not spec.get("impl"):
            shape_errors.append(f"{v}: live 但未声明 impl 落点")
    errors = []
    if not got.get("ok"):
        errors.append(f"源码提取失败：{got.get('error')}")
    if missing_impl:
        errors.append(f"声明为 live 但 MCP 面无分支：{missing_impl}")
    if reserved_leaked:
        errors.append(f"reserved 动词出现实现分支（实现了却未登记）：{reserved_leaked}")
    if shape_errors:
        errors.append(f"形状声明不完整：{shape_errors}")
    return {"protocol_version": PROTOCOL_VERSION, "frozen": FROZEN,
            "doc": PROTOCOL_DOC, "declared": declared, "live": live,
            "reserved": reserved, "actual": actual, "has_impl": has_impl,
            "missing_impl": missing_impl, "extension_ops": extension_ops,
            "reserved_leaked": reserved_leaked, "shape_errors": shape_errors,
            "derive": list(OP_DERIVE), "errors": errors, "ok": not errors}


# 生效条件：verb 为 VERBS 成员时返回其 VERB_SPECS 规格 dict，非成员（含 None/空串）抛 KeyError；
def spec_of(verb: str) -> dict:
    """取动词规格（非声明动词直接抛 KeyError——fail-closed，不返回空壳）。"""
    return VERB_SPECS[verb]


# 生效条件：verb 已声明且 shape 为该动词 shapes 的键时返回该形态 dict；shape 缺省（None/空串）时返回其第一个形态；verb 未声明或 shape 不存在抛 KeyError；
def shape_of(verb: str, shape: str = None) -> dict:
    """取某动词的形态声明（shape 缺省取第一个）。"""
    shapes = VERB_SPECS[verb]["shapes"]
    return shapes[shape] if shape else shapes[next(iter(shapes))]


# 生效条件：无入参；始终返回单行字符串（格式 "protocol v1 live=4/5 reserved=1 ops=4 ok=True"），不抛异常；
def summary() -> str:
    """单行结论（供 sustain / 报告页眉引用）。"""
    a = audit()
    return (f"protocol v{PROTOCOL_VERSION} live={len(a['live'])}/{len(a['declared'])} "
            f"reserved={len(a['reserved'])} ops={len(a['actual'])} "
            f"ext={len(a['extension_ops'])} ok={a['ok']}")


# 生效条件：argv 为 None 时 argparse 取 sys.argv；--json 为真时打印缩进 JSON，否则打印人类可读多行；返回 0（ok）或 1（对账失败）；
def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m md_cg.protocol",
                                description="记忆动词协议 v1 静态对账（只读，零写入）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    a = p.parse_args(argv)
    rep = audit()
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"== {summary()}   doc={rep['doc']}   frozen={rep['frozen']}")
        print(f"   声明 = {rep['declared']}")
        print(f"   MCP 实际 = {rep['actual']}")
        print(f"   扩展能力面（不属协议 v1，共 {len(rep['extension_ops'])} 项）"
              f"= {rep['extension_ops']}")
        for v in rep["declared"]:
            s = VERB_SPECS[v]
            print(f"   [{s['status']:8s}] {v}: "
                  f"{len(s['shapes'])} 形态 / requires_any={s['requires_any']}")
        for e in rep["errors"]:
            print(f"   !! {e}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
