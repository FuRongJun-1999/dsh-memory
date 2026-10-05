#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N276 守卫 · 批内单探针（写链读环的索引代际探活只做一次）。

背景（第 32 轮性能面）：`MdCG.get` 首行无条件 `_maybe_reload_index()`，
而写链读环（`forgetting.redundancy` 240 上限 / `consistency.check` 精比环）
在环内逐节点 `cg.get(nid)` —— 每次重算同一个索引签名（快照 stat +
listdir + 逐分片 stat）。修法：`get` 增可选 `probe=True`（默认零变），
两环循环外单探一次、环内 `cg.get(nid, probe=False)`。

覆盖判据（调用计数优先；墙钟只作辅助不作断言）：
  C1 `forgetting.redundancy` 环内零重探：探针计数 == 1（修前 == 同层可比
     节点数，上限 MAX_COMPARE）
  C2 `consistency.check` 精比环零重探：探针计数 == 1（修前 == len(scan_face)）
  C3 `get(node_id, probe=False)` 与 `get(node_id)` 返回逐位一致（默认语义零变）
  C4 自证腿：旧签名 `get(nid)` 逐次探针（spy 有判别力；默认 probe=True 未变
     ——若有人把默认改 False 或去掉环外探针，C1/C2/C4 必红）
  C5 可见性不丢：他实例写入后，单探 + `probe=False` 组合读到新节点（不陈旧）
  C6 无探活面载体（测试桩）回落原 `cg.get(nid)`（既有桩零破坏）
  C7 等价性：redundancy/check 在「单探 + probe=False」与「逐节点 probe=True」
     两形态下输出逐位一致（C7a/C7b）

运行：python -X utf8 -m md_cg.test_n276_probe_hoist
退出码：0 = 全绿；1 = 有失败。
硬边界：库根一律 tempfile；不动在役数据根；不 git add/commit/push。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _REPO)

from md_cg import consistency, forgetting                    # noqa: E402
from md_cg.mdcos import MdCGSecure                           # noqa: E402
from md_cg.security import Principal                         # noqa: E402

PASS = FAIL = 0
FAILS = []

BODY = ("# 功能名：%s\n# 生效条件：载体=守卫夹具\n# 子功能：占位\n"
        "# 执行：占位\n# 验证方式：compiler 复现\n# 不适用条件：无\n\n"
        "蜂群调度 节点 %s 依赖门禁 收敛 检索\n")
CONTENT = ("# 功能名：待写样本\n# 生效条件：载体=守卫夹具\n# 子功能：占位\n"
           "# 执行：占位\n# 验证方式：compiler 复现\n# 不适用条件：无\n\n"
           "蜂群调度 待写 依赖门禁 收敛 苹果 章节\n")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _principal():
    return Principal(actor="n276", clearance="secret", can_write=True,
                     role="designer", auth_mode="test")


def _lib(n=12):
    root = tempfile.mkdtemp(prefix="n276_")
    cg = MdCGSecure(root, principal=_principal())
    for i in range(n):
        cg.add("k_%02d" % i, BODY % (i, i), layer="knowledge")
    cg.flush()
    return root, cg


def _spy(cg):
    """spy `cg._maybe_reload_index`（实例属性；两类 get 与环外探针都经它）。"""
    calls = {"n": 0}
    orig = cg._maybe_reload_index

    def s():
        calls["n"] += 1
        return orig()
    cg._maybe_reload_index = s
    return calls, orig


