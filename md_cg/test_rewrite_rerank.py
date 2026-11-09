# -*- coding: utf-8 -*-
"""test_rewrite_rerank.py —— E 的判据（改写 + 重排 + vector 健康面）

判的是「改写真的进了检索」和「重排真的改了顺序」，不是「函数存在」：

  A1 关闭时 `terms()` 返回 []（MDCG_REWRITE=0）
  A2 缓存命中：第二次调用不再问 LLM（用假 llm 计数）
  A3 解析容错：带解释的回复也能抽出词；非法回复 → []
  A4 改写词真的进了 fuzzy 路的 expand（`_rw_terms` 被传下去）
  A5 LLM 抛异常时检索照常（不抛、结果仍非空）
  B1 `MDCG_RERANK=0`（缺省）时顺序不变
  B2 `MDCG_RERANK=1` 时按 LLM 打分重排（假 llm 把第 3 名抬到第 1）
  B3 重排失败原样返回
  C1 健康面出现 `vector` 段且 `eligible >= count`
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcos import MdCGSecure                    # noqa: E402
from md_cg.security import Principal                  # noqa: E402
from md_cg import rewrite                             # noqa: E402

PASS = []
FAIL = []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%-6s %s %s" % ("PASS" if cond else "FAIL", name, detail))


BODIES = {
    "kn_lat": "家里网络老卡顿：多半是无线信道拥塞或丢包，先换 5GHz 再测延迟。",
    "kn_mod": "星露谷 Mods 中文清理：批量合并 zh 字段，删重复 manifest。",
    "kn_tok": "灵枢令牌权限：ops_allow 被收窄后 self_state 会被拒。",
}


def mk(root):
    cg = MdCGSecure(root, principal=Principal(
        actor="dsh-memory", role="designer", tenant="default",
        clearance="private", can_write=True, can_admin=True), autoflush=8)
    for nid, b in BODIES.items():
        cg.add(nid, b, layer="knowledge", tags=["t"], importance=0.5)
    return cg


class FakeLLM(object):
    def __init__(self, payload, fail=False):
        self.payload = payload
        self.fail = fail
        self.calls = 0

    def __call__(self, prompt, role=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        return self.payload


def main():
    tmp = tempfile.mkdtemp(prefix="rewrite_")
    old_env = {k: os.environ.get(k) for k in ("MDCG_REWRITE", "MDCG_RERANK")}
    try:
        cg = mk(tmp)

        # A1 关闭
        os.environ["MDCG_REWRITE"] = "0"
        ok("A1 关闭时返回空", rewrite.terms("家里网络老卡顿", root=tmp) == [], "env=0")

        # A2 缓存命中（第一次问、第二次不问）
        os.environ["MDCG_REWRITE"] = "1"
        fake = FakeLLM(u'["丢包","延迟","信道","拥塞"]')
        orig = rewrite._ask
        rewrite._ask = fake
        t1 = rewrite.terms("无线为什么老是断", root=tmp)
        n_after_first = fake.calls
        t2 = rewrite.terms("无线为什么老是断", root=tmp)
        ok("A2 第二次不再问 LLM", fake.calls == n_after_first == 1, "calls=%d" % fake.calls)
        ok("A2b 词表一致", t1 == t2 == ["丢包", "延迟", "信道", "拥塞"], str(t1))

        # A3 解析容错
        rewrite._ask = FakeLLM(u'好的，这些词可能有用：["信道","丢包"] 希望有帮助')
        t3 = rewrite.terms("另一个问法呀", root=tmp)
        ok("A3 带解释也能抽出", t3 == ["信道", "丢包"], str(t3))
        rewrite._ask = FakeLLM(u'我拒绝回答这个问题')
        ok("A3b 非法回复返回空", rewrite.terms("第三个问法", root=tmp) == [], "garbage")

        # A6 只读缓存档：未预热不问模型、预热过直接命中（E 的缺省档）
        os.environ["MDCG_REWRITE"] = "cache"
        cnt = FakeLLM(u'["不该被调用"]')
        rewrite._ask = cnt
        rewrite._cache.clear()
        t6 = rewrite.terms("没人预热过的问法", root=tmp)
        ok("A6 cache 档未命中不问模型", t6 == [] and cnt.calls == 0,
           "terms=%r calls=%d" % (t6, cnt.calls))
        rewrite._save_disk(tmp, "预热过的问法", ["丢包", "延迟"])
        t6b = rewrite.terms("预热过的问法", root=tmp)
        ok("A6b cache 档命中预热结果", t6b == ["丢包", "延迟"] and cnt.calls == 0,
           str(t6b))
        os.environ["MDCG_REWRITE"] = "1"

        # A5 LLM 异常时检索照常
        rewrite._ask = FakeLLM(u'', fail=True)
        res, meta = cg.search_rrf("家里网络老卡顿怎么办", k=3, judge=False)
        ok("A5 LLM 挂了检索照常", isinstance(res, list) and bool(res), "results=%d" % len(res))

        # A4 改写词进了 fuzzy 路：直接盯 `_path_fuzzy` 收到的 expand 实参
        # （比看 meta 可靠——fuzzy 路本身可能一条都不产出）
        rewrite._ask = FakeLLM(u'["丢包","延迟"]')
        rewrite._cache.clear()
        # 缺省 paths 里没有 fuzzy，所以盯 lexical/vector 收到的查询串（E5：_q_lane）
        seen = {}
        orig_lex = cg._lexical
        orig_vec = getattr(cg, "_path_vector", None)

        def spy_lex(qq, entries, stat):
            seen["lexical"] = qq
            return orig_lex(qq, entries, stat)

        def spy_vec(qq, entries):
            seen["vector"] = qq
            return orig_vec(qq, entries)

        cg._lexical = spy_lex
        cg._path_vector = spy_vec
        try:
            cg.search_rrf("网络不给力", k=3, judge=False)
        finally:
            cg._lexical = orig_lex
            cg._path_vector = orig_vec
        q_lex = seen.get("lexical") or ""
        q_vec = seen.get("vector") or ""
        ok("A4 改写词进了 lexical/vector 查询串",
           "丢包" in q_lex and "延迟" in q_lex and q_lex.startswith("网络不给力")
           and ("丢包" in q_vec),
           "lexical=%r vector=%r" % (q_lex, q_vec))

        rewrite._ask = orig

        # B1 默认不重排
        os.environ.pop("MDCG_RERANK", None)
        base, _m = cg.search_rrf("家里网络老卡顿怎么办", k=3, judge=False)
        base_ids = [r[0]["id"] for r in base]
        ok("B1 默认不重排", rewrite.rerank_enabled() is False, str(base_ids))

        # B2 重排生效（合成 3 条融合结果——真实检索在这个小库里只出 1 条，
        # 排序判据要的是「给定 3 条，重排是否按 LLM 打分改序」这一步）
        os.environ["MDCG_RERANK"] = "1"
        node_by_id = {}
        for r in base:
            node_by_id[r[0]["id"]] = (r[0], r[1])
        for nid in ("kn_mod", "kn_tok"):
            node_by_id[nid] = ({"id": nid, "content": BODIES[nid]}, 0.0)
        fused = [(nid, 0.9 - i * 0.1) for i, nid in enumerate(["kn_lat", "kn_mod", "kn_tok"])]
        rewrite._ask = FakeLLM(json.dumps({"1": 0, "2": 3, "3": 2}))
        rr = rewrite.rerank("q", fused, node_by_id)
        ok("B2 重排改变顺序", [n for n, _ in rr] != [n for n, _ in fused] and rr[0][0] == fused[1][0],
           "%s → %s" % ([n for n, _ in fused], [n for n, _ in rr]))

        # B4/B5 分数跟着重排走（只挪顺序会让返回列表非单调）
        os.environ["MDCG_RERANK"] = "1"
        rewrite._ask = FakeLLM(json.dumps({"1": 0, "2": 3, "3": 2}))
        rr3 = rewrite.rerank("q", fused, node_by_id)
        sc = [s for _n, s in rr3]
        ok("B4 重排后分数单调不增", all(sc[i] >= sc[i + 1] for i in range(len(sc) - 1)),
           str([round(x, 3) for x in sc]))
        # 换一个问法：同问法同候选会被重排缓存命中，那测的就不是重排本身了
        rewrite._rcache.clear()
        rewrite._ask = FakeLLM(json.dumps({"1": 3, "2": 0}))
        up = rewrite.rerank("q-同分横比", [("kn_lat", 0.5), ("kn_mod", 0.5)], node_by_id)
        ok("B5 同分横比：高分 grade 得高分", up[0][0] == "kn_lat" and up[0][1] > up[1][1],
           str([(n, round(s, 3)) for n, s in up]))
        # B6–B8 重排结果缓存（key = 问法 + 候选 id 列表）
        os.environ["MDCG_RERANK"] = "1"
        rp = os.path.join(tmp, "_llm_cache", "rerank.jsonl")
        if os.path.exists(rp):
            os.unlink(rp)
        rewrite._rcache.clear()
        fake = FakeLLM(json.dumps({"1": 0, "2": 3, "3": 2}))
        rewrite._ask = fake
        r_first = rewrite.rerank("缓存判据问法", fused, node_by_id, root=tmp)
        n_first = fake.calls
        rewrite._rcache.clear()                     # 清内存缓存，逼它走磁盘
        r_second = rewrite.rerank("缓存判据问法", fused, node_by_id, root=tmp)
        ok("B6 缓存命中不再问模型", n_first == 1 and fake.calls == 1
           and [n for n, _ in r_second] == [n for n, _ in r_first],
           "calls=%d/%d order_same=%s" % (n_first, fake.calls,
                                          [n for n, _ in r_first] == [n for n, _ in r_second]))
        ok("B6b 缓存落了盘", os.path.exists(rp) and "缓存判据问法" in io.open(rp, encoding="utf-8").read(),
           "%d 行" % (0 if not os.path.exists(rp) else len(io.open(rp, encoding="utf-8").read().splitlines())))
        rewrite._rcache.clear()
        fused2 = [(nid, 0.9 - i * 0.1) for i, nid in enumerate(["kn_tok", "kn_lat", "kn_mod"])]
        rewrite.rerank("缓存判据问法", fused2, node_by_id, root=tmp)
        ok("B7 候选变了就是另一次判定", fake.calls == 2, "calls=%d" % fake.calls)
        rewrite._rcache.clear()
        _ttl = rewrite.CACHE_TTL
        rewrite.CACHE_TTL = 0
        rewrite.rerank("缓存判据问法", fused, node_by_id, root=tmp)
        rewrite.CACHE_TTL = _ttl
        ok("B8 过期后重新问模型", fake.calls == 3, "calls=%d" % fake.calls)
        ok("B8b stats 记到命中与未命中", (rewrite.stats().get("rerank_cache") or {}).get("miss", 0) >= 2,
           str(rewrite.stats().get("rerank_cache")))
        rewrite._ask = orig
        os.environ.pop("MDCG_RERANK", None)

        os.environ.pop("MDCG_RERANK", None)
        rewrite._ask = orig

        # D 查询日志（缓存档改写的预热源）
        qlp = os.path.join(tmp, "_queries.jsonl")
        if os.path.exists(qlp):
            os.unlink(qlp)
        os.environ.pop("MDCG_QUERY_LOG", None)
        cg.search_rrf("日志判据专用问法", k=3, judge=False)
        line = ""
        if os.path.exists(qlp):
            line = io.open(qlp, encoding="utf-8").read().strip().splitlines()[-1]
        ok("D1 检索写了查询日志", "日志判据专用问法" in line, line[:90])
        os.environ["MDCG_QUERY_LOG"] = "0"
        n_before = len(io.open(qlp, encoding="utf-8").read().strip().splitlines())
        cg.search_rrf("关掉日志的问法", k=3, judge=False)
        n_after = len(io.open(qlp, encoding="utf-8").read().strip().splitlines())
        ok("D2 MDCG_QUERY_LOG=0 不写", n_before == n_after, "%d→%d" % (n_before, n_after))
        os.environ.pop("MDCG_QUERY_LOG", None)

        # B3 重排失败原样
        rewrite._ask = FakeLLM(u'', fail=True)
        rr2 = rewrite.rerank("q", fused, node_by_id)
        ok("B3 重排失败原样返回", rr2 == fused, "unchanged")
        rewrite._ask = orig
        os.environ.pop("MDCG_RERANK", None)

        # C1 健康面 vector 段
        h = cg.health_os(full=True) if "full" in getattr(cg.health_os, "__code__", type("x", (), {"co_varnames": ()})).co_varnames else cg.health_os()
        v = (h or {}).get("vector") or {}
        ok("C1 健康面有 vector 段", isinstance(v, dict) and "eligible" in v,
           str({k: v.get(k) for k in ("built", "count", "eligible", "stale")}))
        ok("C1b eligible 不小于索引数或未建库",
           (v.get("built") is False) or (v.get("eligible") or 0) >= (v.get("count") or 0),
           "eligible=%s count=%s" % (v.get("eligible"), v.get("count")))
    finally:
        for k, val in old_env.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n==== test_rewrite_rerank: PASS %d / FAIL %d ====" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
