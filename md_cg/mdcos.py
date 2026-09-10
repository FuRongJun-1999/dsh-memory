# -*- coding: utf-8 -*-
"""md_cg · 记忆操作系统扩展（MdCGOS）

在 MdCG（P0/P1 已验证引擎）之上补齐「记忆操作系统」的七项能力
（对标 deja-vu / dsh-noema 的工程实践）：

  1. Fix pairs 自动挖掘    行为日志（错误→修复）→ rejected/ 负记忆 + knowledge/ 修复知识
  2. role 分层索引         工具输出/命令/编辑 单独索引，默认不参与正排（不稀释召回）
  3. RRF 并行多路召回      词法 / 条件桶 / 图扩展 / 实体 四路并行 → Reciprocal Rank Fusion
                        （可选第 5 路 fuzzy：词表/大域驱动；第 6 路 semantic：条件结构驱动）
  4. 审核队列 edit/merge   海马体式 inbox→decisions（accept/reject/edit/merge）
  5. tombstone + 恢复检查   forget 软删除 + 删除清单（恢复时校验）
  6. payload-free 审计     每次变更只记事件 + 载荷哈希，不记内容
  7. budget-driven pack    recall 按 token 预算装包，跳过超大条目而非停下

设计约束：不修改 MdCG 的既有语义（P0/P1 测试须继续全绿）；本模块只**新增**能力。
零第三方依赖（D-005）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

from .mdcg import (MdCG, expand_query_terms, bigrams, STATE_ACCEPT, STATE_REJECT,
                   STATE_DEFER, STATE_BLINDSPOT, TIER_BUCKET_LIKE,
                   TIER_BUCKET_SCAN, TIER_GLOBAL_LIKE, TIER_GLOBAL_SCAN,
                   GLOBAL_CAP, expand_query_terms_weighted,
                   expand_query_terms_llm)
from . import (nodefile, routing, chain, subgraph, forgetting, protect,
               identity, consistency, metacognition, crypto, sustain,
               self_state, predict, evolution, weights)
from .fsutil import FileLock, atomic_write, append_jsonl, read_jsonl
from .security import (Principal, TenantRegistry, AccessDenied,
                       SENSITIVITY_ORDER, DEFAULT_SENSITIVITY, _rank)

# ---- 常量 ----------------------------------------------------------------

# 工作角色（默认不参与正排：工具输出/命令/编辑 会稀释召回）
WORK_ROLES = ("tool-output", "command", "edit")
ALL_ROLES = ("user", "assistant", "developer", "knowledge") + WORK_ROLES

# 错误 / 修复 的启发式特征（Fix pairs 挖掘）
_ERROR_RE = re.compile(
    r"(Traceback \(most recent call last\)|^\s*\w*Error\b|Exception\b|"
    r"\bfailed\b|\berror:\s|\bexit code [1-9]|报错|失败|异常|无法|不能)",
    re.I | re.M)
_FIX_RE = re.compile(
    r"^\s*(npm|pnpm|yarn|pip|pip3|python|python3|node|git|cargo|go|make|cmake|"
    r"curl|wget|cd|cp|mv|rm|mkdir|export|set|del|source|\.\/|\.\\|"
    r"pip install|npm i|git add|git commit|git push)\b",
    re.I | re.M)

RRF_K = 60          # RRF 常数
DEFAULT_BUDGET = 1200  # recall 默认 token 预算


def est_tokens(text: str) -> int:
    """确定性 token 估算：CJK 0.6/字 + 其余 /4（与白箱 adapter 口径一致）。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if 0x4e00 <= ord(ch) <= 0x9fff
              or 0x3040 <= ord(ch) <= 0x30ff)
    other = len(text) - cjk
    return int(cjk * 0.6 + other / 4) + 1


def _sig(text: str, n: int = 12) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:n]


def _term_degree(term: str, text: str) -> float:
    """词在文本中的分级命中（0~1）：整词出现 1.0；否则取最长命中子串的长度比 × 0.5。

    这是「模糊匹配」的最朴素形态——不要求整词命中，允许部分覆盖，
    但部分覆盖必须给出可解释的隶属度（命中越长越隶属）。
    部分命中额外打五折：**只有整词命中才可能 ≥ 0.5**，避免「红按钮 / 蓝按钮」
    这类共享后缀造成过高误配（模糊路的职责是补充线索，不是压倒词法路）。
    """
    if not term or not text:
        return 0.0
    if term in text:
        return 1.0
    n = len(term)
    if n < 2:
        return 0.0
    for L in range(n - 1, 1, -1):
        for i in range(0, n - L + 1):
            if term[i:i + L] in text:
                return 0.5 * L / n
    return 0.0


def _weighted_coverage(tw: dict, text: str) -> float:
    """词权 × 分级命中的加权覆盖率 ∈ [0,1]。"""
    num = den = 0.0
    for t, w in (tw or {}).items():
        if str(t).startswith("__") or w <= 0:
            continue
        den += w
        num += w * _term_degree(str(t), text)
    return num / den if den else 0.0


# ---------------------------------------------------------------------------
# 条件空间结构化匹配（白箱语义路）——只读节点「声明的条件」，不读正文词面。
#
# 与 fuzzy 路的正交关系：
#   fuzzy     = 词表驱动（SYNONYM_GROUPS_WEIGHTED 隶属度 + 大域 IDF）→ 问「像不像」
#   semantic  = 条件结构驱动（CCG 生效条件 + condition_space 四槽）→ 问「条件满不满足」
# 理论依据：《认知过程》第五章「相似度可以产生候选，但不授予执行资格」；
# 条件空间重合率是《激活引擎》cond_match 已被认证的度量。
# ---------------------------------------------------------------------------

def _ccg_field(content: str, name: str) -> str:
    """取 CCG 正文中 `# <name>：` 那一行的值（确定性扫描，无正则回溯风险）。"""
    for line in (content or "").splitlines():
        s = line.strip()
        if not s.startswith("#") or name not in s:
            continue
        body = s.lstrip("#").strip()
        for sep in ("：", ":"):
            if sep in body:
                head, _, val = body.partition(sep)
                if head.strip() == name:
                    return val.strip()
    return ""


def _declared_conditions(fm: dict, content: str):
    """节点声明的条件证据 → (生效条件列表, 不适用条件列表)。

    三处来源合并去重（保序）：
      1. CCG 正文 `# 生效条件：` / `# 不适用条件：`
      2. frontmatter.state_attributes.comment.生效条件 / .不适用条件（迁移语料形态）
      3. frontmatter.non_applicable_conditions
    """
    pos, neg = [], []

    def _push(bucket, val):
        s = str(val).strip()
        if s and s not in bucket:
            bucket.append(s)

    _push(pos, _ccg_field(content, "生效条件"))
    _push(neg, _ccg_field(content, "不适用条件"))
    st = fm.get("state_attributes")
    comment = st.get("comment") if isinstance(st, dict) else None
    if isinstance(comment, dict):
        for k in ("生效条件", "适用条件"):
            for x in (comment.get(k) or []):
                _push(pos, x)
        for x in (comment.get("不适用条件") or []):
            _push(neg, x)
    for x in (fm.get("non_applicable_conditions") or []):
        _push(neg, x)
    return pos, neg


def _neg_hit(tw: dict, neg_texts, min_weight: float = 0.6) -> bool:
    """不适用条件是否被查询词**整词**命中——条件级负路由。

    只认高置信词（权重 ≥ min_weight）且整词命中（_term_degree ≥ 0.5），
    避免「其它」「无需例外」这类泛化负条件把候选误杀。
    """
    if not neg_texts:
        return False
    blob = " ".join(str(x) for x in neg_texts)
    for t, w in (tw or {}).items():
        if w < min_weight or len(str(t)) < 2:
            continue
        if _term_degree(str(t), blob) >= 0.5:
            return True
    return False