def main():
    root, cg = _lib()
    calls, orig_probe = _spy(cg)
    try:
        # ---------- C1 redundancy 环内零重探 ----------
        print("== C1 forgetting.redundancy 环内零重探 ==")
        calls["n"] = 0
        r1 = forgetting.redundancy(cg, CONTENT, layer="knowledge")
        n1 = calls["n"]
        check("C1a redundancy 探针 == 1（修前 == min(同层节点, 240)）",
              n1 == 1, f"calls={n1}")
        check("C1b redundancy 正常产出（compared>0）",
              r1.get("compared", 0) > 0, str(r1))

        # ---------- C4 自证腿：旧签名逐次探针 ----------
        print("== C4 自证腿（旧签名照旧逐次探针）==")
        ids = sorted(cg.index["nodes"].keys())
        calls["n"] = 0
        for nid in ids:
            cg.get(nid)
        n4 = calls["n"]
        check("C4a 旧签名 get(nid) 逐次探针（spy 有判别力）",
              n4 == len(ids), f"calls={n4} ids={len(ids)}")

        # ---------- C2 check 精比环零重探 ----------
        print("== C2 consistency.check 精比环零重探 ==")
        calls["n"] = 0
        rc = consistency.check(cg, CONTENT, layer="knowledge",
                               log_write=False)
        n2 = calls["n"]
        check("C2a check 探针 == 1（修前 == len(scan_face)）",
              n2 == 1, f"calls={n2} kept={rc.get('kept')}")
        check("C2b check 正常产出（verdict 在场）",
              isinstance(rc.get("verdict"), str), str(rc.get("verdict")))

        # ---------- C3 probe=False 与默认逐位一致 ----------
        print("== C3 get(probe=False) 与 get() 逐位一致 ==")
        a = cg.get("k_00")
        b = cg.get("k_00", probe=False)
        check("C3a 两形态返回等值（id/frontmatter/content/path）",
              a is not None and b is not None and a == b)

        # ---------- C5 可见性不丢（他实例写入） ----------
        print("== C5 他实例写入后单探 + probe=False 可见 ==")
        cgB = MdCGSecure(root, principal=_principal())
        cgB.add("k_new", BODY % ("new", "new"), layer="knowledge")
        cgB.flush()
        cgB.close()
        calls["n"] = 0
        cg._maybe_reload_index()                 # 循环外单探（生产探针位）
        probe_calls_before_get = calls["n"]
        node = cg.get("k_new", probe=False)
        check("C5a 单探后 probe=False 读到新节点（不陈旧）",
              bool(node) and "new" in (node.get("content") or ""),
              f"node={'yes' if node else 'None'}")
        check("C5b 该组合探针恰好 1 次（外面那次）",
              probe_calls_before_get == 1 and calls["n"] == 1,
              f"calls={calls['n']}")

        # ---------- C6 无探活面载体回落 ----------
        print("== C6 测试桩回落原 cg.get(nid) ==")
        class _Stub:
            def __init__(self):
                self.index = {"nodes": {"s1": {"path": "knowledge/s1.md",
                                               "layer": "knowledge"}}}

            def get(self, nid):
                return {"id": nid, "frontmatter": {},
                        "content": "占位 苹果 章节", "path": "knowledge/s1.md"}
        r6 = forgetting.redundancy(_Stub(), CONTENT, layer="knowledge")
        check("C6a 无 _maybe_reload_index 的载体不崩且正常比对",
              r6.get("compared") == 1, str(r6))

        # ---------- C7 两形态等价 ----------
        print("== C7 单探形态 vs 逐节点探针形态逐位一致 ==")
        r_prod = forgetting.redundancy(cg, CONTENT, layer="knowledge")
        rc_prod = consistency.check(cg, CONTENT, layer="knowledge",
                                    log_write=False)
        orig_get = cg.get

        def _always_probe(nid, probe=True):
            return orig_get(nid, probe=True)     # 强制回到逐节点探针
        cg.get = _always_probe
        try:
            r_full = forgetting.redundancy(cg, CONTENT, layer="knowledge")
            rc_full = consistency.check(cg, CONTENT, layer="knowledge",
                                        log_write=False)
        finally:
            cg.get = orig_get
        check("C7a redundancy 两形态逐位一致（max/with/jaccard/compared）",
              r_prod == r_full, f"prod={r_prod} full={r_full}")
        _strip = lambda d: {k: v for k, v in d.items() if k != "t"}  # noqa: E731
        check("C7b check 两形态逐位一致（剔动态键 t）",
              _strip(rc_prod) == _strip(rc_full),
              f"prod={_strip(rc_prod).get('verdict')}/{_strip(rc_prod).get('kept')}"
              f" full={_strip(rc_full).get('verdict')}/{_strip(rc_full).get('kept')}")
    finally:
        cg._maybe_reload_index = orig_probe
        cg.close()
        shutil.rmtree(root, ignore_errors=True)

    print(f"\ntest_n276_probe_hoist: {PASS} 通过 / {FAIL} 失败")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
