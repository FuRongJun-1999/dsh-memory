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
        # G6 改判据（原写法两侧同时双补 ⇒ 恒真；改为「BODY 与 BODY+\n 同值」）
        ok(nodefile.content_hash(BODY) == nodefile.content_hash(BODY + "\n"),
           "G6 尾换行幂等（normalize 只补不删：BODY 与 BODY+换行 同值）")

        # G7 旧口径 ≠ 新口径（升级一次性 drift 的书面证据）
        ok(_old_style(BODY) != nodefile.content_hash(BODY),
           "G7 旧口径 != 新口径（升级首轮 hash_drift 属预期，rebuild_index 迁移）")

        # G8/G9 空正文与 None（#741 口径变更的破坏性一面，显式钉住）
        ok(nodefile.content_hash("") == hashlib.sha256(b"\n").hexdigest()[:12],
           "G8 content_hash(空) == sha256(单个换行)（修前是 sha256 空串）")
        ok(nodefile.content_hash(None) == nodefile.content_hash(""),
           "G9 None 与空串同值（content_hash 侧兜底）")
        # G10 normalize 只补不删（尾换行个数仍可区分）
        ok(nodefile.content_hash("a\n\n") != nodefile.content_hash("a\n"),
           "G10 尾换行个数仍可区分（normalize 不 rstrip）")
        ok(nodefile.normalize_body(nodefile.normalize_body("a"))
           == nodefile.normalize_body("a"), "G11 normalize_body 幂等")

        # G12/G13 twophase legacy 双向守卫（旧口径 intent 放行 / 真 mismatch 拒）
        from md_cg import twophase as _tp
        cg.add("g12", BODY, layer="knowledge", tags=["a"], verification_basis="test")
        # issue #759：旧 begin 的实际口径是 content_hash(_norm(x))（= sha256(rstrip + "\n")），
        # 不是手写 sha256(rstrip)——后者少一个尾换行字节，从来不是真实旧口径。
        _legacy_want = nodefile.content_hash(_tp._norm(BODY))
        _st12, _cd12 = _tp._judge(cg, {"id": "g12", "content_hash": _legacy_want})
        ok(_st12 == _tp.STATUS_COMMITTED,
           "G12 旧口径 intent 放行（升级兼容，%s/%s）" % (_st12, _cd12))
        cg.add("g12", BODY + "\n追加", layer="knowledge", tags=["a"],
               verification_basis="test")
        _st13, _cd13 = _tp._judge(cg, {"id": "g12", "content_hash": _legacy_want})
        ok(_st13 == _tp.STATUS_INTERRUPTED and _cd13 == _tp.R_MISMATCH,
           "G13 正文真改后旧 intent 仍判 mismatch（兼容不过宽，%s/%s）" % (_st13, _cd13))

        cg.close()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

    print("\ni741: %d passed, %d failed" % (PASS, FAIL))
    for f in FAILS:
        print("  - " + f)
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
