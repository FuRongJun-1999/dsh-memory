# -*- coding: utf-8 -*-
"""md_cg · 记忆操作系统扩展（MdCGOS）

在 MdCG（P0/P1 已验证引擎）之上补齐「记忆操作系统」的七项能力
（对标 deja-vu / dsh-noema 的工程实践）：

  1. Fix pairs 自动挖掘    行为日志（错误→修复）→ rejected/ 负记忆 + knowledge/ 修复知识
  2. role 分层索引         工具输出/命令/编辑 单独索引，默认不参与正排（不稀释召回）
  3. RRF 并行多路召回      词法 / 条件桶 / 图扩展 / 实体 四路并行 → Reciprocal Rank Fusion
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
                   GLOBAL_CAP)
from . import nodefile, routing
from .fsutil import FileLock, atomic_write, append_jsonl, read_jsonl

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
            if e.get("layer") in ("rejected", "unresolved"):
                continue  # 负记忆走覆盖标记，不进正排
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
        """实体路径：tags 命中。"""
        terms = expand_query_terms(query)
        out = []
        for e in entries:
            tags = [str(t) for t in (e.get("tags") or [])]
            if any(t in query or query in t for t in tags if len(t) >= 2):
                out.append((e, 1.0))
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
                    out.append((by_id[tid], s * 0.5))
        return out

    def search_rrf(self, query: str, k: int = 20, layer: str = None,
                   context=None, roles=None, include_work: bool = False,
                   judge: bool = True, paths=("lexical", "bucket", "entity", "graph"),
                   record: bool = True):
        """并行多路召回 + RRF 融合。返回 (results, meta)。

        每路各自排序 → Reciprocal Rank Fusion：
            score(d) = Σ_path 1 / (RRF_K + rank_path(d))
        多路共同确认的记忆排在单路命中之前（对齐 noema 的 Fusion Recall）。
        meta 含 per_path（各路的候选数与来源），可审计。
        """
        q = (query or "").strip()
        if not q:
            return [], {"tier": None, "reason": "empty_query", "paths": {}}
        entries = self._candidates(layer=layer, roles=roles, include_work=include_work)
        if not entries:
            return [], {"tier": None, "reason": "no_candidates", "paths": {}}

        stat = {"scanned": 0}
        ranked = {}          # path -> [(node, score)]
        if "lexical" in paths:
            ranked["lexical"] = self._lexical(q, entries, stat)
        if "bucket" in paths:
            ranked["bucket"] = self._path_bucket(q, entries, context)
        if "entity" in paths:
            ranked["entity"] = self._path_entity(q, entries)
        if "graph" in paths:
            ranked["graph"] = self._path_graph(q, entries, ranked.get("lexical") or [])

        # 排序 + RRF 融合
        rrf, prov = {}, {}
        per_path = {}
        for name, scored in ranked.items():
            scored = sorted(scored, key=lambda x: (-x[1],
                            -float(x[0]["frontmatter"].get("importance") or 0)))
            per_path[name] = len(scored)
            for rank, (node, _s) in enumerate(scored[:50], 1):
                nid = node["id"]
                rrf[nid] = rrf.get(nid, 0.0) + 1.0 / (RRF_K + rank)
                prov.setdefault(nid, []).append({"path": name, "rank": rank})

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
                         "provenance": prov}

    # ================= 7. budget-driven pack =================

    def recall(self, query: str, budget_tokens: int = DEFAULT_BUDGET, k: int = 20,
               layer: str = None, context=None, roles=None,
               include_work: bool = False, judge: bool = True, use_rrf: bool = True):
        """按 token 预算装包：装到预算花完为止；**超大条目跳过而非停下**。

        返回 {pack: [...], tokens_used, budget, skipped: [...], meta}
        """
        if use_rrf:
            results, meta = self.search_rrf(query, k=k, layer=layer, context=context,
                                            roles=roles, include_work=include_work,
                                            judge=judge)
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
        return {"pack": pack, "tokens_used": used, "budget": budget_tokens,
                "skipped": skipped, "meta": meta}

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
                tags=None, condition_space=None, **kw):
        """把一个候选记忆放入海马体 inbox，等待审核（不直接持久化）。"""
        pid = "prop_" + _sig(node_id + str(time.time()))
        rec = {"t": time.time(), "pid": pid, "id": node_id, "content": content,
               "layer": layer, "tags": list(tags or []),
               "condition_space": condition_space or {}, "extra": kw,
               "actor": self.actor}
        append_jsonl(self.inbox_log, rec)
        self._audit("propose", node_id, pid=pid, layer=layer,
                    payload_hash=_sig(content))
        return pid

    def _decided_pids(self):
        return {r.get("pid") for r in read_jsonl(self.decisions_log) if r.get("pid")}

    def review_list(self):
        """待审核候选（未被 decisions 覆盖的 inbox 条目）。"""
        done = self._decided_pids()
        return [r for r in read_jsonl(self.inbox_log) if r.get("pid") not in done]

    def review_decide(self, pid: str, decision: str, edits: dict = None,
                      merge_into: str = None, reason: str = ""):
        """审核裁决：accept / reject / edit / merge。

        accept  → 按 inbox 原样写入
        reject  → 丢弃（只记裁决，不落节点）
        edit    → 用 edits 覆盖 content/tags/layer 后写入
        merge   → 合并进已有节点 merge_into（内容追加 + 不适用条件并集）
        """
        if decision not in ("accept", "reject", "edit", "merge"):
            raise ValueError(f"未知裁决：{decision}")
        item = next((r for r in read_jsonl(self.inbox_log)
                     if r.get("pid") == pid), None)
        if not item:
            return {"ok": False, "error": "pid_not_found"}
        if pid in self._decided_pids():
            return {"ok": False, "error": "already_decided"}

        result = {"pid": pid, "decision": decision}
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
            nid = self.add(item["id"], content, layer=layer, tags=tags,
                           condition_space=item.get("condition_space"),
                           **item.get("extra", {}))
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

        append_jsonl(self.decisions_log, {"t": time.time(), "pid": pid,
                                          "decision": decision,
                                          "reason": reason,
                                          "actor": self.actor,
                                          "result": {k: v for k, v in result.items()
                                                     if k in ("ok", "node_id", "error")}})
        self._audit("review_decide", item.get("id", ""), pid=pid, decision=decision)
        return result

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
            "tombstones": len(list(read_jsonl(self.deletions_log))),
            "audit_events": len(list(read_jsonl(self.audit_log))),
            "reflections": len(self.last_d_records()),
        }
        return h

    def _role_counts(self):
        c = {}
        for e in self.index["nodes"].values():
            r = e.get("role") or "(none)"
            c[r] = c.get(r, 0) + 1
        return c
