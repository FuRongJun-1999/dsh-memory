# -*- coding: utf-8 -*-
"""test_t15a_supersede —— E-T15a t1「新版覆盖旧版」确定性通道验收。

(A) 覆盖生效：写 v1 → 写 v2（同 key）⇒ 默认读取只返回 1 条（新值），
      旧节点 fm 里 superseded=true 且 superseded_by 指向新节点；
      include_superseded=True 时能同时看到 2 条。
      ⚠ 本段**显式开启** MDCG_JUDGMENT=1：覆盖开关同判定面开关
        （judgment_rules.is_enabled 真源），默认关——不显式打开时
        契约 3「默认关回归」（段 D）成立，[A] 就无从验证。
(B) 不该覆盖的边界：不同 key 仍各自成节点；同 key 但显式声明
      『并存』（supersede=False）不覆盖；空值/None 不触发覆盖；
      跨 key 前缀相似（'server.host' vs 'server.hostname') 不误盖。
(C) 契约不倒退：judgment_rules.judge_text 对既有 t09a/t11a/t18a 代表
      样本判定与既有期望一致。
(D) 默认关回归：覆盖开关未设/显式 0 时，同 key 二次写入仍 2 个节点、
      fm 无 superseded 字段夹带。

口径说明：
- 真 frontmatter 只能经 `kg.get(nid)["frontmatter"]` 取——索引条目
  （`kg.index["nodes"][nid]`）是扁平快照（path/layer/tags…），**没有**
  `frontmatter` 子字典，从索引取恒得 `{}`。
- 「旧节点被标记」必须走**包含口径**：默认口径下旧节点已被排除，用
  `kg.list_nodes(include_superseded=True)` 或经 `kg.get(旧 nid)` 读盘
  （get 是直读盘面，不受默认排除影响）。
- 节点计数用 `len(kg.list_nodes(...))`：默认口径=不含已废弃，包含
  口径=含之。按各断言本来意图选口径。

参考风格：md_cg/test_t11a_noise_drop.py / md_cg/test_t64a_dedup.py
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg import mdcg                      # noqa: E402
from md_cg.mdcos import MdCGOS              # noqa: E402
from md_cg import judgment_rules as jr      # noqa: E402

passed = failed = 0

# ── helper: 造一个临时库并返回 MdCGOS 实例 ──
def _mk_cg():
    return MdCGOS(tempfile.mkdtemp(prefix="mdcg_t15a_"))


# ── check wrapper ──
def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:300])


# ── 读取节点（默认不含已废弃） ──
def _read_default(cg, nid):
    """默认口径读取——不含已废弃节点。"""
    got = cg.get(nid)
    if not got:
        return None
    # 只在 fm 里检查 superseded=True 时才跳过
    fm = got.get("frontmatter") or {}
    if fm.get("superseded") is True:
        return None
    return got


# ── 读取节点（含已废弃） ──
def _read_include_superseded(cg, nid):
    """含已废弃口径读取——无论 superseded 如何均返回。"""
    return cg.get(nid)


# ── fm helper：经 get() 取真 frontmatter（索引里没有 fm） ──
def _fm(cg, nid):
    got = cg.get(nid)
    return (got or {}).get("frontmatter") or {}


# ── 取回某节点的列表条目（includes uperseded 口径） ──
def _row(cg, nid):
    for n in cg.list_nodes(include_superseded=True):
        if n.get("nid") == nid:
            return n
    return None


# ---------------------------------------------------------------------------
# [A] 覆盖生效
# ---------------------------------------------------------------------------

def test_a_overriding():
    print("[A] 覆盖生效：同 key 二次写入 → 默认只见新值，旧者被标记")
    # (a) 覆盖开关同 MDCG_JUDGMENT（judgment_rules.is_enabled 真源，默认关）——
    # 本段验证「覆盖生效」，故**显式打开**；finally 恢复原值，不污染他段。
    _env_prev = os.environ.get("MDCG_JUDGMENT")
    os.environ["MDCG_JUDGMENT"] = "1"
    try:
        # ── i. 默认口径：写 v1 → 写 v2 ⇒ 默认读只见新值 ──
        kg = _mk_cg()
        nid1 = kg.add("t15a_v1", "服务器 IP: 134.175.111.148",
                      topic="server.host")
        check("第一条写入成功：nid1=%s" % nid1, nid1 is not None)
        nid2 = kg.add("t15a_v2", "网关 IP: 100.73.185.0",
                      topic="server.host")
        check("第二条写入成功：nid2=%s" % nid2, nid2 is not None)

        # 默认读：应只返回新节点
        r1 = _read_default(kg, nid1)
        r2 = _read_default(kg, nid2)
        check("默认读只返回新节点（旧者被排除）",
              r2 is not None and r1 is None,
              "r1=%r r2=%r" % (r1, r2))

        # fm 里检查旧节点被标记（真 fm 从 kg.get 取；索引里没有 frontmatter）
        fm_old = _fm(kg, nid1)
        check("旧节点 fm 里 superseded=true",
              fm_old.get("superseded") is True,
              "fm=%s" % fm_old)
        check("旧节点 fm 里 superseded_by 指向新节点",
              fm_old.get("superseded_by") == nid2,
              "superseded_by=%s" % fm_old.get("superseded_by"))

        # ── ii. include_superseded=True 能同时看到 2 条 ──
        r_all = kg.list_nodes(include_superseded=True)
        ids_all = [n["nid"] for n in r_all]
        check("include_superseded=True 时能看到 2 条",
              nid1 in ids_all and nid2 in ids_all,
              "ids_all=%s" % str(ids_all)[:200])

        # ── iii. 读新节点返回新值 ──
        fm_new = _fm(kg, nid2)
        check("新节点 fm 无 superseded 字段",
              fm_new.get("superseded") is not True,
              "fm=%s" % fm_new)
        check("新节点正文反映新值",
              "网关 IP: 100.73.185.0" in (kg.get(nid2) or {}).get("content", ""),
              "content=%s" % (kg.get(nid2) or {}).get("content", "")[:100])

        # ── iv. 旧节点 fm 里同时有 superseded 和 superseded_by ──
        check("旧节点 fm 里有 superseded=true 且 superseded_by=<新 id>",
              fm_old.get("superseded") is True
              and fm_old.get("superseded_by") == nid2,
              "fm_old_keys=%s" % list(fm_old.keys()))

        # ── v. 节点计数：2 条写入变 1 条有效节点（默认口径，不含已废弃） ──
        node_count = len(kg.list_nodes())
        check("有效节点计数为 1（新者）",
              node_count == 1,
              "nodes=%d" % node_count)

    finally:
        if _env_prev is not None:
            os.environ["MDCG_JUDGMENT"] = _env_prev
        else:
            os.environ.pop("MDCG_JUDGMENT", None)


# ---------------------------------------------------------------------------
# [B] 不该覆盖的边界
# ---------------------------------------------------------------------------

def test_b_boundaries():
    print("[B] 不该覆盖的边界：不同 key / 显式并存 / 空值 / 跨 key 相似")
    # 边界段验的是「不该覆盖」——无论开关开或关，这些路径都不该覆盖。
    # 显式打开开关，使不该覆盖的路径仍在覆盖通道开启下被验证（覆盖判定
    # 只在开关开启时运行；关时不覆盖是段 D 的职责，不是本段的）。
    _env_prev = os.environ.get("MDCG_JUDGMENT")
    os.environ["MDCG_JUDGMENT"] = "1"
    try:
        # ── i. 不同 key 各自成节点 ──
        kg = _mk_cg()
        nid1 = kg.add("t15b_key1", "值A", topic="server.host")
        nid2 = kg.add("t15b_key2", "值B", topic="server.hostname")
        check("不同 key 仍各自成节点（2 节点）",
              len(kg.list_nodes(include_superseded=True)) == 2,
              "nodes=%d" % len(kg.list_nodes(include_superseded=True)))
        fm1 = _fm(kg, nid1)
        fm2 = _fm(kg, nid2)
        check("旧键 fm 无 superseded",
              fm1.get("superseded") is not True, "fm1=%s" % fm1)
        check("新键 fm 无 superseded",
              fm2.get("superseded") is not True, "fm2=%s" % fm2)

        # ── ii. 同 key 但显式声明 supersede=False 不覆盖 ──
        kg2 = _mk_cg()
        nid3 = kg2.add("t15b_store", "旧值", topic="server.host",
                       supersede=False)
        nid4 = kg2.add("t15b_new", "新值", topic="server.host",
                       supersede=False)
        check("显式声明不覆盖时仍 2 节点",
              len(kg2.list_nodes(include_superseded=True)) == 2,
              "nodes=%d" % len(kg2.list_nodes(include_superseded=True)))
        fm3 = _fm(kg2, nid3)
        fm4 = _fm(kg2, nid4)
        check("fm 里无 superseded 字段",
              fm3.get("superseded") is not True and fm4.get("superseded") is not True,
              "fm3_keys=%s fm4_keys=%s" % (list(fm3.keys()), list(fm4.keys())))

        # ── iii. 空值/None 不触发覆盖 ──
        kg3 = _mk_cg()
        nid5 = kg3.add("t15b_null", "服务器", topic="")   # 空 topic
        nid6 = kg3.add("t15b_null2", "存储", topic=None)  # None topic
        check("空/None topic 不触发覆盖，仍 2 节点",
              len(kg3.list_nodes(include_superseded=True)) == 2,
              "nodes=%d" % len(kg3.list_nodes(include_superseded=True)))
        fm5 = _fm(kg3, nid5)
        fm6 = _fm(kg3, nid6)
        check("fm 里无 superseded",
              fm5.get("superseded") is not True and fm6.get("superseded") is not True,
              "fm5=%s fm6=%s" % (fm5, fm6))

        # ── iv. 跨 key 前缀相似不误盖（'server.host' vs 'server.hostname'）──
        # 已在 i/1 中验证：不同 topic key 互不影响

    finally:
        if _env_prev is not None:
            os.environ["MDCG_JUDGMENT"] = _env_prev
        else:
            os.environ.pop("MDCG_JUDGMENT", None)


# ---------------------------------------------------------------------------
# [C] 契约不倒退
# ---------------------------------------------------------------------------

def test_c_contract():
    print("[C] 契约不倒退：judgment_rules 对既有样本判定不变")
    # t09a/t11a/t18a 代表样本——逐条断言 judge_text 结果一字不变
    # 只读判定面，不改动它

    # t09a 样本
    t09a_samples = (
        ("给我生成一份PDF", "J7", jr.DROP),
        ("把数据导出来给我", "J7", jr.DROP),
    )
    # t11a 样本
    t11a_samples = (
        ("npm error code ELIFECYCLE", "J9", jr.DROP),
        ("收到收到", "J9", jr.DROP),
    )
    # t18a 样本
    t18a_samples = (
        ("今天把 report.pdf 生成一下", "J7", jr.DROP),
        ("我讨厌你先讲道理，先接住我的情绪再说", "J1", jr.KEEP),
    )

    for label, samples in (("t09a", t09a_samples),
                           ("t11a", t11a_samples),
                           ("t18a", t18a_samples)):
        for t, judge, state in samples:
            v = jr.judge_text(t)
            check("%s 代表样本判定不变：%s → %s/%s" % (label, t, judge, state),
                  v.get("judge") == judge and v.get("state") == state,
                  jr.explain(v))

    # _PRIORITY 次序不动
    check("_PRIORITY 次序不动",
          jr._PRIORITY == ("J9", "J7", "J8", "J11", "J10",
                           "J1", "J2", "J3", "J4", "J5", "J6"),
          str(jr._PRIORITY))


# ---------------------------------------------------------------------------
# [D] 默认关回归
# ---------------------------------------------------------------------------

def test_d_default_fallback():
    print("[D] 默认关回归：覆盖开关未设/显式 0 → 同 key 仍 2 个节点")
    _env_prev = os.environ.get("MDCG_JUDGMENT")
    os.environ.pop("MDCG_JUDGMENT", None)
    try:
        # ── i. 未设 MDCG_JUDGMENT 时，同 key 二次写入仍 2 个节点 ──
        kg = _mk_cg()
        nid1 = kg.add("t15d_v1", "旧值", topic="server.host")
        nid2 = kg.add("t15d_v2", "新值", topic="server.host")
        check("未设开关时同 key 仍 2 个节点",
              len(kg.list_nodes(include_superseded=True)) == 2,
              "nodes=%d" % len(kg.list_nodes(include_superseded=True)))
        fm1 = _fm(kg, nid1)
        fm2 = _fm(kg, nid2)
        check("fm 无 superseded 字段",
              "superseded" not in fm1 and "superseded" not in fm2,
              "fm1_keys=%s fm2_keys=%s" % (list(fm1.keys()), list(fm2.keys())))

        # ── ii. 显式 MDCG_JUDGMENT=0 时同样回归 ──
        kg2 = _mk_cg()
        os.environ["MDCG_JUDGMENT"] = "0"
        try:
            nid3 = kg2.add("t15d_v3", "旧值", topic="server.host")
            nid4 = kg2.add("t15d_v4", "新值", topic="server.host")
            check("显式0时同 key 仍 2 个节点",
                  len(kg2.list_nodes(include_superseded=True)) == 2,
                  "nodes=%d" % len(kg2.list_nodes(include_superseded=True)))
            fm3 = _fm(kg2, nid3)
            fm4 = _fm(kg2, nid4)
            check("显式0时 fm 无 superseded",
                  "superseded" not in fm3 and "superseded" not in fm4,
                  "fm3_keys=%s fm4_keys=%s" % (list(fm3.keys()), list(fm4.keys())))
        finally:
            os.environ.pop("MDCG_JUDGMENT", None)

    finally:
        if _env_prev is not None:
            os.environ["MDCG_JUDGMENT"] = _env_prev


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    global passed, failed
    print("===== md_cg.test_t15a_supersede（E-T15a t1 新版覆盖旧版验收） =====")
    test_a_overriding()
    test_b_boundaries()
    test_c_contract()
    test_d_default_fallback()
    print("\n===== t15a supersede：%d 通过，%d 失败 =====" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