def _window_overlap(a, b) -> float:
    """两个时间窗 [t1,t2] 的交叠比（0~1）= 交叠长度 / 较短窗长度。"""
    try:
        a1, a2 = float(a[0]), float(a[1])
        b1, b2 = float(b[0]), float(b[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return 0.0
    lo, hi = max(a1, b1), min(a2, b2)
    if hi <= lo:
        return 0.0
    span = min(a2 - a1, b2 - b1)
    return 1.0 if span <= 0 else min(1.0, (hi - lo) / span)


def _slot_overlap(tw: dict, cs: dict, q_domain=None, ctx_tw=None) -> float:
    """condition_space 四槽的加权重合度 ∈ [0,1]。

    只对**双方都有信息**的槽计分（缺失槽不进分母），避免「字段没填」被当成
    「条件不匹配」而系统性压低分数。position 权重 2（域是最强的条件证据）。
    """
    parts = []          # [(权重, 取值)]
    pos = cs.get("observation_position")
    if pos:
        sim = 0.0
        if q_domain:
            sim = routing.domain_similarity(
                routing.normalize_domain(pos),
                routing.normalize_domain(q_domain))
        parts.append((2.0, sim))
    for key in ("observation_tool", "existence_constraint"):
        v = cs.get(key)
        if v:
            best = max((_term_degree(str(t), str(v)) for t in tw), default=0.0)
            parts.append((1.0, best))
    win = cs.get("time_window")
    if win and ctx_tw:
        parts.append((1.0, _window_overlap(win, ctx_tw)))
    den = sum(w for w, _ in parts)
    return (sum(w * v for w, v in parts) / den) if den else 0.0


def _verify_norm(verify):
    """判据规范化 + 指纹：判据由 propose 声明，指纹不一致即视为被改写。"""
    if not verify:
        return "", ""
    import json as _json
    norm = _json.dumps(verify, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), default=str)
    return norm, _sig(norm)


def _redteam_required():
    return os.environ.get("MDCG_REDTEAM_REQUIRED", "").strip().lower() \
        in ("1", "true", "yes")


class MdCGOS(MdCG):
    """MdCG + 记忆 OS 七项能力。"""

    HIPPOCAMPUS = "hippocampus"
    TRASH = "trash"

    def __init__(self, root: str, autoflush: int = 64, actor: str = "system"):
        super().__init__(root, autoflush=autoflush)
        self.actor = actor
        self.audit_log = os.path.join(self.root, "_audit.jsonl")
        self.deletions_log = os.path.join(self.root, "_deletions.jsonl")
        self.hippocampus = os.path.join(self.root, self.HIPPOCAMPUS)
        self.inbox_log = os.path.join(self.hippocampus, "inbox.jsonl")
        self.decisions_log = os.path.join(self.hippocampus, "decisions.jsonl")
        self.trash_dir = os.path.join(self.root, self.TRASH)
        os.makedirs(self.hippocampus, exist_ok=True)
        os.makedirs(self.trash_dir, exist_ok=True)

    # ================= 6. payload-free 审计 =================

    def _audit(self, op: str, node_id: str, **meta):
        """只记事件与载荷哈希，绝不记录内容（payload-free）。"""
        rec = {"t": time.time(), "op": op, "id": node_id, "actor": self.actor}
        rec.update(meta)
        try:
            append_jsonl(self.audit_log, rec)
        except OSError:
            pass

    def audit_records(self):
        return list(read_jsonl(self.audit_log))

    # ================= 2. role 分层索引 =================

    def add(self, node_id: str, content: str, layer: str = "knowledge",
            role: str = None, **kw) -> str:
        """在父类 add 之上：写入 role（frontmatter + 索引），默认 role=None（知识）。"""
        if role is not None:
            kw["role"] = role
        nid = super().add(node_id, content, layer=layer, **kw)
        e = self.index["nodes"].get(nid)
        if e is not None and role is not None:
            e["role"] = role
            self._dirty[nid] = e
        self._audit("add", nid, layer=layer, role=role,
                    payload_hash=_sig(content))
        return nid

    def _candidates(self, layer=None, roles=None, include_work=False):
        """候选池：按层 + role 过滤。默认剔除工作角色（工具输出/命令/编辑）。"""
        out = []
        for e in self.index["nodes"].values():
            if e.get("layer") in ("rejected", "unresolved", "goals"):
                continue  # 负记忆走覆盖标记；目标只做定向，都不进正排
            if layer and e.get("layer") != layer:
                continue
            r = e.get("role")
            if roles is not None:
                if r not in roles:
                    continue
            elif not include_work and r in WORK_ROLES:
                continue
            out.append(e)
        return out

    # ================= 资格判定（legacy 记忆豁免） =================

    @staticmethod
    def judge_qualification(node_dict, query: str, context=None):
        """在父类四态之上支持 legacy 记忆（迁移进来的自由文本）。

        迁移进来的历史记忆没有 CCG 5 要素注释。若直接按父类判 BLINDSPOT，
        整库检索结果全是「停止猜测」，信息差 D 恒为 1、反思无意义。
        故对显式标记 `ccg_exempt=true` 且内容非空的节点判 **DEFER**
        （可检索、可继续补条件），并在 reason 里诚实说明缺什么。
        """
        fm = (node_dict or {}).get("frontmatter") or {}
        content = (node_dict or {}).get("content") or ""
        if fm.get("ccg_exempt") and content.strip():
            return {"state": STATE_DEFER,
                    "reason": "legacy 记忆（无 CCG 5 要素）：可检索；建议补生效条件/不适用条件/验证方式"}
        return MdCG.judge_qualification(node_dict, query, context)

    # ================= 检索（含 role 过滤 + 四路召回） =================

    def _neg_coverage(self, terms):
        """负记忆覆盖：查询词是否已被 rejected/unresolved 覆盖。"""
        out = []
        for e in self.index["nodes"].values():
            if e.get("layer") not in ("rejected", "unresolved"):
                continue
            fm, content = self._read(e)
            if not fm:
                continue
            content = self._open_content(fm.get("id"), fm, content)
            if content and any(t in content for t in terms):
                out.append(e)
        return out

    def search(self, query: str, layer: str = None, k: int = 20,
               context=None, min_results: int = 1, record: bool = True,
               include_neg: bool = True, judge: bool = True,
               roles=None, include_work: bool = False):
        """在父类语义之上加 role 过滤（默认剔除工具输出/命令/编辑）。

        返回 (results, meta)，与 MdCG.search 完全同构（T0–T3 阶梯 + 资格判定）。
        """
        q = (query or "").strip()
        if not q:
            return [], {"tier": None, "reason": "empty_query", "scanned": 0}
        entries = self._candidates(layer=layer, roles=roles, include_work=include_work)
        if not entries:
            return [], {"tier": None, "reason": "no_candidates", "scanned": 0}

        terms = expand_query_terms(q)
        qb = bigrams(q)
        stat = {"scanned": 0}
        route_bucket = None
        if context is not None:
            ctx = context if isinstance(context, dict) else {}
            route_bucket = routing.bucket_dir(routing.route_key(ctx, ctx.get("tags")))
        big_domain = routing.big_domain_classify(terms)
        big_scores = routing.big_domain_score_breakdown(terms)
        neg_coverage = self._neg_coverage(terms) if include_neg else []

        def try_stage(docs, tier):
            scored = self._score(docs, q, qb)
            valid = sum(1 for _, s in scored if s > 0)
            if valid >= min_results:
                return self._emit(scored, k, tier, stat, route_bucket, record,
                                  len(docs), judge, context, neg_coverage,
                                  big_domain, big_scores)
            return None

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

        docs_all = self._read_many(entries, stat)
        hits = [d for d in docs_all if self._like(d[2], d[1], terms)]
        if len(hits) > GLOBAL_CAP:
            hits = hits[:GLOBAL_CAP]
        out = try_stage(hits, TIER_GLOBAL_LIKE)
        if out:
            return out

        docs_all.sort(key=lambda d: (-float(d[1].get("importance") or 0),
                                     -float(d[1].get("created_at") or 0)))
        scored = self._score(docs_all[:GLOBAL_CAP], q, qb)
        return self._emit(scored, k, TIER_GLOBAL_SCAN, stat, route_bucket,
                          record, min(len(docs_all), GLOBAL_CAP), judge,
                          context, neg_coverage, big_domain, big_scores)

    def _lexical(self, query, entries, stat):
        """词法路径：LIKE 预筛 + 二元组 Jaccard。"""
        terms = expand_query_terms(query)
        docs = self._read_many(entries, stat)
        hits = [d for d in docs if self._like(d[2], d[1], terms)]
        if len(hits) > GLOBAL_CAP:
            hits = hits[:GLOBAL_CAP]
        scored = self._score(hits or docs[:GLOBAL_CAP], query, bigrams(query))
        return scored

    def _path_bucket(self, query, entries, context):
        """条件桶路径：命中路由桶的节点优先。"""
        if context is None:
            return []
        ctx = context if isinstance(context, dict) else {}
        b = routing.bucket_dir(routing.route_key(ctx, ctx.get("tags")))
        inb = [e for e in entries if e.get("bucket") == b]
        if not inb:
            return []
        stat = {"scanned": 0}
        docs = self._read_many(inb, stat)
        return self._score(docs, query, bigrams(query))

    def _path_entity(self, query, entries):
        """实体路径：tags 命中。（返回节点字典，与 _lexical 同构）"""
        out = []
        for e in entries:
            tags = [str(t) for t in (e.get("tags") or [])]
            if any(t in query or query in t for t in tags if len(t) >= 2):
                fm, c = self._read(e)
                if c is None:
                    continue
                c = self._open_content(fm.get("id"), fm, c)
                if c is None:
                    continue
                out.append(({"id": fm.get("id") or e["path"], "frontmatter": fm,
                             "content": c, "path": e["path"]}, 1.0))
        return out

    def _path_graph(self, query, entries, seeds, depth=1):
        """图扩展路径：从词法种子沿 edges 一跳扩展。"""
        if not seeds:
            return []
        seed_ids = {n["id"] for n, _ in seeds[:5]}
        by_id = {}
        for e in entries:
            nid = e["path"].split("/")[-1][:-3]
            by_id[nid] = e
        out = []
        for n, s in seeds[:5]:
            node = self.get(n["id"])
            if not node:
                continue
            for edge in (node["frontmatter"].get("edges") or []):
                tid = edge.get("target") if isinstance(edge, dict) else str(edge)
                if tid in by_id and tid not in seed_ids:
                    e = by_id[tid]
                    fm, c = self._read(e)
                    if c is None:
                        continue
                    c = self._open_content(fm.get("id"), fm, c)
                    if c is None:
                        continue
                    out.append(({"id": fm.get("id") or tid, "frontmatter": fm,
                                 "content": c, "path": e["path"]}, s * 0.5))
        return out

    def _path_chain(self, query, entries, seeds, context=None,
                    relation_types=None, max_depth=None, decay=0.9):
        """关系链路径：沿 causal/sequential/applies_to 边**多跳**扩散。

        理论依据：`causal` = 条件依赖因果（A 是 B 成立的条件），
        `dex_chain` 沿 causal 边正向展开、每步标注条件，**链 = 条件序列**。
        所以本路的语义是「推理可达性」——与词法/模糊的「词面相似」正交：

            score = 种子分 × 链累积权重（Π 边权重） × decay^跳数

        与既有 `_path_graph` 的区别：graph 只走 1 跳且权重硬编码 0.5；
        本路按边类型权重（causal .85 / sequential .60 …）、逐跳乘边置信度、
        默认 5 跳、visited 剪枝——「检索使用关系链」的落地。

        返回 (scored, prov)；prov[nid] 带该节点**最强链**的节点序列与条件序列，
        使「为什么召回它」可审计。
        """
        if not seeds:
            return [], {}
        seed_map = {}
        for n, s in seeds[:8]:
            nid = n.get("id")
            if nid and nid not in seed_map:
                seed_map[nid] = float(s)
        if not seed_map:
            return [], {}
        rels = tuple(relation_types) if relation_types else chain.CHAIN_TYPES_DEFAULT
        depth = chain.MAX_DEPTH_DEFAULT if max_depth is None else max_depth
        best = chain.expand_from_seeds(self, seed_map, relation_types=rels,
                                       max_depth=depth, decay=decay)
        if not best:
            return [], {}
        allowed = {id(e) for e in entries}
        scored, prov = [], {}
        for nid, info in best.items():
            e = self.index["nodes"].get(nid)
            if e is None or id(e) not in allowed:
                continue
            fm, c = self._read(e)
            if c is None:
                continue
            c = self._open_content(fm.get("id"), fm, c)
            if c is None:
                continue
            out_id = fm.get("id") or nid
            scored.append(({"id": out_id, "frontmatter": fm,
                            "content": c, "path": e["path"]}, info["score"]))
            prov[out_id] = {"chain": info["chain"]["nodes"],
                            "conditions": info["conditions"],
                            "depth": info["depth"]}
        scored.sort(key=lambda x: -x[1])
        return scored, prov

    def _path_fuzzy(self, query, entries, context=None, expand=None):
        """模糊路径（分级隶属度）：返回 (scored, source)。

        与既有四路正交——词法路用二元组 Jaccard（同义词无权重），本路显式使用
        SYNONYM_GROUPS_WEIGHTED 的分级隶属度 + 大域 IDF 加权打分：
            score = 0.6·词权覆盖率 + 0.3·大域亲和 + 0.1·情境亲和
        expand 可注入 LLM 查询侧扩展（expand_query_terms_llm 的偏函数）；
        缺省走白箱加权扩展。source 标注扩展来源（llm/whitebox/…），进 meta 可审计。
        """
        expand_fn = expand or expand_query_terms_weighted
        tw = expand_fn(query) or {}
        source = tw.pop("__source__", "whitebox")
        if not tw:
            return [], source
        dom_scores = routing.big_domain_score_weighted(tw)
        dom_total = sum(dom_scores.values()) or 1.0
        top_domains = sorted(dom_scores.items(), key=lambda kv: -kv[1])[:3]
        ctx_domain = None
        if context is not None:
            ctx = context if isinstance(context, dict) else {}
            ctx_domain = routing.route_key(ctx, ctx.get("tags"))
        stat = {"scanned": 0}
        out = []
        for e, fm, c in self._read_many(entries, stat):
            tags = " ".join(str(t) for t in (fm.get("tags") or []))
            # 负条件行不作召回键（反例命中应由 judge 走 REJECT，不该召回节点）
            cov = _weighted_coverage(tw, f"{nodefile.positive_body(c)} {tags}")
            if cov <= 0.0:
                continue
            e_dom = routing.route_key(None, e.get("tags"))
            aff = 0.0
            for d, s in top_domains:
                aff = max(aff, routing.domain_similarity(e_dom, d) * (s / dom_total))
            ctx_aff = (routing.domain_similarity(e_dom, ctx_domain)
                       if ctx_domain else 0.0)
            score = min(1.0, 0.6 * cov + 0.3 * aff + 0.1 * ctx_aff)
            out.append(({"id": fm.get("id") or e["path"], "frontmatter": fm,
                         "content": c, "path": e["path"]}, round(score, 6)))
        return out, source

    def _path_semantic(self, query, entries, context=None, neg_gate: bool = True):
        """条件空间结构化匹配路径（白箱语义路，零依赖）。

        与 fuzzy 路正交：fuzzy 由「词表 + 大域」驱动（同义词组权重 + IDF），
        本路由「节点声明的条件结构」驱动，打分只读条件、不读正文词面：

            score = 0.6·生效条件覆盖率 + 0.3·条件空间槽位重合 + 0.1·情境亲和

        · 生效条件覆盖率：query 扩展词对节点 `# 生效条件：` 与
          `state_attributes.comment.生效条件` 的加权覆盖（复用 _weighted_coverage）。
        · 条件空间槽位重合：observation_position 域相似度、observation_tool、
          existence_constraint 的分级命中、time_window 与查询窗交叠比（_slot_overlap）。
        · 不适用条件被整词命中 → **直接剔除**：条件级负路由，对齐「资格由条件证据
          裁决」，即 MdCG 评分报告 P1 所指 CCG 28%→88% 的真正来源。

        默认不参与 RRF（与 fuzzy 同样显式传 paths 才启用），既有四路基线不受影响。
        """
        tw = expand_query_terms_weighted(query) or {}
        tw.pop("__source__", None)
        tw = {str(k): float(v) for k, v in tw.items() if not str(k).startswith("__")}
        if not tw:
            return []
        ctx = context if isinstance(context, dict) else {}
        ctx_domain = routing.route_key(ctx, ctx.get("tags")) if ctx else None
        ctx_tw = ctx.get("time_window") if ctx else None
        q_domain = routing.big_domain_classify_weighted(tw)
        stat = {"scanned": 0}
        out = []
        for e, fm, c in self._read_many(entries, stat):
            pos, neg = _declared_conditions(fm, c)
            if neg_gate and _neg_hit(tw, neg):
                continue                      # 条件级负路由：此查询下无资格
            cs = fm.get("condition_space") or {}
            eff_cov = _weighted_coverage(tw, " ".join(pos)) if pos else 0.0
            slot = _slot_overlap(tw, cs, q_domain, ctx_tw)
            ctx_aff = (routing.domain_similarity(
                routing.route_key(cs, fm.get("tags")), ctx_domain)
                if ctx_domain else 0.0)
            score = min(1.0, 0.6 * eff_cov + 0.3 * slot + 0.1 * ctx_aff)
            if score <= 0.0:
                continue
            out.append(({"id": fm.get("id") or e["path"], "frontmatter": fm,
                         "content": c, "path": e["path"]}, round(score, 6)))
        return out

    def _path_goal(self, query, entries, context=None, goal_text=None):
        """目标定向路（白箱第 5 篇第 3 章「目标」）：用当前目标给召回定向。

        目标文本 → 加权词表 → 与节点正文/tags 的加权覆盖，叠加节点大域与
        目标大域的亲和度：
            score = 0.7·目标词覆盖 + 0.3·大域亲和

        goals 层节点本身**不参与本路排序**（目标是方向，不是答案）。
        返回 (scored, goal_used)：无活跃目标时返回 ([], "")，本路为空，
        因此显式启用也不改变其余路的融合结果。
        """
        gt = (goal_text if goal_text is not None else self.goal_text()) or ""
        gt = gt.strip()
        if not gt:
            return [], ""
        tw = expand_query_terms_weighted(gt) or {}
        tw.pop("__source__", None)
        tw = {str(k): float(v) for k, v in tw.items()
              if not str(k).startswith("__")}
        if not tw:
            return [], ""
        dom_scores = routing.big_domain_score_weighted(tw)
        dom_total = sum(dom_scores.values()) or 1.0
        top_domains = sorted(dom_scores.items(), key=lambda kv: -kv[1])[:3]
        stat = {"scanned": 0}
        out = []
        for e, fm, c in self._read_many(entries, stat):
            if e.get("layer") == "goals":
                continue
            tags = " ".join(str(t) for t in (fm.get("tags") or []))
            cov = _weighted_coverage(tw, f"{c} {tags}")
            if cov <= 0.0:
                continue
            e_dom = routing.route_key(None, e.get("tags"))
            aff = 0.0
            for d, s in top_domains:
                aff = max(aff, routing.domain_similarity(e_dom, d) * (s / dom_total))
            score = min(1.0, 0.7 * cov + 0.3 * aff)
            out.append(({"id": fm.get("id") or e["path"], "frontmatter": fm,
                         "content": c, "path": e["path"]}, round(score, 6)))
        return out, gt

    def search_rrf(self, query: str, k: int = 20, layer: str = None,
                   context=None, roles=None, include_work: bool = False,
                   judge: bool = True, paths=("lexical", "bucket", "entity", "graph"),
                   record: bool = True, query_expand=None,
                   path_weights=None, recall_only=None, fusion: str = "sum",
                   goal_text=None):
        """并行多路召回 + RRF 融合。返回 (results, meta)。

        每路各自排序 → Reciprocal Rank Fusion：
            score(d) = Σ_path w_path / (RRF_K + rank_path(d))
        多路共同确认的记忆排在单路命中之前（对齐 noema 的 Fusion Recall）。
        meta 含 per_path（各路的候选数与来源），可审计。

        paths: 基线四路（词法/条件桶/实体/图扩展）+ 两条**显式启用**的增量路：
            "fuzzy"    词表驱动（同义词组分级隶属度 + 大域 IDF）
            "semantic" 条件结构驱动（CCG 生效条件 + condition_space 四槽；
                       不适用条件被整词命中即从本路剔除——条件级负路由）
            "goal"     目标定向（第 5 篇第 3 章）：以活跃目标文本（或显式
                       goal_text）扩展查询，给「与当前目标相关」的记忆加权；
                       无活跃目标时本路为空，等价于未启用。
            缺省 ("lexical","bucket","entity","graph")，既有行为完全不变。
        path_weights: {路名: 权重}；缺省全部 1.0 → 与既有等权 RRF 完全一致。
            用于压低**同质路**的贡献：等权融合下，两路对同一批候选给出不一致
            排序时，RRF 会双重奖励「两路都靠前」的干扰项，把强路的 top-1 挤掉。
        recall_only: 路名集合，这些路**不参与打分**，只把未出现在打分结果里的
            节点以 0 分补进候选池（纯召回扩展、零稀释）；k 足够大时才可见。
        fusion: "sum"（默认，等权求和，即经典 RRF）或 "max"（取各路最高贡献）。
            sum 奖励「多路共识」，但会系统性低估**单路独有**候选：当强路漏掉目标、
            弱路捞到时，目标的单路贡献必然低于任何「两路都有排名」的干扰项。
            max 只认「最好的一次排名」，不奖励共识，适合「任一路捞到即可」的召回。
        """
        q = (query or "").strip()
        if not q:
            return [], {"tier": None, "reason": "empty_query", "paths": {}}
        entries = self._candidates(layer=layer, roles=roles, include_work=include_work)
        if not entries:
            return [], {"tier": None, "reason": "no_candidates", "paths": {}}

        stat = {"scanned": 0}
        ranked = {}          # path -> [(node, score)]
        fuzzy_source = None
        chain_prov = {}
        if "lexical" in paths:
            ranked["lexical"] = self._lexical(q, entries, stat)
        if "bucket" in paths:
            ranked["bucket"] = self._path_bucket(q, entries, context)
        if "entity" in paths:
            ranked["entity"] = self._path_entity(q, entries)
        if "graph" in paths:
            ranked["graph"] = self._path_graph(q, entries, ranked.get("lexical") or [])
        if "chain" in paths:
            seeds = (ranked.get("lexical") or []) + (ranked.get("entity") or [])
            ranked["chain"], chain_prov = self._path_chain(q, entries, seeds, context)
        if "fuzzy" in paths:
            ranked["fuzzy"], fuzzy_source = self._path_fuzzy(
                q, entries, context, expand=query_expand)
        if "semantic" in paths:
            ranked["semantic"] = self._path_semantic(q, entries, context)
        goal_used = None
        if "goal" in paths:
            ranked["goal"], goal_used = self._path_goal(
                q, entries, context, goal_text=goal_text)

        # 排序 + RRF 融合
        rrf, prov = {}, {}
        per_path = {}
        ro = set(recall_only or ())
        for name, scored in ranked.items():
            scored = sorted(scored, key=lambda x: (-x[1],
                            -float(x[0]["frontmatter"].get("importance") or 0)))
            per_path[name] = len(scored)
            if name in ro:
                continue
            w = float((path_weights or {}).get(name, 1.0))
            for rank, (node, _s) in enumerate(scored[:50], 1):
                nid = node["id"]
                contrib = w / (RRF_K + rank)
                if fusion == "max":
                    rrf[nid] = max(rrf.get(nid, 0.0), contrib)
                else:
                    rrf[nid] = rrf.get(nid, 0.0) + contrib
                entry = {"path": name, "rank": rank}
                if name == "chain" and nid in chain_prov:
                    entry["chain"] = chain_prov[nid]["chain"]
                    entry["conditions"] = chain_prov[nid]["conditions"]
                prov.setdefault(nid, []).append(entry)
        for name in ro:                     # 仅召回：补候选，不改排序
            for rank, (node, _s) in enumerate((ranked.get(name) or [])[:50], 1):
                nid = node["id"]
                if nid in rrf:
                    continue
                rrf[nid] = 0.0
                prov.setdefault(nid, []).append({"path": name, "rank": rank,
                                                 "recall_only": True})

        node_by_id = {}
        for scored in ranked.values():
            for node, s in scored:
                node_by_id.setdefault(node["id"], (node, s))
        fused = sorted(rrf.items(), key=lambda kv: -kv[1])[:k]

        results = []
        for nid, fs in fused:
            node, s = node_by_id[nid]
            qual = (self.judge_qualification(node, q, context) if judge
                    else {"state": None, "reason": "judge_disabled"})
            results.append((node, round(fs, 6), qual, prov.get(nid, [])))
        if record and results:
            self.record_access([r[0]["id"] for r in results], "RRF")
        return results, {"tier": "RRF", "scanned": stat["scanned"],
                         "paths": per_path, "fused": len(results),
                         "expand_source": fuzzy_source,
                         "goal_used": goal_used,
                         "provenance": prov}

    # ================= 7. budget-driven pack =================

    def recall(self, query: str, budget_tokens: int = DEFAULT_BUDGET, k: int = 20,
               layer: str = None, context=None, roles=None,
               include_work: bool = False, judge: bool = True, use_rrf: bool = True,
               paths=None, query_expand=None, fusion=None,
               goal_text=None, include_recent=False, recent_limit: int = 10):
        """按 token 预算装包：装到预算花完为止；**超大条目跳过而非停下**。

        paths/query_expand 缺省时行为与既有完全一致（默认四路、纯白箱扩展）；
        显式传 paths 才启用新路，例如
            ("lexical","bucket","entity","graph","fuzzy")            词表驱动
            ("lexical","bucket","entity","graph","semantic")         条件结构驱动
            (… 七路全开 )                                             三者叠加
        include_recent=True 时，把近期事件窗口（第 5 篇第 3 章）附在包后，
        保证当前任务的连续性；它不参与 RRF 正排，但计入 token 预算。
        返回 {pack: [...], tokens_used, budget, skipped: [...], recent: [...], meta}
        """
        if use_rrf:
            kw = dict(k=k, layer=layer, context=context, roles=roles,
                      include_work=include_work, judge=judge)
            if paths is not None:
                kw["paths"] = tuple(paths)
            if query_expand is not None:
                kw["query_expand"] = query_expand
            if fusion is not None:
                kw["fusion"] = fusion
            if goal_text is not None:
                kw["goal_text"] = goal_text
            results, meta = self.search_rrf(query, **kw)
            items = [(r[0], r[1], r[2], r[3]) for r in results]
        else:
            res, meta = self.search(query, layer=layer, k=k, context=context,
                                    judge=judge)
            items = [(r[0], r[1], r[2], []) for r in res]

        pack, skipped, used = [], [], 0
        for node, score, qual, prov in items:
            t = est_tokens(node.get("content") or "")
            if used + t > budget_tokens:
                skipped.append({"id": node["id"], "tokens": t, "reason": "oversize_or_over_budget"})
                continue          # 跳过超大，继续尝试更小的
            used += t
            pack.append({"id": node["id"], "score": score, "state": qual.get("state"),
                         "tokens": t, "content": node.get("content"),
                         "frontmatter": node.get("frontmatter"),
                         "provenance": prov})
        # 近期事件（第 5 篇第 3 章）：只作上下文尾巴，不参与 RRF 正排；
        # 计入 token 预算（诚实口径：附了就是占了）。
        recent, left = [], budget_tokens - used
        if include_recent:
            for ev in self.recent_events(limit=recent_limit):
                t = est_tokens(ev.get("text") or "")
                if t > left:
                    continue
                left -= t
                used += t
                recent.append({"role": ev.get("role"), "t": ev.get("t"),
                               "text": ev.get("text"), "tokens": t,
                               "tags": ev.get("tags") or []})
        return {"pack": pack, "tokens_used": used, "budget": budget_tokens,
                "skipped": skipped, "recent": recent, "meta": meta}

    # ================= 1. Fix pairs 自动挖掘 =================

    def mine_fix_pairs(self, events, lookahead: int = 4, min_len: int = 6):
        """从行为日志挖掘「错误 → 修复」对。

        events: [{"role": ..., "text": ...}] 或 [{"error":..., "fix":...}]（显式对）
        返回 {"pairs": [...], "rejected_ids": [...], "knowledge_ids": [...]}

        产出：
          · knowledge/<fix_xxx>.md —— 可路由的修复知识（CCG 5 要素）
          · rejected/<rej_xxx>.md  —— 负记忆「此错误不必深挖根因」（防重复踩坑）
        """
        pairs = []
        # 显式对
        for ev in events or []:
            if isinstance(ev, dict) and ev.get("error") and ev.get("fix"):
                pairs.append((str(ev["error"]), str(ev["fix"])))
        # 序列扫描：错误后 lookahead 条内出现命令/编辑 → 配对
        seq = [e for e in (events or []) if isinstance(e, dict) and "text" in e]
        for i, ev in enumerate(seq):
            txt = str(ev.get("text") or "")
            if not _ERROR_RE.search(txt):
                continue
            err_line = next((l.strip() for l in txt.splitlines()
                             if _ERROR_RE.search(l)), txt.strip())
            if len(err_line) < min_len:
                continue
            for j in range(i + 1, min(i + 1 + lookahead, len(seq))):
                cand = str(seq[j].get("text") or "")
                if _FIX_RE.search(cand):
                    fix = next((l.strip() for l in cand.splitlines()
                                if _FIX_RE.search(l)), cand.strip())
                    pairs.append((err_line, fix))
                    break

        # 去重
        seen, uniq = set(), []
        for err, fix in pairs:
            k = _sig(err + "\x00" + fix)
            if k in seen:
                continue
            seen.add(k)
            uniq.append((err, fix))

        rej_ids, kno_ids = [], []
        for err, fix in uniq:
            # 1) 可路由的修复知识
            kid = "fix_" + _sig(err + "\x00" + fix)
            content = (
                f"# 功能名：修复「{err[:60]}」\n"
                f"# 生效条件：{err}\n"
                f"# 子功能：执行修复命令\n"
                f"# 执行：{fix}\n"
                f"# 验证方式：行为日志（后续同类错误不再出现）\n"
                f"# 不适用条件：与「{err[:30]}」不同的错误\n\n"
                f"错误：{err}\n修复：{fix}\n")
            self.add(kid, content, layer="knowledge", tags=["fix_pair"],
                     verification_basis="data", importance=0.7)
            kno_ids.append(kid)
            # 2) 负记忆：这个错误不是死路（防止重复深挖）
            rid = self.add_rejected(
                hypothesis=f"「{err[:60]}」需要深挖根因（无现成解法）",
                reason=f"已有修复：{fix[:80]}",
                verification_basis="data", tags=["fix_pair"])
            rej_ids.append(rid)
        return {"pairs": [{"error": e, "fix": f} for e, f in uniq],
                "rejected_ids": rej_ids, "knowledge_ids": kno_ids}

    # ================= 4. 审核队列（inbox → decisions） =================

    def propose(self, node_id: str, content: str, layer: str = "knowledge",
                tags=None, condition_space=None, verify=None, **kw):
        """把一个候选记忆放入海马体 inbox，等待审核（不直接持久化）。

        verify —— 验收判据（内联声明，裁决阶段只读），形如：
            {"kind": "code", "assertions": ["pytest -k foo 通过"], "cmd": "..."}
        判据指纹随提案落盘，复核者只能按原判据裁决，不能放宽标准。
        """
        pid = "prop_" + _sig(node_id + str(time.time()))
        _norm, vhash = _verify_norm(verify)
        rec = {"t": time.time(), "pid": pid, "id": node_id, "content": content,
               "layer": layer, "tags": list(tags or []),
               "condition_space": condition_space or {},
               "verify": verify or {}, "verify_hash": vhash,
               "extra": kw, "actor": self.actor}
        append_jsonl(self.inbox_log, rec)
        self._audit("propose", node_id, pid=pid, layer=layer,
                    payload_hash=_sig(content), verify_hash=vhash)
        return pid

    def _pid_status(self):
        """pid → 最新一条裁决记录（多轮再审批时取最后一轮）。"""
        st = {}
        for r in read_jsonl(self.decisions_log):
            if r.get("pid"):
                st[r["pid"]] = r
        return st

    def _closed_pids(self):
        """已被终态裁决关闭的 pid（needs_reapproval 仍视为打开）。"""
        return {pid for pid, r in self._pid_status().items()
                if r.get("status") in ("accepted", "rejected")}

    def review_list(self):
        """待审核候选（含被红队打回、待再审批的条目）。"""
        st = self._pid_status()
        out = []
        for r in read_jsonl(self.inbox_log):
            s = st.get(r.get("pid")) or {}
            if s.get("status") in ("accepted", "rejected"):
                continue
            rec = dict(r)
            rec["status"] = s.get("status") or "pending"
            rec["round"] = int(s.get("round") or 0)
            rec["issues"] = list(s.get("issues") or [])
            out.append(rec)
        return out

    def review_rounds(self, pid: str):
        """某提案的裁决轮次历史（红队打回 → 修复 → 再审批，可追溯）。"""
        return [{"round": r.get("round"), "decision": r.get("decision"),
                 "status": r.get("status"),
                 "redteam": r.get("redteam_verdict"),
                 "issues": r.get("issues") or [], "t": r.get("t"),
                 "actor": r.get("actor"),
                 "record_node_id": r.get("record_node_id"),
                 "record_hash": r.get("record_hash")}
                for r in read_jsonl(self.decisions_log) if r.get("pid") == pid]

    # ---------- 裁决记录的 md 审计节点（供其他来源审计） ----------

    AUDIT_ROLE = "tool-output"   # 审计记录默认不进正排（不稀释召回）
    AUDIT_TAG = "review-record"

    @staticmethod
    def _record_hash(rec):
        """裁决记录指纹：外部审计方按同规则重算即可验证未被篡改。"""
        keys = ("pid", "round", "decision", "status", "redteam_verdict",
                "issues", "verify_hash", "reason", "actor", "t")
        payload = {k: rec.get(k) for k in keys}
        norm = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), default=str)
        return hashlib.sha1(norm.encode("utf-8")).hexdigest()

    @staticmethod
    def _audit_node_id(pid: str, round_no) -> str:
        return f"rev_{pid.split('_')[-1]}_r{int(round_no)}"

    def _write_review_record(self, rec):
        """把一轮裁决写成 md 记忆节点（self 层）——外部来源可读、可复核。"""
        nid = rec["record_node_id"]
        rh = rec["record_hash"]
        body = (
            f"# 功能名：审核裁决记录 {rec['pid']} 第 {rec['round']} 轮\n"
            f"# 生效条件：提案 {rec['pid']} 第 {rec['round']} 轮裁决发生时\n"
            f"# 子功能：记录 decision/status/红队裁决/判据指纹，供外部来源复核\n"
            f"# 执行：读 hippocampus/decisions.jsonl 中同 pid+round 记录，"
            f"按 _record_hash 规则重算并比对 record_hash\n"
            f"# 验证方式：data（重算哈希比对；不一致即视为记录被篡改）\n"
            f"# 不适用条件：提案不存在时；本轮无裁决记录时\n\n"
            f"- 提案：{rec['pid']}（目标节点 {rec.get('target_id') or '-'}）\n"
            f"- 轮次：{rec['round']}　裁决：{rec['decision']}"
            f"　状态：{rec['status']}\n"
            f"- 红队：{rec['redteam_verdict']}"
            f"　问题数：{len(rec.get('issues') or [])}\n"
            f"- 判据指纹：{rec.get('verify_hash') or '-'}\n"
            f"- 记录指纹：{rh}\n"
            f"- 裁决人：{rec.get('actor')}　时间："
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(rec['t']))}\n"
        )
        extra = {}
        if hasattr(self, "principal"):     # MdCGSecure：审计记录按裁决者密级写
            extra["sensitivity"] = getattr(self.principal, "clearance", None)
        self.add(nid, body, layer="self", override=True, role=self.AUDIT_ROLE,
                 tags=["audit", self.AUDIT_TAG, f"pid:{rec['pid']}",
                       f"round:{rec['round']}"],
                 importance=0.2, verification_basis="data",
                 pid=rec["pid"], round=rec["round"], decision=rec["decision"],
                 status=rec["status"],
                 redteam_verdict=rec["redteam_verdict"],
                 verify_hash=rec.get("verify_hash"), record_hash=rh,
                 issues_count=len(rec.get("issues") or []),
                 audit_source="hippocampus/decisions.jsonl", **extra)
        return nid

    def _record_decision(self, pid, item, decision, status, reason, round_no,
                         rt_verdict, issues, vhash, result):
        """落盘一轮裁决：jsonl（权威）+ md 审计节点（可复核、供外部审计）。"""
        t = time.time()
        rec = {"t": t, "pid": pid, "decision": decision, "status": status,
               "round": round_no, "redteam_verdict": rt_verdict or "absent",
               "issues": issues, "verify_hash": vhash, "reason": reason,
               "actor": self.actor, "target_id": item.get("id"),
               "record_node_id": self._audit_node_id(pid, round_no)}
        rec["record_hash"] = self._record_hash(rec)
        rec["result"] = {k: v for k, v in result.items()
                         if k in ("ok", "node_id", "error", "state")}
        append_jsonl(self.decisions_log, rec)
        # md 审计节点写失败不影响裁决（jsonl 仍是权威来源）
        try:
            self._write_review_record(rec)
            result["record_node_id"] = rec["record_node_id"]
            result["record_hash"] = rec["record_hash"]
        except Exception as exc:  # noqa: BLE001
            result["record_error"] = f"{type(exc).__name__}: {exc}"
            self._audit("review_record_failed", item.get("id", ""), pid=pid,
                        round=round_no, error=type(exc).__name__)
        self._audit("review_decide", item.get("id", ""), pid=pid,
                    decision=decision, status=status, round=round_no,
                    redteam=rt_verdict or "absent", issue_count=len(issues),
                    record_node=rec["record_node_id"])
        return result

    def review_records(self, pid: str = None):
        """列出裁决记录节点（self 层 / audit 标签），供外部来源审计。"""
        out = []
        for nid, e in self.index["nodes"].items():
            if e.get("layer") != "self":
                continue
            tags = e.get("tags") or []
            if self.AUDIT_TAG not in tags:
                continue
            if pid and f"pid:{pid}" not in tags:
                continue
            out.append({"id": nid, "path": e.get("path"), "tags": tags,
                        "created_at": e.get("created_at")})
        out.sort(key=lambda r: (r.get("created_at") or 0, r["id"]))
        return out

    def verify_review_record(self, node_id: str):
        """复核一条裁决记录节点：重算 record_hash 与 decisions.jsonl 比对。

        外部来源只需读 md 节点 + decisions.jsonl 即可独立完成复核，
        不依赖本系统运行：不一致 → 记录被改写。
        """
        node = self.get(node_id)
        if not node:
            return {"ok": False, "error": "node_not_found"}
        fm = node.get("frontmatter") or {}
        pid, rnd = fm.get("pid"), fm.get("round")
        src = next((r for r in read_jsonl(self.decisions_log)
                    if r.get("pid") == pid
                    and int(r.get("round") or 0) == int(rnd or 0)), None)
        if not src:
            return {"ok": False, "error": "source_record_missing",
                    "pid": pid, "round": rnd}
        actual = self._record_hash(src)
        expected = fm.get("record_hash")
        return {"ok": bool(expected) and actual == expected,
                "node_id": node_id, "pid": pid, "round": rnd,
                "expected": expected, "actual": actual,
                "decision": src.get("decision"), "status": src.get("status"),
                "verify_hash": src.get("verify_hash"),
                "source": "hippocampus/decisions.jsonl"}

    def review_decide(self, pid: str, decision: str, edits: dict = None,
                      merge_into: str = None, reason: str = "",
                      redteam: dict = None, issues=None):
        """审核裁决：accept / reject / edit / merge。

        accept  → 按 inbox 原样写入
        reject  → 丢弃（只记裁决，不落节点）
        edit    → 用 edits 覆盖 content/tags/layer 后写入
        merge   → 合并进已有节点 merge_into（内容追加 + 不适用条件并集）

        两条验证纪律（借自任务分级协议的验证端）：
          1. 判据只读：verify 由 propose 声明，裁决阶段传入不同判据 → verify_readonly。
          2. 红队门控 + 再审批：redteam.verdict=reject（或带 issues 的 reject）不落库，
             该 pid 转 needs_reapproval；修复后必须带 round 递增的 pass 再审批。
        """
        if decision not in ("accept", "reject", "edit", "merge"):
            raise ValueError(f"未知裁决：{decision}")
        item = next((r for r in read_jsonl(self.inbox_log)
                     if r.get("pid") == pid), None)
        if not item:
            return {"ok": False, "error": "pid_not_found"}
        if pid in self._closed_pids():
            return {"ok": False, "error": "already_decided"}

        expect = item.get("verify_hash") or ""
        if (edits and "verify" in edits) or (redteam and "verify" in redteam):
            return {"ok": False, "error": "verify_readonly",
                    "expected_hash": expect,
                    "detail": "判据由 propose 声明，裁决阶段不可修改"}

        st = self._pid_status().get(pid) or {}
        last_status, last_round = st.get("status"), int(st.get("round") or 0)
        last_issues = list(st.get("issues") or [])
        rt = dict(redteam or {})
        rt_v = str(rt.get("verdict") or "").strip().lower()
        rt_v = rt_v if rt_v in ("pass", "reject") else ""
        rt_issues = [str(x) for x in (issues or rt.get("issues") or [])
                     if str(x).strip()]
        round_no = int(rt.get("round") or (last_round + 1))

        # 再审批义务：上一轮被红队打回 → 必须 pass 且轮次严格递增
        if last_status == "needs_reapproval":
            if rt_v != "pass":
                return {"ok": False, "error": "reapproval_required",
                        "last_round": last_round, "last_issues": last_issues,
                        "detail": "上一轮被红队打回，修复后必须带 "
                                  "redteam.verdict=pass 再审批"}
            if round_no <= last_round:
                return {"ok": False, "error": "round_not_advanced",
                        "last_round": last_round,
                        "detail": "再审批轮次必须严格递增"}
        # 红队打回：本轮不落库，转待再审批
        if rt_v == "reject" or (decision == "reject" and rt_issues):
            return self._record_decision(
                pid, item, "reject", "needs_reapproval", reason, round_no,
                rt_v or "reject", rt_issues or ["红队打回"], expect,
                {"ok": True, "state": "needs_reapproval", "round": round_no,
                 "issues": rt_issues or ["红队打回"]})
        # 硬门控（可选）：accept 必须带红队 pass
        if decision == "accept" and not rt_v and _redteam_required():
            return {"ok": False, "error": "redteam_required",
                    "detail": "MDCG_REDTEAM_REQUIRED=1：accept 必须带红队 pass"}

        result = {"pid": pid, "decision": decision, "round": round_no,
                  "redteam": rt_v or "absent"}
        if decision == "reject":
            result["ok"] = True
        elif decision in ("accept", "edit"):
            content = item["content"]
            tags = list(item.get("tags") or [])
            layer = item.get("layer") or "knowledge"
            if decision == "edit" and edits:
                content = edits.get("content", content)
                tags = list(edits.get("tags", tags))
                layer = edits.get("layer", layer)
            extra = dict(item.get("extra") or {})
            if item.get("verify"):
                extra["verify"] = item["verify"]
                extra["verify_hash"] = expect
            nid = self.add(item["id"], content, layer=layer, tags=tags,
                           condition_space=item.get("condition_space"), **extra)
            result.update(ok=True, node_id=nid)
        else:  # merge
            target = merge_into or (item.get("extra") or {}).get("merge_into")
            tgt = self.get(target) if target else None
            if not tgt:
                return {"ok": False, "error": "merge_target_not_found"}
            fm = dict(tgt["frontmatter"])
            merged_content = (tgt["content"].rstrip() + "\n\n" +
                              item["content"].strip() + "\n")
            # 不适用条件并集（保序去重）
            neg = list(fm.get("non_applicable_conditions") or [])
            for x in (item.get("extra") or {}).get("non_applicable_conditions") or []:
                if x not in neg:
                    neg.append(x)
            fm["non_applicable_conditions"] = neg
            self._write_node(target, os.path.join(self.root, tgt["path"]),
                             fm, merged_content)
            self.rebuild_index()
            result.update(ok=True, node_id=target)

        return self._record_decision(
            pid, item, decision,
            "rejected" if decision == "reject" else "accepted",
            reason, round_no, rt_v, rt_issues, expect, result)

    def decisions(self):
        return list(read_jsonl(self.decisions_log))

    # ================= 5. tombstone + 恢复时删除检查 =================

    def forget(self, node_id: str, reason: str = "", override: bool = False):
        """软删除：节点文件移入 trash/，写入删除清单（payload-free）。

        写保护：受保护节点（self/anchor 层、protected 标记、importance≥0.7）
        不可遗忘——需显式 override=True，且旧版本先快照、动作全程留痕。
        """
        e = self.index["nodes"].get(node_id)
        if not e:
            return {"ok": False, "error": "not_found"}
        protect.guard_forget(self, node_id, override=override, actor=self.actor)
        src = os.path.join(self.root, e["path"])
        fm, content = self._read(e)
        h = _sig(content or "", 16)
        dst = os.path.join(self.trash_dir, f"{node_id}.md")
        try:
            os.replace(src, dst)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        append_jsonl(self.deletions_log, {"t": time.time(), "id": node_id,
                                          "hash": h, "reason": reason,
                                          "actor": self.actor,
                                          "trash": os.path.relpath(dst, self.root)
                                                   .replace("\\", "/")})
        self.index["nodes"].pop(node_id, None)
        self._dirty.pop(node_id, None)
        subgraph.invalidate_cache(self)
        chain.invalidate_cache(self)
        self._audit("forget", node_id, reason=reason, payload_hash=h)
        return {"ok": True, "id": node_id, "tombstone": h}

    def deletions(self):
        return list(read_jsonl(self.deletions_log))

    def is_tombstoned(self, node_id: str):
        return any(r.get("id") == node_id for r in read_jsonl(self.deletions_log))

    def restore(self, node_id: str, force: bool = False):
        """恢复：若在删除清单中且未 force → 拒绝（恢复时删除检查）。"""
        tomb = [r for r in read_jsonl(self.deletions_log) if r.get("id") == node_id]
        if tomb and not force:
            return {"ok": False, "error": "tombstoned",
                    "reason": tomb[-1].get("reason", ""), "t": tomb[-1].get("t")}
        src = os.path.join(self.trash_dir, f"{node_id}.md")
        if not os.path.exists(src):
            return {"ok": False, "error": "not_in_trash"}
        with open(src, encoding="utf-8") as f:
            fm, content = nodefile.loads(f.read())
        layer = fm.get("layer", "knowledge")
        tags = fm.get("tags") or []
        self.add(node_id, content, layer=layer, tags=tags, override=True,
                 sensitivity=fm.get("sensitivity"),
                 condition_space=fm.get("condition_space"),
                 importance=fm.get("importance", 0.5),
                 confidence=fm.get("confidence", 0.6),
                 verification_basis=fm.get("verification_basis"))
        os.remove(src)
        self._audit("restore", node_id, forced=bool(force))
        return {"ok": True, "id": node_id, "forced": bool(force)}

    # ================= 会话层（P0 会话三件套：note / recall / compact） =================
    #
    # 定位：hook 缺失时的**库侧替代**。载体侧 hook 负责「何时自动做」，
    # 库侧只保证「一次调用就够用」——把原本由 hook 自动注入的内容打包返回，
    # 从而降低对载体引导机制的依赖（见 docs/灵枢82工具 §五 ③-4「自动注入不对等」）。
    # 诚实边界：本层是「库侧可缓解」，不等于载体侧 hook 已闭合。

    SESSION_TAG = "session"

    @staticmethod
    def _session_node_id(session, summary):
        """会话要点节点 id：同 (session, summary) → 同 id（幂等覆盖，不新增）。"""
        sig = hashlib.sha1(
            f"{session or ''}|{(summary or '').strip()}".encode("utf-8")
        ).hexdigest()[:12]
        return f"sess_{sig}"

    @staticmethod
    def _session_digest(content):
        """从会话节点正文取一行摘要（`# 执行：` 优先，否则首个非空行）。"""
        v = _ccg_field(content, "执行")
        if v:
            return v[:500]
        for ln in (content or "").splitlines():
            if ln.strip():
                return ln.strip()[:500]
        return ""

    def session_note(self, summary, session=None, tags=None, layer="contextual",
                     importance=0.6, sensitivity=None, conditions=None,
                     basis="data"):
        """会话要点写入：把一段会话的要点落成可续接的 contextual 节点。

        幂等：同 (session, summary) 重复写入 → 覆盖同一节点，不新增。
        CCG 齐备：生效条件 / 验证方式自动补齐，避免「只可检索、不可判定」。
        """
        summary = (summary or "").strip()
        if not summary:
            raise ValueError("summary 不能为空")
        session = (session or "").strip() or time.strftime("%Y%m%d")
        nid = self._session_node_id(session, summary)
        cond = conditions or f"续接会话 {session}、或查询命中该会话要点关键词时"
        content = (
            f"# 功能名：会话要点（{session}）\n"
            f"# 生效条件：{cond}\n"
            f"# 子功能：会话要点记录（可续接 / 可检索）\n"
            f"# 执行：{summary}\n"
            f"# 验证方式：{basis}\n"
            f"# 不适用条件：其它会话的要点；与本次会话无关的查询\n\n"
            f"{summary}\n"
        )
        tg = [self.SESSION_TAG, f"session:{session}"] + list(tags or [])
        self.add(nid, content, layer=layer, tags=tg,
                 importance=float(importance),
                 condition_space={"observation_position": "session"},
                 verification_basis=basis,
                 non_applicable_conditions=["其它会话"],
                 sensitivity=sensitivity)
        self._audit("session_note", nid, session=session)
        return {"ok": True, "id": nid, "session": session, "layer": layer,
                "basis": basis, "tokens": est_tokens(content)}

    def _session_notes(self, session=None, limit=5):
        """按时间倒序取会话要点（索引过滤 + 惰性回读摘要）。只读，不写盘。"""
        out = []
        for nid, e in (self.index.get("nodes") or {}).items():
            tags = list(e.get("tags") or [])
            if self.SESSION_TAG not in tags and not any(
                    str(t).startswith("session:") for t in tags):
                continue
            if session and f"session:{session}" not in tags:
                continue
            fm, content = self._read(e)
            if content is None:
                continue               # 不可读（无密钥 / 身份不符）→ 视为不存在
            out.append({
                "id": nid, "session": (fm or {}).get("session") or "",
                "created_at": float(e.get("created_at") or 0),
                "layer": e.get("layer"), "tags": tags,
                "summary": self._session_digest(content),
            })
        out.sort(key=lambda n: -n["created_at"])
        return out[:max(1, int(limit or 5))]

    def session_recall(self, session=None, limit=5, recent_limit=10,
                       budget_tokens=1200, include_state=True):
        """按需恢复：一次调用返回「可续接的上下文包」（替代 hook 自动注入）。

        内容 = 最近会话要点 + 活跃目标 + 近期事件 + 未解问题 (+ 自我状态卡)。
        纯只读、无副作用；返回体受 budget_tokens 约束（超出即裁剪并显式上报）。
        无 hook 的载体应在会话开始时显式调用本 op 一次。
        """
        limit = max(1, min(int(limit or 5), 50))
        budget = max(200, int(budget_tokens or 1200))
        pack = {"ok": True, "session": session, "source": "session_recall",
                "notes": [], "goals": [], "recent": [], "unresolved": [],
                "degraded": []}
        # ① 会话要点
        try:
            pack["notes"] = self._session_notes(session=session, limit=limit)
        except Exception:                                  # noqa: BLE001
            pack["degraded"].append("notes")
        # ② 活跃目标（检索定向的默认来源）
        try:
            pack["goals"] = [{"id": g["id"], "goal": g["goal"],
                              "priority": g["priority"]}
                             for g in self.active_goals(limit=5)]
        except Exception:                                  # noqa: BLE001
            pack["degraded"].append("goals")
        # ③ 近期事件（原始滚动窗口）
        try:
            evs = self.recent_events(limit=max(1, int(recent_limit or 10)))
            pack["recent"] = [{"role": r.get("role"),
                               "text": (r.get("text") or "")[:300],
                               "t": r.get("t")} for r in evs]
        except Exception:                                  # noqa: BLE001
            pack["degraded"].append("recent")
        # ④ 未解问题（驱动主动补全）
        try:
            for nid, e in (self.index.get("nodes") or {}).items():
                if e.get("layer") != "unresolved":
                    continue
                _fm, content = self._read(e)
                if content is None:
                    continue
                pack["unresolved"].append(
                    {"id": nid, "question": (_ccg_field(content, "问题") or "")[:300]})
        except Exception:                                  # noqa: BLE001
            pack["degraded"].append("unresolved")
        # ⑤ 自我状态卡（只读快照，不触发 refresh 写盘）
        if include_state:
            try:
                from . import self_state as _ss
                pack["self_state"] = _ss.summary(self)
            except Exception:                              # noqa: BLE001
                pack["degraded"].append("self_state")
        # ⑥ 预算裁剪：交替丢 recent / notes 尾部，超出预算则显式上报
        pack["tokens"] = est_tokens(json.dumps(pack, ensure_ascii=False))
        while pack["tokens"] > budget and (pack["recent"] or pack["notes"]):
            if len(pack["recent"]) >= len(pack["notes"]):
                pack["recent"].pop()
            else:
                pack["notes"].pop()
            pack["tokens"] = est_tokens(json.dumps(pack, ensure_ascii=False))
        pack["budget_tokens"] = budget
        pack["truncated"] = pack["tokens"] > budget
        pack["note"] = ("只读上下文包：会话要点 + 目标 + 近期事件 + 未解问题"
                        "（+自我状态卡）。库侧替代 hook 自动注入；"
                        "会话开始时显式调用本 op 一次即可续接。")
        return pack

    def session_compact(self, session=None, limit=40, max_points=8,
                        note=False, importance=0.5):
        """上下文压缩摘要：把会话近期事件压成要点（可选写入会话节点）。

        零依赖启发式（无嵌入 / 无 LLM）：按行去重 + 角色配比 + 截断。
        返回体显式声明 heuristic=True，不冒充语义摘要（语义归纳见 consolidate）。
        """
        try:
            evs = self.recent_events(limit=max(1, int(limit or 40)))
        except Exception:                                  # noqa: BLE001
            evs = []
        if session:
            evs = [r for r in evs
                   if (r.get("meta") or {}).get("session") == session]
        roles, seen, points = {}, set(), []
        for r in evs:
            role = r.get("role") or "user"
            roles[role] = roles.get(role, 0) + 1
            for ln in (r.get("text") or "").splitlines():
                s = ln.lstrip("#-*> \t").strip()
                if len(s) < 8 or s in seen:
                    continue
                seen.add(s)
                points.append({"role": role, "text": s[:200]})
        # 优先保留 user 行（指令 / 意图），再 assistant
        points.sort(key=lambda p: 0 if p["role"] == "user" else 1)
        pts = points[:max(1, int(max_points or 8))]
        body = "\n".join(f"- [{p['role']}] {p['text']}" for p in pts)
        summary = (f"会话摘要（{session or 'current'}）：共 {len(evs)} 条事件，"
                   f"角色分布 {roles}。要点：\n{body}")
        out = {"ok": True, "session": session, "events": len(evs),
               "roles": roles, "points": len(pts), "summary": summary,
               "heuristic": True,
               "note": "启发式压缩（去重 + 角色配比 + 截断），非语义摘要；"
                       "需要语义归纳请用 consolidate/induce（P2）。"}
        if note:
            r = self.session_note(summary, session=session,
                                  tags=["session:compact"], importance=importance)
            out["written_id"] = r["id"]
        return out

    # ================= 维护面（P1：maintain / consolidate） =================
    #
    # 分工：`maintain` 管「已记住的东西怎么保持健康」（重算/快照/前馈/分离），
    #       `consolidate` 管「记住的东西怎么升格」（情境→长期）。二者都不进默认
    #       召回热路径，只在显式调用时工作。

    MAINTAIN_ACTIONS = ("stat", "history", "importance", "longterm",
                        "prefeed", "separate", "rollback",
                        "backfill", "backfill_rollback", "backfill_history",
                        "cap", "cap_rollback", "cap_history",
                        "exempt", "exempt_rollback", "exempt_history")

    def prefeed(self, content, layer="contextual", role=None,
                verification_basis=None, importance_hint=None, node_id=None,
                write=False, tags=None, conditions=None):
        """海马体前馈：写入**之前**做新奇检测——重复项并入而非新增。

        write=False（默认）只做裁决预演（不写盘）；write=True 时按裁决落库：
        ACCEPT→add / MERGE→forgetting.reinforce / DROP|DEFER→不写。
        """
        vd = forgetting.prefeed(self, content, layer=layer, role=role,
                                verification_basis=verification_basis,
                                importance_hint=importance_hint, node_id=node_id)
        out = dict(vd)
        out["written"] = None
        out["reinforced"] = None
        if not write:
            out["note"] = "前馈预演（未写盘）；write=True 才按裁决落库"
            return out
        dec = vd["decision"]
        if dec == "write":
            nid = node_id or forgetting._prefeed_id(content)
            tg = list(tags or [])
            if "prefeed" not in tg:
                tg.append("prefeed")
            out["written"] = self.add(
                nid, content, layer=layer, tags=tg,
                importance=(0.5 if importance_hint is None else importance_hint),
                verification_basis=verification_basis,
                condition_space=conditions,
                actor=getattr(self, "actor", None))
        elif dec == "reinforce" and vd.get("duplicate_with"):
            out["reinforced"] = forgetting.reinforce(self, vd["duplicate_with"])
        out["note"] = {"write": "已新增节点", "reinforce": "已并入既有节点（未新增）",
                       "discard": "已丢弃（不写）", "defer": "留待复核（不写不并）"}.get(dec, "")
        return out

    def maintain(self, action="stat", layer=None, limit=None, apply=False,
                 min_delta=None, max_rows=None, force=False, keep=None,
                 mode=None, snapshot_id=None, batch=None, entry_ids=None,
                 content=None, role=None, verification_basis=None,
                 importance_hint=None, node_id=None, write=False,
                 min_jaccard=None, ids=None, pairs=None, actor=None, **extra):
        """记忆维护（P1）：importance / longterm / prefeed / separate / stat。

        只读 action（stat/history/longterm 预演）与写层 action（prefeed）不受
        管理权限约束；apply 类批量改写由 MCP 分发层 `require_admin` 把守。
        """
        act = str(action or "stat").strip().lower()
        if act == "importance":
            return weights.recalc(self, layer=layer, limit=limit, apply=apply,
                                  min_delta=(weights.APPLY_DELTA if min_delta is None
                                             else min_delta),
                                  actor=actor or getattr(self, "actor", "maintain"))
        if act == "longterm":
            md = str(mode or "").strip().lower()
            if md in ("list", "ls"):
                return forgetting.longterm_list(self, limit=limit or 20)
            if md in ("show", "read"):
                return forgetting.longterm_show(self, snapshot_id=snapshot_id)
            return forgetting.longterm_assess(
                self, apply=apply, layer=layer, max_rows=max_rows,
                keep=(forgetting.LONGTERM_KEEP if keep is None else keep),
                force=force, actor=actor or getattr(self, "actor", "maintain"))
        if act == "prefeed":
            if content is None:
                raise ValueError("maintain.prefeed 需要 content")
            return self.prefeed(content, layer=layer or "contextual", role=role,
                                verification_basis=verification_basis,
                                importance_hint=importance_hint, node_id=node_id,
                                write=write)
        if act == "separate":
            return subgraph.separate_run(
                self, layer=layer, pairs=pairs, apply=apply, ids=ids,
                min_jaccard=(subgraph.SEP_MIN_JACCARD if min_jaccard is None
                             else min_jaccard),
                limit=limit or subgraph.SEP_MAX_PAIRS,
                actor=actor or getattr(self, "actor", "maintain"))
        if act == "rollback":
            return weights.rollback(self, batch=batch, entry_ids=entry_ids,
                                    actor=actor or getattr(self, "actor", "maintain"))
        if act in ("history", "log"):
            return {"ok": True, "action": "history",
                    "records": forgetting.maintain_history(
                        self, limit=limit or 100, action=extra.get("filter_action"))}
        if act in ("backfill", "backfill_rollback", "backfill_history",
                   "cap", "cap_rollback", "cap_history",
                   "exempt", "exempt_rollback", "exempt_history"):
            from . import backfill
            who = actor or getattr(self, "actor", "maintain")
            if act == "backfill":
                common = dict(layer=layer, limit=limit, ids=ids,
                              include_partial=bool(extra.get("include_partial")),
                              basis_text=extra.get("basis_text"))
                if apply:
                    return backfill.apply(self, batch=batch,
                                          entry_ids=entry_ids, actor=who, **common)
                return backfill.plan(self, **common)
            if act == "backfill_rollback":
                return backfill.rollback(self, batch=batch,
                                         entry_ids=entry_ids, actor=who)
            if act == "backfill_history":
                return backfill.history(self, limit=limit or 100)
            if act == "cap":
                common = dict(layer=layer, limit=limit, ids=ids,
                              min_conf=(0.5 if extra.get("min_conf") is None
                                        else float(extra.get("min_conf"))))
                if apply:
                    return backfill.cap_apply(self, batch=batch,
                                              entry_ids=entry_ids, actor=who,
                                              **common)
                return backfill.cap_plan(self, **common)
            if act == "cap_rollback":
                return backfill.cap_rollback(self, batch=batch,
                                             entry_ids=entry_ids, actor=who)
            if act == "cap_history":
                return backfill.history(self, limit=limit or 100, action="cap")
            common = dict(layer=layer, limit=limit, ids=ids,
                          require_ready=bool(extra.get("require_ready", True)))
            if act == "exempt":
                if apply:
                    return backfill.exempt_apply(self, batch=batch,
                                                 entry_ids=entry_ids, actor=who,
                                                 **common)
                common["sample"] = int(extra.get("sample") or 0)
                return backfill.exempt_plan(self, **common)
            if act == "exempt_rollback":
                return backfill.exempt_rollback(self, batch=batch,
                                                entry_ids=entry_ids, actor=who)
            return backfill.history(self, limit=limit or 100, action="exempt")
        if act == "stat":
            nodes = self.index.get("nodes") or {}
            by_layer, imp_sum, protected, missing_basis = {}, 0.0, 0, 0
            for e in nodes.values():
                lay = e.get("layer") or "?"
                by_layer[lay] = by_layer.get(lay, 0) + 1
                imp_sum += float(e.get("importance", 0.0) or 0.0)
                if e.get("protected"):
                    protected += 1
                if not e.get("verification_basis"):
                    missing_basis += 1
            n = max(1, len(nodes))
            cur = None
            try:
                with open(forgetting.current_path(self), encoding="utf-8") as f:
                    cur = json.load(f)
            except (OSError, ValueError):
                cur = None
            return {"ok": True, "action": "stat", "op": "maintain",
                    "actions": list(self.MAINTAIN_ACTIONS),
                    "nodes": len(nodes), "by_layer": by_layer,
                    "importance": {"avg": round(imp_sum / n, 4),
                                   "protected": protected,
                                   "missing_basis": missing_basis},
                    "maintain_log": len(forgetting.maintain_history(self, limit=10 ** 9)),
                    "longterm": {"current": cur},
                    "note": "只读盘点；apply 类动作需管理权限（require_admin）。"}
        raise ValueError(f"maintain 未知 action：{act}（可选 {list(self.MAINTAIN_ACTIONS)}）")

    def consolidate_run(self, action="promote", **kw):
        """离线固化面（P1：promote；P2：induce/run）。"""
        from . import consolidate
        act = str(action or "promote").strip().lower()
        if act == "promote":
            return consolidate.promote_memories(
                self.root, source_layer=kw.get("source_layer") or "contextual",
                target_layer=kw.get("target_layer") or "knowledge",
                min_merge=(2 if kw.get("min_merge") is None else kw.get("min_merge")),
                min_importance=(0.6 if kw.get("min_importance") is None
                                else kw.get("min_importance")),
                require_conditions=(True if kw.get("require_conditions") is None
                                    else bool(kw.get("require_conditions"))),
                limit=kw.get("limit"), apply=bool(kw.get("apply")),
                actor=kw.get("actor") or getattr(self, "actor", "maintain"))
        if act in ("promote_rollback", "rollback"):
            return consolidate.rollback_promotion(
                self.root, node_ids=kw.get("node_ids") or kw.get("ids"),
                batch=kw.get("batch"), actor=kw.get("actor") or "maintain")
        if act == "promote_history":
            return {"ok": True, "records": [r for r in consolidate._read_maintain(self.root)
                                            if r.get("action") == "promote"][-(kw.get("limit") or 50):]}
        if act == "induce":
            i_kw = dict(kw)
            # 与 promote 同构：MCP 未传时回落到既定默认层，避免 None 变成「扫描全层」
            i_kw["source_layer"] = kw.get("source_layer") or "contextual"
            i_kw["target_layer"] = kw.get("target_layer") or "knowledge"
            return consolidate.induce_memories(self, **i_kw)
        raise ValueError(f"consolidate 未知 action：{act}"
                         "（可选 promote|promote_rollback|promote_history|induce）")

    # ================= 洞察（P2：insight） =================
    #
    # 与 maintain/consolidate 的分工：
    #   maintain    —— 已有记忆的维护（重算/快照/前馈/分离）；
    #   consolidate —— 已有情境记忆的升格与归纳；
    #   insight     —— **条件层记账 + 情景重构 + 盲区学习 + 结构洞察**。
    # 三者都不进默认召回热路径，只在显式调用时工作。

    INSIGHT_ACTIONS = ("window", "record", "verify", "list", "report",
                       "reconstruct", "learn", "outlook", "catalog")

    def insight(self, action="outlook", **kw):
        """洞察条件层 + 情景重构 + 盲区学习 + 结构洞察（P2）。

        只读：window / list / report / reconstruct / outlook / catalog
        记账：record / verify（条件层事件，写 contextual）
        落库：learn(apply) 写 gap_hint；reconstruct(apply) 写 scene 节点
        apply 类批量落库由 MCP 分发层 `require_admin` 把守（见 `_insight_call`）。
        """
        from . import insight as ins
        from . import predict, subgraph
        act = str(action or "outlook").strip().lower()
        actor = kw.get("actor") or getattr(self, "actor", "insight")
        conditions = kw.get("conditions")

        if act == "window":
            return {"ok": True, "action": "window", "op": "insight",
                    **ins.window(conditions)}
        if act == "record":
            rkw = {k: kw.get(k) for k in ("statement", "category", "source",
                                          "tags", "node_id")}
            rkw["conditions"] = conditions if isinstance(conditions, dict) else None
            rkw["importance"] = 0.5 if kw.get("importance") is None else kw.get("importance")
            rkw["actor"] = actor
            return ins.record(self, **rkw)
        if act == "verify":
            return ins.verify(self, node_id=kw.get("node_id"),
                              evidence=kw.get("evidence"),
                              v_types=kw.get("v_types"),
                              verdict=kw.get("verdict"), actor=actor,
                              note=kw.get("note") or "")
        if act in ("list", "events"):
            events = ins.list_events(self, state=kw.get("state"),
                                     limit=kw.get("limit") or 0)
            return {"ok": True, "action": "list", "op": "insight",
                    "state": kw.get("state"), "count": len(events),
                    "events": events}
        if act == "report":
            return ins.report(self, window_days=kw.get("window_days"))
        if act == "reconstruct":
            return subgraph.reconstruct_scene(
                self, clues=kw.get("clues"), ids=kw.get("ids"),
                conditions=(list(conditions)
                            if isinstance(conditions, (list, tuple)) else None),
                layer=kw.get("layer"), apply=bool(kw.get("apply")), actor=actor,
                limit=(kw.get("limit") or subgraph.RECON_MAX_ANCHORS),
                max_nodes=(kw.get("max_nodes") or subgraph.RECON_MAX_NODES),
                neighbors=(True if kw.get("neighbors") is None
                           else bool(kw.get("neighbors"))))
        if act == "learn":
            lkw = {k: kw[k] for k in ("blindspot_id", "limit", "horizon",
                                      "max_branches") if kw.get(k) is not None}
            lkw["apply"] = bool(kw.get("apply"))
            lkw["actor"] = actor
            return predict.learn_blindspots(self, **lkw)
        if act == "outlook":
            return ins.outlook(self, window_days=kw.get("window_days"),
                               sample_limit=(kw.get("sample_limit") or 8),
                               recent_days=(kw.get("recent_days") or 7))
        if act in ("catalog", "stat"):
            nodes = self.index.get("nodes") or {}
            events = ins.list_events(self)
            by_state = {}
            for e in events:
                by_state[e["state"]] = by_state.get(e["state"], 0) + 1
            return {"ok": True, "action": "catalog", "op": "insight",
                    "actions": list(self.INSIGHT_ACTIONS),
                    "conditions": list(ins.CONDITION_KEYS),
                    "v_types": list(ins.V_TYPES), "v_labels": dict(ins.V_LABELS),
                    "window_min": ins.C1_WINDOW_MIN,
                    "sample_min": ins.CER_MIN_SAMPLES,
                    "importance_floor": ins.IMPORTANCE_FLOOR,
                    "events": {"total": len(events), "by_state": by_state},
                    "nodes": len(nodes),
                    "note": "洞察层自描述：条件快照字段 + 证据类型 + 判定门槛"}
        raise ValueError(f"insight 未知 action：{act}"
                         f"（可选 {list(self.INSIGHT_ACTIONS)}）")

    # ================= 健康度（并入 OS 指标） =================

    def health_os(self):
        h = self.health()
        h["os"] = {
            "roles": self._role_counts(),
            "review_pending": len(self.review_list()),
            "review_records": len(self.review_records()),
            "tombstones": len(list(read_jsonl(self.deletions_log))),
            "audit_events": len(list(read_jsonl(self.audit_log))),
            "reflections": len(self.last_d_records()),
            # 七件套覆盖度（第 5 篇）：目标槽 + 近期事件窗口
            "goals": {"total": len(self.list_goals()),
                      "active": len(self.active_goals(limit=0))},
            "recent_events": len(self.recent_events(limit=0)),
            # 写保护 + 主动遗忘面（可审计；ids 列表不塞进健康度，避免膨胀）
            "protection": {k: v for k, v in self.protect_stats().items()
                           if k not in ("ids", "immutable_ids")},
            "forgetting": forgetting.summary(self),
            # 身份特征识别（智能论 v3.4 位置效应 + 扮演论三接口）
            "identity": identity.summary(self),
            # 节点间自动冲突检测（三级决策：情绪 → 反思 → 递归反思）
            "consistency": consistency.summary(self),
            # 独立元认知（观察自身认知的二阶单元，不参与裁决）
            "metacognition": metacognition.summary(self),
            # 自我状态层（薄自我 + 富索引：八项自我信息的一致性载体）
            "self_state": self_state.summary(self),
            # 演化账本（md 载体：每一次修改 = 补一条缺失条件，记录规律与状态）
            "evolution": evolution.summary(self),
        }
        return h

    def _role_counts(self):
        c = {}
        for e in self.index["nodes"].values():
            r = e.get("role") or "(none)"
            c[r] = c.get(r, 0) + 1
        return c


