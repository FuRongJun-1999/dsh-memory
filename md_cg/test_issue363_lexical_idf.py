# -*- coding: utf-8 -*-
# 功能名：缺省 lexical 路的真实打分（IDF 加权覆盖度，issue #363）
# 生效条件：python -X utf8 -m md_cg.test_issue363_lexical_idf [--mutate]；被测面＝md_cg/mdcg.py 的 idf_of / lexical_sim(df,n_docs) / MdCG._score 的 df 统计与透传
# 子功能：A 组＝缺陷行为面（同分退化 → 稀有 bigram 命中者居首、分数可分辨）；K 组＝非恒真对照（不传 df 的旧公式逐位不变、jaccard 不受影响、idf 与 bm25 同公式且随 df 单调降、同内容文档不产生虚假分差）；E 组＝判据单点（idf 算术全仓唯一、df 只在 _score 统计、透传在位）
# 执行：--mutate 时把修复逐条回退（撤 _score 的 df 透传 / 撤 lexical_sim 的 IDF 分支 / 把 idf 打成常量），守卫必须按指定项转红
# 验证方式：正向全部 PASS 且退出码 0；--mutate 下红项集合须与预期逐项相符（空集合即不合格），变异锚点未命中 ⇒ 退出码 2（fail-closed）
# 不适用条件：① 不判 Rust 侧（rust/src/retrieval.rs 的 legacy 公式未同步改，跨侧 rank_parity 由 scripts/rank_parity.py 的 jaccard 口径钉住，本件不覆盖）；② 不判 `_score` 之外的二文档比对（S5 负记忆抑制仍走不传 df 的旧公式，K1 只钉其不变）；③ 不判跨候选池的分数可比性（df 统计面＝本批 docs，跨批分数不可横比，已在 lexical_sim docstring 登记）；④ 不判冻结集 hit@k/MRR 的绝对量级（随语料浮动，只登记在报告里，不作断言）。
"""issue #363 守卫：缺省 lexical 路的真实打分（IDF 加权覆盖度）。

病象（修前，本守卫 A 组逐条复现）：
  查询「甲甲乙乙」在 40 条只含「甲甲」的干扰 + 1 条只含「乙乙」的稀有文档上，
  legacy 口径 `|q∩d|/|q|` 对 41 条文档全部给 0.333333 —— 分数只有 k/|q| 几个
  离散档，名次由 `(-score, -importance, id)` 的 id 兜底决定＝写入序：稀有命中
  的 z_rare 排第 41（探针实测 41/41，分数档数 1/41）。

修法（判据单点，不新造第二套分词口径）：
  · `idf_of(df, n_docs) = log1p((N-df+0.5)/(df+0.5))`——与 `md_cg/bm25.py`
    的 BM25 IDF 同一算术，全仓唯一实现；
  · `lexical_sim(..., df=, n_docs=)` 在 legacy 口径下走
    `Σ_{g∈q∩d} idf(g) / Σ_{g∈q} idf(g)`；**不传 df 时逐位保持旧公式**；
  · `MdCG._score` 按本批候选文档统计查询 bigram 的 df 并透传（与 bm25 的
    posting 面同为「当前候选池」口径，不扫全库）。

判别力来源（非恒真）：A1 修前 41 → 修后 1；A2 稀有分/常见分差 > 1e-3；
K1 旧公式逐位相等（防止「到处都变了」）；K4 同内容文档同分（防止「凭空分差」）；
E1/E4 单一实现（防止第二份 IDF 公式漂移）。
"""
from __future__ import annotations

import math
import os
import re
import sys
import tempfile
import types

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_TMP = tempfile.mkdtemp(prefix="iss363_")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "root")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "cd" * 32
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
for _k in ("MDCG_TOKEN", "MDCG_VERIFY_KEY", "MDCG_SCORE_MODE", "MDCG_UNIFY_QUERY",
           "MDCG_CN_GRAMS", "MDCG_READ_CACHE"):
    os.environ.pop(_k, None)

from md_cg import mdcg as _mdcg            # noqa: E402

PASS: list = []
FAIL: list = []


def ok(cond, msg, detail=""):
    (PASS if cond else FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(detail)) if (detail and not cond) else ""))
    return bool(cond)


# ---------------------------------------------------------------- 夹具

QUERY = "甲甲乙乙"
COMMON = "甲甲 记录 第%d条"
RARE = "乙乙 独特 内容"


def _build(cg_cls, root, n_common=40):
    cg = cg_cls(root)
    for i in range(n_common):
        cg.add("a_common%02d" % i, COMMON % i, layer="knowledge")
    cg.add("z_rare", RARE, layer="knowledge")
    cg.flush()
    return cg


def _search_rows(cg, k=41):
    res, meta = cg.search(QUERY, k=k, judge=False, record=False)
    return [(n["id"], float(s)) for n, s, _q in res], meta


