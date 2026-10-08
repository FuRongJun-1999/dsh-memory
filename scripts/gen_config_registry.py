# -*- coding: utf-8 -*-
"""统一配置层 · registry 批量条目的**生成器**（一次性迁移工具，非运行期管线）。

用途
----
把「可调参数全量盘点」（`.tmp/param_inventory.json`）里**可机械复核**的条目，
连同源码 AST 的**逐位复核**，转写成 `md_cg/config_registry_bulk.py`（生成件）。
生成块一经产出即成为 registry 真源的一部分（冻结快照）——此后：

  · 改默认值 → 改**源码**（真源），守卫 `md_cg/config_registry_guard.py` 转红，
    再重跑本脚本补齐登记（或手工改登记，两者都会过守卫）；
  · 改登记体例 → 改本脚本 + `md_cg/config_registry.py` 的 SCHEMA，重跑。

为什么不直接进运行期：本批**只加机制**（登记／生成／守卫），读取点一律不动；
registry 不是运行时取值源，故生成器不进 import 链。

收录判据（全机械，无一例外）
--------------------------
【const 面】盘点里 `kind=const_literal` 且 `anchor` 形如 `文件 :: 「符号 =」`，
  且该符号在**该文件**的模块级确有赋值、且赋值右值可用 `ast.literal_eval` 取出者。
  取不出的（派生别名 / 非常量表达式）**一律不收录**，在报告里计数，不猜值。

【env 面】只收**策展名单**（`CURATED_ENV_NAMES`）里的 env 名；对每个名字在
  `md_cg/` 下做 AST 扫描，把「读取点 → 缺省」收成集合：
  · `os.environ.get("X", d)`        → 字面量缺省 d
  · `os.environ.get("X")`           → 无缺省（语义 = 关 / fail-open，按 `SEMANTICS` 定）
  · `os.environ.get(NAME, d)`       → NAME 为模块级 `NAME = "X"` 常量（间接入口）
  · `f(..., "X", ...)` 形参传名字   → 助手式读取（`_cap` / `check_path_root` / `_flag_on`）
  同一名字的**全部生产读取点**缺省一致才算解析成功；分叉者照实记 `conflict`
  （这本身就是待裁定证据，不许静默取其一）。

产出
----
`md_cg/config_registry_bulk.py`：`CONST_ENTRIES` / `ENV_ENTRIES` / `META`。

运行
----
    python -X utf8 scripts/gen_config_registry.py            # 写生成件
    python -X utf8 scripts/gen_config_registry.py --dry-run   # 只打印统计
"""
from __future__ import annotations

import ast
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_INVENTORY = os.path.join(REPO, ".tmp", "param_inventory.json")
OUT_MODULE = os.path.join(REPO, "md_cg", "config_registry_bulk.py")

SCAN_DIR = "md_cg"

