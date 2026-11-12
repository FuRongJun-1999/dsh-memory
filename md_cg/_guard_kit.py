# -*- coding: utf-8 -*-
# 功能名：守卫完备性骨架（防「声称的面 > 实际覆盖的面」，task-16/#421+#422 沉淀）
# 生效条件：任何**声称「全枚举 / 全表 / 不变量 / 已落仓」**的守卫都应调用本模块的两条判据；
#           纯单点断言（不声称覆盖面）的守卫不适用。
# 子功能：
#   ① assert_enumeration_complete —— **枚举完备性自证**：把「应当被抓的第 N 种语法/形态」的
#      **合成样本**喂给**守卫自己的那条枚举逻辑**，必须命中；另喂「不该被抓」的样本，必须不命中
#      （过度收紧方向）。不通过则守卫自身转红。
#   ② assert_revert_reddens —— **回退即绿自证**：在**镜像树**里把被守护的修复实际回退一次，
#      实跑守卫并核对红项集合；**不接受推演**（#421 的指控点正是「声称有判据、回退却仍绿」）。
# 执行：由守卫在自身进程内 import 调用；两条判据都返回 (ok, detail) 并可打印。
# 验证方式：本模块自身的行为由使用它的守卫（test_issue400 / test_issue398）在 --mutate 下覆盖。
# 不适用条件：不判「枚举逻辑的语义正确性」（那是被守护的判据本体）；不做跨进程编排（②在镜像树里
#             子进程跑守卫，故只适用于**能独立跑起来**的守卫；需要外部依赖的守卫请显式跳过并注明）。
"""守卫完备性骨架。

为什么需要它（本会话三次同形事故）：
  · #400：E01 文案声称「hive 内裸 int() 只剩 _int_arg 本体一处」，实际只枚举**内联**
    `int(args.get(...))`——`v = spec.get(k); int(v)` 这种**变量中转**整类逃过（7 处）；
  · #421：回复声称「该守卫已随修复落仓」，实际守卫文件在**后一个提交**里才 add；
  · #398：声称的「弱化登记清单」在一次检索范围内不存在（那份检索面窄于声称面）。
⇒ 共同形态是**守卫声明的面 > 守卫实际覆盖的面**。本模块把两条「防衍生」判据做成可复用函数。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile


def assert_enumeration_complete(discover, samples, expect_hits=True):
    """枚举完备性自证。

    discover(texts: dict[relpath -> 源码文本]) -> list[命中项]
        **守卫自己的那条枚举逻辑**，写成「源码映射 → 命中列表」的纯函数（喂合成样本即靠这一点）。
    samples: list[(类名, 源码文本, 期望是否命中, relpath)]
        每类「语义等价形态」一个合成样本；含**不该命中**的样本（过度收紧方向）。

    返回 (ok, detail)；ok=False 时守卫应当转红——**这正是「第 N 种形态」的守卫**。
    """
    bad = []
    seen = []
    for cls, src, want, rel_hint in samples:
        texts = {rel_hint: src}
        try:
            hits = discover(texts)
        except Exception as exc:              # noqa: BLE001 —— 枚举逻辑崩了也要可归因
            bad.append((cls, "discover 抛 %s: %s" % (type(exc).__name__, exc)))
            continue
        got = bool(hits)
        seen.append((cls, got, len(hits)))
        if got != bool(want):
            bad.append((cls, "期望命中=%s 实际=%s（命中 %d）" % (want, got, len(hits))))
    detail = {"样本": seen, "不符": bad}
    return (not bad), detail


def assert_revert_reddens(build_mirror, revert_edits, run_guard, expect_prefixes,
                          rel_path, timeout=1800):
    """回退即绿自证：在镜像树里**实跑**一次回退，核对红项集合。

    build_mirror() -> 镜像树根路径（调用方负责其构成；本函数负责删）
    revert_edits  -> list[(相对路径, 原文, 替换文)]：**实际的回退**（不是等价改写）
    run_guard(tree) -> (rc, 红项列表, 完整输出)
    expect_prefixes -> 期望转红的前缀元组（如 ("A03", "E03")）

    返回 (ok, detail)。**不接受推演**：必须真的改文件、真的跑、真的看到红。
    """
    tree = build_mirror()
    detail = {}
    try:
        rc0, reds0, _out0 = run_guard(tree)
        if rc0 != 0 or reds0:
            detail["基线"] = "镜像基线即红：%s" % (reds0[:5],)
            return False, detail
        eol = None
        for rel, old, new in revert_edits:
            p = os.path.join(tree, rel)
            with io.open(p, encoding="utf-8", newline="") as f:
                txt = f.read()
            if eol is None:
                eol = "\r\n" if "\r\n" in txt else "\n"
            o = old.replace("\n", eol)
            if txt.count(o) != 1:
                detail[rel] = "回退锚点命中 %d 次" % txt.count(o)
                return False, detail
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(txt.replace(o, new.replace("\n", eol), 1))
        for root, dd, ff in os.walk(tree):
            if os.path.basename(root) == "__pycache__":
                shutil.rmtree(root, ignore_errors=True)
        rc1, reds1, out1 = run_guard(tree)
        hit = sorted({r.split(" ")[0] for r in reds1})
        detail["回退后 rc"] = rc1
        detail["实际红项"] = hit
        ok = (rc1 != 0) and (hit == sorted(expect_prefixes))
        if not ok:
            detail["输出尾部"] = "\n".join((out1 or "").splitlines()[-8:])
        return ok, detail
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def mirror_sources(texts, root):
    """把 {relpath: 源码} 物化到临时根下（供 discover 之外的端到端复跑用）。返回根。"""
    for rel, src in texts.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(src)
    return root


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)

