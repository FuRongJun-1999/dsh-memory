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
from . import nodefile, routing
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
                    out.append(({"id": fm.get("id") or tid, "frontmatter": fm,
                                 "content": c, "path": e["path"]}, s * 0.5))
        return out

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
            cov = _weighted_coverage(tw, f"{c} {tags}")
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
        if "lexical" in paths:
            ranked["lexical"] = self._lexical(q, entries, stat)
        if "bucket" in paths:
            ranked["bucket"] = self._path_bucket(q, entries, context)
        if "entity" in paths:
            ranked["entity"] = self._path_entity(q, entries)
        if "graph" in paths:
            ranked["graph"] = self._path_graph(q, entries, ranked.get("lexical") or [])
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
                prov.setdefault(nid, []).append({"path": name, "rank": rank})
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
        self.add(nid, body, layer="self", role=self.AUDIT_ROLE,
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
            atomic_write(os.path.join(self.root, tgt["path"]),
                         nodefile.dumps(fm, merged_content))
            self.rebuild_index()
            result.update(ok=True, node_id=target)

        return self._record_decision(
            pid, item, decision,
            "rejected" if decision == "reject" else "accepted",
            reason, round_no, rt_v, rt_issues, expect, result)

    def decisions(self):
        return list(read_jsonl(self.decisions_log))

    # ================= 5. tombstone + 恢复时删除检查 =================

    def forget(self, node_id: str, reason: str = ""):
        """软删除：节点文件移入 trash/，写入删除清单（payload-free）。"""
        e = self.index["nodes"].get(node_id)
        if not e:
            return {"ok": False, "error": "not_found"}
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
        self.add(node_id, content, layer=layer, tags=tags,
                 condition_space=fm.get("condition_space"),
                 importance=fm.get("importance", 0.5),
                 confidence=fm.get("confidence", 0.6),
                 verification_basis=fm.get("verification_basis"))
        os.remove(src)
        self._audit("restore", node_id, forced=bool(force))
        return {"ok": True, "id": node_id, "forced": bool(force)}

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

class MdCGSecure(MdCGOS):
    """带权限的记忆 OS：租户 + 密级（clearance）× 节点敏感度（sensitivity）。

    动机：灵枢是开源仓库，私有记忆不能混进公开根。本类保证：
      · 读隔离：clearance 之下的节点对调用方不可见（search/recall/get 一致过滤）
      · 写隔离：写入高于 clearance 的敏感度 → AccessDenied
      · 管理隔离：forget/restore/review_decide 需 can_admin
      · 审计带 tenant/actor/session（可追溯到哪个会话做了什么）
    """

    def __init__(self, root: str, principal: Principal = None, **kw):
        self.principal = principal or Principal()
        super().__init__(root, actor=self.principal.actor, **kw)
        self.session = self.principal.session

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
        self.principal.require_write(sens)
        nid = super().add(node_id, content, layer=layer, sensitivity=sens, **kw)
        self._index_sensitivity(nid, sens)
        return nid

    def add_rejected(self, hypothesis: str, reason: str, sensitivity: str = None, **kw) -> str:
        sens = sensitivity or DEFAULT_SENSITIVITY
        self.principal.require_write(sens)
        nid = super().add_rejected(hypothesis, reason, sensitivity=sens, **kw)
        self._index_sensitivity(nid, sens)
        return nid

    def add_unresolved(self, question: str, known_clues: str = "", goal: str = "",
                       sensitivity: str = None, **kw) -> str:
        sens = sensitivity or DEFAULT_SENSITIVITY
        self.principal.require_write(sens)
        nid = super().add_unresolved(question, known_clues, goal, sensitivity=sens, **kw)
        self._index_sensitivity(nid, sens)
        return nid

    def propose(self, node_id: str, content: str, sensitivity: str = None, **kw):
        sens = sensitivity or DEFAULT_SENSITIVITY
        self.principal.require_write(sens)
        return super().propose(node_id, content, sensitivity=sens, **kw)

    def add_goal(self, goal: str, sensitivity: str = None, **kw) -> str:
        sens = sensitivity or DEFAULT_SENSITIVITY
        _rank(sens)
        self.principal.require_write(sens)
        gid = super().add_goal(goal, sensitivity=sens, **kw)
        self._index_sensitivity(gid, sens)
        return gid

    def set_goal_status(self, node_id: str, status: str):
        self.principal.require_write(DEFAULT_SENSITIVITY)
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
        if window is None:
            return super().remember_event(role, text, tags=tags, meta=m)
        return super().remember_event(role, text, tags=tags, meta=m, window=window)

    # ---------- 读：密级过滤 ----------

    def _readable(self, e) -> bool:
        return self.principal.allows(e.get("sensitivity") or DEFAULT_SENSITIVITY)

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

    def forget(self, node_id: str, reason: str = ""):
        self.principal.require_admin("forget")
        return super().forget(node_id, reason)

    def restore(self, node_id: str, force: bool = False):
        self.principal.require_admin("restore")
        return super().restore(node_id, force=force)

    def review_decide(self, *a, **kw):
        self.principal.require_admin("review_decide")
        return super().review_decide(*a, **kw)

    # ---------- 身份/审计 ----------

    def whoami(self):
        p = self.principal
        return {"principal": p.as_dict(), "root": self.root,
                "readable_sensitivities": [s for s in SENSITIVITY_ORDER
                                           if p.allows(s)],
                "nodes_visible": sum(1 for e in self.index["nodes"].values()
                                     if self._readable(e)),
                "nodes_total": len(self.index["nodes"])}

    def _audit(self, op, node_id, **meta):
        meta.setdefault("tenant", self.principal.tenant)
        meta.setdefault("session", self.principal.session)
        meta.setdefault("clearance", self.principal.clearance)
        super()._audit(op, node_id, **meta)

    def health_os(self):
        h = super().health_os()
        h["security"] = {
            "tenant": self.principal.tenant,
            "clearance": self.principal.clearance,
            "sensitivity_counts": self._sensitivity_counts(),
        }
        return h

    def _sensitivity_counts(self):
        c = {}
        for e in self.index["nodes"].values():
            s = e.get("sensitivity") or DEFAULT_SENSITIVITY
            c[s] = c.get(s, 0) + 1
        return c
