#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config-wiring-audit.py · 配置登记 vs 生产接线的机械对账（病灶 N）

背景（2026-10-20 审计）：`md_cg/config_registry*.py` 登记了 304 个旋钮，
其中一部分的「锚点模块」在生产链上一次 import 都没有（只有测试/基准脚本在引），
操作者读配置表会以为那些功能是能拨的。本脚本只做一件事：

    每个登记条目的 anchor_file（模块）→ 它是否在「从生产入口可达」的 import 闭包里。

判定口径
--------
根（production roots）：`md_cg/` 下带 `if __name__ == "__main__"` 且文件名不以
`test`/`bench`/`demo`/`probe` 开头的模块，加上 `md_cg/mdcg.py`、`md_cg/mdcos.py`、
`md_cg/mcp_server.py`（存在才算）、以及仓库 `scripts/*.py`（登记表里逐条点名的入口）。
边：AST 解析出的 import。三种写法都算：
  ① 绝对 `import md_cg.X` / `from md_cg.X import …`
  ② 相对 `from . import x` / `from ..y import z`
  ③ 裸名 `import chat_engine` / `from kwroute import match_longest`
     —— 灵枢的 whitebox_kb 依赖 sys.path 注入，裸名要按「当前包及其祖先包」逐个
     试成立（第一个存在的模块算命中）。
测试、基准、归档目录不参与计算。可达 = 根 ∪ 传递 import。

退出码：0 正常（清单已落盘）；1 解析失败。
"""

from __future__ import annotations

import ast
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD = os.path.join(REPO, "md_cg")
SCRIPT_DIRS = (MD, os.path.join(REPO, "scripts"))
SKIP_PREFIX = ("test", "bench", "demo")
SKIP_DIRS = {"__pycache__", "_archive", "node_modules"}
ROOT_MODULES = ("md_cg.mdcg", "md_cg.mdcos", "md_cg.mcp_server")


def iter_py(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def relmod(path):
    rel = os.path.relpath(path, REPO).replace(os.sep, "/")
    if rel.endswith(".py"):
        rel = rel[:-3]
    rel = rel.replace("/", ".")
    if rel.endswith(".__init__"):
        rel = rel[: -len(".__init__")]
    return rel


def raw_imports(path):
    """返回 [(kind, level, module, names)]，kind ∈ abs/rel/bare。"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            tree = ast.parse(f.read(), filename=path)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out.append(("abs" if a.name.startswith("md_cg") else "bare",
                            0, a.name, []))
        elif isinstance(n, ast.ImportFrom):
            kind = "rel" if n.level else ("abs" if (n.module or "").startswith("md_cg")
                                          else "bare")
            out.append((kind, n.level, n.module or "",
                        [a.name for a in n.names]))
    return out, None


def has_main_guard(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            tree = ast.parse(f.read(), filename=path)
    except (SyntaxError, UnicodeDecodeError):
        return False
    for n in tree.body:
        if isinstance(n, ast.If) and isinstance(n.test, ast.Compare):
            left = n.test.left
            if isinstance(left, ast.Name) and left.id == "__name__":
                return True
    return False


def ancestors(mod):
    parts = mod.split(".")
    return [".".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)]


def resolve(kind, level, node, names, mod, existing, short2mods=None):
    """把一条 import 归一成绝对模块名集合（只保留真实存在的模块）。"""
    found = set()

    def add(cand):
        if cand in existing:
            found.add(cand)

    if kind == "abs":
        add(node)
        for nm in names:
            add(node + "." + nm)
        return found
    if kind == "rel":
        anc = ancestors(mod)      # 由内到外的完整点分前缀
        if level - 1 >= len(anc):
            return found
        pkg = anc[level - 1]
        full = pkg + ("." + node if node else "")
        add(full)
        for nm in names:
            add(full + "." + nm)
        return found
    # bare：按「当前包 → 祖先包 → md_cg」逐个拼接
    for pkg in ancestors(mod) + ["md_cg"]:
        cand = pkg + "." + node
        if cand in existing:
            found.add(cand)
            for nm in names:
                add(cand + "." + nm)
            return found
    # 裸名平铺导入：`from aeis_core import X` 这类只要包里注入了 sys.path，
    # 短名不等于任何绝对前缀。按「模块名后缀」找唯一候选（同前缀多个取最短）。
    if short2mods is not None:
        cands = short2mods.get(node) or []
        if cands:
            best = sorted(cands, key=lambda m: (m.count("."), m))[0]
            add(best)
            for nm in names:
                add(best + "." + nm)
    return found


