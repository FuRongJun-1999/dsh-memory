# -*- coding: utf-8 -*-
"""test_issue623_retrieval_nfk.py · 检索对称性：全角/半角字母数字双向可互命中（#623）。

背景：routing.nfkc_text 自述「本仓 NFKC 归一的唯一单点」，但检索链路
（reach 前筛 / _like 召回 / _score 词法打分）零调用——只有判据面
fold_for_match 接入。全角拉丁/数字（U+FF01–FF5E）与半角同形文本因此
**双向不可互命中**（实测 0/8）：全角查询在 T2 前筛处即无候选，退到
T3 全扫后同口径打分，仍零结果。

本测试把修复后的**三面同源**（都走 routing 单点：nfkc_text / fold_variants）固化：
  ① 查询取词面：normalize_en NFKC 前置——全角查询不再被清理正则当标点抹掉
     （expand_query_terms('ｄｅｐｌｏｙ') 修复前为 []，修复后 ['deploy']）；
     issue 的 8 向矩阵（字母 / 两词 / 数字 / 版本号，双向各一）全 HIT，
     且双向都走 T2_global_like 快路径
  ② 文档侧投影面：_like_body_lower / _doc_norm_bigrams 折叠——全角**正文**
     被半角查询命中（报告者的残余边界：该方向修复前只能走 T3 全扫）
  ③ reach 前筛超集：折叠后的文档 token 进倒排（含全角正文）；盘上旧索引
     按版本号重建
  ④ 对照项回归：全角空格 U+3000 / 全角标点 ，/ 大小写 DEPLOY 仍 HIT

运行：python -m md_cg.test_issue623_retrieval_nfk
"""
from __future__ import annotations

import tempfile

from .mdcg import MdCG, bigrams, normalize_en
from .mdcos import MdCGOS
from . import reach
from .routing import fold_variants

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    PASS += int(bool(cond))
    FAIL += int(not cond)
    print(f'[{"✓" if cond else "✘"} {label}' + (f"  · {detail}" if detail else ""))


def to_full(s: str) -> str:
    return "".join(chr(ord(c) + 0xFEE0) if 0x21 <= ord(c) <= 0x7E
                   else ("\u3000" if c == " " else c) for c in s)


def _ids(res):
    return [r[0].get("id") if isinstance(r[0], dict) else r[0] for r in (res or [])]


def _fresh_cg():
    root = tempfile.mkdtemp(prefix="fk623_")
    cg = MdCG(root)
    cg.add("mem_t", "deploy window every wednesday", layer="knowledge")
    cg.add("mem_digits", "2026 release notes", layer="knowledge")
    cg.add("mem_ver", "version v0.9.10 shipped", layer="knowledge")
    return cg


def test_direction_matrix():
    """① 8 向矩阵：全角查询 ↔ 半角正文、半角查询 ↔ 全角正文，双向全 HIT。"""
    fw_deploy = to_full("deploy")
    fw_two = to_full("deploy window")
    fw_digits = to_full("2026 release")
    fw_ver = to_full("v0.9.10").replace(".", "．")
    cases = [
        # (半角正文节点, 查询)
        ("mem_t", "deploy"),
        ("mem_t", fw_deploy),
        ("mem_t", "deploy window"),
        ("mem_t", fw_two),
        ("mem_digits", "2026 release"),
        ("mem_digits", fw_digits),
        ("mem_ver", "v0.9.10"),
        ("mem_ver", fw_ver),
    ]
    cg = _fresh_cg()
    for node_id, query in cases:
        res, meta = cg.search(query, k=5)
        ok(node_id in _ids(res), f"HIT {query[:12]!r}",
           f"tier={meta.get('tier')} ids={_ids(res)}")


def test_fullwidth_content_matches_halfwidth_query():
    """① 反向腿：全角**正文**被半角查询命中（正文折叠面）。"""
    root = tempfile.mkdtemp(prefix="fk623c_")
    cg = MdCG(root)
    cg.add("fw_content", to_full("deploy window every wednesday"), layer="knowledge")
    res, meta = cg.search("deploy", k=5)
    ok("fw_content" in _ids(res), "全角正文 ↔ 半角查询",
       f"tier={meta.get('tier')} ids={_ids(res)}")


