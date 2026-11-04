# -*- coding: utf-8 -*-
"""issue #741 守卫：content_hash 全写点同源（落盘形态规范化收进唯一实现）。

## 病象
`_stage`（add 内联）手写 `sha256(sealed)[:12]`（无尾换行），而 `rebuild_index →
`_node_entry` 走 `nodefile.content_hash(读回正文)`（`dumps` 恒补尾换行）⇒ 同一节点
同一正文在索引里先后出现两个值（实测 9eb1d121c59f / aaf2ffbbdd36），对账恒报
hash_drift 假阳性；#352 §B 已被迫绕行（mdcg.py「不用索引条目的 content_hash」）。

## 修法（单点）
`nodefile.normalize_body()` ＝从 `dumps()` 抽出的尾换行规则；`nodefile.content_hash`
内部先 normalize 再哈希 ⇒ **全部**写点（add 内联 / `_write_node` 索引同步 /
`_move_layer` 经 `_node_entry` / twophase）自动同源，无需逐点手补。

## 断言面（每条＝可定点变异的判据）
- G1 写入指纹 == 读回重建指纹（#741 主判据；修前必红）
- G2 `rebuild_index()` 后不变（幂等）
- G3 元数据更新（`update_tags` → `_write_node` 索引同步口）后仍同源
- G4 搬层（`_move_layer` → `_node_entry`）后仍同源
- G5 内容改动 → 指纹变化；重建后稳定
- G6 正文自带尾换行 → 幂等（不双补）
- G7 旧手写口径 != 新口径（升级首轮 hash_drift 属预期，`rebuild_index` 迁移）

运行：python -X utf8 -m md_cg.test_issue741_content_hash_same_source
退出码：0 = 全绿；1 = 有断言失败。沙箱纪律：临时库，绝不触在役库与 ~/.mdcg。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile

from md_cg import nodefile
from md_cg.mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(msg)


def _idx_hash(cg, nid):
    e = (cg.index.get("nodes") or {}).get(nid) or {}
    return e.get("content_hash")


def _rb_hash(cg, nid):
    node = cg.get(nid) or {}
    return nodefile.content_hash(node.get("content") or "")


def _old_style(content):
    """修前 `_stage` 的手写口径（无尾换行）——只在断言里用于证明鉴别力。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


BODY = "\n".join([
    "# 功能名：741 探针",
    "# 生效条件：任意时刻",
    "# 子功能：x",
    "# 执行：x",
    "# 验证方式：test",
    "# 不适用条件：无",
    "",
    "正文第一行",
    "正文第二行",
])  # 不带尾换行 —— 旧实现必分叉形态


def main():
    TMP = tempfile.mkdtemp(prefix="i741_")
    try:
        cg = MdCGOS(os.path.join(TMP, "root"))

        # G1 写入 == 重建（#741 主判据）
        cg.add("g1", BODY, layer="knowledge", tags=["a"], verification_basis="test")
        h1 = _idx_hash(cg, "g1")
        r1 = _rb_hash(cg, "g1")
        ok(h1 == r1, "G1 写入索引指纹 == 读回重建指纹（%s vs %s）" % (h1, r1))
        ok(h1 == nodefile.content_hash(BODY), "G1 指纹 == 唯一实现(正文)（normalize 内置）")
        ok(h1 != _old_style(BODY), "G1 新口径 != 旧手写口径（证明本测试有鉴别力）")

        # G2 rebuild 幂等
        cg.rebuild_index()
        ok(_idx_hash(cg, "g1") == h1, "G2 rebuild 后指纹不变")

        # G3 元数据更新（_write_node 索引同步口）
        cg.update_tags("g1", add=["t741"])
        ok(_idx_hash(cg, "g1") == _rb_hash(cg, "g1"), "G3 update_tags 后仍同源")

        # G4 搬层（_move_layer → _node_entry）
        cg._move_layer("g1", "contextual", reason="i741")
        ok(_idx_hash(cg, "g1") == _rb_hash(cg, "g1"), "G4 搬层后仍同源")

        # G5 内容改动 → 指纹变；重建稳定
        h_before = _idx_hash(cg, "g1")
        cg.add("g1", BODY + "\n追加", layer="knowledge", tags=["a"], verification_basis="test")
        h_after = _idx_hash(cg, "g1")
        ok(h_after != h_before, "G5 内容改动 → 指纹变化")
        cg.rebuild_index()
        ok(_idx_hash(cg, "g1") == h_after, "G5 重建后指纹稳定")

        # G6 尾换行幂等
        cg.add("g6", BODY + "\n", layer="knowledge", tags=["a"], verification_basis="test")
        ok(_idx_hash(cg, "g6") == nodefile.content_hash(BODY + "\n"), "G6 尾换行幂等（不双补）")

        # G7 旧口径 ≠ 新口径（升级一次性 drift 的书面证据）
        ok(_old_style(BODY) != nodefile.content_hash(BODY),
           "G7 旧口径 != 新口径（升级首轮 hash_drift 属预期，rebuild_index 迁移）")

        cg.close()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

    print("\ni741: %d passed, %d failed" % (PASS, FAIL))
    for f in FAILS:
        print("  - " + f)
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
