# -*- coding: utf-8 -*-
"""六系统横评（bench6）· 主进程臂：灵枢 / 纯向量 RAG + 统一评分。

四家 LLM 竞品（mem0/Graphiti/GraphRAG/Letta）依赖互斥，跑在各自 venv 的独立
脚本里（外部评测工作区的 bench6 适配脚本），只回吐 {qid: [id...]} 的 JSON；本模块
读回后与灵枢/向量臂走**同一个** bc.rows_from_hits → ec.summarize，保证六家同口径
（排名判据复用 ec.first_evidence_rank，指标复用 ec.summarize，均不重造）。

灵枢三种检索口径（同一份中文层 + 英文原文，只变检索路）：
  lex        : 单词法路，且建库不加 tags/condition_space——复现公开参考量级
               （词法 hit@1≈0.936）的**回归锚**，用于确认本次口径没有漂移
  rrf4       : 四路 RRF（lexical,bucket,entity,graph）+ 传 context——用户选定口径
  rrf4_noref : 四路 RRF 不传 context——名义四路，量化条件约束路的净效应

## 为什么灵枢要建两个库而不是一个
lex 臂必须与 `bench_locomo_zh_public.build_pool` **逐字同口径**（无 tags、无
condition_space）才能作回归锚；而 rrf4 臂按用户口径要喂 entity 路（tags）与
bucket 路（condition_space）。建库参数不同 → 目录不同 → 拆成两个 ROOT，避免
"复用已建库"逻辑把两种口径混成一个。

## 诚实边界
locomo-zh-500 是**单域**会话语料，且查询侧是**无情境标注**的关键词串。bucket 路
要求读写两侧 `route_key` 同构（routing.py 模块头「风险2」）——写侧有域、读侧
没有，故条件路由在本语料上预期无区分力。这一点由实测的桶健康度取证，不预设。
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (HERE, os.path.join(HERE, "md_cg")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from md_cg import bench6_common as bc      # noqa: E402
from md_cg import eval_common as ec        # noqa: E402

ROOT_BASE = os.path.join(HERE, "_md_cg_eval_bench6")   # .gitignore 的 /_md_cg_eval_*/ 已覆盖

# 条件约束路的查询侧情境：所有题共用同一份默认情境（查询串本身无情境标注）。
# 与建库侧 condition_space 同构 → route_key 两侧落在同一键上。这是 bucket 路能被
# 开启的唯一合法构造方式；若查询侧能精确给出每题的场景/域，那已是使用 qrels 作弊。
QUERY_CONTEXT = {
    "observation_position": "会话陈述",
    "observation_tool": "会话记录",
    "existence_constraint": "公开",
}


def cond_of(c):
    """zh_fields.condition（中文三槽）→ mdcos 期望的英文槽名。

    只映射 zh_fields 里**真实存在**的三槽，不臆造 time_window（写入侧会自行补）。
    """
    cond = (c.get("zh_fields") or {}).get("condition") or {}
    return {"observation_position": cond.get("观测位置", ""),
            "observation_tool": cond.get("观测工具", ""),
            "existence_constraint": cond.get("存在约束", "")}


def tags_of(c):
    """喂 entity 路的裸词 tags = identity + terms。

    刻意不加 `ent:` 前缀：`mdcos._path_entity` 的判据是 `t in query or query in t`，
    带前缀的标签在自然查询下永不命中（既有实测教训）。也不加 `domain:`——那会
    劫持 route_key 的 domain 分支，把 bucket 路变成按场景分桶，而查询侧无法复现
    同一场景键（见模块头「诚实边界」）。
    """
    f = c.get("zh_fields") or {}
    return [str(f.get("identity") or "")] + [str(t) for t in (f.get("terms") or [])]


class Adapter:
    """统一适配接口。六家一律只回吐 id 列表，指标计算交回 bench6_common。"""
    name = "adapter"

    def reset(self):
        raise NotImplementedError

    def add(self, nid, text):
        raise NotImplementedError

    def search(self, query, k=5):
        raise NotImplementedError

    def describe_ingest(self, nids):
        """回读真实存储内容样本，用于取证「入库语言与入库形态」。"""
        return []


class LingshuAdapter(Adapter):
    """灵枢臂：进程内 MdCGOS。

    with_meta=True 时三口径共用一库（lex 需与公开脚本同库，故 lex 单独建）。
    """

    name = "lingshu"

    def __init__(self, rows, variant, paths, context=None, with_meta=False,
                 rebuild=False):
        from md_cg.bench_locomo_zh_public import body_of
        from md_cg.mdcos import MdCGOS

        self.variant = variant
        self.paths = tuple(paths)
        self.context = context
        self._body_of = body_of
        root = os.path.join(ROOT_BASE, variant)
        self.root = root
        if rebuild and os.path.isdir(root):
            shutil.rmtree(root, ignore_errors=True)
        self.cg = MdCGOS(root, autoflush=500)
        if len(self.cg.index["nodes"]) >= len(rows):
            return                                  # 幂等复用
        t0 = time.time()
        for c in rows:
            kw = {}
            if with_meta:
                kw["tags"] = tags_of(c)
                kw["condition_space"] = cond_of(c)
            self.cg.add(c["id"], body_of(c), layer="knowledge",
                        eval_src="bench6:locomo-zh-500",
                        verification_basis="data", **kw)
        self.cg.flush()
        print("  [lingshu/%s] 建库 %d 节点 %.1fs"
              % (variant, len(self.cg.index["nodes"]), time.time() - t0))

    def search(self, query, k=5):
        kw = {"context": self.context} if self.context is not None else {}
        res, _meta = self.cg.search_rrf(query, k=k, paths=self.paths,
                                        judge=False, record=False, **kw)
        return [r[0]["id"] for r in res]

    def describe_ingest(self, nids):
        """回读真实落盘内容（索引元数据 + 文件头），取证入库语言与形态。

        不走 `cg.get`：其返回形状随层不同，且读缓存会介入；直接按索引 path 读
        文件是最贴近"磁盘上真实存了什么"的取证方式。
        """
        out = []
        for nid in nids[:2]:
            e = self.cg.index["nodes"].get(nid)
            if not e:
                continue
            head = ""
            try:
                with open(os.path.join(self.cg.root, e["path"]), encoding="utf-8") as f:
                    head = f.read()[:300]
            except OSError:
                pass
            out.append({"id": nid, "layer": e.get("layer"), "tags": e.get("tags"),
                        "bucket": e.get("bucket"),
                        "condition_space": e.get("condition_space"),
                        "file_head": head})
        return out

    def bucket_health(self):
        """桶健康度自检（routing.bucket_health）：取证条件路由是否有区分力。"""
        from md_cg import routing
        counts = {}
        for e in self.cg.index["nodes"].values():
            b = e.get("bucket") or "<none>"
            counts[b] = counts.get(b, 0) + 1
        return routing.bucket_health(counts)


class VectorRagAdapter(Adapter):
    """纯向量 RAG 基线（零 LLM）：英文原文直嵌入 + 余弦 Top-k。

    作为**下界锚**：无结构化、无图、无实体/条件路。embedding 走本地
    127.0.0.1:1234（OpenAI 兼容），与既有竞品探针同源，不引入新依赖。
    """

    name = "vector_rag"

    def __init__(self, base=None, model=None, timeout=30):
        self.base = (base or os.environ.get("BENCH6_EMBED_BASE")
                     or "http://127.0.0.1:1234/v1").rstrip("/")
        self.model = model or os.environ.get("BENCH6_EMBED_MODEL") or ""
        self.timeout = timeout
        self.ids = []
        self.vecs = []
        self._dim = 0

    def _post(self, path, payload):
        req = urllib.request.Request(
            self.base + path, method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def resolve_model(self):
        """未显式指定时，从 /models 取第一个 embedding 模型。"""
        if self.model:
            return self.model
        req = urllib.request.Request(self.base + "/models")
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        ids = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
        if not ids:
            raise RuntimeError("embedding 服务未返回任何模型：%s" % self.base)
        # 优先明显是 embedding 的模型名
        for mid in ids:
            if any(k in mid.lower() for k in ("embed", "bge", "gte", "m3")):
                self.model = mid
                break
        else:
            self.model = ids[0]
        return self.model

    def embed(self, text):
        d = self._post("/embeddings", {"model": self.model, "input": text})
        v = d["data"][0]["embedding"]
        self._dim = len(v)
        return v

    def embed_many(self, texts, batch=32):
        """批量嵌入（服务不支持 batch 时逐条回退）。"""
        out = []
        for i in range(0, len(texts), batch):
            chunk = texts[i:i + batch]
            try:
                d = self._post("/embeddings", {"model": self.model, "input": chunk})
                rows = sorted(d["data"], key=lambda x: x.get("index", 0))
                out.extend([r["embedding"] for r in rows])
            except Exception:
                out.extend([self.embed(t) for t in chunk])
            if self._dim == 0 and out:
                self._dim = len(out[-1])
        return out

    def reset(self):
        self.ids, self.vecs = [], []

    def add(self, nid, text):
        self.ids.append(nid)
        self.vecs.append(self.embed(text))

    def search(self, query, k=5):
        if not self.vecs:
            return []
        qv = self.embed(query)
        qn = math.sqrt(sum(x * x for x in qv)) or 1.0
        scored = []
        for i, v in enumerate(self.vecs):
            vn = math.sqrt(sum(x * x for x in v)) or 1.0
            s = sum(a * b for a, b in zip(qv, v)) / (qn * vn)
            scored.append((s, self.ids[i]))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [nid for _s, nid in scored[:k]]

    def describe_ingest(self, nids):
        return [{"id": nid, "form": "原样英文文本 → embedding",
                 "lang": "en", "dim": self._dim} for nid in nids[:2]]


# ------------------------------------------------------------------ 套件与评分

def run_suite(adapter, questions, lang, k=5, verbose=True):
    """一套查询语言跑一遍 → {qid: [id...]}（顺序即相关性降序）。"""
    key = "question_zh" if lang == "zh" else "question_en"
    hits, t0 = {}, time.time()
    for i, q in enumerate(questions, 1):
        hits[q["qid"]] = adapter.search(q[key], k=k)
        if verbose and i % 50 == 0:
            print("    [%s] %d/%d（%.0fs）" % (lang, i, len(questions),
                                              time.time() - t0))
    return hits


def evaluate(arm, adapter, questions, k=5, langs=("zh", "en")):
    """一套库 × 两种查询语言 → 指标 + per-question 明细 + 回读取证。"""
    out = {"arm": arm, "k": k, "langs": {}}
    for lang in langs:
        hits = run_suite(adapter, questions, lang, k=k)
        rows = bc.rows_from_hits(questions, hits, k=k)
        s = ec.summarize(rows, k=k)
        out["langs"][lang] = {"summary": s, "rows": rows, "hits": hits}
        print("  [%s/%s] hit@1=%.1f%% hit@%d=%.1f%% MRR=%.4f"
              % (arm, lang, s["hit@1"] * 100, k, s["hit@%d" % k] * 100, s["mrr"]))
    out["ingest_probe"] = adapter.describe_ingest([q["qid"] for q in questions[:2]])
    return out


def build_vector_rag(pool, model=None):
    """向量基线：池内英文原文批量嵌入（零 LLM、无结构化）。"""
    vec = VectorRagAdapter(model=model or os.environ.get("BENCH6_EMBED_MODEL")
                           or "text-embedding-bge-m3")
    vec.resolve_model()
    t0 = time.time()
    vec.ids = [t["id"] for t in pool]
    vec.vecs = vec.embed_many([t["ingest"] for t in pool])
    print("  [vector_rag] 模型=%s dim=%d 嵌入 %d 条 %.0fs"
          % (vec.model, vec._dim, len(vec.vecs), time.time() - t0))
    return vec


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    rebuild = "--rebuild" in argv
    only = [a for a in argv if not a.startswith("-")]
    t_all = time.time()

    data = bc.load()
    questions, pool, man = data["questions"], data["pool"], data["manifest"]
    print("[bench6] 题 %d / 池 %d（口径固化于 %s）"
          % (len(questions), len(pool), man["created_at"]))

    # 评测口径：与既有公开基准一致，否则与参考量级不可比（见 eval_common 注释）
    ec.unlock_global_cap()
    ec.use_jaccard()

    corpus_by_id = {c["id"]: c for c in ec.iter_jsonl(bc.CORPUS567)}
    rows = [corpus_by_id[t["id"]] for t in pool]
    results, table = {}, {}

    def _want(name):
        return not only or name in only

    # (1) 灵枢单词法路 = 回归锚。建库刻意**不加** tags/condition_space，与
    #     bench_locomo_zh_public.build_pool 逐字同口径；须复现 hit@1≈0.936，
    #     否则说明本次口径已漂移，后续所有四路数字都不可信。
    if _want("lingshu_lex"):
        lex = LingshuAdapter(rows, "lex", paths=("lexical",), with_meta=False,
                             rebuild=rebuild)
        ec.install_read_cache(lex.cg)
        results["lingshu_lex"] = evaluate("lingshu_lex", lex, questions)
        table["灵枢·单词法"] = results["lingshu_lex"]["langs"]["zh"]["summary"]

    # (2) 灵枢四路：真开 bucket（传 context）vs 名义四路（不传），单变量对照。
    if _want("lingshu_rrf4"):
        rrf = LingshuAdapter(rows, "rrf4", paths=ec.PATHS, with_meta=True,
                             rebuild=rebuild)
        ec.install_read_cache(rrf.cg)
        health = rrf.bucket_health()
        print("  [lingshu] 桶健康度 %s" % json.dumps(health, ensure_ascii=False))
        rrf.context = QUERY_CONTEXT
        results["lingshu_rrf4"] = evaluate("lingshu_rrf4", rrf, questions)
        rrf.context = None
        results["lingshu_rrf4_noref"] = evaluate("lingshu_rrf4_noref", rrf, questions)
        table["灵枢·四路(真开bucket)"] = results["lingshu_rrf4"]["langs"]["zh"]["summary"]
        table["灵枢·四路(名义)"] = results["lingshu_rrf4_noref"]["langs"]["zh"]["summary"]
        results["bucket_health"] = health

    # (2b) 2×2 消融：隔离「建库补 meta(tags/condition_space)」与「检索从 1 路变
    #      4 路」两个变量。rrf4(81%) 与 lex(99%) 之间混了这两个变量，不隔离就
    #      无法归因下降来自哪一侧。两个臂都复用已建好的库，只改检索参数，0 成本。
    if not only:
        rrf.paths = ("lexical",)
        results["lingshu_lex_meta"] = evaluate("lingshu_lex_meta", rrf, questions)
        rrf.paths = ec.PATHS                       # 复原
        lex.paths = ec.PATHS
        lex.context = QUERY_CONTEXT
        results["lingshu_rrf4_nometa"] = evaluate("lingshu_rrf4_nometa", lex, questions)
        lex.paths, lex.context = ("lexical",), None  # 复原
        table["灵枢·词法+meta"] = results["lingshu_lex_meta"]["langs"]["zh"]["summary"]
        table["灵枢·四路(无meta)"] = results["lingshu_rrf4_nometa"]["langs"]["zh"]["summary"]

    # (3) 纯向量 RAG 基线（零 LLM，下界锚）
    if _want("vector_rag"):
        vec = build_vector_rag(pool)
        results["vector_rag"] = evaluate("vector_rag", vec, questions)
        table["纯向量RAG"] = results["vector_rag"]["langs"]["zh"]["summary"]

    payload = {"manifest": man, "results": results,
               "elapsed_s": round(time.time() - t_all, 1)}
    ec.save_result("bench6_arms_result.json", payload)
    if table:
        ec.print_table("bench6 主进程臂 · 中文查询（池 %d / 题 %d）"
                       % (len(pool), len(questions)), table, k=5)
    print("\n[bench6] 主进程臂完成，用时 %.0fs" % (time.time() - t_all))
    return payload


if __name__ == "__main__":
    main()
