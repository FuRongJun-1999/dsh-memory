# -*- coding: utf-8 -*-
"""csre.py · CSRE 条件空间路由引擎（分形收敛 · 导航递归 × CSPMN 矩阵并行）

原始设计（荣）：「并行子线程多区域寻址」正是 CSPMN 的形态——
  问题 → 并行子线程 × N 个大区域同时打分 → 各区域置信度
       → 最高置信度大区域 → 区域内再分子线程 × M 子区域（并行）
       → 递归收敛至最高置信度区域 → … 直至原子知识

分工（《对照评估》路线 + 校准指令 2026-08-27）：
  层内打分  = CSPMN 条件空间分块矩阵（domain 子矩阵并行乘）
  层间收敛  = 导航递归（composite → 收窄子条件空间 → 下一层）
  负权门控  = 不适用条件负权重（门控第三段——此前未做的真缺口）

白箱声明：查询与索引向量均为**条件空间稀疏向量**（维度=协议规范词，
每一维都是一个中文规范词，匹配过程全程可解释）——零训练、零黑盒嵌入，
bge 遗产 npz 不再作为输入来源（其作者已退役）。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_NPZ = os.path.join(HERE, "csre_lexicon_index.npz")

MAX_DEPTH = 3          # 智能论 3.12 递归深度约束（超出 = structural_blindspot）
NEG_GATE = 1           # 负路由门控阈值：不适用条件命中 ≥ NEG_GATE → REJECT
INDEX_FORMAT = 2       # v2 binds the derived cache to its source and negative conditions
_SOURCE_SQL = ("SELECT id, content, state_attributes FROM nodes "
               "WHERE tags LIKE '%knowledge_point%'")


class Csre:
    """条件空间路由引擎：每层的并行打分（CSPMN 矩阵乘）+ 层间导航递归。"""

    def __init__(self, db_path: str, index_path: str = INDEX_NPZ,
                 max_workers: int | None = None):
        self.db_path = db_path
        self.index_path = index_path
        self.max_workers = max_workers or min(8, (os.cpu_count() or 4))
        self.matrix = None        # [n_units, n_vocab] float32
        self.unit_ids = None
        self.unit_names = None
        self.unit_domains = None
        self.vocab = None
        self.block_cache = {}     # domain → (row_idx 子块, norm 子矩阵)
        self.unit_negatives = None
        self._source_metadata = None
        self._index_status = {"state": "not_loaded"}

    def _source_snapshot(self):
        """Read a fresh source snapshot; never create a missing SQLite database.

        Full row hashes detect same-size edits and WAL commits. This is an O(N)
        correctness check, not a claim of constant-time cache validation.
        MdConn's process cache must not hide edits from this check.
        """
        from md_access import _md_conn_or_none

        _md = _md_conn_or_none()
        if _md is not None:
            from md_access import MdConn
            fresh = MdConn(_md.root, layers=_md._layers)
            rows = fresh.execute(_SOURCE_SQL).fetchall()
            identity = ["md", os.path.normcase(os.path.realpath(_md.root)), list(_md._layers)]
            schema = ["md-access-nodes", 1, list(_md._layers)]
        else:
            path = Path(self.db_path).resolve()
            with contextlib.closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
                rows = conn.execute(_SOURCE_SQL).fetchall()
                schema = conn.execute("PRAGMA table_info(nodes)").fetchall()
            identity = ["sqlite", os.path.normcase(os.path.realpath(path))]

        def fingerprint(value):
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            return hashlib.sha256(text.encode("utf-8")).hexdigest()

        return rows, {"format": INDEX_FORMAT, "algorithm": "csre-condition-vector-v1",
                      "source_id": fingerprint(identity), "source_kind": identity[0],
                      "schema_hash": fingerprint(schema), "rows_hash": fingerprint(rows)}

    def _invalidate(self, state, detail=None):
        self.matrix = self.unit_ids = self.unit_names = self.unit_domains = self.vocab = None
        self.unit_negatives = self._source_metadata = None
        self._unit_norm = None
        self.block_cache.clear()
        self._index_status = {"state": state}
        if detail:
            self._index_status["detail"] = detail
        return False

    def index_info(self) -> dict:
        """Report the last explicit source check; this method does not refresh it."""
        return dict(self._index_status, loaded=self.matrix is not None,
                    units=len(self.unit_ids or []), format=INDEX_FORMAT,
                    freshness_check="full_source_row_hash")

    @staticmethod
    def _negative_conditions(value):
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, (list, tuple)):
            return []
        return list(dict.fromkeys(clean for item in value if isinstance(item, str)
                                  if (clean := item.replace("问", "").strip())))

    # ---------- 索引构建（白箱条件向量） ----------
    def build_index(self) -> dict:
        """从知识库重建词表矩阵索引。

        向量口径（全白箱、可解释）：
          维   = 词条（翻译表规范词 ∪ KCCS 生效条件短语·去停用清洗）
          行   = 每个 knowledge_point 卡
          权重 = 词条在该卡 content + comment 四要素中的出现强度
                 （生效条件命中 1.0 / 名称 1.0 / 正文 0.5——生效条件是
                  when最强信号，正文 what 减半）
        """
        from semantic_translate import ALL_TABLE, _card_bigrams  # noqa: E402
        rows, source_metadata = self._source_snapshot()

        vocab_rows = []
        for nid, _content, sa in rows:
            try:
                obj = json.loads(sa) if isinstance(sa, str) else {}
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            cm = obj.get("comment") or {}
            if not isinstance(cm, dict):
                continue
            for cond in (cm.get("生效条件") or []):
                if isinstance(cond, str):
                    clean = cond.replace("问", "").strip()
                    if len(clean) >= 4:
                        vocab_rows.append(clean)
        vocab = sorted({v for v in vocab_rows if v})
        vocab_pos = {v: i for i, v in enumerate(vocab)}
        units = []
        vec_rows = []
        negatives = []

        from semantic_translate import translate as _noop  # noqa: F401 (确保模块加载)
        for nid, content, sa in rows:
            try:
                obj = json.loads(sa) if isinstance(sa, str) else {}
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            cm = obj.get("comment") or {}
            if not isinstance(cm, dict):
                continue
            body_parts = [
                obj.get("name") or "",
                (content or "")[:200],
                cm.get("name") or "",
                " ".join(cm.get("生效条件") or []),
                " ".join(cm.get("子功能") or []) if isinstance(cm.get("子功能"), str)
                else str(cm.get("子功能") or ""),
                (cm.get("执行") or "") if isinstance(cm.get("执行"), str) else "",
            ]
            body = " ".join(body_parts)
            if not body.strip():
                continue
            vec = np.zeros(len(vocab), dtype=np.float32)
            hit_any = False
            for cond in (cm.get("生效条件") or []):
                cc = cond.replace("问", "").strip() if isinstance(cond, str) else ""
                pos = vocab_pos.get(cc)
                if pos is not None and cc:
                    vec[pos] = max(vec[pos], 1.0)     # 生效条件 = 最强信号
                    hit_any = True
            nm = (obj.get("name") or "")
            pos = vocab_pos.get(nm.replace("问", "").strip())
            if pos is not None and nm.strip():
                vec[pos] = max(vec[pos], 1.0)
                hit_any = True
            if not hit_any:
                # 兜底：正文 bigram 与词表bigram 交集聚合（保持可解释口径）
                bg = set()
                for k in range(len(nm) - 1):
                    bg.add(nm[k:k + 2])
                for vi, vword in enumerate(vocab):
                    vb = {vword[i:i + 2] for i in range(len(vword) - 1)} \
                        if len(vword) > 1 else {vword}
                    if bg & vb:
                        vec[vi] = 0.8
                        hit_any = True
                        break
            units.append((nid, obj.get("name") or "", obj.get("domain") or ""))
            vec_rows.append(vec)
            negatives.append(self._negative_conditions(cm.get("不适用条件")))

        self.matrix = np.vstack(vec_rows) if vec_rows else np.zeros(
            (0, len(vocab)), dtype=np.float32)
        self.unit_ids = [u[0] for u in units]
        self.unit_names = [u[1] for u in units]
        self.unit_domains = [u[2] for u in units]
        self.vocab = vocab
        self.unit_negatives = negatives
        self._source_metadata = source_metadata
        self._index_status = {"state": "ready", "origin": "built"}
        norms = np.linalg.norm(self.matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._unit_norm = self.matrix / norms
        self.block_cache.clear()
        return {"units": len(units), "vocab": len(vocab)}

    def ensure_loaded(self) -> bool:
        """Use only an index matching the current source; reads never rebuild/write.

        Legacy, stale, corrupt and cross-source files return False with a state.
        Existing callers keep the bool API and may fall back to normal retrieval.
        """
        if self.matrix is None and not os.path.isfile(self.index_path):
            return self._invalidate("index_missing")
        try:
            _rows, current = self._source_snapshot()
        except Exception as exc:
            return self._invalidate("source_unavailable", type(exc).__name__)
        if self.matrix is not None and self._source_metadata == current:
            return True
        self._invalidate("not_loaded")
        if not os.path.isfile(self.index_path):
            return self._invalidate("index_missing")
        try:
            with np.load(self.index_path, allow_pickle=False) as data:
                if "metadata" not in data.files:
                    return self._invalidate("legacy_index")
                metadata = json.loads(str(data["metadata"].item()))
                if not isinstance(metadata, dict) or metadata.get("format") != INDEX_FORMAT:
                    return self._invalidate("legacy_index")
                if metadata.get("source_id") != current["source_id"]:
                    return self._invalidate("source_mismatch")
                if metadata != current:
                    return self._invalidate("stale_index")
                matrix = data["vectors"]
                arrays = [data[name] for name in ("unit_ids", "names", "domains", "vectors_vocab")]
                encoded_negatives = data["negative_conditions"]
                if (matrix.ndim != 2 or matrix.dtype.kind not in "fiu" or
                        not np.isfinite(matrix).all() or
                        any(array.ndim != 1 or array.dtype.kind not in "US" for array in arrays) or
                        any(len(array) != matrix.shape[0] for array in arrays[:3]) or
                        len(arrays[3]) != matrix.shape[1] or
                        encoded_negatives.ndim != 1 or len(encoded_negatives) != matrix.shape[0]):
                    return self._invalidate("invalid_index", "array_shape_or_values")
                negatives = [json.loads(str(value)) for value in encoded_negatives]
                if any(not isinstance(value, list) or any(not isinstance(x, str) for x in value)
                       for value in negatives):
                    return self._invalidate("invalid_index", "negative_conditions")
                self.matrix = matrix
                self.unit_ids, self.unit_names, self.unit_domains, self.vocab = [a.tolist() for a in arrays]
                self.unit_negatives = negatives
                self._source_metadata = metadata
                norms = np.linalg.norm(matrix, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                self._unit_norm = matrix / norms
                self._index_status = {"state": "ready", "origin": "loaded"}
                return True
        except Exception as exc:
            return self._invalidate("invalid_index", type(exc).__name__)

    def save_index(self) -> None:
        """Explicitly save a current derived cache, using no pickle/object arrays."""
        if not self.ensure_loaded():
            raise ValueError("cannot save unavailable or stale CSRE index")
        target = Path(self.index_path)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".csre-",
                                             suffix=".npz", delete=False) as handle:
                temporary = handle.name
                np.savez_compressed(handle, vectors=self.matrix,
                                    unit_ids=np.asarray(self.unit_ids, dtype=str),
                                    names=np.asarray(self.unit_names, dtype=str),
                                    domains=np.asarray(self.unit_domains, dtype=str),
                                    vectors_vocab=np.asarray(self.vocab, dtype=str),
                                    negative_conditions=np.asarray([
                                        json.dumps(value, ensure_ascii=False)
                                        for value in self.unit_negatives], dtype=str),
                                    metadata=np.asarray(json.dumps(self._source_metadata, sort_keys=True)))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    # ---------- L0/Ln · 层内并行打分（CSPMN 分块矩阵乘） ----------
    def _qvec(self, question: str, cond_hint: str = "") -> np.ndarray:
        """查询 → 条件空间稀疏向量（复用全局词典）。"""
        q = question + (" " + cond_hint if cond_hint else "")
        qv = np.zeros(len(self.vocab), dtype=np.float32)
        hit_any = False
        qr = question.replace("问", "", 1).strip()
        parts = [question, qr, cond_hint]
        for vi, vw in enumerate(self.vocab):
            vt = vw.strip()
            if not vt:
                continue
            if vt in question or vt in cond_hint:
                qv[vi] = 1.0; hit_any = True
            elif len(qr) >= 4 and qr and vt.startswith(qr[:len(qr)]):
                qv[vi] = 0.9; hit_any = True
        return qv, hit_any

    def rank_domains(self, question: str, cond_hint: str = "",
                     top_k: int = 3) -> list[dict]:
        """L(L)·域级并行打分：所有域子块一次矩阵乘 → 大域置信度排序。

        （『子线程 × N 个大区域同时打分』——numpy/BLAS 行化为并行实现，
         域子块缓存后亦支持独立 GPU 升级路径。）"""
        if top_k <= 0 or not self.ensure_loaded():
            return []
        qv, _ = self._qvec(question, cond_hint)
        qn = np.linalg.norm(qv)
        if qn == 0:
            return []
        sims = self.matrix @ (qv / qn)             # 一次 BLAS 批量乘
        dom_scores: dict[str, list] = {}
        seen_domains = {}
        for idx, dom in enumerate(self.unit_domains):
            seen_domains.setdefault(dom, []).append((idx, float(sims[idx])))
        # 域分 = 该域最强单元分（不是平均——地图式收敛找的是最亮灯塔）
        rank = []
        for dom, pairs in seen_domains.items():
            best_idx, best = max(pairs, key=lambda p: p[1])
            rank.append({"domain": dom, "score": round(best, 4),
                         "best_unit_row": best_idx})
        rank.sort(key=lambda x: -x["score"])
        return rank[:top_k]

    def top_units_in_domain(self, domain: str, question: str,
                            limit: int = 3, neg_terms: list[str] | None = None,
                            neg_gate: int = NEG_GATE) -> list[dict]:
        """L(n+1)·域子块 Top-K 条目（含负权门控——不适用条件互斥补缺口）。"""
        if limit <= 0 or not self.ensure_loaded():
            return []
        out = []
        # 精确路径：同一 domain 的行
        import numpy as np2
        rows = [(i, d) for i, d in enumerate(self.unit_domains) if d == domain]
        qv, _ = self._qvec(question)
        qn = np2.linalg.norm(qv)
        scored = []
        context = "\n".join([question, *self._negative_conditions(neg_terms)])
        for i, _d in rows:
            if neg_gate > 0 and self.negative_hit(
                    {"不适用条件": self.unit_negatives[i]}, context) >= neg_gate:
                continue
            v = self.matrix[i]
            vn = np2.linalg.norm(v)
            if vn == 0 or qn == 0:
                continue
            score = float(np2.dot(v, qv) / (vn * qn))
            scored.append((i, score))
        scored.sort(key=lambda x: -x[1])
        for i, sc in scored[:limit]:
            out.append({"node_id": self.unit_ids[i],
                        "name": self.unit_names[i], "score": round(sc, 4)})
        return out

    # ---------- L · 门控第三段：不适用条件负权 ----------
    @staticmethod
    def negative_hit(kccs_comment: dict, question: str) -> int:
        """Count positive literal mentions, respecting identifiers and local negation.

        This is a bounded lexical rule, not general natural-language inference.
        An independent positive occurrence still counts after a negated mention.
        """
        negs = Csre._negative_conditions(
            kccs_comment.get("不适用条件") if isinstance(kccs_comment, dict) else None)
        hits = 0
        for term in negs:
            left = r"(?<![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", term[0]) else ""
            right = r"(?![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", term[-1]) else ""
            for match in re.finditer(left + re.escape(term) + right, question):
                prefix = question[max(0, match.start() - 32):match.start()]
                if re.search(r"(?:不是|并非|不在|不属于|非)\s*$", prefix):
                    continue
                if re.search(r"(?:\bnot(?:\s+(?:in|on|to))?|\bwithout|\bnon-)\s*$",
                             prefix, flags=re.IGNORECASE):
                    continue
                hits += 1
                break
        return hits


# ---------------- CLI ----------------
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="CSRE 条件空间路由引擎")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--db", default=os.path.join(ROOT := os.path.dirname(
                                                     os.path.dirname(os.path.abspath(__file__))),
                                                 "aeis", "wisdom",
                                                 "wisdom-book-cloud.db"))
    args = ap.parse_args()
    eng = Csre(args.db)
    stats = eng.build_index()
    eng.save_index()
    print(json.dumps(stats, ensure_ascii=False))
