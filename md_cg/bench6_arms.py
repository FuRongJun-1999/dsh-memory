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


# 生效条件：形参 c 若提供映射接口，则取 c["zh_fields"]（缺失或假值回落 {}）再取其 "condition"（缺失或假值回落 {}），返回三槽 observation_position/observation_tool/existence_constraint，各自以 cond.get(中文键, "") 取值——中文键缺失时回落空串，键存在而值为 None 时结果即为 None（不回落）。
def cond_of(c):
    """zh_fields.condition（中文三槽）→ mdcos 期望的英文槽名。

    只映射 zh_fields 里**真实存在**的三槽，不臆造 time_window（写入侧会自行补）。
    """
    cond = (c.get("zh_fields") or {}).get("condition") or {}
    return {"observation_position": cond.get("观测位置", ""),
            "observation_tool": cond.get("观测工具", ""),
            "existence_constraint": cond.get("存在约束", "")}


# 生效条件：形参 c 若提供映射接口，则 f = c["zh_fields"] 为假值（缺失/None/{}）时当作 {}，返回 [str(f["identity"] 或 "")] + [str(t) for t in (f["terms"] 或 [])]：identity 缺失或假值时首元素为空串（列表恒有 1 项），terms 缺失或假值时只有首元素。
def tags_of(c):
    """喂 entity 路的裸词 tags = identity + terms。

    刻意不加 `ent:` 前缀：`mdcos._path_entity` 的判据是 `t in query or query in t`，
    带前缀的标签在自然查询下永不命中（既有实测教训）。也不加 `domain:`——那会
    劫持 route_key 的 domain 分支，把 bucket 路变成按场景分桶，而查询侧无法复现
    同一场景键（见模块头「诚实边界」）。
    """
    f = c.get("zh_fields") or {}
    return [str(f.get("identity") or "")] + [str(t) for t in (f.get("terms") or [])]


# 生效条件：类无 __init__，实例化无需任何形参；其 describe_ingest(nids) 对任意 nids（含空）恒返回 []，而 reset()、add(nid, text)、search(query, k=5) 对任意实参一律抛 NotImplementedError。
class Adapter:
    """统一适配接口。六家一律只回吐 id 列表，指标计算交回 bench6_common。"""
    name = "adapter"

# 生效条件：无可选/必需形参，任何调用一律抛 NotImplementedError（基类接口桩）。
    def reset(self):
        raise NotImplementedError

# 生效条件：对任意 nid 与 text 一律抛 NotImplementedError（形参不参与任何判断）。
    def add(self, nid, text):
        raise NotImplementedError

# 生效条件：对任意 query 与任意 k（默认 5）一律抛 NotImplementedError，不返回结果。
    def search(self, query, k=5):
        raise NotImplementedError

# 生效条件：对任意 nids（包括空列表或 None）都直接返回空列表 []，不读取任何存储。
    def describe_ingest(self, nids):
        """回读真实存储内容样本，用于取证「入库语言与入库形态」。"""
        return []


# 生效条件：必须以 rows、variant、paths 三个必需形参构造（context 默认 None、with_meta 默认 False、rebuild 默认 False 可选），构造后 search(query, k=5) 是否向 search_rrf 传 context 由 context 是否为 None 决定，describe_ingest(nids)/bucket_health() 的取证内容取决于 variant 对应 root 库的索引状态。
class LingshuAdapter(Adapter):
    """灵枢臂：进程内 MdCGOS。

    with_meta=True 时三口径共用一库（lex 需与公开脚本同库，故 lex 单独建）。
    """

    name = "lingshu"

# 生效条件：root 固定为 os.path.join(ROOT_BASE, variant)；rebuild 为真且 os.path.isdir(root) 为真时先 rmtree，索引中已有节点数 ≥ len(rows) 时直接 return（幂等复用、不写库），否则按 rows 逐条 add（with_meta 为真时同时补 tags=tags_of(c)、condition_space=cond_of(c)）后 flush。
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

# 生效条件：只遍历 nids[:2]，节点索引中 .get(nid) 为假值（缺失）的 nid 被跳过，其余按 os.path.join(self.cg.root, e["path"]) 读文件头 300 字符，抛 OSError 时 file_head 保持空串，输出各字段用 e.get（缺键为 None）。
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

# 生效条件：无参数，遍历 self.cg.index["nodes"] 各节点的 e.get("bucket")，其缺失或为假值（None/空串等）时归入 "<none>" 计数，再把计数字典交 routing.bucket_health 并返回其结果。
    def bucket_health(self):
        """桶健康度自检（routing.bucket_health）：取证条件路由是否有区分力。"""
        from md_cg import routing
        counts = {}
        for e in self.cg.index["nodes"].values():
            b = e.get("bucket") or "<none>"
            counts[b] = counts.get(b, 0) + 1
        return routing.bucket_health(counts)


