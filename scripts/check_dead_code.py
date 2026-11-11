#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""R-406 · 死码活性判据（scripts/check_dead_code.py）

【为什么有它】
审计发现一批「写了但没有任何人调用」的顶层定义与整块模块（`autocut.py` /
`defer.py` / `trashbin.py` / `selflayer.py` / `decision_state.py` / cond 死链…）。
仓里原有 `check_unreachable.py` 只覆盖 **TS 侧**导出的可达性，Python 主体没有对应判据
—— 于是「实现了但没人调」只能靠人眼发现。

【R-541 的三模块处置（2026-11-10）】
- `autocut.py`：**已删**（304 行纯函数、全树零引用、零测试；其「阈值裁切」规则集与
  在役检索截断路径重复，留着只会与主路径漂移）。git 历史保留原件。
- `trashbin.py`：**已接线**（接进 `sustain._tick_tidy`，守卫见
  `md_cg/test_trash_retention.py`）—— 保留期策略此前静默失效、正文永久留存。
- `defer.py`：**显式豁免**（零 import，但 `mreview/terminal.py` 以它的口径作对照；
  两条零引用定义在下面的 BASELINE 里带理由）。

【判什么】
`md_cg/*.py`（非 test_）的**顶层** `def` / `class`（不含 `__dunder__`），在全仓
`.py` / `.ts` / `.mjs` / `.rs` 的词频里出现次数 ≤ 1（= 只有定义本身），即判「零引用」。

**存量不进判据**（与 `scripts/AGENTS.md` §2 同口径）：31 条存量逐条登记在
`BASELINE` 里并写明理由，只有**新增**才红。

【不判什么】
- 方法（`ast.FunctionDef` 但不在模块顶层）—— 可能是回调用、可能被反射调用，判不准；
- 装饰器注册面（如 `@app.tool`）—— 词频法会把它算成「被引用」，漏就漏了；
- 包内 `__init__.py` 的再导出。
这三类都会带来假红，宁可漏。**判据的边界写在判据里，不许靠注释兜。**

【退出码】0 = 无新增死码；1 = 有新增；2 = 自身故障

【负控】在任一 `md_cg/*.py` 末尾加一个只定义不调用的顶层函数 ⇒ 必须报红。

【报数三行（scripts/AGENTS.md 要求）】
  数：扫 N 个模块 / 顶层定义 M 个 / 零引用 K 个（基线 31，新增 X）
  口径：词频法（全仓 .py/.ts/.mjs/.rs 里同名标识符出现 ≤1 次），只判模块顶层
  反例：方法、装饰器注册面、`__init__` 再导出**判不出来** —— 它们不在这条判据的射程内