# ==========================================================================
# 记忆 OS #2 · 权限模型（公开知识 / 私有记忆隔离）
# ==========================================================================

    # ============ 8. 嵌套子图 + 关系链（结构要素的可递归化 / 因果链＝条件链）============

    def subgraph_expand(self, node_id, max_depth=None):
        """递归展开嵌套子图：`max_depth=None` 数据驱动（展开到自然耗尽）。"""
        return subgraph.expand(self, node_id, max_depth=max_depth)

    def subgraph_flatten(self, node_id, max_depth=None):
        """摊平为「节点 + 对称父子边」（part_of / parent_of）。"""
        return subgraph.flatten(self, node_id, max_depth=max_depth)

    def subgraph_validate(self, limit=50):
        """树一致性：多父 / 环 / 悬空 / 自环（不一致 → 该层判定应退回 DEFER）。"""
        return subgraph.validate(self, limit=limit)

    def subgraph_roots(self):
        return subgraph.roots(self)

    # ---- 主动遗忘（写入侧三问闸门）+ 写保护盘点 ----

    def remember_gated(self, node_id, content, layer="contextual", **kw):
        """写入情景层记忆前的**主动遗忘闸门**：三问 → 四态。

        理论：J 判断引擎 9-10 档「独立元认知 + 主动遗忘」；
        prefeed（新奇检测）/ pattern_separation（相似分离）/ nightly_cleanup
        三者的**写入侧前置版**——不等夜间整理，写之前就裁决。

        ACCEPT 写入 / MERGE 并入既有（不新增，强化既有节点）/
        DROP 丢弃（低熵噪音）/ DEFER 待定（不写）。
        四种结果都写进 `_forgetting.jsonl`，可审计。
        """
        role = kw.get("role")
        vb = kw.get("verification_basis")
        hint = kw.pop("importance_hint", kw.get("importance"))
        gated = kw.pop("gated", True)
        override = kw.pop("override", False)
        do_consistency = kw.pop("consistency", False)
        on_conflict = kw.pop("on_conflict", "defer")
        if not gated:
            return {"verdict": "ACCEPT", "bypass": True, "gate": None,
                    "node_id": node_id,
                    "written": self.add(node_id, content, layer=layer,
                                        override=override, **kw)}
        verdict = forgetting.assess(self, content, layer=layer, role=role,
                                    verification_basis=vb, importance_hint=hint,
                                    node_id=node_id)
        v = verdict["verdict"]
        out = {"verdict": v, "node_id": node_id, "gate": verdict}
        if v == "ACCEPT":
            if hint is not None and "importance" not in kw:
                kw["importance"] = hint
            try:
                out["written"] = self.add(node_id, content, layer=layer,
                                          override=override,
                                          consistency=do_consistency,
                                          on_conflict=on_conflict, **kw)
            except consistency.ConsistencyError as e:
                v = out["verdict"] = "DEFER"
                out["conflict"] = {"verdict": e.verdict, "reason": e.reason,
                                   "conflicts": e.conflicts}
            else:
                if out.get("written") is None:  # on_conflict=defer：冲突未落盘
                    v = out["verdict"] = "DEFER"
        elif v == "MERGE":
            tgt = verdict["redundancy"]["with"]
            out["merged_into"] = tgt
            out["reinforced"] = forgetting.reinforce(self, tgt) if tgt else None
        # DROP / DEFER：不落库，只留痕
        forgetting.log(self, {"t": time.time(), "node_id": node_id,
                              "layer": layer, "verdict": v,
                              "reason": verdict["reason"],
                              "importance": verdict["importance"],
                              "entropy": verdict["entropy"],
                              "actor": self.actor})
        return out

    def forgetting_history(self, limit=100):
        """遗忘裁决留痕：为什么没记住，与为什么记住同样可查。"""
        return forgetting.history(self, limit=limit)

    def protect_stats(self):
        """写保护面盘点：受保护节点数、分层分布、自动保护命中数。"""
        return protect.stats(self)

    # ---- 身份特征识别（智能论 v3.4 位置效应 + 扮演论三接口）----

    def identity_observe(self, subject_id, text, **kw):
        """memory 接口：记录主体行为证据（供位置效应推断）。"""
        return identity.observe(self, subject_id, text, **kw)

    def identity_anchor(self, subject_id, text, **kw):
        """anchor 接口：写身份锚点（不可遗忘；role/user 不得进 self 层）。"""
        return identity.set_anchor(self, subject_id, text, **kw)

    def identity_trait(self, subject_id, trait, **kw):
        """values 接口：写条件触发的特征 / 特化价值观（落结构层）。"""
        return identity.add_trait(self, subject_id, trait, **kw)

    def identity_profile(self, subject_id):
        """主体画像：身份锚点 + 位置效应 + 条件特征（不止「用户画像」）。"""
        return identity.profile(self, subject_id)

    def identity_positions(self, limit=0):
        """所有主体的位置效应分布（谁在记录/反思/验证/输出/维生）。"""
        return identity.positions(self, limit=limit)

    def identity_history(self, limit=100):
        """身份操作留痕。"""
        return identity.history(self, limit=limit)

    def identity_catalog(self):
        """自描述：位置效应表 + 扮演论三接口。"""
        return identity.catalog()

    # ---- 节点间自动冲突检测（三级决策：情绪 → 反思 → 递归反思）----

    def check_consistency(self, content, layer=None, condition_space=None,
                          non_applicable_conditions=None, tags=None,
                          exclude=None, limit=consistency.MAX_SCAN,
                          depth=consistency.MAX_DEPTH, auto_flywheel=False):
        """不落盘地预检一条待写内容是否与既有节点/纪律冲突（三级决策）。

        对齐《智能的公理化基石》§十一（情绪=信息差二阶变化，独立不参与信任）、
        条件论「反题」（预测与事实冲突）、:273（递归受深度/节点/循环/增益门槛约束）。
        """
        return consistency.check(
            self, content, layer=layer, condition_space=condition_space,
            non_applicable_conditions=non_applicable_conditions, tags=tags,
            exclude=exclude, limit=limit, depth=depth,
            auto_flywheel=auto_flywheel)

    def consistency_history(self, limit=100):
        """冲突判定留痕：为什么冲突 / 为什么放行。"""
        return consistency.history(self, limit=limit)

    def consistency_stats(self):
        """冲突面汇总（供 health / 运维审计）。"""
        return consistency.summary(self)

    def consistency_catalog(self):
        """自描述：三级决策 + 四态 + 递归约束（供协议对照验证）。"""
        return consistency.catalog()

    # ============ 独立元认知（观察自身认知的二阶单元，不参与裁决）============

    def metacognition_report(self, window=50):
        """元认知报告：轨迹 / 校准 / 盲区 / 信任 + 确定性建议。

        智能论出处：情绪=d²D/dt²（§十一）、五大单元外部观察者（§十三）、
        推论三「局部不可知」（盲区即知识）、P_trust/P_gap（§十）。
        独立性：只读留痕，不写 confidence / 资格 / 召回打分。
        """
        return metacognition.report(self, window=window)

    def metacognition_trace(self, window=50):
        """信息差轨迹 D(t) → dD/dt（方向）→ d²D/dt²（情绪）。"""
        return metacognition.trace(self, window=window)

    def metacognition_calibration(self, max_scan=2000):
        """自信校准：期望正确率 vs 实际验证通过率（过度自信 / 过度保守）。"""
        return metacognition.calibration(self, max_scan=max_scan)

    def metacognition_blindspots(self, limit=20, window=200):
        """盲区地图：反复 BLINDSPOT 的查询邻域 + 未解问题清单。"""
        return metacognition.blindspots(self, limit=limit, window=window)

    def metacognition_trust(self, window=100):
        """P_gap（信息差置信）+ P_trust（验证稳定置信）+ d²T/dt²（情感）。"""
        return metacognition.trust(self, window=window)

    def self_check(self, query, k=5, min_sim=0.25):
        """元认知闸门：回答前先自问「我对这件事的认知状态如何」。"""
        return metacognition.self_check(self, query, k=k, min_sim=min_sim)

    def metacognition_history(self, limit=100):
        """元认知留痕（倒序）。"""
        return metacognition.history(self, limit=limit)

    def metacognition_summary(self):
        """一句话元认知状态（供 health / 面板）。"""
        return metacognition.summary(self)

    def metacognition_catalog(self):
        """自描述：观测面 + 理论出处 + 独立性约束。"""
        return metacognition.catalog()

    # ============ 自我状态层（薄自我 + 富索引）============
    # self 层只放状态卡（单例）+ 关系节点；八项自我信息只登记当前值与指针，
    # 具体任务/人物/会话/时间/信任的细节由认知图按五维索引连接（不搬运内容）。

    def self_state_snapshot(self, subject=self_state.DEFAULT_SUBJECT):
        """读自我状态卡（薄）：信息差/信任/情绪/情感/短期记忆/重要性/身份/关系。"""
        return self_state.snapshot(self, subject)

    def self_state_refresh(self, subject=self_state.DEFAULT_SUBJECT, **kw):
        """刷新状态卡：聚合八项自我信息 → 写卡 + 版本链留痕（幂等）。"""
        return self_state.refresh(self, subject, **kw)

    def self_state_bootstrap(self, subject=self_state.DEFAULT_SUBJECT, **kw):
        """会话启动加载：状态卡 + 关系 + 最近留痕 + 五维索引（跨会话自我续接）。"""
        return self_state.bootstrap(self, subject, **kw)

    def self_state_relate(self, frm, to, **kw):
        """写一条有向关系（自我 ↔ 其他智能），reciprocal=True 时双向。"""
        return self_state.relate(self, frm, to, **kw)

    def self_state_relations(self, subject=None, direction="both"):
        """列出关系节点（按 subject 过滤出/入）。"""
        return self_state.relations(self, subject=subject, direction=direction)

    def self_state_index(self, dim, value, **kw):
        """按五维索引（task/person/session/time/trust）反查具体详情节点。"""
        return self_state.index(self, dim, value, **kw)

    def self_state_dimensions(self, subject=self_state.DEFAULT_SUBJECT):
        """状态卡登记的五维索引标签。"""
        return self_state.dimensions(self, subject)

    def self_state_audit(self, subject=self_state.DEFAULT_SUBJECT, **kw):
        """自我信息一致性审计：单例/版本链/时序/派生自洽/跨面一致/身份/关系/保护/索引。"""
        return self_state.audit(self, subject, **kw)

    def self_state_history(self, limit=100, subject=None):
        """自我状态留痕（倒序，含版本链 hash）。"""
        return self_state.history(self, limit=limit, subject=subject)

    def self_state_summary(self, subject=self_state.DEFAULT_SUBJECT):
        """一句话自我状态（供 health / 面板）。"""
        return self_state.summary(self, subject)

    def self_state_catalog(self):
        """自描述：八项自我信息 + 五维索引 + 审计规则。"""
        return self_state.catalog()

    def causal_chain(self, node_id, relation_types=None,
                     max_depth=chain.MAX_DEPTH_DEFAULT, direction="out",
                     max_chains=50, sort="strength"):
        """沿关系链展开：`causal` = 条件依赖因果，链 = 条件序列。

        返回链列表，每条含 nodes / hops（带条件与权重）/ conditions / weight。
        """
        return chain.walk(self, node_id,
                          relation_types=relation_types or chain.CAUSAL_TYPES,
                          max_depth=max_depth, direction=direction,
                          max_chains=max_chains, sort=sort)

    def explain_chain(self, node_id, **kw):
        """人类可读链式解释：「什么条件下 → 发生什么」。"""
        return chain.explain(self, node_id, **kw)

    # ============ 生成式预测 / 因果推理 ============

    def predict_routes(self, start_id=None, blindspot_id=None,
                       horizon=predict.HORIZON_DEFAULT,
                       max_branches=predict.MAX_BRANCHES_DEFAULT,
                       sort="composite", limit=0, semantic=True):
        """生成候选未来路线（D-001~D-005）：**候选未来，非必然未来**。"""
        return predict.routes(self, start_id=start_id,
                              blindspot_id=blindspot_id, horizon=horizon,
                              max_branches=max_branches, sort=sort,
                              limit=limit, semantic=semantic)

    def predict_feedback(self, predicted_node_id, actual_node_id=None,
                         hit=None, note="", actor="predict"):
        """预测反馈（D-006）：命中 → 边置信度 +0.05；未命中 → 登记 rejected。"""
        return predict.feedback(self, predicted_node_id, actual_node_id,
                                hit=hit, note=note, actor=actor)

    def predict_stats(self, limit=20):
        """预测统计：调用数 / 路线数 / 命中率 / 动态阈值。"""
        return predict.stats(self, limit=limit)

    def predict_catalog(self):
        """自描述：D-001~D-006 决策、权重、校准参数、与 AEIS 的差异。"""
        return predict.catalog()

    def causal_path(self, a_id, b_id, max_depth=5):
        """因果路径推理：A 能否沿因果/时序边到达 B（伪因果防护的完整语义）。"""
        return predict.causal_path(self, a_id, b_id, max_depth=max_depth)

    def causal_gate(self, a_id, b_id):
        """D-002 伪因果过滤门 → (准入?, 理由)。"""
        return predict.causal_gate(self, a_id, b_id)

    # ============ 演化账本（md 载体：规律 + 状态，可回滚）============
    # 每一次修改 = 对一条缺失条件的补充；记录的是认知规律与状态，不是实现。

    def evolution_record(self, node_id=None, pattern="", missing="", action="",
                         evidence="", source="", kind=None, before=None,
                         after=None, **extra):
        """追加一条演化条目（pattern=规律 必填）。"""
        return evolution.record(
            self, node_id=node_id, pattern=pattern, missing=missing,
            action=action, evidence=evidence, source=source,
            kind=kind or evolution.KIND_CONDITION_GAP,
            before=before, after=after, extra=extra or None)

    def evolution_entries(self, limit=50, node_id=None, kind=None):
        """账本条目（倒序）。"""
        return {"entries": evolution.entries(
            self, limit=limit, node_id=node_id, kind=kind)}

    def evolution_show(self, entry_id):
        """单条演化条目。"""
        return {"entry": evolution.show(self, entry_id)}

    def evolution_history(self, node_id, limit=50):
        """某节点的演化史（倒序）。"""
        return evolution.history(self, node_id, limit=limit)

    def evolution_patterns(self, limit=10):
        """规律统计：哪一维条件反复缺失、由谁触发、哪些规律重复出现。"""
        return evolution.patterns(self, limit=limit)

    def evolution_summary(self):
        """一句话演化状态（供 health / 面板）。"""
        return evolution.summary(self)

    def evolution_rollback(self, entry_id, dry_run=False, note=""):
        """把某条演化撤回其 before 状态；撤销本身也记一条条目。"""
        return evolution.rollback(self, entry_id, dry_run=dry_run, note=note)

    def evolution_catalog(self):
        """自描述：载体 + 原则 + 字段 + 可回滚范围。"""
        return evolution.catalog()


