# -*- coding: utf-8 -*-
"""issue #677 P2 守卫：索引落盘异步化——写后立即可检索、后台补齐、close 保证落盘、关闸回旧行为。

守卫面（六组）：① 写后立即在内存索引（检索可见性不降级）· ② 阈值触发的是**后台**
线程（不在返回路径同步落盘）· ③ close 同步兜底 + 线程停止 · ④ 关闸 MDCG_ASYNC_FLUSH=0
回逐位旧行为 · ⑤ **显式同步逃生门** `maintain(action="flush")`（异步的对价：要「确定
已落盘」或要让索引面错误在带内暴露时必须有一条可走的路）· ⑥ **后台失败不静默**
（分片目录被文件占住 ⇒ 写仍成功、`flush_state()["last_error"]` 记账、显式 flush 抛
结构化 ShardDirError——「容忍 ≠ 静默」，N225 判据在异步化后的落点）。
"""
from __future__ import annotations

import os
import tempfile
import threading
import time

from . import fsutil as F
from .mdcg import MdCG
from .mdcos import MdCGOS


def _shard_bytes(root):
    d = os.path.join(root, "_index_log")
    tot = 0
    for base, _dirs, names in os.walk(d):
        for n in names:
            try:
                tot += os.path.getsize(os.path.join(base, n))
            except OSError:
                pass
    return tot


