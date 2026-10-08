# -*- coding: utf-8 -*-
"""统一配置层 · **一致性守卫**（本文件即判据；第一批：只加机制、不动语义）。

判据（任一条红 ⇒ 退出码 1）
-------------------------
  G1 **schema/内部一致性**——每条 registry 条目给齐必填字段；face/layer/kind/
     status 取值合法；key 唯一；`tunable` 与 `value_type` 相容。
  G2 **锚点可解 + 缺省逐位相等**（本守卫的核心，防「登记与代码漂移」）：
     · `const`：锚点文件的模块级赋值**确有**该符号，且常量折叠后的值
       == registry 登记的 value；
     · `table`：既有真源表（`SLEEP_ENV_DEFAULTS`/`AUTO_DEFAULTS`/
       `AUTONOMY_ENV_DEFAULTS`）里的键值 == registry 登记的 value；
     · `env`：按锚点形态复核（字面量缺省 / 助手缺省符号 / 无缺省开关 /
       助手实参），分叉条目必须**仍**分叉（≥2 个不同缺省）——分叉被修掉要
       同步改登记，否则红。
  G3 **生成件新鲜度**——`docs/reference/配置参数表_v0.1.md` 与
     `md_cg/config_validate.py` 必须**逐字节等于**由真源重渲染的结果
     （生成件陈旧 ⇒ 红；禁手改生成件）。
  G4 **分区表覆盖完整**——三张既有真源表的每个键都必须在 registry 里登记
     （漏登 ⇒ 红）。

不适用条件
----------
· 不判「缺省值是否合理」（那是标定/裁定的活，见设计文档 §5）；
· 不改任何读取点；不给 env 面「有效缺省」下数值判断（只判代码里**写着的**
  缺省与登记是否一致）。

运行
----
    python -X utf8 -m md_cg.config_registry_guard               # 全绿裁决
    python -X utf8 -m md_cg.config_registry_guard --mutate      # 定点变异自证
    python -X utf8 -m md_cg.config_registry_guard --mutate --list
    python -X utf8 -m md_cg.config_registry_guard --verbose

退出码：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；2 = ANCHOR-MISS
（变异锚点在当前源码里找不到——实现改了却没同步本表）。

**基线纪律**（沿用 `md_cg/test_sleep_p1.py` 先例）：不以 git HEAD 为基线源——
「改动前形态」由在当前工作区源码文本上做**定点变异**复现，锚点漂移即退出码 2。
变异全程在**内存**里改源码文本（`_SRC` 覆盖），**不落盘**。
"""
from __future__ import annotations

import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PASS, _FAIL = [], []
_SRC = {}
_DOC = os.path.join(REPO, "docs", "reference", "配置参数表_v0.1.md")
_VALIDATOR = os.path.join(REPO, "md_cg", "config_validate.py")

TABLE_SPECS = (
    ("md_cg/sleep.py", "SLEEP_ENV_DEFAULTS", "SLEEP_ENV_KEYS"),
    ("md_cg/sustain.py", "AUTO_DEFAULTS", "AUTO_ENVS"),
    ("md_cg/autonomy_modes.py", "AUTONOMY_ENV_DEFAULTS", "AUTONOMY_ENV_KEYS"),
)


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _read(rel: str) -> str:
    if rel in _SRC:
        return _SRC[rel]
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


def _tree(rel: str):
    try:
        return ast.parse(_read(rel), filename=rel)
    except (SyntaxError, FileNotFoundError):
        return None


def _const_fold(el):
    if isinstance(el, ast.Constant):
        return el.value
    if isinstance(el, ast.UnaryOp) and isinstance(el.op, (ast.USub, ast.UAdd)):
        v = _const_fold(el.operand)
        return -v if isinstance(el.op, ast.USub) else v
    if isinstance(el, ast.BinOp):
        l, r = _const_fold(el.left), _const_fold(el.right)
        op = el.op
        table = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                 ast.Mult: lambda a, b: a * b, ast.FloorDiv: lambda a, b: a // b,
                 ast.Pow: lambda a, b: a ** b,
                 ast.LShift: lambda a, b: a << b, ast.RShift: lambda a, b: a >> b}
        for t, fn in table.items():
            if isinstance(op, t):
                return fn(l, r)
        raise ValueError("unsupported BinOp")
    if isinstance(el, ast.Tuple):
        return tuple(_const_fold(e) for e in el.elts)
    if isinstance(el, ast.List):
        return [_const_fold(e) for e in el.elts]
    if isinstance(el, ast.Dict):
        return {_const_fold(k): _const_fold(v)
                for k, v in zip(el.keys, el.values)}
    raise ValueError("non-constant")


