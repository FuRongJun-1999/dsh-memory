# -*- coding: utf-8 -*-
"""md 认知图 · 存储、检索与认知循环

对齐白箱认知架构（《白箱智能是什么？》系列·第 1-5 篇）：
  五层记忆（anchor/structural/knowledge/contextual/self）
  + 两类负记忆（rejected 失败/否决、unresolved 未解问题，第 5 篇 L2/L5）
  + 条件路由（rec_content 优先 + 条件路由到桶）
  + 四态资格判定（ACCEPT/REJECT/DEFER/BLINDSPOT，与性能 tier 正交）
  + 验证基底（verification_basis：白箱信任的硬门槛）

P0 风险（基线功能）：
  风险1 分桶键退化 → routing.route_key 归一化（普查驱动）+ 健康度自检
  风险2 检索无情境入参 → search(context=...)，无情境时显式不走路由
  风险3 回退语义被改变 → 分级阶梯 T0..T3，结果标注 tier
  风险4 检索变写操作 → 访问计数走 append-only 日志

索引是派生物：节点 .md 是唯一真相源，_index.json 随时可由 rebuild_index() 重建。
"""
import os
import re
import json
import time
import hashlib
import threading

from . import nodefile, routing
from .fsutil import (FileLock, ShardedLog, atomic_write, append_jsonl,
                     read_jsonl, sweep_stale_temps)

# 五层 + 两类负记忆（白箱记忆七件套工程化：事实/规则→knowledge；
# 假设→contextual；失败/未解→独立目录）
LAYERS = ("anchor", "structural", "knowledge", "contextual", "self",
          "rejected", "unresolved")
# 有条件分区的层：knowledge 是主检索层；负记忆目录按自己的 MARKS 走，不路由
BUCKETED_LAYERS = ("knowledge",)
# 负记忆的 MARKS 必填（与 knowledge 的 5 要素不同）
NEG_MEMORY_MARKS = {
    "rejected":   ("假设", "否决原因", "验证"),
    "unresolved": ("问题", "已知线索", "目标"),
}
SCHEMA = 2

# 全量回退的读取上限，对齐 sqlite 版 `ORDER BY importance DESC, created_at DESC LIMIT 500`
GLOBAL_CAP = 500

# 条件论「观测时间」栏的默认观测窗口（秒）：调用方未提供 time_window 时，
# 以写入时刻为锚开一个 1 小时窗口（与 AEIS 既有约定一致）。
OBSERVATION_WINDOW_SEC = 3600.0

# 与 aeis.core.LayeredStore.SYNONYM_GROUPS 保持一致（检索结果可比性的前提）
SYNONYM_GROUPS = [
    {"视觉", "图像", "画面", "图片", "影像", "视像"},
    {"语义", "含义", "意思", "意义", "概念"},
    {"识别", "检测", "感知", "探测", "发现"},
    {"转换", "转化", "映射", "变换"},
    {"实验", "试验", "集成", "实现", "验证", "测试"},
    {"评测", "评估", "跑分", "基准", "benchmark", "评审", "考核"},
    {"记忆", "记录", "库"},
    {"智能", "智能体", "灵枢", "AI"},
    {"语音", "声音", "音频", "说话"},
    {"对话", "聊天", "交流"},
]

# 性能回退阶梯（怎么找到的）
TIER_BUCKET_LIKE = "T0_bucket_like"
TIER_BUCKET_SCAN = "T1_bucket_scan"
TIER_GLOBAL_LIKE = "T2_global_like"
TIER_GLOBAL_SCAN = "T3_global_scan"

# 资格判定四态（该不该用——白箱第 1 篇核心）
STATE_ACCEPT = "ACCEPT"           # 条件满足，有资格执行
STATE_REJECT = "REJECT"           # 条件冲突/不适用条件命中，明确不适用
STATE_DEFER = "DEFER"             # 条件不足但可继续寻找缺失条件
STATE_BLINDSPOT = "BLINDSPOT"     # 无法建立可靠归属，停止猜测

# 验证基底（白箱第 2 篇第 7 章：能被验证才能被信任）
VERIFICATION_BASIS = nodefile.VERIFICATION_BASIS