def _fixture_readout(cg_cls, root):
    cg = _build(cg_cls, root)
    rows, meta = _search_rows(cg)
    ids = [i for i, _ in rows]
    scores = [s for _, s in rows]
    rank = ids.index("z_rare") + 1 if "z_rare" in ids else 0
    rare = scores[ids.index("z_rare")] if rank else 0.0
    common = max((s for i, s in rows if i.startswith("a_common")), default=0.0)
    return {"rank": rank, "rare": rare, "common": common,
            "levels": len({round(s, 12) for s in scores}), "n": len(rows),
            "meta": meta}


# ---------------------------------------------------------------- A 行为面

def group_a():
    print("== A 缺陷行为面：同分退化 → 稀有 bigram 命中者居首 ==")
    r = _fixture_readout(_mdcg.MdCG, os.path.join(_TMP, "a1"))
    print("    读数：rank=%s/%s rare=%.6f common=%.6f levels=%s"
          % (r["rank"], r["n"], r["rare"], r["common"], r["levels"]))
    ok(r["n"] == 41, "A0 夹具非空转：41 条文档全部参与打分（正对照）", r["n"])
    ok(r["rank"] == 1,
       "A1 稀有 bigram（只出现在 1/41 文档）命中者居首（修前 rank=41，写入序兜底）",
       "rank=%s" % r["rank"])
    ok(r["rare"] - r["common"] > 1e-3,
       "A2 稀有/常见命中分数可分辨（修前逐位相同 0.333333）",
       "rare=%r common=%r" % (r["rare"], r["common"]))
    ok(r["levels"] >= 2, "A3 分数档数 > 1（修前 1/41：整批同分）", r["levels"])


# ---------------------------------------------------------------- K 非恒真对照

def group_k():
    print("== K 非恒真对照：旧公式 / jaccard / idf 公式 / 无虚假分差 ==")
    qb = {"甲甲", "乙乙", "甲乙"}
    nb = {"甲甲", "甲乙"}
    # K1 不传 df ⇒ 旧公式逐位不变（S5 等二文档比对路径）
    ok(_mdcg.lexical_sim(qb, nb) == len(qb & nb) / len(qb),
       "K1 不传 df 时 legacy 仍是 |q∩d|/|q|（旧公式逐位不变）",
       _mdcg.lexical_sim(qb, nb))
    ok(_mdcg.lexical_sim(set(), nb) == 0.0 and _mdcg.lexical_sim(qb, set()) == 0.0,
       "K1b 空集合恒 0.0（边界不因 IDF 改变）")
    # K2 jaccard 不受 df 影响
    df = {"甲甲": 40, "乙乙": 1, "甲乙": 40}
    ok(_mdcg.lexical_sim(qb, nb, mode="jaccard", df=df, n_docs=41)
       == len(qb & nb) / len(qb | nb),
       "K2 jaccard 口径不因传入 df 改变（口径隔离）")
    # K3 idf 与 bm25 同公式
    for d in (0, 1, 20, 40, 41):
        want = math.log1p((41 - d + 0.5) / (d + 0.5))
        got = _mdcg.idf_of(d, 41)
        ok(abs(got - want) < 1e-15,
           "K3 idf_of(df=%d, N=41) 与 bm25 公式逐位一致" % d, (got, want))
    ok(_mdcg.idf_of(0, 41) > _mdcg.idf_of(20, 41) > _mdcg.idf_of(40, 41),
       "K3b idf 随 df 单调递减（高频 bigram 权重更低）")
    ok(_mdcg.idf_of(5, 0) == 0.0, "K3c N=0 时 idf 恒 0（不猜测）")
    # K4 同内容文档不得产生虚假分差
    ok(_mdcg.lexical_sim(qb, nb, df=df, n_docs=41)
       == _mdcg.lexical_sim(qb, nb, df=df, n_docs=41),
       "K4 同一输入同分（打分是纯函数）")
    root = os.path.join(_TMP, "k4")
    cg = _mdcg.MdCG(root)
    for i in range(6):
        cg.add("dup%d" % i, "丙丙 同样内容", layer="knowledge")
    cg.flush()
    # 用与内容同词的查询（有 LIKE 命中 ⇒ 走真实打分路径，而不是 0 分兜底池）
    rows = [(n["id"], float(s)) for n, s, _q in
            cg.search("丙丙", k=6, judge=False, record=False)[0]]
    ok(len(rows) == 6 and len({round(s, 12) for _, s in rows}) == 1,
       "K4b 同内容文档分数逐位相同（IDF 不制造虚假分差）",
       [s for _, s in rows])
    # K5 不传 df 与传 df 的结果不同（否则 A 组可能只是恒真）
    ok(_mdcg.lexical_sim(qb, nb, df=df, n_docs=41) != _mdcg.lexical_sim(qb, nb),
       "K5 传 df 确实改变分数（A 组读数非恒真）",
       (_mdcg.lexical_sim(qb, nb, df=df, n_docs=41), _mdcg.lexical_sim(qb, nb)))


# ---------------------------------------------------------------- E 判据单点