def _module_value(rel: str, symbol: str):
    """模块级常量取值：返回 ("OK", value) / (其它, None)。"""
    tree = _tree(rel)
    if tree is None:
        return "NOFILE", None
    for node in tree.body:
        val = None
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == symbol for t in node.targets):
            val = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == symbol:
            val = node.value
        if val is not None:
            try:
                return "OK", _const_fold(val)
            except Exception:
                return "NONLITERAL", None
    return "NOTFOUND", None


def _table_value(rel: str, symbol: str, key: str):
    tree = _tree(rel)
    if tree is None:
        return "NOFILE", None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == symbol for t in node.targets):
            try:
                d = ast.literal_eval(node.value)
            except Exception:
                return "NONLITERAL", None
            return "OK", d.get(key, "<MISSING>")
    return "NOTFOUND", None


def _env_aliases(tree):
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
    return out


def _env_sites(rel: str, env_name: str):
    """锚点文件里该 env 的读取点 → {"literal": set, "bare": bool, "helper": bool}。

    `literal` = 非空字面量缺省（`get("X", d)` 的 d / `get("X") or "lit"` 的 lit）。
    """
    tree = _tree(rel)
    res = {"literal": set(), "bare": False, "helper": False}
    if tree is None:
        return res
    holders = _env_aliases(tree)
    parents = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parents[c] = n

    def name_of(arg):
        if isinstance(arg, ast.Constant) and arg.value == env_name:
            return True
        if isinstance(arg, ast.Name) and holders.get(arg.id) == env_name:
            return True
        return False

    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == "get" and n.args and name_of(n.args[0]):
            if len(n.args) > 1:
                try:
                    v = ast.literal_eval(n.args[1])
                except Exception:
                    v = ast.unparse(n.args[1])
                res["literal"].add(repr(v))
            else:
                p = parents.get(n)
                lit = None
                if isinstance(p, ast.BoolOp) and isinstance(p.op, ast.Or):
                    for v in p.values:
                        if v is n:
                            continue
                        try:
                            lit = ast.literal_eval(v)
                        except Exception:
                            lit = None
                if lit not in (None, ""):
                    res["literal"].add(repr(lit))
                else:
                    res["bare"] = True
            continue
        if isinstance(n, ast.Call):
            for a in n.args:
                if name_of(a):
                    res["helper"] = True
                    break
    return res


# ---------------------------------------------------------------------------
# 判据
# ---------------------------------------------------------------------------

def g1_schema(cr):
    required = [k for k, (req, _) in cr.SCHEMA.items() if req]
    seen = set()
    bad = 0
    for e in cr.entries():
        miss = [k for k in required if k not in e]
        if miss:
            bad += 1
            ok(False, f"G1 {e.get('key')} 缺必填字段 {miss}")
        if e["face"] not in cr.FACES or e["layer"] not in cr.LAYERS \
                or e["kind"] not in cr.KINDS or e["status"] not in cr.STATUSES:
            bad += 1
            ok(False, f"G1 {e['key']} 分类取值非法")
        if e["key"] in seen:
            bad += 1
            ok(False, f"G1 key 重复：{e['key']}")
        seen.add(e["key"])
        # tunable 的数值型判断：str 值须带显式语义（开关/枚举/数值语义）才算
        if e["tunable"] and e["value_type"] == "str" and e.get("semantic") not in (
                "value", "enum", "on", "off", "fail-open", "unset"):
            bad += 1
            ok(False, f"G1 {e['name']} tunable 但类型 str 且无语义标注")
        elif e["tunable"] and e["value_type"] not in (
                "int", "float", "bool", "tuple", "list", "dict", "str"):
            bad += 1
            ok(False, f"G1 {e['name']} tunable 但类型 {e['value_type']}")
    ok(bad == 0, f"G1 schema/内部一致性（{len(cr.entries())} 条）", f"{bad} 处不合规")
    return bad