class MdCGSecure(MdCGOS):
    """带权限的记忆 OS：租户 + 密级（clearance）× 节点敏感度（sensitivity）。

    动机：灵枢是开源仓库，私有记忆不能混进公开根。本类保证：
      · 读隔离：clearance 之下的节点对调用方不可见（search/recall/get 一致过滤）
      · 写隔离：写入高于 clearance 的敏感度 → AccessDenied
      · 管理隔离：forget/restore/review_decide 需 can_admin
      · 审计带 tenant/actor/session（可追溯到哪个会话做了什么）
    """

    def __init__(self, root: str, principal: Principal = None,
                 master_key=None, **kw):
        self.principal = principal or Principal()
        self.kek = None
        self.dek = None
        self._crypto_error = None
        super().__init__(root, actor=self.principal.actor, **kw)
        self.session = self.principal.session
        self._init_crypto(master_key)

    # ---------- 私有内容加密（密钥即访问权 + 身份一致性识别）----------

    def _init_crypto(self, master_key=None):
        """解析 KEK（显式 → 环境变量 → 仓库外主密钥文件），签发本身份 DEK。

        主密钥缺失时自动生成于仓库外 `~/.mdcg/master.key`（0600）；
        仍取不到才 `dek=None`，写 private/secret 时 fail-closed。
        """
        try:
            kek = (self._resolve_master_key(master_key)
                   if master_key is not None
                   else crypto.load_master_key())
            if not kek:
                self._crypto_error = "no_master_key"
                self.kek = self.dek = None
                return
            self.kek = kek
            self.dek = crypto.provision_dek(
                self.root, kek, self.principal.tenant, self.principal.actor,
                clearance=self.principal.clearance)
            self._crypto_error = None
        except (crypto.CryptoError, OSError) as e:
            self._crypto_error = str(e)
            self.kek = self.dek = None

    @staticmethod
    def _resolve_master_key(master_key):
        """接受 32B bytes / 64 位 hex / base64 / 密钥文件路径。"""
        if isinstance(master_key, (bytes, bytearray)):
            k = bytes(master_key)
        else:
            s = str(master_key).strip()
            if os.path.exists(s):
                with open(s, encoding="utf-8") as f:
                    s = f.read().strip()
            try:
                k = bytes.fromhex(s) if len(s) == 64 else crypto._b64d(s)
            except ValueError as e:
                raise crypto.CryptoError(
                    "主密钥须为 32 字节 / 64 位 hex / base64 / 密钥文件") from e
        if len(k) != crypto.KEY_LEN:
            raise crypto.CryptoError("主密钥须为 32 字节")
        return k

    def unlock(self, master_key=None):
        """运行时解锁（显式密钥 / 重新加载环境变量或主密钥文件）。"""
        self._init_crypto(master_key)
        return self.crypto_status()

    def lock(self):
        """锁定：丢弃内存中的密钥（已落盘密文不受影响）。"""
        self.kek = self.dek = None
        self._crypto_error = "locked"
        return self.crypto_status()

    def crypto_status(self):
        """当前加密状态（不含密钥材料）。"""
        return {
            "unlocked": self.dek is not None,
            "tenant": self.principal.tenant,
            "actor": self.principal.actor,
            "id_fp": crypto.identity_fingerprint(self.principal.tenant,
                                                 self.principal.actor),
            "kek_fp": crypto.kek_fingerprint(self.kek) if self.kek else None,
            "encrypted_levels": list(crypto.ENCRYPTED_LEVELS),
            "error": self._crypto_error,
            "keys_file": crypto.keys_path(self.root),
            "envelopes": crypto.envelopes(self.root),
        }

    def _seal_content(self, node_id, content, sensitivity=None):
        """私有内容（private / secret）写入前加密；无密钥 → fail-closed。"""
        sens = sensitivity or DEFAULT_SENSITIVITY
        if sens not in crypto.ENCRYPTED_LEVELS or crypto.is_encrypted(content):
            return content
        if not self.dek:
            crypto.audit(self.root, {"op": "seal_denied", "node_id": node_id,
                                     "tenant": self.principal.tenant,
                                     "actor": self.principal.actor,
                                     "reason": self._crypto_error or "no_dek"})
            raise crypto.LockedError(
                f"{sens} 内容需加密，但当前无可用密钥（{self._crypto_error}）")
        sealed = crypto.seal_node(content, self.dek, node_id,
                                  self.principal.tenant, self.principal.actor)
        crypto.audit(self.root, {"op": "seal", "node_id": node_id,
                                 "sensitivity": sens,
                                 "tenant": self.principal.tenant,
                                 "actor": self.principal.actor})
        return sealed

    def _open_content(self, node_id, fm, content):
        """密文解封；无密钥 / 身份不符 → None（不可读），失败留审计。"""
        if content is None or not crypto.is_encrypted(content):
            return content
        if not self.dek:
            crypto.audit(self.root, {"op": "read_locked", "node_id": node_id,
                                     "tenant": self.principal.tenant,
                                     "actor": self.principal.actor,
                                     "reason": self._crypto_error or "no_dek"})
            return None
        try:
            return crypto.open_node(content, self.dek, node_id,
                                    self.principal.tenant, self.principal.actor)
        except crypto.CryptoError as e:
            crypto.audit(self.root, {"op": "open_failed", "node_id": node_id,
                                     "tenant": self.principal.tenant,
                                     "actor": self.principal.actor,
                                     "reason": str(e)[:120]})
            return None

    # ---------- 索引：把 role / sensitivity 一并索引 ----------

    def _scan_nodes(self):
        nodes = super()._scan_nodes()
        for nid, e in nodes.items():
            fm, _c = self._read(e)
            if fm:
                e["role"] = fm.get("role")
                e["sensitivity"] = fm.get("sensitivity") or DEFAULT_SENSITIVITY
        return nodes

    def _index_sensitivity(self, nid, sens):
        e = self.index["nodes"].get(nid)
        if e is not None:
            e["sensitivity"] = sens
            self._dirty[nid] = e

    # ---------- 写：权限校验 ----------

    def add(self, node_id: str, content: str, layer: str = "knowledge",
            sensitivity: str = None, **kw) -> str:
        sens = sensitivity or DEFAULT_SENSITIVITY
        _rank(sens)
        self.principal.require_layer_write(layer, sens)
        nid = super().add(node_id, content, layer=layer, sensitivity=sens, **kw)
        self._index_sensitivity(nid, sens)
        return nid

    def add_rejected(self, hypothesis: str, reason: str, sensitivity: str = None, **kw) -> str:
        sens = sensitivity or DEFAULT_SENSITIVITY
        self.principal.require_layer_write("rejected", sens)
        nid = super().add_rejected(hypothesis, reason, sensitivity=sens, **kw)
        self._index_sensitivity(nid, sens)
        return nid

    def add_unresolved(self, question: str, known_clues: str = "", goal: str = "",
                       sensitivity: str = None, **kw) -> str:
        sens = sensitivity or DEFAULT_SENSITIVITY
        self.principal.require_layer_write("unresolved", sens)
        nid = super().add_unresolved(question, known_clues, goal, sensitivity=sens, **kw)
        self._index_sensitivity(nid, sens)
        return nid

    def propose(self, node_id: str, content: str, sensitivity: str = None, **kw):
        sens = sensitivity or DEFAULT_SENSITIVITY
        self.principal.require_layer_write(kw.get("layer") or "contextual", sens)
        return super().propose(node_id, content, sensitivity=sens, **kw)

    def add_goal(self, goal: str, sensitivity: str = None, **kw) -> str:
        sens = sensitivity or DEFAULT_SENSITIVITY
        _rank(sens)
        self.principal.require_layer_write("goals", sens)
        gid = super().add_goal(goal, sensitivity=sens, **kw)
        self._index_sensitivity(gid, sens)
        return gid

    def set_goal_status(self, node_id: str, status: str):
        self.principal.require_layer_write("goals", DEFAULT_SENSITIVITY)
        return super().set_goal_status(node_id, status)

    def remember_event(self, role: str, text: str, tags=None, meta=None,
                       window=None, sensitivity: str = None):
        sens = sensitivity or DEFAULT_SENSITIVITY
        _rank(sens)
        self.principal.require_write(sens)
        m = dict(meta or {})
        m.setdefault("tenant", self.principal.tenant)
        m.setdefault("session", self.principal.session)
        m["sensitivity"] = sens
        text = self._seal_content("_recent", text, sens)
        if window is None:
            return super().remember_event(role, text, tags=tags, meta=m)
        return super().remember_event(role, text, tags=tags, meta=m, window=window)

    # ---------- 读：密级过滤 ----------

    def _readable(self, e) -> bool:
        sens = e.get("sensitivity")
        if not sens:
            # 索引可能被「无密级上下文」的实例重建而丢掉该字段：按盘上真相回填，
            # fail-closed（宁可少读，不可越权）。
            fm, _c = self._read(e)
            sens = (fm or {}).get("sensitivity") or DEFAULT_SENSITIVITY
            e["sensitivity"] = sens
        return self.principal.allows(sens)

    def list_goals(self, status=None, limit=None):
        """读隔离：只返回当前 clearance 可见的目标（active_goals/goal_text 同源过滤）。"""
        out = super().list_goals(status=status, limit=None)
        keep = []
        for g in out:
            e = self.index["nodes"].get(g["id"])
            if e is not None and self._readable(e):
                keep.append(g)
        return keep[:limit] if limit else keep

    def recent_events(self, limit=20, roles=None, since=None, newest_first=True):
        """读隔离：只返回本 tenant 且当前 clearance 可见的近期事件。"""
        out = super().recent_events(limit=0, roles=roles, since=since,
                                    newest_first=newest_first)
        keep = []
        for r in out:
            m = r.get("meta") or {}
            if m.get("tenant", self.principal.tenant) != self.principal.tenant:
                continue
            if not self.principal.allows(m.get("sensitivity") or DEFAULT_SENSITIVITY):
                continue
            if crypto.is_encrypted(r.get("text")):
                t = self._open_content("_recent", m, r["text"])
                if t is None:
                    continue
                r = dict(r)
                r["text"] = t
            keep.append(r)
        return keep[:limit] if limit else keep

    def clear_recent(self):
        self.principal.require_admin("clear_recent")
        return super().clear_recent()

    def _candidates(self, layer=None, roles=None, include_work=False):
        out = super()._candidates(layer=layer, roles=roles, include_work=include_work)
        return [e for e in out if self._readable(e)]

    def _neg_coverage(self, terms):
        return [e for e in super()._neg_coverage(terms) if self._readable(e)]

    def get(self, node_id: str):
        e = self.index["nodes"].get(node_id)
        if e is not None and not self._readable(e):
            return None                     # 读隔离：不可见即不存在
        return super().get(node_id)

    def search_rrf(self, *a, **kw):
        """RRF 路径里的图扩展会绕过 _candidates，这里显式再过滤一次。"""
        res, meta = super().search_rrf(*a, **kw)
        res = [r for r in res
               if self._readable(self.index["nodes"].get(r[0]["id"], r[0]))]
        return res, meta

    # ---------- 管理：需 can_admin ----------

    def forget(self, node_id: str, reason: str = "", override: bool = False):
        self.principal.require_admin("forget")
        return super().forget(node_id, reason, override=override)

    def restore(self, node_id: str, force: bool = False):
        self.principal.require_admin("restore")
        return super().restore(node_id, force=force)

    def review_decide(self, *a, **kw):
        self.principal.require_admin("review_decide")
        return super().review_decide(*a, **kw)

    def evolution_rollback(self, entry_id, dry_run=False, note=""):
        """回滚是管理操作：撤回结构变更 → 需 can_admin。"""
        self.principal.require_admin("evolution_rollback")
        return super().evolution_rollback(entry_id, dry_run=dry_run, note=note)

    # ---------- 身份/审计 ----------

    def whoami(self):
        p = self.principal
        out = {"principal": p.as_dict(), "root": self.root,
               "readable_sensitivities": [s for s in SENSITIVITY_ORDER
                                          if p.allows(s)],
               "nodes_visible": sum(1 for e in self.index["nodes"].values()
                                    if self._readable(e)),
               "nodes_total": len(self.index["nodes"]),
               "encryption": self.crypto_status()}
        try:                                  # 角色职责自描述（未知角色不阻塞）
            from . import tokens as _tk
            spec = _tk.role_spec(p.role)
            out["role_label"] = spec["label"]
            out["duty"] = spec["duty"]
            out["forbidden"] = spec["forbidden"]
        except Exception:                     # noqa: BLE001
            pass
        return out

    def _audit(self, op, node_id, **meta):
        meta.setdefault("tenant", self.principal.tenant)
        meta.setdefault("session", self.principal.session)
        meta.setdefault("clearance", self.principal.clearance)
        super()._audit(op, node_id, **meta)

    def health_os(self):
        h = super().health_os()
        # 持续性自维持（常驻 / 心跳 / 会话续接）：只读摘要，不做巡检
        h["os"]["sustain"] = sustain.summary(self)
        h["security"] = {
            "tenant": self.principal.tenant,
            "clearance": self.principal.clearance,
            "sensitivity_counts": self._sensitivity_counts(),
            "encryption": self.crypto_status(),
        }
        return h

    def _sensitivity_counts(self):
        c = {}
        for e in self.index["nodes"].values():
            s = e.get("sensitivity") or DEFAULT_SENSITIVITY
            c[s] = c.get(s, 0) + 1
        return c
