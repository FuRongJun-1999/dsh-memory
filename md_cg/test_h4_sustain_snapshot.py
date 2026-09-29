# -*- coding: utf-8 -*-
"""H-4 止血守卫 · **全 md_cg 域**：共享索引 `nodes` 字典上的迭代一律先取快照
（N138 / FI-M04 跨模块止血面）。

来源：设计者裁定的 H-4(a) 契约——**只做止血**：凡从 `cg.index` 取回 `nodes`
后在**取用前先取快照**（`list(nodes.items())` / `list(nodes.values())` /
`list(nodes)`），使并发写不再触发
`RuntimeError: dictionary changed size during iteration`，且**既有判据与结果
逐位不变**（只换取用方式，不改语义）。实例级读写锁 / 写路径消息化 / 线程模型
重构属设计级，本批刻意不做；`SustainLoop._lock` 覆盖范围**未扩**。

缺陷（N138，docs/eval/缺陷挖掘_自主迭代_v16.md:90；跨模块面见
docs/eval/优化第三批_…_v1.0.md §6.3/§7.3）：默认部署下 MDCG_SUSTAIN 开，
sustain 的后台巡检线程与请求线程**共享同一个 MdCG 实例与同一个
`index['nodes']` 字典**，而引擎全域无线程锁；前台 add/flush 在迭代进行中改
该字典即抛 RuntimeError，异常被 `SustainLoop._run` 的 `except Exception: pass`
吞掉 ⇒ **巡检静默丢一轮**（不是进程崩溃）。

**v2（本轮）修了什么**：v1 只把 `sustain.py` 四处迭代点包了快照——而
`diagnose()` **默认参数**的路径跨模块：`sustain.py:579 → evolution_candidates
→ weights.recalc → weights.coverage_index` 的裸 `items()`，且 `diagnose`
无条件调 `refindex.check_refs`（`for nid in nodes` 裸键迭代）——同一共享 dict，
止血面切窄了。v2 把快照面扩到**全 md_cg 域**的每一处共享 dict 迭代点
（含 `weights.py:408/409/425/483`、`refindex.py:672/815/878/966` 等 **80 处**：
并把验收判据切在**目标**上（见 G4）。

契约四项 ↔ 断言组：
  ① 迭代点全部取快照（结构判据 · **全域**）—— G1（AST 判据：全 md_cg（含测试）
     模块零裸迭代；含判据自证 G1b：对同一份源码反包裹后必须原样报出）
  ② 并发写不再可触发 RuntimeError（**目标级**判据）—— G4：
     G4a 确定性（注入绕开 sustain 自身快照面的写：只对 `edges` 触发 → 全默认
     参数 `diagnose(cg)` 不得抛；**回缺陷副本必须抛** ⇒ 判据有判别力）；
     G4b 真线程 · 默认 switchinterval；G4c 真线程 · 1e-6（放大窗口）。
  ③ 判定结果逐位不变（独立 oracle 对照，不靠推理）—— G3（现实现 vs 全域
     「回缺陷副本」的 30+ 条只读路径输出逐字节相同）+ G3b（**手算** oracle）
  ④ 记账面 `_lock` 覆盖范围**未扩**（本批不改并发契约）—— G0

运行：
    python -X utf8 -m md_cg.test_h4_sustain_snapshot                  # 正向
    python -X utf8 -m md_cg.test_h4_sustain_snapshot --mutate          # 定点变异自证
    python -X utf8 -m md_cg.test_h4_sustain_snapshot --mutate --list   # 只列变异表

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；
2 = **ANCHOR-MISS**（变异锚点在当前源码里找不到——实现改了却没同步本表，
本表就是判据，锚点漂移必须硬失败，不得静默跳过）。

**基线纪律**：本守卫**不以 git HEAD 为基线源**——所有「修复前」形态都由在当前
工作区源码上做**定点文本变异**（`_MUTATIONS`）或**全域反包裹**
（`_revert_source`）得到，基线随代码一起走。

**时序敏感项的处理**：G4b / G4c（真线程）与 G5（真实并发对撞）**不参与定点
变异计数**——它们只在正向跑里作防线在位证据（对照组观测记 NOTE）；定点变异
自证由确定性判据 G1/G2/G4a 承担。

**扫描面**：`md_cg/**.py` **全部模块**（含 `test_*.py`——早先把测试面切在判据外
＝给判据留豁免口；实测测试面另有 25 处裸站点，已一并取快照，见 `_domain_files`）。
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import types

# ── 隔离前置：必须在 import md_cg 子模块**之前**（tokens/theory 等在模块级把
# aux_root() 冻成常量）——否则会指到真实 ~/.mdcg 并在那里建密钥/令牌库。
# 与 md_cg/test_c3_transient_read_negative.py 同款前置（同一纪律）。
# 实验根一律在系统临时目录；不触任何在役数据根。 ──
_TMP = tempfile.mkdtemp(prefix="h4sus_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "ab" * 32          # 哑主密钥（绝不触真实密钥面）
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
os.environ["MDCG_SUSTAIN_DIR"] = os.path.join(_TMP, "sustain")
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES"):
    os.environ.pop(_k, None)

from . import sustain as _sustain                               # noqa: E402
from . import weights as _weights                               # noqa: E402
from . import refindex as _refindex                             # noqa: E402
from . import provenance as _provenance                         # noqa: E402
from . import trust as _trust                                   # noqa: E402
from . import self_state as _self_state                         # noqa: E402
from . import identity as _identity                             # noqa: E402
from . import insight as _insight                               # noqa: E402
from . import subgraph as _subgraph                             # noqa: E402
from . import reach as _reach                                   # noqa: E402
from . import export as _export                                 # noqa: E402
from . import forgetting as _forgetting                         # noqa: E402
from . import consistency as _consistency                       # noqa: E402
from . import chain as _chain                                   # noqa: E402
from . import protect as _protect                               # noqa: E402
from . import logref as _logref                                 # noqa: E402
from . import linkref as _linkref                               # noqa: E402
from . import refine as _refine                                 # noqa: E402
from . import branches as _branches                             # noqa: E402
from . import consolidate as _consolidate                       # noqa: E402
from . import reconcile as _reconcile                           # noqa: E402
from .mdcos import MdCGSecure                                   # noqa: E402
from .security import Principal                                 # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_RELPATH = os.path.join("md_cg", "sustain.py")
_MD_DIR = os.path.join(_REPO, "md_cg")

# 被测模块的**可替换引用**：变异模式会把其中一项换成 exec 出来的变异副本，
# 断言组一律经本表取模块（不直接闭包捕获原模块），否则变异对断言不可见。
MOD = {"sustain": _sustain, "weights": _weights, "refindex": _refindex,
       "provenance": _provenance, "trust": _trust, "self_state": _self_state,
       "identity": _identity, "insight": _insight, "subgraph": _subgraph,
       "reach": _reach, "export": _export, "forgetting": _forgetting,
       "consistency": _consistency, "chain": _chain, "protect": _protect,
       "logref": _logref, "linkref": _linkref, "refine": _refine,
       "branches": _branches, "consolidate": _consolidate,
       "reconcile": _reconcile}

_PASS: list = []
_FAIL: list = []
_SKIP: list = []
_NOTES: list = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))
    return bool(cond)


def note(msg):
    _NOTES.append(msg)
    print("  NOTE " + msg)


def skip(msg):
    _SKIP.append(msg)
    print("  SKIP " + msg)


# ═══════════════════════════════════════════════ 判据辅助（1）：全域扫描器
#
# 判据：**共享索引 nodes 字典**上的迭代必须先把迭代源包成副本
# （`list(` / `tuple(` / `sorted(` / `set(` / `dict(`）。AST 判定链见各函数注释；
# 用 AST 而非文本扫描的原因：站点跨模块、形态多样（`for` / 推导式 /
# `sum(genexp)` / 别名变量 / 参数透传），文本匹配会漏。

_COPY_CALLS = {"list", "tuple", "sorted", "set", "frozenset", "dict"}
_CONSUME_CALLS = {"sum", "any", "all", "max", "min", "len", "Counter"}


def _is_shared_expr(node) -> bool:
    """该表达式是否「从 (cg|self).index 取回 nodes」——字面量容器不算。"""
    if isinstance(node, (ast.Dict, ast.List, ast.Set, ast.Tuple, ast.Constant)):
        return False

    def _is_index_ref(n):
        if isinstance(n, ast.Attribute) and n.attr == "index":
            return True
        if isinstance(n, ast.Name) and n.id == "index":
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id == "getattr" and len(n.args) >= 2:
            a = n.args[1]
            return isinstance(a, ast.Constant) and a.value == "index"
        return False

    if not any(_is_index_ref(n) for n in ast.walk(node)):
        return False
    try:
        src = ast.unparse(node)
    except Exception:                                   # noqa: BLE001
        return False
    return bool(re.search(r"""\[\s*['"]nodes['"]\s*\]""", src)
                or re.search(r"""\.get\(\s*['"]nodes['"]""", src))


