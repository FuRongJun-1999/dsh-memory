# -*- coding: utf-8 -*-
"""issue #741 守卫（读侧）：**消费 content_hash 的读点**也必须与写点同口径。

## 为什么需要这一组
写点收口（G1–G8）只保证「索引里存的值是同一口径」。但仓里还有若干读点
拿索引值与**自己算的**指纹比对——那些点若按入参原串算，正文不带尾换行时
就会与索引值恒不相等，功能**静默失效**（不是报错，是默默地永远不命中）。

这正是 #741 的同一个失败模式换了位置。附证（维护者已核）：
mdcg.py:3510-3511 的 #352 §B 注释早就写着
「该键的基准随写入路径而异……故正文比对走读回内容」——当时选了绕行不是修根。

## 断言面
- **R1** 幂等闸（writepipe._gate_dedupe）对**不带尾换行**的正文能命中既有节点。
- **R2** 两段式 intent 的 content_hash 与对账实际重算值相等（不报 interrupted）。
- **R3** 对账双形态接受集（reconcile._disk_hashes）接受当前索引值。
- **R4** 元数据更新后（update_tags）索引值仍等于**盘面读回正文**的指纹。

## 与 G1–G8 的分工
G1–G8 守「写进去的值同源」；R1–R4 守「读出来比对时口径没走样」。
两边都绿才叫收口完成——只有一边绿时，功能表现为「索引对了但用不对」。

运行：python -X utf8 -m md_cg.test_issue741_read_side_same_source
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

from md_cg import nodefile, writepipe, twophase, reconcile   # noqa: E402
from md_cg.mdcg import MdCG                                  # noqa: E402

_FAILED = []


def ok(cond, msg):
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        _FAILED.append(msg)


# 关键：**不带**尾换行——旧口径在此形态下必然与索引值分叉
_BODY = (
    "# 功能名：读侧口径同源守卫\n"
    "# 生效条件：守卫自检时\n"
    "# 子功能：验证读点比对口径\n"
    "# 执行：逐读点比对\n"
    "# 验证方式：本条测试\n"
    "# 不适用条件：无"
)


def _disk_content(root, cg, nid):
    """按盘面形态读回正文（nodefile.loads 切出的 body，恒带尾换行）。"""
    p = os.path.join(root, (cg.index["nodes"][nid])["path"])
    with open(p, encoding="utf-8") as f:
        _fm, content = nodefile.loads(f.read())
    return content


def r1_dedupe_gate():
    print("== R1 幂等闸能命中（正文不带尾换行） ==")
    root = tempfile.mkdtemp(prefix="mdcg741-r1-")
    try:
        cg = MdCG(root)
        cg.add("r1", _BODY, layer="knowledge")
        ctx = {"cg": cg, "a": {"content": _BODY, "layer": "knowledge", "dedupe": True}}
        got = writepipe._gate_dedupe(ctx)
        ok(got is not None, "R1 幂等闸识别到同层同指纹（实际 %r）"
           % (None if got is None else got.get("deduped"),))
        ok(bool(got) and got.get("dedupe_of") == "r1",
           "R1 命中的是既有节点 r1（实际 %r）"
           % (None if got is None else got.get("dedupe_of"),))
        ok(bool(got) and got.get("committed") is False,
           "R1 未落盘（committed=False）")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def r2_twophase_intent():
    print("== R2 两段式 intent 与对账重算一致 ==")
    root = tempfile.mkdtemp(prefix="mdcg741-r2-")
    try:
        cg = MdCG(root)
        tok = twophase.begin(cg, "r2", _BODY, layer="knowledge")
        cg.add("r2", _BODY, layer="knowledge")
        # 判据取 reconcile 的**结局分布**：unpaired 是"待对账笔数"（本轮必然 ≥1），
        # 它等于 0 只能说明没有待对账记录，不能说明对账成功。真正的判据是
        # interrupted==0 且 committed>=1 —— 即那一笔被判定为「已落盘」。
        rep = twophase.reconcile(cg)
        ok(rep.get("interrupted") == 0,
           "R2 无 interrupted（实际 %r）" % (rep.get("interrupted"),))
        ok(rep.get("committed") >= 1,
           "R2 该笔被判 committed（实际 %r）" % (rep.get("committed"),))
        got = nodefile.content_hash(nodefile.normalize_body(_BODY))
        ok(tok.get("content_hash") == got,
           "R2 intent 指纹 == normalize 口径（intent=%s 期望=%s）"
           % (tok.get("content_hash"), got))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def r3_reconcile_accepts():
    print("== R3 对账双形态接受集接受当前索引值 ==")
    root = tempfile.mkdtemp(prefix="mdcg741-r3-")
    try:
        cg = MdCG(root)
        cg.add("r3", _BODY, layer="knowledge")
        idx = (cg.index["nodes"]["r3"]).get("content_hash")
        raw, norm = reconcile._disk_hashes(_disk_content(root, cg, "r3"))
        ok(idx in (raw, norm),
           "R3 索引值落在接受集内（idx=%s raw=%s norm=%s）" % (idx, raw, norm))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def r4_metadata_update_caliber():
    print("== R4 元数据更新后仍等于盘面读回指纹 ==")
    root = tempfile.mkdtemp(prefix="mdcg741-r4-")
    try:
        cg = MdCG(root)
        cg.add("r4", _BODY, layer="knowledge")
        cg.update_tags("r4", add=["tag_after"])
        idx = (cg.index["nodes"]["r4"]).get("content_hash")
        raw = nodefile.content_hash(_disk_content(root, cg, "r4"))
        ok(idx == raw, "R4 元数据更新后 索引值 == 盘面读回指纹（idx=%s raw=%s）"
           % (idx, raw))
        cg.rebuild_index()
        idx2 = (cg.index["nodes"]["r4"]).get("content_hash")
        ok(idx == idx2, "R4 元数据更新后 与重建值一致（更新后=%s 重建后=%s）"
           % (idx, idx2))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    for fn in (r1_dedupe_gate, r2_twophase_intent, r3_reconcile_accepts,
               r4_metadata_update_caliber):
        fn()
    print("=" * 68)
    if _FAILED:
        print("读侧口径同源守卫：%d 条失败" % len(_FAILED))
        for m in _FAILED:
            print("  - " + m)
        return 1
    print("读侧口径同源守卫：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