def expand_query_terms(query: str) -> list:
    """与 aeis.core 同实现：整句 + 分词（≥2字符）+ 同义词组展开。"""
    terms = [query]
    for w in re.split(r"[\s、，。；：,;.:/\\|]+", query):
        w = w.strip()
        if len(w) >= 2 and w not in terms:
            terms.append(w)
    for group in SYNONYM_GROUPS:
        for w in group:
            if w in query:
                terms.extend(g for g in group if g not in terms)
                break
    return list(dict.fromkeys(terms))


def bigrams(s: str) -> set:
    s = "".join(s.split())
    if len(s) <= 1:
        return {s}
    return {s[i:i + 2] for i in range(len(s) - 1)}


class MdCG:
    def __init__(self, root: str, autoflush: int = 64):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        for L in LAYERS:
            os.makedirs(os.path.join(self.root, L), exist_ok=True)
        self.index_path = os.path.join(self.root, "_index.json")
        self.index_log_dir = os.path.join(self.root, "_index_log")
        self.access_log = os.path.join(self.root, "_access.log")
        # 信息差 D 跟踪（白箱第 4 篇：D=D(t,C)）
        self.d_trace = os.path.join(self.root, "_d_trace.jsonl")
        # 反思单元日志（白箱第 3 篇第 13 章）
        self.reflection_log = os.path.join(self.root, "_reflection.jsonl")
        self.autoflush = autoflush
        self._dirty = {}
        self._log = None
        self.index = self._load_index()
        sweep_stale_temps(self.root)

    # ---------- 索引（派生物，可重建） ----------

    def _load_index(self):
        idx = None
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("schema") == SCHEMA:
                    idx = d
            except (ValueError, OSError):
                idx = None
        if idx is None:
            idx = {"schema": SCHEMA, "nodes": self._scan_nodes(), "buckets": {}}
        for rec in ShardedLog.read_all(self.index_log_dir):
            nid, e = rec.get("id"), rec.get("e")
            if nid and e:
                idx["nodes"][nid] = e
        idx["buckets"] = self._count_buckets(idx["nodes"])
        return idx

    @staticmethod
    def _count_buckets(nodes):
        buckets = {}
        for e in nodes.values():
            b = e.get("bucket")
            if b:
                buckets[b] = buckets.get(b, 0) + 1
        return buckets

    def compact_index(self):
        with FileLock(self.index_path):
            idx = {"schema": SCHEMA, "nodes": {}, "buckets": {}}
            if os.path.exists(self.index_path):
                try:
                    with open(self.index_path, encoding="utf-8") as f:
                        d = json.load(f)
                    if d.get("schema") == SCHEMA:
                        idx = d
                except (ValueError, OSError):
                    pass
            for rec in ShardedLog.read_all(self.index_log_dir):
                nid, e = rec.get("id"), rec.get("e")
                if nid and e:
                    idx["nodes"][nid] = e
            idx["buckets"] = self._count_buckets(idx["nodes"])
            atomic_write(self.index_path, json.dumps(idx, ensure_ascii=False))
            ShardedLog.clear(self.index_log_dir)
        self.index = idx
        return idx

    def flush(self):
        if not self._dirty:
            return
        if self._log is None:
            self._log = ShardedLog(self.index_log_dir)
        for nid, e in self._dirty.items():
            self._log.append({"id": nid, "e": e})
        self._dirty = {}

    def close(self):
        if self._log:
            self._log.close()
            self._log = None

    def _scan_nodes(self):
        nodes = {}
        for layer in LAYERS:
            base = os.path.join(self.root, layer)
            for dirpath, _dirs, files in os.walk(base):
                for fn in files:
                    if not fn.endswith(".md"):
                        continue
                    p = os.path.join(dirpath, fn)
                    try:
                        with open(p, encoding="utf-8") as f:
                            fm, content = nodefile.loads(f.read())
                    except OSError:
                        continue
                    nid = fm.get("id") or fn[:-3]
                    rel = os.path.relpath(p, self.root).replace("\\", "/")
                    parent = os.path.basename(dirpath)
                    nodes[nid] = {
                        "path": rel, "layer": fm.get("layer", layer),
                        "tags": fm.get("tags", []),
                        "bucket": parent if parent != layer else None,
                        "importance": fm.get("importance", 0.5),
                        "created_at": fm.get("created_at", 0),
                        "verification_basis": fm.get("verification_basis"),
                        "has_neg_conditions": nodefile.has_non_applicable(content),
                        "content_hash": hashlib.sha256(
                            content.encode("utf-8")).hexdigest()[:12],
                    }
        return nodes

    def rebuild_index(self):
        nodes = self._scan_nodes()
        idx = {"schema": SCHEMA, "nodes": nodes,
               "buckets": self._count_buckets(nodes)}
        with FileLock(self.index_path):
            atomic_write(self.index_path, json.dumps(idx, ensure_ascii=False))
            ShardedLog.clear(self.index_log_dir)
        self.index = idx
        self._dirty = {}
        return idx

    # ---------- 写 ----------

    def add(self, node_id: str, content: str, layer: str = "knowledge",
            tags=None, condition_space=None, importance: float = 0.5,
            confidence: float = 0.6, edges=None, verification_basis: str = None,
            non_applicable_conditions=None, **extra) -> str:
        """写入一个节点。

        verification_basis: 外部验证基底（白箱信任的硬门槛），
                            可选值在 nodefile.VERIFICATION_BASIS。
                            knowledge/self/anchor/structural 层强烈建议填写；
                            负记忆层（rejected/unresolved）通常填 "test" 或 "data"。
        non_applicable_conditions: 不适用条件列表，第 1 篇第 10 章 28%→88% 的关键。
        """
        if layer not in LAYERS:
            raise ValueError(f"未知层：{layer}（允许：{LAYERS}）")
        if verification_basis is not None and verification_basis not in VERIFICATION_BASIS:
            raise ValueError(f"未知验证基底：{verification_basis}（允许：{VERIFICATION_BASIS}）")
        tags = list(tags or [])
        bucket = None
        d = os.path.join(self.root, layer)
        if layer in BUCKETED_LAYERS:
            bucket = routing.bucket_dir(routing.route_key(condition_space, tags))
            d = os.path.join(d, bucket)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{node_id}.md")
        created_at = extra.pop("created_at", time.time())
        # 条件论「观测时间」栏：写入时必须记录观测时间窗。
        # 调用方未提供 time_window 时，以写入时刻为锚、默认窗口 OBSERVATION_WINDOW_SEC。
        cs = dict(condition_space or {})
        tw = cs.get("time_window")
        if not (isinstance(tw, (list, tuple)) and len(tw) == 2):
            cs["time_window"] = [created_at, created_at + OBSERVATION_WINDOW_SEC]
        fm = {
            "id": node_id, "layer": layer,
            "modality": extra.pop("modality", "text"),
            "importance": importance, "confidence": confidence,
            "condition_space": cs, "tags": tags,
            "created_at": created_at,
            "access_count": 0, "last_access": 0, "edges": list(edges or []),
            "verification_basis": verification_basis,
            "non_applicable_conditions": list(non_applicable_conditions or []),
        }
        fm.update(extra)
        atomic_write(path, nodefile.dumps(fm, content))
        self._stage(node_id, {
            "path": os.path.relpath(path, self.root).replace("\\", "/"),
            "layer": layer, "tags": tags, "bucket": bucket,
            "importance": importance, "created_at": fm["created_at"],
            "verification_basis": verification_basis,
            "has_neg_conditions": nodefile.has_non_applicable(content),
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest()[:12],
        })
        return node_id

    def add_rejected(self, hypothesis: str, reason: str, verification_basis: str = "test",
                     tags=None, **extra) -> str:
        """第 5 篇 L2：负记忆——失败/否决的假设库。重复证伪幂等。"""
        nid = f"rej_{hashlib.sha1(hypothesis.encode()).hexdigest()[:10]}"
        if nid in self.index["nodes"]:
            return nid  # 幂等：重复证伪不重复记录
        content = (f"# 假设：{hypothesis}\n"
                   f"# 否决原因：{reason}\n"
                   f"# 验证：{verification_basis}\n")
        return self.add(nid, content, layer="rejected",
                        tags=tags, verification_basis=verification_basis,
                        importance=0.0, **extra)  # importance=0：不被检索优先

    def add_unresolved(self, question: str, known_clues: str = "",
                       goal: str = "", verification_basis: str = "data",
                       tags=None, **extra) -> str:
        """第 5 篇 L5：未解问题清单——驱动主动探索。"""
        nid = f"unr_{hashlib.sha1(question.encode()).hexdigest()[:10]}"
        if nid in self.index["nodes"]:
            return nid
        content = (f"# 问题：{question}\n"
                   f"# 已知线索：{known_clues or '（暂无）'}\n"
                   f"# 目标：{goal or '（未设定）'}\n"
                   f"# 验证：{verification_basis}\n")
        return self.add(nid, content, layer="unresolved",
                        tags=tags, verification_basis=verification_basis,
                        importance=0.3, **extra)

    def _stage(self, node_id, entry):
        self._dirty[node_id] = entry
        self.index["nodes"][node_id] = entry
        if entry.get("bucket"):
            self.index["buckets"][entry["bucket"]] = \
                self.index["buckets"].get(entry["bucket"], 0) + 1
        if len(self._dirty) >= self.autoflush:
            self.flush()

    # ---------- 读 ----------

    def get(self, node_id: str):
        e = self.index["nodes"].get(node_id) or self._dirty.get(node_id)
        if not e:
            return None
        p = os.path.join(self.root, e["path"])
        try:
            with open(p, encoding="utf-8") as f:
                fm, content = nodefile.loads(f.read())
        except OSError:
            return None
        return {"id": node_id, "frontmatter": fm, "content": content, "path": e["path"]}

    def _read(self, entry):
        p = os.path.join(self.root, entry["path"])
        try:
            with open(p, encoding="utf-8") as f:
                return nodefile.loads(f.read())
        except OSError:
            return None, None

    # ---------- 资格判定（与性能 tier 正交）----------

    @staticmethod
    def judge_qualification(node_dict, query: str, context=None):
        """四态判定（白箱第 1/2 篇）。

        输入：节点 + 查询 + 当前情境
        输出：{state: ACCEPT|REJECT|DEFER|BLINDSPOT, reason: str}

        判定逻辑（与文档一致）：
        - BLINDSPOT：节点 MARKS 不完整（无法建立可靠归属）→ 停止
        - REJECT：不适用条件命中 → 明确不适用
        - DEFER：条件不足但缺的不是不适用条件，是适用条件未声明 → 可继续寻找
        - ACCEPT：条件满足（默认）
        """
        fm = node_dict.get("frontmatter") or {}
        content = node_dict.get("content") or ""
        cpl = nodefile.ccg_completeness(content)

        # 1) BLINDSPOT：5 要素不全 → 无法建立可靠归属
        if not cpl["complete"]:
            return {"state": STATE_BLINDSPOT,
                    "reason": f"CCG 5 要素不全：缺 {set(nodefile.CCG_REQUIRED) - set(cpl['required_present'])}"}

        # 2) REJECT：不适用条件命中（需条件对比，简化版用关键词命中）
        neg = fm.get("non_applicable_conditions") or []
        ctx_str = json.dumps(context or {}, ensure_ascii=False)
        neg_hit = [n for n in neg if any(w in ctx_str for w in n.split())]
        if neg_hit:
            return {"state": STATE_REJECT,
                    "reason": f"不适用条件命中：{neg_hit[:3]}"}

        # 3) DEFER：节点无 verification_basis → 信任根基不足
        if not fm.get("verification_basis"):
            return {"state": STATE_DEFER,
                    "reason": "未声明验证基底，需补充才能继续判定"}

        # 4) ACCEPT：默认
        return {"state": STATE_ACCEPT, "reason": "5 要素齐全 + 不适用条件未命中 + 验证基底已声明"}

    # ---------- 检索（性能阶梯 + 资格判定）----------

    def search(self, query: str, layer: str = None, k: int = 20,
               context=None, min_results: int = 1, record: bool = True,
               include_neg: bool = True, judge: bool = True):
        """返回 (results, meta)。results = [(node_dict, score, qualification)]。

        meta 含 tier（性能层级）、scanned（读取节点数）、bucket（路由桶）、candidates。
        qualification 是独立的 {state, reason}，与 tier 正交：
          - tier = 怎么找到的（性能）
          - state = 是否该用（资格）

        include_neg：是否包含 rejected/unresolved 层（默认 True：负记忆可参与判定）
        judge：是否对每条结果做四态资格判定（默认 True）
        """
        q = (query or "").strip()
        if not q:
            return [], {"tier": None, "reason": "empty_query", "scanned": 0}

        terms = expand_query_terms(q)
        qb = bigrams(q)
        # 把 rejected/unresolved 视作可参与召回的特殊「候选池」
        # ——命中它们的结果会改变 meta 的 covered_neg（被负记忆覆盖的查询）
        # 默认排除掉负记忆层的节点进入正排打分，仅作为「覆盖标记」用
        entries = [e for e in self.index["nodes"].values()
                   if not layer or e["layer"] == layer]
        if not entries:
            return [], {"tier": None, "reason": "no_candidates", "scanned": 0}

        # 负记忆覆盖：查询词是否已被否决议过
        neg_coverage = []
        if include_neg:
            for e in self.index["nodes"].values():
                if e["layer"] in ("rejected", "unresolved"):
                    got = self.get(e["path"].split("/")[-1][:-3])
                    # 用 path 末段作为 id 反查（_index 用 path，get 用 id）
                    # 上面写法是错的；改用直接路径读
                    full_path = os.path.join(self.root, e["path"])
                    if not os.path.exists(full_path):
                        continue
                    try:
                        with open(full_path, encoding="utf-8") as f:
                            fm, content = nodefile.loads(f.read())
                    except OSError:
                        continue
                    if any(t in content for t in terms):
                        neg_coverage.append(e)

        stat = {"scanned": 0}
        route_bucket = None
        if context is not None:
            ctx = context if isinstance(context, dict) else {}
            route_bucket = routing.bucket_dir(
                routing.route_key(ctx, ctx.get("tags")))

        # 阶段 1：14 大域并行打分 → 收敛到 top-1（白箱第 2 篇第 5 章）
        big_domain = routing.big_domain_classify(terms)
        big_scores = routing.big_domain_score_breakdown(terms)

        def try_stage(docs, tier):
            scored = self._score(docs, q, qb)
            valid = sum(1 for _, s in scored if s > 0)
            if valid >= min_results:
                return self._emit(scored, k, tier, stat, route_bucket, record,
                                  len(docs), judge, context, neg_coverage,
                                  big_domain, big_scores)
            return None

        # T0/T1：路由桶内
        if route_bucket:
            in_bucket = [e for e in entries if e.get("bucket") == route_bucket]
            if in_bucket:
                docs = self._read_many(in_bucket, stat)
                hits = [d for d in docs if self._like(d[2], d[1], terms)]
                out = try_stage(hits, TIER_BUCKET_LIKE)
                if out:
                    return out
                out = try_stage(docs, TIER_BUCKET_SCAN)
                if out:
                    return out

        # T2：跨桶 LIKE
        docs_all = self._read_many(entries, stat)
        hits = [d for d in docs_all if self._like(d[2], d[1], terms)]
        if len(hits) > GLOBAL_CAP:
            hits = hits[:GLOBAL_CAP]
        out = try_stage(hits, TIER_GLOBAL_LIKE)
        if out:
            return out

        # T3：全量兜底
        docs_all.sort(key=lambda d: (-float(d[1].get("importance") or 0),
                                     -float(d[1].get("created_at") or 0)))
        scored = self._score(docs_all[:GLOBAL_CAP], q, qb)
        return self._emit(scored, k, TIER_GLOBAL_SCAN, stat, route_bucket,
                          record, min(len(docs_all), GLOBAL_CAP), judge,
                          context, neg_coverage, big_domain, big_scores)

    def _read_many(self, entries, stat):
        docs = []
        for e in entries:
            fm, c = self._read(e)
            if c is not None:
                docs.append((e, fm, c))
        stat["scanned"] += len(docs)
        return docs

    @staticmethod
    def _like(content, fm, terms):
        tags = " ".join(str(t) for t in (fm.get("tags") or []))
        return any(t in content or t in tags for t in terms)

    def _score(self, docs, q, qb):
        scored = []
        for e, fm, c in docs:
            nb = bigrams(c)
            sim = len(qb & nb) / len(qb) if qb else 0.0
            tag_bonus = 0.05 if any(str(t) in q or q in str(t)
                                    for t in (fm.get("tags") or [])) else 0.0
            scored.append(({"id": fm.get("id") or e["path"], "frontmatter": fm,
                            "content": c, "path": e["path"]},
                           min(1.0, sim + tag_bonus)))
        return scored

    def _emit(self, scored, k, tier, stat, bucket, record, candidates,
              judge, context, neg_coverage, big_domain=None, big_scores=None):
        scored.sort(key=lambda x: (-x[1],
                                   -float(x[0]["frontmatter"].get("importance") or 0)))
        results = scored[:k]
        # 资格判定（与性能正交）
        out = []
        for r in results:
            if judge:
                qual = self.judge_qualification(r[0], "", context)
            else:
                qual = {"state": None, "reason": "judge_disabled"}
            out.append((r[0], r[1], qual))
        # 把被负记忆覆盖的查询也作为结果条目返回（首条），方便调用方感知
        for nc in neg_coverage[:3]:
            full_path = os.path.join(self.root, nc["path"])
            try:
                with open(full_path, encoding="utf-8") as f:
                    fm, content = nodefile.loads(f.read())
            except OSError:
                continue
            entry = {"id": nc["path"], "frontmatter": fm,
                     "content": content, "path": nc["path"]}
            qual = {"state": STATE_REJECT if nc["layer"] == "rejected" else STATE_DEFER,
                    "reason": f"查询已被{nc['layer']}层覆盖：见 {nc['path']}"}
            out.append((entry, 1.0, qual))
        if record and results:
            self.record_access([r[0]["id"] for r in results], tier)
        return out, {"tier": tier, "scanned": stat["scanned"], "bucket": bucket,
                     "candidates": candidates,
                     "covered_neg": [nc["path"] for nc in neg_coverage],
                     # 阶段 1 大域收敛结果 + 完整打分明细（白箱可审计）
                     "big_domain": big_domain,
                     "big_domain_scores": big_scores}

    # ---------- 五大单元之四：反思 / 验证 / 输出 ----------

    def reflect(self, query: str, results, user_feedback: str = None):
        """反思单元（白箱第 3 篇第 13 章）。

        输入：本次查询 + 检索结果 + 用户反馈（可选）
        输出：反思记录（追加到 _reflection.jsonl）

        反思内容：
        - 信息差 D(t,C) 增量
        - 命中节点的资格态分布
        - 是否触发 BLINDSPOT（覆盖率不足）
        - 用户反馈时记录「预测与事实的偏差」→ 知识飞轮的入口
        """
        d_prev = self._last_d()
        d_curr = self._compute_d(query, results)
        states = [r[2]["state"] for r in results] if results else []
        reflection = {
            "t": time.time(),
            "query": query,
            "d_prev": d_prev,
            "d_curr": d_curr,
            "d_delta": d_curr - d_prev,
            "d2": (d_curr - d_prev) - (d_prev - self._d_prev2()),
            "states": dict((s, states.count(s)) for s in set(states)),
            "n_results": len(results),
            "feedback": user_feedback,
        }
        try:
            append_jsonl(self.reflection_log, reflection)
        except OSError:
            pass
        return reflection

    def _d_prev2(self):
        """上一次的前一次 D 值，用于二阶差分。"""
        recs = list(read_jsonl(self.reflection_log))
        if len(recs) >= 2:
            return recs[-2].get("d_curr", 1.0)
        return 1.0

    def _last_d(self):
        recs = list(read_jsonl(self.reflection_log))
        if recs:
            return recs[-1].get("d_curr", 1.0)
        return 1.0

    def last_d_records(self):
        """反思日志全量记录（测试/审计用）。"""
        return list(read_jsonl(self.reflection_log))

    def _compute_d(self, query, results):
        """信息差 D 的简化度量（白箱第 4 篇）：
        D = 1 - 有效命中比例，0=信息差为零（完美），1=完全空白。

        简化模型：本次查询的「有效命中」= score>0 且 state=ACCEPT 的比例。
        """
        if not results:
            return 1.0
        accept = sum(1 for r in results
                     if r[1] > 0 and r[2]["state"] == STATE_ACCEPT)
        return max(0.0, 1.0 - accept / len(results))

    def verify(self, node_id: str, evidence: str, verdict: str):
        """验证单元（白箱第 3 篇第 13 章）：对节点做一次外部验证裁决。

        verdict ∈ {"confirmed", "weakened", "falsified"}
        - confirmed：写入 positive_evidence，confidence 上调（受第 5 篇纪律约束）
        - weakened：写入 negative_evidence，confidence 下调
        - falsified：调 falsify()，节点移入 rejected/（幂等：相同 hypothesis 不重复）
        """
        if verdict not in ("confirmed", "weakened", "falsified"):
            raise ValueError(f"未知裁决：{verdict}")
        node = self.get(node_id)
        if not node:
            return None
        if verdict == "falsified":
            # 移入 rejected：负记忆化
            self.add_rejected(hypothesis=node["content"][:200],
                              reason=evidence,
                              verification_basis="test")
            # 从原位置删除（节点进入 rejected 层）
            os.remove(os.path.join(self.root, node["path"]))
            return {"action": "falsified", "new_id": None}
        # confirmed/weakened：调整 confidence（白箱第 5 篇：
        # 反例的权重应该比正例大——这里用非对称步长实现）
        fm = node["frontmatter"]
        cur = float(fm.get("confidence", 0.6))
        step = 0.05 if verdict == "confirmed" else -0.15
        fm["confidence"] = round(min(0.99, max(0.0, cur + step)), 2)
        fm.setdefault("evidence_log", []).append(
            {"t": time.time(), "verdict": verdict, "evidence": evidence})
        atomic_write(os.path.join(self.root, node["path"]),
                     nodefile.dumps(fm, node["content"]))
        return {"action": verdict, "confidence": fm["confidence"]}

    # ---------- 知识飞轮（白箱第 2 篇第 8 章）----------

    def flywheel_step(self, error_report: str):
        """知识飞轮入口：错误 → 寻找遗漏条件 → 验证 → 结构更新。

        error_report: 形如 {"query": ..., "expected_state": "ACCEPT",
                              "actual_state": "REJECT/BLINDSPOT",
                              "missing": "可能漏掉的 condition 描述"}

        行为：
        1. 把 missing 解析为新的条件分支
        2. 写入 unresolved/ 目录，等待人工/外部验证基底裁决
        3. 触发 reflect 记录这次飞轮输入
        """
        try_data = json.loads(error_report) if isinstance(error_report, str) else error_report
        question = (f"为何 {try_data.get('query','?')} 出现 {try_data.get('actual_state','?')}"
                    f" 而期望 {try_data.get('expected_state','?')}？")
        clues = try_data.get("missing", "")
        nid = self.add_unresolved(question=question, known_clues=clues,
                                  goal="结构精化：补缺失条件分支")
        return {"unresolved_id": nid, "question": question}

    # ---------- 访问计数：append-only，检索路径不写节点文件 ----------

    def record_access(self, node_ids, tier=None):
        try:
            append_jsonl(self.access_log,
                         {"t": time.time(), "ids": list(node_ids), "tier": tier})
        except OSError:
            pass

    def access_counts(self):
        counts, last = {}, {}
        for rec in read_jsonl(self.access_log):
            ts = rec.get("t", 0)
            for nid in rec.get("ids", []):
                counts[nid] = counts.get(nid, 0) + 1
                if ts > last.get(nid, 0):
                    last[nid] = ts
        return counts, last

    def compact_access(self):
        counts, last = self.access_counts()
        if not counts:
            return 0
        n = 0
        for nid, c in counts.items():
            e = self.index["nodes"].get(nid)
            if not e:
                continue
            fm, content = self._read(e)
            if fm is None:
                continue
            fm["access_count"] = int(fm.get("access_count") or 0) + c
            fm["last_access"] = max(float(fm.get("last_access") or 0), last.get(nid, 0))
            atomic_write(os.path.join(self.root, e["path"]), nodefile.dumps(fm, content))
            n += 1
        with FileLock(self.access_log):
            atomic_write(self.access_log, "")
        return n

    # ---------- 健康度 ----------

    def health(self):
        """扩充：分桶健康度 + 5 要素完整度 + 验证基底覆盖率 + 负记忆密度。"""
        h = routing.bucket_health(self.index.get("buckets", {}))
        h["total_nodes"] = len(self.index["nodes"])
        # 5 要素完整度（全节点扫一遍，可能慢但只在 health() 调用）
        layer_stats = {}
        neg_stats = {}
        for e in self.index["nodes"].values():
            full_path = os.path.join(self.root, e["path"])
            try:
                with open(full_path, encoding="utf-8") as f:
                    fm, content = nodefile.loads(f.read())
            except OSError:
                continue
            cpl = nodefile.ccg_completeness(content)
            layer = e["layer"]
            if layer not in layer_stats:
                layer_stats[layer] = {"total": 0, "ccg_complete": 0,
                                      "verification_basis_set": 0,
                                      "neg_conditions_set": 0}
            layer_stats[layer]["total"] += 1
            if cpl["complete"]:
                layer_stats[layer]["ccg_complete"] += 1
            if fm.get("verification_basis"):
                layer_stats[layer]["verification_basis_set"] += 1
            if e.get("has_neg_conditions"):
                layer_stats[layer]["neg_conditions_set"] += 1
            if layer in ("rejected", "unresolved"):
                if layer not in neg_stats:
                    neg_stats[layer] = 0
                neg_stats[layer] += 1
        h["ccg_by_layer"] = layer_stats
        h["neg_memory_counts"] = neg_stats
        return h