def _call_name(node):
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name):
            return f.id
        if isinstance(f, ast.Attribute):
            return f.attr
    return None


def _is_copying(node) -> bool:
    """该表达式的**结果**是否为独立副本（不再是共享 dict 本体）。"""
    if isinstance(node, ast.Subscript):                 # list(x)[:n]
        return _is_copying(node.value)
    if isinstance(node, ast.BoolOp):                    # a or {}
        return all(_is_copying(v) for v in node.values)
    nm = _call_name(node)
    if nm in _COPY_CALLS:
        return True
    if nm in _CONSUME_CALLS and len(node.args) == 1:
        return True
    return False


def _base_access(expr):
    """下探复制/切片外壳后取 (基表达式, 访问名) —— 判据必须同时认出
    「已快照」与「回缺陷」两态，否则变异自证无从谈起。"""
    e = expr
    while True:
        if isinstance(e, ast.Subscript):
            e = e.value
            continue
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) \
                and e.func.id in _COPY_CALLS and len(e.args) == 1:
            e = e.args[0]
            continue
        break
    if isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) \
            and e.func.attr in ("items", "values", "keys"):
        return e.func.value, e.func.attr
    if isinstance(e, ast.Attribute) and e.attr in ("items", "values", "keys"):
        return e.value, e.attr
    return e, None


def _mutates_self(name, body) -> bool:
    """循环体是否改写被迭代的那个 dict（改写自身迭代源＝单线程也非法）。"""
    for n in body:
        for x in ast.walk(n):
            if isinstance(x, ast.Assign):
                for t in x.targets:
                    if isinstance(t, ast.Subscript) and \
                            isinstance(t.value, ast.Name) and t.value.id == name:
                        return True
            if isinstance(x, ast.AugAssign) and \
                    isinstance(x.target, ast.Subscript) and \
                    isinstance(x.target.value, ast.Name) and \
                    x.target.value.id == name:
                return True
            if isinstance(x, ast.Delete):
                for t in x.targets:
                    if isinstance(t, ast.Subscript) and \
                            isinstance(t.value, ast.Name) and t.value.id == name:
                        return True
            if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) \
                    and x.func.attr in ("pop", "update", "setdefault", "clear",
                                        "popitem") \
                    and isinstance(x.func.value, ast.Name) \
                    and x.func.value.id == name:
                return True
    return False


def _iter_sites(tree):
    """返回 [(迭代源节点, 宿体)]：For / 推导式的迭代源。

    **必须传同一棵 AST**（调用方只 parse 一次）：另起 `ast.parse` 得到的节点与
    父表不是同一身，`enclosing_fn` 认不出所在函数，判据会退回模块级作用域而误报
    （本守卫曾因此把 `Ledger.record` 的 list 形参误判成共享 dict）。
    """
    out = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.For, ast.AsyncFor)):
            out.append((n.iter, n.body))
        elif isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp,
                            ast.DictComp)):
            for g in n.generators:
                out.append((g.iter, []))
    return out


#: 源码文本 → 扫描结果（见 scan_source 的缓存说明）
_SCAN_CACHE: dict = {}


def scan_source(src: str) -> list:
    """对单份源码报出**共享 dict 的迭代点**：[(行号, 文本, owner, safe, mutates)]。

    owner ∈ {inline, alias:<名>, param:<形参>}；safe=True 表示迭代源已取快照。

    **按源码文本缓存**：全域扫描要过 196 个文件、定点变异模式要跑十几轮，不缓存
    则同一份源码被反复 AST 分析（实测：g1 一轮 36s，是变异模式耗时主因）。命中时
    连同源码本体一起比对确认，不做「哈希相同就算同源」的盲信。
    """
    key = (len(src), hash(src))
    hit = _SCAN_CACHE.get(key)
    if hit is not None and hit[0] == src:
        return hit[1]
    result = _scan_source_uncached(src)
    if len(_SCAN_CACHE) > 1024:
        _SCAN_CACHE.clear()
    _SCAN_CACHE[key] = (src, result)
    return result