def g2_anchors(cr):
    bad = 0
    for e in cr.entries():
        a = e["anchor"]
        how = a.get("how")
        if e["kind"] == "env" and not a.get("files"):
            a["files"] = [a["file"]] if a.get("file") else []
        if e["kind"] == "const":
            st, v = _module_value(a["file"], a["symbol"])
            if st != "OK" or v != e["value"]:
                bad += 1
                ok(False, f"G2 const {a['file']}::{a['symbol']} "
                          f"登记={e['value']!r} 代码={v!r}（{st}）")
        elif e["kind"] == "table":
            st, v = _table_value(a["file"], a["symbol"], a["key"])
            if st != "OK" or v != e["value"]:
                bad += 1
                ok(False, f"G2 table {a['file']}::{a['symbol']}[{a['key']}] "
                          f"登记={e['value']!r} 代码={v!r}（{st}）")
        else:  # env
            files = a.get("files") or [a["file"]]
            if how == "env_literal":
                obs = set()
                for f in files:
                    obs |= _env_sites(f, e["name"])["literal"]
                want = e["value"]
                if isinstance(want, list):
                    if sorted(obs) != sorted(f"{w}" for w in want):
                        bad += 1
                        ok(False, f"G2 env 分叉 {e['name']} 登记={want} 观测={sorted(obs)}")
                else:
                    if repr(want) not in obs:
                        bad += 1
                        ok(False, f"G2 env {e['name']} 登记={want!r} 未在 "
                                  f"{files} 观测到（观测={sorted(obs)}）")
            elif how == "env_helper_default":
                sym = a.get("symbol")
                if e.get("value") is None and sym:
                    hit = any(_module_value(f, sym)[0] == "OK" for f in files)
                    if not hit:
                        bad += 1
                        ok(False, f"G2 env {e['name']} 助手缺省符号 {sym} "
                                  f"在 {files} 无模块级赋值")
                else:
                    ok(True, f"G2 env {e['name']}（字面量缺省，非符号）")
            else:  # env_flag / env_helper_arg
                hit = False
                for f in files:
                    s = _env_sites(f, e["name"])
                    if how == "env_helper_arg":
                        hit = hit or s["helper"]
                    else:
                        hit = hit or s["bare"] or s["literal"]
                if not hit:
                    bad += 1
                    ok(False, f"G2 env {e['name']}（{how}）在 {files} 未检出读取点")
    ok(bad == 0, f"G2 锚点可解 + 缺省逐位相等（{len(cr.entries())} 条）", f"{bad} 条不符")
    return bad


def g3_generated(cr):
    from . import config_render as rnd
    bad = 0
    for path, text, label in (
            (_DOC, rnd.render_doc(cr), "文档参数表"),
            (_VALIDATOR, rnd.render_validator(cr), "校验器")):
        cur = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
        same = cur == text
        if not same:
            bad += 1
        ok(same, f"G3 生成件新鲜度：{label} {os.path.relpath(path, REPO)}")
    return bad


def g4_table_coverage(cr):
    bad = 0
    for rel, sym, _keysym in TABLE_SPECS:
        st, d = _table_value(rel, sym, "__absent__")
        tree = _tree(rel)
        if tree is None:
            bad += 1
            ok(False, f"G4 无法解析 {rel}")
            continue
        keys = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == sym for t in node.targets):
                try:
                    keys = list(ast.literal_eval(node.value).keys())
                except Exception:
                    keys = []
        reg = {e["anchor"].get("key") for e in cr.entries()
               if e["kind"] == "table" and e["anchor"]["file"] == rel
               and e["anchor"]["symbol"] == sym}
        missing = [k for k in keys if k not in reg]
        if missing:
            bad += 1
        ok(not missing, f"G4 分区表覆盖完整：{rel}::{sym}（{len(keys)} 键）",
           f"漏登 {missing}")
    return bad


def run_all(cr=None):
    _PASS.clear()
    _FAIL.clear()
    if cr is None:
        from . import config_registry as cr
    print("[统一配置层守卫] 判据 G1..G4")
    total = g1_schema(cr) + g2_anchors(cr) + g3_generated(cr) + g4_table_coverage(cr)
    print(f"\n结果：PASS {len(_PASS)} / FAIL {len(_FAIL)}")
    return len(_FAIL)


# ---------------------------------------------------------------------------
# 定点变异自证
# ---------------------------------------------------------------------------
_MUTATIONS = []


def _mut(name, kind, rel, anchor, repl):
    _MUTATIONS.append((name, kind, rel, anchor, repl))


