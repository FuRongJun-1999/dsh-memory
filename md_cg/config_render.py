# -*- coding: utf-8 -*-
"""统一配置层 · **生成器的渲染函数**（真源 → 生成件）。

本模块只做「registry 真源 → 文本」的纯函数渲染，不触盘、无副作用：

    render_doc(cr)        → 文档参数表（`docs/reference/配置参数表_v0.1.md`）
    render_validator(cr)  → 值域/类型校验器（`md_cg/config_validate.py`）

触盘由薄壳 `scripts/gen_config_doc.py` / `scripts/gen_config_validate.py` 做；
守卫 `md_cg/config_registry_guard.py` 直接用本模块做「生成件是否与真源一致」
的判据（生成件陈旧 ⇒ 红）。

纪律：**生成件不手写**。要改文档表或校验器的形态，改本模块后重跑薄壳。
"""
from __future__ import annotations

import pprint

from . import autonomy_modes as _am
from . import sleep as _sl

#: 两个「既有守卫禁止第二处字面量」的 env 名——**从真源表取**，本文件不写字面量。
#: 守卫：`md_cg/test_sleep_p1.py::g8`（`"MDCG_SLEEP*"`）、
#: `md_cg/test_autonomy_modes.py::g_g`（`MDCG_AUTONOMY` 单双引号皆禁）。
_ENV_SLEEP_MERGE = _sl.SLEEP_ENV_KEYS["merge"]
_ENV_AUTONOMY_MODE = _am.AUTONOMY_ENV_KEYS["mode"]

#: 生成件里以**变量表达式**取代字面量的键（否则生成件会成第二处字面量落点）。
DERIVED_KEY_VARS = {
    _ENV_SLEEP_MERGE: "_ENV_SLEEP_MERGE",
    _ENV_AUTONOMY_MODE: "_ENV_AUTONOMY_MODE",
}

#: 已知枚举的合法值域（**人工核验**，取自源码；未列者不约束——不许编）。
ENUMS = {
    "MDCG_MCP_SURFACE": ("kernel", "full"),
    "MDCG_CLEARANCE": ("public", "internal", "restricted", "private", "secret"),
    _ENV_AUTONOMY_MODE: tuple(_am.AUTONOMY_MODES),
    _ENV_SLEEP_MERGE: tuple(_sl.SLEEP_MERGE_MODES),
    "IMGSKILL_BACKEND": ("auto", "magick", "pillow"),
    "MDCG_SCORE_MODE": ("legacy", "jaccard"),
}

#: 明显带值域约束的数值参数（**人工核验**，取自源码夹取/断言；未列者不约束）。
#: 值 = (下限, 上限, 类型)；None 表示该侧不约束。
RANGES = {
    "MDCG_BUCKET_MIN_SIM": (0.0, 1.0, "float"),
    "MDCG_SPREAD_GAIN": (0.0, 1.0, "float"),
    "MDCG_SPREAD_DECAY": (0.0, 1.0, "float"),
    "MDCG_NEG_SIM": (0.0, 1.0, "float"),
    "MDCG_NEG_LAMBDA": (0.0, 1.0, "float"),
    "MDCG_SPREAD_HOPS": (1, None, "int"),
    "MDCG_HOTCACHE_MAX_NODES": (1, None, "int"),
    "MDCG_HOTCACHE_MAX_QUERIES": (1, None, "int"),
    "MDCG_REACH_TTL": (0.0, None, "float"),
    "MDCG_TEMPORAL_GAMMA": (0.0, None, "float"),
}

_DOC_HEADER = "# 配置参数表 v0.1（由 registry 真源生成，勿手改）\n"
_GEN_HEADER = ('# -*- coding: utf-8 -*-\n'
               '"""统一配置层 · 值域/类型校验器（**生成件**，勿手改）。\n')


def _fmt_value(e):
    v = e.get("value")
    if v is None:
        return "—"
    return "`" + repr(v) + "`"


def _fmt_anchor(e):
    a = e["anchor"]
    sym = a.get("symbol") or ""
    if a.get("key"):
        sym = f"{sym}[{a['key']!r}]"
    if a.get("how") == "env_literal" or a.get("how", "").startswith("env"):
        return f"`{a['file']}`（env）"
    if a.get("how", "").startswith("helper_arg"):
        return f"`{a['file']}`（助手实参）"
    if a.get("how") == "table_entry":
        return f"`{a['file']}::{sym}`（既有真源表）"
    return f"`{a['file']}::{sym}`"


def _rows_for(entries, cols):
    out = []
    for e in entries:
        out.append("| " + " | ".join(cols(e)) + " |")
    return out


