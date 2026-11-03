# -*- coding: utf-8 -*-
"""issue #741 守卫：`_stage` 与 `rebuild_index` 的 content_hash 必须同源。

## 病象
同一节点、同一份正文，在索引快照 `_index.json` 里先后出现**两个不同的
`content_hash`**：

    刚写入（add → _stage）   content_hash = sha256(传入正文)
    rebuild_index → _node_entry content_hash = sha256(读回正文)

两者相差 `dumps()` 补的那个尾换行 —— `nodefile.dumps` 在正文无尾换行时补
一个 `"\n"`（写盘形态），`nodefile.loads` 原样保留。于是「写入时传入的原串」
与「此后读回的串」在这一个字节上分叉，两侧各算各的指纹。

## 危害
`content_hash` 是启动对账与变更探测的判据键（见 `nodefile.content_hash`
docstring：两处共用且必须逐位一致，否则对账「永远匹配成功」而失去意义）：

- 写入后与重建后不同 ⇒ 启动对账**恒报 hash_drift 假阳性**；
- 反过来，正文真变动时也可能因两侧口径不同而漏报。

## 断言面（每条＝一个可定点变异的判据）
- **G1 写入 vs 重建同源**：`add` 后取 `content_hash`，`rebuild_index()` 后再取，
  两者**逐位相同**（回退成 `sha256(sealed)` 且正文无尾换行时此条必红）。
- **G2 覆写后仍同源**：同一节点覆写一次正文，`_stage` 的 hash 与重建后一致。
- **G3 跨进程重开一致**：新实例加载同一 root，索引值不变（无「重开即漂移」）。
- **G4 指纹真的跟着正文走**：正文改动后 hash 必须变（防「永远匹配」退化）。
- **G5 与唯一实现同口径**：索引值 == `nodefile.content_hash(读回正文)`。

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


_BODY = (
    "# 功能名：hash 同源守卫节点\n"
    "# 生效条件：守卫自检时\n"
    "# 子功能：构造一个完整 CCG 节点\n"
    "# 执行：add 后比对索引指纹\n"
    "# 验证方式：本条测试\n"
    "# 不适用条件：无\n"
)


def _fresh_root(tag: str) -> str:
    return tempfile.mkdtemp(prefix="mdcg741-" + tag + "-")


def g1_write_vs_rebuild():
    """G1：写入登记与重建登记必须同源（正文**不带**尾换行）。"""
    print("== G1 写入 vs 重建同源 ==")
    root = _fresh_root("g1")
    try:
        cg = MdCG(root)
        # 关键：正文**不带**尾换行——旧实现在这一形态下必然分叉
        cg.add("g1", _BODY.rstrip("\n"), layer="knowledge",
               tags=["t"], importance=0.2)
        after_write = (cg.index["nodes"].get("g1") or {}).get("content_hash")
        cg.rebuild_index()
        after_rebuild = (cg.index["nodes"].get("g1") or {}).get("content_hash")
        ok(after_write == after_rebuild,
           "G1 写入后与重建后 content_hash 逐位一致（写入=%s 重建=%s）"
           % (after_write, after_rebuild))
        ok(after_write is not None,
           "G1 前置：写入后索引条目确有 content_hash（实际 %r）" % (after_write,))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g2_overwrite():
    """G2：覆写一次正文后，两条路径仍同源。"""
    print("== G2 覆写后仍同源 ==")
    root = _fresh_root("g2")
    try:
        cg = MdCG(root)
        cg.add("g2", _BODY.rstrip("\n"), layer="knowledge",
               tags=["t"], importance=0.2)
        cg.add("g2", _BODY.rstrip("\n") + "追加一行", layer="knowledge",
               tags=["t"], importance=0.2)
        after_write = (cg.index["nodes"].get("g2") or {}).get("content_hash")
        cg.rebuild_index()
        after_rebuild = (cg.index["nodes"].get("g2") or {}).get("content_hash")
        ok(after_write == after_rebuild,
           "G2 覆写后写入侧与重建侧一致（写入=%s 重建=%s）"
           % (after_write, after_rebuild))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g3_reopen():
    """G3：跨进程（新实例）重开，索引值不漂移。"""
    print("== G3 跨进程重开一致 ==")
    root = _fresh_root("g3")
    try:
        cg = MdCG(root)
        cg.add("g3", _BODY.rstrip("\n"), layer="knowledge",
               tags=["t"], importance=0.2)
        before = (cg.index["nodes"].get("g3") or {}).get("content_hash")
        del cg
        cg2 = MdCG(root)
        after = (cg2.index["nodes"].get("g3") or {}).get("content_hash")
        ok(before == after,
           "G3 重开后 content_hash 不变（前=%s 后=%s）" % (before, after))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g4_hash_follows_content():
    """G4：正文改动后指纹**必须变**（防「永远匹配」的假绿）。"""
    print("== G4 指纹跟随正文 ==")
    root = _fresh_root("g4")
    try:
        cg = MdCG(root)
        cg.add("g4", _BODY.rstrip("\n"), layer="knowledge",
               tags=["t"], importance=0.2)
        h1 = (cg.index["nodes"].get("g4") or {}).get("content_hash")
        cg.add("g4", _BODY.rstrip("\n") + "改动内容", layer="knowledge",
               tags=["t"], importance=0.2)
        h2 = (cg.index["nodes"].get("g4") or {}).get("content_hash")
        ok(h1 != h2, "G4 正文改动后指纹随之改变（旧=%s 新=%s）" % (h1, h2))
        cg.rebuild_index()
        h3 = (cg.index["nodes"].get("g4") or {}).get("content_hash")
        ok(h2 == h3, "G4 重建后仍等于改动后的值（%s vs %s）" % (h2, h3))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g5_matches_nodefile():
    """G5：索引值 == `nodefile.content_hash`（唯一实现）对**读回正文**的结果。"""
    print("== G5 与唯一实现同口径 ==")
    root = _fresh_root("g5")
    try:
        cg = MdCG(root)
        cg.add("g5", _BODY.rstrip("\n"), layer="knowledge",
               tags=["t"], importance=0.2)
        idx = (cg.index["nodes"].get("g5") or {}).get("content_hash")
        read_back = (cg.get("g5") or {}).get("content") or ""
        expect = nodefile.content_hash(read_back)
        ok(idx == expect,
           "G5 索引指纹 == nodefile.content_hash(读回正文)（索引=%s 期望=%s）"
           % (idx, expect))
    finally:
        shutil.rmtree(root, ignore_errors=True)


_GROUPS = (g1_write_vs_rebuild, g2_overwrite, g3_reopen,
           g4_hash_follows_content, g5_matches_nodefile)


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