def _scan_source_uncached(src: str) -> list:
    tree = ast.parse(src)
    lines = src.splitlines()
    parent = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parent[c] = n

    def enclosing_fn(n):
        p = parent.get(n)
        while p is not None:
            if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return p
            p = parent.get(p)
        return None

    scopes = [tree] + [n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    def scope_aliases(scope, extra=()):
        names = set(extra)
        for st in scope.body:
            for n in ast.walk(st):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and n is not scope:
                    continue
                if isinstance(n, ast.Assign) and _is_shared_expr(n.value) \
                        and not _is_copying(n.value):
                    for t in n.targets:
                        if isinstance(t, ast.Name):
                            names.add(t.id)
                if isinstance(n, ast.AnnAssign) and n.value is not None \
                        and _is_shared_expr(n.value) and not _is_copying(n.value) \
                        and isinstance(n.target, ast.Name):
                    names.add(n.target.id)
        return names

    fn_by_name = {}
    for s in scopes[1:]:
        fn_by_name.setdefault(s.name, []).append(s)

    # 一层过程间：以共享实参调用某函数 ⇒ 该形参在该函数体内也是共享面
    param_shared = {}
    for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
        nm = _call_name(call)
        if nm not in fn_by_name:
            continue
        csc = enclosing_fn(call) or tree
        local = scope_aliases(csc)
        for callee in fn_by_name[nm]:
            args = [a.arg for a in callee.args.args]
            for i, a in enumerate(call.args):
                if i >= len(args):
                    break
                if _is_shared_expr(a) or (isinstance(a, ast.Name)
                                          and a.id in local):
                    param_shared.setdefault(id(callee), set()).add(args[i])
            for kw in call.keywords:
                if kw.arg and (_is_shared_expr(kw.value)
                               or (isinstance(kw.value, ast.Name)
                                   and kw.value.id in local)):
                    param_shared.setdefault(id(callee), set()).add(kw.arg)

    cache = {id(s): scope_aliases(s, param_shared.get(id(s), set()))
             for s in scopes}

    def alias_set_for(node):
        s = enclosing_fn(node)
        return cache[id(tree)] if s is None else cache[id(s)]

    out = []
    for expr, body in _iter_sites(tree):
        base, _access = _base_access(expr)
        owner = None
        if isinstance(base, ast.Name):
            if base.id in alias_set_for(expr):
                owner = "alias:%s" % base.id
            else:
                fn = enclosing_fn(expr)
                if fn is not None and base.id in param_shared.get(id(fn), ()):
                    owner = "param:%s" % base.id
        if owner is None and _is_shared_expr(base):
            owner = "inline"
        if owner is None:
            continue
        out.append({"line": expr.lineno,
                    "text": lines[expr.lineno - 1].strip(),
                    "owner": owner,
                    "safe": _is_copying(expr),
                    "mutates": _mutates_self(base.id, body)
                    if isinstance(base, ast.Name) else False})
    return out


def _domain_files() -> list:
    """扫描面：**md_cg/**.py 全部模块**（含测试，不再切掉测试面）。

    早先版本把 `test_*.py` 排除在外（理由：夹具单线程自读自写），但那等于给
    判据留了个自证豁免口——「全 md_cg 域再无裸迭代」这句话要么全真、要么不该
    这么说。实测测试面另有 25 处裸站点（12 个测试文件，且**无**改写自身迭代源
    的形态），已一并取快照后纳入本扫描面。
    """
    out = []
    for dirpath, dirnames, filenames in os.walk(_MD_DIR):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for f in sorted(filenames):
            if f.endswith(".py"):
                out.append(os.path.join(dirpath, f))
    return out


def scan_domain(overrides: dict = None):
    """全 md_cg 域扫描：返回 (共享迭代点总数, 裸迭代点列表, 扫描文件数)。

    overrides：{相对仓根路径: 源码} —— 变异模式下用**内存里的变异源码**替换盘上
    文本（否则结构判据对变异不可见，判据就成了空转）。
    """
    overrides = overrides or {}
    total, bad, files = 0, [], 0
    for path in _domain_files():
        rel = os.path.relpath(path, _REPO).replace(os.sep, "/")
        if rel in overrides:
            src = overrides[rel]
        else:
            with open(path, encoding="utf-8") as f:
                src = f.read()
        try:
            sites = scan_source(src)
        except SyntaxError as e:                        # 变异源写坏 → 硬失败
            bad.append({"path": rel, "line": 0,
                        "text": "扫描器无法解析：%s" % e, "owner": "-",
                        "safe": False, "mutates": False})
            files += 1
            continue
        total += len(sites)
        files += 1
        for s in sites:
            if not s["safe"] or s["mutates"]:
                s = dict(s)
                s["path"] = rel
                bad.append(s)
    return total, bad, files


# ═══════════════════════════════════════════════ 判据辅助（2）：全域「回缺陷副本」
#
# `_revert_source` 把快照 `list(X)` 削成 `(X)`：括号留着（多行表达式的续行不能丢），
# 复制没了（括号不复制）⇒ 语义＝裸迭代。用途有二：
#   * G1b 判据自证：反包裹后扫描器必须**原样报出**这些站点（判据有判别力）；
#   * G3/G4a 的对照组：全域「回缺陷副本」（这批未取快照时的样子）。

def _revert_source(src: str):
    """返回 (反包裹后的源码, 处数)。"""
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln))

    def off(lineno, col):
        return starts[lineno - 1] + col

    bad_lines = set()
    for s in scan_source(src):
        bad_lines.add(s["line"])
    spans = []
    for expr, _body in _iter_sites(tree):
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) \
                and expr.func.id == "list" and len(expr.args) == 1 \
                and expr.lineno in bad_lines:
            spans.append(off(expr.lineno, expr.col_offset))
    body = src
    for s in sorted(set(spans), reverse=True):
        assert body[s:s + 5] == "list(", "反包裹锚点错位：%d" % s
        body = body[:s] + "(" + body[s + 5:]
    return body, len(set(spans))


def _control_sources():
    """全域回缺陷源码 + 处数：{相对路径: 源码}。"""
    out, n = {}, 0
    for path in _domain_files():
        with open(path, encoding="utf-8") as f:
            src = f.read()
        rev, k = _revert_source(src)
        if k:
            n += k
            out[os.path.relpath(path, _REPO).replace(os.sep, "/")] = rev
    return out, n


def _build_control_modules(sources: dict):
    """把回缺陷源码 exec 成独立模块（**只用于判据对照**，不落盘、不改工作区）。

    模块名与真实模块同名但**不进 sys.modules**；对照期间经 `_Swap` 换入包属性
    （`from . import X` 走包属性 ⇒ 换入即生效），退出即还原。
    """
    mods = {}
    for rel, src in sources.items():
        name = rel[:-3].replace("/", ".")
        path = os.path.join(_REPO, rel.replace("/", os.sep))
        mod = types.ModuleType(name)
        mod.__package__ = name.rsplit(".", 1)[0]
        mod.__file__ = path
        exec(compile(src, path, "exec"), mod.__dict__)      # noqa: S102
        mods[name] = mod
    return mods


class _Swap:
    """对照期把回缺陷模块换进 sys.modules 与所属包属性（退出必还原）。

    `from . import X` 走**包属性**，故两处都要换：只换 sys.modules 的话，
    已导入过的兄弟模块仍会拿到旧对象（判据就成了空转的对照组）。
    """

    def __init__(self, mods):
        self.mods = mods
        self.saved = {}

    @staticmethod
    def _pkg_of(name):
        import importlib
        parent = ".".join(name.split(".")[:-1])
        pkg = sys.modules.get(parent)
        if pkg is None:
            pkg = importlib.import_module(parent)
        return pkg

    def __enter__(self):
        for name, mod in self.mods.items():
            self.saved[name] = sys.modules.get(name)
            sys.modules[name] = mod
            setattr(self._pkg_of(name), name.split(".")[-1], mod)
        return self

    def __exit__(self, *exc):
        for name, old in self.saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
                setattr(self._pkg_of(name), name.split(".")[-1], old)
        return False


# ═══════════════════════════════════════════════ 判据辅助（3）：并发写注入

class _OneShotMutatingEntry(dict):
    """一条「取值即触发并发写」的索引条目（确定性并发注入）。

    首次 `.get(trigger)` 时向**所属索引字典**添加一个影子键（模拟前台 add/flush
    改共享索引），随后按普通 dict 语义取值。用真实 dict 的真实迭代语义：**裸迭代**
    在该条目之后继续 `__next__` 必抛 `RuntimeError('dictionary changed size
    during iteration')`；**快照迭代**（`list(nodes.items())`）在拷贝完成后才执行
    `.get`，故不受影响。

    `trigger=None` ⇒ 任何键都触发；`trigger="edges"` ⇒ 只在该键被读时触发
    （用于**绕开 sustain 自身快照面**的目标级注入：写发生在 weights 的迭代里）。
    """

    def __init__(self, data: dict, owner: dict, probe_key: str, trigger=None):
        super().__init__(data)
        self._owner = owner
        self._probe_key = probe_key
        self._trigger = trigger
        self._fired = False

    def get(self, key, default=None):
        if not self._fired and (self._trigger is None or key == self._trigger):
            self._fired = True
            self._owner[self._probe_key] = dict(self)
        return super().get(key, default)


