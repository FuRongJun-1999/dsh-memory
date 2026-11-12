#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""统一配置层 · **反向对账守卫**：代码里读的 env 必须在 registry 登记面内（issue #120）。

# 功能名：check_config_env_registry —— 「代码读取面 → registry 登记面」反向对账
# 生效条件：仓库根可解析、md_cg/ 可遍历、registry 可导入（任一不可用 ⇒ exit 2 fail-closed）
# 子功能：
#   ① 扫代码里的 **env 读取**（AST 三形态：os.environ.get(lit) / os.environ[lit] 读 /
#      os.getenv(lit)，外加「模块级别名 NAME = "MDCG_X" 再被读」的间接形态）；
#   ② 与 registry 登记面（ENV_ROWS / CONST_ROWS 的 name·env_name 列 ∪ entries() ∪
#      env_catalog()）对账；
#   ③ 缺口以 **显式基线**（BASELINE）冻结：新缺口 ⇒ 红；基线失效（已登记/已不读）⇒ 红。
# 执行：python -X utf8 scripts/check_config_env_registry.py [--json|--mutate|--root DIR]
# 验证方式：绿读数（本仓基线态 exit 0）＋ --mutate 定点变异读数（注入一个未登记 env 读取 ⇒ 必红）；
#           自证见 scripts/test_check_config_env_registry.py
# 不适用条件：
#   · 不判「缺省值是否合理」（标定/裁定的事，见 config_registry_guard.py 的 G2）；
#   · 不判「登记条目的语义字段是否可信」（tunable/domain 的口径边界见
#     config_registry_bulk.py 头部「字段语义（如实）」段——那是**注释对齐**，非本守卫判据）；
#   · 测试文件（test_*.py）与 whitebox_kb/ 知识库数据件不在扫描面内——**这是有意收窄**，
#     故本守卫不能读作「全仓 env 完备性」的证明，只能读作「生产面读取 ⊆ 登记面 ∪ 显式基线」。

判据（任一条红 ⇒ 退出码 1）
--------------------------
  C1 代码读取面 ⊆ 登记面 ∪ BASELINE（**新**的未登记读取 ⇒ 红）
  C2 BASELINE 不得陈旧（条目已进登记面 ⇒ 红：请从基线删除）
  C3 BASELINE 不得陈旧（条目已不再被读 ⇒ 红：请从基线删除）
  C4 登记面可构建（读不到 registry ⇒ exit 2，不静默放过）
  C5 **校验器口径 ↔ 源码真值**（issue #138）：生成件 config_validate 里每个 bool_like 规则，
     其归一为「真」的词表必须**同时**让源码判真——源码写 == "1" 的开关，校验器不得把
     "true"/"yes"/"on" 当作开（那会让用户按校验器写配置而行为相反，且零报错）。
     与 #120 同款**冻结账本**：新失配 ⇒ 红；账本条目已对齐 ⇒ 红（请收缩账本）。

口径（**先钉口径再报数**——#120 复核时双方数字差异全部来自口径）
--------------------------------------------------------------
  · 扫描面：md_cg/**/*.py，排除 test_*.py、__pycache__、whitebox_kb/、_probe_hv；
  · 识别面：AST。**只认读取**（Load 语境的 environ[]、.get()、getenv()）；写入
    （environ["X"] = ... / environ.update(X=...)）不算读取；
  · 间接形态：模块级 NAME = "<ENV>" 别名（**变量名须以 _ENV 结尾**，与仓内
    _INDEX_ENV / _QUALIFY_ENV / BUDGET_MAX_ENV 的既有约定一致），其后任何对 NAME 的读折算为
    该 env 的读取；**不以 _ENV 结尾的同值常量（如状态码 "ACCEPT"、错误码 E_PERM）不算 env**；
  · 登记面：config_registry_bulk.ENV_ROWS/CONST_ROWS 的 name 与 env_name 列 ∪
    config_registry.entries() 的 name/env_name/key ∪ env_catalog()（复合名按 " / " 拆分）；
  · 名字面：只判**本仓自有配置词表**（ENV_PREFIXES）内的名字——第三方服务键
    （DEEPSEEK_API_KEY 等）与 bench 私有变量（BENCH6_*、ZH_PROBE_*）不在判据面内。

