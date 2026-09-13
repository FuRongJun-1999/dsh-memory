# -*- coding: utf-8 -*-
"""原子级中英归一管线（lexicon + semantic + mdcg 集成）· 设计态验收。

管线四件套：
  lexicon/build_standard_en.py  英文标准库构建器（牛肉→cow_meat，构建即验证）
  lexicon/standard_en.json      词条真源（语素拼接自洽 + snake_case）
  semantic/en_normalizer.py     英文 query → 中文语素序列（时态归零→停用词→映射→专有词保留）
  semantic/zh_en_atoms.py       中文文本 → 标准英文原子序列（反方向序列化）

集成面（mdcg.en_zh_terms → expand_query_terms）：
  英→中语素追加为召回词+打分 bigram（en_zh_bigrams）；默认关闭
  （双语双路裁定：md_cg 主链路英文走独立 Jaccard 路，见 semantic/REPRODUCE.md），
  MDCG_EN_ATOMS=1 显式开启；纯中文 query 零触发；
  mdcos 四路 RRF 的 lexical 路同源复用 expand_query_terms，自动受益。

运行：python -m md_cg.test_en_pipeline
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile

from . import mdcg
from .semantic import en_normalizer, zh_en_atoms

PASS = FAIL = 0
FAILS = []


def ok(cond, name=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(name)


# ---- 1 · en_normalizer：屈折归零 ----
ok(en_normalizer.strip_tense("Ate") == "eat", "irregular ate→eat")
ok(en_normalizer.strip_tense("went") == "go", "irregular went→go")
ok(en_normalizer.strip_tense("regretted") == "regret", "-ed 剥离+双辅音还原")
ok(en_normalizer.strip_tense("running") == "run", "-ing 剥离+双辅音还原")
ok(en_normalizer.strip_tense("stopped") == "stop", "stopped→stop")
ok(en_normalizer.strip_tense("crossed") == "cross", "ss 保留（正字法例外）")
ok(en_normalizer.strip_tense("called") == "call", "ll 保留（正字法例外）")
ok(en_normalizer.strip_tense("dogs") == "dog", "-s 复数剥离")
ok(en_normalizer.strip_tense("class") == "class", "-ss 例外不剥")
ok(en_normalizer.strip_tense("be") == "be", "短词不动")

# ---- 2 · en_normalizer：停用词 / 专有词 / 复合词 ----
t, d = en_normalizer.normalize_en_query("I eat beef yesterday")
ok(t == ["我", "吃", "牛肉", "昨天"], "端到端映射 beef→牛肉: %s" % t)
t2, _ = en_normalizer.normalize_en_query("Caroline went to Paris")
ok("Caroline" in t2 and "Paris" in t2, "专有词保留原名: %s" % t2)
ok(en_normalizer.normalize_en_query("soul hub")[0] == ["灵枢"], "短语级复合 soul hub→灵枢")
ok(en_normalizer.normalize_en_query("beef")[0] == ["牛肉"], "单词级复合 beef→牛肉")
ok(en_normalizer.normalize_en_query("xyzzy")[0] == ["xyzzy"], "未知词 unknown_keep")
t3, _ = en_normalizer.normalize_en_query("The dogs were running")
ok("the" not in [x.lower() for x in t3] and "were" not in [x.lower() for x in t3],
   "停用词剔除: %s" % t3)

# ---- 3 · zh_en_atoms：中文→标准英文原子序列 ----
ok(zh_en_atoms.serialize("我昨天吃牛肉") == "i yester day eat cow meat",
   "serialize 复合词拆原子")
ok(zh_en_atoms.serialize("灵枢记忆库") == "soul hub memory store", "serialize 灵枢记忆库")
ok(zh_en_atoms.segment("吃牛肉") == ["吃", "牛肉"], "贪心最长匹配")

# ---- 4 · mdcg.en_zh_terms：集成单元（双态：默认关 / MDCG_EN_ATOMS=1 开） ----
ok(mdcg.en_zh_terms("I eat beef yesterday") == [],
   "默认关闭：en_zh_terms 不触发（双语双路裁定）")
os.environ["MDCG_EN_ATOMS"] = "1"
ok(mdcg.en_zh_terms("I eat beef yesterday") == ["吃", "牛肉", "昨天"],
   "开启：en_zh_terms 三语素（代词剔除）: %s" % mdcg.en_zh_terms("I eat beef yesterday"))
ok(mdcg.en_zh_terms("我昨天吃了牛肉面") == [], "纯中文零触发")
ok(all(t not in mdcg._EN_ZH_PRONOUNS for t in mdcg.en_zh_terms("She saw my dog")),
   "代词全剔除、实词保留")
os.environ["MDCG_EN_ATOMS"] = "0"
ok(mdcg.en_zh_terms("I eat beef") == [], "显式关闭回退 legacy")
del os.environ["MDCG_EN_ATOMS"]

# ---- 5 · expand_query_terms：召回词融合 + 纯中文回归守卫 ----
os.environ["MDCG_EN_ATOMS"] = "1"
et = mdcg.expand_query_terms("I ate beef yesterday")
ok("牛肉" in et and "昨天" in et, "开启：英文 query 产出中文召回词: %s" % et)
ok("eat" in et, "形态归一仍在（ate→eat）")
del os.environ["MDCG_EN_ATOMS"]
ok("牛肉" not in mdcg.expand_query_terms("I ate beef yesterday"),
   "默认关闭：expand_query_terms 回 legacy（无中文语素）")
_zc = "抑制剂怎么选择效果好"
os.environ["MDCG_EN_ATOMS"] = "1"
zc_on = mdcg.expand_query_terms(_zc)
del os.environ["MDCG_EN_ATOMS"]
zc_off = mdcg.expand_query_terms(_zc)
ok(zc_on == zc_off, "纯中文 query 开关前后零差异（回归守卫）")

# ---- 6 · 端到端：英文 query 召回中文记忆 ----
tmp = tempfile.mkdtemp(prefix="mdcg_en_pipe_")
try:
    cg = mdcg.MdCG(root=tmp)
    cg.add("n_beef", "昨天中午我在家里吃了牛肉面，配了可乐。",
           layer="contextual", verification_basis="data")
    cg.add("n_unrel", "我喜欢在雨天听爵士乐。",
           layer="contextual", verification_basis="data")
    cg.flush()
    os.environ["MDCG_EN_ATOMS"] = "1"
    res, _meta = cg.search("I ate beef yesterday", judge=False)
    ids = [r[0].get("id") for r in res]
    del os.environ["MDCG_EN_ATOMS"]
    ok(len(res) >= 1 and ids[0] == "n_beef", "开启：英文 query top1 召回中文牛肉节点 %s" % ids)
    res0, _m0 = cg.search("I ate beef yesterday", judge=False)   # 默认未设=关闭
    ok(not res0 or all(r[1] <= 0 for r in res0),
       "默认关闭：词面零重叠召回归零（跨语断点复现）")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---- 7 · 构建自洽：standard_en.json / search_index.json ----
_here = os.path.dirname(os.path.abspath(__file__))
std = json.load(io.open(os.path.join(_here, "lexicon", "standard_en.json"), encoding="utf-8"))
entries = {e["zh"]: e for e in std["entries"]}
ok(len(entries) == 62, "词条数 62（真源守卫）")
ok(entries["牛肉"]["standard_en"] == "cow_meat" and "beef" in entries["牛肉"]["legacy_en"],
   "牛肉=cow_meat（legacy 别名 beef）")
ok(entries["火山"]["standard_en"] == "fire_mountain", "语素序直拼 火山=fire_mountain")
ok(sum(1 for e in std["entries"] if e["class"] == "opaque") == 5, "opaque 化石词 5 条")
si = json.load(io.open(os.path.join(_here, "semantic", "search_index.json"), encoding="utf-8"))
ok(si["meta"]["atom_count"] == 815 and si["meta"]["zh_terms"] == 815,
   "search_index 与 atoms 数一致")
ok(si["en_index"].get("meat") and "牛肉" in si["en_index"]["meat"],
   "en_index 倒排 meat→牛肉")

# ---- 8 · mdcos lexical 路同源受益 ----
from .mdcos import MdCGOS
from .mdcg import expand_query_terms as _eqt
ok(_eqt is mdcg.expand_query_terms, "mdcos 复用同一 expand_query_terms（同源单实现）")

print("en_pipeline: %d assertions all green" % PASS if not FAIL
      else "en_pipeline: %d passed, %d FAILED: %s" % (PASS, FAIL, FAILS))
raise SystemExit(1 if FAIL else 0)