def render_doc(cr) -> str:
    cat = cr.catalog()
    L = [_DOC_HEADER]
    L.append("> 生成自 `md_cg/config_registry.py`（真源）+ "
             "`md_cg/config_registry_bulk.py`（生成件）。\n"
             "> 重跑：`python -X utf8 scripts/gen_config_doc.py`；"
             "守卫：`python -X utf8 -m md_cg.config_registry_guard`。\n")
    L.append("## 计数\n")
    c = cat["counts"]
    L.append("| 口径 | 数 |")
    L.append("|---|---|")
    L.append(f"| registry 条目合计 | {c['total']} |")
    L.append(f"| 环境面 ENV（只登记分类） | {c['by_face']['ENV']} |")
    L.append(f"| 调参面 TUNE | {c['by_face']['TUNE']} |")
    L.append(f"| 标定面 CALIB | {c['by_face']['CALIB']} |")
    L.append(f"| 真数值型可调（tunable） | {c['tunable']} |")
    L.append(f"| 缺省分叉/跨副本不一致（conflict） | {c['conflict']} |")
    L.append("| status | " + "／".join(
        f"{k}={v}" for k, v in c["by_status"].items()) + " |")
    L.append(f"| 环境面分类登记（只登记分类） | {c['env_category']} |")
    L.append("")
    L.append("## 分层表（谁能进用户配置文件）\n")
    L.append("| face | 进用户配置文件 | 进调参序列 | 理由 |")
    L.append("|---|---|---|---|")
    for r in cat["layer_table"]:
        L.append(f"| {r['face']} | {'是' if r['user_config'] else '否'} | "
                 f"{'是' if r['tune_sequence'] else '否'} | {r['why']} |")
    L.append("")
    L.append("## 优先级\n")
    L.append(" > ".join(cat["priority_order"]) + "\n")
    L.append("## 写配置权限矩阵（角色 → 可写类别）\n")
    L.append("| 角色 | 可写类别 |")
    L.append("|---|---|")
    for role, cls in cat["role_write_matrix"].items():
        L.append(f"| {role} | {'、'.join(cls) if cls else '（不可写配置）'} |")
    L.append("")
    L.append(f"写入需二次确认的类别：{'、'.join(cat['classes_requiring_confirm'])}\n")

    L.append("## 环境面分类登记（只登记分类、**不登记缺省值**）\n")
    L.append("| name | kind | repo | 值域类型 | 备注 |")
    L.append("|---|---|---|---|---|")
    for r in cr.env_catalog():
        L.append(f"| {r['name']} | {r['kind']} | {r['repo']} | {r['domain']} | "
                 f"{r['notes']} |")
    L.append("")

    cols = (lambda e: [e["name"], e["kind"], "是" if e["tunable"] else "否",
                       _fmt_value(e), e.get("semantic") or e["domain"],
                       e.get("env_name") or "—", _fmt_anchor(e), e["status"]])
    for face in cr.FACES:
        es = cr.by_face(face)
        L.append(f"## {face} 面（{len(es)} 条）\n")
        L.append("| name | kind | tunable | 缺省 | 语义/值域 | env | 锚点 | status |")
        L.append("|---|---|---|---|---|---|---|---|")
        L += _rows_for(es, cols)
        L.append("")
    return "\n".join(L) + "\n"


def _rule_for(e):
    """条目 → 校验规则（只登记**已知**约束；未知不臆造）。"""
    r = {"type": e.get("value_type") or "str"}
    name = e.get("env_name") or e["name"]
    # ① 真开关/失败放行语义 → 布尔
    if e.get("semantic") in ("on", "off", "fail-open"):
        r["type"] = "bool"
        r["bool_like"] = True
    # ② 已知枚举 → 枚举约束
    if name in ENUMS:
        r["type"] = "str"
        r["enum"] = list(ENUMS[name])
    # ③ 已知数值值域 → 数值类型 + 上下限
    if name in RANGES:
        lo, hi, t = RANGES[name]
        r["type"] = t
        if lo is not None:
            r["min"] = lo
        if hi is not None:
            r["max"] = hi
    if r["type"] not in ("int", "float", "bool", "str"):
        r["type"] = "str"
    return r


