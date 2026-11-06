# -*- coding: utf-8 -*-
# 功能名：台账双端触发点的定点变异自证（守卫真能红吗）
# 生效条件：python -X utf8 -m md_cg.mutate_ledger_e2e
# 子功能：对 mcp_server 的 recent·add 抽取块做 4 处**语义有效**变异，
#   每处都必须让 test_state_ledger_e2e 失败；还原后必须复绿。
# 执行：备份原文 → 逐条变异 → 跑守卫 → 还原 → 复跑。
# 验证方式：每处 mutation 都被捕获（rc≠0），全还原后 rc=0。
# 不适用条件：不做语法级变异（见下方「为什么不用 pass/删除行」）。

"""为什么不用「删行 / 换 pass」这类变异（本仓已栽过，2026-11-02 实录）：

上一轮做 `state_extract` 变异时，我把 `_se.append(...)` 换成 `pass` 却留下后续
实参 → `SyntaxError`，rc=1 但**根本没走到断言**，什么也没证明。那是假捕获。

故本文件的每处变异都保持**语法有效、语义变坏**，并且断言必须
"因为行为不对" 而红，不是"因为文件坏了"而红。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(REPO, "md_cg", "mcp_server.py")
GUARD = "md_cg.test_state_ledger_e2e"
BAK = TARGET + ".mutbak"


def run_guard():
    p = subprocess.run([sys.executable, "-X", "utf8", "-m", GUARD],
                       cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode


MUTS = [
    # （名字，原文片段，替换片段）
    ("M1 抽取块整段停用（语法有效：条件恒假）",
     "            if _role == \"user\" and _text and _meta.get(\"session\"):",
     "            if False and _role == \"user\" and _text and _meta.get(\"session\"):"),

    ("M2 去掉「只抽用户轮」前置（助手轮也抽）",
     "            if _role == \"user\" and _text and _meta.get(\"session\"):",
     "            if _text and _meta.get(\"session\"):"),

    ("M3 去掉 session 前置（无归属也抽）",
     "            if _role == \"user\" and _text and _meta.get(\"session\"):",
     "            if _role == \"user\" and _text:"),

    ("M4 异常不再 fail-soft（改成不吞，破坏窗口写入隔离）",
     "                except Exception:  # noqa: BLE001\n                    pass",
     "                except ZeroDivisionError:  # noqa: BLE001\n                    pass"),
]


def main():
    if not os.path.exists(TARGET):
        print("目标不在：%s" % TARGET)
        return 1
    shutil.copy2(TARGET, BAK)
    caught, missed = 0, 0
    try:
        base = run_guard()
        print("基线（未变异）：rc=%d %s" % (base, "OK 绿" if base == 0 else "!! 基线就红"))
        if base != 0:
            print("基线不绿，变异自证无意义；先修基线")
            return 1
        print()
        for name, old, new in MUTS:
            src = open(BAK, encoding="utf-8").read()
            if old not in src:
                print("  SKIP %-52s（原文片段未命中，变异无效）" % name)
                missed += 1
                continue
            open(TARGET, "w", encoding="utf-8", newline="\n").write(
                src.replace(old, new, 1))
            rc = run_guard()
            if rc != 0:
                caught += 1
                print("  CAUGHT %-52s rc=%d" % (name, rc))
            else:
                missed += 1
                print("  MISSED %-52s rc=0（断言没兜住这个坏法）" % name)
    finally:
        shutil.copy2(BAK, TARGET)
        os.remove(BAK)
        rc = run_guard()
        print()
        print("还原后复跑：rc=%d %s" % (rc, "OK 复绿" if rc == 0 else "!! 未复绿"))

    print()
    print("变异自证：捕获 %d / 漏 %d（总 %d）" % (caught, missed, len(MUTS)))
    return 0 if (missed == 0 and caught == len(MUTS)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
