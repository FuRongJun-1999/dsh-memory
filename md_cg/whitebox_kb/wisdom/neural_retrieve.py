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
import logging
import os
import sys

#: 模块级 logger（issue #75 部位②）：降级路径此前是裸 except 静默吞，
#: 调用方无法区分「没有命中」与「神经层整个没跑起来」。凡吞异常处一律
#: 记一条 WARNING，使失败在日志面可见。
logger = logging.getLogger(__name__)

#: 结构化失败记录的保留上限（口径）：只留**最近** FAILURE_LIMIT 条，最旧先丢，
#: 淘汰条数记入实例的 _failures_dropped。为什么设上限：失败集中在降级路径上，
#: 长驻 serve 进程里「模型不可用」会让每次 embed/search 都失败，无界累积会把
#: 内存与日志面拖垮；50 条足够覆盖一次故障排查窗口，且不隐瞒「还有更多」。
FAILURE_LIMIT = 50

#: 单条 message 的截断长度：异常消息可能内嵌整段响应体/路径串，
#: 留 300 字符足够定位，又不至于把一条记录撑成小作文。
FAILURE_MESSAGE_LIMIT = 300

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
        # 生效条件：os.path.isdir/os.path.exists 抛异常（权限、路径异常等）时记一条 warning 并继续探测下一个候选——本函数是**模块级**、无实例可用，故只落日志不留实例记录（实例面记录见 _record_failure）。
        except Exception as e:
            logger.warning("[neural_retrieve] bge 路径探测吞异常(p=%s) exc=%s: %s",
                           p, type(e).__name__, e)
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
            # #75 部位②：结构化失败留痕（口径见 _record_failure 与 FAILURE_LIMIT）
            inst._failures = []
            inst._last_failure = None
            inst._failures_dropped = 0
            cls._singleton = inst
        return cls._singleton

    def __init__(self, model_path=MODEL_PATH):
        """神经检索器懒加载容器：模型与向量缓存置空待首访触发。"""
        # __new__ 已初始化；__init__ 幂等（不覆盖已有模型）
        pass

    # 生效条件：self 为 NeuralRetriever 实例；恒不抛；_failures/_last_failure/_failures_dropped 任一缺失时按空值补齐（兼容本次改动之前构造、仍存活于进程内的老单例实例）。
    def _ensure_failure_state(self):
        """结构化留痕字段的惰性补齐（单例跨改动存活时的兼容），恒不抛。"""
        if not hasattr(self, "_failures"):
            self._failures = []
        if not hasattr(self, "_last_failure"):
            self._last_failure = None
        if not hasattr(self, "_failures_dropped"):
            self._failures_dropped = 0

    # 生效条件：stage 为非空字符串、exc 为 BaseException 实例；恒不抛、恒返回本次记录 dict（stage/exc_type/message 三键齐备，message 超 FAILURE_MESSAGE_LIMIT 即截断加省略号）；写入 self._failures 尾部并按 FAILURE_LIMIT 淘汰最旧、淘汰数累加 self._failures_dropped、self._last_failure 指向本次记录，同时以模块 logger 记一条 warning。
    def _record_failure(self, stage, exc):
        """结构化失败留痕（issue #75 部位②）。

        为什么要有：本模块刻意降级（D-005：不可用返回空）——**降级本身是契约**，
        但**静默**降级让调用方无法区分「没有命中」与「神经层整个没跑起来」。
        记 {stage, exc_type, message} 后，调用方经 failures() 可读、可诊断；
        stage 取吞异常处的能力名（ensure_model / embed / load_index /
        cspmn_backend / search_index / cosine），一眼看出坏在哪一段。

        上限口径见模块级 FAILURE_LIMIT 与 FAILURE_MESSAGE_LIMIT 的注释。
        """
        self._ensure_failure_state()
        msg = str(exc)
        if len(msg) > FAILURE_MESSAGE_LIMIT:
            msg = msg[:FAILURE_MESSAGE_LIMIT] + "…"
        rec = {"stage": stage, "exc_type": type(exc).__name__, "message": msg}
        self._failures.append(rec)
        if len(self._failures) > FAILURE_LIMIT:
            del self._failures[:len(self._failures) - FAILURE_LIMIT]
            self._failures_dropped += 1
        self._last_failure = rec
        logger.warning("[neural_retrieve] 降级 stage=%s exc=%s: %s",
                       stage, rec["exc_type"], msg)
        return rec

    # 生效条件：stage 为非空字符串、exc 为 BaseException 实例、degrade_value 为任意值；恒先经 _record_failure 留痕，随后**原样返回 degrade_value 且绝不抛**——本方法是 D-005 降级契约的唯一出口，任何改动若让它抛异常即破坏对外契约。
    def _degrade(self, stage, exc, degrade_value):
        """降级唯一出口：留痕 + 返回契约值（**绝不抛**）。"""
        self._record_failure(stage, exc)
        return degrade_value

    def failures(self):
        """已吞掉的异常清单（结构化，最旧→最新）——返回**副本**，调用方改动不影响内部状态。"""
        self._ensure_failure_state()
        return [dict(r) for r in self._failures]

    def last_failure(self):
        """最近一次被吞掉的异常记录（无则 None）——返回**副本**。"""
        self._ensure_failure_state()
        return dict(self._last_failure) if self._last_failure else None

    def failures_dropped(self):
        """因超出 FAILURE_LIMIT 而被淘汰的记录条数（>0 表示还有更早的失败未保留）。"""
        self._ensure_failure_state()
        return self._failures_dropped

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
        # 生效条件：sentence_transformers 导入失败，或 SentenceTransformer(model_path) 构造抛异常；仍置 _fail_reason 并返回 False（降级契约不变），另经 _record_failure 落一条 stage=ensure_model 的结构化记录。
        except Exception as e:
            self._fail_reason = str(e)
            self._record_failure("ensure_model", e)
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
        # 生效条件：self._model.encode(key) 抛异常（模型句柄损坏、显存/内存不足等）；仍返回 None（降级契约不变），另落一条 stage=embed 的结构化记录。
        except Exception as e:
            return self._degrade("embed", e, None)

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
        # 生效条件：numpy 导入或 np.load / 归一化计算抛异常（索引文件缺失、损坏、维度不符等）；仍置 _index=None 并返回 False（降级契约不变），另落一条 stage=load_index 的结构化记录。
        except Exception as e:
            self._index = None
            return self._degrade("load_index", e, False)

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
            # 生效条件：cspmn 导入失败，或其后端 CSPMN(...)/net.search(...) 抛异常；记录「为何回退」（stage=cspmn_backend，含异常类型与消息）后**继续走下面的 numpy 实现**——回退行为本身一字不改（结果与 CPU 逐位一致），只是不再裸 pass。
            except Exception as e:
                self._record_failure("cspmn_backend", e)
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
        # 生效条件：search_index 的 numpy 兜底路径抛异常（索引字典缺键、维度不符、内存不足等）；仍返回 []（D-005 降级契约不变——**不得改成抛异常**），另落一条 stage=search_index 的结构化记录。
        except Exception as e:
            return self._degrade("search_index", e, [])

    def index_info(self):
        """索引状态。"""
        if self._index is None:
            return {"loaded": False}
        return {"loaded": True, "cards": len(self._index["names"]),
                "dim": self._index["vectors"].shape[1]}

    # 生效条件：a/b 为可做 np.linalg.norm 与 @ 的向量对象；**保持 staticmethod 签名 (a, b) 不变**——本方法不在 search_index 调用链上（其调用点是 retrieve），为记一条日志而改签名属无收益的契约变更，故异常时只落模块级日志、不进实例结构化记录；恒返回 float。
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
        # 生效条件：np.linalg.norm 或点积抛异常（维度不符、空向量、非数值 dtype 等）；仍返回 0.0（降级契约不变）。因本方法为 staticmethod（无实例），此处**只落模块日志**，不进实例结构化记录（_cosine 不在 search_index 调用链上，理由见上）。
        except Exception as e:
            logger.warning("[neural_retrieve] 降级 stage=cosine exc=%s: %s",
                           type(e).__name__, e)
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