# ① 改 registry 里的 const 缺省（登记侧漂移）
_mut("M1 registry-const-默认值改掉", "registry", None,
     "WINDOW_SHORT_D", 4)
# ② 改代码里的 const 缺省（代码侧漂移）
_mut("M2 代码-const-默认值改掉", "code", "md_cg/admission.py",
     "WINDOW_SHORT_D = 3", "WINDOW_SHORT_D = 4")
# ③ 改既有真源表的值（分区表漂移）
_mut("M3 既有表-sleep-interval-改掉", "table", "md_cg/sleep.py",
     '"interval": "3600"', '"interval": "1800"')
# ④ 改 env 字面量缺省（env 面漂移）
_mut("M4 env-字面量缺省改掉", "code", "md_cg/mdcg.py",
     'os.environ.get("MDCG_GATE_S2_COND", "1")',
     'os.environ.get("MDCG_GATE_S2_COND", "0")')
# ⑤ 文档参数表陈旧
_mut("M5 文档参数表陈旧", "doc", None, "registry 条目合计", "registry 条目合计")
# ⑥ 校验器陈旧
_mut("M6 校验器陈旧", "validator", None, "RULES = ", "RULES = {}  # ")


def _apply_mutation(name, kind, rel, anchor, repl):
    """应用一条变异；锚点找不到 ⇒ 返回 2（ANCHOR-MISS）。返回 0/2。"""
    from . import config_registry as cr
    if kind == "registry":
        for e in cr.entries():
            if e["name"] == anchor:
                e["value"] = repl
                return 0
        return 2
    if kind in ("code", "table"):
        text = _read(rel)
        if anchor not in text:
            return 2
        _SRC[rel] = text.replace(anchor, repl, 1)
        return 0
    if kind == "doc":
        text = open(_DOC, encoding="utf-8").read()
        _SRC["__doc__"] = text.replace(anchor, anchor + "（变异）", 1)
        return 0
    if kind == "validator":
        text = open(_VALIDATOR, encoding="utf-8").read()
        _SRC["__validator__"] = text.replace(anchor, repl, 1)
        return 0
    return 2


def _run_mutations():
    from . import config_registry as cr
    print("[定点变异自证] 预期：每条变异后守卫**必红**，复原后**全绿**")
    bad = 0
    for name, kind, rel, anchor, repl in _MUTATIONS:
        # 复原（重新导入真源 + 清空源码覆盖）
        _SRC.clear()
        import importlib
        from . import config_registry as _cr
        importlib.reload(_cr)
        code = _apply_mutation(name, kind, rel, anchor, repl)
        if code == 2:
            print(f"  ANCHOR-MISS {name}（锚点 {anchor!r} 在 {rel} 找不到）")
            return 2
        fails = run_all(_cr)
        red = fails > 0
        ok(red, f"{name} ⇒ 守卫转红（FAIL={fails}）", "未转红")
        if not red:
            bad += 1
        _SRC.clear()
        importlib.reload(_cr)
    # 复原后全绿
    _SRC.clear()
    import importlib
    from . import config_registry as _cr2
    importlib.reload(_cr2)
    fails = run_all(_cr2)
    ok(fails == 0, f"复原后复跑全绿（FAIL={fails}）", "未复原为绿")
    if fails:
        bad += 1
    print(f"\n变异自证结果：{'全部按预期' if bad == 0 else str(bad) + ' 项不符'}")
    return 1 if bad else 0


def main(argv):
    if "--list" in argv:
        for n, k, r, a, _ in _MUTATIONS:
            print(f"{n}  [{k}]  {r or '-'}  anchor={a!r}")
        return 0
    if "--mutate" in argv:
        # 文档/校验器变异需经 _SRC；其余读盘
        import md_cg.config_render as _r
        real_doc = _r.render_doc
        real_val = _r.render_validator

        def doc_patched(cr, _rd=real_doc):
            t = _rd(cr)
            return _SRC.get("__doc__", t)

        def val_patched(cr, _rv=real_val):
            t = _rv(cr)
            return _SRC.get("__validator__", t)

        _r.render_doc = doc_patched
        _r.render_validator = val_patched
        return _run_mutations()
    fails = run_all()
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


# pytest 收集入口（脚本式文件也可被 pytest 收）
def test_config_registry_guard():
    assert run_all() == 0


def test_config_registry_guard_mutations():
    assert main(["--mutate"]) == 0
