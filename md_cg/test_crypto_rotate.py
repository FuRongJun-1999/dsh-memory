# -*- coding: utf-8 -*-
"""`_crypto.jsonl` 审计分片轮转验证（A2：把无上界增长装上界，与 `_audit` 共用共享件）。

背景（第 4 条取证，2026-10-10）：`crypto.audit()` 此前是「直接 `append_jsonl` +
`except OSError: pass`」——**无阈值 / 无归档 / 无索引 / 无淘汰 / 无体检 / 失败静默**，
在役库实测 `_crypto.jsonl` 682 MB / 302 万条且无 `_crypto_archive/`。本件守卫 A2 的
crypto 侧口径，逐条对齐 `test_audit_rotate.py` 的既有 12 条（机制同源
`md_cg.rotate.Rotator`），并补两条本侧特有面：
  ⑬ `_crypto_archive/` 不在 `LAYERS`（md_cg/mdcg.py 顶层常量）⇒ 不参与节点索引；
  ⑭ N126：审计写失败**开口告警**（不再 `except OSError: pass` 静默）。

断言面：
  ① 未达阈值不轮转（不产生空转切分）
  ② 达阈值切分：产生归档分片（`_crypto.<6位序号>.jsonl`）、活动文件被重建
  ③ 切分无损：轮转前序列是轮转后序列的前缀；分片字节 == 轮转前活动文件字节
  ④ 轮转自述留痕（op=crypto_rotate，不静默）
  ⑤ audit_scale 聚合口径 == 全量写入条数（分片走索引 + 活动实时）
  ⑥ audit_records 跨分片按时间序合并 / limit 取尾部
  ⑦ 保留策略：超 keep 淘汰最旧分片且索引同步（pruned 名单进自述）
  ⑧ audit_scale 透出轮转参数（rotate_bytes/keep_shards/shards/total_bytes）
  ⑨ 可关闭：CRYPTO_ROTATE_BYTES=0 → 不切分（退回无上界，供对照/应急）
  ⑩ 超大历史分片分档：exact=False 且**零全量计数**（O(n) 守卫）
  ⑪ 稳态 O(1)：二次 audit_scale 不重数分片（索引缓存生效）
  ⑫ 归档目录不在 LAYERS → 不参与节点索引
  ⑭ 写失败开口告警（N126）

运行：python -m md_cg.test_crypto_rotate
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import tempfile

from . import crypto
from . import rotate as rotate_mod
from .mdcg import LAYERS

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
    """记录 rotate 模块级 count_jsonl 的调用路径（O(n) 守卫）。"""

    def __enter__(self):
        self.count = []
        self._count = rotate_mod.count_jsonl
        spy = self

        def _c(p, *a, **k):
            spy.count.append(p)
            return spy._count(p, *a, **k)

        rotate_mod.count_jsonl = _c
        return self

    def __exit__(self, *exc):
        rotate_mod.count_jsonl = self._count
        return False


def _mk(tmp, name, rotate=2048, keep=8, probe=1, count_max=None):
    root = os.path.join(tmp, name)
    os.makedirs(root, exist_ok=True)
    crypto.CRYPTO_ROTATE_BYTES = rotate
    crypto.CRYPTO_KEEP_SHARDS = keep
    crypto.CRYPTO_PROBE_EVERY = probe
    if count_max is not None:
        crypto.CRYPTO_COUNT_MAX_BYTES = count_max
    return root


def _fill(root, n, tag="x"):
    for i in range(n):
        crypto.audit(root, {"op": "add", "node_id": "node_%s_%d" % (tag, i),
                            "pad": "z" * 160})


def _shards(root):
    return crypto._rotator(root).shards()


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_crypto_rotate_")
    saved = (crypto.CRYPTO_ROTATE_BYTES, crypto.CRYPTO_KEEP_SHARDS,
             crypto.CRYPTO_PROBE_EVERY, crypto.CRYPTO_COUNT_MAX_BYTES)
    try:
        # ================= A：基本轮转 + 无损 + 聚合 + 尾部读 =================
        root = _mk(tmp, "a", rotate=(1 << 30))     # 先给超大阈值 → 不轮转
        _fill(root, 20, "p")
        active = os.path.join(root, crypto.AUDIT_FILE)

        # ---------- ① 未达阈值不轮转 ----------
        ok(not _shards(root),
           "①未达阈值 → 零分片（无空转切分）")
        ok(os.path.getsize(active) > 0 and len(crypto.audit_records(root)) == 20,
           "①b活动文件承载全部记录（20 条），不提前分片")

        before = [r.get("node_id") for r in crypto.audit_records(root)]

        # ---------- ② 达阈值切分 ----------
        crypto.CRYPTO_ROTATE_BYTES = 2048
        raw_before = open(active, "rb").read()
        _fill(root, 20, "q")
        shards = _shards(root)
        ok(len(shards) >= 1,
           "②达阈值 → 产生归档分片（%s）" % (shards or "无"))
        ok(all(n.startswith("_crypto.") and n.endswith(".jsonl")
               for n in shards),
           "②b分片命名规范（_crypto.<6位序号>.jsonl，字典序==时间序）")
        ok(os.path.exists(active),
           "②c活动文件被重建（最新记录始终在 _crypto.jsonl）")

        # ---------- ③ 切分无损（序列前缀 + 分片字节 == 轮转前活动字节） ----------
        after = crypto.audit_records(root)
        ids = [r.get("node_id") for r in after
               if r.get("op") != "crypto_rotate"]
        ok(ids[:len(before)] == before,
           "③轮转不丢记录：轮转前序列是轮转后序列的前缀（%d→%d 条）"
           % (len(before), len(after)))
        marks = [r for r in after if r.get("op") == "crypto_rotate"]
        ok(len(after) == len(before) + 20 + len(marks),
           "③b条数守恒：轮转前 %d + 新增 20 + 自述 %d == %d"
           % (len(before), len(marks), len(after)))
        newest = os.path.join(crypto._rotator(root).archive, shards[0])
        with open(newest, "rb") as f:
            shard_bytes = f.read()
        ok(shard_bytes == raw_before,
           "③c首片字节 == 轮转前活动文件字节（%d B，rename 不动字节——"
           "共享件切分非重写）" % len(shard_bytes))

        # ---------- ④ 自述留痕 ----------
        ok(bool(marks) and marks[0].get("node_id") in shards,
           "④轮转自述留痕（op=crypto_rotate，node_id 指向分片名，不静默）")

        # ---------- ⑤ 聚合口径 ----------
        sc = crypto.audit_scale(root)
        ok(sc["total_events"] == len(after) and sc["total_exact"] is True,
           "⑤audit_scale 聚合 == 全量写入条数（%s vs %d），且标注精确"
           % (sc["total_events"], len(after)))
        ok(sc["shards"] == len(shards) and sc["oversized"] == 0,
           "⑤b分片计数 + 零超大分片")
        ok(sc["total_bytes"] == sc["bytes"] + sc["shard_bytes"],
           "⑤c总量字节 = 活动 + 分片（%d = %d + %d）"
           % (sc["total_bytes"], sc["bytes"], sc["shard_bytes"]))
        ok(sc["rotate_bytes"] == 2048 and sc["keep_shards"] == 8,
           "⑤d读数透出轮转参数（有界性可观测，不用猜配置）")

        # ---------- ⑥ 跨分片合并 / limit 尾部读 ----------
        tail = crypto.audit_records(root, limit=3)
        ok(len(tail) == 3
           and [r.get("node_id") for r in tail]
           == [r.get("node_id") for r in after[-3:]],
           "⑥limit=3 取尾部 3 条（巡检不必把有界日志读成全量）")

        # ---------- ⑪ 稳态 O(1)：索引缓存生效 ----------
        with _Spy() as spy:
            sc2 = crypto.audit_scale(root)
        ok(not any(os.path.basename(p) in shards for p in spy.count),
           "⑪二次 audit_scale 未重数任何分片（走索引缓存）[count=%s]"
           % spy.count)
        ok(sc2["total_events"] == sc["total_events"],
           "⑪b稳态读数一致（%s == %s）"
           % (sc2["total_events"], sc["total_events"]))

        # ---------- 保留策略（淘汰最旧分片） ----------
        rootb = _mk(tmp, "b", rotate=2048, keep=2)
        _fill(rootb, 60, "b")
        sb = _shards(rootb)
        ok(len(sb) == 2,
           "⑦分片数受 keep 约束（保留最近 2 片，实际 %d）" % len(sb))
        pruned = [r for r in crypto.audit_records(rootb)
                  if r.get("op") == "crypto_rotate" and r.get("pruned")]
        ok(bool(pruned) and len(pruned[0]["pruned"]) >= 1,
           "⑦b淘汰非静默：pruned 名单写进审计（%s）"
           % (pruned[0]["pruned"] if pruned else "无"))
        idx = crypto._rotator(rootb).load_index()
        ok(all(n in idx for n in sb) and all(n in sb for n in idx),
           "⑦c索引与磁盘分片对齐（淘汰即摘索引，不留悬空项）")

        # ---------- ⑨ 可关闭（退回无上界） ----------
        rootc = _mk(tmp, "c", rotate=0)
        _fill(rootc, 40, "c")
        ok(not _shards(rootc)
           and os.path.getsize(os.path.join(rootc, crypto.AUDIT_FILE)) > 0,
           "⑨CRYPTO_ROTATE_BYTES=0 → 不切分（应急/对照可退回无上界形态）")

        # ---------- ⑩ 超大历史分片分档（O(n) 守卫） ----------
        rootd = _mk(tmp, "d", rotate=2048, keep=8, count_max=512)
        _fill(rootd, 20, "d")
        sd = _shards(rootd)
        ok(bool(sd), "⑩超大分档前置：至少产生 1 个分片（%s）" % (sd or "无"))
        with _Spy() as spy:
            scd = crypto.audit_scale(rootd)
        ok(scd["oversized"] >= 1 and scd["total_exact"] is False,
           "⑩b历史超大分片 → oversized=%d、total_exact=False（不假装精确）"
           % scd["oversized"])
        ok(not any(os.path.basename(p) in sd for p in spy.count),
           "⑩c超大分片零全量计数（走旋转件 log_scale 元数据口径）")

        # ---------- ⑫ 归档目录不在 LAYERS ----------
        ok(crypto.CRYPTO_ARCHIVE not in LAYERS
           and not any("_crypto" in L for L in LAYERS),
           "⑫归档目录 _crypto_archive 不在 LAYERS → 分片不参与节点索引")

        # ---------- ⑭ N126：写失败开口告警（不再静默） ----------
        # 本条只考「append 失败不静默」，故**必须让轮转闸门不介入**：Linux 上
        # `os.path.getsize(目录)` = 4096（Windows = 0），若阈值 ≤4096 会先走轮转
        # 路径——`Rotator.rotate` 的 `publish` 是 `os.replace`，在 POSIX 上能把该
        # 同名**目录**整个 rename 进归档，随后 append 到重建的空文件反而成功
        # ⇒ 计数不增、归档被建，两条断言全失真（2026-10-10 容器实测复现）。
        # 阈值取 1<<30（远高于两平台的目录 getsize）⇒ 两平台都不触发轮转。
        roote = _mk(tmp, "e", rotate=(1 << 30))
        active_e = os.path.join(roote, crypto.AUDIT_FILE)
        os.remove(active_e) if os.path.exists(active_e) else None
        os.makedirs(active_e)                    # 同名目录顶位 → append 必失败
        ok(os.path.getsize(active_e) < crypto.CRYPTO_ROTATE_BYTES,
           "⑭前置：同名目录 size(%d) < 轮转阈值(%d) ⇒ 不触发轮转（Linux 目录"
           " getsize=4096 / Windows=0，阈值须高于二者，否则目录被 rename 进归档）"
           % (os.path.getsize(active_e), crypto.CRYPTO_ROTATE_BYTES))
        n0 = crypto._AUDIT_WRITE_FAILURES
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            crypto.audit(roote, {"op": "add", "node_id": "boom"})   # 不抛
        ok(crypto._AUDIT_WRITE_FAILURES == n0 + 1 and "审计写入失败" in err.getvalue(),
           "⑭写失败不静默：计数 +1（%d→%d）且 stderr 有告警（N126）"
           % (n0, crypto._AUDIT_WRITE_FAILURES))
        ok(os.path.isdir(active_e) and not os.path.exists(
               os.path.join(roote, crypto.CRYPTO_ARCHIVE)),
           "⑭b写失败不阻断、不伪造成功（best-effort：同名目录原样在，未误建归档）")
    finally:
        (crypto.CRYPTO_ROTATE_BYTES, crypto.CRYPTO_KEEP_SHARDS,
         crypto.CRYPTO_PROBE_EVERY, crypto.CRYPTO_COUNT_MAX_BYTES) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\ncrypto_rotate: {PASS} pass / {FAIL} fail")
    if FAILS:
        for f in FAILS:
            print(f" - {f}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()