退出码：0 = 通过（无新缺口且基线不陈旧）；1 = 有判据红；2 = 环境/解析错误（fail-closed）。
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

#: 不看的面（判据面=生产源码；测试夹具与知识库数据件有意排除，见模块头「不适用条件」）
SKIP_DIRS = frozenset({"__pycache__", "whitebox_kb", "_probe_hv", ".git",
                       "node_modules", ".tmp", "target"})
SCAN_SUBDIR = "md_cg"

ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")

#: 判据名字面：本仓自有配置词表前缀（取自 env_catalog() 的实有前缀，勿凭想象扩表）
ENV_PREFIXES = ("MDCG_", "AEIS_", "LINGSHU_", "IMGSKILL_", "DMCG_", "DSH_", "HIVE_")

#: **冻结基线**：当前「生产面读取但未登记」的 env（2026-10-12 首次登记，issue #120）。
#: 规则：**新增缺口必须改这里**（从而在 code review 里可见）；条目一旦进登记面或不再被读，
#: 必须从本表删除（C2/C3 会红）。**基线只减不增**。
BASELINE: dict = {
    # 2026-10-12：issue #120 的 22 项缺口**已补登记**（见 config_registry_bulk.py
    # 的 ENV_CATEGORY_ROWS 补登记段），故基线清空——此后**任何**未登记读取即红。
}


# 生效条件：src 为 Python 源码文本；解析失败返回 None（由调用方决定是跳过还是报错）。
def _parse(src):
    try:
        return ast.parse(src)
    except SyntaxError:
        return None


# 生效条件：tree 为已解析的模块 AST；返回 {别名: env 名}——仅收模块级 NAME = "<ENV>" 且右侧为字面量者。
def _aliases(tree):
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id.endswith("_ENV") \
                and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str) \
                and ENV_NAME_RE.match(node.value.value):
            out[node.targets[0].id] = node.value.value
    return out


def _is_environ(node):
    return (isinstance(node, ast.Attribute) and node.attr == "environ"
            and isinstance(node.value, ast.Name) and node.value.id == "os")


# 生效条件：sources 为 {相对路径: 源码文本}；返回 {env 名: [位置]}（位置形如 "md_cg/x.py:12"）。
def collect_env_reads(sources):
    """**判据单点**（自证测试按此打桩做定点变异）：从源码集合里提取 env **读取**面。"""
    found = {}
    for rel, src in sorted(sources.items()):
        tree = _parse(src)
        if tree is None:
            continue
        alias = _aliases(tree)
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Attribute) and f.attr == "get" and _is_environ(f.value):
                    if node.args and isinstance(node.args[0], ast.Constant) \
                            and isinstance(node.args[0].value, str):
                        name = node.args[0].value
                elif isinstance(f, ast.Attribute) and f.attr == "getenv" \
                        and isinstance(f.value, ast.Name) and f.value.id == "os":
                    if node.args and isinstance(node.args[0], ast.Constant) \
                            and isinstance(node.args[0].value, str):
                        name = node.args[0].value
            elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) \
                    and _is_environ(node.value):
                sl = node.slice
                if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                    name = sl.value
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) \
                    and node.id in alias:
                name = alias[node.id]
            if name and ENV_NAME_RE.match(name) and name.startswith(ENV_PREFIXES):
                found.setdefault(name, set()).add("%s:%d" % (rel, getattr(node, "lineno", 0)))
    return {k: sorted(v) for k, v in found.items()}


# 生效条件：root 为仓库根（含 md_cg/）；返回 {相对路径: 源码文本}（按扫描面过滤）。
def load_sources(root):
    base = os.path.join(root, SCAN_SUBDIR)
    out = {}
    for dp, dn, fn in os.walk(base):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            if not f.endswith(".py") or f.startswith("test_"):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            with open(p, encoding="utf-8", errors="replace") as fh:
                out[rel] = fh.read()
    return out