#: 只收这些 env 名（第一批策展面）。其余 env 名不进第一批（报告里计未收录）。
#: 分层理由：五条真问题链上的项 + 三张既有真源表覆盖项 + 检索门控/缓存/身份/
#: 写路径白名单族 + 与它们同族、读取点唯一可控的开关。
CURATED_ENV_NAMES = [
    # 检索门控族（真问题 c）
    "MDCG_RETRIEVAL_PIPELINE", "MDCG_GATE_S1_DOMAIN", "MDCG_GATE_S2_COND",
    "MDCG_GATE_S3_SPREAD", "MDCG_GATE_S4_LAYER", "MDCG_GATE_S5_NEG",
    "MDCG_GATE_S6_CROSSCHECK", "MDCG_GATE_S7_POSTINGS", "MDCG_GATE_S1B_BUCKET",
    "MDCG_BUCKET_MIN_SIM", "MDCG_BUCKET_TOPK", "MDCG_SPREAD_GAIN",
    "MDCG_SPREAD_DECAY", "MDCG_NEG_SIM", "MDCG_NEG_LAMBDA", "MDCG_SPREAD_HOPS",
    "MDCG_LAYER_BOOST",
    # 缓存族（真问题 d）
    "MDCG_HOTCACHE", "MDCG_HOTCACHE_MAX_NODES", "MDCG_HOTCACHE_MAX_QUERIES",
    "MDCG_READ_CACHE",
    # 身份/工具面族（真问题 b）
    "MDCG_MCP_SURFACE", "MDCG_CLEARANCE", "MDCG_ACTOR", "MDCG_TENANT",
    "MDCG_TOOL_FACE",
    # 写路径白名单族（真问题 e）
    "MDCG_EXPORT_ROOT", "MDCG_INGEST_ROOT",
    # 跨仓默认分叉（真问题 a）
    "AEIS_DB", "AEIS_WORKSPACE",
    # 检索开关族
    "MDCG_SEMANTIC", "MDCG_EN_ATOMS", "MDCG_CN_GRAMS", "MDCG_CHAIN_TYPES",
    "MDCG_S7_FRESHNESS", "MDCG_UNIFY_QUERY", "MDCG_SCORE_MODE",
    "MDCG_TEMPORAL_GAMMA", "MDCG_LAYER_BOOST_DIR",
    # 会话/写入限流族
    "MDCG_WRITELIMIT", "MDCG_RECONCILE", "MDCG_REACH", "MDCG_REACH_DIFFUSE",
    "MDCG_REACH_TTL", "MDCG_POOLING",
    # 自治/预算族
    "MDCG_PROPOSAL_EMOTION", "MDCG_EXPLORE_BUDGET_MAX", "MDCG_EXPLORE_BUDGET_WINDOW",
    # 叙事/状态族
    "MDCG_D_META", "MDCG_STATUS_HEAD", "MDCG_FRESHNESS", "MDCG_SUSTAIN",
    "MDCG_HEARTBEAT_LEDGER",
    # 预测面
    "PREDICTION_META_DIM", "PREDICTION_META_PROXY",
    # 图像后端
    "IMGSKILL_BACKEND", "IMGSKILL_PILLOW",
]

#: 有「第 2 实参即缺省」语义的助手（其余助手把 env 名当实参但**无缺省**，
#: 如 `check_path_root(path, "MDCG_INGEST_ROOT", what)` —— 未配置 = 放行）。
HELPER_DEFAULT_CALLEES = ("_cap",)

#: 有效缺省由**同文件模块常量**给出的 env（读取点写作 `get(ENV) or ""` 再回落
#: 常量）——此表为**人工核验**的小名单，值由 const 面登记，此处只存符号指引。
DEFAULT_SYMBOL_OVERRIDE = {
    "MDCG_EXPLORE_BUDGET_WINDOW": ("md_cg/autonomy.py", "BUDGET_WINDOW_DEFAULT"),
}

#: 跨副本/跨侧同名分叉（AST 扫不到另一副本，故人工核验后写死在生成器里）。
#: 这些是「统一配置层」的硬障碍，登记时**照实标注**，不静默取一侧。
CROSS_SIDE_NOTES = {
    "AEIS_DB": ("★ 跨仓同名分叉：本仓（脑内副本 md_cg/whitebox_kb/wisdom/*）缺省 "
                "= os.path.join('data','lingshu.db')（相对路径**落盘**库）；"
                "私域仓 <私域仓>/aeis/{server.py,mcp/server.py} 缺省 \":memory:\""
                "（内存库）。同名同义假设不成立——落盘 vs 不落盘。"),
    "MDCG_MCP_SURFACE": ("★ 跨侧同名分叉：本仓 md_cg/mcp_server.py::SURFACE 缺省 "
                         "'kernel'；TS 侧 src/lib/mdcg_client.ts 缺省 'full'"
                         "（写入通道 mdcg_remember 属细粒度工具，故插件侧必须 full）。"
                         "两侧各有理由，属**待裁定/待文档并列**。"),
    "MDCG_CLEARANCE": ("★ 跨侧同名分叉：本仓 md_cg/mcp_server.py::_build_principal "
                       "缺省 'internal'；TS 侧 src/index.ts config.mdcg.clearance "
                       "缺省 'private'。令牌优先时 MDCG_CLEARANCE 完全被令牌覆盖"
                       "（代码已有 stderr 告警），但两侧缺省仍不一致。"),
}