# 生效条件：无必需构造形参，base 为假值（None/空串）时先回落 os.environ["BENCH6_EMBED_BASE"]、再回落 "http://127.0.0.1:1234/v1" 并 rstrip("/")，model 为假值时回落 os.environ["BENCH6_EMBED_MODEL"]、再回落空串 ""，timeout 缺省为 30。
class VectorRagAdapter(Adapter):
    """纯向量 RAG 基线（零 LLM）：英文原文直嵌入 + 余弦 Top-k。

    作为**下界锚**：无结构化、无图、无实体/条件路。embedding 走本地
    127.0.0.1:1234（OpenAI 兼容），与既有竞品探针同源，不引入新依赖。
    """

    name = "vector_rag"

# 生效条件：base 依次按 base 形参 → os.environ.get("BENCH6_EMBED_BASE") → "http://127.0.0.1:1234/v1" 取值（每级为空串/None 均继续回落）再去掉尾部 "/"，model 依次按 model 形参 → os.environ.get("BENCH6_EMBED_MODEL") → "" 取值（空串也回落），timeout 直接取形参（含 0），ids/vecs 置 []、_dim 置 0。
    def __init__(self, base=None, model=None, timeout=30):
        self.base = (base or os.environ.get("BENCH6_EMBED_BASE")
                     or "http://127.0.0.1:1234/v1").rstrip("/")
        self.model = model or os.environ.get("BENCH6_EMBED_MODEL") or ""
        self.timeout = timeout
        self.ids = []
        self.vecs = []
        self._dim = 0

# 生效条件：以 self.base + path 为 URL、method="POST"、JSON 编码的 payload 为 body、Content-Type: application/json、超时 self.timeout 发出请求，返回响应体按 UTF-8 解码后 json.loads 的对象。
    def _post(self, path, payload):
        req = urllib.request.Request(
            self.base + path, method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

# 生效条件：self.model 为真值时直接返回；否则请求 self.base + "/models"，从 data.get("data") 筛出 id 非空的模型名列表，该列表为空时抛 RuntimeError，否则优先取名字含 embed/bge/gte/m3 的第一个，无匹配则取 ids[0]，写入 self.model 后返回。
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

# 生效条件：对任意 text 以 self.model 调 _post("/embeddings", {"model":…, "input": text})，取 d["data"][0]["embedding"]，令 self._dim 等于该向量长度并返回该向量。
    def embed(self, text):
        d = self._post("/embeddings", {"model": self.model, "input": text})
        v = d["data"][0]["embedding"]
        self._dim = len(v)
        return v

# 生效条件：按 batch（默认 32）把 texts 切片，每片整批 POST /embeddings 成功时按 x.get("index", 0) 排序后依次收集 r["embedding"]，该片抛任何异常时改为对片内每条调 self.embed 回退，self._dim 为 0 且有结果时置为最后一条向量长度，最后返回 out。
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

# 生效条件：对任意 nid 与 text，把 nid 追加到 self.ids、把 self.embed(text) 的向量追加到 self.vecs，二者按下标一一对应，不查重、不返回。
    def add(self, nid, text):
        self.ids.append(nid)
        self.vecs.append(self.embed(text))

# 生效条件：self.vecs 为空时直接返回 []；否则嵌入 query 并对每条候选计算余弦相似度（qn 或 vn 为 0 时用 1.0 兜底），按相似度降序、同分按 id 升序排序后返回前 k 个 nid。
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

# 生效条件：对任意 nids 都只取前 2 项（nids[:2]），各返回 {"id": nid, "form": "原样英文文本 → embedding", "lang": "en", "dim": self._dim}，不读磁盘内容。
    def describe_ingest(self, nids):
        return [{"id": nid, "form": "原样英文文本 → embedding",
                 "lang": "en", "dim": self._dim} for nid in nids[:2]]


# ------------------------------------------------------------------ 套件与评分

# 生效条件：lang 等于 "zh" 时逐题取 q["question_zh"]，lang 为其它任何值（含 "en"）时取 q["question_en"]，对 questions 每项调 adapter.search(query, k=k)，verbose 为真且序数能被 50 整除时打印进度，返回 {qid: 检索结果列表}。
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


# 生效条件：对 langs 中每个 lang 依次跑 run_suite(adapter, questions, lang, k=k)、bc.rows_from_hits 与 ec.summarize，结果写入 out["langs"][lang]；最后取 questions 前 2 条的 qid 调 adapter.describe_ingest 存入 out["ingest_probe"] 并返回 out。
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


# 生效条件：model 依次按 model 形参 → os.environ.get("BENCH6_EMBED_MODEL") → "text-embedding-bge-m3" 取值（形参为空串/None、环境变量缺失或为空串都会继续回落），随后 resolve_model()，再把 pool 中每条的 t["id"]、t["ingest"] 分别装进 vec.ids 与批量嵌入结果 vec.vecs 后返回 vec。
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


# 生效条件：argv 为 None 时取 sys.argv[1:]，其中出现 "--rebuild" 则各臂以 rebuild=True 建库，非 "-" 开头的项构成 only 白名单，仅当 only 为空或臂名在 only 中时执行对应臂（only 为空时额外执行 2×2 消融块），跑完返回含 manifest/results/elapsed_s 的 payload。
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

# 生效条件：形参 name 出现在外层 main 的 only 白名单中时返回 True；only 为空（假值）时对任何 name 都返回 True；only 非空且不含 name 时返回 False。
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