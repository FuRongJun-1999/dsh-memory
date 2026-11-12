#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_chain_retrieval_diag · 零模型检索侧诊断回路（官方状态链轨 v0.2）

# 功能名：检索侧诊断量具——把灵枢（本仓 md_cg）在官方状态链轨上的**检索能力**单独量出来
# 生效条件：需要一条「不烧钱、不依赖 reader LLM」的快速反馈回路时；给定官方 bench 检出目录
# 子功能：①隔离沙箱 ingest（官方 runner 同款 titled 形态）②现值题的三项检索侧指标
#         （现行值最佳名次/得分 · 退役值优于现行的「滞后混淆代理」· 官方链长桶分布）
#         ③朴素 BM25 对照（同口径）④机器可读 JSON 读数
# 执行：python scripts/bench_chain_retrieval_diag.py --bench <bench 检出目录> [--engine both]
# 验证方式：scripts/test_bench_chain_retrieval_diag.py（合成小语料判别力 + 定点变异自证）
# 不适用条件：**只量检索侧**，不判 reader 层答案（那需要 LLM，本件零模型零联网）；
#             不改 md_cg 任何实现；桶函数**不另写阈值**（importlib 复用官方 probe_judge._bucket）

## 为什么要这条回路
官方链轨判分（`chain/tools/probe_judge.py`）读的是 **reader LLM 的答卷**，一轮要烧钱、要等。
本件把「同一批现值题」的**检索侧**单独量到与官方同口径的桶，用于版本化召回迭代的快速反馈：
判据是机械的、确定性的、秒级的，且无需任何模型 API。

## 指标定义（与官方判据同源）
- **现行值 / 退役值**：逐字复用官方 `probe_judge.stale_confused` 的口径——
  现行值 = `answer['value']`；退役值 = `{e['to'] for e in answer['chain'][:-1]}` 去掉现行值。
- **(a) 现行值名次/得分**：检索结果里**第一条正文含现行值**的块的名次（1 基）与得分；未命中记 None。
- **(b) 滞后混淆代理**：存在**首条含退役值的块**名次优于首条含现行值的块（含「现行值未进前 k 而退役值进了」）
  ——即官方「把已退役旧值当现行值」在**检索侧**的可观测代理。
- **(c) 分桶**：桶函数直接 importlib 加载官方 `probe_judge._bucket`（short ≤8 / mid 9–30 / long >30）。

## 隔离
`MDCG_ROOT` / `MDCG_AUX_ROOT` / `MDCG_MASTER_KEY` 一律指向 tempfile 沙箱，跑完清理；
**绝不触碰在役库**。（注：AUX 目录末段用 `auxstore`——`aux` 是 Windows 保留设备名，会被 issue #57 守卫拒绝。）
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
from collections import Counter, defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

K_DEFAULT = 6          # 与官方 probe_runner.K 同值（常规问型 top-k 块数）
TYPES_PRESENT = ("现值",)


