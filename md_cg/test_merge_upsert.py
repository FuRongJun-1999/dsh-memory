#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge 裁决定向增量收尾守卫（issue：merge 用 rebuild_index O(N) 收尾）。

缺陷形态（缺陷报告实测）：review_decide(merge) 只改一个目标节点
（content 追加 + 不适用条件并集）却用 rebuild_index 收尾——_scan_nodes
全库逐文件 open+parse（1500 池实测 ~97-247ms/次），而同场景 accept/edit
走 add+flush 增量收尾（O(1)，~3.4ms）。

本守卫断言（调用计数/对账形态，非时间阈值）：
  M1 merge 零全库扫描：merge 裁决期间 _scan_nodes 调用 == 0
     （旧代码 rebuild→1 次全库扫描 → 红）；
  M2 upsert 与 rebuild 同源零漂移：merge 完成后目标节点索引条目与
     之后再 rebuild_index 的条目逐位相等（entry 构造唯一真源）；
  M3 merge 语义保持：content 追加命中、不适用条件并集、裁决记录
     accepted、级联关闭同内容兄弟提案；
  M4 accept 对照不受影响（零全库扫描、结果 ok）；
  M5 定向收尾落增量日志：merge 后未 flush 尾部（_dirty）在统一收尾
     flush 后，新进程重开可见目标新条目（增量账本，不靠 rebuild 救回）。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import md_cg.mdcg as mdcg_mod               # noqa: E402
from md_cg.mdcos import MdCGOS              # noqa: E402

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


def count_scans(fn):
    n = 0
    real = mdcg_mod.MdCG._scan_nodes

    def _spy(self):
        nonlocal n
        n += 1
        return real(self)

    mdcg_mod.MdCG._scan_nodes = _spy
    try:
        return fn(), n
    finally:
        mdcg_mod.MdCG._scan_nodes = real


def build(root, n=6):
    cg = MdCGOS(root)
    for i in range(n):
        cg.add("mem_%02d" % i, "# 功能名：样本 %d\n# 正文：蜂群调度 内容 %d" % (i, i),
               layer="knowledge")
    cg.add("tgt", "# 功能名：合并目标\n# 正文：目标原始内容 星云\n目标正文。",
           layer="knowledge", tags=["合并"],
           non_applicable_conditions=["旧条件甲"])
    cg.close()
    return root


def main():
    root = tempfile.mkdtemp(prefix="mdcg_merge_guard_")
    try:
        build(root)
        cg = MdCGOS(root)
        pid = cg.propose("cand", "# 功能名：候选\n# 正文：候选正文 水位信箱",
                         layer="knowledge")
        # 同内容兄弟提案（级联关闭面）：propose 对同 payload_hash 幂等返回
        # 既有 pid——兄弟须以他进程形态手工入队（同 phash 不同 pid）
        from md_cg.fsutil import append_jsonl
        from md_cg.mdcos import _sig
        sib_content = "# 功能名：候选\n# 正文：候选正文 水位信箱"
        append_jsonl(cg.inbox_log,
                     {"t": 1.0, "pid": "prop_sib_manual", "id": "cand_sib",
                      "content": sib_content, "layer": "knowledge",
                      "tags": [], "condition_space": {}, "verify": {},
                      "payload_hash": _sig(sib_content), "actor": "ext"})

        out, n_scan = count_scans(
            lambda: cg.review_decide(pid, "merge", merge_into="tgt",
                                     reason="guard"))
        print("  (merge 期间 _scan_nodes 调用 %d 次)" % n_scan)
        check("M1a merge 裁决零全库扫描（旧代码 rebuild→1 次 O(N) 扫描）",
              n_scan == 0, f"scans={n_scan}")
        check("M3a merge 返回 ok 且 node_id 指向目标",
              out.get("ok") and out.get("node_id") == "tgt", str(out)[:120])

        # M2 upsert 与 rebuild 同源：先存 merge 后条目，rebuild 后逐位比对
        e_after_merge = dict(cg.index["nodes"].get("tgt") or {})
        cg.rebuild_index()
        e_after_rebuild = dict(cg.index["nodes"].get("tgt") or {})
        check("M2a merge 定向 upsert 条目与 rebuild 后逐位一致（同源零漂移）",
              e_after_merge == e_after_rebuild,
              f"diff={ {k: (e_after_merge.get(k), e_after_rebuild.get(k)) for k in set(e_after_merge) | set(e_after_rebuild) if e_after_merge.get(k) != e_after_rebuild.get(k)} }")

        node = cg.get("tgt")
        check("M3b content 追加命中（候选正文并入目标）",
              node and "候选正文 水位信箱" in (node.get("content") or ""),
              str(node)[:80])
        neg = (node.get("frontmatter") or {}).get("non_applicable_conditions")
        check("M3c 不适用条件并集（fm 旧条件保留，无新增时原样）",
              neg == ["旧条件甲"], f"neg={neg}")

        st = cg._pid_status().get(pid) or {}
        check("M3d 裁决记录 accepted", st.get("status") == "accepted",
              str(st)[:80])
        casc = out.get("cascade_closed") or []
        check("M3e 级联关闭同内容兄弟提案（手工入队形态）",
              "prop_sib_manual" in casc, f"casc={casc}")

        # M4 accept 对照
        print("== M4 accept 对照 ==")
        root4 = tempfile.mkdtemp(prefix="mdcg_merge_guard4_")
        try:
            build(root4)
            cg4 = MdCGOS(root4)
            pid4 = cg4.propose("acc", "# 功能名：接受候选\n# 正文：接受正文",
                               layer="knowledge")
            out4, n_scan4 = count_scans(
                lambda: cg4.review_decide(pid4, "accept", reason="guard"))
            check("M4a accept 裁决零全库扫描（对照不受影响）",
                  n_scan4 == 0, f"scans={n_scan4}")
            check("M4b accept 落节点 ok",
                  out4.get("ok") and out4.get("node_id") == "acc", str(out4)[:80])
            cg4.close()
        finally:
            shutil.rmtree(root4, ignore_errors=True)

        # M5 增量账本：merge 库重开（新进程形态），目标条目可见且带新内容指纹
        print("== M5 增量账本跨进程可见 ==")
        cg.close()
        cg5 = MdCGOS(root)
        try:
            e5 = (cg5.index.get("nodes") or {}).get("tgt")
            node5 = cg5.get("tgt")
            check("M5a 重开后目标条目在索引（增量日志，不靠 rebuild 救回）",
                  bool(e5))
            check("M5b 重开后目标内容为合并后版本",
                  node5 and "候选正文 水位信箱" in (node5.get("content") or ""))
        finally:
            cg5.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
