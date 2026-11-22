# -*- coding: utf-8 -*-
"""issue #1011 四条并发一致性守卫（确定性，不依赖真实竞态时序）。

每条都**直接构造**故障现场：

G1  落盘窗口内重载必须让路——否则覆写写入被永久回退（_index_signature 排除本进程分片 ⇒ 不自愈）
G2  回填不得把「窗口内已被新写入覆盖」的 id 标陈旧——否则下次 flush 连新版本一起丢
G3  重载若已越过让路点，必须把「在飞批次」叠回去
G4  compact 拿不到锁就跳过，不得静默继续 clear 分片

跑法：python -X utf8 -m md_cg.test_issue1011_concurrency_guards
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcos import MdCGOS

_ok = 0
_bad = 0


def ok(cond, label, detail=""):
    global _ok, _bad
    if cond:
        _ok += 1
        print("  [PASS] %s" % label)
    else:
        _bad += 1
        print("  [FAIL] %s  %s" % (label, detail))


def _fresh(tag):
    root = tempfile.mkdtemp(prefix="i1011_%s_" % tag)
    return MdCGOS(root, actor="designer"), root


def g1_reload_yields_to_flush_window():
    """落盘窗口内调用 _maybe_reload_index 必须返回 False 且不改内存索引。"""
    cg, _root = _fresh("g1")
    cg.add("seed_1", "v1 正文", tags=["v1"], importance=0.4, layer="knowledge")
    cg.flush()
    cg.add("seed_1", "v2 正文", tags=["v2_updated"], importance=0.6, layer="knowledge",
           override=True)
    # 构造「盘面仍是旧值」的读面：不靠真实 IO 时序，直接给 _load_index 一份旧快照。
    _disk_old = {"schema": cg.index.get("schema"),
                 "nodes": {"seed_1": {"id": "seed_1", "content": "v1 正文",
                                       "tags": ["v1"], "bucket": None}},
                 "buckets": {}}
    _orig = cg._load_index
    cg._load_index = lambda: {"schema": _disk_old["schema"],
                              "nodes": dict(_disk_old["nodes"]), "buckets": {}}
    cg._index_sig = None             # 构造签名变化（否则根本不会进重载分支）
    try:
        # ① 窗口内：必须让路
        cg._flush_window = True
        cg._flush_inflight = {"seed_1": cg.index["nodes"].get("seed_1")}
        try:
            reloaded = cg._maybe_reload_index()
        finally:
            cg._flush_window = False
            cg._flush_inflight = {}
        entry = cg.index["nodes"].get("seed_1") or {}
        ok(reloaded is False, "G1a 窗口内重载让路（返回 False）", repr(reloaded))
        ok("v2_updated" in (entry.get("tags") or []),
           "G1b 窗口内存活：内存索引仍是覆写后的新值", repr(entry.get("tags")))
        # ② 变异对照：把两道机制都摘掉（无窗口位、无在飞批次、脏集为空）后再重载——
        #    同一步必须**真的**退回盘面旧值。否则前两条就是空过。
        cg._index_sig = None
        with cg._dirty_lock:
            cg._dirty.clear()          # 构造：窗口里 _dirty 已被清空
        cg._flush_inflight = {}        # 构造：没有在飞批次可叠
        reloaded2 = cg._maybe_reload_index()
        entry2 = cg.index["nodes"].get("seed_1") or {}
        ok(reloaded2 is True and "v1" in (entry2.get("tags") or [])
           and "v2_updated" not in (entry2.get("tags") or []),
           "G1c 变异对照：无让路位+无在飞批次时确实回退旧值",
           "%r / %r" % (reloaded2, entry2.get("tags")))
    finally:
        cg._load_index = _orig


def g2_rollback_keeps_newer_version():
    """flush 失败回填：同一 id 若已有新版本在脏集里，不得再标陈旧。"""
    cg, _root = _fresh("g2")
    cg.add("seed_2", "v1", tags=["v1"], importance=0.4, layer="knowledge")
    cg.flush()
    cg.add("seed_2", "v2", tags=["v2"], importance=0.6, layer="knowledge", override=True)
    with cg._dirty_lock:
        cg._dirty.superseded_ids.add("seed_2")

    def _boom(batch, superseded):
        # 构造**真正的窗口内新写入**：落盘进行中，同一 id 又进了新版本，然后失败。
        with cg._dirty_lock:
            cg._dirty["seed_2"] = {"id": "seed_2", "content": "v3 窗口内新版本"}
        raise OSError("注入：落盘失败")

    _orig = cg._flush_batch
    cg._flush_batch = _boom
    try:
        cg.flush()
    except OSError:
        pass
    finally:
        cg._flush_batch = _orig
    ok("seed_2" not in set(cg._dirty.superseded_ids),
       "G2 回填不把「窗口内已有新版本」的 id 标陈旧", repr(set(cg._dirty.superseded_ids)))
    ok((cg._dirty.get("seed_2") or {}).get("content") == "v3 窗口内新版本",
       "G2b 窗口内的新版本不被旧批次覆盖", repr((cg._dirty.get("seed_2") or {}).get("content")))
    ok(cg._flush_window is False, "G2c 异常路径也关闭落盘窗口")


def g3_reload_replays_inflight():
    """重载越过让路点时，在飞批次必须叠回内存索引。"""
    cg, root = _fresh("g3")
    cg.add("seed_3", "盘面旧值", tags=["disk_old"], layer="knowledge")
    cg.flush()
    idx = cg._load_index()
    ok("seed_3" in idx["nodes"], "G3a 前置：盘面已有该节点")
    # 构造：该节点被本进程覆写并已从脏集摘走（在飞），盘面仍是旧值
    cg._flush_inflight = {"seed_3": {"id": "seed_3", "content": "新值在飞",
                                      "tags": ["inflight_new"], "bucket": None}}
    cg.index["nodes"].pop("seed_3", None)
    _orig = cg._load_index
    cg._load_index = lambda: {"schema": cg.index.get("schema"), "nodes": dict(idx["nodes"]),
                              "buckets": {}}
    cg._index_sig = None             # 构造签名变化
    try:
        cg._maybe_reload_index()
    finally:
        cg._load_index = _orig
        cg._flush_inflight = {}
    e = cg.index["nodes"].get("seed_3") or {}
    ok("inflight_new" in (e.get("tags") or []),
       "G3b 在飞批次已叠回（不回退成盘面旧值）", repr(e.get("tags")))


def g4_compact_skips_without_lock():
    """拿不到 index_path 锁时 compact 必须跳过，不得继续 clear 分片。"""
    cg, _root = _fresh("g4")
    cg.add("seed_4", "正文", layer="knowledge")
    cg.flush()
    import md_cg.mdcg as _M
    _orig = _M.FileLock

    class _NeverAcquired:
        def __init__(self, *a, **k):
            self.acquired = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    _M.FileLock = _NeverAcquired
    try:
        cg.compact_index()
    finally:
        _M.FileLock = _orig
    ok(getattr(cg, "_compact_skipped_locked", 0) >= 1,
       "G4 未获锁时跳过压紧（计数留痕）", repr(getattr(cg, "_compact_skipped_locked", 0)))


def g5_flush_defers_when_lock_busy():
    """落盘拿不到索引锁 ⇒ 本批**退回脏集**（不写盘、不丢），计数留痕，且补唤醒等重试。"""
    cg, _root = _fresh("g5")
    # 显式开后台落盘：补唤醒只在**异步模式**有意义（同步模式下重试发生在下一次显式 flush，
    # 没有事件可置；G5d 二者都照实断言，不假装）。
    cg._async_flush_forced = True
    cg.add("seed_5", "v1", tags=["v1"], layer="knowledge")
    cg.flush()
    cg._request_flush()                      # 让 _flush_evt 真的建出来
    cg.add("seed_5", "v2", tags=["v2"], layer="knowledge", override=True)
    import md_cg.mdcg as _M
    _orig = _M.FileLock
    _ev = cg._flush_evt
    if _ev is not None:
        _ev.clear()                       # 先清，才能证明「补唤醒」真的发生了
    class _NeverAcquired:
        def __init__(self, *a, **k):
            self.acquired = False
            self.timeout = 10.0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    _M.FileLock = _NeverAcquired
    raised = None
    try:
        cg.flush()
    except _M.FlushLockBusy as exc:
        raised = exc
    finally:
        _M.FileLock = _orig
    ok(raised is not None, "G5a 未获索引锁 ⇒ 显式 FlushLockBusy（不再静默放行写盘）",
       repr(raised))
    ok("seed_5" in cg._dirty, "G5b 本批退回脏集（数据不丢，下一轮重试）",
       list(cg._dirty.keys()))
    ok(getattr(cg, "_flush_lock_busy", 0) == 1, "G5c 退让计数留痕（可观测）",
       repr(getattr(cg, "_flush_lock_busy", None)))
    ok(_ev is not None and _ev.is_set(), "G5d 补一次唤醒（无人再标脏也不会搁浅）",
       repr(None if _ev is None else _ev.is_set()))
    # 对照臂：锁正常时这一批照常落盘，且盘面拿到的是 v2（不是 v1）
    cg.flush()
    idx = cg._load_index()
    _e = idx["nodes"].get("seed_5") or {}
    ok("v2" in (_e.get("tags") or []), "G5e 对照：锁正常时重试落盘成功、盘面为最新版本",
       repr((_e.get("tags") or [])))


def main():
    print("issue #1011 并发一致性守卫")
    g1_reload_yields_to_flush_window()
    g2_rollback_keeps_newer_version()
    g3_reload_replays_inflight()
    g4_compact_skips_without_lock()
    g5_flush_defers_when_lock_busy()
    print("守卫结果：%d 通过 / %d 失败" % (_ok, _bad))
    return 1 if _bad else 0


if __name__ == "__main__":
    sys.exit(main())