def group_e():
    print("== E 判据单点：idf 算术唯一 / df 只在本批统计 / 透传在位 ==")
    src = open(os.path.join(_HERE, "mdcg.py"), encoding="utf-8").read()
    ok(src.count("def idf_of(") == 1, "E1 idf_of 在 mdcg.py 恰定义一次")
    ok(len(re.findall(r"log1p\(\(n_docs - df \+ 0\.5\) / \(df \+ 0\.5\)\)", src)) == 1,
       "E2 IDF 算术在 mdcg.py 恰出现一次（无第二份副本）")
    ok("df=_df, n_docs=_n_docs" in src,
       "E3 _score 把本批 df 透传给 lexical_sim（缺此透传 ⇒ IDF 不生效）")
    ok("for _nb in _nbs:" in src and "_df.get(_g, 0) + 1" in src,
       "E4 df 统计面＝本批候选文档（不扫全库、不读盘）")
    bm = open(os.path.join(_HERE, "bm25.py"), encoding="utf-8").read()
    ok("(count - len(self.post[term]) + 0.5) / (len(self.post[term]) + 0.5)" in bm,
       "E5 与 bm25.py 的 IDF 算术同源（同一公式，两处同形）")


# ---------------------------------------------------------------- 变异

_MUTATIONS = (
    ("M1 撤 _score 的 df 透传（IDF 不再生效）",
     "            sim = lexical_sim(qb, nb, mode, df=_df, n_docs=_n_docs)",
     "            sim = lexical_sim(qb, nb, mode)",
     ("A1", "A2", "A3")),
    ("M2 撤 lexical_sim 的 IDF 分支（回退旧公式）",
     "    if df is not None and n_docs:",
     "    if False:  # MUT",
     ("A1", "A2", "A3", "K5")),
    ("M3 idf 打成常量 1.0（有分支但无判别力 ⇒ 退化为旧公式）",
     "    return math.log1p((n_docs - df + 0.5) / (df + 0.5))",
     "    return 1.0  # MUT",
     ("A1", "A2", "A3")),
)


def _mutant(patches, name):
    src = open(os.path.join(_HERE, "mdcg.py"), encoding="utf-8").read()
    for a, b in patches:
        if a not in src:
            print("ANCHOR-MISS: %r" % a[:70])
            return None
        src = src.replace(a, b, 1)
    mod = types.ModuleType("md_cg._mdcg_" + name)
    mod.__package__, mod.__file__ = "md_cg", os.path.join(_HERE, "mdcg.py")
    exec(compile(src, "<mutant:%s>" % name, "exec"), mod.__dict__)   # noqa: S102
    return mod


def group_mutate():
    print("== 变异：修复回退 ⇒ 指定项必须转红 ==")
    base = _fixture_readout(_mdcg.MdCG, os.path.join(_TMP, "m_base"))
    base_ok = {"A1": base["rank"] == 1,
               "A2": base["rare"] - base["common"] > 1e-3,
               "A3": base["levels"] >= 2,
               "K5": _mdcg.lexical_sim({"甲甲", "乙乙", "甲乙"}, {"甲甲", "甲乙"},
                                       df={"甲甲": 40, "乙乙": 1, "甲乙": 40},
                                       n_docs=41)
               != _mdcg.lexical_sim({"甲甲", "乙乙", "甲乙"}, {"甲甲", "甲乙"})}
    bad = 0
    for title, a, b, expect in _MUTATIONS:
        mod = _mutant([(a, b)], title.split()[0])
        if mod is None:
            bad += 1
            continue
        reds = set()
        try:
            if "A" in "".join(expect):
                r = _fixture_readout(mod.MdCG, os.path.join(
                    _TMP, "m_" + title.split()[0]))
                if not (r["rank"] == 1):
                    reds.add("A1")
                if not (r["rare"] - r["common"] > 1e-3):
                    reds.add("A2")
                if not (r["levels"] >= 2):
                    reds.add("A3")
            if "K5" in expect:
                if mod.lexical_sim({"甲甲", "乙乙", "甲乙"}, {"甲甲", "甲乙"},
                                   df={"甲甲": 40, "乙乙": 1, "甲乙": 40},
                                   n_docs=41) == mod.lexical_sim(
                                       {"甲甲", "乙乙", "甲乙"}, {"甲甲", "甲乙"}):
                    reds.add("K5")
        except Exception as exc:            # 变异导致崩溃也算转红（指名到项）
            print("    变异 %s 崩溃：%r" % (title, exc))
            reds |= set(expect)
        print("    %s → 红项=%s（预期 %s）" % (title, sorted(reds), list(expect)))
        ok(reds == set(expect) and bool(reds),
           "变异 %s 的红项集合与预期逐项相符" % title.split()[0],
           sorted(reds))
        bad += 0 if reds == set(expect) else 1
    ok(all(base_ok.values()), "M0 正向基线自证（变异前的读数确实成立）", base_ok)
    return bad


def main():
    print("=== issue #363 守卫：缺省 lexical 路的真实打分（IDF）===")
    mutate = "--mutate" in sys.argv
    group_a()
    group_k()
    group_e()
    if mutate:
        bad = group_mutate()
        if bad:
            FAIL.append("变异段 %d 条不合格" % bad)
    print("\n通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：" + "；".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
