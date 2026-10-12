# -*- coding: utf-8 -*-
"""MCP 工具面 op 元数据**三向对账守卫**（issue #133 + #140）。

【守什么】
op 元数据修前分散在 6 处（cg 的 op 枚举串字面量 / cg 工具 description 的段落文本 /
`_ACTION_SIGS` / `_ACTION_DEFAULT` / `_cg_dispatch` 的 `require_op` 实参 /
`tool_face.TOOL_BRIEFS` 的散文计数），**四份 op 清单互不对账**——实测把枚举串里的
`|ccg|` 删掉，`md_cg/test_tool_face`（23 passed）与 `md_cg/test_protocol`（44 passed）
**双双仍绿**，而服务端仍接受 `ccg`。本守卫补上那个缺口。

真源（单点）：`md_cg/op_table.py` 的 `_OP_TABLE`。本守卫断言：

  ① **enum ↔ dispatch ↔ schema 三向对账**
     · enum（运行期 `cg` 工具 op 参数的枚举串）== dispatch（`protocol.dispatch_ops()`
       从 `_cg_dispatch` 源码 AST 提取的分支名）——**双向**；
     · enum == `_OP_TABLE` 的键（**顺序也相等**：顺序是枚举串对外契约的一部分）；
     · 表登记的每个 op 专属参数都真实存在于 `cg` 的 schema.properties；
       且「全部 op 专属参数 ∪ 通用参数 == schema.properties − {op}」（无孤儿参数）。
  ② **`_OP_TABLE` 是唯一权威**（AST 断言）：`mcp_server.py` 的 cg description /
     op 枚举串 / stg 枚举串 / `_ACTION_SIGS` / `_ACTION_DEFAULT` 与 `tool_face.py`
     的 cg 职责行，**取值处必须是 `_ot.*` 的派生调用**，不得回写字面量；
     且两文件内不得再出现 op 枚举串字面量（≥3 个 `|` 且含 route/read/write）。
  ③ **`tool_face.py` 无写死 op 计数**（源码不得出现 `\\d+\\s*op`）。
  ④ **定点变异自证**（`--mutate`）：逐条把「修复」抽掉，对账必须转红。
  ⑤ **失败编码形态登记 + 运行时逐位对账**：同一「失败」当前有 3 种 wire 编码
     （业务失败 `isError:false`+JSON / 异常 `isError:true`+JSON / read 缺失 `null`），
     本守卫把现状**登记**并做运行时抽样比对（防无意漂移），同时如实报告
     `failure_forms_unified=false`——**是否收敛为单一形态属对外行为变更，待裁定**
     （见 issue #133 报告的口径项）。

【为什么用 AST/运行期而非正则】正则对写法（单引号/换行/`op.strip().lower()`）会静默
漏提，而「漏提」在本仓等于假绿灯（`protocol._ops_from_source` 的既有教训）。

退出码（机器可判，**绝不静默退 0**）：
  0  全部对账通过
  1  存在对账失败项
  2  环境/解析错误（fail-closed）
  3  变异自证未转红（守卫本身失效）

用法：
  python -X utf8 scripts/check_op_table_parity.py            # 人读报告
  python -X utf8 scripts/check_op_table_parity.py --json     # 机器读
  python -X utf8 scripts/check_op_table_parity.py --mutate   # 定点变异自证
  python -X utf8 scripts/check_op_table_parity.py --selftest # 合成语料自检（不看本仓）
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

EXIT_MEANING = {
    0: "全部对账通过",
    1: "存在对账失败项",
    2: "环境/解析错误（fail-closed）",
    3: "变异自证未转红（守卫本身失效）",
}

# ---------------------------------------------------------------------------
# 失败编码形态登记（现状；「收敛为单一形态」属对外行为变更，待裁）
# ---------------------------------------------------------------------------
FAILURE_FORMS = {
    "tool_business_error": {
        "when": "工具返回 dict 且 ok is False（业务失败，不是异常）",
        "isError": False,
        "json_has": ("ok", "error"),
        "probe": ("cg", {"op": "ccg", "action": "compile"}),   # 缺 dialog → {ok:false,...}
    },
    "tool_exception": {
        "when": "工具抛异常（未知 action / 未知工具名）",
        "isError": True,
        "json_has": ("error",),
        "probe": ("cg", {"op": "theory", "action": "__no_such_action__"}),
    },
    "read_node_missing": {
        "when": "read(node_id=不存在) —— 协议登记的 null 形态（returns_null=True）",
        "isError": False,
        "text_is_null": True,
        "probe": ("cg", {"op": "read", "node_id": "mem___no_such_node__"}),
    },
}

_OP_ENUM_LITERAL_RE = re.compile(r"\d+\s*op")
_ENUM_ISH_RE = re.compile(r"[a-z_]+(?:\|[a-z_]+){3,}")

# 沙箱环境（**绝不触碰在役记忆库**）：一律 tempdir 根，显式设三个 MDCG_* 键。
_SANDBOX_KEYS = ("MDCG_ROOT", "MDCG_AUX_ROOT", "MDCG_MASTER_KEY", "MDCG_SUSTAIN")


def enter_sandbox() -> tuple:
    """把 MDCG_* 指向全新 tempdir；返回 (根, 恢复回调)。fail-closed：只碰 tempdir。"""
    tmp = tempfile.mkdtemp(prefix="mdcg_opparity_")
    saved = {k: os.environ.get(k) for k in _SANDBOX_KEYS}
    os.environ["MDCG_ROOT"] = tmp
    # 末段不得是 Windows 保留设备名（aux/nul/com1…）——datapath 会 fail-closed 拒。
    os.environ["MDCG_AUX_ROOT"] = os.path.join(tmp, "mdcgaux")
    os.environ["MDCG_MASTER_KEY"] = "0" * 64
    os.environ["MDCG_SUSTAIN"] = "0"

    def restore():
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    return tmp, restore


# ---------------------------------------------------------------------------
# 输入采集
# ---------------------------------------------------------------------------
def _read(rel: str) -> str:
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


def _cg_tool_dict(tree: ast.AST):
    """在 KERNEL_TOOLS 里定位 name=="cg" 的 dict 节点。"""
    for n in ast.walk(tree):
        if not isinstance(n, ast.Dict):
            continue
        nm = [v.value for k, v in zip(n.keys, n.values)
              if isinstance(k, ast.Constant) and k.value == "name"
              and isinstance(v, ast.Constant)]
        if nm and nm[0] == "cg":
            return n
    return None


def _kwarg(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def collect() -> dict:
    """从**真实源**采集对账输入（纯读，不落盘）。"""
    src_ms = _read("md_cg/mcp_server.py")
    src_tf = _read("md_cg/tool_face.py")
    tree_ms = ast.parse(src_ms)
    tree_tf = ast.parse(src_tf)

    from md_cg import mcp_server as ms          # noqa: PLC0415
    from md_cg import op_table as ot            # noqa: PLC0415
    from md_cg import protocol as P             # noqa: PLC0415

    cg = [t for t in ms.KERNEL_TOOLS if t["name"] == "cg"][0]
    stg = [t for t in ms.KERNEL_TOOLS if t["name"] == "stg"][0]
    enum = [x for x in cg["inputSchema"]["properties"]["op"]["description"].split("|") if x]
    props = cg["inputSchema"]["properties"]
    dispatch = P.dispatch_ops()

    return {
        "table": dict(ot._OP_TABLE),
        "table_order": list(ot._OP_TABLE),
        "enum": enum,
        "stg_enum": [x for x in stg["inputSchema"]["properties"]["op"]["description"].split("|") if x],
        "stg_table": list(ot.stg_ops()),
        "dispatch_ok": dispatch.get("ok"),
        "dispatch": list(dispatch.get("ops") or []),
        "props": list(props),
        "params_of": {o: list(ot.params_of(o)) for o in ot.op_names()},
        "generic": sorted(ot.generic_params()),
        "action_default": ot.action_default(),
        "action_sigs": {k: [list(x) for x in v] for k, v in ot.action_sigs().items()},
        "cg_desc": cg["description"],
        "src_ms": src_ms,
        "src_tf": src_tf,
        "tree_ms": tree_ms,
        "tree_tf": tree_tf,
        "cg_desc_from_table": ot.cg_description(),
        "section_ops": list(ot._OP_TABLE),
    }


# ---------------------------------------------------------------------------
# 对账判据（纯函数：输入 → 失败项列表；便于变异注入）
# ---------------------------------------------------------------------------
def _require_op_map(tree: ast.AST) -> dict:
    """从 `_cg_dispatch` 源码 AST 提取 op → require 词（`require_op` 实参）。

    `_p.require_op("write" if op == "state_event" else op)` 形态解析为
    {"state_event": "write", "*": "self"}；`*` 表示「用 op 自身」。
    """
    out: dict = {}
    fn = None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "_cg_dispatch":
            fn = n
            break
    if fn is None:
        return {"__error__": "未找到 _cg_dispatch"}
    for sub in ast.walk(fn):
        if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "require_op" and sub.args):
            continue
        arg = sub.args[0]
        if isinstance(arg, ast.IfExp):
            test = arg.test
            if (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                    and test.left.id == "op" and isinstance(test.comparators[0], ast.Constant)):
                key = test.comparators[0].value
                val = arg.body.value if isinstance(arg.body, ast.Constant) else None
                out[key] = val
                out.setdefault("*", arg.orelse.id if isinstance(arg.orelse, ast.Name) else None)
                continue
        if isinstance(arg, ast.Name):
            out.setdefault("*", arg.id)
    return out


def parity(inp: dict) -> dict:
    """三向对账 + 唯一权威 + 计数 + 失败形态登记。返回 {errors, notes, readings}。"""
    errors: list = []
    notes: list = []
    readings: dict = {}

    enum, dispatch, table, order = (inp["enum"], inp["dispatch"], inp["table"],
                                    inp["table_order"])
    readings["n_enum"] = len(enum)
    readings["n_dispatch"] = len(dispatch)
    readings["n_table"] = len(table)
    readings["n_sections"] = sum(1 for t in table.values() if t.get("doc"))

    # ---- ① enum ↔ dispatch ↔ schema ----
    if not inp.get("dispatch_ok"):
        errors.append("protocol.dispatch_ops() 源码提取失败（fail-closed）")
    se, sd, st = set(enum), set(dispatch), set(table)
    if se != sd:
        errors.append("enum ↔ dispatch 不相等：仅 enum=%s 仅 dispatch=%s"
                      % (sorted(se - sd), sorted(sd - se)))
    if se != st:
        errors.append("enum ↔ _OP_TABLE 键不相等：仅 enum=%s 仅表=%s"
                      % (sorted(se - st), sorted(st - se)))
    if list(order) != list(enum):
        errors.append("表插入序 != 枚举串顺序（顺序是枚举串对外契约的一部分）")
    if inp["stg_enum"] != inp["stg_table"]:
        errors.append("stg 枚举串 != _STG_OPS：%s vs %s"
                      % (inp["stg_enum"], inp["stg_table"]))
    # 段落面：枚举里除 help（无段落）外，每个 op 都要有段落
    doc_ops = [o for o in table if table[o].get("doc")]
    missing_doc = sorted(se - set(doc_ops) - {"help"})
    if missing_doc:
        errors.append("以下 op 无说明段（常驻面与按需面都会丢）：%s" % missing_doc)
    extra_doc = sorted(set(doc_ops) - se)
    if extra_doc:
        errors.append("段落里有枚举外的 op（幻影段）：%s" % extra_doc)
    if inp.get("cg_desc_from_table") != inp.get("cg_desc"):
        errors.append("cg description 与表的段落拼接不逐字相等（漂移）")
    readings["desc_chars"] = len(inp.get("cg_desc") or "")

    # 参数归属：表登记 ⊆ schema；并集 + 通用 == schema − {op}
    props = set(inp["props"])
    ph = set(props) - {"op"}
    union = set()
    for o, ps in inp["params_of"].items():
        ghost = sorted(set(ps) - props)
        if ghost:
            errors.append("op=%s 登记了 schema 里不存在的参数（幻影参数）：%s" % (o, ghost))
        union |= set(ps)
    covered = union | set(inp["generic"])
    if covered != ph:
        errors.append("参数归属有缺口：未覆盖=%s 越界=%s"
                      % (sorted(ph - covered), sorted(covered - ph)))
    readings["n_props"] = len(props)
    readings["n_params_union"] = len(union)
    readings["n_generic"] = len(inp["generic"])

    # ---- ② _OP_TABLE 是唯一权威（AST） ----
    tree_ms = inp["tree_ms"]
    cgdict = _cg_tool_dict(tree_ms)

    def _is_call(node, attr: str) -> bool:
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == attr
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "_ot")

    if cgdict is None:
        errors.append("mcp_server 里未找到 cg 工具定义（fail-closed）")
    else:
        d = [v for k, v in zip(cgdict.keys, cgdict.values)
             if isinstance(k, ast.Constant) and k.value == "description"]
        if not d or not _is_call(d[0], "cg_description"):
            errors.append("cg description 未从 _ot.cg_description() 派生")
        isch = [v for k, v in zip(cgdict.keys, cgdict.values)
                if isinstance(k, ast.Constant) and k.value == "inputSchema"]
        opv = _kwarg(isch[0], "op") if isch else None
        inner = opv.args[1] if (isinstance(opv, ast.Call) and len(opv.args) > 1) else None
        if not _is_call(inner, "op_enum"):
            errors.append("cg op 枚举串未从 _ot.op_enum() 派生")
    # stg 枚举串
    stg_ok = False
    for n in ast.walk(tree_ms):
        if isinstance(n, ast.Dict):
            nm = [v.value for k, v in zip(n.keys, n.values)
                  if isinstance(k, ast.Constant) and k.value == "name"
                  and isinstance(v, ast.Constant)]
            if nm and nm[0] == "stg":
                isch = [v for k, v in zip(n.keys, n.values)
                        if isinstance(k, ast.Constant) and k.value == "inputSchema"]
                opv = _kwarg(isch[0], "op") if isch else None
                inner = (opv.args[1] if (isinstance(opv, ast.Call) and len(opv.args) > 1)
                         else None)
                stg_ok = _is_call(inner, "stg_op_enum")
    if not stg_ok:
        errors.append("stg op 枚举串未从 _ot.stg_op_enum() 派生")
    # _ACTION_SIGS / _ACTION_DEFAULT
    for var, fn in (("_ACTION_SIGS", "action_sigs"), ("_ACTION_DEFAULT", "action_default")):
        val = None
        for n in ast.walk(tree_ms):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id == var:
                        val = n.value
        if not _is_call(val, fn):
            errors.append("%s 未从 _ot.%s() 派生" % (var, fn))
    # 不得回写 op 枚举串字面量
    for rel, tree in (("md_cg/mcp_server.py", tree_ms), ("md_cg/tool_face.py", inp["tree_tf"])):
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                v = n.value
                if _ENUM_ISH_RE.search(v) and all(w in v for w in ("route", "read", "write")):
                    errors.append("%s:%d 出现 op 枚举串字面量（应派生）"
                                  % (rel, getattr(n, "lineno", 0)))
    # tool_face 的 cg 职责行
    briefs_ok = False
    for n in ast.walk(inp["tree_tf"]):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == "TOOL_BRIEFS":
                    for k, v in zip(n.value.keys, n.value.values):
                        if isinstance(k, ast.Constant) and k.value == "cg":
                            briefs_ok = (isinstance(v, ast.Call)
                                         and isinstance(v.func, ast.Name)
                                         and v.func.id == "cg_brief")
    if not briefs_ok:
        errors.append("tool_face.TOOL_BRIEFS['cg'] 未从 cg_brief() 派生")

    # ---- ③ tool_face.py 无写死 op 计数 ----
    hits = []
    for m in _OP_ENUM_LITERAL_RE.finditer(inp["src_tf"]):
        ln = inp["src_tf"][:m.start()].count("\n") + 1
        hits.append("L%d:%r" % (ln, m.group(0)))
    if hits:
        errors.append("tool_face.py 有写死 op 计数：%s" % hits[:5])
    readings["tool_face_hardcoded_counts"] = len(hits)

    # ---- ④ require 词 ↔ 表 ----
    reqmap = _require_op_map(tree_ms)
    readings["require_map"] = reqmap
    if "__error__" in reqmap:
        errors.append(reqmap["__error__"])
    else:
        self_key = reqmap.get("*")          # "op" 表示「用 op 变量自身」；None 表示未取到
        for op in enum:
            tab = table.get(op, {}).get("require")
            if op == "help":
                # help 在 require_op 之前短路（见 _cg_dispatch 首行），故表登记 None
                if tab is not None:
                    errors.append("op=help 应无 require 词，表登记了 %r" % tab)
                continue
            if tab is None:
                errors.append("op=%s 未在表中登记 require 词" % op)
                continue
            if op in reqmap:
                got = reqmap[op]            # 显式条件分支（如 state_event → write）
            elif self_key == "op":
                got = op                    # `require_op(op)`：权限词 = op 名自身
            else:
                got = self_key
            if got != tab:
                errors.append("op=%s 的 require 词对不上：表=%r dispatch=%r"
                              % (op, tab, got))

    # ---- ⑤ 二级子 op 登记 ----
    sub = {o: list(table[o].get("actions") or ()) for o in table}
    readings["n_sub_ops"] = sum(len(v) for v in sub.values())
    readings["n_ops_with_sub"] = sum(1 for v in sub.values() if v)
    for probe in ("rounds", "handshake", "catalog"):
        if not any(probe in v for v in sub.values()):
            errors.append("二级子 op %r 未登记进 _OP_TABLE.actions" % probe)
    # 缺省 action 必须在该 op 的 actions 登记内（防幻影缺省）
    for op, act in inp["action_default"].items():
        if op in sub and sub[op] and act not in sub[op]:
            errors.append("op=%s 缺省 action=%s 不在其 actions 登记内" % (op, act))
    # 签名推导的目标 action 同理
    for op, pairs in inp["action_sigs"].items():
        for _key, act in pairs:
            if op in sub and sub[op] and act not in sub[op]:
                errors.append("op=%s 签名推导目标 %s 不在 actions 登记内" % (op, act))

    # ---- ⑥ 失败编码形态登记 ----
    readings["failure_forms"] = sorted(FAILURE_FORMS)
    readings["failure_forms_unified"] = len(FAILURE_FORMS) == 1
    notes.append("失败编码当前 %d 种 wire 形态（业务失败/异常/read null）；"
                 "**收敛为单一形态属对外行为变更，待裁定**" % len(FAILURE_FORMS))

    return {"errors": errors, "notes": notes, "readings": readings}


# ---------------------------------------------------------------------------
# 失败编码运行时抽样（真起 cg + _serve_line，沙箱根）
# ---------------------------------------------------------------------------
def probe_failure_forms() -> list:
    """在**沙箱根**上逐形态真调 `_serve_line`，比对 wire 编码是否与登记一致。

    前提：调用方已 `enter_sandbox()`（环境变量指向 tempdir）。本函数**不再**自建根，
    以免与 `collect()` 的 import 面用两套根（crypto 的 MASTER_FILE 在 import 时定值）。
    """
    fails: list = []
    tmp = os.environ.get("MDCG_ROOT")
    if not tmp:
        return ["未进入沙箱（MDCG_ROOT 为空）——拒绝在役库上抽样"]
    try:
        from md_cg import mcp_server as ms                  # noqa: PLC0415
        from md_cg.mdcos import MdCGSecure                  # noqa: PLC0415
        from md_cg.security import DEFAULT_SENSITIVITY, Principal  # noqa: PLC0415
        p = Principal(actor="opparity", clearance=DEFAULT_SENSITIVITY,
                      can_write=True, can_admin=True, role="designer")
        cg = MdCGSecure(tmp, principal=p)

        def wire(name, args):
            buf, old = io.StringIO(), sys.stdout
            sys.stdout = buf
            try:
                ms._serve_line(cg, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": name, "arguments": args}})
            finally:
                sys.stdout = old
            return json.loads(buf.getvalue().strip())

        for fname, spec in FAILURE_FORMS.items():
            name, args = spec["probe"]
            msg = wire(name, args)
            res = msg.get("result") or {}
            got_iserror = res.get("isError")
            if got_iserror is not spec["isError"]:
                fails.append("%s：isError=%r 期望 %r" % (fname, got_iserror, spec["isError"]))
            text = (res.get("content") or [{}])[0].get("text")
            if spec.get("text_is_null"):
                if text != "null":
                    fails.append("%s：text=%r 期望 'null'" % (fname, text))
                continue
            try:
                obj = json.loads(text or "{}")
            except ValueError:
                fails.append("%s：text 不是 JSON：%r" % (fname, text))
                continue
            miss = [k for k in spec.get("json_has", ()) if k not in obj]
            if miss:
                fails.append("%s：wire JSON 缺键 %s（实得 %s）"
                             % (fname, miss, sorted(obj)))
    except Exception as exc:                                # noqa: BLE001
        fails.append("运行时抽样异常：%s: %s" % (type(exc).__name__, exc))
    return fails


# ---------------------------------------------------------------------------
# 定点变异（把修复抽掉 ⇒ 对账必红）
# ---------------------------------------------------------------------------
def mutations() -> tuple:
    """每条：(名字, 变异函数 inp→inp, 期望转红的判据关键词)。"""
    def m_drop_op(inp):
        inp = dict(inp)
        t = dict(inp["table"])
        t.pop("ccg", None)
        inp["table"] = t
        inp["table_order"] = [o for o in inp["table_order"] if o != "ccg"]
        inp["enum"] = [o for o in inp["enum"] if o != "ccg"]
        inp["cg_desc_from_table"] = inp["cg_desc_from_table"].replace("op=ccg：", "op=__x__：")
        return inp

    def m_keep_enum_only(inp):
        """只删枚举串（表与 dispatch 保留）——复现 issue 的原始变异。"""
        inp = dict(inp)
        inp["enum"] = [o for o in inp["enum"] if o != "ccg"]
        return inp

    def m_break_require(inp):
        inp = dict(inp)
        src = inp["src_ms"].replace(
            '        _p.require_op("write" if op == "state_event" else op)',
            '        _p.require_op("read")')
        inp["src_ms"] = src
        inp["tree_ms"] = ast.parse(src)
        return inp

    def m_hardcode_count(inp):
        inp = dict(inp)
        inp["src_tf"] = inp["src_tf"].replace(
            'def cg_brief() -> str:', 'CG_BRIEF_HEAD = "灵枢认知图唯一入口（34 op）"\n'
                                      'def cg_brief() -> str:')
        return inp

    def m_revert_literal(inp):
        inp = dict(inp)
        inp["src_ms"] = inp["src_ms"].replace(
            '"description": _ot.cg_description(),',
            '"description": "op=route：x；op=read：y；op=write：z；op=verify：w；",')
        inp["tree_ms"] = ast.parse(inp["src_ms"])
        return inp

    return (
        ("M1 删表里的 ccg（enum/表少一项，dispatch 仍有）", m_drop_op, "不相等"),
        ("M2 只删枚举串的 ccg（issue 原始变异）", m_keep_enum_only, "不相等"),
        ("M3 把 state_event 的 require 词改成 read", m_break_require, "require"),
        ("M4 在 tool_face 回写死 op 计数「34 op」", m_hardcode_count, "写死 op 计数"),
        ("M5 把 cg description 回退成字面量", m_revert_literal, "派生"),
    )


def run_mutations() -> int:
    print("!! 定点变异自证：逐条抽掉修复，对账必须转红\n")
    base = collect()
    clean = parity(base)
    print("  未变异基线：失败=%d（必须为 0）" % len(clean["errors"]))
    if clean["errors"]:
        for e in clean["errors"]:
            print("     !! %s" % e)
        return 3
    bad = []
    for name, fn, keyword in mutations():
        try:
            rep = parity(fn(base))
        except Exception as exc:                            # noqa: BLE001
            print("  %-46s [EXC] %s: %s" % (name, type(exc).__name__, exc))
            bad.append(name)
            continue
        hit = [e for e in rep["errors"] if keyword in e]
        if hit:
            print("  %-46s [OK] 转红：%s" % (name, hit[0][:88]))
        else:
            print("  %-46s [MISS] 未转红（守卫对该变异无判别力）" % name)
            bad.append(name)
    print("")
    if bad:
        print("  变异自证：%d/%d 未转红" % (len(bad), len(mutations())))
        return 3
    print("  变异自证：%d/%d 全部转红" % (len(mutations()), len(mutations())))
    return 0


# ---------------------------------------------------------------------------
# 自检（合成语料，不看本仓）
# ---------------------------------------------------------------------------
def selftest() -> int:
    fails: list = []
    base = collect()
    if parity(base)["errors"]:
        fails.append("基线非绿（本仓现状未通过对账）")
    # 判据有判别力：每条变异必须转红
    for name, fn, keyword in mutations():
        rep = parity(fn(base))
        if not [e for e in rep["errors"] if keyword in e]:
            fails.append("变异未转红：%s" % name)
    # 失败形态登记非空且覆盖三类
    if len(FAILURE_FORMS) < 3:
        fails.append("失败形态登记不足 3 类")
    for f in fails:
        print("  [FAIL] " + f)
    if fails:
        print("\n  自检：%d 项失败" % len(fails))
        return 1
    print("  自检：全部通过（对账判据 + 5 条定点变异均有判别力）")
    return 0


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description="MCP 工具面 op 元数据三向对账守卫")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--skip-runtime", action="store_true",
                    help="跳过失败编码运行时抽样（纯静态对账）")
    a = ap.parse_args(argv)

    if a.selftest:
        _tmp, _restore = enter_sandbox()
        try:
            return selftest()
        finally:
            _restore()
    if a.mutate:
        _tmp, _restore = enter_sandbox()
        try:
            return run_mutations()
        finally:
            _restore()

    _tmp, _restore = enter_sandbox()
    try:
        try:
            rep = parity(collect())
        except Exception as exc:                            # noqa: BLE001
            print("  VERDICT=FAIL(环境)：%s: %s" % (type(exc).__name__, exc))
            return 2

        runtime_fails = [] if a.skip_runtime else probe_failure_forms()
    finally:
        _restore()
    errs = list(rep["errors"]) + ["[wire] " + x for x in runtime_fails]
    code = 1 if errs else 0

    if a.json:
        print(json.dumps({"ok": not errs, "errors": errs, "notes": rep["notes"],
                          "readings": rep["readings"], "exit_code": code,
                          "exit_meaning": EXIT_MEANING[code]},
                         ensure_ascii=False, indent=1))
    else:
        print("  MCP 工具面 op 元数据三向对账（issue #133 + #140）")
        print("  真源：md_cg/op_table.py::_OP_TABLE")
        print("")
        r = rep["readings"]
        print("  读数：enum=%d  dispatch(AST)=%d  _OP_TABLE=%d  段落=%d  schema 参数=%d"
              % (r["n_enum"], r["n_dispatch"], r["n_table"], r["n_sections"], r["n_props"]))
        print("        op 专属参数并集=%d  通用参数=%d  二级子 op=%d（跨 %d 个 op）"
              % (r["n_params_union"], r["n_generic"], r["n_sub_ops"], r["n_ops_with_sub"]))
        print("        cg description=%d 字符  tool_face 写死计数=%d"
              % (r["desc_chars"], r["tool_face_hardcoded_counts"]))
        print("        失败编码形态=%d 种（%s）  单一形态=%s"
              % (len(r["failure_forms"]), ", ".join(r["failure_forms"]),
                 r["failure_forms_unified"]))
        print("        require 词映射=%s" % r["require_map"])
        print("")
        for e in errs:
            print("  [FAIL] %s" % e)
        for n in rep["notes"]:
            print("  [注] %s" % n)
        if not errs:
            print("  全部对账通过。")
    print("")
    print("  退出码 %d：%s" % (code, EXIT_MEANING[code]))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