class _CgGetFires:
    """宿主代理：首次 `cg.get(nid)` 触发并发写（键迭代站点无 `.get` 中的读可取）。"""

    def __init__(self, cg, owner: dict, probe_key: str):
        self._cg = cg
        self._owner = owner
        self._probe_key = probe_key
        self._fired = False

    def __getattr__(self, name):
        return getattr(self._cg, name)

    def get(self, nid, *a, **kw):
        if not self._fired:
            self._fired = True
            self._owner[self._probe_key] = {"path": "", "layer": "knowledge",
                                            "tags": ["code"], "content_hash": "x"}
        return self._cg.get(nid, *a, **kw)


class _FakeCg:
    """`_locked_nodes` 的最小可驱动宿主（只用到 index 与 crypto_status）。"""

    def __init__(self, root, nodes):
        self.root = root
        self.index = {"nodes": nodes}

    def crypto_status(self):
        return {"unlocked": False}


def _with_injection(cg, trigger=None, probe="h4sus_shadow"):
    """在 cg.index['nodes'] 里注入「并发写」条目；返回还原函数。"""
    owner = (getattr(cg, "index", {}) or {}).get("nodes")
    saved = dict(owner)
    victim = sorted(owner)[-1]
    owner[victim] = _OneShotMutatingEntry(dict(owner[victim]), owner, probe,
                                          trigger=trigger)

    def restore():
        owner.clear()
        owner.update(saved)
    return restore


# ═══════════════════════════════════════════════ fixture

def _princ(role="designer"):
    from . import tokens
    spec = tokens.role_spec(role)
    return Principal(tenant="default", actor="h4sustain-" + role,
                     clearance="secret", can_write=bool(spec["can_write"]),
                     can_admin=True, role=role, session="sess_h4sustain")


def _new_cg(tag: str, n: int = 0):
    root = tempfile.mkdtemp(prefix="h4sus_cg_%s_" % tag, dir=_TMP)
    cg = MdCGSecure(root, principal=_princ())
    for i in range(n):
        cg.add("h4sus_%s_%02d" % (tag, i), "正文 %s %d h4susuniq" % (tag, i),
               layer="knowledge")
    if n:
        cg.flush()
    return cg


def _index_nodes(cg):
    return (getattr(cg, "index", {}) or {}).get("nodes") or {}


