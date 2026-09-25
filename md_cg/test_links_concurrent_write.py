# -*- coding: utf-8 -*-
"""连接层并发写守卫（缺陷：load→改内存→save 无锁 + 固定临时名互踩）。

缺陷形态（缺陷报告 2026-09-25 复现证实，medium）：links 连接层全部变更
（handshake/observe/promote/degrade/isolate/withdraw/decay）是
load→改内存→save 的读-改-写，无跨进程锁；save 用固定临时名 p+".tmp"
（fsutil.py:6-8 明载的已实名反模式：两写者共享同一临时文件，后者截断
前者写了一半的内容）。并发下后写者整文件覆盖前写者——静默丢一方信任
更新（20/20 实证：终态一方 evidence_count=0），互踩 .tmp 产生交织内容
（audit 超单写者上限实拍）。

修复方向：save 改走 fsutil.atomic_write（mkstemp 唯一临时名 + 带短重试
rename）；各变更原语以 FileLock 为 load→mutate→save 全程加连接级互斥。

红守卫 = 缺陷报告 Barrier 对齐双线程复现（两线程都完成 load+mutate 后
在 save 点对齐同时落盘）：
  S1 observe×observe（不同连接）：双方都返回 ok 而终态一方 evidence_count
     丢失 = 静默丢更新（红）；audit 超上限/文件不可解析亦不得出现；
  S2 observe×degrade（跨原语家族）：同一读-改-写形态，两方效果都幸存。
对齐窗处理：barrier 超时（3s）短于 FileLock 超时（10s）——修复后另一
写者被连接锁挡在临界区外、barrier 自然超时Broken，捕获后照常落盘（无
死锁）；修复前双方都快速到达 save 点、barrier 正常放行 → 确定性竞态。
运行：python -m md_cg.test_links_concurrent_write
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading

from . import links

PASS = FAIL = 0
FAILS = []

BARRIER_TIMEOUT = 3.0     # < FileLock 默认 10s：锁化后对齐窗自然超时，不死锁


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def _race(p, calls):
    """双线程在 save 点 Barrier 对齐并发执行 calls 里的两个变更。

    calls: [(fn, kwargs), (fn, kwargs)]——fn 为 links 模块变更原语。
    返回 (两线程结果, 对齐是否达成)。对齐未达成（barrier 超时 Broken）
    属修复后预期形态，单独如实报告。
    """
    real_save = links.save
    barrier = threading.Barrier(2)
    aligned = {"hit": True}
    results = [None, None]

    def aligned_save(data, path=None):
        try:
            barrier.wait(timeout=BARRIER_TIMEOUT)
        except threading.BrokenBarrierError:
            aligned["hit"] = False   # 另一写者未到（被锁挡住）——修复后预期
        return real_save(data, path)

    def worker(i, fn, kw):
        try:
            results[i] = {"ok": fn(**kw).get("ok")}
        except Exception as exc:                    # noqa: BLE001
            results[i] = {"exc": f"{type(exc).__name__}: {exc}"}

    links.save = aligned_save
    try:
        ts = [threading.Thread(target=worker, args=(i, fn, kw))
              for i, (fn, kw) in enumerate(calls)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=60)
    finally:
        links.save = real_save
    return results, aligned["hit"]


def _seq_ref_audit_len(tmp):
    """单写者合法基线：同序列（handshake→observe）在无并发下顺序重放的
    audit 长度（本机实测 3：handshake + version_misaligned + observe——
    未声明版本会多记一条，故不得硬编码 2）。"""
    p = os.path.join(tmp, "ref", "_links.json")
    links.handshake("peerRef", path=p)
    links.observe("agent:peerRef", evidence="顺序基线", positive=True, path=p)
    return len(links.get("agent:peerRef", path=p)["audit"])


def _get_link(p, peer):
    data = links.load(p)
    for lk in (data.get("links") or {}).values():
        if lk.get("peer_node_id") == "agent:" + peer:
            return lk
    return None


def _scenario_observe_race(tmp):
    """S1：双线程并发 observe 不同连接——对齐在 save 点。"""
    print("== S1 observe×observe（save 点对齐） ==")
    p = os.path.join(tmp, "s1", "_links.json")
    links.handshake("peerA", path=p)
    links.handshake("peerB", path=p)

    results, aligned = _race(p, [
        (links.observe, {"peer": "agent:peerA", "evidence": "并发证据A",
                         "positive": True, "path": p}),
        (links.observe, {"peer": "agent:peerB", "evidence": "并发证据B",
                         "positive": True, "path": p}),
    ])
    ok(all(r and r.get("ok") for r in results),
       f"S1a 双方 observe 均成功无异常（实测 {results}）——静默丢更新的前提"
       f"是『返回 ok 但更新消失』")
    print(f"  ..   save 点对齐达成={aligned}（修复前应 True=真竞态；"
          f"修复后 False=另一写者被锁挡住，属预期）")

    la, lb = _get_link(p, "peerA"), _get_link(p, "peerB")
    ok(la is not None and lb is not None,
       "S1b 终态文件可解析且两条连接都在（无交织撕裂丢连接）")
    eca = (la or {}).get("evidence_count")
    ecb = (lb or {}).get("evidence_count")
    ok(eca == 1 and ecb == 1,
       f"S1c 无静默丢更新（peerA={eca}/peerB={ecb}，应 1/1——旧代码"
       f"后写者整文件覆盖前写者，一方恒 0）")
    ref = _seq_ref_audit_len(tmp)
    aa = len((la or {}).get("audit") or [])
    ab = len((lb or {}).get("audit") or [])
    ok(aa == ref and ab == ref,
       f"S1d audit 恰为单写者合法基线（A={aa}/B={ab}，顺序重放基线={ref}；"
       f"旧代码丢更新侧偏少、固定临时名互踩可超限——缺陷实拍 audit 超上限）")
    ok(not os.path.exists(p + ".tmp"),
       "S1e 固定临时名不再出现（改走 atomic_write 唯一临时名）")


def _scenario_cross_family(tmp):
    """S2：observe×degrade 跨原语家族（同一 load→mutate→save 形态）。"""
    print("== S2 observe×degrade（跨原语） ==")
    p = os.path.join(tmp, "s2", "_links.json")
    links.handshake("peerC", path=p)
    links.handshake("peerD", path=p)

    results, aligned = _race(p, [
        (links.observe, {"peer": "agent:peerC", "evidence": "并发证据C",
                         "positive": True, "path": p}),
        (links.degrade, {"peer": "agent:peerD", "reason": "并发降级守卫",
                         "path": p}),
    ])
    ok(all(r and r.get("ok") for r in results),
       f"S2a 双方均成功无异常（实测 {results}）")
    print(f"  ..   save 点对齐达成={aligned}")
    lc, ld = _get_link(p, "peerC"), _get_link(p, "peerD")
    ok(lc is not None and ld is not None, "S2b 两条连接都在（文件未撕裂）")
    ok((lc or {}).get("evidence_count") == 1
       and (ld or {}).get("status") == "degraded",
       f"S2c 两方效果都幸存（C.evidence_count="
       f"{(lc or {}).get('evidence_count')}，D.status="
       f"{(ld or {}).get('status')}——旧代码丢一方）")
    ok(not os.path.exists(p + ".tmp"), "S2d 固定临时名不再出现")


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_links_race_")
    try:
        _scenario_observe_race(tmp)
        _scenario_cross_family(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