#: env 的**有效缺省语义**（人工裁定字段，见设计文档 §4）：三面里「用户该调的
#: 开关」真正看的是这个，而不是 `os.environ.get` 第二实参的字面量。
#:   on       未设即开
#:   off      未设即关
#:   unset    未设 = 未配置（回落另一处默认表 / 由调用点给定）
#:   fail-open 未设 = 放行（写路径白名单，见 security.check_path_root）
#:   value    未设 = 给定数值缺省（value 字段即真值）
#:   enum     未设 = 给定枚举缺省（value 字段即真值）
#:   conflict 生产面缺省分叉（照实记，待裁定）
SEMANTICS = {
    # 检索门控族（真问题 c）
    "MDCG_RETRIEVAL_PIPELINE": "off",
    "MDCG_GATE_S1_DOMAIN": "on", "MDCG_GATE_S2_COND": "on",
    "MDCG_GATE_S3_SPREAD": "off", "MDCG_GATE_S4_LAYER": "off",
    "MDCG_GATE_S5_NEG": "off", "MDCG_GATE_S6_CROSSCHECK": "off",
    "MDCG_GATE_S7_POSTINGS": "off", "MDCG_GATE_S1B_BUCKET": "off",
    "MDCG_BUCKET_MIN_SIM": "value", "MDCG_BUCKET_TOPK": "value",
    "MDCG_SPREAD_GAIN": "value", "MDCG_SPREAD_DECAY": "value",
    "MDCG_NEG_SIM": "value", "MDCG_NEG_LAMBDA": "value",
    "MDCG_SPREAD_HOPS": "value", "MDCG_LAYER_BOOST": "unset",
    # 缓存族（真问题 d）
    "MDCG_HOTCACHE": "off", "MDCG_HOTCACHE_MAX_NODES": "value",
    "MDCG_HOTCACHE_MAX_QUERIES": "value", "MDCG_READ_CACHE": "on",
    # 身份/工具面族（真问题 b）
    "MDCG_MCP_SURFACE": "enum", "MDCG_CLEARANCE": "enum",
    "MDCG_ACTOR": "conflict", "MDCG_TENANT": "enum",
    "MDCG_TOOL_FACE": "off",
    # 写路径白名单族（真问题 e）
    "MDCG_EXPORT_ROOT": "fail-open", "MDCG_INGEST_ROOT": "fail-open",
    # 跨仓默认分叉（真问题 a）
    "AEIS_DB": "conflict", "AEIS_WORKSPACE": "value",
    # 检索开关族
    "MDCG_SEMANTIC": "off", "MDCG_EN_ATOMS": "off", "MDCG_CN_GRAMS": "on",
    "MDCG_CHAIN_TYPES": "unset", "MDCG_S7_FRESHNESS": "on",
    "MDCG_UNIFY_QUERY": "off", "MDCG_SCORE_MODE": "enum",
    "MDCG_TEMPORAL_GAMMA": "unset",
    # 会话/写入限流族
    "MDCG_WRITELIMIT": "on", "MDCG_RECONCILE": "on", "MDCG_REACH": "off",
    "MDCG_REACH_DIFFUSE": "off", "MDCG_REACH_TTL": "value",
    "MDCG_POOLING": "off",
    # 自治/预算族
    "MDCG_PROPOSAL_EMOTION": "off", "MDCG_EXPLORE_BUDGET_MAX": "unset",
    "MDCG_EXPLORE_BUDGET_WINDOW": "value",
    # 叙事/状态族
    "MDCG_D_META": "on", "MDCG_STATUS_HEAD": "on", "MDCG_FRESHNESS": "on",
    "MDCG_SUSTAIN": "on", "MDCG_HEARTBEAT_LEDGER": "on",
    # 预测面
    "PREDICTION_META_DIM": "value", "PREDICTION_META_PROXY": "enum",
    # 图像后端
    "IMGSKILL_BACKEND": "enum", "IMGSKILL_PILLOW": "on",
}

