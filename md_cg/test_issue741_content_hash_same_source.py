# -*- coding: utf-8 -*-
"""issue #741 守卫：content_hash 的**算法与输入口径**必须全仓同源。

## 病象
同一节点、同一份正文，在索引快照 `_index.json` 里**先后出现两个不同的
`content_hash`**——修前 4 个写点里 3 个各算各的：

    mdcg.py 写点                        输入                      修前口径
    ① _stage（add 内联）                sealed（未规范化）        手写 sha256[:12]
    ② _write_node 的索引同步            sealed（未规范化）        nodefile.content_hash
    ③ _node_entry（_move_layer 调用方） sealed（未规范化）        nodefile.content_hash
    ④ _node_entry（_scan_nodes/rebuild）读回正文（**恒带尾换行**）  nodefile.content_hash

②③ 与 ④ 差一个 `dumps()` 补的尾换行 ⇒ 同一正文两个值 ⇒ 启动对账恒报
hash_drift 假阳性；反过来正文真变动时也可能因口径不同而漏报。

## 修法
算法与输入**双双收口到单点**：
  · 算法 = `nodefile.content_hash`（唯一实现，禁再手写 sha256）；
  · 输入 = `nodefile.normalize_body`（`dumps()` body 段同一实现，禁在调用处手写
    `endswith("\n")` 判断——那是同一个失败模式换位置复现）。

## 断言面（每条＝一个可定点变异的判据）
- **G1 写入 vs 重建同源**：正文**不带**尾换行（旧实现必分叉的形态）。
- **G2 覆写后仍同源**。
- **G3 元数据更新族后仍同源**（`update_tags`：走写点②，修前必红）。
- **G4 搬层后仍同源**（`_move_layer`：走写点③，修前必红）。
- **G5 跨实例重开一致**（与 G1 等价，仅作开关往返的回归保险）。
- **G6 指纹跟随正文**（防「永远匹配」的假绿）。
- **G7 与唯一实现同口径**：索引值 == `content_hash(normalize_body(读回正文))`。
- **G8 三写点互相一致**：对同一节点依次触发 写点②/③，每一步都与重建值相等。

运行：python -X utf8 -m md_cg.test_issue741_content_hash_same_source
退出码（fail-closed）：0 = 全绿；1 = 有断言失败。
沙箱纪律：库根落守卫临时目录，绝不碰在役库与 ~/.mdcg。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from md_cg import nodefile                       # noqa: E402
from md_cg.mdcg import MdCG                      # noqa: E402

_FAILED = []


def ok(cond, msg):
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        _FAILED.append(msg)


# 关键：**不带**尾换行——正是旧实现必分叉的形态
_BODY = (
    "# 功能名：hash 同源守卫节点\n"
    "# 生效条件：守卫自检时\n"
    "# 子功能：构造一个完整 CCG 节点\n"
    "# 执行：add 后比对索引指纹\n"
    "# 验证方式：本条测试\n"
    "# 不适用条件：无"
)


def _fresh_root(tag):
    return tempfile.mkdtemp(prefix="mdcg741-" + tag + "-")


def _idx(cg, nid):
    return (cg.index["nodes"].get(nid) or {}).get("content_hash")


def _rebuild_hash(cg, nid):
    snap = _idx(cg, nid)
    cg.rebuild_index()
    val = _idx(cg, nid)
    return snap, val


def g1_write_vs_rebuild():
    print("== G1 写入 vs 重建同源 ==")
    root = _fresh_root("g1")
    try:
        cg = MdCG(root)
        cg.add("g1", _BODY, layer="knowledge", tags=["t"], importance=0.2)
        w = _idx(cg, "g1")
        _, r = _rebuild_hash(cg, "g1")
        ok(w is not None, "G1 前置：写入后索引条目确有 content_hash（%r）" % (w,))
        ok(w == r, "G1 写入后与重建后逐位一致（写=%s 重建=%s）" % (w, r))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g2_overwrite():
    print("== G2 覆写后仍同源 ==")
    root = _fresh_root("g2")
    try:
        cg = MdCG(root)
        cg.add("g2", _BODY, layer="knowledge", tags=["t"], importance=0.2)
        cg.add("g2", _BODY + "\n追加一行", layer="knowledge", tags=["t"], importance=0.2)
        w = _idx(cg, "g2")
        _, r = _rebuild_hash(cg, "g2")
        ok(w == r, "G2 覆写后写入侧与重建侧一致（写=%s 重建=%s）" % (w, r))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g3_metadata_update():
    """G3：元数据更新族（走写点② _write_node 的索引同步）。修前必红。"""
    print("== G3 元数据更新后仍同源 ==")
    root = _fresh_root("g3")
    try:
        cg = MdCG(root)
        cg.add("g3", _BODY, layer="knowledge", tags=["t"], importance=0.2)
        base = _idx(cg, "g3")
        fn = getattr(cg, "update_tags", None)
        ok(fn is not None, "G3 前置：存在 update_tags（元数据更新族入口）")
        if fn is not None:
            fn("g3", ["t", "extra"])
            after_write = _idx(cg, "g3")
            _, after_rebuild = _rebuild_hash(cg, "g3")
            ok(after_write == after_rebuild,
               "G3 元数据更新后写入侧与重建侧一致（写=%s 重建=%s）"
               % (after_write, after_rebuild))
            ok(after_write == base,
               "G3 正文未变 ⇒ 指纹不应变（前=%s 后=%s）" % (base, after_write))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g4_move_layer():
    """G4：搬层（_move_layer → _node_entry，写点③）。修前必红。"""
    print("== G4 搬层后仍同源 ==")
    root = _fresh_root("g4")
    try:
        cg = MdCG(root)
        cg.add("g4", _BODY, layer="knowledge", tags=["t"], importance=0.2)
        base = _idx(cg, "g4")
        mv = getattr(cg, "_move_layer", None)
        ok(mv is not None, "G4 前置：存在 _move_layer")
        if mv is not None:
            mv("g4", "contextual", reason="守卫搬层")
            after_write = _idx(cg, "g4")
            _, after_rebuild = _rebuild_hash(cg, "g4")
            ok(after_write == after_rebuild,
               "G4 搬层后写入侧与重建侧一致（写=%s 重建=%s）"
               % (after_write, after_rebuild))
            ok(after_write == base,
               "G4 正文未变 ⇒ 指纹不应变（前=%s 后=%s）" % (base, after_write))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g5_reopen():
    print("== G5 跨实例重开一致 ==")
    root = _fresh_root("g5")
    try:
        cg = MdCG(root)
        cg.add("g5", _BODY, layer="knowledge", tags=["t"], importance=0.2)
        before = _idx(cg, "g5")
        cg2 = MdCG(root)
        after = _idx(cg2, "g5")
        ok(before == after, "G5 重开后 content_hash 不变（前=%s 后=%s）" % (before, after))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g6_hash_follows_content():
    print("== G6 指纹跟随正文 ==")
    root = _fresh_root("g6")
    try:
        cg = MdCG(root)
        cg.add("g6", _BODY, layer="knowledge", tags=["t"], importance=0.2)
        h1 = _idx(cg, "g6")
        cg.add("g6", _BODY + "\n改动内容", layer="knowledge", tags=["t"], importance=0.2)
        h2 = _idx(cg, "g6")
        ok(h1 != h2, "G6 正文改动后指纹随之改变（旧=%s 新=%s）" % (h1, h2))
        _, h3 = _rebuild_hash(cg, "g6")
        ok(h2 == h3, "G6 重建后仍等于改动后的值（%s vs %s）" % (h2, h3))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g7_matches_single_impl():
    print("== G7 与唯一实现同口径 ==")
    root = _fresh_root("g7")
    try:
        cg = MdCG(root)
        cg.add("g7", _BODY, layer="knowledge", tags=["t"], importance=0.2)
        idx = _idx(cg, "g7")
        read_back = (cg.get("g7") or {}).get("content") or ""
        expect = nodefile.content_hash(nodefile.normalize_body(read_back))
        ok(idx == expect,
           "G7 索引指纹 == content_hash(normalize_body(读回正文))（索引=%s 期望=%s）"
           % (idx, expect))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g8_three_write_sites_agree():
    """G8：写点 ①（add）、②（元数据更新）、③（搬层）三轮之后仍与重建同值。"""
    print("== G8 三写点互相一致 ==")
    root = _fresh_root("g8")
    try:
        cg = MdCG(root)
        cg.add("g8", _BODY, layer="knowledge", tags=["t"], importance=0.2)
        h_add = _idx(cg, "g8")
        cg.update_tags("g8", ["t", "x"])
        h_meta = _idx(cg, "g8")
        cg._move_layer("g8", "contextual", reason="守卫搬层")
        h_move = _idx(cg, "g8")
        _, h_rebuild = _rebuild_hash(cg, "g8")
        ok(h_add == h_meta == h_move == h_rebuild,
           "G8 三写点与重建值全等（add=%s meta=%s move=%s rebuild=%s）"
           % (h_add, h_meta, h_move, h_rebuild))
    finally:
        shutil.rmtree(root, ignore_errors=True)


_GROUPS = (g1_write_vs_rebuild, g2_overwrite, g3_metadata_update,
           g4_move_layer, g5_reopen, g6_hash_follows_content,
           g7_matches_single_impl, g8_three_write_sites_agree)


def main():
    for fn in _GROUPS:
        fn()
    print("=" * 68)
    if _FAILED:
        print("content_hash 同源守卫：%d 条失败" % len(_FAILED))
        for m in _FAILED:
            print("  - " + m)
        return 1
    print("content_hash 同源守卫：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
