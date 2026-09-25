#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""propose 尾部增量对账守卫（issue：propose 每条全量重读 inbox+decisions）。

缺陷形态（缺陷报告实测）：propose 每条在 strict 排它锁内
read_jsonl(inbox_log) + read_jsonl(decisions_log) 全量逐条 json.loads
（O(M+D)/条，批量累计 O(M²)），存量无 payload_hash 还逐条现算 sha1。
万条存量单条 ~26ms、批量 O(M²) 分钟级。

本守卫断言（调用计数/复杂度形态，非时间阈值）：
  T1 二次 propose 零全量读：同实例第 2 次 propose（无外部写）期间
     mdcos.read_jsonl 对 inbox/decisions 的调用数为 0（旧代码每条各 1 次
     全量 → 红）；
  T2 批量 O(M)：500 条连续 propose 全程，首条装载后 read_jsonl 调用数为 0
     （旧代码 2×499 次 → 红）；
  T3 增量不漏账（跨进程 append 可见）：外部 append 同内容提案（他进程形态）
     → 本实例 propose 同内容 dedup 命中新 pid；
  T4 已裁决优先语义保持：外部裁决（accepted）后 propose 同内容 →
     返回已裁决 pid + status；
  T5 旧格式兼容：无 payload_hash 存量行 → 同内容 propose 命中（装载期
     现算一次，不每条重算）；
  T6 幂等保形：同内容两次 propose 返回同 pid、不重复入队；
  T7 决策增量可见：外部 append decisions 后 _closed_pids 即含该 pid。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import md_cg.mdcos as mdcos_mod           # noqa: E402
from md_cg.fsutil import append_jsonl     # noqa: E402
from md_cg.mdcos import MdCGOS, _sig      # noqa: E402

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def count_full_reads(fn):
    """打桩 mdcos.read_jsonl 计数（propose/_pid_status 的全量读入口）。"""
    n = 0
    real = mdcos_mod.read_jsonl

    def _spy(path, *a, **kw):
        nonlocal n
        n += 1
        return real(path, *a, **kw)

    mdcos_mod.read_jsonl = _spy
    try:
        return fn(), n
    finally:
        mdcos_mod.read_jsonl = real


def main():
    root = tempfile.mkdtemp(prefix="mdcg_prop_guard_")
    try:
        cg = MdCGOS(root)
        # T1 二次 propose 零全量读（预热完成首装——inbox 文件由首条 propose
        # 创建，创建后第一次访问做一次全量装载属预期，装载后稳态零全量读）
        print("== T1 稳态 propose 零全量读 ==")
        cg.propose("t1w1", "T1 预热 甲")     # 创建 inbox + 装载（不计数）
        cg.propose("t1w2", "T1 预热 乙")     # 装载水位已建立（不计数）
        _, n1 = count_full_reads(lambda: cg.propose("t1", "T1 内容 甲"))
        print(f"  (稳态首次计数窗 full_reads={n1})")
        _, n2 = count_full_reads(lambda: cg.propose("t1b", "T1 内容 乙"))
        check("T1a 稳态 propose 全量 read_jsonl 调用 == 0（旧默认 2 次/条）",
              n1 == 0 and n2 == 0, f"full_reads={n1},{n2}")

        # T2 批量 O(M)：500 条连续 propose，装载完成后全量读为 0
        print("== T2 批量 500 条 O(M) ==")
        cg2_root = tempfile.mkdtemp(prefix="mdcg_prop_guard2_")
        cg2 = MdCGOS(cg2_root)
        try:
            cg2.propose("warm1", "预热 占位一")   # 创建 inbox + 装载（不计）
            cg2.propose("warm2", "预热 占位二")   # 水位建立（不计）
            _, nb = count_full_reads(lambda: [
                cg2.propose("b%03d" % i, "批量守卫 %d 各异 %d" % (i, i * 3))
                for i in range(500)])
            check("T2a 500 条批量 propose 全量 read_jsonl 调用 == 0"
                  "（旧代码 2×499=998 次，O(M²) 解析）", nb == 0,
                  f"full_reads={nb}")
        finally:
            shutil.rmtree(cg2_root, ignore_errors=True)

        # T3 增量不漏账：外部（他进程形态）append 同内容提案
        print("== T3 跨进程 append 可见（增量不漏账）==")
        content = "T3 同内容 蜂群调度"
        pid_ext = "prop_ext_abc123"
        append_jsonl(cg.inbox_log,
                     {"t": 1.0, "pid": pid_ext, "id": "ext_n",
                      "content": content, "layer": "knowledge",
                      "tags": [], "condition_space": {}, "verify": {},
                      "payload_hash": _sig(content), "actor": "ext"})
        r3 = cg.propose("t3", content, info=True)
        check("T3a 外部 append 后同内容 dedup 命中新 pid",
              r3["dedup"] and r3["pid"] == pid_ext, f"r={r3}")

        # T4 已裁决优先：外部裁决 accepted → propose 返回已裁决 pid
        print("== T4 已裁决优先 ==")
        append_jsonl(cg.decisions_log,
                     {"t": 2.0, "pid": pid_ext, "decision": "accept",
                      "status": "accepted", "round": 1, "actor": "ext"})
        r4 = cg.propose("t4", content, info=True)
        check("T4a 外部裁决后同内容返回已裁决 pid（accepted 优先）",
              r4["dedup"] and r4["pid"] == pid_ext
              and r4["dup_status"] == "accepted", f"r={r4}")
        check("T4b 外部裁决进入 _closed_pids（增量可见）",
              pid_ext in cg._closed_pids())

        # T5 旧格式兼容：无 payload_hash 存量行
        print("== T5 旧格式（无 payload_hash）==")
        legacy = "T5 旧格式内容 星云编译"
        append_jsonl(cg.inbox_log,
                     {"t": 3.0, "pid": "prop_legacy_001", "id": "lg_n",
                      "content": legacy, "layer": "knowledge",
                      "tags": [], "verify": {}, "actor": "old"})  # 无 hash
        r5 = cg.propose("t5", legacy, info=True)
        check("T5a 旧格式行同内容命中（装载期现算，兼容旧账）",
              r5["dedup"] and r5["pid"] == "prop_legacy_001", f"r={r5}")
        _, n5 = count_full_reads(lambda: cg.propose("t5b", legacy, info=True))
        check("T5b 旧格式行不触发每条重算全量读（==0）", n5 == 0,
              f"full_reads={n5}")

        # T6 幂等保形：同内容两次 propose 同 pid
        print("== T6 幂等保形 ==")
        p_a = cg.propose("t6", "T6 幂等内容")
        p_b = cg.propose("t6r", "T6 幂等内容")
        check("T6a 同内容两次 propose 返回同 pid（不重复入队）",
              p_a == p_b and p_a, f"{p_a} vs {p_b}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