#: 非 md_cg 主包的读取点（身体仓/TS 面）不参与 AST 扫描，只作备注。
ANCHOR_RE = __import__("re").compile(r"^(?P<file>[^:]+?)\s*::\s*「(?P<sym>[^」]+?)」\s*$")


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _parse_const_anchor(raw: str):
    m = ANCHOR_RE.match((raw or "").strip())
    if not m:
        return None
    f = m.group("file").strip()
    s = m.group("sym").strip()
    if s.endswith("="):
        s = s[:-1].strip()
    if not s.isidentifier():
        return None
    return f, s


def _const_fold(el):
    """常量折叠：常量 / ±常量 / 常量四则与移位 / 容器递归。

    `1 << 20`、`50 * 1024`、`10 ** 9` 这类**写成了表达式**的字面量也能取值；
    含名字或函数调用的（`2.0 * DEFAULT_BEAT_INTERVAL`、`OrderedDict(...)`、
    `refine.GATE_MIN_PASS_RATE`）**取不出即不收录**，不猜。
    """
    if isinstance(el, ast.Constant):
        return el.value
    if isinstance(el, ast.UnaryOp) and isinstance(el.op, (ast.USub, ast.UAdd)):
        v = _const_fold(el.operand)
        return -v if isinstance(el.op, ast.USub) else v
    if isinstance(el, ast.BinOp):
        left, right = _const_fold(el.left), _const_fold(el.right)
        op = el.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Pow):
            return left ** right
        if isinstance(op, ast.FloorDiv):
            return left // right
        if isinstance(op, ast.LShift):
            return left << right
        if isinstance(op, ast.RShift):
            return left >> right
        raise ValueError("unsupported BinOp")
    if isinstance(el, ast.Tuple):
        return tuple(_const_fold(e) for e in el.elts)
    if isinstance(el, ast.List):
        return [_const_fold(e) for e in el.elts]
    if isinstance(el, ast.Dict):
        return {_const_fold(k): _const_fold(v)
                for k, v in zip(el.keys, el.values)}
    raise ValueError("non-constant")


def _module_literal(path: str, symbol: str):
    """返回 (状态, 值)。状态 ∈ OK / NOFILE / SYNTAX / NOTFOUND / NONLITERAL。"""
    fp = os.path.join(REPO, path)
    if not os.path.isfile(fp):
        return "NOFILE", None
    try:
        tree = ast.parse(open(fp, encoding="utf-8").read(), filename=fp)
    except SyntaxError:
        return "SYNTAX", None
    for node in tree.body:
        val = None
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == symbol for t in node.targets):
                val = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == symbol:
                val = node.value
        if val is not None:
            try:
                return "OK", _const_fold(val)
            except Exception:
                return "NONLITERAL", None
    return "NOTFOUND", None


def _type_name(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, tuple):
        return "tuple"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "dict"
    return type(v).__name__


_NUM_DOMAINS = ("上限/条数", "超时/时间窗", "阈值/权重")


def _tunable(domain: str, v) -> bool:
    """真「可调参数」（数值型阈值/上限/超时/预算）——枚举名与模板串不算。"""
    if not any(d in (domain or "") for d in _NUM_DOMAINS):
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return True
    if isinstance(v, (tuple, list)) and all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
        return True
    if isinstance(v, dict) and v and all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in v.values()):
        return True
    return False


_STATUS_READ_HINTS = ("实测", "读数", "裁定", "标定", "issue #", "证据", "样本")


