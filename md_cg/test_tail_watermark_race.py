# -*- coding: utf-8 -*-
"""四增量对账缓存水位守卫（缺陷：水位存 stat 时刻值，stat→read 窗口并发 append 重复并入）。

缺陷形态（缺陷报告 2026-09-25 复现证实，medium）：_pid_status /
_inbox_phash_index / _inbox_records / _decisions_records 四缓存（mdcos.py
:1708/:1739/:1768/:1793）扫描水位存「读前 stat 的 size」，而
fsutil.read_jsonl_tail（:228-249）seek(offset) 后**读到真实 EOF**——跨进程
append 恰落在 stat 与 read 之间时，新记录本轮已并入但水位偏小，下一轮增量
从旧水位重读：列表型缓存重复并入同一条记录（review_list 待审清单重复 pid、
review_stats 计数虚高、_cascade_dedup 连写两条 reject），且进程内永不自愈
（稳态 size 只增，不触发全量重建）。

修复：read_jsonl_tail 返回 (记录列表, 真实读到的 EOF 偏移)，四处缓存把水位
存为**实际消费位置**（含首装/回退全量路径统一走 tail(0) 取精确 EOF）；
读后再 stat 不可取——re-stat 可能大于已消费位置，下轮会跳过未读记录（丢账）。

红守卫 = 缺陷报告复现口径（monkeypatch mdcos.read_jsonl_tail / read_jsonl，
在 stat 后、read 前注入并发 append，等价真实交错）：
  A decisions：窗口 append 后 records 必须 == 盘上条数，且第三次调用仍相等
    （旧代码：本轮对、下轮重读翻倍、永不自愈）；
  B inbox：review_list 无重复 pid 且长度 == 盘上条数；
  C _pid_status dict 覆盖免疫（proposals == 去重 pid 数，语义锁）；
  D 首装全量路径同窗（旧代码全量重建同样把 stat size 当水位，一样翻倍）。
运行：python -m md_cg.test_tail_watermark_race
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

from . import mdcos
from .fsutil import append_jsonl, read_jsonl
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


class _WindowInjector:
    """把一条 append 注入 stat→read 窗口：目标函数被调（=stat 已发生）时
    先落盘注入记录再委托原函数——等价跨进程 append 恰落在窗口内的交错。"""

    def __init__(self, mod, log_path, rec):
        self.mod, self.path, self.rec = mod, log_path, rec
        self.fired = False
        self._orig_tail = mod.read_jsonl_tail
        self._orig_full = mod.read_jsonl

    def _maybe_inject(self, path):
        if not self.fired and os.path.abspath(str(path)) == \
                os.path.abspath(self.path):
            self.fired = True
            append_jsonl(self.path, self.rec)

    def _tail(self, path, offset):
        self._maybe_inject(path)
        return self._orig_tail(path, offset)

    def _full(self, path):
        self._maybe_inject(path)
        return self._orig_full(path)

    def __enter__(self):
        self.mod.read_jsonl_tail = self._tail
        self.mod.read_jsonl = self._full
        return self

    def __exit__(self, *a):
        self.mod.read_jsonl_tail = self._orig_tail
        self.mod.read_jsonl = self._orig_full


def _n_on_disk(path):
    return len(list(read_jsonl(path)))


def _dec(pid, decision="noop"):
    return {"t": time.time(), "pid": pid, "decision": decision,
            "status": decision, "round": 1, "actor": "race_guard"}


def _inbox(pid):
    return {"t": time.time(), "pid": pid, "id": "m_" + pid,
            "content": "窗口竞态守卫正文 " + pid, "layer": "knowledge"}


def _scenario_decisions(tmp):
    """A：decisions 尾部窗口（review_stats 口径）。"""
    print("== A decisions 窗口竞态（review_stats） ==")
    root = os.path.join(tmp, "dec")
    os.makedirs(root)
    cg = MdCGOS(root)
    append_jsonl(cg.decisions_log, _dec("p1"))
    append_jsonl(cg.decisions_log, _dec("p2"))
    st1 = cg.review_stats()
    ok(st1["records"] == 2, f"A1 基线装载 records=2（实测 {st1['records']}）")

    append_jsonl(cg.decisions_log, _dec("p3_ext"))      # stat 前并发 append
    with _WindowInjector(mdcos, cg.decisions_log, _dec("p4_ext")):
        st2 = cg.review_stats()                          # 读窗内并发 append
    disk = _n_on_disk(cg.decisions_log)
    ok(st2["records"] == disk,
       f"A2 窗口轮 records==盘上（{st2['records']} vs 盘上 {disk}）")

    st3 = cg.review_stats()
    ok(st3["records"] == disk,
       f"A3 下一轮不重读（records={st3['records']}，盘上 {disk}——"
       f"旧代码重读 p4_ext 虚高为 {st3['records']}）")
    st4 = cg.review_stats()
    ok(st4["records"] == disk,
       f"A4 永不自愈形态不得出现（第三次调用 records={st4['records']}，"
       f"盘上 {disk}）")
    disk_noop = sum(1 for r in read_jsonl(cg.decisions_log)
                    if r.get("decision") == "noop")
    ok(st4["by_decision"].get("noop", 0) == disk_noop,
       f"A5 noop 计数与盘上一致（{st4['by_decision'].get('noop', 0)} vs "
       f"{disk_noop}）")
    # C：_pid_status 为 dict 后写覆盖——窗口竞态不得影响 pid 去重口径
    pids_disk = {r.get("pid") for r in read_jsonl(cg.decisions_log)}
    st5 = cg.review_stats()
    ok(st5["proposals"] == len(pids_disk)
       and set(cg._pid_status()) == pids_disk,
       f"C1 proposals==盘上去重 pid 数（{st5['proposals']} vs "
       f"{len(pids_disk)}）——dict 覆盖免疫不受影响")


def _scenario_inbox(tmp):
    """B：inbox 尾部窗口（review_list 待审清单）。"""
    print("== B inbox 窗口竞态（review_list） ==")
    root = os.path.join(tmp, "inbox")
    os.makedirs(root)
    cg = MdCGOS(root)
    append_jsonl(cg.inbox_log, _inbox("q1"))
    append_jsonl(cg.inbox_log, _inbox("q2"))
    rl1 = cg.review_list()
    ok(len(rl1) == 2, f"B1 基线装载待审 2（实测 {len(rl1)}）")

    append_jsonl(cg.inbox_log, _inbox("q3_ext"))
    with _WindowInjector(mdcos, cg.inbox_log, _inbox("q4_ext")):
        rl2 = cg.review_list()
    disk = _n_on_disk(cg.inbox_log)
    ok(len(rl2) == disk,
       f"B2 窗口轮待审数==盘上（{len(rl2)} vs {disk}）")

    rl3 = cg.review_list()
    pids = [r.get("pid") for r in rl3]
    ok(len(rl3) == disk and len(set(pids)) == len(pids),
       f"B3 下一轮无重复 pid（len={len(rl3)}，去重 {len(set(pids))}，"
       f"盘上 {disk}——旧代码 q4_ext 重复并入）")
    rl4 = cg.review_list()
    pids4 = [r.get("pid") for r in rl4]
    ok(len(rl4) == disk and len(set(pids4)) == len(pids4),
       f"B4 第三次调用仍无重复（len={len(rl4)}，盘上 {disk}）")


def _scenario_first_load(tmp):
    """D：首装全量路径同窗（旧代码全量重建也把 stat size 当水位）。"""
    print("== D 首装全量路径同窗 ==")
    root = os.path.join(tmp, "first")
    os.makedirs(root)
    cg = MdCGOS(root)
    append_jsonl(cg.decisions_log, _dec("d1"))
    append_jsonl(cg.decisions_log, _dec("d2"))
    with _WindowInjector(mdcos, cg.decisions_log, _dec("d3_ext")):
        st1 = cg.review_stats()                     # 首装发生在窗口内
    disk = _n_on_disk(cg.decisions_log)
    ok(st1["records"] == disk,
       f"D1 首装窗口轮 records==盘上（{st1['records']} vs {disk}）")
    st2 = cg.review_stats()
    ok(st2["records"] == disk,
       f"D2 首装后下一轮不重读（records={st2['records']}，盘上 {disk}）")


def main():
    os.environ.pop("MDCG_READ_CACHE", None)
    tmp = tempfile.mkdtemp(prefix="mdcg_tail_race_")
    try:
        _scenario_decisions(tmp)
        _scenario_inbox(tmp)
        _scenario_first_load(tmp)
    finally:
        os.environ.pop("MDCG_READ_CACHE", None)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
