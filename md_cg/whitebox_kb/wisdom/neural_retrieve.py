# -*- coding: utf-8 -*-
"""智慧之书 · 神经嵌入检索层（L3 语义轴 · bge-small-zh-v1.5）。

对齐灵枢语义空间三层架构的 L3 神经轴：查询与知识卡内容投影到
bge 嵌入空间，余弦相似度排序——「水烧开了→沸腾」「肚子咕咕叫→饿」
这类词面差异大的真正语义关联，翻译表/部首层都做不到，嵌入可以。

用法：
  from neural_retrieve import NeuralRetriever
  nr = NeuralRetriever()                # 懒加载 bge 模型
  hits = nr.retrieve(dex, "水烧开了")   # [(name, score, content_preview)]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# v1.22 可移植性修复（2026-08-20 · 外部测试报告 P0-2）：
# 原硬编码作者本机模型路径 → 换机器即失效（模型不可用 → 神经层整体降级）。
# 改为环境变量 AEIS_BGE_PATH 优先，再按候选路径自动探测（仓库内 models/
# 相对路径 + 随包目录），最后才落到作者本机路径。
_AEIS_BGE_DEFAULT = os.environ.get(
    'AEIS_BGE_PATH',
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'models', 'bge-small-zh-v1.5'))
def _probe_bge_path():
    """探测 bge 模型目录：环境变量（显式指定即用，不探测）>
    仓库相对 > 随包相对 > 本机默认。"""
    env_p = os.environ.get('AEIS_BGE_PATH', '').strip()
    if env_p:
        return env_p  # 用户显式指定 → 用用户的（可移植性契约）
    cands = [
        _AEIS_BGE_DEFAULT,
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'models', 'bge-small-zh-v1.5'),
        os.path.join(HERE, 'models', 'bge-small-zh-v1.5'),
    ]
    for p in cands:
        try:
            if os.path.isdir(p) and os.path.exists(
                    os.path.join(p, 'config.json')):
                return p
        except Exception:
            continue
    return _AEIS_BGE_DEFAULT
MODEL_PATH = _probe_bge_path()
INDEX_NPZ = os.path.join(HERE, 'neural_index.npz')
INDEX_META = os.path.join(HERE, 'neural_index.json')


class NeuralRetriever:
    """bge-small-zh 神经嵌入检索（懒加载，D-005 降级：不可用返回空）。

    索引模式（推荐）：build_neural_index.py 预计算全库向量 → npz，
    查询时只编码查询向量，numpy 向量化全库余弦（毫秒级）。
    """

    _singleton = None
    _embed_cache = {}  # 内容哈希 → 向量（避免重复编码）

    def __new__(cls, model_path=MODEL_PATH):
        """单例：模型只加载一次（进程内缓存）。"""
        if cls._singleton is None:
            inst = super().__new__(cls)
            inst.model_path = model_path
            inst._model = None
            inst._fail_reason = None
            inst._index = None      # 加载的索引 {"vectors","names",...}
            cls._singleton = inst
        return cls._singleton

    def __init__(self, model_path=MODEL_PATH):
        """神经检索器懒加载容器：模型与向量缓存置空待首访触发。"""
        # __new__ 已初始化；__init__ 幂等（不覆盖已有模型）
        pass

    def _ensure_model(self):
        """确保 bge 模型可用：首访触发加载，失败记录原因并走词面降级。"""
        if self._model is not None:
            return True
        if self._fail_reason:
            return False
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_path)
            return True
        except Exception as e:
            self._fail_reason = str(e)
            return False

    def embed(self, text):
        """文本 → 嵌入向量（不可用时返回 None；同内容走缓存）。"""
        if not self._ensure_model() or not text:
            return None
        key = text[:600]  # 内容缓存键（截断对齐检索用法）
        if key in self._embed_cache:
            return self._embed_cache[key]
        try:
            v = self._model.encode(key)
            self._embed_cache[key] = v
            return v
        except Exception:
            return None

    # ---- 索引模式（预计算全库向量） ----

    def load_index(self, npz_path=INDEX_NPZ, meta_path=INDEX_META):
        """加载预计算索引。返回 True/False。"""
        try:
            import numpy as np
            data = np.load(npz_path, allow_pickle=True)
            self._index = {
                "vectors": data["vectors"],  # (N, dim)
                "names": list(data["names"]),
                "domains": list(data["domains"]),
                "edus": list(data["edus"]),
            }
            self._index["norm"] = np.linalg.norm(self._index["vectors"],
                                                 axis=1, keepdims=True)
            self._index["vectors_normed"] = self._index["vectors"] / np.maximum(
                self._index["norm"], 1e-9)
            return True
        except Exception:
            self._index = None
            return False

    def search_index(self, query, limit=10, threshold=0.3):
        """索引检索：查询编码一次 → numpy 全库余弦 → 排序。

        返回 [(name, score, domain, edu)]（score 为余弦相似度）。
        CSPMN 接入（v1.18 · 2026-08-20）：规模>阈值且 CUDA 可用时，
        矩阵乘走 GPU（cspmn 后端），结果与 CPU 逐位一致。
        """
        if self._index is None:
            if not self.load_index():
                return []
        qv = self.embed(query)
        if qv is None:
            return []
        try:
            import numpy as np
            # CSPMN 后端：规模感知 GPU 加速（荣：百万级子实例主线）
            try:
                from cspmn import CSPMN, GPU_THRESHOLD
                n = len(self._index["names"])
                if n > GPU_THRESHOLD:
                    net = CSPMN(backend="auto")
                    r = net.search(qv, limit=limit, threshold=threshold)
                    return [(h["name"], h["score"], h["domain"], h["edu"])
                            for h in r["hits"]]
            except Exception:
                pass  # CSPMN 不可用 → 回退 numpy（现有实现）
            qn = qv / max(float(np.linalg.norm(qv)), 1e-9)
            sims = self._index["vectors_normed"] @ qn  # (N,)
            order = np.argsort(-sims)
            out = []
            for i in order:
                s = float(sims[i])
                if s < threshold:
                    break  # 已排序，后续更低
                out.append((self._index["names"][i], round(s, 3),
                            self._index["domains"][i],
                            self._index["edus"][i]))
                if len(out) >= limit:
                    break
            return out
        except Exception:
            return []

    def index_info(self):
        """索引状态。"""
        if self._index is None:
            return {"loaded": False}
        return {"loaded": True, "cards": len(self._index["names"]),
                "dim": self._index["vectors"].shape[1]}

    @staticmethod
    def _cosine(a, b):
        """余弦相似度：已归一化向量直接点积。"""
        try:
            import numpy as np
            na = float(np.linalg.norm(a))
            nb = float(np.linalg.norm(b))
            if na == 0 or nb == 0:
                return 0.0
            return float(a @ b / (na * nb))
        except Exception:
            return 0.0

    def retrieve(self, dex, query, limit=10, threshold=0.35):
        """全库神经嵌入检索：查询 vs 知识卡内容余弦，返回 [(name, score, preview)]。

        threshold：嵌入余弦阈值（bge 对语义相关通常 >0.4；0.35 宽松召回）。
        """
        qv = self.embed(query)
        if qv is None:
            return []
        from aeis_core import MemoryLayer
        scored = []
        for n in dex.store.query_nodes(layer=MemoryLayer.KNOWLEDGE, limit=500):
            sa = n.state_attributes
            if not sa.get('name'):
                continue
            text = (n.content or '')[:600]  # 内容截断，嵌入成本可控
            if not text:
                continue
            nv = self.embed(text)
            if nv is None:
                continue
            sim = self._cosine(qv, nv)
            if sim >= threshold:
                scored.append((sa.get('name'), round(sim, 3),
                               text[:80], sa.get('domain')))
        scored.sort(key=lambda x: -x[1])
        return scored[:limit]

    def available(self):
        """探针：bge 模型是否就绪（懒加载成功即 True）。"""
        return self._ensure_model()

    def fail_reason(self):
        """加载失败原因回读（available=False 时用于诊断降级原因）。"""
        self._ensure_model()
        return self._fail_reason