def _status_and_evidence(calibration: str):
    """未标定一律标 uncalibrated（不许把「看起来合理」写成「已验证」）。

    有可指认读数/裁定注记（`_STATUS_READ_HINTS`）者标 `calibrating`（有依据、
    未走完回填流程）；`calibrated` 在第一批**恒为 0 条**——标定流程本身是设计
    产物，尚无条目走完「可复跑基准 → 读数 → 回填 evidence」。
    """
    cal = (calibration or "").strip()
    if cal and any(h in cal for h in _STATUS_READ_HINTS) and not cal.startswith("无（"):
        return "calibrating", cal
    return "uncalibrated", (cal or "保守缺省（未标定）")


# ---------------------------------------------------------------------------
# const 面
# ---------------------------------------------------------------------------

def build_const_entries(params):
    entries, dropped = [], []
    for p in params:
        if p.get("kind") != "const_literal" or p.get("repo") != "dsh-memory-main":
            continue
        pa = _parse_const_anchor(p.get("anchor"))
        if not pa:
            dropped.append((p.get("name"), p.get("anchor"), "ANCHOR_UNPARSEABLE"))
            continue
        f, s = pa
        st, v = _module_literal(f, s)
        if st != "OK":
            dropped.append((p.get("name"), f"「{s}」", st))
            continue
        status, evidence = _status_and_evidence(p.get("calibration"))
        entries.append({
            "key": f"dsh-memory-main::{f}::{s}",
            "name": p.get("name") or s,
            "symbol": s,
            "face": p.get("face"),
            "layer": "tune" if p.get("face") == "TUNE" else "calib",
            "kind": "const",
            "tunable": _tunable(p.get("domain"), v),
            "value": v,
            "value_type": _type_name(v),
            "domain": p.get("domain") or "",
            "env_name": None,
            "anchor": {"how": "const_assign", "file": f, "symbol": s},
            "status": status,
            "evidence": evidence,
            "since": "unknown",
            "notes": (p.get("notes") or "").strip(),
        })
    entries.sort(key=lambda e: (e["anchor"]["file"], e["symbol"]))
    return entries, dropped


# ---------------------------------------------------------------------------
# env 面
# ---------------------------------------------------------------------------

def _iter_md_cg_py():
    for dirpath, dirs, files in os.walk(os.path.join(REPO, SCAN_DIR)):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in files:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _module_env_name_consts(tree):
    """模块级 `NAME = "MDCG_..."` 常量 → {NAME: "MDCG_..."}（间接读取入口）。"""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name) and node.value.value.startswith(
                        ("MDCG_", "AEIS_", "IMGSKILL_", "PREDICTION_")):
                    out[t.id] = node.value.value
    return out