def _strip_time(obj):
    """去掉时间戳键（唯一非确定量）后的规范化形态（用于逐位对照）。"""
    _time_keys = ("t", "last_t", "updated_at", "created_at", "first_t",
                  "started_ts", "heartbeat_ts", "finished_ts", "duration_s",
                  "elapsed_s", "elapsed_ms", "checked_at", "time_range",
                  "duration_ms", "took_ms", "access_count", "generated_at",
                  "mtime", "size", "ts", "now", "batch")
    if isinstance(obj, dict):
        return {k: _strip_time(v) for k, v in obj.items()
                if k not in _time_keys}
    if isinstance(obj, (list, tuple)):
        return [_strip_time(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(_strip_time(v) for v in obj)
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return "<TS>" if obj > 1e9 else round(obj, 6)
    if isinstance(obj, int):
        return "<TS>" if obj > 10 ** 9 else obj
    if isinstance(obj, str):
        s = obj.replace(_TMP, "<TMP>")
        s = re.sub(r"\d{8}-\d{6}[-\w]*", "<STAMP>", s)
        # 消息里内嵌的 set repr（元素序随字符串哈希随机）→ 排序后比
        return re.sub(r"\{('(?:[^']*)'(?:, )?)+\}",
                      lambda m: "{" + ", ".join(
                          sorted(m.group(0)[1:-1].split(", "))) + "}", s)
    return obj


def _j(obj) -> str:
    return json.dumps(_strip_time(obj), ensure_ascii=False, sort_keys=True,
                      default=str)


def _build_fixture(tag: str, n: int = 3):
    """哑实验库（系统临时目录）：n 个 knowledge 节点，删掉其中 1 个的文件造孤儿。"""
    cg = _new_cg(tag, n)
    ids = sorted(_index_nodes(cg))
    orphan = ids[-1]
    p = os.path.join(cg.root, _index_nodes(cg)[orphan]["path"])
    os.remove(p)                       # 索引在、文件没了 → index_orphan
    return cg, ids, orphan


# ═══════════════════════════════════════════════ 断言组

def g0():
    """记账面未扩：`with self._lock:` 仍恰 4 处（本批不改并发契约）。"""
    with open(os.path.join(_REPO, _RELPATH), encoding="utf-8") as f:
        src = f.read()
    n = src.count("with self._lock:")
    ok(n == 4, "G0 记账面未扩：`with self._lock:` 仍恰 4 处（tidys/evolves/"
               "scrubs/heals）", f"实测 {n} 处")


def _override_for(relpath_hint: str = None):
    """变异模式下把内存里的变异源码交给判据（否则判据看不见变异＝空转）。

    返回 {相对路径: 源码}；无变异上下文时为 {}（判据读盘上源码）。
    """
    rel = relpath_hint or _MUT_CTX.get("rel")
    if not rel:
        return {}
    key = os.path.basename(rel)[:-3]
    src = getattr(MOD.get(key), "__h4_src__", None)
    return {rel.replace(os.sep, "/"): src} if src is not None else {}


def g1():
    """结构判据（全域）：md_cg 全部模块（含测试）零裸迭代点。"""
    overrides = _override_for()
    total, bad, files = scan_domain(overrides)
    ok(total >= 80, "G1a 扫描器覆盖面（共享 nodes 迭代点总数 ≥ 80，"
                    "防判据空转——扫描器若瞎了总数会掉）",
       f"实测 total={total} files={files}")
    ok(not bad, "G1a 全 md_cg 域（含测试模块）零裸迭代点：凡从 cg.index 取回的 "
                "nodes 均先取快照",
       f"裸迭代点 {len(bad)} 处：{[(b['path'], b['line']) for b in bad[:5]]}")
    for b in bad[:5]:
        print("        " + "%s:%s %s" % (b["path"], b["line"], b["text"][:90]))

    # G1b 判据自证（判别力）：把当前源码**反包裹**后，扫描器必须报出同批站点
    src_all = {}
    for path in _domain_files():
        with open(path, encoding="utf-8") as f:
            src_all[os.path.relpath(path, _REPO).replace(os.sep, "/")] = f.read()
    rev, n_rev = {}, 0
    for rel, src in src_all.items():
        r, k = _revert_source(src)
        if k:
            rev[rel] = r
            n_rev += k
    _t2, bad2, _f2 = scan_domain(rev)
    # 与**盘上现役源码**比（不是变异源码）：G1b 判的是「扫描器认不认得出反包裹
    # 形态」这件事本身；把它与变异源码比会让每一次定点变异都连带打红本项，
    # 红项数就掺进了不相干的因素（判据要各司其职）。
    _t3, bad_disk, _f3 = scan_domain()
    ok(n_rev >= 70 and len(bad2) == n_rev + len(bad_disk),
       "G1b 判据自证：反包裹后扫描器原样报出全部站点（判别力在位）",
       f"反包裹 {n_rev} 处 + 现役裸 {len(bad_disk)} 处 vs 报出 {len(bad2)} 处"
       f"——不等即判据漏了站点")
    ok(all(b["mutates"] is False for b in bad2),
       "G1b 反包裹副本里无「改写自身迭代源」的站点（快照不掩盖单线程非法）",
       f"{[b['text'] for b in bad2 if b['mutates']][:2]}")

    # G1c 站点在位（防「删掉迭代」冒充「已快照」）：契约点名的八个站点逐字
    tokens = [
        ("md_cg/sustain.py", "for e in list(nodes.values())"),
        ("md_cg/sustain.py", "for nid, e in list(nodes.items()):"),
        ("md_cg/sustain.py",
         "for k, v in list(nodes.items()) if v.get(\"layer\") == layer"),
        ("md_cg/sustain.py", "[nid for nid, e in list(nodes.items())"),
        ("md_cg/weights.py", "for nid, e in list(nodes.items()):"),
        ("md_cg/weights.py", "indeg = {nid: 0 for nid in list(nodes)}"),
        ("md_cg/weights.py", "ids = [nid for nid, e in list(nodes.items())"),
        ("md_cg/refindex.py", "todo = [nid for nid in list(nodes)"),
        ("md_cg/refindex.py", "for nid in list(nodes):"),
    ]
    for rel, token in tokens:
        src = overrides.get(rel)
        if src is None:
            with open(os.path.join(_REPO, rel.replace("/", os.sep)),
                      encoding="utf-8") as f:
                src = f.read()
        ok(token in src, "G1c 快照站点在位：%s ← %s" % (rel, token[:44]))


def g2_behavior():
    """行为判据（确定性注入）：取值/迭代期间改索引 → 迭代点不得抛 RuntimeError。"""
    # ① _ccg_backlog（sustain.py:422 面）
    d = {"n1": {"verification_basis": None, "has_neg_conditions": False}}
    d["n2"] = _OneShotMutatingEntry({"verification_basis": None,
                                     "has_neg_conditions": False}, d, "shadow1")
    try:
        cb = MOD["sustain"]._ccg_backlog(d, 5)
        ok(cb["n"] == 2 and cb["no_basis"] == 2 and cb["no_neg"] == 2,
           "G2a _ccg_backlog 在并发写索引下不崩溃且计数正确", str(cb))
    except RuntimeError as e:
        ok(False, "G2a _ccg_backlog 在并发写索引下不崩溃且计数正确", repr(e))

    # ② evolution_candidates 的 layer 过滤（sustain.py:449 面）
    cg = _new_cg("g2b", 2)
    restore = _with_injection(cg)
    try:
        ev = MOD["sustain"].evolution_candidates(cg, layer="knowledge", top=3)
        ok(ev["ok"] is True,
           "G2b evolution_candidates(layer=…) 在并发写索引下不崩溃",
           json.dumps(ev, ensure_ascii=False)[:200])
    except RuntimeError as e:
        ok(False, "G2b evolution_candidates(layer=…) 在并发写索引下不崩溃",
           repr(e))
    finally:
        restore()

    # ③ diagnose 的孤儿扫描（sustain.py:485 面）
    cg = _new_cg("g2c", 2)
    restore = _with_injection(cg)
    try:
        rep = MOD["sustain"].diagnose(cg, name="h4_g2c", check_evolution=False)
        ok("index_orphan" in {i["code"] for i in rep["issues"]}
           or rep["stats"]["nodes_indexed"] >= 2,
           "G2c diagnose 孤儿扫描在并发写索引下不崩溃", _j(rep)[:200])
    except RuntimeError as e:
        ok(False, "G2c diagnose 孤儿扫描在并发写索引下不崩溃", repr(e))
    finally:
        restore()

    # ④ _locked_nodes（sustain.py:397 面）
    owner = {"x": {"sensitivity": "internal"}}
    owner["y"] = _OneShotMutatingEntry({"sensitivity": "internal"}, owner,
                                       "shadow_locked")
    try:
        fake = _FakeCg(tempfile.mkdtemp(prefix="h4sus_fake_", dir=_TMP), owner)
        n = MOD["sustain"]._locked_nodes(fake)
        ok(n == 0, "G2d _locked_nodes 在并发写索引下不崩溃（内部级不计密文）",
           f"locked={n}")
    except RuntimeError as e:
        ok(False, "G2d _locked_nodes 在并发写索引下不崩溃（内部级不计密文）",
           repr(e))

    # ⑤ weights.coverage_index（weights.py:408/409 面——v2 扩面站点）
    cg = _new_cg("g2e", 2)
    restore = _with_injection(cg)
    try:
        indeg = MOD["weights"].coverage_index(cg)
        ok(isinstance(indeg, dict) and len(indeg) >= 2,
           "G2e weights.coverage_index 在并发写索引下不崩溃且入度表完整",
           str(indeg)[:120])
    except RuntimeError as e:
        ok(False, "G2e weights.coverage_index 在并发写索引下不崩溃且入度表完整",
           repr(e))
    finally:
        restore()

    # ⑥ weights.redundancy_map（weights.py:425 面）
    cg = _new_cg("g2f", 2)
    restore = _with_injection(cg)
    try:
        red = MOD["weights"].redundancy_map(cg)
        ok(isinstance(red, dict) and len(red) >= 2,
           "G2f weights.redundancy_map 在并发写索引下不崩溃且覆盖全节点",
           str(red)[:120])
    except RuntimeError as e:
        ok(False, "G2f weights.redundancy_map 在并发写索引下不崩溃且覆盖全节点",
           repr(e))
    finally:
        restore()

    # ⑦ weights.recalc（weights.py:483 面）
    cg = _new_cg("g2g", 2)
    restore = _with_injection(cg)
    try:
        rep = MOD["weights"].recalc(cg, apply=False)
        ok(rep.get("nodes_scanned", 0) >= 2,
           "G2g weights.recalc 在并发写索引下不崩溃且扫全节点",
           json.dumps(rep, ensure_ascii=False)[:160])
    except RuntimeError as e:
        ok(False, "G2g weights.recalc 在并发写索引下不崩溃且扫全节点", repr(e))
    finally:
        restore()

    # ⑧ refindex.check_refs 的键迭代（refindex.py:672 面）
    cg = _new_cg("g2h", 2)
    restore = _with_injection(cg)
    try:
        refs = MOD["refindex"].check_refs(
            cg, ledger=MOD["refindex"].Ledger(cg.root), only_tagged=True)
        ok(isinstance(refs, dict),
           "G2h refindex.check_refs 键迭代在并发写索引下不崩溃",
           str(refs)[:160])
    except RuntimeError as e:
        ok(False, "G2h refindex.check_refs 键迭代在并发写索引下不崩溃", repr(e))
    finally:
        restore()

    # ⑨ refindex.rebuild 的键迭代（refindex.py:966 面，无 .get 可取 → 宿主代理触发）
    cg = _new_cg("g2i", 1)
    owner = _index_nodes(cg)
    saved = dict(owner)
    try:
        proxy = _CgGetFires(cg, owner, "h4sus_g2i_shadow")
        try:
            out = MOD["refindex"].rebuild(proxy, max_files=1, max_items=1)
            ok(isinstance(out, dict),
               "G2i refindex.rebuild 键迭代在并发写索引下不崩溃",
               str(out)[:160])
        except RuntimeError as e:
            ok(False, "G2i refindex.rebuild 键迭代在并发写索引下不崩溃", repr(e))
        except Exception as e:                          # noqa: BLE001
            note("G2i rebuild 抛出非 RuntimeError 异常（与裸迭代无关，仅记录）："
                 "%s: %s" % (type(e).__name__, e))
    finally:
        owner.clear()
        owner.update(saved)


    # ⑩ refindex.prune_orphans 的裸 items()（refindex.py:815 面）
    cg = _new_cg("g2j", 2)
    restore = _with_injection(cg)
    try:
        out = MOD["refindex"].prune_orphans(
            cg, kind="code_ref", root=cg.root,
            items=[{"path": "h4sus_absent.py", "name": "f",
                    "lineno": 1, "end": 2, "hash": "x"}],
            dry_run=True)
        ok(isinstance(out, dict),
           "G2j refindex.prune_orphans 裸 items() 在并发写索引下不崩溃",
           str(out)[:160])
    except RuntimeError as e:
        ok(False, "G2j refindex.prune_orphans 裸 items() 在并发写索引下不崩溃",
           repr(e))
    finally:
        restore()

    # ⑪ refindex.prune_dangling 的裸 items()（refindex.py:878 面）
    cg = _new_cg("g2k", 2)
    restore = _with_injection(cg)
    try:
        # only_roots 非空 ⇒ 跳过前面的幽灵条目循环（:867 是**既有**快照站点，
        # 会先把一次性注入用掉），判据才能命中 :878 这一段
        out = MOD["refindex"].prune_dangling(cg, only_roots=[cg.root],
                                             dry_run=True)
        ok(isinstance(out, dict),
           "G2k refindex.prune_dangling 裸 items() 在并发写索引下不崩溃",
           str(out)[:160])
    except RuntimeError as e:
        ok(False, "G2k refindex.prune_dangling 裸 items() 在并发写索引下不崩溃",
           repr(e))
    finally:
        restore()


def g3_oracle():
    """逐位不变：现实现 vs 全域「回缺陷副本」，**同一 fixture** 上逐字节相同。"""
    ctrl, n_rev = _ctrl_table()
    cg, _ids, _orphan = _build_fixture("g3", 4)
    keys = sorted(_index_nodes(cg))
    rows = [
        ("weights.coverage_index", lambda m: m["weights"].coverage_index(cg)),
        ("weights.redundancy_map",
         lambda m: m["weights"].redundancy_map(cg, layer="knowledge")),
        ("weights.recalc", lambda m: m["weights"].recalc(cg, apply=False,
                                                         limit=3)),
        ("weights.node_importance",
         lambda m: m["weights"].node_importance(cg, keys[0])),
        ("refindex.check_refs",
         lambda m: m["refindex"].check_refs(
             cg, ledger=m["refindex"].Ledger(cg.root))),
        ("refindex.check_refs:tagged",
         lambda m: m["refindex"].check_refs(
             cg, ledger=m["refindex"].Ledger(cg.root), only_tagged=True)),
        ("refindex.prune_dangling",
         lambda m: m["refindex"].prune_dangling(cg, dry_run=True)),
        ("sustain.diagnose", lambda m: m["sustain"].diagnose(cg, name="h4_g3")),
        ("sustain.diagnose:noevolve",
         lambda m: m["sustain"].diagnose(cg, name="h4_g3",
                                         check_evolution=False)),
        ("sustain.evolution_candidates",
         lambda m: m["sustain"].evolution_candidates(cg, top=4)),
        ("sustain.evolution_candidates:layer",
         lambda m: m["sustain"].evolution_candidates(cg, layer="knowledge",
                                                     top=4)),
        ("sustain.heal:dry",
         lambda m: m["sustain"].heal(cg, name="h4_g3", dry_run=True)),
        ("sustain._ccg_backlog",
         lambda m: m["sustain"]._ccg_backlog(_index_nodes(cg), 5)),
        ("sustain._locked_nodes", lambda m: m["sustain"]._locked_nodes(cg)),
        ("provenance.index_edges", lambda m: m["provenance"].index_edges(cg)),
        ("trust.dependents_index", lambda m: m["trust"].dependents_index(cg)),
        ("trust.propagate", lambda m: m["trust"].propagate(cg)),
        ("self_state.snapshot", lambda m: m["self_state"].snapshot(cg)),
        ("self_state.audit", lambda m: m["self_state"].audit(cg)),
        ("self_state.relations", lambda m: m["self_state"].relations(cg)),
        ("self_state._relation_counts",
         lambda m: m["self_state"]._relation_counts(cg, None)),
        ("identity.positions", lambda m: m["identity"].positions(cg, limit=5)),
        ("identity.profile", lambda m: m["identity"].profile(cg, keys[0])),
        ("insight._events", lambda m: m["insight"]._events(cg)),
        ("insight.outlook", lambda m: m["insight"].outlook(cg)),
        ("subgraph.separation_pairs",
         lambda m: m["subgraph"].separation_pairs(cg, limit=5)),
        ("reach._hash_complete", lambda m: m["reach"]._hash_complete(cg)),
        ("export.export_stat", lambda m: m["export"].export_stat(cg)),
        ("forgetting.longterm_assess",
         lambda m: m["forgetting"].longterm_assess(cg)),
        ("consistency.check",
         lambda m: m["consistency"].check(cg, "正文 h4susuniq probe")),
        ("chain.adjacency", lambda m: m["chain"].adjacency(cg)),
        ("protect.stats", lambda m: m["protect"].stats(cg)),
        ("logref.session_src_state",
         lambda m: m["logref"].session_src_state(cg)),
        ("linkref.known_ids", lambda m: m["linkref"].known_ids(cg)),
        ("refine._pool", lambda m: m["refine"]._pool(cg, "h4sus")),
        ("branches.list_branches",
         lambda m: m["branches"].list_branches(cg)),
        ("consolidate.induce_memories",
         lambda m: m["consolidate"].induce_memories(cg, limit=5)),
        ("reconcile.reconcile_state",
         lambda m: m["reconcile"].reconcile_state(cg, apply=False)),
    ]
    live_rows = {}
    for tag, fn in rows:
        try:
            live_rows[tag] = _j(fn(MOD))
        except Exception as e:                          # noqa: BLE001
            live_rows[tag] = "__exc__" + type(e).__name__ + ":" + str(e)
    with _Swap(_CTRL_MODS):
        ctrl_rows = {}
        for tag, fn in rows:
            try:
                ctrl_rows[tag] = _j(fn(ctrl))
            except Exception as e:                      # noqa: BLE001
                ctrl_rows[tag] = "__exc__" + type(e).__name__ + ":" + str(e)
    diffs = [t for t, _ in rows if live_rows[t] != ctrl_rows[t]]
    ok(not diffs, "G3 逐位不变：%d 条只读路径在快照版与全域回缺陷副本上输出"
                  "逐字节相同" % len(rows),
       f"差异 {diffs[:3]}：" + "; ".join(
           "%s live=%s ctrl=%s" % (t, live_rows[t][:120], ctrl_rows[t][:120])
           for t in diffs[:1]))
    ok(n_rev >= 70, "G3 回缺陷副本覆盖面（≥70 处反包裹，防对照空转）",
       f"实测 {n_rev} 处")


# 对照组模块表：与 MOD 同名的回缺陷模块（进程内只建一次：盘上源码在本次运行里不变）
_CTRL: dict = {}
_CTRL_MODS: dict = {}
_CTRL_N = [0]
# 变异模式下的上下文：{"rel": "md_cg/xxx.py"} —— 结构判据据此读**内存里的变异源码**
_MUT_CTX: dict = {}


def _ctrl_table():
    """返回 (回缺陷模块表, 反包裹处数)；首次调用时构建。"""
    if not _CTRL_MODS:
        sources, n = _control_sources()
        mods = _build_control_modules(sources)
        _CTRL_MODS.update(mods)
        _CTRL_N[0] = n
        for key in MOD:
            full = "md_cg." + key
            _CTRL[key] = mods.get(full, MOD[key])   # 无站点的模块 → 用现役模块
    return _CTRL, _CTRL_N[0]


def g3b():
    """手算 oracle：fixture 的已知事实与 diagnose 的报数逐项相等（不靠自比）。"""
    cg, _ids, orphan = _build_fixture("g3b", 3)
    rep = MOD["sustain"].diagnose(cg, name="h4_g3b")
    codes = {i["code"] for i in rep["issues"]}
    ok(rep["stats"]["nodes_indexed"] == 3 and rep["stats"]["nodes_on_disk"] == 2,
       "G3b 手算：索引 3 / 磁盘 2（删掉 1 个文件）",
       json.dumps(rep["stats"], ensure_ascii=False))
    ok("index_drift" in codes and "index_orphan" in codes,
       "G3b 手算：漂移与孤儿两条告警均在位", str(sorted(codes)))
    org = next(i for i in rep["issues"] if i["code"] == "index_orphan")
    ok(org.get("sample") == [orphan], "G3b 手算：孤儿样本恰为被删的那个节点",
       f"{org.get('sample')} != [{orphan}]")
    ev = rep["evolve"]["ccg_backlog"]
    ok(ev["n"] == 3 and ev["no_basis"] == 3 and ev["no_neg"] == 3,
       "G3b 手算：3 个节点全无验证基底/负条件 → 候补 3",
       json.dumps(ev, ensure_ascii=False))
    ok(rep["evolve"]["importance_drift"]["scanned"] >= 3,
       "G3b 手算：重要性巡检覆盖全部节点", str(rep["evolve"]["importance_drift"]))
    # 手算跨模块面：weights 的入度表对 h4 环状引用逐项对账
    indeg = MOD["weights"].coverage_index(cg)
    ok(set(indeg) == set(_index_nodes(cg)) and all(v == 0 for v in indeg.values()),
       "G3b 手算：weights.coverage_index 覆盖全节点且无出边时入度全 0",
       str(indeg)[:120])


def g4a_target_deterministic():
    """**目标级判据（确定性）**：注入绕开 sustain 自身快照面的并发写后，
    以**全默认参数**调 `diagnose(cg)` 不得抛 RuntimeError；**回缺陷副本必须抛**
    （同一判据上的一红一绿 ⇒ 判据有判别力）。

    注入是**一次性**的（第一次读 `edges` 时改索引）⇒ 现实现与对照组必须各用
    一个**同形新夹具**：同一个夹具上跑两遍的话，第一遍已经把注入用掉了，
    对照组的绿是假绿（判据自己踩过的坑，注释在此留痕）。
    """
    def _run(mods_ctx, mod, tag):
        cg, _ids, _orphan = _build_fixture("g4a" + tag, 4)
        restore = _with_injection(cg, trigger="edges")
        try:
            with mods_ctx:
                rep = mod["sustain"].diagnose(cg)      # 全默认参数
                return ("green", rep.get("stats", {}).get("nodes_indexed"))
        except RuntimeError as e:
            import traceback
            tb = [ln.strip() for ln in traceback.format_exc().splitlines()
                  if "md_cg" in ln]
            return ("RED", "%s: %s | %s" % (type(e).__name__, e,
                                            tb[-1] if tb else "?"))
        finally:
            restore()

    _ctrl_table()                                      # 首次构建（幂等）
    live = _run(contextlib.nullcontext(), MOD, "l")
    ok(live[0] == "green",
       "G4a 目标级（确定性）：全默认参数 diagnose 在并发写下不抛 RuntimeError",
       str(live))
    ctrl = _run(_Swap(_CTRL_MODS), _CTRL, "c")
    ok(ctrl[0] == "RED",
       "G4a 判据有判别力：同一注入下**回缺陷副本**必须抛 RuntimeError",
       str(ctrl))
    if ctrl[0] == "RED":
        note("G4a 对照组崩溃栈顶：%s" % ctrl[1])


def g4bc_threads():
    """真线程形态（默认 switchinterval / 1e-6）：全默认参数 diagnose 与前台写
    对撞，零 RuntimeError。时序敏感，不参与定点变异计数（见文件头）。"""
    for tag, switch in (("G4b", None), ("G4c", 1e-6)):
        cg, _ids, _orphan = _build_fixture("h4%s" % tag.lower(), 60)
        errors = []
        stop = threading.Event()

        def _inspector():
            while not stop.is_set():
                try:
                    MOD["sustain"].diagnose(cg)        # 全默认参数
                except Exception as e:                 # noqa: BLE001 —— 本组抓它
                    errors.append("%s: %s" % (type(e).__name__, e))
                    return

        old_switch = sys.getswitchinterval()
        if switch is not None:
            sys.setswitchinterval(switch)
        th = threading.Thread(target=_inspector, daemon=True)
        th.start()
        i, deadline = 0, time.time() + 3.0
        try:
            while time.time() < deadline:
                cg.add("h4%s_w%04d" % (tag.lower(), i),
                       "并发写入正文 %d" % i, layer="knowledge")
                i += 1
                if i % 5 == 0:
                    cg.flush()
        finally:
            stop.set()
            th.join(timeout=15)
            sys.setswitchinterval(old_switch)
        ok(not errors,
           "%s 目标级（真线程%s）：写 %d 条 + 全默认 diagnose 对撞零 RuntimeError"
           % (tag, "，switchinterval=1e-6" if switch else "，默认 switchinterval",
              i),
           f"首个异常={errors[:1]}")


def g5_concurrent():
    """真实多线程对撞（sustain 巡检 vs 前台写，时序敏感加分项，不参与变异计数）。"""
    cg, _ids, _orphan = _build_fixture("g5", 2)
    errors = []
    stop = threading.Event()

    def _healer():
        while not stop.is_set():
            try:
                MOD["sustain"].diagnose(cg, name="h4_g5")
                MOD["sustain"].heal(cg, name="h4_g5", dry_run=True)
                MOD["sustain"].evolution_candidates(cg)
            except Exception as e:              # noqa: BLE001 —— 本组就是抓它
                errors.append("%s: %s" % (type(e).__name__, e))
                return

    th = threading.Thread(target=_healer, daemon=True)
    th.start()
    i, deadline = 0, time.time() + 2.0
    try:
        while time.time() < deadline:
            cg.add("h4sus_g5_%d" % i, "并发写入正文 %d h4susuniq" % i,
                   layer="knowledge")
            i += 1
            if i % 3 == 0:
                cg.flush()
    finally:
        stop.set()
        th.join(timeout=10)
    ok(not errors, f"G5 真实并发（写 {i} 条 + 巡检对撞）零异常",
       f"首个异常={errors[:1]}")


# ------------------------------------------------------------------ 定点变异

# 「修复前」形态 = 把 `list(X)` 削成 `(X)`（括号不复制 ⇒ 等价裸迭代；括号留着
# 是因为多行表达式的续行不能丢）。每条锚点都必须**唯一命中**目标站点：
# 同一文件里重复出现的锚点由更长的上下文锚定（否则变异打到别的站点上，
# 红项数就对不上，本表即判据）。
_MUTATIONS = (
    # (名称, 相对路径, 锚点原文, 变异后, 期望红项数)
    ("H-4a-1 回缺陷：_ccg_backlog 裸迭代（sustain.py:422）",
     "md_cg/sustain.py",
     "for nid, e in list(nodes.items()):", "for nid, e in (nodes.items()):", 3),
    ("H-4a-2 回缺陷：evolution_candidates 的 layer 过滤裸迭代（:449）",
     "md_cg/sustain.py",
     "for k, v in list(nodes.items()) if v.get(\"layer\") == layer",
     "for k, v in (nodes.items()) if v.get(\"layer\") == layer", 3),
    ("H-4a-3 回缺陷：diagnose 孤儿扫描裸迭代（:485）",
     "md_cg/sustain.py",
     "[nid for nid, e in list(nodes.items())",
     "[nid for nid, e in (nodes.items())", 3),
    ("H-4a-4 回缺陷：_locked_nodes 裸迭代 values()（:397）",
     "md_cg/sustain.py",
     "for e in list(nodes.values())", "for e in (nodes.values())", 3),
    ("H-4a-5 回缺陷：weights.coverage_index 键迭代（weights.py:408）",
     "md_cg/weights.py",
     "indeg = {nid: 0 for nid in list(nodes)}",
     "indeg = {nid: 0 for nid in (nodes)}", 2),
    ("H-4a-6 回缺陷：weights.coverage_index 裸 items()（weights.py:409）",
     "md_cg/weights.py",
     "for nid, e in list(nodes.items()):\n        for t in _targets(e):",
     "for nid, e in (nodes.items()):\n        for t in _targets(e):", 3),
    ("H-4a-7 回缺陷：weights.redundancy_map 裸 items()（weights.py:425）",
     "md_cg/weights.py",
     "seen, out = {}, {}\n    for nid, e in list(nodes.items()):",
     "seen, out = {}, {}\n    for nid, e in (nodes.items()):", 2),
    ("H-4a-8 回缺陷：weights.recalc 裸推导（weights.py:483）",
     "md_cg/weights.py",
     "ids = [nid for nid, e in list(nodes.items())",
     "ids = [nid for nid, e in (nodes.items())", 2),
    ("H-4a-9 回缺陷：refindex.check_refs 裸键迭代（refindex.py:672）",
     "md_cg/refindex.py",
     "todo = [nid for nid in list(nodes)", "todo = [nid for nid in (nodes)", 3),
    ("H-4a-10 回缺陷：refindex.rebuild 裸键迭代（refindex.py:966）",
     "md_cg/refindex.py",
     "for nid in list(nodes):", "for nid in (nodes):", 3),
    ("H-4a-11 回缺陷：refindex.prune_orphans 裸 items()（refindex.py:815）",
     "md_cg/refindex.py",
     "plan = []\n    for nid, e in list(nodes.items()):",
     "plan = []\n    for nid, e in (nodes.items()):", 2),
    ("H-4a-12 回缺陷：refindex.prune_dangling 裸 items()（refindex.py:878）",
     "md_cg/refindex.py",
     "regenerable_skipped = []\n    for nid, e in list(nodes.items()):",
     "regenerable_skipped = []\n    for nid, e in (nodes.items()):", 2),
)


def _exec_module(name: str, path: str, src: str):
    mod = types.ModuleType(name)
    mod.__package__ = name.rsplit(".", 1)[0]
    mod.__file__ = path
    mod.__h4_src__ = src          # 结构判据取此源码（变异对判据可见）
    exec(compile(src, path, "exec"), mod.__dict__)          # noqa: S102
    return mod


def _load_one(relpath: str, old: str, new: str):
    """单点变异：只把该文件的 old 退回裸迭代（其余站点维持快照）。"""
    path = os.path.join(_REPO, relpath.replace("/", os.sep))
    with open(path, encoding="utf-8") as f:
        src = f.read()
    if old not in src:
        return None, src
    mut_src = src.replace(old, new, 1)
    name = "md_cg._h4sus_mut1_%s" % os.path.basename(path)[:-3]
    return _exec_module(name, path, mut_src), src


def _run_groups(with_threads: bool = True) -> int:
    _PASS.clear()
    _FAIL.clear()
    _SKIP.clear()
    _NOTES.clear()
    for g in (g0, g1, g2_behavior, g3_oracle, g3b, g4a_target_deterministic):
        try:
            g()
        except Exception as exc:                            # noqa: BLE001
            import traceback
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            print(traceback.format_exc()[-800:])
    if with_threads:
        for g in (g4bc_threads, g5_concurrent):
            try:
                g()
            except Exception as exc:                        # noqa: BLE001
                import traceback
                ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
                print(traceback.format_exc()[-800:])
    else:
        skip("G4b/G4c/G5 真线程组：定点变异模式下不计分（时序敏感，见文件头）")
    return len(_FAIL)


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条把快照取用改回裸迭代，套件必须按预期条数转红\n")
    if list_only:
        for name, rel, _old, _new, exp in _MUTATIONS:
            print("  %-56s expect_red=%d  (%s)" % (name, exp, rel))
        return 0

    anchor_miss, bad = [], []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups(with_threads=True)
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    for name, rel, old, new, expect in _MUTATIONS:
        mut, _src = _load_one(rel, old, new)
        if mut is None:
            print("  ANCHOR-MISS %s —— 锚点在 %s 当前源码里找不到"
                  "（实现改了却没同步本表；基线不得静默漂移）" % (name, rel))
            anchor_miss.append(name)
            continue
        key = os.path.basename(rel)[:-3]
        live = MOD.get(key)
        MOD[key] = mut
        _MUT_CTX["rel"] = rel.replace(os.sep, "/")
        try:
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups(with_threads=False)
            detail = buf.getvalue()
        finally:
            _MUT_CTX.pop("rel", None)
            if live is not None:
                MOD[key] = live
        red_lines = [l for l in detail.splitlines() if l.strip().startswith("FAIL ")]
        verdict = "红" if reds else "**仍全绿 = 该判据空转**"
        mark = "OK  " if reds == expect else "MISMATCH"
        print("  %s %-56s 红项=%d 预期=%d  %s" % (mark, name, reds, expect,
                                                  verdict))
        for l in red_lines:
            print("        " + l.strip()[5:])
        if reds != expect:
            bad.append("%s（红=%d 预期=%d）" % (name, reds, expect))

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都被打红且恰好命中预期项数）" if not bad
             else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    if "--mutate" in sys.argv:
        try:
            return _mutate_mode("--list" in sys.argv)
        finally:
            _cleanup()
    try:
        n_fail = _run_groups(with_threads=True)
        print("\nH-4(a) 守卫（全 md_cg 域迭代点取快照）：%d 通过，%d 失败，%d 跳过"
              % (len(_PASS), n_fail, len(_SKIP)))
        return 0 if not n_fail else 1
    finally:
        _cleanup()


def _cleanup():
    import gc
    for _ in range(6):
        shutil.rmtree(_TMP, ignore_errors=True)
        if not os.path.exists(_TMP):
            return
        gc.collect()
        time.sleep(0.2)


if __name__ == "__main__":
    sys.exit(main())
