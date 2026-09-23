# -*- coding: utf-8 -*-
"""issue #25 生产路径门控守卫：MdCGSecure.search（生产类）必须真实吃到门控。

病灶（2026-09-23 外部报告）：检索门控 S1/S1b/S2/S4 只存在于 MdCG.search，
而生产调用链 mcp_server → MdCGSecure → MdCGOS 走的是 MdCGOS.search 覆写——
门控在生产路径从未生效，专项测试（test_retr_s*.py）全测非生产路径，
绿灯是假信号（gates=None、scanned=全表）。

本文件是「门控确实接进生产路径」的守卫：
  P1 生产类开关生效：gates 出现且 scanned 真实收敛（旧代码必红）；
  P2 默认路径零变更：总开关未设 → meta 无 gates 键（契约纪律）；
  P3 两路共享同一实现：MdCG.search 与 MdCGOS.search 的 gates 结构一致；
  P4 覆写防悬空：两份 search 源码都必须引用 apply_retrieval_gates——
     防止未来再写出第三个不含门控的覆写（本病灶的复发形态）。
"""
import inspect
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcos import MdCGSecure, MdCGOS
from md_cg.mdcg import MdCG, apply_retrieval_gates

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def build_lib(root, n=30):
    """小库：一半节点挂在 swarm-dispatch 桶（含查询词面），一半无关桶。"""
    cg = MdCGSecure(root)
    for i in range(n):
        bucket = "swarm-dispatch" if i < n // 2 else "unrelated-cow"
        text = ("# 功能名：蜂群调度样本 %d\n# 正文：dispatch 调度内容样本 %d"
                % (i, i)) if i < n // 2 else \
               ("# 功能名：无关样本 %d\n# 正文：cow 内容样本 %d" % (i, i))
        cg.add("mem_%03d" % i, text, layer="knowledge")
        # S1b 依赖 entry.bucket（平铺字段）；big_domain 同理（S1 面）
        e = cg.index["nodes"]["mem_%03d" % i]
        e["bucket"] = bucket
        e["big_domain"] = "swarm" if i < n // 2 else "farm"
    cg.flush()
    return cg


def main():
    print("== P1 生产类（MdCGSecure）开关生效（能红旧实现）==")
    root = tempfile.mkdtemp(prefix="mdcg_gate_prod_")
    cg = build_lib(root)
    os.environ["MDCG_RETRIEVAL_PIPELINE"] = "1"
    os.environ["MDCG_GATE_S1B_BUCKET"] = "1"
    try:
        r, meta = cg.search("dispatch")
        gates = meta.get("gates") or {}
        check("P1a 生产类 gates 审计出现（旧代码 gates=None）",
              isinstance(gates, dict) and "s1b" in gates,
              json.dumps(meta, ensure_ascii=False, default=str)[:200])
        check("P1b scanned 真实收敛（< 全库节点数）",
              meta.get("scanned", 10**9) < 30,
              f"scanned={meta.get('scanned')}")
        check("P1c 召回不丢（收敛后仍有结果）",
              len(r) >= 1, f"results={len(r)}")
    finally:
        os.environ.pop("MDCG_RETRIEVAL_PIPELINE", None)
        os.environ.pop("MDCG_GATE_S1B_BUCKET", None)

    print("== P2 默认路径零变更 ==")
    os.environ.pop("MDCG_RETRIEVAL_PIPELINE", None)
    r, meta = cg.search("dispatch")
    check("P2 默认（总开关未设）meta 无 gates 键",
          "gates" not in meta, json.dumps(meta, ensure_ascii=False, default=str)[:160])

    print("== P3 两路共享同一实现（同库同查询 gates 结构一致）==")
    base = MdCG(tempfile.mkdtemp(prefix="mdcg_gate_base_"))
    # 把同形状节点直接写进基类实例（经 add 共享落盘口径）
    for i in range(30):
        bucket = "swarm-dispatch" if i < 15 else "unrelated-cow"
        text = ("# 功能名：蜂群调度样本 %d\n# 正文：dispatch 调度内容样本 %d"
                % (i, i)) if i < 15 else \
               ("# 功能名：无关样本 %d\n# 正文：cow 内容样本 %d" % (i, i))
        base.add("mem_%03d" % i, text, layer="knowledge")
        e = base.index["nodes"]["mem_%03d" % i]
        e["bucket"] = bucket
        e["big_domain"] = "swarm" if i < 15 else "farm"
    base.flush()
    os.environ["MDCG_RETRIEVAL_PIPELINE"] = "1"
    os.environ["MDCG_GATE_S1B_BUCKET"] = "1"
    try:
        _, meta_os = cg.search("dispatch")
        _, meta_cg = base.search("dispatch")
        g_os, g_cg = meta_os.get("gates") or {}, meta_cg.get("gates") or {}
        check("P3a MdCGOS 与 MdCG 的 s1b 审计键集合一致",
              bool(g_os) and set(g_os) == set(g_cg),
              f"os={sorted(g_os)} cg={sorted(g_cg)}")
        check("P3b MdCG.search 自身收敛不回归（搬移未改行为）",
              meta_cg.get("scanned", 10**9) < 30,
              f"scanned={meta_cg.get('scanned')}")
    finally:
        os.environ.pop("MDCG_RETRIEVAL_PIPELINE", None)
        os.environ.pop("MDCG_GATE_S1B_BUCKET", None)

    print("== P4 覆写防悬空（病灶复发形态的结构守卫）==")
    src_os = inspect.getsource(MdCGOS.search)
    src_cg = inspect.getsource(MdCG.search)
    check("P4a MdCGOS.search 引用共享门控", "apply_retrieval_gates" in src_os)
    check("P4b MdCG.search 引用共享门控", "apply_retrieval_gates" in src_cg)
    check("P4c 共享函数存在且可调（两路 MRO 都能到达）",
          callable(apply_retrieval_gates))

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 → {', '.join(FAILS)}")
        return 1
    print(f"ALL OK: {PASS} 项（生产路径门控守卫全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