def _scan_env_sites(env_names):
    """返回 {env_name: [(file, how, default_repr)]}。

    how ∈ get_literal / get_bare / get_or_literal / helper_arg:<callee> / const_holder

    读取形态覆盖（本仓实有的四类）：
      · `os.environ.get("X", d)` / `os.environ.get(NAME, d)`   → get_literal
      · `(environ or os.environ).get(NAME)` / `env.get(NAME)`   → get_bare
      · `os.environ.get("X") or "lit"`                          → get_or_literal
      · `_cap(x, "X", SYMBOL)` / `check_path_root(p, "X", w)`   → helper_arg:*
    只登记**生产面**（排除 test_/bench_/probe_ 前缀文件）参与缺省裁定。
    """
    sites = {n: [] for n in env_names}
    for fp in _iter_md_cg_py():
        rel = os.path.relpath(fp, REPO).replace("\\", "/")
        base = os.path.basename(rel)
        prod = not (base.startswith("test_") or base.startswith("bench_")
                    or base.startswith("probe"))
        if not prod:
            continue
        try:
            tree = ast.parse(open(fp, encoding="utf-8").read(), filename=fp)
        except SyntaxError:
            continue
        holders = _module_env_name_consts(tree)
        # 父节点索引（判 `get(...) or "lit"` 形态）
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        def _env_of(arg):
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                    and arg.value in sites:
                return arg.value
            if isinstance(arg, ast.Name) and arg.id in holders \
                    and holders[arg.id] in sites:
                return holders[arg.id]
            return None

        for node in ast.walk(tree):
            # ① `.get(...)`（对象是 os.environ 或任意 environ 别名/表达式）
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "get" and node.args:
                nm = _env_of(node.args[0])
                if nm:
                    if len(node.args) > 1:
                        # 2 实参 get 的缺省**原样登记**（含 "" —— `get("X","")`
                        # 是显式空缺省；与 `get("X") or ""` 的归一化写法不同）
                        try:
                            raw = repr(ast.literal_eval(node.args[1]))
                        except Exception:
                            raw = ast.unparse(node.args[1])
                        sites[nm].append((rel, "get_literal", raw))
                    else:
                        # `get("X") or "lit"` ⇒ 缺省 = lit（空串是**归一化**惯用
                        # 写法而非缺省，故 "" 一律按「无字面量缺省」处理）
                        p = parents.get(node)
                        lit = None
                        if isinstance(p, ast.BoolOp) and isinstance(p.op, ast.Or):
                            for v in p.values:
                                if v is node:
                                    continue
                                try:
                                    lit = ast.literal_eval(v)
                                except Exception:
                                    lit = None
                        if lit in (None, ""):
                            sites[nm].append((rel, "get_bare", None))
                        else:
                            sites[nm].append((rel, "get_or_literal", repr(lit)))
                    continue
            # ② 助手式：env 名当实参（`_cap(x, "X", DEFAULT)` /
            #    `check_path_root(p, "X", what)` —— 后者**无缺省**）
            if isinstance(node, ast.Call):
                for i, arg in enumerate(node.args):
                    nm = _env_of(arg)
                    if not nm:
                        continue
                    callee = getattr(node.func, "id", None) \
                        or getattr(node.func, "attr", None) or "?"
                    dflt = None
                    if callee in HELPER_DEFAULT_CALLEES and len(node.args) > i + 1:
                        dflt = ast.unparse(node.args[i + 1])
                    sites[nm].append((rel, f"helper_arg:{callee}", dflt))
    return sites


def _resolve_default(sites_for_env, env_name):
    """折成 (value, default_symbol, status, how, files)。

    status ∈ ok_literal / ok_symbol / ok_flag / conflict / no_site
    生产面缺省分叉 ⇒ conflict（照实记，不许静默取其一）。
    """
    lits = [s[2] for s in sites_for_env
            if s[1] in ("get_literal", "get_or_literal") and s[2] is not None]
    helpers = [s[2] for s in sites_for_env
               if s[1].startswith("helper_arg") and s[2] is not None]
    bare = [s for s in sites_for_env if s[1] == "get_bare"]
    helper_nodflt = [s for s in sites_for_env
                     if s[1].startswith("helper_arg") and s[2] is None]
    files = sorted({s[0] for s in sites_for_env})
    if env_name in DEFAULT_SYMBOL_OVERRIDE:
        f, sym = DEFAULT_SYMBOL_OVERRIDE[env_name]
        return None, sym, "ok_symbol", "env_helper_default", sorted({f} | set(files))
    if lits:
        uniq = sorted(set(lits))
        if len(uniq) > 1:
            return uniq, None, "conflict", "env_literal", files
        raw = uniq[0]
        try:
            v = ast.literal_eval(raw)
        except Exception:
            v = raw
        return v, None, "ok_literal", "env_literal", files
    if helpers:
        uniq = sorted(set(helpers))
        if len(uniq) > 1:
            return uniq, None, "conflict", "env_helper_default", files
        # 助手实参是**符号名**（如 MAX_NODES）——值由 const 面登记，此处只存符号
        return None, uniq[0], "ok_symbol", "env_helper_default", files
    if bare or helper_nodflt:
        how = "env_flag" if bare else "env_helper_arg"
        return None, None, "ok_flag", how, files
    return None, None, "no_site", "none", files


