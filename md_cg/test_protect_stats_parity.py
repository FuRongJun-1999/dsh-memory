# -*- coding: utf-8 -*-
# 功能名：protect.stats 的条目口径等价性 + 性能护栏（全库逐节点读盘 → 索引遍历）
# 生效条件：python -X utf8 -m md_cg.test_protect_stats_parity；被测面＝md_cg/protect.py 的 is_protected_entry / is_immutable_entry / stats
# 子功能：①合成库覆盖各判定分支（层保护 / 显式位 / 按分保护 hint / heuristic 不触发 / self_state 豁免不可覆盖 / 显式 immutable）②逐节点断言条目口径 == cg 口径 ③断言 stats() 与「逐节点 cg 口径」五字段逐位相同 ④性能护栏：2000 节点 stats() < 1s（回退成逐节点读盘即转红）
# 执行：构造隔离库 → 逐节点比对两个口径 → 逐位比对 stats 五字段 → 计时护栏
# 验证方式：全部 PASS 即 exit 0；否则 exit 1（逐条打印读数）
# 不适用条件：不判真实库的冷热态差异（那是磁盘/杀软首扫，属环境）；不判 stats 返回的 ids 排序（无排序契约）
"""protect.stats 条目口径等价性守卫（#XXX · 2026-10-27）。

病象：`protect.stats()` 对全库逐节点调 `is_protected(cg, nid)` / `is_immutable(cg, nid)`，
两者内部都 `_fm()` **读盘取 frontmatter** ⇒ 在役库 32398 节点冷态实测 **310 秒**；
该函数经 `health_os()` 的 `protection` 段被 `cg(op=info)` 无条件调用，而 UI 概览页首屏
就发 `cg({op:"info"})` ⇒ 首屏卡 5 分钟（用户现场：「读取认知图太慢/像卡死」）。

修法：判定逻辑本就与 `_fm` 无关，只需 layer / protected / protection_reason /
importance / importance_source / self_state / immutable 七个字段——索引条目全带。
故 `stats()` 改走**条目口径**（`is_protected_entry` / `is_immutable_entry`）：
实测 0.015 秒（快约 2 万倍），且与 cg 口径全量比对 **0 差异**。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import protect
from md_cg.mdcg import MdCG

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


#: 覆盖各分支的夹具：(node_id, kwargs)
_CASES = (
    ("p_plain", dict(layer="knowledge", importance=0.5)),
    ("p_imp_none", dict(layer="knowledge", importance=0.9)),
    ("p_imp_hint", dict(layer="knowledge", importance=0.9, importance_source="hint")),
    ("p_imp_heur", dict(layer="knowledge", importance=0.9, importance_source="heuristic")),
    ("p_layer_self", dict(layer="self", importance=0.3)),
    ("p_explicit", dict(layer="knowledge", importance=0.2, protected=True,
                        protection_reason="人工保护")),
    ("p_immutable", dict(layer="knowledge", importance=0.2, immutable=True,
                         protection_reason="人工不可覆盖")),
    ("p_selfstate", dict(layer="self", importance=0.9, self_state=True)),
)


def _build(root, cases):
    cg = MdCG(root, autoflush=1)
    for nid, kw in cases:
        body = "# 功能名：%s\n# 生效条件：无条件\n# 执行：夹具\n# 验证方式：断言\n# 不适用条件：无" % nid
        try:
            cg.add(nid, body, verification_basis="test", **kw)
        except TypeError:
            cg.add(nid, body, verification_basis="test")
    return cg


def main():
    tmp = tempfile.mkdtemp(prefix="protect_stats_parity_")
    cg = _build(tmp, _CASES)

    print("== A 逐节点：条目口径 == cg 口径（八条分支夹具）")
    for nid, _kw in _CASES:
        e = cg.index["nodes"][nid]
        p_cg, w_cg = protect.is_protected(cg, nid)
        p_e, w_e = protect.is_protected_entry(e)
        ok(bool(p_cg) == bool(p_e), "A1 %s protected 两口径一致" % nid, (p_cg, p_e))
        ok((not p_cg) or (("importance=" in w_cg) == ("importance=" in w_e)),
           "A2 %s auto_by_importance 归因一致" % nid, (w_cg, w_e))
        i_cg, _ = protect.is_immutable(cg, nid)
        i_e, _ = protect.is_immutable_entry(e)
        ok(bool(i_cg) == bool(i_e), "A3 %s immutable 两口径一致" % nid, (i_cg, i_e))

    print("== B 分支确实被覆盖（防夹具全落同一分支的空转绿）")
    p = {nid: protect.is_protected(cg, nid)[0] for nid, _ in _CASES}
    im = {nid: protect.is_immutable(cg, nid)[0] for nid, _ in _CASES}
    ok(p["p_plain"] is False, "B1 普通节点不保护")
    ok(p["p_imp_none"] is True, "B2 缺省来源按分保护（importance=0.9）")
    ok(p["p_imp_hint"] is True, "B3 hint 来源按分保护")
    ok(p["p_imp_heur"] is False, "B4 heuristic 来源**不**按分保护（issue50-e）")
    ok(p["p_layer_self"] is True, "B5 self 层保护")
    ok(p["p_explicit"] is True, "B6 显式 protected 位")
    ok(im["p_immutable"] is True, "B7 显式 immutable 位")
    ok(im["p_selfstate"] is False and p["p_selfstate"] is True,
       "B8 self_state 卡：不可覆盖但不可遗忘")

    print("== C stats() 与「逐节点 cg 口径」五字段逐位相同")
    got = protect.stats(cg)
    by_layer, ids, auto, immutable = {}, [], 0, []
    for nid, e in cg.index["nodes"].items():
        pr, why = protect.is_protected(cg, nid)
        if pr:
            ids.append(nid)
            lay = str(e.get("layer") or "?")
            by_layer[lay] = by_layer.get(lay, 0) + 1
            if "importance=" in why or why.startswith("重要性保护"):
                auto += 1
        ifmm, _ = protect.is_immutable(cg, nid)
        if ifmm:
            immutable.append(nid)
    ok(got["protected_count"] == len(ids), "C1 protected_count", (got["protected_count"], len(ids)))
    ok(got["immutable_count"] == len(immutable), "C2 immutable_count",
       (got["immutable_count"], len(immutable)))
    ok(got["by_layer"] == by_layer, "C3 by_layer 逐位", (got["by_layer"], by_layer))
    ok(got["auto_by_importance"] == auto, "C4 auto_by_importance",
       (got["auto_by_importance"], auto))
    ok(sorted(got["ids"]) == sorted(ids), "C5 ids 集合相同")
    ok(sorted(got["immutable_ids"]) == sorted(immutable), "C6 immutable_ids 集合相同")

    print("== D 性能护栏：2000 节点 stats() < 1s（回退成逐节点读盘即转红）")
    big = tempfile.mkdtemp(prefix="protect_stats_big_")
    cg2 = MdCG(big, autoflush=200)
    for i in range(2000):
        body = "# 功能名：n%d\n# 生效条件：无条件\n# 执行：压测\n# 验证方式：计时\n# 不适用条件：无" % i
        kw = dict(layer="knowledge", importance=0.5)
        if i % 7 == 0:
            kw = dict(layer="knowledge", importance=0.9)
        cg2.add("perf_%04d" % i, body, verification_basis="test", **kw)
    t0 = time.time()
    out = protect.stats(cg2)
    dt = time.time() - t0
    ok(dt < 1.0, "D1 2000 节点 stats() < 1s（实测 %.3fs）" % dt, dt)
    ok(out["protected_count"] >= 200, "D2 压测库确有受保护节点（防空转）", out["protected_count"])

    print()
    print("protect.stats 口径等价与性能守卫：%d 通过 / %d 失败"
          % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项：")
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())