"""
from __future__ import annotations

import argparse
import ast
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MDCG = os.path.join(ROOT, "md_cg")
SKIP_DIRS = {".git", "node_modules", "__pycache__", "_archive", ".tmp", "trash",
             "_md_cg_p0", "_md_cg_p0_conc", "_md_cg_p1", "_md_cg_p26", "_md_cg_p27",
             "_md_cg_p28", "_md_cg_membench", ".pytest_cache"}

#: 存量 31 条：审计已登记，不进判据（新增才红）。分四类：
#: ① 公开 API 供外部脚本用 ② 自测入口 ③ 已知死功能（审计已列） ④ 未接线的观测面
BASELINE = {
    # ① 公开 API / 供外部脚本或宿主调用
    "config_registry.toml_keys": "配置层公开查询面，供第二批写入器调用",
    "crypto.has_envelope": "加密信封探测 API，运维脚本用",
    "datapath.aux_path": "辅助根路径拼接，外部迁移脚本用",
    "conformance.register_sustain": "断言注册表项（按名注册，词频法看不见）",
    "hotcache.default_cache": "默认缓存工厂，供未接线的宿主装配",
    "coldverify.default_queue": "默认队列工厂，供未接线的宿主装配",
    "config_registry_guard.test_config_registry_guard": "自测入口（--selftest 调用）",
    # ② 已知死功能（审计报告 P2 已列，处置留给第 3 步）
    "decision_state.r1_counts": "decision_state 整块零引用（审计 P2-13）",
    "decision_state.r3_d_face": "同上",
    "decision_state.read_verified": "同上",
    "defer.is_hidden": "defer 整块零引用（审计 P1-D6）",
    "defer.is_pending": "同上",
    "selflayer.move_legacy": "selflayer 整块零引用（审计 P2-12）",
    "unresolved.listing": "unresolved 查询面未接线",
    "value_conflict.find_in": "value_conflict 未接线",
    "writegate.check_condition_quality": "条件质量 warn 通道未接线（审计 P2，R-503 待做）",
    # R-503（2026-11-10 已裁定）：这两个**不是遗漏**，是 v1 的设计决定
    # （mdcg 的 postings 模块 docstring 第 7 点：每次写都 load+save 75MB 不可接受，
    #  v1 只做全量重建，改写后请重建）。属 v2 里程碑，按「公开 API 待用」保留。
    "postings.add_to_table": "v1 不接增量（设计决定），v2 里程碑",
    "postings.remove_from_table": "同上",
    "state_slots._project": "状态槽投影未接线",
    "state_slots._project_current": "同上",
    "sig.est_jaccard": "签名相似度估算，暂无消费方",
    "refindex.render_of": "ref 渲染，暂无消费方",
    "vision_evidence._now_batch": "视觉证据批次时间戳，暂无消费方",
    "provenance.reset_origin_cache": "出处缓存重置，测试专用钩子",
    "op_table.op_section": "op 段落渲染，供 tool_face 之外的宿主（词频法看不见动态取）",
    "op_table.require_of": "同上",
    "op_table.sub_ops": "同上",
    "op_table.all_sub_ops": "同上",
    "op_table.params_of": "同上",
    "op_table.generic_params": "同上",
    "protocol.spec_of": "协议签名推导面，供外部校验器",
}


#: 必须排除在词频统计之外的**被核对象本身**（scripts/AGENTS.md「自证三条例」第 1 条）：
#: 本脚本的 BASELINE 里逐条写着那 31 个名字 —— 若把它们算进词频，每个名字就会因
#: 「基线里写了一次 + 定义处一次」而得到频次 2，判据当场失效（实测：`dead` 从 31 变 0）。
_SELF_EXCLUDE = {"check_dead_code.py"}


def _freq():
    c = collections.Counter()
    for dirpath, dirnames, files in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in files:
            if f in _SELF_EXCLUDE:
                continue
            if not f.endswith((".py", ".ts", ".mjs", ".rs")):
                continue
            try:
                txt = open(os.path.join(dirpath, f), encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", txt):
                c[w] += 1
    return c


def _top_level(mod_path):
    try:
        tree = ast.parse(open(mod_path, encoding="utf-8", errors="replace").read(), mod_path)
    except SyntaxError:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("__"):
                continue
            out.append((node.name, node.lineno))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    freq = _freq()
    mods, total_defs = 0, 0
    dead = []
    for fn in sorted(os.listdir(MDCG)):
        if not fn.endswith(".py") or fn.startswith("test_"):
            continue
        mods += 1
        key_mod = fn[:-3]
        for name, lineno in _top_level(os.path.join(MDCG, fn)):
            total_defs += 1
            if freq[name] <= 1:
                dead.append(("%s.%s" % (key_mod, name), lineno))

    known = [d for d in dead if d[0] in BASELINE]
    new = [d for d in dead if d[0] not in BASELINE]
    stale = sorted(set(BASELINE) - {d[0] for d in dead})

    print("数：扫 %d 个模块 / 顶层定义 %d 个 / 零引用 %d 个（基线 %d，**新增 %d**）"
          % (mods, total_defs, len(dead), len(known), len(new)))
    print("口径：全仓 .py/.ts/.mjs/.rs 词频法（同名标识符出现 ≤1 次），只判模块顶层，"
          "不含方法/装饰器注册面/__init__ 再导出")
    print("反例：被反射或按名字符串调用的（`getattr`、注册表按名查、装饰器注册）"
          "会被算成「零引用」而漏报；反之动态调用方写在不同语言里也会漏")

    if new:
        print("\n✗ 新增零引用顶层定义（%d）：" % len(new))
        for k, ln in new:
            print("   md_cg/%s  L%d" % (k.replace(".", ".py  ", 1), ln))
        print("\n处置三选一：接进调用点 / 删掉 / 登记进 BASELINE 并写理由")
    if stale:
        print("\n· BASELINE 里 %d 条已不再零引用（可移出基线）：" % len(stale))
        for k in stale[:8]:
            print("   ", k)
    if not a.quiet:
        print("\n存量（不进判据）前 6 条：")
        for k, ln in known[:6]:
            print("   %-46s L%-5d %s" % (k, ln, BASELINE.get(k, "")))
    print("\n结果：%s" % ("PASS（无新增死码）" if not new else "FAIL（新增 %d）" % len(new)))
    return 0 if not new else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:                                   # noqa: BLE001
        print("✗ 自身故障：%s: %s" % (type(e).__name__, e))
        sys.exit(2)