def _env_face(env_name, params_index):
    for p in params_index.get(env_name, []):
        if p.get("repo") == "dsh-memory-main":
            return p.get("face", "TUNE")
    return "TUNE"


def build_env_category(params):
    """环境面**分类登记**（只登记「这是环境面 + 值域类型」，不登记缺省值）。

    为什么单列：环境面（`MDCG_ROOT`/凭据/身份/密级/解释器/写路径白名单…）是
    部署与隔离必需项，**不进用户配置文件**、也不进 registry 调参序列；把它们
    登记成分类，是为了「一张表看全哪些名字属于环境面」而不对缺省值下判断。
    """
    rows, seen = [], set()
    for p in params:
        if p.get("face") != "ENV":
            continue
        key = (p["name"], p.get("repo"))
        if key in seen:
            continue
        seen.add(key)
        rows.append((p["name"], p.get("kind") or "env", p.get("repo") or "",
                     p.get("domain") or "", (p.get("notes") or "")[:80]))
    rows.sort(key=lambda r: (r[2], r[0]))
    return rows


def build_env_entries(params):
    index = {}
    for p in params:
        if p.get("kind") == "env":
            index.setdefault(p["name"], []).append(p)
    sites = _scan_env_sites(CURATED_ENV_NAMES)
    entries, skipped = [], []
    for name in CURATED_ENV_NAMES:
        ss = sites.get(name) or []
        if not ss:
            skipped.append((name, "NO_PROD_SITE"))
            continue
        value, sym, st, how, files = _resolve_default(ss, name)
        face = _env_face(name, index)
        sem = SEMANTICS.get(name, "unset")
        inv_text = ""
        for p in index.get(name, []):
            if p.get("repo") == "dsh-memory-main" and p.get("default"):
                inv_text = str(p["default"]).strip()
                break
        if st == "conflict":
            note = f"★ 生产面缺省分叉：{value}"
        elif st == "no_site":
            note = "★ 未在 md_cg 生产面检出读取点"
        else:
            note = ""
        # value 为 None（无字面量缺省 / 有效缺省由常量给出）时，把**盘点文字**
        # 附在 evidence 里——它是采信输入、非 AST 复核值，故不计入 value 字段。
        ev = note or "由生成器自 AST 复核（第一批未见标定读数）"
        if name in CROSS_SIDE_NOTES:
            ev = CROSS_SIDE_NOTES[name] + ("；" + ev if ev else "")
        if value is None and inv_text and st != "conflict":
            ev += f"；有效缺省（盘点文字，未 AST 复核）：{inv_text[:120]}"
        entries.append({
            "key": f"dsh-memory-main::env::{name}",
            "name": name,
            "symbol": sym,
            "face": face,
            "layer": "env" if face == "ENV" else (
                "tune" if face == "TUNE" else "calib"),
            "kind": "env",
            "tunable": face in ("TUNE", "CALIB"),
            "value": value,
            "value_type": (_type_name(value) if value is not None
                           and not isinstance(value, list) else "str"),
            "domain": sem,
            "env_name": name,
            "semantic": sem,
            "anchor": {"how": how, "file": files[0], "symbol": sym,
                       "files": files},
            "status": "uncalibrated",
            "evidence": ev,
            "since": "unknown",
            "notes": note,
            "resolve_status": st,
        })
    return entries, skipped


# ---------------------------------------------------------------------------
# 主
# ---------------------------------------------------------------------------

