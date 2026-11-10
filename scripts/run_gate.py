#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""灵枢发布门禁 · 全执行 + 汇总（R-302，2026-11-10）

【为什么有它】
`package.json` 的 `gate` 此前是 13 项的 `&&` 链。`&&` 的语义是「第一个失败就停」——
实测在第 4 项 `cogmap_sync.py check` 就短路（5 处 README 深链行号漂移），
**后 9 道门一次都没执行过**，其中包含 `gate_rust_parity.py`（Rust↔Python 逐位对拍）
与 `verify_discipline.py`。讽刺的是 `gate_rust_parity` 本身就是为了「门禁绿 ≠ 有回归
保障」而加的。

本脚本改成：**逐项跑完，全部汇总，任一红则总退出码非 0**。

【判据（三闸）】
- 判据：13 项**全部**出现在输出里；非 0 退出 ⇔ 至少一项红
- 负控：往任一项注入失败（如临时改坏 `link_check.py` 的输入）⇒ 该项红 **且后续项仍执行**
- 复跑：`python scripts/run_gate.py`；只列不跑用 `--list`

【报数三行（scripts/AGENTS.md 要求）】
  数：本次执行 N 项 / 红 M 项
  口径：`scripts/run_gate.py` 的 `ITEMS` 清单，逐项 `subprocess.run`，超时 900s
  反例：若某脚本 `import` 失败即退 2，会被记为红（不是「跳过」）—— 这正是要的
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable or "python"

#: (显示名, argv) —— 与 package.json 原 `gate` 链逐项对应；加门只改这里
ITEMS = [
    ("不可达死码", [PY, "scripts/check_unreachable.py"]),
    ("发布件清单", [PY, "scripts/check_publish_artifact.py"]),
    ("发布件冒烟", [PY, "scripts/check_publish_smoke.py"]),
    ("认知图同步", [PY, "scripts/cogmap_sync.py", "check"]),
    ("文档链接", [PY, "scripts/link_check.py"]),
    ("行锚点", [PY, "scripts/check_line_anchors.py"]),
    ("工作区索引", [PY, "scripts/workspace_index.py", "--check"]),
    ("纪律投影生成", [PY, "scripts/discipline_nodes.py", "--init", "--write",
                 "--cg-root", ".tmp/discipline-cg"]),
    ("纪律投影校验", [PY, "scripts/verify_discipline.py", "--allow-missing",
                 "--cg-root", ".tmp/discipline-cg"]),
    ("Rust crate 测试", [PY, "scripts/gate_rust_crate_test.py"]),
    ("Rust↔Python 对拍", [PY, "scripts/gate_rust_parity.py"]),
    ("本机路径", [PY, "scripts/check_local_paths.py"]),
    ("端到端冒烟", [PY, "scripts/body_e2e_smoke.py"]),
    # R-304（2026-11-10）：此前 6 个 workflow **无一**调用 run_tests.py，147 目标的
    # Python 套件完全在 CI 之外；本项把它接进发布门禁。串行（--jobs 1）——并发
    # 下多条测试共享库根会互相踩（见 known-red.md 的 flaky 标注）。
    ("Python 全量套件", [PY, "scripts/run_tests.py", "md_cg", "--jobs", "1",
                    "--timeout", "300"]),
]

TIMEOUT = 900


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--timeout", type=int, default=TIMEOUT)
    a = ap.parse_args()

    if a.list:
        for i, (name, argv) in enumerate(ITEMS, 1):
            print("%2d  %-18s %s" % (i, name, " ".join(argv)))
        print("\n共 %d 项" % len(ITEMS))
        return 0

    rows = []
    t_all = time.time()
    for i, (name, argv) in enumerate(ITEMS, 1):
        t0 = time.time()
        try:
            r = subprocess.run(argv, cwd=ROOT, capture_output=True,
                               encoding="utf-8", errors="replace",
                               timeout=a.timeout)
            rc = r.returncode
            tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        except subprocess.TimeoutExpired:
            rc = -1
            tail = ["超时 > %ds" % a.timeout]
        dt = time.time() - t0
        rows.append((i, name, rc, dt, tail))
        print("%s %2d %-18s rc=%-3d %6.1fs  %s"
              % ("PASS" if rc == 0 else "FAIL", i, name, rc, dt,
                 (tail[-1][:88] if tail else "")))

    bad = [x for x in rows if x[2] != 0]
    print("\n数：执行 %d 项 / 红 %d 项 / 总计 %.1fs"
          % (len(rows), len(bad), time.time() - t_all))
    print("口径：scripts/run_gate.py 的 ITEMS 清单，逐项 subprocess，超时 %ds，"
          "**全部执行不短路**" % a.timeout)
    print("反例：某脚本 import 失败退 2 会被记为红（不是跳过）；`--list` 只列不跑")
    if bad:
        print("\n红项：")
        for i, name, rc, dt, tail in bad:
            print("  %2d %-18s rc=%d" % (i, name, rc))
            for ln in (tail[-3:] if tail else []):
                print("       %s" % ln[:150])
    print("\n结果：%s" % ("全绿（13/13）" if not bad else "红 %d 项" % len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