def _wait(pred, timeout=3.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def main():
    ok = bad = 0

    def chk(cond, label, extra=""):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  PASS", label)
        else:
            bad += 1
            print("  FAIL", label, extra)

    # ① 异步开（缺省）：写入返回时**内存索引已含新节点**（写后即可检索），分片日志尚未必有
    os.environ.pop("MDCG_ASYNC_FLUSH", None)
    root = tempfile.mkdtemp(prefix="f677p2_")
    cg = MdCG(root, autoflush=1)          # 阈值 1：每次写都会触发「落盘请求」
    cg.add("a1", "# 功能名：甲\n# 执行：乙", layer="knowledge",
           importance=0.6, verification_basis="test")
    chk("a1" in (cg.index.get("nodes") or {}), "#677P2 写完立即在内存索引里（写后即可检索）")
    chk(cg._flush_thread is not None and cg._flush_thread.is_alive(),
        "#677P2 阈值触发的是**后台**刷盘线程（不在写路径同步落盘）")
    chk(_wait(lambda: len(cg._dirty) == 0 and _shard_bytes(root) > 0),
        "#677P2 后台把脏索引补齐写到 _index_log", (_shard_bytes(root), len(cg._dirty)))

    # ② close 同步保证落盘 + 线程停止
    cg.add("a2", "# 功能名：乙\n# 执行：丙", layer="knowledge",
           importance=0.6, verification_basis="test")
    cg.close()
    chk(cg._flush_thread is None, "#677P2 close 后后台线程已停")
    # close 会顺带 compact/rebuild 出快照（issue #33），分片日志可能已并入并被清 —— 
    # 判据是「快照或分片至少其一存在」，不是死盯分片。
    chk(os.path.exists(cg.index_path) or _shard_bytes(root) > 0,
        "#677P2 close 后有落盘产物（快照或分片）",
        cg.index_path)

    # ③ 关闸 MDCG_ASYNC_FLUSH=0 → 回到同步行为（写完即已落盘，没有后台线程）
    os.environ["MDCG_ASYNC_FLUSH"] = "0"
    root2 = tempfile.mkdtemp(prefix="f677sync_")
    try:
        cg2 = MdCG(root2, autoflush=1)
        cg2.add("b1", "# 功能名：丙\n# 执行：丁", layer="knowledge",
                importance=0.6, verification_basis="test")
        chk(cg2._flush_thread is None, "#677P2 关闸后不创建后台线程")
        chk(len(cg2._dirty) == 0, "#677P2 关闸后写路径同步 flush（_dirty 立即清空）")
        chk(_shard_bytes(root2) > 0, "#677P2 关闸后写盘已完成（不依赖后台）")
        cg2.close()
    finally:
        os.environ.pop("MDCG_ASYNC_FLUSH", None)

    # ④ 显式同步逃生门：maintain(action="flush") ——异步的对价是「写完那一刻索引
    #    派生物未必在盘上」，故必须有一条「确定已落盘」的路；它走的是 mcp_server
    #    op=maintain 的同一入口（#677 P2 后索引面错误的**唯一带内出口**）。
    root3 = tempfile.mkdtemp(prefix="f677flush_")
    cg3 = MdCGOS(root3, autoflush=1)
    cg3.add("c1", "# 功能名：戊\n# 执行：己", layer="knowledge",
            importance=0.6, verification_basis="test")
    st_pending = cg3.flush_state()
    chk(st_pending["async"] is True and st_pending["pending_dirty"] >= 0
        and st_pending["last_error"] is None,
        "#677P2 flush_state() 可读（async / pending_dirty / last_error）",
        st_pending)
    rep = cg3.maintain(action="flush")
    chk(isinstance(rep, dict) and rep.get("ok") is True
        and rep.get("action") == "flush" and rep.get("async") is True,
        "#677P2 maintain(action=flush) 返回结构化回执", rep)
    chk(len(cg3._dirty) == 0 and _shard_bytes(root3) > 0,
        "#677P2 显式 flush 后脏索引清零且已落分片日志", len(cg3._dirty))
    cg3.close()

    # ⑤ 后台失败不静默（容忍 ≠ 静默，N225）：分片目录路径被**文件**占住 ⇒ 重建必
    #    失败。异步契约下写仍成功（节点已落盘、内存索引已同钩），但失败必须留下
    #    可检痕迹，且显式 flush 要把它**真抛**出来（不是只写 stderr）。
    root4 = tempfile.mkdtemp(prefix="f677fail_")
    with open(os.path.join(root4, "_index_log"), "w", encoding="utf-8") as fh:
        fh.write("squat")
    cg4 = MdCGOS(root4, autoflush=1)
    err_add = None
    try:
        cg4.add("d1", "# 功能名：庚\n# 执行：辛", layer="knowledge",
                importance=0.6, verification_basis="test")
    except Exception as exc:                       # noqa: BLE001
        err_add = exc
    chk(err_add is None, "#677P2 索引面坏掉时写仍成功（异步不回退写入）", err_add)
    chk(_wait(lambda: cg4.flush_state()["last_error"]),
        "#677P2 后台落盘失败被记账（flush_state().last_error 非空——不静默）",
        cg4.flush_state())
    err_flush = None
    try:
        cg4.maintain(action="flush")
    except Exception as exc:                       # noqa: BLE001
        err_flush = exc
    chk(isinstance(err_flush, F.ShardDirError)
        and getattr(err_flush, "code", None) == F.SHARD_DIR_ERR_CODE
        and bool(getattr(err_flush, "hint", "")),
        "#677P2 显式 flush 把索引面错误结构化抛出（code + hint 可机读）",
        repr(err_flush)[:200])
    try:
        cg4.close()                                # 关闭面同款：不吞异常
    except Exception:                              # noqa: BLE001
        pass

    # ⑥ 生产写链的「读回确认」已异步（writepipe._commit_visibility）：写返回体带
    #    机器可读的 index_flush 标记——异步面「本笔写入的索引派生物尚未保证落盘」，
    #    关闸面「同步已落盘」。这一条钉的是**用户要的那个语义**（返回不再等落盘），
    #    只钉 MdCG 内部机制会漏掉生产入口。
    from . import writepipe as W
    os.environ.pop("MDCG_ASYNC_FLUSH", None)
    root5 = tempfile.mkdtemp(prefix="f677wp_")
    cg5 = MdCGOS(root5, autoflush=1)
    out5 = {}
    cg5.add("e1", "# 功能名：壬\n# 执行：癸", layer="knowledge",
            importance=0.6, verification_basis="test")
    W._commit_visibility(cg5, out5)
    chk(out5.get("index_flush") == "async" and "flush_error" not in out5,
        "#677P2 写提交边界走异步通道（返回体 index_flush=async，无 flush_error）", out5)
    cg5.close()
    os.environ["MDCG_ASYNC_FLUSH"] = "0"
    root6 = tempfile.mkdtemp(prefix="f677wpsync_")
    try:
        cg6 = MdCGOS(root6, autoflush=1)
        out6 = {}
        cg6.add("f1", "# 功能名：子\n# 执行：丑", layer="knowledge",
                importance=0.6, verification_basis="test")
        W._commit_visibility(cg6, out6)
        chk(out6.get("index_flush") == "sync" and len(cg6._dirty) == 0
            and _shard_bytes(root6) > 0,
            "#677P2 关闸后写提交边界同步落盘（index_flush=sync 且脏集已清）", out6)
        cg6.close()
    finally:
        os.environ.pop("MDCG_ASYNC_FLUSH", None)

    # ⑦ 并发写 × 后台落盘不撞车（本批套件实测缺陷的守卫）：flush 移到后台线程后，
    #    `_dirty` 出现双线程读写——`_flush_locked` 直接遍历脏集时，写路径插入新键
    #    即抛 RuntimeError: dictionary changed size during iteration（实测把
    #    test_p27_docindex 整轮打红）。判据：多线程写完、后台落定后 last_error
    #    必须为空，且新实例读得回全部节点（索引没落后也没丢条）。
    root7 = tempfile.mkdtemp(prefix="f677race_")
    cg7 = MdCGOS(root7, autoflush=1)
    ids = ["r%02d_%02d" % (t, i) for t in range(4) for i in range(15)]
    errs = []

    def _writer(t):
        try:
            for i in range(15):
                nid = "r%02d_%02d" % (t, i)
                cg7.add(nid, "# 功能名：%s\n# 执行：并发" % nid, layer="knowledge",
                        importance=0.6, verification_basis="test")
        except Exception as exc:                   # noqa: BLE001
            errs.append(exc)

    ths = [threading.Thread(target=_writer, args=(t,)) for t in range(4)]
    for th in ths:
        th.start()
    for th in ths:
        th.join(30)
    chk(not errs, "#677P2 并发写不抛异常", errs[:1])
    chk(_wait(lambda: len(cg7._dirty) == 0),
        "#677P2 并发写后脏集最终清空（后台落定）", cg7.flush_state())
    cg7.maintain(action="flush")
    chk(cg7.flush_state()["last_error"] is None,
        "#677P2 并发写 × 后台落盘零失败（dictionary changed size 不再复现）",
        cg7.flush_state())
    cg7.close()
    reader = MdCG(root7)
    miss = [nid for nid in ids if reader.get(nid) is None]
    chk(not miss, "#677P2 并发写的节点全部可读回（索引不落后于盘面）", miss[:3])
    reader.close()

    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