def main(argv):
    dry = "--dry-run" in argv
    inv = DEFAULT_INVENTORY
    for i, a in enumerate(argv):
        if a == "--inventory" and i + 1 < len(argv):
            inv = argv[i + 1]
    if not os.path.isfile(inv):
        print(f"盘点件缺失：{inv}")
        return 2
    data = json.load(open(inv, encoding="utf-8"))
    params = data["params"]

    const_entries, const_dropped = build_const_entries(params)
    env_entries, env_skipped = build_env_entries(params)
    env_category = build_env_category(params)

    print(f"const 收录 {len(const_entries)} / 未收录 {len(const_dropped)}")
    print(f"env   收录 {len(env_entries)} / 未收录 {len(env_skipped)}")
    print(f"env   分类登记（环境面，只登记分类）{len(env_category)}")
    print("env 未收录明细：", env_skipped)
    print("const 未收录（前 25）：")
    for d in const_dropped[:25]:
        print("   ", d)

    if dry:
        return 0

    lines = [
        "# -*- coding: utf-8 -*-",
        '"""统一配置层 · registry **批量条目（生成件）**。',
        "",
        "由 `scripts/gen_config_registry.py` 生成；来源 = `.tmp/param_inventory.json`",
        "（可调参数全量盘点）+ 源码 AST 逐位复核。",
        "",
        "**本文件是生成件，不要手改。** 生成块一经产出即成为 registry 真源的一部分",
        "（冻结快照）：改默认值请改**源码**，守卫 `md_cg/config_registry_guard.py`",
        "会转红；补齐登记请重跑生成器或手工改登记（两条路都会过守卫）。",
        "",
        "字段（元组序，与 `cp.entry_from_row` 对齐）：",
        "    name, face, layer, kind, tunable, value_repr, value_type, domain,",
        "    env_name, semantic, anchor_how, anchor_file, anchor_symbol,",
        "    status, evidence, since, notes",
        "",
        '"""',
        "from __future__ import annotations",
        "",
        "ROW_FIELDS = (",
        "    \"name\", \"face\", \"layer\", \"kind\", \"tunable\", \"value_repr\",",
        "    \"value_type\", \"domain\", \"env_name\", \"semantic\", \"anchor_how\",",
        "    \"anchor_file\", \"anchor_symbol\", \"status\", \"evidence\", \"since\",",
        "    \"notes\",",
        ")",
        "",
        "# fmt: off",
        "CONST_ROWS = [",
    ]
    for e in const_entries:
        row = (e["name"], e["face"], e["layer"], e["kind"], e["tunable"],
               repr(e["value"]), e["value_type"], e["domain"], "",
               "", "const_assign", e["anchor"]["file"], e["symbol"], e["status"],
               e["evidence"][:300], e["since"], e["notes"][:200])
        lines.append("    " + repr(row) + ",")
    lines += ["]", "", "ENV_ROWS = ["]
    for e in env_entries:
        row = (e["name"], e["face"], e["layer"], e["kind"], e["tunable"],
               repr(e["value"]), e["value_type"], e["domain"], e["env_name"],
               e["semantic"], e["anchor"]["how"],
               ";".join(e["anchor"].get("files") or [e["anchor"]["file"]]),
               e["symbol"] or "", e["status"],
               e["evidence"][:300], e["since"], e["notes"][:200])
        lines.append("    " + repr(row) + ",")
    lines += [
        "]",
        "",
        "# 环境面**分类登记**（只登记「属于环境面」与值域类型；**不登记缺省值**）",
        "# 字段：(name, kind, repo, domain, notes)",
        "ENV_CATEGORY_ROWS = [",
    ]
    for r in env_category:
        lines.append("    " + repr(r) + ",")
    lines += [
        "]",
        "# fmt: on",
        "",
        "META = {",
        f"    \"generated_from\": \"{os.path.basename(inv)}\",",
        f"    \"const_count\": {len(const_entries)},",
        f"    \"const_dropped\": {len(const_dropped)},",
        f"    \"env_count\": {len(env_entries)},",
        f"    \"env_skipped\": {len(env_skipped)},",
        f"    \"env_category_count\": {len(env_category)},",
        "}",
        "",
    ]
    os.makedirs(os.path.dirname(OUT_MODULE), exist_ok=True)
    with open(OUT_MODULE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print("已写：", os.path.relpath(OUT_MODULE, REPO))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