# 生效条件：root 为仓库根；registry 可导入（否则抛 ImportError，由 run 兜成 exit 2）。
def registry_names(root):
    """登记面：ENV_ROWS/CONST_ROWS 的 name·env_name ∪ entries() ∪ env_catalog()。"""
    if root not in sys.path:
        sys.path.insert(0, root)
    from md_cg import config_registry as cr
    from md_cg import config_registry_bulk as bulk
    names = set()
    for rows in (bulk.CONST_ROWS, bulk.ENV_ROWS):
        for r in rows:
            for i in (0, 8):
                v = r[i] if len(r) > i else ""
                if isinstance(v, str) and v:
                    names.add(v)
    for e in cr.entries():
        for k in ("name", "env_name", "key"):
            v = e.get(k)
            if isinstance(v, str) and v:
                names.add(v)
    for row in bulk.ENV_CATEGORY_ROWS:
        for part in str(row[0]).split(" / "):
            part = part.strip()
            if part:
                names.add(part)
    return names


# 生效条件：reads/registered/baseline 均非 None；返回 (new, stale_registered, stale_gone) 三个有序列表。
def compare(reads, registered, baseline):
    """判据 C1/C2/C3 的**单点实现**（自证测试直接调用）。"""
    new = sorted(n for n in reads if n not in registered and n not in baseline)
    stale_reg = sorted(n for n in baseline if n in registered)
    stale_gone = sorted(n for n in baseline if n not in reads)
    return new, stale_reg, stale_gone


#: **校验器口径账本**（issue #138）：当前「校验器 bool 词表宽于源码真值」的键。
#: 规则同 BASELINE：**新失配必须改这里**；条目一旦对齐必须删除（C5 会红）。**只减不增**。
VALIDATOR_LEDGER: dict = {
    # 2026-10-12：#138 的 14 项口径差**已由 config_render._rule_for 的
    # bool:/enum: 域标记 + coerce 严格布尔消解**，故账本清空。
}

#: 源码侧「严格字面量比较」的形态：environ.get("X") == "1"
TRUE_LITERAL_RE = re.compile(r'==\s*"([^"]*)"')

#: 反相形态（== "0" / == "false"）的字面量集：源码判「非它即真」，校验器词表只要不含它即同口径
FALSY_LITERALS = frozenset({"0", "false", "False", "no", "n", "off", "Off", ""})


# 生效条件：root 为仓库根、可导入 md_cg.config_validate（否则抛，由 run 兜成 exit 2）。
def validator_module(root):
    if root not in sys.path:
        sys.path.insert(0, root)
    from md_cg import config_validate as cv
    return cv


# 生效条件：sources 为源码集合、name 为 env 名；返回该 env 在源码里被 == "<字面量>" 比较到的字面量集（取并集；无可判形态返回空集）。
def source_truth_literals(sources, name):
    """只认**读取**行（environ.get("X"...) / environ["X"]），写形态（update/赋值）不计。"""
    lits = set()
    for _rel, src in sources.items():
        for line in src.split("\n"):
            if "environ" not in line or "environ.update(" in line:
                continue
            read = any(p in line for p in (
                'environ.get("%s"' % name, "environ.get('%s'" % name,
                'environ["%s"]' % name, "environ['%s']" % name))
            if not read:
                continue
            lits.update(TRUE_LITERAL_RE.findall(line))
    return lits


# 生效条件：sources 为源码集合、cv 为 config_validate 模块；返回 (mis, unknown, wide)——mis=校验器真值词表⊄源码真值的键（**必有判别力**），unknown=源码侧无严格字面量形态（不判），wide=词表宽度读数。
def validator_mismatches(sources, cv):
    """**判据单点**（自证测试按此打桩做定点变异）。"""
    default_vocab = set(getattr(cv, "_TRUE", ()))
    mis, unknown = [], []
    for k, r in sorted(cv.RULES.items()):
        if not r.get("bool_like"):
            continue
        lits = source_truth_literals(sources, k)
        if not lits:
            unknown.append(k)
            continue
        # 反相形态（源码写 == "0"：非 "0" 即真）⇒ 真值集 = 互补，校验器词表只须不含该字面量
        true_vocab = set(r.get("true_literals") or default_vocab)
        if lits <= FALSY_LITERALS:
            bad = bool(true_vocab & lits)
        else:
            bad = not (true_vocab <= lits)
        if bad:
            mis.append(k)
    return mis, unknown, len(default_vocab)


