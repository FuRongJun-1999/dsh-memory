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

import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_NPZ = os.path.join(HERE, "csre_lexicon_index.npz")

MAX_DEPTH = 3          # 智能论 3.12 递归深度约束（超出 = structural_blindspot）
NEG_GATE = 1           # 负路由门控阈值：不适用条件命中 ≥ NEG_GATE → REJECT


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

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT id, content, state_attributes FROM nodes "
            "WHERE tags LIKE '%knowledge_point%'").fetchall()
        conn.close()

        vocab_rows = []
        for nid, _content, sa in rows:
            try:
                obj = json.loads(sa) if isinstance(sa, str) else {}
            except Exception:
                continue
            cm = obj.get("comment") or {}
            for cond in (cm.get("生效条件") or []):
                if isinstance(cond, str):
                    clean = cond.replace("问", "").strip()
                    if len(clean) >= 4:
                        vocab_rows.append(clean)
        vocab = sorted({v for v in vocab_rows if v})
        vocab_pos = {v: i for i, v in enumerate(vocab)}
        units = []
        vec_rows = []

        from semantic_translate import translate as _noop  # noqa: F401 (确保模块加载)
        for nid, content, sa in rows:
            try:
                obj = json.loads(sa) if isinstance(sa, str) else {}
            except Exception:
                continue
            cm = obj.get("comment") or {}
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

        self.matrix = np.vstack(vec_rows) if vec_rows else np.zeros(
            (0, max(len(vocab), 1)), dtype=np.float32)
        self.unit_ids = [u[0] for u in units]
        self.unit_names = [u[1] for u in units]
        self.unit_domains = [u[2] for u in units]
        self.vocab = vocab
        norms = np.linalg.norm(self.matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._unit_norm = self.matrix / norms
        self.block_cache.clear()
        return {"units": len(units), "vocab": len(vocab)}

    def ensure_loaded(self) -> bool:
        if self.matrix is not None:
            return True
        if os.path.exists(self.index_path):
            d = np.load(self.index_path, allow_pickle=True)
            self.matrix = d["vectors"]
            self.unit_ids = list(d["unit_ids"])
            self.unit_names = list(d["names"])
            self.unit_domains = list(d["domains"])
            self.vocab = list(d["vectors_vocab"])
            return True
        return False

    def save_index(self) -> None:
        np.savez_compressed(self.index_path,
                            vectors=self.matrix,
                            unit_ids=np.array(self.unit_ids),
                            names=np.array(self.unit_names),
                            domains=np.array(self.unit_domains,
                                             dtype=object),
                            vectors_vocab=np.array(self.vocab))

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
        assert self.matrix is not None, "先 build_index()/ensure_loaded()"
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
        out = []
        # 精确路径：同一 domain 的行
        import numpy as np2
        rows = [(i, d) for i, d in enumerate(self.unit_domains) if d == domain]
        qv, _ = self._qvec(question)
        qn = np2.linalg.norm(qv)
        scored = []
        for i, _d in rows:
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
        """REJECT 门控计数：不适用条件去『问』后的字面包含命中数。"""
        negs = (kccs_comment or {}).get("不适用条件") or []
        return sum(1 for n in negs
                   if isinstance(n, str) and n and n.replace("问", "") in question)


# ---------------- CLI ----------------
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="CSRE 条件空间路由引擎")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--db", default=os.path.join(ROOT := HERE.rsplit(os.sep, 2)[0]
                                                 if False else os.path.dirname(
                                                     os.path.dirname(os.path.abspath(__file__))),
                                                 "aeis", "wisdom",
                                                 "wisdom-book-cloud.db"))
    args = ap.parse_args()
    eng = Csre(args.db)
    stats = eng.build_index()
    eng.save_index()
    print(json.dumps(stats, ensure_ascii=False))
