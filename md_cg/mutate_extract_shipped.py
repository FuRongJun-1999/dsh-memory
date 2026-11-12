# -*- coding: utf-8 -*-
"""定点变异自证：`md_cg/test_state_extract_shipped.py` 的每条判据是否真能红。

口径（沿本仓既有变异纪律）：逐个植入「本该被抓住」的缺陷，跑守卫，断言**必须红**；
还原后断言**必须绿**且文件 sha256 逐字节还原。变异的对象是**仓内真实文件**
（先备份到内存，finally 必还原），不改在役库、不落第二份副本。

运行：python -X utf8 -m md_cg.mutate_extract_shipped
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CORE = os.path.join(HERE, "state_extract.py")
SHIM = os.path.join(REPO, "scripts", "state_extract.py")
PKG = os.path.join(REPO, "package.json")
GUARD = "md_cg.test_state_extract_shipped"


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def run_guard():
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", GUARD],
                       cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONUTF8": "1"})
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def mutate(label, path, old, new, expect_hit_substr):
    """把 path 里 old 换成 new，跑守卫，断言必须红且命中期望断言；还原。"""
    orig = open(path, encoding="utf-8").read()
    backup = orig
    digest = sha(path)
    if old not in orig:
        print("  SKIP %-52s （变异锚点不存在：%r）" % (label, old[:40]))
        return None
    try:
        open(path, "w", encoding="utf-8", newline="\n").write(
            orig.replace(old, new, 1))
        rc, out = run_guard()
        hit = expect_hit_substr in out
        caught = rc != 0 and hit
        print(("  OK   " if caught else "  MISS ") + "%-52s rc=%s 命中=%s"
              % (label, rc, hit))
        return caught
    finally:
        open(path, "w", encoding="utf-8", newline="\n").write(backup)
        assert sha(path) == digest, "!! 还原后 sha256 不一致：" + path


def main():
    print("== 基线（必须先绿）")
    rc0, out0 = run_guard()
    print("  基线 rc=%s（0＝绿）" % rc0)
    if rc0 != 0:
        print(out0)
        return 1

    print("== 逐条变异（每行都必须 OK＝被抓住）")
    results = []

    # M1：本体删掉生产面 → A2 必红（模拟「本体没搬过来」）
    results.append(mutate(
        "M1 本体删 extract_and_record 定义", CORE,
        "def extract_and_record(cg, session: str, turn_no, role: str, text: str,",
        "def _gone_extract_and_record(cg, session: str, turn_no, role: str, text: str,",
        "A2 本体定义了生产面 extract_and_record"))

    # M2：垫片重新实现判据 → B2 必红（模拟「两份实现」复发）
    results.append(mutate(
        "M2 垫片重新定义 RULES（两份判据）", SHIM,
        'from md_cg.state_extract import (',
        'RULES = []\n\nfrom md_cg.state_extract import (',
        "B2 垫片不得重新定义生产面符号"))

    # M3：垫片包一层 wrapper → C1 必红（模拟「薄别名变成真实现」）
    results.append(mutate(
        "M3 垫片把 extract_turn 包成 wrapper", SHIM,
        'from md_cg.state_extract import (            # noqa: E402,F401  —— 薄别名，非实现',
        'from md_cg.state_extract import extract_turn as _core_extract_turn\n'
        'def extract_turn(*a, **k):\n    return _core_extract_turn(*a, **k)\n\n'
        'from md_cg.state_extract import (            # noqa: E402,F401  —— 薄别名，非实现',
        "C1 垫片 extract_turn 与本体是同一对象"))

    # M4：白名单删掉 md_cg → D1 必红（模拟「生产方目录不可发货」）
    results.append(mutate(
        "M4 package.json files 删掉 md_cg", PKG,
        '"lib",\n    "src",\n    "md_cg",',
        '"lib",\n    "src",',
        "D1 生产方目录"))

    # M5：extract_and_record 不落台账 → E1 必红（模拟「抽取了但不记账」）
    # 注意：变异必须是**语义有效**的。首版把 `_se.append(...)` 那行替换成 `pass`
    # 留下后面几行实参 ⇒ SyntaxError（rc=1 但根本没走到 E1）——那是**假捕获**，
    # 证明不了断言有力度。改为在函数体开头插 `return 0`：语法合法、语义是
    # 「抽了但不记账」，E1 必须以断言文本失败。
    results.append(mutate(
        "M5 extract_and_record 提前 return 0（不记账）", CORE,
        "    n = 0\n    for ev in extract_turn(text, role, subject):",
        "    return 0  # MUTANT: 不记账\n    n = 0\n    for ev in extract_turn(text, role, subject):",
        "E1 从 md_cg 本体可直接抽取并落台账"))

    print("== 还原后必须复绿")
    rc1, out1 = run_guard()
    print("  还原后 rc=%s（0＝绿）" % rc1)

    done = [r for r in results if r is not None]
    caught = sum(1 for r in done if r)
    print()
    print("变异自证：%d/%d 被捕获；还原后复绿=%s"
          % (caught, len(done), rc1 == 0))
    okall = caught == len(done) and len(done) == 5 and rc1 == 0
    print("结论：" + ("全部判据有力度（可红可复绿）" if okall else "存在无力度判据"))
    return 0 if okall else 1


if __name__ == "__main__":
    raise SystemExit(main())
