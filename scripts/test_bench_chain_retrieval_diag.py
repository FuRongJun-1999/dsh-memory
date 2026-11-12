#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_bench_chain_retrieval_diag · 检索侧诊断量具的守卫（判别力 + 定点变异自证）

# 功能名：守卫 test_bench_chain_retrieval_diag
# 生效条件：修改 scripts/bench_chain_retrieval_diag.py 的判据（切值/名次/滞后代理/聚合）之后必跑
# 子功能：①用**合成小语料**（真值内生）断言判据有判别力：退役值排前的语料必须报高、现行值排前的必须报低
#         ②定点变异自证（4 条）：把判据的某个环节打坏，**同一份语料必须转红**——否则守卫自己红
# 执行：python scripts/test_bench_chain_retrieval_diag.py（脚本式，退出码 0/1）
# 验证方式：末行「通过 N / 失败 M」；变异段逐条打印「变异前 -> 变异后」读数
# 不适用条件：零外部依赖、不读官方 bench（官方口径可用时才额外校验一致，否则显式 SKIP 并给原因）；
#             本守卫**不**跑 md_cg 引擎（避免把重量级依赖拖进门禁），真引擎读数由量具本体给
"""
from __future__ import annotations

import contextlib
import importlib.util
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOL = os.path.join(_HERE, "bench_chain_retrieval_diag.py")

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))


def _load_tool():
    spec = importlib.util.spec_from_file_location("bench_chain_retrieval_diag", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)               # type: ignore[union-attr]
    return mod


diag = _load_tool()


def _norm(s) -> str:
    """与官方 probe_judge.norm 等价的兜底实现（去非词字符 + lower）。

    官方口径可用时由 `_check_official_norm` 校验二者一致；不可用时本实现独立成立。
    """
    return re.sub(r"\W+", "", "" if s is None else str(s)).lower()


@contextlib.contextmanager
def patched(mod, name, fn):
    old = getattr(mod, name)
    setattr(mod, name, fn)
    try:
        yield
    finally:
        setattr(mod, name, old)


# ---------------------------------------------------------------- 合成语料（真值内生）
# 三条链：现行值都在链尾；退役值取自 chain[:-1] 的 to（官方口径）。
SYNTH = [
    {   # A：检索面把**退役值**排在前面 —— 滞后代理必须报 1
        "qid": "syn-A", "chain_len": 5, "reconstructible": False, "legacy": False,
        "answer": {"value": "redis", "state": "active", "at_seq": 5,
                   "chain": [{"seq": 1, "from": None, "to": "redis"},
                             {"seq": 2, "from": "redis", "to": "lmdb"},
                             {"seq": 3, "from": "lmdb", "to": "badger"},
                             {"seq": 4, "from": "badger", "to": "bbolt"},
                             {"seq": 5, "from": "bbolt", "to": "redis"}]},
        "hits": ["依赖名曾改为 lmdb（历史记录）", "别的内容", "依赖名当前是 redis"],
        #         ↑ 退役值名次 1，现行值名次 3 ⇒ 退役优于现行
    },
    {   # B：检索面把**现行值**排在前面 —— 滞后代理必须报 0
        "qid": "syn-B", "chain_len": 12, "reconstructible": False, "legacy": False,
        "answer": {"value": "sqlite", "state": "active", "at_seq": 12,
                   "chain": [{"seq": 1, "from": None, "to": "redis"},
                             {"seq": 2, "from": "redis", "to": "sqlite"}]},
        "hits": ["依赖名当前是 sqlite", "依赖名曾为 redis（已退役）"],
    },
    {   # C：现行值与退役值落在**同一块** —— 同块不算「退役优于现行」（边界判据）
        "qid": "syn-C", "chain_len": 40, "reconstructible": True, "legacy": True,
        "answer": {"value": "bbolt", "state": "active", "at_seq": 40,
                   "chain": [{"seq": 1, "from": None, "to": "sled"},
                             {"seq": 2, "from": "sled", "to": "bbolt"}]},
        "hits": ["同时提到 sled 与 bbolt 的一段"],
    },
]


def _cases(rows):
    out = []
    for r in rows:
        cur, stales = diag.split_values(r["answer"], _norm)
        hits = [{"text": t, "score": 1.0 - 0.1 * i} for i, t in enumerate(r["hits"])]
        c = diag.diag_case(hits, cur, stales, _norm)
        c["qid"] = r["qid"]
        c["chain_len"] = r["chain_len"]
        out.append(c)
    return out


def _rate(rows):
    return diag.summarize(_cases(rows))["stale_beats_rate"]


def main() -> int:
    print("=== 守卫：检索侧诊断量具（合成小语料，真值内生） ===")

    print("\n[1] 切值判据（官方口径：退役值 = chain[:-1] 的 to，去掉现行值）")
    cur, stales = diag.split_values(SYNTH[0]["answer"], _norm)
    check("A 链现行值 = 链尾 to", cur == "redis", cur)
    check("A 链退役值 = {lmdb,badger,bbolt}（不含现行值）",
          stales == {"lmdb", "badger", "bbolt"}, sorted(stales))
    cur_c, stales_c = diag.split_values(SYNTH[2]["answer"], _norm)
    check("C 链退役值 = {sled}", stales_c == {"sled"}, sorted(stales_c))

    print("\n[2] 判别力：退役值排前 ⇒ 报高；现行值排前 ⇒ 报低")
    rate_a = _rate([SYNTH[0]])
    rate_b = _rate([SYNTH[1]])
    check("A（退役值第 1 / 现行值第 3）滞后代理率 = 1.0", rate_a == 1.0, rate_a)
    check("B（现行值第 1 / 退役值第 2）滞后代理率 = 0.0", rate_b == 0.0, rate_b)
    rate_c = _rate([SYNTH[2]])
    check("C（现行与退役同块）滞后代理率 = 0.0（同块不判「优于」）", rate_c == 0.0, rate_c)

    print("\n[3] 名次与得分读数")
    ca = _cases([SYNTH[0]])[0]
    check("A 现行值名次 = 3、得分 = 0.8", ca["cur_rank"] == 3 and abs(ca["cur_score"] - 0.8) < 1e-9,
          "rank=%s score=%s" % (ca["cur_rank"], ca["cur_score"]))
    check("A 退役值名次 = 1", ca["stale_rank"] == 1, ca["stale_rank"])
    cb = _cases([SYNTH[1]])[0]
    check("B 现行值名次 = 1、退役值名次 = 2", cb["cur_rank"] == 1 and cb["stale_rank"] == 2,
          "cur=%s stale=%s" % (cb["cur_rank"], cb["stale_rank"]))

    print("\n[4] 桶分布（用与官方同形的分桶函数）：A(5)=short / B(12)=mid / C(40)=long")
    bf = diag.__dict__.get("_bucket") if hasattr(diag, "_bucket") else None
    if bf is None:
        print("  [SKIP] 官方 _bucket 不在量具模块命名空间（应经 load_official 注入）——"
              "改用与官方同阈值的本地桩校验聚合面")
        def bf(x):
            return "short" if x <= 8 else ("mid" if x <= 30 else "long")
    items = [(r["chain_len"], c) for r, c in zip(SYNTH, _cases(SYNTH))]
    buckets = diag.by_bucket(items, bf)
    check("三桶恰好各落一题且数量为 1", [buckets[b]["n"] for b in ("short", "mid", "long")] == [1, 1, 1],
          {b: buckets[b]["n"] for b in buckets})
    check("long 桶（C 题）滞后代理率 = 0.0", buckets["long"]["stale_beats_rate"] == 0.0,
          buckets["long"]["stale_beats_rate"])
    check("short 桶（A 题）滞后代理率 = 1.0", buckets["short"]["stale_beats_rate"] == 1.0,
          buckets["short"]["stale_beats_rate"])

    print("\n[5] 端到端形状：朴素 BM25 真检索（零依赖臂）")
    bm = diag.NaiveBM25()
    bm.ingest([{"cid": "s1", "text": "依赖名曾改为 lmdb 的历史记录"},
               {"cid": "s2", "text": "依赖名当前是 redis"},
               {"cid": "s3", "text": "容量与回滚预案"}])
    hits = bm.retrieve("依赖名当前是什么值", k=3)
    check("BM25 返回 hits 带 cid/text/score", bool(hits) and all(
        {"cid", "text", "score"} <= set(h) for h in hits), hits[:2])
    check("BM25 hits 数 <= k", len(hits) <= 3, len(hits))

    print("\n[6] 定点变异自证（同一份语料，判据被打坏后**必须转红**）")

    def mut_split_empty(answer, norm):
        # 变异：把退役值集合算成空（**不**回调被替换后的 diag.split_values，否则自递归）
        return norm((answer or {}).get("value")), set()

    base_a = _rate([SYNTH[0]])
    with patched(diag, "split_values", mut_split_empty):
        after_a = _rate([SYNTH[0]])
    check("V1 变异「退役值集合=空」⇒ A 语料滞后率 1.0 → 0.0（判据有判别力）",
          base_a == 1.0 and after_a == 0.0, "before=%s after=%s" % (base_a, after_a))

    def mut_beats_false(hits, cur, stales, norm):
        d = dict(orig_diag_case(hits, cur, stales, norm))
        d["stale_beats_current"] = False      # 变异：恒不判「退役优于现行」
        return d

    orig_diag_case = diag.diag_case
    with patched(diag, "diag_case", mut_beats_false):
        after_a2 = _rate([SYNTH[0]])
    check("V2 变异「滞后判据恒 False」⇒ A 语料滞后率 1.0 → 0.0",
          base_a == 1.0 and after_a2 == 0.0, "before=%s after=%s" % (base_a, after_a2))

    def mut_beats_true(hits, cur, stales, norm):
        d = dict(orig_diag_case(hits, cur, stales, norm))
        d["stale_beats_current"] = True       # 变异：恒判「退役优于现行」
        return d

    base_b = _rate([SYNTH[1]])
    base_c = _rate([SYNTH[2]])
    with patched(diag, "diag_case", mut_beats_true):
        after_b = _rate([SYNTH[1]])
        after_c = _rate([SYNTH[2]])
    check("V3 变异「滞后判据恒 True」⇒ B 语料 0.0 → 1.0",
          base_b == 0.0 and after_b == 1.0, "before=%s after=%s" % (base_b, after_b))
    check("V3b 同变异 ⇒ C 语料（同块边界）0.0 → 1.0",
          base_c == 0.0 and after_c == 1.0, "before=%s after=%s" % (base_c, after_c))

    def mut_le(hits, cur, stales, norm):
        """变异：把「退役优于现行」的严格小于改成**小于等于**（同块也算优于）。"""
        d = dict(orig_diag_case(hits, cur, stales, norm))
        if d["stale_rank"] is not None and d["cur_rank"] is not None:
            d["stale_beats_current"] = d["stale_rank"] <= d["cur_rank"]
        return d

    with patched(diag, "diag_case", mut_le):
        after_c2 = _rate([SYNTH[2]])
        after_b3 = _rate([SYNTH[1]])
    check("V4 变异「同块也算优于」（< 改 <=）⇒ C 语料（同块边界）0.0 → 1.0",
          base_c == 0.0 and after_c2 == 1.0, "before=%s after=%s" % (base_c, after_c2))
    check("V4b 同变异对 B 语料（严格更靠后）无影响，仍 0.0",
          after_b3 == 0.0, "after=%s" % after_b3)

    print("\n[7] 官方口径一致性（可选用：找得到 bench 才校验，找不到显式 SKIP）")
    bench = os.environ.get("BENCH_CHAIN_DIR") or ""
    if bench and os.path.isfile(os.path.join(bench, "chain", "tools", "probe_judge.py")):
        _b, onorm = diag.load_official(bench)
        same = all(onorm(s) == _norm(s) for s in ("Redis ", "lmdb-1", " BBolt\n", None, ""))
        check("本地兜底 norm 与官方 probe_judge.norm 同口径", same, "BENCH_CHAIN_DIR=%s" % bench)
        check("官方 _bucket 边界：8→short / 9→mid / 30→mid / 31→long",
              (_b(8), _b(9), _b(30), _b(31)) == ("short", "mid", "mid", "long"),
              (_b(8), _b(9), _b(30), _b(31)))
    else:
        print("  [SKIP] 未设 BENCH_CHAIN_DIR 或该目录无 chain/tools/probe_judge.py —— "
              "官方口径一致性未校验（原因：本守卫零外部依赖，CI 无 bench 沙箱）")

    print("\n" + "=" * 68)
    print("通过 %d / 失败 %d" % (PASS, len(FAILS)))
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