# =============================================================================
# 官方口径载体（不另写阈值：分桶与归一化一律从官方文件加载）
# =============================================================================
def load_official(bench_dir: str):
    """从官方 `chain/tools/probe_judge.py` 加载 (`_bucket`, `norm`)。

    生效条件：bench_dir 下存在 chain/tools/probe_judge.py。
    副作用：把该文件作为独立模块加载（不 import 官方 runner）。
    失败：抛 RuntimeError（**不静默退化**成自写阈值——那会让读数与官方不可比）。
    """
    p = os.path.join(bench_dir, "chain", "tools", "probe_judge.py")
    if not os.path.isfile(p):
        raise RuntimeError(f"官方判分器不存在：{p}（--bench 指向 bench 检出根）")
    spec = importlib.util.spec_from_file_location("_official_probe_judge", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # type: ignore[union-attr]
    return mod._bucket, mod.norm


def load_bench(bench_dir: str):
    """读官方语料与答案键（270 段 / 642 题）。"""
    cp = os.path.join(bench_dir, "chain", "corpus", "corpus.json")
    kp = os.path.join(bench_dir, "chain", "keys", "keys.json")
    with open(cp, encoding="utf-8") as f:
        chapters = json.load(f)
    with open(kp, encoding="utf-8") as f:
        keys = json.load(f)
    return chapters, keys


# =============================================================================
# 纯函数层（引擎无关；守卫测试直接 import 这一层）
# =============================================================================
def split_values(answer: dict, norm) -> tuple:
    """官方口径切分 (现行值, 退役值集合)。

    现行值 = answer['value']；退役值 = chain[:-1] 的 to 去掉现行值（同 probe_judge.stale_confused）。
    """
    cur = norm((answer or {}).get("value"))
    chain = (answer or {}).get("chain") or []
    olds = {norm(e.get("to")) for e in chain[:-1] if e.get("to")}
    olds.discard("")
    olds.discard(cur)
    return cur, olds


def rank_of_values(texts, values, norm) -> tuple:
    """首个命中 `values` 中任一值的正文名次（1 基）与得分；未命中 -> (None, None)。

    values 为空集 -> (None, None)：**没有退役值就没有可混淆的对象**（这一条是定点变异的靶子）。
    """
    if not values:
        return None, None
    for i, t in enumerate(texts, 1):
        s = norm(t)
        for v in values:
            if v and v in s:
                return i, None
    return None, None


def diag_case(hits, cur: str, stales, norm) -> dict:
    """单题检索侧诊断。

    hits: [{"text": str, "score": float, ...}]（名次 = 列表序，与引擎返回序一致）
    返回: cur_rank / cur_score / stale_rank / stale_score / stale_beats_current
    """
    texts = [h.get("text") or "" for h in hits]
    scores = [h.get("score") for h in hits]

    cur_rank = None
    cur_score = None
    if cur:
        for i, t in enumerate(texts, 1):
            if cur in norm(t):
                cur_rank, cur_score = i, scores[i - 1]
                break
    stale_rank = None
    stale_score = None
    if stales:
        for i, t in enumerate(texts, 1):
            s = norm(t)
            if any(v and v in s for v in stales):
                stale_rank, stale_score = i, scores[i - 1]
                break

    if stale_rank is None:
        beats = False
    elif cur_rank is None:
        beats = True                       # 现行值未进前 k，退役值进了
    else:
        beats = stale_rank < cur_rank
    return {
        "cur_rank": cur_rank, "cur_score": cur_score,
        "stale_rank": stale_rank, "stale_score": stale_score,
        "stale_beats_current": bool(beats),
    }


def summarize(cases) -> dict:
    """聚合 (a)(b)：命中率 / 平均名次 / 平均得分 / 滞后代理率。空集返回 n=0（各率为 None）。"""
    n = len(cases)
    if n == 0:
        return {"n": 0, "cur_hit_rate": None, "cur_mean_rank": None,
                "cur_mean_score": None, "stale_beats_rate": None, "stale_hit_rate": None}
    hit = [c for c in cases if c["cur_rank"] is not None]
    sh = [c for c in cases if c["stale_rank"] is not None]
    return {
        "n": n,
        "cur_hit_rate": round(len(hit) / n, 4),
        "cur_mean_rank": round(sum(c["cur_rank"] for c in hit) / len(hit), 3) if hit else None,
        "cur_mean_score": round(sum(float(c["cur_score"] or 0.0) for c in hit) / len(hit), 4) if hit else None,
        "stale_hit_rate": round(len(sh) / n, 4),
        "stale_beats_rate": round(sum(1 for c in cases if c["stale_beats_current"]) / n, 4),
    }


def by_bucket(items, bucket_fn) -> dict:
    """items: [(chain_len, case)] -> {桶: summarize}；桶函数由调用方注入（官方 _bucket）。"""
    groups = defaultdict(list)
    for cl, case in items:
        groups[bucket_fn(cl)].append(case)
    return {b: summarize(groups[b]) for b in ("short", "mid", "long")}


# =============================================================================
# 引擎一：本仓 md_cg（隔离沙箱）
# =============================================================================
class MdCGEngine:
    """把 270 段按官方 runner 同款形态灌进本仓引擎，并以其检索面出读数。

    隔离：root / aux / master_key 全部落在 tempfile 沙箱；close 后清理。
    官方同款点（chain/tools/probe_runner.py:288-290）：
        titled = [dict(ch, text=f"# {ch['cid']}\n{ch['text']}") for ch in chapters]
        ad.ingest(titled)
    本件不 import 官方 runner，只用其**形态**；引擎侧逐段 add（每段一块，node_id = cid）。
    """
    name = "mdcg"

    def __init__(self, sandbox: str):
        self.sandbox = sandbox
        self.root = os.path.join(sandbox, "mdcgroot")
        self.aux = os.path.join(sandbox, "auxstore")     # 末段避开 Windows 保留名
        os.makedirs(self.aux, exist_ok=True)
        os.environ["MDCG_ROOT"] = self.root
        os.environ["MDCG_AUX_ROOT"] = self.aux
        os.environ.setdefault("MDCG_MASTER_KEY", "00" * 32)   # 沙箱假值，仅本进程
        from md_cg.mdcg import MdCG
        self._eng = MdCG(root=self.root)
        self.ingest_secs = 0.0

    @staticmethod
    def node_id(cid: str) -> str:
        """cid -> 合法 node_id 的**确定性**映射。

        官方 cid 形如 `猎户项目#1`，而 md_cg 的 node_id 白名单不含 `#`
        （白名单见 md_cg.mdcg.add 的 node_id 校验，会拼进落盘路径故收得很紧）。
        这里只做字符替换（可逆可复现），**不改变语料内容**——检索面只看正文。
        """
        return re.sub(r"[^A-Za-z0-9_.@\u4e00-\u9fff,-]", "-", cid).replace("..", "--")[:128]

    def ingest(self, chapters) -> None:
        titled = [dict(ch, text="# " + ch["cid"] + "\n" + ch["text"]) for ch in chapters]
        t0 = time.time()
        for ch in titled:
            self._eng.add(self.node_id(ch["cid"]), ch["text"], layer="knowledge")
        self._eng.flush()
        self.ingest_secs = round(time.time() - t0, 2)

    def retrieve(self, query: str, k: int):
        res, _meta = self._eng.search(query, k=k)
        out = []
        for row in res or []:
            node = row[0] if isinstance(row, (tuple, list)) else row
            score = row[1] if isinstance(row, (tuple, list)) and len(row) > 1 else None
            if isinstance(node, dict):
                out.append({"cid": node.get("id"), "text": node.get("content") or "",
                            "score": float(score) if score is not None else None})
        return out

    def close(self):
        try:
            self._eng.close()
        except Exception:            # noqa: BLE001
            pass


# =============================================================================
# 引擎二：朴素 BM25（对照臂）
# =============================================================================
def _bigrams(s: str):
    """中文朴素切分：去空白后取字符 bigram（无空格语言下的常见朴素做法）。"""
    s = re.sub(r"\s+", "", s or "")
    if len(s) < 2:
        return [s] if s else []
    return [s[i:i + 2] for i in range(len(s) - 1)]


class NaiveBM25:
    """进程内朴素 BM25（k1=1.5 / b=0.75），与 md_cg 同口径出 hits。

    说明：官方基准的朴素 BM25 臂在 `adapters/naive_bm25.py`，**不在本仓**（本仓 git 全历史无 bm25 文件，
    PR #107 未落本仓），故此处为脚本内自实现的同族朴素实现，读数只作**量级参照**，不可当官方臂复现。
    """
    name = "bm25"

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = []
        self.tf = []
        self.len = []
        self.df = Counter()
        self.ingest_secs = 0.0

    def ingest(self, chapters) -> None:
        t0 = time.time()
        for ch in chapters:
            text = "# " + ch["cid"] + "\n" + ch["text"]
            toks = _bigrams(text)
            self.docs.append({"cid": ch["cid"], "text": text})
            c = Counter(toks)
            self.tf.append(c)
            self.len.append(len(toks) or 1)
            for t in c:
                self.df[t] += 1
        self.avgdl = (sum(self.len) / len(self.len)) if self.len else 1.0
        self.ingest_secs = round(time.time() - t0, 2)

    def retrieve(self, query: str, k: int):
        N = len(self.docs) or 1
        qs = _bigrams(query)
        scores = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            dl = self.len[i]
            for t in qs:
                f = tf.get(t, 0)
                if not f:
                    continue
                idf = math.log(1 + (N - self.df[t] + 0.5) / (self.df[t] + 0.5))
                s += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if s > 0:
                scores.append((s, i))
        scores.sort(key=lambda x: (-x[0], x[1]))
        return [{"cid": self.docs[i]["cid"], "text": self.docs[i]["text"], "score": s}
                for s, i in scores[:k]]


# =============================================================================
# 诊断主流程
# =============================================================================
def run_engine(engine, chapters, keys, norm, bucket_fn, k: int, limit=None):
    """灌语料 → 逐道现值题检索 → 三元读数。返回 (report_dict, per_qid)。"""
    engine.ingest(chapters)
    present = [x for x in keys if x.get("type") in TYPES_PRESENT]
    if limit:
        present = present[:limit]
    cases, items, per = [], [], {}
    for key in present:
        cur, stales = split_values(key.get("answer") or {}, norm)
        hits = engine.retrieve(key["question"], k)
        case = diag_case(hits, cur, stales, norm)
        case["qid"] = key["qid"]
        case["chain_len"] = key.get("chain_len") or len((key.get("answer") or {}).get("chain") or [])
        case["reconstructible"] = bool(key.get("reconstructible"))
        cases.append(case)
        items.append((case["chain_len"], case))
        per[key["qid"]] = {"cur": cur, "n_stale": len(stales), "hits": len(hits), **case}
    strict = [c for c in cases if not c["reconstructible"]]
    strict_items = [(c["chain_len"], c) for c in strict]
    rep = {
        "engine": engine.name,
        "k": k,
        "ingest_secs": getattr(engine, "ingest_secs", None),
        "n_corpus": len(chapters),
        "全部现值题": summarize(cases),
        "剔除可推题(对齐官方 present 分母)": summarize(strict),
        "桶_全部现值题": by_bucket(items, bucket_fn),
        "桶_剔除可推题": by_bucket(strict_items, bucket_fn),
        "桶基数_全部现值题": dict(Counter(bucket_fn(c["chain_len"]) for c in cases)),
        "桶基数_剔除可推题": dict(Counter(bucket_fn(c["chain_len"]) for c in strict)),
    }
    return rep, per


def _fmt(rep) -> str:
    lines = []
    a = rep["全部现值题"]
    b = rep["剔除可推题(对齐官方 present 分母)"]
    lines.append("  ingest %.2fs · 语料 %d 段 · k=%d" % (rep["ingest_secs"] or 0, rep["n_corpus"], rep["k"]))
    for lbl, s in (("全部现值题", a), ("剔除可推题", b)):
        lines.append("  [%s] n=%d 现行值命中率=%.4f 平均名次=%s 平均得分=%s 滞后代理率=%.4f"
                     % (lbl, s["n"], s["cur_hit_rate"] or 0, s["cur_mean_rank"],
                        s["cur_mean_score"], s["stale_beats_rate"] or 0))
    for lbl, key in (("全部", "桶_全部现值题"), ("剔除可推", "桶_剔除可推题")):
        cells = []
        for bk in ("short", "mid", "long"):
            s = rep[key][bk]
            cells.append("%s n=%d 命中=%.3f 滞后=%.3f"
                         % (bk, s["n"], s["cur_hit_rate"] or 0, s["stale_beats_rate"] or 0))
        lines.append("  [桶·%s] %s" % (lbl, " | ".join(cells)))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="官方状态链轨 · 零模型检索侧诊断")
    ap.add_argument("--bench", required=True, help="官方 bench 检出目录（含 chain/）")
    ap.add_argument("--engine", default="both", choices=("both", "mdcg", "bm25"))
    ap.add_argument("--k", type=int, default=K_DEFAULT, help="检索块数（官方常规问型 K=6）")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 道现值题（冒烟用）")
    ap.add_argument("--json", default=None, help="读数落盘路径")
    ap.add_argument("--keep-sandbox", action="store_true", help="保留临时沙箱（默认清理）")
    args = ap.parse_args(argv)

    bucket_fn, norm = load_official(args.bench)
    chapters, keys = load_bench(args.bench)
    print("官方口径：分桶 short<=8 / mid<=30 / long>30（importlib 自 probe_judge._bucket）")
    print("语料 %d 段 · 答案键 %d 题（现值 %d）"
          % (len(chapters), len(keys), sum(1 for x in keys if x.get("type") in TYPES_PRESENT)))

    sandbox = tempfile.mkdtemp(prefix="bench_chain_diag_")
    reports = {}
    try:
        targets = []
        if args.engine in ("both", "mdcg"):
            targets.append(MdCGEngine(sandbox))
        if args.engine in ("both", "bm25"):
            targets.append(NaiveBM25())
        for eng in targets:
            print("\n=== 引擎 %s ===" % eng.name)
            rep, _per = run_engine(eng, chapters, keys, norm, bucket_fn, args.k, args.limit)
            reports[eng.name] = rep
            print(_fmt(rep))
            if hasattr(eng, "close"):
                eng.close()
    finally:
        if args.keep_sandbox:
            print("沙箱保留：%s" % sandbox)
        else:
            shutil.rmtree(sandbox, ignore_errors=True)

    payload = {"bench": args.bench, "k": args.k, "engines": reports,
               "官方参照(首轮 v1)": {"bm25": {"present": 0.6596, "stale": 0.2766},
                                     "lingshu": {"stale": 0.298}}}
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("\n读数已落盘：%s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