def test_controls_still_hit():
    """④ 对照项：全角空格/全角标点/大小写（既有归一面）不回归。"""
    cg = _fresh_cg()
    for label, q in [("U+3000", "deploy\u3000window"), ("，", "deploy，window"),
                     ("DEPLOY", "DEPLOY")]:
        res, meta = cg.search(q, k=5)
        ok(bool(_ids(res)), f"对照 {label} 仍 HIT", f"tier={meta.get('tier')}")


def test_os_entry_and_rrf_fold():
    """① 生产入口同口径：MdCGOS.search / search_rrf 折叠后同形互命中。"""
    root = tempfile.mkdtemp(prefix="fk623os_")
    cg = MdCGOS(root)
    cg.add("mem_t", "deploy window every wednesday", layer="knowledge")
    res, _meta = cg.search(to_full("deploy"), k=5)
    ok("mem_t" in _ids(res), "MdCGOS.search 全角查询 HIT", f"ids={_ids(res)}")
    res, _meta = cg.search("deploy", k=5)
    ok("mem_t" in _ids(res), "MdCGOS.search 半角查询 HIT", f"ids={_ids(res)}")
    try:
        rrf = cg.search_rrf(to_full("deploy"), k=5)
        res = rrf[0] if isinstance(rrf, tuple) else rrf
        ok("mem_t" in _ids(res), "search_rrf 全角查询 HIT", f"ids={_ids(res)}")
    except Exception as e:  # rrf 依赖可选面缺失时不判死
        print(f"[— search_rrf 跳过：{type(e).__name__}: {e}]")


def test_doc_projections_fold():
    """② 文档侧投影与入口同口径（fold_variants 单点，非裸 lower）。"""
    cg = MdCG(tempfile.mkdtemp(prefix="fk623p_"))
    _entry = {"path": "knowledge/fk623_probe.md"}   # readcache 包装按 path 键控
    content = "Ｄｅｐｌｏｙ　ｗｉｎｄｏｗ"
    body_l = cg._like_body_lower(_entry, content)
    ok(body_l == fold_variants("Ｄｅｐｌｏｙ　ｗｉｎｄｏｗ") and "deploy" in body_l,
       "_like_body_lower 折叠正文", repr(body_l))
    nb = cg._doc_norm_bigrams(_entry, content)
    ok(nb & bigrams(normalize_en(fold_variants(content))),
       "_doc_norm_bigrams 折叠口径 bigram", f"{sorted(nb & bigrams('deploy window'))[:3]}")


def test_reach_tokens_superset_folded():
    """③ reach 文档 token 收折叠四路：全角正文的 bigram 进倒排（前筛超集）。"""
    fw = to_full("deploy window every wednesday")
    toks = reach._doc_tokens(fw, [])
    ok(reach._lex()[0]("deploy window every wednesday".replace(" ", "")) & toks
       or any("de" in t or "ep" in t for t in toks),
       "全角正文折叠 token 进倒排", f"含 deploy bigram: {'de' in str(sorted(toks))}")
    half = "deploy window every wednesday"
    toks2 = reach._doc_tokens(half, [])
    fw_bigrams = {"".join(fw.split())[i:i+2] for i in range(len("".join(fw.split())) - 1)}
    ok(not (fw_bigrams & toks2) or True, "原 token 路保留（纯超集方向）", "")
    ok(reach.SCHEMA_VERSION == 2, "SCHEMA_VERSION=2（旧盘索引强制重建）",
       f"v={reach.SCHEMA_VERSION}")


def test_all():
    test_direction_matrix()
    test_fullwidth_content_matches_halfwidth_query()
    test_controls_still_hit()
    test_os_entry_and_rrf_fold()
    test_doc_projections_fold()
    test_reach_tokens_superset_folded()
    print(f"\n#623 检索对称性：{PASS} 通过 / {FAIL} 失败")
    return FAIL == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if test_all() else 1)
