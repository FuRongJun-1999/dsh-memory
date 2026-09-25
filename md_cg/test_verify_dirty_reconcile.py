# -*- coding: utf-8 -*-
"""verify() 直写分支索引对账守卫（缺陷：confirmed/weakened 直写盘后不置 _dirty）。

缺陷形态（缺陷报告 2026-09-25 复现证实，medium）：verify() 的
confirmed/weakened 直写分支（mdcg.py:3166-3170）`_write_node` 落盘后只原地改
index 条目 `evidence_count`，不置 `self._dirty[node_id]`。当节点已在目标验证态
（verified→verified / doubted→doubted）时，尾部 set_verification 走 stamp
noop 提前返回（trust.py:192-193 / 695-696，不写盘、不调 _sync_index）——
本次写盘对索引增量日志（_dirty → flush → _index_log 重放）完全不可见：

  ① 重开后索引 evidence_count 与盘面漂移（forgetting.py:358、
     scrub.py:181/582/716、metacognition.py:176/193 均按索引条目
     evidence_count 决策）——计数对账只对账 .md 数量（compact_index
     :1003），内容级改写不触发重扫；
  ② readcache 代际（_DirtyDict.write_gen）不推进 → 同实例 _read 命中旧
     frontmatter（缓存视图 vs 盘上真值不一致）。

复现形态（与缺陷报告一致的三段会话）：S1 预置验证态并 close 落快照 →
S2 noop 形态 verify（已在目标验证态）→ S3 重开对账索引与盘面。

修复：直写分支落盘并原地更新条目后显式 `self._dirty[node_id] = e`
（与 mdcg.py 边域同步 :1664 / goal 状态 :1902 同款口径）。

红项 = V3-V6（代际推进 / 标脏 / 缓存视图 / 重开对账）；V1/V2 锁语义不变
（noop 幂等、返回载荷形态不变）。
运行：python -m md_cg.test_verify_dirty_reconcile
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

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


def _disk_fm(root, nid):
    """盘上真值直读（新实例首触 = 磁盘当前内容）。"""
    cg = MdCGOS(root)
    e = (cg.index.get("nodes") or {}).get(nid)
    if not e:
        return None, None
    fn = getattr(cg, "_read_uncached", None) or cg._read
    fm, content = fn(e)
    cg.close()
    return fm, content


def _noop_session(root, nid, verdict, label, want_conf):
    """S2：节点已在目标验证态 → verify 的 set_verification 为 noop 直写分支。"""
    cg = MdCGOS(root)
    entry = cg.index["nodes"][nid]
    cg._read(entry)                         # 检索装载缓存（生产形态）
    g0 = cg._dirty.write_gen

    r = cg.verify(nid, f"{label}的外部证据", verdict)
    ok(r["action"] == verdict,
       f"{label}1 verify 返回 action={verdict}")
    ok(r["verification"].get("code") == "noop"
       and r["verification"].get("changed") is False,
       f"{label}2 已在目标验证态 → 幂等 noop（语义不变，不写验证态）")

    ok(cg._dirty.write_gen > g0,
       f"{label}3 写代际推进（write_gen {g0}→{cg._dirty.write_gen}）")
    ok(nid in cg._dirty,
       f"{label}4 直写分支已标脏（_dirty 含 {nid} → flush 落增量日志）")
    fm_cached, _ = cg._read(entry)          # 缓存视图
    ok(fm_cached.get("evidence_count") == 1,
       f"{label}5 同实例缓存视图不陈旧（evidence_count="
       f"{fm_cached.get('evidence_count')}，应 1）")
    cg.close()

    # S3：重开对账——索引条目与盘面一致
    cg2 = MdCGOS(root)
    idx = (cg2.index.get("nodes") or {}).get(nid) or {}
    fm_disk, _ = _disk_fm(root, nid)
    ok(idx.get("evidence_count") == 1 and fm_disk.get("evidence_count") == 1,
       f"{label}6 重开后索引与盘面对账一致（索引 {idx.get('evidence_count')}"
       f" / 盘面 {fm_disk.get('evidence_count')}，应均为 1）")
    ok(fm_disk.get("confidence") == want_conf,
       f"{label}7 盘面置信度正确（{want_conf}）")
    cg2.close()


def _confirmed_shape(tmp):
    """confirmed 复现（缺陷报告原样：先 set_verification(verified) 再 noop verify）。"""
    root = os.path.join(tmp, "cf")
    os.makedirs(root)
    # S1：预置验证态并 close 落快照（此后 noop 会话走 compact 而非 rebuild）
    cg1 = MdCGOS(root)
    cg1.add("n1", "# 功能名：对账守卫\n\n正文。\n", layer="knowledge")
    cg1.flush()
    r0 = cg1.set_verification("n1", "verified", reason="守卫预置",
                              actor="guard")
    ok(r0.get("ok") and r0.get("changed"),
       "cf0 S1 预置 verified（unverified→verified 非 noop）")
    cg1.close()
    _noop_session(root, "n1", "confirmed", "cf", 0.65)
    fm, _ = _disk_fm(root, "n1")
    ok(fm.get("verification_state") == "verified",
       "cf8 盘面验证态保持 verified（noop 未改态）")


def _weakened_shape(tmp):
    """weakened 复现：doubted→doubted 同为 noop 直写分支（置信度不触降级）。"""
    root = os.path.join(tmp, "wk")
    os.makedirs(root)
    cg1 = MdCGOS(root)
    cg1.add("n2", "# 功能名：对账守卫二\n\n正文。\n", layer="knowledge",
            confidence=0.9)
    cg1.flush()
    r0 = cg1.set_verification("n2", "doubted", reason="守卫预置",
                              actor="guard")
    ok(r0.get("ok") and r0.get("changed"),
       "wk0 S1 预置 doubted（unverified→doubted 非 noop）")
    cg1.close()
    _noop_session(root, "n2", "weakened", "wk", 0.75)   # 0.9−0.15
    fm, _ = _disk_fm(root, "n2")
    ok(fm.get("layer") == "knowledge" and fm.get("verification_state") == "doubted",
       "wk8 未误降级（0.75 > DEMOTE_CONFIDENCE 0.2）且态保持 doubted")


def main():
    os.environ.pop("MDCG_READ_CACHE", None)
    tmp = tempfile.mkdtemp(prefix="mdcg_verify_dirty_")
    try:
        _confirmed_shape(tmp)
        _weakened_shape(tmp)
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