MUTATION_ENV = "MDCG_ZZZ_GUARD_MUTATION_PROBE"


# 生效条件：root 为仓库根、baseline 为基线映射；sources 可显式注入（自证测试用）。返回退出码。
def run(root, baseline, as_json=False, mutate=False, sources=None):
    try:
        sources = load_sources(root) if sources is None else sources
        registered = registry_names(root)
    except Exception as exc:
        print("环境错误（fail-closed）：%s" % exc)
        return 2
    if mutate:
        cand = sorted(k for k in sources if k.endswith("mdcg.py")) or sorted(sources)
        if not cand:
            print("变异失败：扫描面为空")
            return 2
        target = cand[0]
        sources = dict(sources)
        sources[target] += '\n_zzz_probe = os.environ.get("%s", "1")\n' % MUTATION_ENV
        print("定点变异：在 %s 注入 os.environ.get(%r)" % (target, MUTATION_ENV))
    reads = collect_env_reads(sources)
    new, stale_reg, stale_gone = compare(reads, registered, baseline)
    try:
        cv = validator_module(root)
        mis, unknown, wide = validator_mismatches(sources, cv)
    except Exception as exc:                              # noqa: BLE001
        print("环境错误（校验器不可读，fail-closed）：%s" % exc)
        return 2
    mis_new = [k for k in mis if k not in VALIDATOR_LEDGER]
    led_stale = sorted(k for k in VALIDATOR_LEDGER if k not in mis)
    ok = not (new or stale_reg or stale_gone or mis_new or led_stale)
    if as_json:
        print(json.dumps({"ok": ok, "reads": len(reads), "registered": len(registered),
                          "baseline": len(baseline), "new": new,
                          "baseline_now_registered": stale_reg,
                          "baseline_no_longer_read": stale_gone,
                          "validator_mismatch": mis, "validator_mismatch_new": mis_new,
                          "validator_unjudged": unknown,
                          "validator_ledger": len(VALIDATOR_LEDGER),
                          "validator_ledger_stale": led_stale}, ensure_ascii=False))
    else:
        print("[配置面反向对账] 代码读取 env %d 个 / 登记面 %d 个 / 冻结基线 %d 个"
              % (len(reads), len(registered), len(baseline)))
        print("  %s C1 代码读取面 ⊆ 登记面 ∪ 基线（新缺口 %d）"
              % ("PASS" if not new else "FAIL", len(new)))
        for n in new:
            print("       + %s  %s" % (n, "; ".join(reads[n][:3])))
        print("  %s C2 基线不陈旧·已进登记面（%d）" % ("PASS" if not stale_reg else "FAIL", len(stale_reg)))
        for n in stale_reg:
            print("       - %s 已进登记面 ⇒ 请从 BASELINE 删除" % n)
        print("  %s C3 基线不陈旧·已无读取点（%d）" % ("PASS" if not stale_gone else "FAIL", len(stale_gone)))
        for n in stale_gone:
            print("       - %s 已无读取点 ⇒ 请从 BASELINE 删除" % n)
        print("  %s C5 校验器口径 ⊆ 源码真值（新失配 %d / 已冻账本 %d / 未判 %d / 词表宽 %d）"
              % ("PASS" if not mis_new and not led_stale else "FAIL", len(mis_new),
                 len(VALIDATOR_LEDGER), len(unknown), wide))
        for n in mis_new:
            print("       + %s 校验器真值词表宽于源码（源码只认 %s）"
                  % (n, sorted(source_truth_literals(sources, n))))
        for n in led_stale:
            print("       - %s 已对齐 ⇒ 请从 VALIDATOR_LEDGER 删除" % n)
        print("结果：%s" % ("PASS" if ok else "FAIL"))
    if mutate:
        print("变异后判据：%s（期望 FAIL）" % ("FAIL" if not ok else "PASS"))
    return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--root", default=_REPO)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args(argv)
    return run(a.root, BASELINE, a.json, a.mutate)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
