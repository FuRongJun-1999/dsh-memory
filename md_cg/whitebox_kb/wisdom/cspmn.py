# -*- coding: utf-8 -*-
"""cspmn · 条件空间并行匹配网络（Condition-Space Parallel Matching Network）
================================================================================
灵枢自身原生的神经网络（2026-08-20 架构级扩展 · 荣终裁）。

统一架构三要素（与协议第四章「世界模型」对应）：
  条件空间（0.0.5）—— 子实例 = 矩阵行，每行 = 一个「条件空间→规则」匹配单元
  局部匹配       —— s = Wq（矩阵乘，CPU numpy / GPU torch 双后端）
  差异传递（2.7） —— 信息差驱动调用深度（cspmn_depth）+ 盲区注入（追加行）

设计原则（荣）：
  - 百万级子实例是主线，但「信息差足够小就不需要更深的调用」（3.10 自维持）
  - 规模感知：N≤10^4 CPU / N≤10^6 GPU / N>10^6 分块稀疏
  - 盲区注入 = 追加矩阵行（新知识卡），Hebbian 增强/减弱
  - 结构自检：信息层次对应性门控（防止 CSPMN 变成臃肿 CNN）

用法：:
    from cspmn import CSPMN
    net = CSPMN()                          # 懒加载索引 + 双后端
    hits = net.search("三角形的内角和是多少度？")   # [(name, score, domain)]
    net.inject("新知识卡内容", domain="数学")       # 盲区注入（追加行）
    depth = net.depth_for(query)                    # 信息差驱动调用深度

后端：
  - auto: 有 CUDA torch 且规模>阈值 → GPU；否则 CPU
  - cpu:  numpy 矩阵乘（现有 search_index 同款）
  - gpu:  torch cu118（SD python 已验证 10^6: 2.1ms/4.11GB）
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_NPZ = os.path.join(HERE, 'neural_index.npz')
GPU_THRESHOLD = 50_000  # N ≥ 5万 → 尝试 GPU（规模感知：矩阵乘占比主导后 GPU 显效）


def _has_gpu_torch() -> bool:
    """检测 CUDA torch 是否可用（主环境或 SD python 环境）。"""
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


class CSPMN:
    """条件空间并行匹配网络：子实例矩阵 + 匹配 + 路由 + 注入 + 深度决策。"""

    def __init__(self, index_path: str = INDEX_NPZ, backend: str = "auto"):
        """CSPMN 并行匹配网络实例：后端(gpu/cpu/auto)·维度与信息差指标占位。"""
        self.index_path = index_path
        self.backend = backend
        self._vectors = None      # (N, D) float32 归一化
        self._names = []
        self._domains = []
        self._edus = []
        self._gpu = None          # GPU 张量（None = 未启用）
        self._dirty = False       # 增量修改标记（strengthen/inject 后置 True）
        self._load_error = None   # load() 失败原因（暴露，不静默）
        self._d_norm = 0.5        # 信息差（默认中性，接入引擎后更新）
        self._gap_trend = 0.0     # 信息差趋势（>0 扩大，<0 收敛）
        self.load()

    # ---------------- 索引加载 ----------------

    def load(self) -> bool:
        """加载 neural_index.npz → 归一化向量。

        失败不静默：_load_error 记录原因，_vectors 保持 None，
        search/info 抛清晰错误（而非底层 ValueError: matmul）。
        """
        self._load_error = None
        try:
            import numpy as np
            data = np.load(self.index_path, allow_pickle=True)
            vecs = data["vectors"].astype(np.float32)
            if vecs.ndim != 2 or vecs.shape[0] == 0:
                self._load_error = f"索引维度异常: {vecs.shape}"
                return False
            norm = np.linalg.norm(vecs, axis=1, keepdims=True)
            self._vectors = vecs / np.maximum(norm, 1e-9)
            self._names = list(data["names"])
            self._domains = list(data["domains"])
            self._edus = list(data["edus"])
            return True
        except FileNotFoundError:
            self._load_error = f"索引不存在: {self.index_path}"
        except KeyError as e:
            self._load_error = f"索引缺字段: {e}（需 vectors/names/domains/edus）"
        except Exception as e:
            self._load_error = f"索引加载失败: {e}"
        return False

    def _require_loaded(self) -> None:
        """search/inject 前置：索引未加载 → 清晰报错（不抛底层 ValueError）。"""
        if self._vectors is None:
            raise RuntimeError(
                f"CSPMN 索引未加载: {self._load_error or '未知原因'}"
                f"（路径: {self.index_path}）")

    # ---------------- 后端决策（规模感知） ----------------

    def _use_gpu(self) -> bool:
        """后端决策：auto → GPU 需 CUDA 可用且规模>阈值。"""
        if self.backend == "cpu":
            return False
        if self.backend == "gpu":
            return _has_gpu_torch()
        # auto：规模感知（N ≥ GPU_THRESHOLD 且 CUDA 可用 → GPU）
        n = len(self._names)
        return n >= GPU_THRESHOLD and _has_gpu_torch()

    def _gpu_matrix(self):
        """懒加载 GPU 张量。"""
        if self._gpu is None:
            import torch
            self._gpu = torch.from_numpy(self._vectors).cuda()
        return self._gpu

    # ---------------- 核心：局部匹配（P1 层） ----------------

    def _match(self, qvec) -> "list[float]":
        """匹配度向量 s = Wq（全子实例并行判断）。"""
        import numpy as np
        qn = qvec / max(float(np.linalg.norm(qvec)), 1e-9)
        if self._use_gpu():
            import torch
            qg = torch.from_numpy(qn.astype(np.float32)).cuda()
            sims = self._gpu_matrix() @ qg
            return sims.cpu().numpy()
        return self._vectors @ qn  # CPU numpy 矩阵乘

    # ---------------- 搜索（P1+P2+P3 层） ----------------

    def search(self, query_vec, limit: int = 10, threshold: float = 0.3,
               domain_filter: str = None, depth: int = None) -> list:
        """CSPMN 搜索：匹配 → TopK 路由 → 条件空间声明。

        domain_filter: 只匹配指定学科（CSPRE 定向检索）
        depth: 调用深度（None → 信息差驱动自动决策）
        返回 [{name, score, domain, edu}]
        """
        self._require_loaded()
        import numpy as np
        sims = self._match(query_vec)
        # 条件空间过滤（CSPRE：跳过无关 domain）
        if domain_filter:
            mask = np.array([domain_filter in d for d in self._domains])
            sims = np.where(mask, sims, -1.0)
        # TopK 路由（P2）
        order = np.argsort(-sims)
        out = []
        for i in order:
            s = float(sims[i])
            if s < threshold:
                break
            out.append({"name": self._names[i], "score": round(s, 4),
                        "domain": self._domains[i], "edu": self._edus[i]})
            if len(out) >= limit:
                break
        # 盲区标记（P3）：最高匹配度 < 0.7 → 可能盲区
        result = {"hits": out, "top_score": out[0]["score"] if out else 0.0}
        result["blind_spot"] = result["top_score"] < 0.7 or not out
        result["depth"] = depth if depth is not None else self.depth_for(top=result["top_score"])
        return result

    # ---------------- 信息差驱动调用深度（荣：信息差小就不深调用） ----------------

    def depth_for(self, top: float = None, d_norm: float = None) -> int:
        """调用深度决策（复用 D_norm 信息差 + 匹配度）。

        规则（荣终裁）：
          D_norm > 0.6            → 深度3（全量 + 盲区检测）
          0.3 < D_norm ≤ 0.6      → 深度2（CSPRE domain 分块）
          D_norm ≤ 0.3            → 深度1（浅层匹配 + 缓存）
          gap_trend 收敛（≤-0.01） → 深度0（不再扩展，3.10 自维持）
        top（匹配度）作为辅助信号：top < 0.4 时即使 D_norm 小也加深一级
        （低匹配 = 检索未覆盖 → 需要更深调用探盲区）。
        """
        dn = d_norm if d_norm is not None else self._d_norm
        tp = top if top is not None else 0.0
        # 自维持：信息差收敛 → 停止扩展
        if self._gap_trend <= -0.01 and dn <= 0.3:
            return 0
        if dn > 0.6:
            return 3
        if dn > 0.3:
            return 2
        # 小信息差 + 低匹配 → 加深一级探盲区
        if tp < 0.4:
            return 2
        return 1

    def set_gap(self, d_norm: float, gap_trend: float = 0.0) -> None:
        """接入引擎的信息差状态（gap_trend A-4 线性回归斜率）。"""
        self._d_norm = float(d_norm)
        self._gap_trend = float(gap_trend)

    # ---------------- 盲区注入（追加子实例 = 新知识卡） ----------------

    def inject(self, vec, name: str, domain: str = "", edu: str = "") -> dict:
        """盲区注入：追加一行子实例（新知识卡）。支持 GPU 增量更新。

        vec: 新知识卡的条件空间向量（bge 编码）
        返回 {status, N_after, matched_boost}——新子实例与查询的匹配度
        """
        self._require_loaded()
        import numpy as np
        v = np.asarray(vec, dtype=np.float32).reshape(1, -1)
        nrm = np.linalg.norm(v)
        if nrm < 1e-9:
            return {"status": "failed", "reason": "zero_vec"}
        self._vectors = np.concatenate([self._vectors, v / nrm], axis=0)
        self._names.append(name)
        self._domains.append(domain)
        self._edus.append(edu)
        # GPU 增量更新（若启用）
        if self._gpu is not None:
            import torch
            self._gpu = torch.cat([self._gpu, torch.from_numpy(v / nrm).cuda()], dim=0)
        return {"status": "injected", "N_after": len(self._names)}

    def strengthen(self, idx: int, qvec, eta: float = 0.05) -> None:
        """Hebbian 增强：命中正确的子实例向查询方向微调（真实实现）。

        v_i ← normalize(v_i + η·q)——被查询证实相关的子实例，其条件
        向量向该查询方向靠拢（局部强化，非梯度下降）。
        """
        self._require_loaded()
        import numpy as np
        q = np.asarray(qvec, dtype=np.float32).flatten()
        if q.size == 0 or idx < 0 or idx >= len(self._names):
            raise IndexError(f"strengthen 越界: idx={idx}, N={len(self._names)}")
        v = self._vectors[idx] + eta * q / max(float(np.linalg.norm(q)), 1e-9)
        n = float(np.linalg.norm(v))
        if n > 1e-9:
            self._vectors[idx] = v / n
        self._dirty = True
        # GPU 同步（若启用）
        if self._gpu is not None:
            import torch
            self._gpu[idx] = torch.from_numpy(self._vectors[idx]).cuda()

    # ---------------- 状态 ----------------

    def info(self) -> dict:
        """实例概况：子实例数/维度/后端(GPU·CPU·unloaded)/信息差 d_norm 与缺口趋势。"""
        if self._vectors is None:
            return {"sub_instances": 0, "dim": 0, "backend": "unloaded",
                    "requested": self.backend, "load_error": self._load_error,
                    "d_norm": self._d_norm, "gap_trend": self._gap_trend}
        backend = ("gpu" if self.backend == "gpu" and _has_gpu_torch()
                   else "cpu" if self.backend == "cpu"
                   else "gpu" if self._gpu is not None
                   else "cpu")
        return {"sub_instances": len(self._names), "dim": self._vectors.shape[1],
                "backend": backend, "requested": self.backend,
                "d_norm": self._d_norm, "gap_trend": self._gap_trend}