def render_validator(cr) -> str:
    rules = {}
    for e in cr.tune_sequence() + cr.env_layer():
        key = e.get("env_name") or e["key"]
        rules[key] = _rule_for(e)
    L = [_GEN_HEADER]
    L.append("由 `md_cg/config_render.py::render_validator` 生成。真源 = "
             "`md_cg/config_registry.py`（+ 生成件 `config_registry_bulk.py`）。\n")
    L.append('"""\nfrom __future__ import annotations\n\nimport sys\n\n')
    L.append("from . import autonomy_modes as _am\n")
    L.append("from . import sleep as _sl\n\n")
    L.append("# 这两个键的**名字**取自既有真源表（既有守卫禁止第二处 env 名字面量；\n")
    L.append("# 见 md_cg/test_sleep_p1.py::g8 / md_cg/test_autonomy_modes.py::g_g）。\n")
    L.append("_ENV_SLEEP_MERGE = _sl.SLEEP_ENV_KEYS[\"merge\"]\n")
    L.append("_ENV_AUTONOMY_MODE = _am.AUTONOMY_ENV_KEYS[\"mode\"]\n\n")
    L.append("#: 参数名/env 名 → 校验规则（只登记已知约束，未列者不臆造）\n")
    L.append("RULES = {\n")
    for name in sorted(rules):
        key_expr = DERIVED_KEY_VARS.get(name, repr(name))
        L.append(f"    {key_expr}: "
                 + pprint.pformat(rules[name], width=76) + ",\n")
    L.append("}\n\n")
    L.append(_VALIDATOR_BODY)
    return "".join(L)


_VALIDATOR_BODY = '''
_TRUE = ("1", "true", "True", "yes", "y", "on", "On")
_FALSE = ("0", "false", "False", "no", "n", "off", "Off")


def coerce(name, raw):
    """把配置面取值（TOML 已带类型；env 恒为字符串）归一到规则类型。

    返回 (ok, value_or_None, err)。**不猜测**：无法归一即报错（fail-closed）。
    """
    r = RULES.get(name)
    if r is None:
        return True, raw, None
    t = r["type"]
    if isinstance(raw, bool):
        return True, raw, None
    if t == "bool" and r.get("bool_like"):
        s = str(raw)
        if s in _TRUE:
            return True, True, None
        if s in _FALSE:
            return True, False, None
        return False, None, f"{name}: 非布尔字面量 {raw!r}"
    try:
        if t == "int":
            v = int(raw)
        elif t == "float":
            v = float(raw)
        else:
            v = str(raw)
    except (TypeError, ValueError) as e:
        return False, None, f"{name}: 类型应为 {t}，得到 {raw!r}（{e}）"
    return True, v, None


def validate(name, raw):
    """值域/类型校验（唯一入口）。返回 (ok, coerced, err)。"""
    ok, v, err = coerce(name, raw)
    if not ok:
        return ok, v, err
    r = RULES.get(name)
    if r is None:
        return True, v, None
    if "enum" in r and v not in r["enum"]:
        return False, None, f"{name}: 取值 {v!r} 不在 {r['enum']}"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "min" in r and v < r["min"]:
            return False, None, f"{name}: {v} < 下限 {r['min']}"
        if "max" in r and v > r["max"]:
            return False, None, f"{name}: {v} > 上限 {r['max']}"
    return True, v, None


CASES = (
    # (name, 输入, 期望 ok)
    ("MDCG_MCP_SURFACE", "kernel", True),
    ("MDCG_MCP_SURFACE", "nope", False),
    ("MDCG_CLEARANCE", "internal", True),
    ("MDCG_CLEARANCE", "top-secret", False),
    ("MDCG_BUCKET_MIN_SIM", "0.34", True),
    ("MDCG_BUCKET_MIN_SIM", "1.7", False),
    ("MDCG_SPREAD_HOPS", "2", True),
    ("MDCG_SPREAD_HOPS", "0", False),
    (_ENV_AUTONOMY_MODE, "full", True),
    (_ENV_AUTONOMY_MODE, "god", False),
    (_ENV_SLEEP_MERGE, "auto", True),
    (_ENV_SLEEP_MERGE, "later", False),
    ("MDCG_HOTCACHE", "1", True),
    ("MDCG_HOTCACHE", "0", True),
    ("MDCG_HOTCACHE", "maybe", False),
)


def self_test():
    """内置用例自证（`--self-test` / pytest 收集）。返回失败数。"""
    bad = 0
    for name, raw, want in CASES:
        ok, _, err = validate(name, raw)
        if ok != want:
            bad += 1
            print(f"  FAIL {name}={raw!r} 期望 ok={want} 实得 {ok} ({err})")
    return bad


def test_config_validate_self_test():
    """pytest 收集入口。"""
    assert self_test() == 0


def main(argv):
    if "--self-test" in argv or not argv:
        bad = self_test()
        print(f"self-test: {'OK' if bad == 0 else str(bad) + ' FAIL'}")
        return 0 if bad == 0 else 1
    name = None
    val = None
    for i, a in enumerate(argv):
        if a == "--name" and i + 1 < len(argv):
            name = argv[i + 1]
        if a == "--value" and i + 1 < len(argv):
            val = argv[i + 1]
    if not name:
        print("用法：python -X utf8 -m md_cg.config_validate "
              "[--self-test | --name X --value V]")
        return 2
    ok, v, err = validate(name, val)
    print(f"{name} = {v!r}" if ok else f"拒绝：{err}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''
