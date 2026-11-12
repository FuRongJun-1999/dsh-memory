# -*- coding: utf-8 -*-
# 功能名：状态事件台账「整链可达性」守卫（把可发货性判据从「一个文件」升级为「一条链」）
# 生效条件：python -X utf8 -m md_cg.test_state_ledger_chain；被测面＝状态事件台账的
#   四段链路 ①落盘点 ②生产方 ③触发点 ④端到端可达 —— 每一段都必须在**随包发货面**内。
# 子功能：A 落盘点单点性；B 生产方随包；C 触发点随包且非测试；D 跨端（TS）接线；
#   E 端到端可达性合成判定。
# 执行：纯静态（AST + package.json 白名单 + 文本扫描），零落盘、零网络。
# 验证方式：全绿 exit 0；**红的每一条都是链路上真实缺环**，不是环境缺失。
# 不适用条件：不判抽取规则好坏（见 test_state_extract.py）；不判台账读写语义
#   （见 test_state_events.py / test_state_slots.py）；不判 npm 实际 tarball。

"""为什么要它（2026-11-02，对上一轮修复的**自我纠正**）：

上一轮修了「`md_cg/state_extract.py` 未随包发货」，并加了守卫
`test_state_extract_shipped.py`。那条守卫钉住的判据是——
**「运行时被装载的模块，其所在目录必须被 files 白名单覆盖」**。

它对，但**只覆盖了链路末端**。真实链是三段：

    触发点（sync_zcode_session.sync_to_window）
        → 生产方（state_extract.extract_and_record）
        → 落盘点（state_events.append → _state_events.jsonl）

实测（2026-11-02）：
  · 落盘点 `md_cg/state_events.py`        SHIPPED  ✓
  · 生产方 `md_cg/state_extract.py`        SHIPPED  ✓（上一轮迁入）
  · 触发点 `scripts/sync_zcode_session.py` **MISSING**（files 白名单只发 scripts/workspace_index.py）

即：**上一轮的守卫会绿，而链仍是断的。** 判据覆盖不到触发点，
等于把一个"装载不到的模块"修成了"装得上但没人调"。

这不是新缺陷，是**判据落点选错**——与本仓多次栽过的
「同一判据两个落点」同族：我把"可发货"钉在了**被调方**上，
而断点在**调用方**。

另一条独立断点（DSH 端，更深）：`src/hooks.ts` 每轮调
`graph.recentAdd()` 写 `_recent.jsonl`（实测在跑），但**全文件无
`state_event` / `extract_and_record` / `state_extract` 任何字样**——
DSH 端从未接入状态抽取。zcode 端脚本又不在装机包里。
故装机环境里 `_state_events.jsonl` **零生产路径**（实测该文件 ABSENT）。

本守卫把三段一起钉住，并要求**至少存在一条端到端可达**的路径。
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  <- " + str(detail)) if detail and not cond else ""))


# ── 判据单点：随包发货面 ────────────────────────────────────────────────
def _shipped_predicate():
    """返回 shipped(rel)->bool；`files` 支持目录前缀（"md_cg" 覆盖整目录）。"""
    pkg = json.load(open(os.path.join(REPO, "package.json"), encoding="utf-8"))
    entries = [e.replace("\\", "/").rstrip("/") for e in (pkg.get("files") or [])]

    def shipped(rel):
        rel = rel.replace("\\", "/")
        return any(rel == e or rel.startswith(e + "/") for e in entries)
    return shipped, entries


def _py_files():
    """仓内全部 .py（跳过构建产物与依赖目录）。"""
    out = []
    for root, dirs, fs in os.walk(REPO):
        dirs[:] = [d for d in dirs
                   if d not in {"node_modules", ".git", "__pycache__", "lib", "web"}]
        for fn in fs:
            if fn.endswith(".py"):
                out.append(os.path.relpath(os.path.join(root, fn), REPO).replace("\\", "/"))
    return sorted(out)


def _is_test(rel):
    base = os.path.basename(rel)
    return base.startswith("test_") or "/test/" in rel or rel.startswith("test/")


def _callers_of(sym, files):
    """AST 面：哪些模块**调用了** sym（排除定义处与测试件）。"""
    hits = []
    for rel in files:
        try:
            tree = ast.parse(open(os.path.join(REPO, rel), encoding="utf-8").read(),
                             filename=rel)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = None
            if isinstance(f, ast.Attribute):
                name = f.attr
            elif isinstance(f, ast.Name):
                name = f.id
            if name == sym:
                ln = getattr(node, "lineno", 0)
                hits.append((rel, ln))
    return hits


def main():
    shipped, entries = _shipped_predicate()
    files = _py_files()

    # ── A 落盘点 ────────────────────────────────────────────────────
    print("== A 落盘点（怎么让它红：把 state_events.py 移出 md_cg/ 或删 files 里的 md_cg）")
    se_rel = "md_cg/state_events.py"
    ok(os.path.exists(os.path.join(REPO, se_rel)), "A1 落盘模块在场 %s" % se_rel)
    ok(shipped(se_rel), "A2 落盘模块随包发货", entries)

    # append 必须是唯一落盘单点：别处不得自己 open(ledger,'a')
    body = open(os.path.join(REPO, se_rel), encoding="utf-8").read()
    ok("def append(" in body, "A3 落盘单点 state_events.append 存在")
    foreign_writers = []
    for rel in files:
        if rel == se_rel or _is_test(rel):
            continue
        s = open(os.path.join(REPO, rel), encoding="utf-8").read()
        if "_state_events.jsonl" in s and re.search(r"open\s*\([^)]*['\"]a", s):
            foreign_writers.append(rel)
    ok(not foreign_writers,
       "A4 无第二个落盘点（别处不得直接以追加模式打开台账）", foreign_writers)

    # ── B 生产方 ────────────────────────────────────────────────────
    print("== B 生产方（怎么让它红：把 state_extract.py 移回 scripts/）")
    sx_rel = "md_cg/state_extract.py"
    ok(os.path.exists(os.path.join(REPO, sx_rel)), "B1 生产模块在场 %s" % sx_rel)
    ok(shipped(sx_rel), "B2 生产模块随包发货", entries)
    ok("def extract_and_record(" in open(os.path.join(REPO, sx_rel),
                                         encoding="utf-8").read(),
       "B3 生产面 extract_and_record 存在")

    # ── C 触发点（上一轮漏掉的一环）──────────────────────────────────
    print("== C 触发点（怎么让它红：删掉 mcp_server 的 recent 分支抽取块）")
    callers = [(r, l) for r, l in _callers_of("extract_and_record", files)
               if r != sx_rel and not _is_test(r)]
    ok(bool(callers), "C1 存在非测试的 extract_and_record 调用点（触发点）",
       "整仓零触发点 ⇒ 生产方永不执行")
    live = [r for r, _ in callers if shipped(r)]
    ok(bool(live),
       "C2 至少一个触发点在随包发货面内（装机环境可达）",
       "可发货触发点＝0 ⇒ 装机的包里有抽取器却没人调")

    # ── D 双端覆盖（判据已修正，见头注）──────────────────────────────
    print("== D 双端覆盖（怎么让它红：把 recent add 分支里的抽取块删掉）")
    srv = open(os.path.join(REPO, "md_cg", "mcp_server.py"), encoding="utf-8").read()
    # 取出 recent 分支的源码段（到 state_event 分支为止），只在该段内找抽取调用
    m = re.search(r'if op == "recent":(.*?)\n    if op == "state_event":',
                  srv, flags=re.S)
    recent_seg = m.group(1) if m else ""
    # 去注释，避免「文档里提过」被当成「接上了」（本轮判据修正的直接教训）
    seg_code = re.sub(r"#[^\n]*", "", recent_seg)
    ok("extract_and_record" in seg_code,
       "D1 服务端 recent·add 分支（双端共用单点）内直接调用抽取器",
       "recent 分支是 DSH 与 zcode 都必经的出口；不在此则必有一端覆盖不到")

    hooks = os.path.join(REPO, "src", "hooks.ts")
    if os.path.exists(hooks):
        s = open(hooks, encoding="utf-8").read()
        code = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
        code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
        ok("recentAdd" in code,
           "D2 DSH 端经 recentAdd 走上述单点（故不加 TS 调用也覆盖到）")
    else:
        ok(False, "D2 src/hooks.ts 不在（发行包内无 TS 源）", hooks)

    ok(shipped("md_cg/mcp_server.py"),
       "D3 服务端触发点本身随包发货", entries)

    # ── E 端到端可达性合成 ──────────────────────────────────────────
    print("== E 端到端可达性（三段同绿才算通）")
    seg_land = os.path.exists(os.path.join(REPO, se_rel)) and shipped(se_rel)
    seg_prod = os.path.exists(os.path.join(REPO, sx_rel)) and shipped(sx_rel)
    seg_trig = bool(live) and "extract_and_record" in seg_code
    ok(seg_land and seg_prod and seg_trig,
       "E1 存在「触发→生产→落盘」全段可达的链路（装机环境能真正写出事件）",
       "落盘=%s 生产=%s 触发=%s" % (seg_land, seg_prod, seg_trig))

    print()
    print("状态事件台账整链可达性：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("  失败项（每一条都是链路上的真实缺环）：")
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
