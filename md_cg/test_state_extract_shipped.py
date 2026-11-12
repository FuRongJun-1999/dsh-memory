# -*- coding: utf-8 -*-
# 功能名：状态抽取器的「可发货性」守卫（issue 实测缺陷防复发，2026-11-02）
# 生效条件：python -X utf8 -m md_cg.test_state_extract_shipped；被测面＝
#   ① `md_cg/state_extract.py` 存在且是**生产方**（有 RULES/extract_turn/extract_and_record 定义）
#   ② `scripts/state_extract.py` 是**薄垫片**（只 import 绑定，不定义判据）
#   ③ 两者是**同一对象**（不是两份实现）
#   ④ 生产方所在目录在 `package.json` 的 `files` 白名单覆盖范围内（＝能随包发货）
# 子功能：A 本体在场且可执行；B 垫片无重复定义（AST 面）；C 对象同一性；D 打包覆盖。
# 执行：纯静态 + 一次真抽取（temp 库），不写仓内任何文件。
# 验证方式：全部 PASS exit 0；每节注明「怎么让它红」。
# 不适用条件：不校验 npm 实际 tarball（那是 check_publish_artifact 的面）；不判抽取
#   规则好坏（见 test_state_extract.py）；不覆盖 DSH 端 TS 接线（宿主库内 TS 钩子
#   尚未接本链路——那是 `src/hooks.ts` 的面，且本机无 node_modules 无法构建验证，
#   不在此面冒充已验证）。
"""为什么要它（真实缺陷，2026-11-02 实测）：

`state_extract.py` 此前整份落在 `scripts/`，而 `package.json` 的 `files` 白名单
**只发 `scripts/workspace_index.py`**。实测 `npm pack --dry-run --ignore-scripts`：
发货 1791 件，`scripts/` 下仅 1 件，`state_extract.py` MISSING。

后果不是「少个文件」，而是**每轮记账链在装机环境整条断掉**：装机侧
`sync_zcode_session._load_state_extract()` 装载不到抽取器 ⇒ `state_events.append`
永不发生 ⇒ 生产台账 `_state_events.jsonl` 长期 `events=0`（`state_slots --status`
实测）。世界模型 L2 的读面（`state_chain`/`state_slots`/`alternatives`）做得再准，
源头无数据就是空转。

**发布闸为什么不拦**：`scripts/check_publish_artifact.py` 的 R1–R7 校验的是
「**清单内的文件安不安全**」（凭据/私有数据/隐私/非追踪件/路径逃逸/…），
不校验「**必需文件在不在清单里**」——它没有「必需件」概念，故白名单漏项是它的
盲区。本守卫补的正是这个盲区：把「运行时被装载的模块，其所在目录必须被 files
白名单覆盖」钉成断言。

判据单点：**生产方必须在可发货目录内**。`md_cg/` 整目录在白名单里；`scripts/`
只剩 `workspace_index.py`。故本体归 `md_cg/`，垫片归 `scripts/`。
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  <- " + str(detail)) if detail and not cond else ""))


#: 生产方的公开面：垫片**不得**重新定义其中任何一个（否则就是两份实现）。
_PROD_SYMS = ("RULES", "extract_turn", "extract_and_record", "enabled",
              "DEFAULT_SUBJECT")


def _defined_names(path):
    """AST 面：该文件里**自己定义**的顶层名（函数/类/赋值目标）。"""
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
    return out


def main():
    core_p = os.path.join(HERE, "state_extract.py")
    shim_p = os.path.join(REPO, "scripts", "state_extract.py")
    pkg_p = os.path.join(REPO, "package.json")

    print("== A 本体在场（怎么让它红：删掉 md_cg/state_extract.py）")
    ok(os.path.exists(core_p), "A1 md_cg/state_extract.py 存在")
    if not os.path.exists(core_p):
        print("\n本体缺失，后续断言无从进行")
        return 1
    core_defs = _defined_names(core_p)
    for s in ("RULES", "extract_turn", "extract_and_record"):
        ok(s in core_defs, "A2 本体定义了生产面 %s" % s)

    print("== B 垫片无重复实现（怎么让它红：把原实现抄回 scripts/state_extract.py）")
    ok(os.path.exists(shim_p), "B1 scripts/state_extract.py 仍在（既有 import 路径不变）")
    if os.path.exists(shim_p):
        shim_defs = _defined_names(shim_p)
        dup = sorted(shim_defs & set(_PROD_SYMS))
        ok(not dup, "B2 垫片不得重新定义生产面符号（发现重复定义即两份判据）", dup)
        ok("enabled" not in dup and "extract_turn" not in dup,
           "B3 关键两函数只在 md_cg 定义一次")

    print("== C 对象同一性（怎么让它红：让垫片自己包一层 wrapper 函数）")
    import importlib.util
    from md_cg import state_extract as core
    spec = importlib.util.spec_from_file_location(
        "_shim_probe", shim_p) if os.path.exists(shim_p) else None
    if spec is not None:
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        ok(m.extract_turn is core.extract_turn,
           "C1 垫片 extract_turn 与本体是同一对象")
        ok(m.extract_and_record is core.extract_and_record,
           "C2 垫片 extract_and_record 与本体是同一对象")
        ok(m.RULES is core.RULES, "C3 规则表是同一对象（无第二份规则）")

    print("== D 打包覆盖（怎么让它红：把本体移回 scripts/ 或删掉 files 里的 md_cg）")
    pkg = json.load(open(pkg_p, encoding="utf-8"))
    files = pkg.get("files") or []
    # `files` 支持目录前缀（"md_cg"）——生产方所在目录须被某条目覆盖。
    core_dir = os.path.basename(HERE)          # "md_cg"
    covered = any(
        entry == core_dir or entry.startswith(core_dir + "/")
        for entry in files)
    ok(covered, "D1 生产方目录 %r 被 package.json files 白名单覆盖" % core_dir,
       files)
    ok("scripts" not in files,
       "D2 scripts/ 不是整目录发货（故放生产方进去即漏发——本缺陷的成因）",
       files)
    ok(os.path.basename(core_p) == "state_extract.py",
       "D3 生产方文件名与既有装载点期望一致")

    print("== E 端到端（怎么让它红：让 extract_and_record 不落台账）")
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("MDCG_")}
    root = tempfile.mkdtemp(prefix="mdcg_ship_")
    try:
        os.environ["MDCG_ROOT"] = root
        os.environ["MDCG_STATE_ROOT"] = os.path.join(root, "state")
        os.environ["MDCG_AUX_ROOT"] = os.path.join(root, "aux-root")
        from md_cg.mdcos import MdCGOS
        from md_cg import state_events as _se
        cg = MdCGOS(root)
        n = core.extract_and_record(cg, "s-ship", 1, "user", "我搬到青岛了")
        evs = _se.read(cg)
        ok(n == 1 and evs and evs[-1]["new"] == "青岛",
           "E1 从 md_cg 本体可直接抽取并落台账（不经 scripts/）", (n, evs))
    finally:
        for k in list(os.environ):
            if k.startswith("MDCG_"):
                os.environ.pop(k, None)
        os.environ.update(saved)
        shutil.rmtree(root, ignore_errors=True)

    print()
    print("状态抽取器可发货性守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