def production_graph():
    raws, failures, files = {}, [], {}
    for root_dir in SCRIPT_DIRS:
        for p in iter_py(root_dir):
            if os.path.basename(p).startswith(SKIP_PREFIX):
                continue
            mod = relmod(p)
            imps, err = raw_imports(p)
            if err:
                failures.append({"file": os.path.relpath(p, REPO), "err": err})
            raws[mod] = imps or []
            files[mod] = {"path": os.path.relpath(p, REPO).replace(os.sep, "/"),
                          "imports": set(), "root": False}
    existing = set(files)
    short2mods = {}
    for m in existing:
        short2mods.setdefault(m.rsplit(".", 1)[-1], []).append(m)
    for mod, imps in raws.items():
        for kind, level, node, names in imps:
            files[mod]["imports"] |= resolve(kind, level, node, names, mod, existing,
                                             short2mods)
    roots = set()
    for mod, info in files.items():
        if mod in ROOT_MODULES or mod.startswith("scripts."):
            info["root"] = True
            roots.add(mod)
        elif mod.endswith(".__main__"):
            # 包级入口 `python -m pkg`：__main__ 本身就是可执行入口
            info["root"] = True
            roots.add(mod)
            roots.add(mod[: -len(".__main__")])
            seen_pkg = mod[: -len(".__main__")]
            if seen_pkg in files:
                files[seen_pkg]["root"] = True
                files[seen_pkg]["imports"].add(mod)
        elif has_main_guard(os.path.join(REPO, info["path"])):
            info["root"] = True
            roots.add(mod)
    seen, stack = set(roots), list(roots)
    while stack:
        cur = stack.pop()
        for t in files.get(cur, {}).get("imports", ()):
            if t not in seen:
                seen.add(t)
                stack.append(t)
    # 包本身（__init__）不作为独立可达单元：任一子模块可达即视为可达
    changed = True
    while changed:
        changed = False
        for m in list(existing - seen):
            if any(w.startswith(m + ".") for w in seen):
                seen.add(m)
                changed = True
    return sorted(seen), sorted(existing - seen), files, failures


def registry_entries():
    sys.path.insert(0, REPO)
    from md_cg import config_registry as reg  # noqa: E402

    return reg.entries()


def audit():
    wired, unwired, files, failures = production_graph()
    wired_set = set(wired)
    rows = []
    for e in registry_entries():
        anchor = e.get("anchor") or {}
        af = (anchor.get("file") or "").strip()
        if not af:
            files_ = anchor.get("files") or []
            af = (files_[0] if files_ else "").strip()
        if not af:
            continue
        mod = af[:-3].replace("/", ".") if af.endswith(".py") else af.replace("/", ".")
        rows.append({
            "name": e.get("name"),
            "kind": e.get("kind"),
            "face": e.get("face"),
            "anchor_file": af,
            "module": mod,
            "wired": mod in wired_set,
            "module_exists": mod in set(files),
            "notes": (e.get("notes") or "")[:80],
        })
    by_mod = {}
    for r in rows:
        slot = by_mod.setdefault(r["module"], {"total": 0, "wired": r["wired"],
                                               "anchor_file": r["anchor_file"],
                                               "names": []})
        slot["total"] += 1
        slot["names"].append(r["name"])
    return {
        "roots": sorted(m for m, i in files.items() if i["root"]),
        "modules": {"total": len(files), "wired": len(wired), "unwired": len(unwired)},
        "wired": wired,
        "unwired": unwired,
        "entries": {"total": len(rows), "wired": sum(1 for r in rows if r["wired"]),
                    "unwired": sum(1 for r in rows if not r["wired"])},
        "entries_unwired": [r for r in rows if not r["wired"]],
        "by_module_unwired": {m: v for m, v in by_mod.items() if not v["wired"]},
        "parse_failures": failures,
    }


def emit_map(rep, path):
    """把「不可达模块」写成 md_cg/config_wiring_map.py（给文档渲染器读）。"""
    mods = list(rep["unwired"])
    lines = [
        "# -*- coding: utf-8 -*-",
        '"""配置接线地图（生成件，勿手改）。',
        "",
        "真源：`scripts/config-wiring-audit.py --emit-map`（AST import 闭包，从生产入口出发）。",
        "UNWIRED 里的模块：登记表把它当锚点，但生产链上一次 import 都没有。",
        '"""',
        "",
        "UNWIRED = (",
    ]
    lines += [f'    "{m}",' for m in mods]
    lines += [")", "", "UNWIRED_ENTRIES = (", ]
    for r in rep["entries_unwired"]:
        lines.append(f'    ("{r["name"]}", "{r["module"]}"),')
    lines += [")", ""]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    return path


def main(argv):
    out = None
    map_out = None
    for a in argv:
        if a.startswith("--out="):
            out = a.split("=", 1)[1]
        elif a.startswith("--emit-map="):
            map_out = a.split("=", 1)[1]
    rep = audit()
    text = json.dumps(rep, ensure_ascii=False, indent=1)
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
    if map_out:
        path = map_out if os.path.isabs(map_out) else os.path.join(REPO, map_out)
        emit_map(rep, path)
    print(f"根 {len(rep['roots'])} 个 · 生产模块 {rep['modules']['total']} · "
          f"可达 {rep['modules']['wired']} / 不可达 {rep['modules']['unwired']}")
    print(f"登记条目 {rep['entries']['total']} · 锚在可达模块 {rep['entries']['wired']} / "
          f"锚在不可达模块 {rep['entries']['unwired']}")
    for m, v in sorted(rep["by_module_unwired"].items()):
        print(f"  UNWIRED {m} · {v['total']} 条登记 · {v['anchor_file']}")
    if rep["parse_failures"]:
        print("解析失败:", rep["parse_failures"])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
