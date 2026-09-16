# -*- coding: utf-8 -*-
"""审计日志分片轮转验证（治本：给无上界增长装上界）。

背景（第 4 条取证，2026-09-16）：审计日志无上界增长——实测 ~2 条/s 持续写入、
累计 ~21.5 M 条 / 4.0 GB，且单文件形态使任何「读它」的操作随运行时长线性劣化。
上一轮把**体检读数**降为 O(1) 元数据口径（_log_scale），只让「指标与代价错配」
不再显形；**有界性的来源是轮转**：单文件 ≤ AUDIT_ROTATE_BYTES、分片数 ≤
AUDIT_KEEP_SHARDS ⇒ 单片读取代价与总量都有上界。

断言面：
  ① 未达阈值不轮转（不产生空转切分）
  ② 达阈值切分：产生归档分片、活动文件被重建
  ③ 切分无损：轮转前记录序列是轮转后序列的前缀（rename 不动字节）
  ④ 轮转自述留痕（首条新记录 op=audit_rotate，不静默）
  ⑤ audit_scale 聚合口径 == 全量写入条数（分片走索引 + 活动实时）
  ⑥ audit_records 跨分片按时间序合并 / limit 取尾部
  ⑦ 保留策略：超 keep 淘汰最旧分片且索引同步
  ⑧ health_os 透出轮转面（shards/total_bytes/total_exact）
  ⑨ 可关闭：ROTATE_BYTES=0 → 不切分（退回无上界，供对照/应急）
  ⑩ 超大历史分片分档读数：exact=False 且**零全量计数**（O(n) 守卫——否则刚修好的
     「一次调用堵死通道」会在轮转路径上原样复现）
  ⑪ 稳态 O(1)：二次 audit_scale 不重数分片（索引缓存生效）
  ⑫ 归档目录不在 LAYERS → 不参与节点索引

运行：python -m md_cg.test_audit_rotate
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import mdcos as mdcos_mod
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


class _Spy:
    """记录 mdcos 模块级 count_jsonl / read_jsonl 的调用路径（O(n) 守卫）。"""

    def __enter__(self):
        self.read, self.count = [], []
        self._read, self._count = mdcos_mod.read_jsonl, mdcos_mod.count_jsonl
        spy = self

        def _r(p, *a, **k):
            spy.read.append(p)
            return spy._read(p, *a, **k)

        def _c(p, *a, **k):
            spy.count.append(p)
            return spy._count(p, *a, **k)

        mdcos_mod.read_jsonl, mdcos_mod.count_jsonl = _r, _c
        return self

    def __exit__(self, *exc):
        mdcos_mod.read_jsonl, mdcos_mod.count_jsonl = self._read, self._count
        return False


def _mk(tmp, name, rotate=2048, keep=8, probe=1, count_max=None):
    root = os.path.join(tmp, name)
    os.makedirs(root, exist_ok=True)
    cg = MdCGOS(root)
    cg.AUDIT_ROTATE_BYTES = rotate
    cg.AUDIT_KEEP_SHARDS = keep
    cg.AUDIT_PROBE_EVERY = probe
    if count_max is not None:
        cg.AUDIT_COUNT_MAX_BYTES = count_max
    return cg


def _fill(cg, n, tag="x"):
    for i in range(n):
        cg._audit("add", "node_%s_%d" % (tag, i), pad="z" * 160)


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_rotate_")
    try:
        # ================= A：基本轮转 + 无损 + 聚合 + 尾部读 =================
        cg = _mk(tmp, "a", rotate=(1 << 30))       # 先给超大阈值 → 不轮转
        _fill(cg, 20, "p")

        # ---------- ① 未达阈值不轮转 ----------
        ok(not cg._audit_shards(),
           "①未达阈值 → 零分片（无空转切分）")
        ok(os.path.getsize(cg.audit_log) > 0 and len(cg.audit_records()) == 20,
           "①b活动文件承载全部记录（20 条），不提前分片")

        before = [r.get("id") for r in cg.audit_records()]

        # ---------- ② 达阈值切分 ----------
        cg.AUDIT_ROTATE_BYTES = 2048
        _fill(cg, 20, "q")
        shards = cg._audit_shards()
        ok(len(shards) >= 1,
           "②达阈值 → 产生归档分片（%s）" % (shards or "无"))
        ok(all(n.startswith("_audit.") and n.endswith(".jsonl") for n in shards),
           "②b分片命名规范（_audit.<6位序号>.jsonl，字典序==时间序）")
        ok(os.path.exists(cg.audit_log),
           "②c活动文件被重建（最新记录始终在 _audit.jsonl，读尾调用方不受影响）")

        # ---------- ③ 切分无损 ----------
        after = cg.audit_records()
        ids = [r.get("id") for r in after if r.get("op") != "audit_rotate"]
        ok(ids[:len(before)] == before,
           "③轮转不丢记录：轮转前序列是轮转后序列的前缀（%d→%d 条）"
           % (len(before), len(after)))
        ok(len(after) == len(before) + 20 + len([r for r in after
                                                 if r.get("op") == "audit_rotate"]),
           "③b条数守恒：轮转前 %d + 新增 20 + 自述 %d == %d"
           % (len(before), len([r for r in after if r.get("op") == "audit_rotate"]),
              len(after)))

        # ---------- ④ 自述留痕 ----------
        marks = [r for r in after if r.get("op") == "audit_rotate"]
        ok(bool(marks) and marks[0].get("id") in shards,
           "④轮转自述留痕（op=audit_rotate，id 指向分片名，不静默）")

        # ---------- ⑤ 聚合口径 ----------
        sc = cg.audit_scale()
        ok(sc["total_events"] == len(after) and sc["total_exact"] is True,
           "⑤audit_scale 聚合 == 全量写入条数（%s vs %d），且标注精确"
           % (sc["total_events"], len(after)))
        ok(sc["shards"] == len(shards) and sc["oversized"] == 0,
           "⑤b分片计数 + 零超大分片（阈值内分片走精确计数）")
        ok(sc["total_bytes"] == sc["bytes"] + sc["shard_bytes"],
           "⑤c总量字节 = 活动 + 分片（%d = %d + %d）"
           % (sc["total_bytes"], sc["bytes"], sc["shard_bytes"]))
        ok(sc["rotate_bytes"] == 2048 and sc["keep_shards"] == 8,
           "⑤d读数透出轮转参数（有界性可观测，不用猜配置）")

        # ---------- ⑥ 跨分片合并 / limit 尾部读 ----------
        tail = cg.audit_records(limit=3)
        ok(len(tail) == 3 and [r.get("id") for r in tail]
           == [r.get("id") for r in after[-3:]],
           "⑥limit=3 取尾部 3 条（巡检不必把有界日志读成全量）")

        # ---------- ⑧ health_os 透出轮转面 ----------
        o = cg.health_os()["os"]
        ok(o["audit_shards"] == len(shards) and o["audit_total_exact"] is True
           and o["audit_total_bytes"] == sc["total_bytes"],
           "⑧health_os 透出轮转面（shards/total_bytes/total_exact）")

        # ---------- ⑪ 稳态 O(1)：索引缓存生效 ----------
        # 口径：守的是「分片不被重数」（分片走索引缓存）；活动文件的精确计数是
        # **有界**代价（size ≤ AUDIT_ROTATE_BYTES），属设计内。
        with _Spy() as spy:
            sc2 = cg.audit_scale()
        ok(not any(os.path.basename(p) in shards for p in spy.count),
           "⑪二次 audit_scale 未重数任何分片（走索引缓存）[count=%s]" % spy.count)
        ok(sc2["total_events"] == sc["total_events"],
           "⑪b稳态读数一致（%s == %s），缓存不改变结论"
           % (sc2["total_events"], sc["total_events"]))

        # ---------- ⑫ 归档目录不参与节点索引 ----------
        ok(not any("_audit" in k for k in cg.index["nodes"]),
           "⑫归档目录不在 LAYERS → 分片不参与节点索引（检索面零污染）")

        cg.close()

        # ================= B：保留策略（淘汰最旧分片） =================
        cgb = _mk(tmp, "b", rotate=2048, keep=2)
        _fill(cgb, 60, "b")
        sb = cgb._audit_shards()
        ok(len(sb) == 2,
           "⑦分片数受 keep 约束（保留最近 2 片，实际 %d）" % len(sb))
        pruned = [r for r in cgb.audit_records() if r.get("op") == "audit_rotate"
                  and r.get("pruned")]
        ok(bool(pruned) and len(pruned[0]["pruned"]) >= 1,
           "⑦b淘汰非静默：pruned 名单写进审计（%s）"
           % (pruned[0]["pruned"] if pruned else "无"))
        idx = cgb._load_audit_index()
        ok(all(n in idx for n in sb) and all(n in sb for n in idx),
           "⑦c索引与磁盘分片对齐（淘汰即摘索引，不留悬空项）")
        cgb.close()

        # ================= C：可关闭（退回无上界） =================
        cgc = _mk(tmp, "c", rotate=0)
        _fill(cgc, 40, "c")
        ok(not cgc._audit_shards() and os.path.getsize(cgc.audit_log) > 0,
           "⑨ROTATE_BYTES=0 → 不切分（应急/对照可退回无上界形态）")
        cgc.close()

        # ================= D：超大历史分片分档（O(n) 守卫） =================
        cgd = _mk(tmp, "d", rotate=2048, keep=8, count_max=512)
        _fill(cgd, 20, "d")
        sd = cgd._audit_shards()
        ok(bool(sd), "⑩超大分档前置：至少产生 1 个分片（%s）" % (sd or "无"))
        with _Spy() as spy:
            scd = cgd.audit_scale()
        ok(scd["oversized"] >= 1 and scd["total_exact"] is False,
           "⑩b历史超大分片 → oversized=%d、total_exact=False（不假装精确）"
           % scd["oversized"])
        ok(not any(os.path.basename(p) in sd for p in spy.count),
           "⑩c超大分片零全量计数（走 _log_scale 元数据口径）——"
           "否则「一次调用堵死通道」会在轮转路径上复现")
        cgd.close()

        # ================= E：真实规模（~113 MB 活动文件）轮转不得全量解析 =====
        # 这是「4.0 GB 历史日志」场景的等价缩小版：轮转必须只做 rename（O(1)），
        # 绝不能在写路径上解析整个文件——否则刚修好的「通道被堵死」原样复现。
        import json as _json
        import time as _time

        cge = _mk(tmp, "e", rotate=64 << 20, keep=8, probe=1)
        line = _json.dumps({"t": 1.0, "op": "add", "id": "bulk",
                            "pad": "z" * 200}) + "\n"
        with open(cge.audit_log, "w", encoding="utf-8") as f:
            for _ in range(70):                 # 70 × ~1.6 MB ≈ 113 MB
                f.write(line * 7000)
        size_bulk = os.path.getsize(cge.audit_log)
        rss0 = None
        try:
            import psutil
            rss0 = psutil.Process(os.getpid()).memory_info().rss
        except Exception:                       # noqa: BLE001 —— 无 psutil 则不假装
            pass
        t0 = _time.time()
        cge._audit("add", "after_bulk")         # 探测到超阈值 → 触发轮转
        rotate_dt = _time.time() - t0
        ok(rotate_dt < 5.0,
           "⑬超大活动文件（%.0f MB）轮转在秒级完成（%.2fs）——rename O(1)，"
           "写路径不解析全量" % (size_bulk / 1048576.0, rotate_dt))
        se = cge._audit_shards()
        idxe = cge._load_audit_index()
        ok(len(se) == 1 and idxe[se[0]]["bytes"] == size_bulk,
           "⑬b超大分片登记字节 == 轮转前大小（%d），内容未重写"
           % size_bulk)
        ok(idxe[se[0]]["exact"] is False,
           "⑬c超大分片条数走元数据口径（exact=False，不假装精确）")
        t1 = _time.time()
        sce = cge.audit_scale()
        scale_dt = _time.time() - t1
        ok(sce["oversized"] == 1 and sce["total_bytes"] >= size_bulk,
           "⑬d体检识别 oversized=%d、总量 %.0f MB（历史分片仍在总量核算内）"
           % (sce["oversized"], sce["total_bytes"] / 1048576.0))
        if rss0 is not None:
            import psutil
            rss_delta = psutil.Process(os.getpid()).memory_info().rss - rss0
            ok(rss_delta < (300 << 20) and scale_dt < 2.0,
               "⑬e轮转+体检 RSS 增量 %.0f MB < 300 MB、体检 %.2fs —— 不物化不阻塞"
               % (rss_delta / 1048576.0, scale_dt))
        cge.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\naudit_rotate: {PASS} pass / {FAIL} fail")
    if FAILS:
        for f in FAILS:
            print(f" - {f}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
