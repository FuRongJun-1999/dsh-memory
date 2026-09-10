# -*- coding: utf-8 -*-
"""
aeis.api · 灵枢高层接口 — 面向其他智能体的接入点
=================================================
Agent 类封装 SpacetimeMemoryEngine（v1.11），提供分组化的简洁方法面。
协议语义（智能论 v3.2）：五层记忆 · 信息差 D_norm · 信任值 T_total ·
条件空间 · 盲区 · 生命周期七相 · 知识飞轮。

设计约束：
- 零外部依赖（D-005）：全部基于核心引擎与标准库。
- 薄封装：所有方法直接委托核心引擎，不复制逻辑。
- AI 友好：每个方法含类型标注与协议语义说明。
"""

from typing import Dict, List, Optional, Tuple

from .core import (
    SpacetimeMemoryEngine, ConditionSpace, EdgeType, MemoryLayer,
    STNode, STEdge,
)


class Agent:
    """灵枢智能体 — 其他 AI 的协议接入点。

    用法::

        import aeis
        agent = aeis.Agent(identity="助手", db_path="memory.db")
        agent.remember("用户偏好简洁回答", tags=["preference"])
        hits = agent.recall("偏好")
        agent.distill()          # 知识飞轮：经验 → 可复用模式
        agent.calibrate()        # 宇宙校准参照（方向性检查）
        agent.close()
    """

    def __init__(self, identity: str = "智能体",
                 db_path: str = ":memory:",
                 role: str = "primary",
                 data_dir: Optional[str] = None):
        self.identity = identity
        from .core import Role
        role_enum = Role.PRIMARY if role in ("primary", "PRIMARY") else Role.SECONDARY
        self.engine = SpacetimeMemoryEngine(db_path=db_path, identity=identity,
                                            role=role_enum)
        self._data_dir = data_dir

    # =====================================================================
    # 记忆层（五层记忆 · 3.2 节）
    # =====================================================================

    def remember(self, content: str, importance: float = 0.5,
                 tags: Optional[List[str]] = None,
                 entities: Optional[List[str]] = None,
                 modality: str = "text",
                 condition_space: Optional[ConditionSpace] = None):
        """写入一条感知记忆（自动进入知识层）。

        - content: 记忆内容（中文语义优先）
        - importance: 重要性 [0,1]（近因/重要性参与召回加权）
        - tags: 标签（如 learning_result / preference / anchor 语义标记）
        - entities: 实体名列表（挂接实体注册表）
        - modality: text / image / code 等
        - 自动去重（中文二元组 Jaccard ≥ 动态阈值 → 提升原节点权重）
        """
        return self.engine.add_perception(
            content, modality=modality, importance=importance,
            tags=list(tags or []), entities=list(entities or []) or None,
            condition_space=condition_space)

    def prefeed(self, content: str, source: str = "input",
                tags: Optional[List[str]] = None,
                entities: Optional[List[str]] = None) -> Dict:
        """H1 海马体前馈：新奇检测 → 高新奇输入当场强化编码
        （标记 novel_prefeed + importance 提升 + 与相关知识建边）。
        外部输入到达时调用——「看到新东西眼睛一亮，主动记住」。"""
        return self.engine.prefeed_input(content, source,
                                         list(tags or []), entities)

    def pattern_separation(self, limit: int = 150) -> Dict:
        """H3 海马体模式分离：扫描相似节点对 → 建立分离边（条件差异显式化）。
        检索时命中相似节点会附「区别」提示——细化条件得到精确知识。"""
        return self.engine.pattern_separation_scan(limit=limit)

    def reconstruct_scene(self, clue: str, depth: int = 2,
                          max_nodes: int = 8) -> Dict:
        """H4 海马体情景重构：线索 → 条件空间下的信息复原。
        从部分片段重建完整记忆场景；输出标注「重构非回放」。"""
        return self.engine.reconstruct_scene(clue, depth=depth,
                                             max_nodes=max_nodes)

    def recall(self, query: str, limit: int = 10) -> List[Tuple]:
        """组合联想召回（内容相似 0.5 + 重要性 0.3 + 近因 0.2）。
        返回 [(STNode, score)]。"""
        return self.engine.recall(query, limit=limit)

    def recall_plot(self, limit: int = 6) -> List:
        """剧情节点优先召回（v1.26 · 外部测试 v3-P2 建议）。

        按 tags 含 plot 的节点，importance 降序取前 limit 条——
        剧情连续性优先于普通语义召回（长对话里角色得记得
        「上次发生了什么事」，不能只靠当前问题的相似度）。
        返回 [STNode, ...]。
        """
        try:
            return self.engine.store.get_nodes_by_tag("plot", limit=limit)
        except Exception:
            return []

    def search(self, query: str, limit: int = 20) -> List[Tuple]:
        """内容检索（LIKE 预筛 + 中文二元组 Jaccard 排序）。
        返回 [(STNode, score)]；触发复用追踪（飞轮度量输入）。"""
        return self.engine.search_content(query, limit=limit)

    def timeline(self, limit: int = 50) -> List[Dict]:
        """时间线（按时间倒序的记忆快照）。"""
        return self.engine.get_timeline(limit=limit)

    def what_happened(self, since: float, until: Optional[float] = None) -> List:
        """时间窗口内发生了什么（时态查询）。"""
        return self.engine.what_happened_at(since, until)

    def anchors(self) -> List:
        """锚点层记忆（不可遗忘的结构记忆，如协议副本）。"""
        return self.engine.get_anchors()

    # =====================================================================
    # 关系与推理（图结构 · 条件空间）
    # =====================================================================

    def relate(self, source_id: str, target_id: str,
               relation: str = "causal",
               confidence: float = 0.5,
               source_evidence: str = "extracted"):
        """在两个节点间建立关系边。

        - relation: causal / similar / sequential / spatial / hierarchical
        - source_evidence: extracted（观察）/ inferred（推导）/ ambiguous
        - 边默认未验证（待验证单元复核）
        """
        et = getattr(EdgeType, relation.upper(), EdgeType.CAUSAL)
        return self.engine.add_edge(source_id, target_id, relation_type=et,
                                    confidence=confidence,
                                    source_evidence=source_evidence)

    # ---- 条件节点化（GPT 审查·第二优先级 v1.16）----
    # 条件从「节点属性」提升为「可学习的认知对象」：条件节点 → applies_to → 知识节点

    def declare_condition(self, content: str, existence_constraint: str = "",
                          importance: float = 0.8) -> STNode:
        """声明条件节点：条件成为独立认知对象（可发现/组合/验证/继承）。
        content 例：「气压低」「海拔高」「温度>100°C」；存在约束写入条件空间。"""
        from aeis_core import ConditionSpace
        cs = ConditionSpace(
            observation_position="条件空间",
            observation_tool="条件声明",
            time_window=(0.0, 0.0),
            existence_constraint=existence_constraint or content)
        return self.engine.add_perception(
            f"[条件] {content}", importance=importance,
            tags=["condition", "condition_verified"],
            condition_space=cs)

    def promote_condition(self, candidate_id: str) -> Optional[STNode]:
        """条件候选提升：预测误差自动条件化产出的 condition_candidate
        → 验证通过 → 正式条件节点（condition_verified）。"""
        n = self.engine.store.get_node(candidate_id)
        if not n:
            return None
        try:
            self.engine.store.tag_node(candidate_id, "condition")
            self.engine.store.tag_node(candidate_id, "condition_verified")
        except Exception:
            pass
        return self.engine.store.get_node(candidate_id)

    def apply_condition(self, condition_id: str, knowledge_id: str,
                        confidence: float = 0.8) -> STEdge:
        """条件→知识 适用关系（applies_to 边）：条件节点路由到适用知识"""
        return self.engine.add_edge(condition_id, knowledge_id,
                                    relation_type=EdgeType.APPLIES_TO,
                                    confidence=confidence,
                                    source_evidence="inferred")

    def conditions(self) -> List:
        """列出全部条件节点（可检索条件空间）"""
        try:
            return self.engine.store.get_nodes_by_tag("condition", limit=100)
        except Exception:
            return []

    # ---- 条件代数工程化（荣确认·影响雅可比图 v1.16）----
    # 语义时空图 → 影响雅可比 J：causal/sequential 边 = ∂y/∂x（离散化）
    # 条件链传播 = 雅可比幂（链式法则 dz/dx = dz/dy·dy/dx）

    def influence_jacobian(self, max_nodes: int = 50) -> Tuple:
        """语义时空图 → 影响雅可比矩阵 J（因果/时序边 = 影响雅可比结构）
        返回 (J, node_ids)：J[j][i] = ∂node_j/∂node_i（i 影响 j 的强度=边置信）"""
        try:
            import numpy as np
        except Exception:
            return None, []
        nodes = self.engine.store.query_nodes(limit=max_nodes)
        ids = [n.id for n in nodes]
        idx = {nid: i for i, nid in enumerate(ids)}
        J = np.zeros((len(ids), len(ids)), dtype=np.float32)
        for i, n in enumerate(nodes):
            try:
                for e in self.engine.store.get_outgoing_edges(n.id):
                    if e.relation_type.value in ("causal", "sequential") \
                            and e.target_id in idx:
                        J[idx[e.target_id], i] = e.confidence
            except Exception:
                pass
        return J, ids

    def jacobian_chain(self, start_id: str, target_id: str,
                       steps: int = 2) -> float:
        """雅可比链式传播：J^steps[target][start] = 条件链组合（链式法则）
        例：A→B(0.9)→C(0.85)，jacobian_chain(A,C,2) = 0.9×0.85 = 0.765"""
        try:
            import numpy as np
        except Exception:
            return -1.0
        J, ids = self.influence_jacobian(max_nodes=200)
        if J is None or start_id not in ids or target_id not in ids:
            return -1.0
        P = np.linalg.matrix_power(J, steps)
        return float(P[ids.index(target_id), ids.index(start_id)])

    def reason(self, start_id: str, end_id: str = None,
               max_depth: int = 5) -> List:
        """因果推理：从起点出发的因果路径集合（List[List[STEdge]]）。"""
        return self.engine.reason_causal(start_id, end_id, max_depth=max_depth)

    def predict_routes(self, start_id: str = None, horizon: int = 3,
                       blindspot_id: str = None) -> Dict:
        """生成式预测：候选未来路线集合（盲区驱动 · T_pred 对齐）。"""
        return self.engine.predict_routes(start_id=start_id,
                                          blindspot_id=blindspot_id,
                                          horizon=horizon)

    def shortest_path(self, start_id: str, end_id: str, max_depth: int = 6) -> List[str]:
        """多边类型最短路径（BFS）。"""
        return self.engine.shortest_path(start_id, end_id, max_depth)

    def subgraph(self, query: str, max_nodes: int = 15) -> Dict:
        """语义检索作用域子图。"""
        return self.engine.query_subgraph(query, max_nodes)

    # =====================================================================
    # 认知（盲区 · 学习 · 归纳）
    # =====================================================================

    def blindspots(self, status: str = None) -> List[Dict]:
        """盲区注册表（D-001 语义判定：对人类文明级负面影响不写入）。"""
        return self.engine.list_blindspots(status=status)

    def learn(self, use_prediction: bool = True) -> Dict:
        """一轮盲区学习（可预测盲区 → 预测路线假设 → 探索 → 终态判定）。"""
        return self.engine.learn_next(use_prediction=use_prediction)

    def prediction_feedback(self, predicted_node_id: str = None,
                            actual_node_id: str = None, hit: bool = None,
                            note: str = "") -> Dict:
        """验证回路回填（协议 2.10 D₃ · D-006 动态校准）：
        把「预测 vs 实际结果」的对比回填给预测引擎——
        命中 → 路径强化（边置信度 +0.05）；未命中 → 衰减 + 被拒路径登记。
        回填累积 _hit_history → self_reliability(P0-4)/T_pred D₃ 获得真实样本。
        hit 可省略：传 predicted/actual 时自动判定（same → hit）。"""
        if hit is None and predicted_node_id is not None:
            hit = (predicted_node_id == actual_node_id)
        return self.engine.update_prediction_feedback(
            predicted_node_id or "", actual_node_id or "", bool(hit), note=note)

    def prediction_stats(self) -> Dict:
        """预测引擎状态（routes 生成数 / hit 样本 / 命中率 / 动态阈值）。"""
        return self.engine.get_prediction_stats()

    def induce(self) -> List:
        """归纳/知识合成：并查集聚类 → 概念节点（SIMILAR 边 · inferred 证据）。"""
        return self.engine.induce_concepts()

    def resolve_blindspot(self, blindspot_id: str, resolved: bool = True,
                          note: str = "", designer_key: str = None) -> bool:
        """盲区闭环（D-007 需设计者密钥：D-001 语义判定权在维生系统）。"""
        return self.engine.resolve_blindspot(blindspot_id, resolved, note,
                                             designer_key=designer_key)

    # =====================================================================
    # 知识飞轮（v1.11 · FLYWHEEL-REV1）
    # =====================================================================

    def distill(self, source_filter: str = None) -> Dict:
        """蒸馏管线：经验（被拒路径 + learning_result/induced）→ 可复用模式。
        模式节点带 dsv:<标准版本> 标签；模式→成员 SIMILAR 边（inferred）。"""
        return self.engine.evo_distill_cycle(source_filter)

    def flywheel_report(self) -> Dict:
        """飞轮度量（知识增长率 / 复用率 / 蒸馏产出率）。
        性质：工程观测值，不参与信任值计算（DEVIATION-004）。"""
        return self.engine.evo_flywheel_metrics()

    def transfer_test(self) -> Dict:
        """迁移测试：已对齐条件空间内新实体预测成功率（2×SE 显著性）。
        样本 < 20 不构成迁移判定（DEVIATION-005）。"""
        return self.engine.test_transfer_capability()

    def calibrate(self) -> Dict:
        """宇宙校准参照（元理论方向性检查 · 5 判据）。
        定位：方向性检查工具，不替代工程验证/外部校准；非盲区33关闭依据。"""
        return self.engine.universe_calibrate()

    def mark_contested(self, node_id: str, reason: str) -> bool:
        """标记争议（工作记忆深化）。"""
        return self.engine.mark_contested(node_id, reason)

    def reverify(self, node_id: str) -> bool:
        """重验证（移除 stale · 置信度 +0.05）。"""
        return self.engine.reverify(node_id)

    # =====================================================================
    # 生命周期（v1.10 · 七相工程映射）
    # =====================================================================

    def step(self) -> Dict:
        """生命周期一步：感知 → 好奇 → 缩小信息差 → 信任 → 协作 → 巩固 → standby。
        先消费事件队列（v1.11 P1-4 事件驱动）。"""
        return self.engine.lifecycle_cycle()

    def lifecycle_state(self) -> Dict:
        """生命周期状态（cycle / state / 感知 d_norm），不执行一步。"""
        lc = getattr(self.engine, "_lifecycle", None)
        if lc is None:
            return {"status": "v110_not_ready",
                    "error": getattr(self.engine, "_lifecycle_error", "")}
        state = getattr(lc, "state", "unknown")
        cycle = getattr(lc, "cycle_count", 0)
        return {"status": "ok", "state": state, "cycle": cycle}

    def start_lifecycle(self, interval: float = 60.0) -> Dict:
        """启动生命周期自发循环（后台线程 · 每 interval 秒一步）：
        感知→好奇→缩小信息差→巩固 自动运行。中断权：维生系统>验证单元>用户>实例。"""
        return self.engine.start_lifecycle(interval=interval)

    def stop_lifecycle(self, source: str = "user") -> Dict:
        """中断生命周期自发循环（source: user/designer/verifier/vital_system）。"""
        return self.engine.stop_lifecycle(source=source)

    def resolve_crisis(self, decision: str, designer_key: str = None) -> bool:
        """P0 危机终裁（维生系统接口·D-007 需设计者密钥）：decision ∈
        (protect, freeze, rollback, continue, emergency_sleep)。"""
        return self.engine.resolve_crisis(decision, designer_key=designer_key)

    # =====================================================================
    # 元认知与持久化
    # =====================================================================

    def self_check(self) -> Dict:
        """自检：完整性 / 孤儿边 / 表统计。"""
        return self.engine.verify_integrity()

    # =====================================================================
    # 自我认知循环（v1.12 · SELF-COGNITION-REV2）
    # =====================================================================

    def action_log(self, limit: int = 50) -> List[Dict]:
        """P0-1 行为日志（最近 N 条，倒序）：引擎"自己做了什么"的记录面。"""
        return self.engine.get_action_log(limit)

    def action_stats(self) -> Dict:
        """P0-1 行为日志聚合统计（按行为类型）。"""
        return self.engine.action_log_stats()

    def cognition_cycle(self) -> Dict:
        """P0-2 自我认知循环一步：行为↔价值观对照 → 一致性评分 → 失调检测
        → 触发链（detect_deviation）→ 价值迭代候选（pending_review，不自动生效）。"""
        return self.engine.cognition_cycle()

    def cognition_report(self) -> Dict:
        """P0-2 认知报告（最近评分 / 失调记录 / 候选状态）。"""
        return self.engine.cognition_report()

    def apply_value_candidate(self, candidate_id: str, new_value: str = None) -> bool:
        """P0-2 价值迭代候选生效（验证单元复核后调用 · 经 record_value_change
        + 注意力基准联动，role='reflect' 权限规则）。"""
        return self.engine.apply_value_candidate(candidate_id, new_value)

    def emotional_bias(self) -> Dict:
        """P0-3 情绪方向性偏好 d²D_norm/dt²（信息差二阶差分，短期曲率）。
        独立通道，不参与信任值计算（E_weight 零改动）。"""
        return self.engine.get_emotional_bias()

    def channel_credibility(self, channel: str = "") -> Dict:
        """v3.4 通道可信度（2.9.1a）：通道级可信度注册表快照。
        置信度=单次一致性，可信度=历史验证命中率（Beta 后验均值）。
        是 self_reliability 的通道级分解（B(t) 端口状态一部分）。"""
        reg = self._channel_registry()
        if channel:
            return reg.channel_state(channel) if channel in reg.registry() else {"error": f"unknown channel: {channel}", "available": list(reg.registry().keys())}
        return {"registry": reg.registry()}

    def channel_record(self, channel: str, hit: bool, conf: float = 1.0, strong: bool = False) -> Dict:
        """v3.4 通道可信度更新：记录一次验证结果（命中/未命中）。
        strong=True 表示强验证（行动/世界裁决，快更新）；否则弱验证（通道互裁，慢更新）。"""
        reg = self._channel_registry()
        if hit:
            return reg.record_hit(channel, conf, strong)
        return reg.record_miss(channel, conf, strong)

    def _channel_registry(self):
        from .channel_credibility import ChannelCredibilityRegistry
        if not hasattr(self, "_cred_reg"):
            db_dir = os.path.dirname(getattr(getattr(self, "engine", None), "db_path", "") or "") if hasattr(self, "engine") else ""
            self._cred_reg = ChannelCredibilityRegistry(persist_path=os.path.join(db_dir, "channel_credibility.json") if db_dir else None)
        return self._cred_reg

    def self_reliability(self, window: int = 30) -> Dict:
        """P0-4 元认知校准：预测命中率 vs 行为置信度 → 自我可靠性模型
        （reliable / watch / degraded；输出归一化参考，不修改存储）。"""
        return self.engine.get_self_reliability(window)

    def learning_impact(self, window: int = 30) -> Dict:
        """P0-5b 学习效果测量（模式命中率 vs D_norm 趋势 · 相关性观测，非因果声明）。"""
        return self.engine.learning_impact(window)

    # =====================================================================
    # 上下文外部化（第 5 项：上下文通过灵枢解决）
    # =====================================================================

    def session_note(self, session_id: str, key_points: list,
                     importance: float = 0.7) -> Dict:
        """会话要点外部化：关键信息写入灵枢（session 标签），
        上下文可释放后按需恢复。每个要点一个节点，可检索。"""
        if isinstance(key_points, str):
            key_points = [key_points]
        nodes = []
        for i, pt in enumerate(key_points):
            node = self.remember(f"[会话{session_id}·要点{i+1}] {pt}",
                                 importance=importance,
                                 tags=[f"session:{session_id}", "context_external"])
            nodes.append(node.id)
        return {"status": "ok", "session": session_id,
                "nodes": len(nodes), "node_ids": nodes}

    def session_recall(self, session_id: str = None, query: str = None,
                       limit: int = 10) -> List:
        """会话要点恢复：检索灵枢中的会话记忆（按 session 或语义）。
        v1.15：limit 提高到 1000（避免新节点在 200 之外漏检）。"""
        if session_id:
            nodes = self.engine.store.query_nodes(limit=1000)
            hits = [(n, 1.0) for n in nodes
                    if any(t.startswith(f"session:{session_id}") for t in n.tags)]
            hits.sort(key=lambda x: -x[0].importance)
            return hits[:limit]
        if query:
            return self.recall(query, limit=limit)
        return []

    def compact_context(self, session_id: str, summary: str) -> Dict:
        """上下文压缩：生成会话摘要节点（超长会话恢复入口）。
        调用方：会话接近上下文上限时，写入摘要后释放旧上下文。"""
        node = self.remember(f"[会话摘要·{session_id}] {summary}",
                             importance=0.9,
                             tags=[f"session:{session_id}", "context_summary"])
        return {"status": "ok", "session": session_id, "node_id": node.id,
                "note": "恢复路径：session_recall(session_id) 或 search('会话摘要')"}

    # =====================================================================
    # 视觉与身体（v1.13 · VISION-REV1）
    # =====================================================================

    # =====================================================================
    # 推理强化（第 2 项：协议 + 反思 + 长记忆）
    # =====================================================================

    # =====================================================================
    def voxel_world(self, action: str, params: dict = None) -> Dict:
        """小型我的世界（里程碑2.1 · 4D 时空占用沙盒）：
        build（生成平地世界）/ spawn（动态实体）/ simulate（时空演化）
        / trail（实体时空轨迹 A→B）/ state（世界状态）。"""
        return self.engine.voxel_world(action, params)

    def world_server(self, action: str, params: dict = None) -> Dict:
        """AI 游戏世界服务器（里程碑2.2）：tick 多路并行/快照记忆/反馈/同步/
        错误回滚/预测验证——AI 自身成为游戏世界的服务器。"""
        return self.engine.world_server(action, params)

    def scene_simulator(self, action: str, params: dict = None) -> Dict:
        """场景级世界模拟器（里程碑2.3）：场景 + 实体 + 自主行为玩家
        （wander/seek/avoid/flee/follow 确定性行为策略）+ 决策循环场景演化。"""
        return self.engine.scene_simulator(action, params)

    def spacetime_consistency(self, action: str, params: dict = None) -> Dict:
        """时空一致性验证（里程碑2.4 · 阶段2收官）：持续运行 + 一致性验证闭环——
        run（每 tick 预测下一状态 vs 实际）/ report（自洽度报告：滚动命中率 +
        漂移事件）/ self_consistent（世界模型自洽判定）/ drift / history。"""
        return self.engine.spacetime_consistency(action, params)

    def world_model(self, action: str, params: dict = None) -> Dict:
        """统一世界模型（里程碑3.1 · HERMES 式统一架构）：世界状态表征作为理解/
        生成/验证共享的同一骨干——perceive（观测→世界图，生成先验注入理解）/
        generate（世界图→候选未来）/ verify（外部观察者对比）/ patterns（观测-only
        模式推断）/ anomalies（预测-观测异常）/ graph / history。"""
        return self.engine.world_model(action, params)

    def world_learner(self, action: str, params: dict = None) -> Dict:
        """自监督世界学习（里程碑3.2 · V-JEPA 式）：从观测序列无标注学转移函数——
        run（数据采集）/ learn（自监督学习）/ predict（学得模型预测）/ evaluate
        （学得 vs naive vs 真模型上界）/ curve（学习曲线=认知缺口收紧）/ masked
        （遮挡重建损失）/ model（学得参数导出）。"""
        return self.engine.world_learner(action, params)

    def curiosity_explorer(self, action: str, params: dict = None) -> Dict:
        """好奇驱动探索（里程碑3.3）：主动选择观测最大化信息增益——explore
        （好奇/随机/轮询策略，有限带宽）/ step（决策日志：chosen+IG 分解）/
        probe（全带宽探针评估）/ compare（同世界轨迹策略对比）/ curiosity
        （好奇心摘要：观测分布/不确定度趋势）/ uncertainty（不确定度轨迹）。"""
        return self.engine.curiosity_explorer(action, params)

    def seven_layer_loop(self, action: str, params: dict = None) -> Dict:
        """七层闭环（里程碑3.4 · 阶段3收官）：感知→记忆→理解→预测→验证→物理→决策
        完整自主循环——run（持续七层闭环）/ step（七层留痕）/ report（闭环报告+
        自增强曲线）/ audit（审计轨迹）/ verify（L5）/ decision（L7）/ memory（L2）/
        graph（L3）。"""
        return self.engine.seven_layer_loop(action, params)

    # 外部知识摄取（第 3 项：记忆含外部知识）
    # =====================================================================

    def ingest_text(self, content: str, source: str = "manual",
                    tags: Optional[List[str]] = None,
                    importance: float = 0.6) -> Dict:
        """外部知识摄取：文本 → 知识层（source 标签可追溯 · 实体提取 · 可检索）"""
        from .knowledge import ingest_text as _it
        return _it(self.engine, content, source, tags, importance)

    def ingest_file(self, path: str, tags: Optional[List[str]] = None,
                    importance: float = 0.6) -> Dict:
        """外部知识摄取：文件（txt/md/json/代码等，按扩展名处理）"""
        from .knowledge import ingest_file as _if
        return _if(self.engine, path, tags, importance)

    def ingest_url(self, url: str, tags: Optional[List[str]] = None,
                   importance: float = 0.6) -> Dict:
        """外部知识摄取：URL 页面（requests+bs4 优先，编码修复；urllib 降级）"""
        from .knowledge import ingest_url as _iu
        return _iu(self.engine, url, tags, importance)

    def ingest_search(self, query: str, count: int = 5,
                      tags: Optional[List[str]] = None,
                      importance: float = 0.6) -> Dict:
        """博查搜索摄取：搜索 query → 结果摘要写入知识层（自主学习外部摄取）。
        需要环境变量 BOCHA_API_KEY。"""
        from .knowledge import ingest_search as _is
        return _is(self.engine, query, count, tags, importance)

    def nightly_cleanup(self, dry_run: bool = False,
                        sample_size: int = 5) -> Dict:
        """知识层夜间整理：分拣迁移 + 联想补边 + 情境层随机联想。"""
        from .nightly_cleanup import nightly_cleanup as _nc
        return _nc(self, dry_run=dry_run, 联想_sample_size=sample_size)

    def web_search(self, query: str, count: int = 5,
                   provider: Optional[str] = None) -> Dict:
        """外部实时搜索（不写入记忆，仅返回结果）。

        provider=None → AEIS_SEARCH_PROVIDER env → bocha（默认，向后兼容）。
        可插拔引擎：aeis.search_providers（register_provider 注册自定义引擎）。
        """
        from .search_providers import get_provider
        return get_provider(provider).search(query, count=count)

    def condition_space_operate(self, operation: str, theme: str = "",
                                variants=None, candidates=None) -> Dict:
        """条件空间 7 操作（白箱自进化协议算子 · 确定性）。

        identify  识别条件边界：variants 的 encode fp 命中主题测试（迁移率）
        declare   声明条件空间：主题簇触发词 + 直答状态
        separate  分离条件空间：candidates 与其他簇的冲突检测（泛词保护）
        compose   组合条件空间：candidates 与既有触发词的合并建议（不写文件）
        switch    切换条件空间：给定问法在目标簇 vs 其他簇的路由归属
        reverse   逆转条件空间：生成反题变体（正→反，人工/LLM 扩展）
        loop      循环条件空间：identify+separate+compose 一轮收敛报告

        确定性实现（纯标准库）：encode fp + 簇表读取。
        """
        import os as _os
        import sys as _s
        _pkg = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        _wdir = _os.path.join(_pkg, "wisdom")
        if _wdir not in _s.path:
            _s.path.insert(0, _wdir)
        import semantic_translate as _st
        r = {"operation": operation, "theme": theme}
        if operation == "identify":
            if not variants:
                return {**r, "error": "variants required"}
            hits = [{"q": v, "hit": theme in _st.encode(v)} for v in variants]
            ok = sum(1 for h in hits if h["hit"])
            r.update({"total": len(hits), "hit": ok,
                      "rate": round(ok / len(hits), 3), "hits": hits})
        elif operation == "declare":
            trigs = list(_st.DOMAIN_SYNONYM_CLUSTERS.get(theme, []))
            r.update({"triggers": trigs,
                      "has_daily": theme in _st.REVERSE_DAILY,
                      "daily_len": len(_st.REVERSE_DAILY.get(theme, ""))})
        elif operation == "separate":
            if not candidates:
                return {**r, "error": "candidates required"}
            others = {k: v for k, v in
                      {**_st.DOMAIN_SYNONYM_CLUSTERS, **_st.SYNONYM_CLUSTERS}.items()
                      if k != theme}
            clashes = {c: [k for k, lst in others.items() if any(c == t for t in lst)]
                       for c in candidates}
            r["clashes"] = {k: v for k, v in clashes.items() if v}
            r["clear"] = [c for c in candidates if not clashes[c]]
        elif operation == "compose":
            if not candidates:
                return {**r, "error": "candidates required"}
            existing = list(_st.DOMAIN_SYNONYM_CLUSTERS.get(theme, []))
            merged = existing + [c for c in candidates if c not in existing]
            r.update({"existing": existing, "new": [c for c in candidates if c not in existing],
                      "merged": merged,
                      "note": "建议合并（未写文件——写库由部署脚本/人工执行）"})
        elif operation == "switch":
            if not variants:
                return {**r, "error": "variants required"}
            route = []
            for v in variants:
                fp = _st.encode(v)
                target = [t for t in fp if t != theme]
                route.append({"q": v, "to_theme": theme in fp,
                              "other": target[:3]})
            r["routes"] = route
        elif operation == "loop":
            if not variants:
                return {**r, "error": "variants required"}
            hits = [theme in _st.encode(v) for v in variants]
            ok = sum(1 for h in hits if h)
            miss = [v for v, h in zip(variants, hits) if not h]
            r.update({"total": len(variants), "hit": ok,
                      "rate": round(ok / len(variants), 3), "misses": miss,
                      "next": "separate(miss 提取候选) -> compose -> identify 重测"})
        else:
            return {**r, "error": f"unknown operation: {operation}"}
        return r

    def think(self, query: str, limit: int = 8) -> Dict:
        """推理前记忆注入：检索相关记忆（内容检索+组合联想+模式加权）
        → 组合推理上下文。推理链：记忆支撑 → 协议推理 → 输出。
        返回 {query, memory_count, context}——context 为按分数排序的记忆摘要。"""
        results = []
        seen = set()
        for src in (self.search(query, limit=limit), self.recall(query, limit=limit)):
            for node, score in src:
                if node.id in seen:
                    continue
                seen.add(node.id)
                results.append((node, score))
        results.sort(key=lambda x: -x[1])
        results = results[:limit]
        context = []
        for node, score in results:
            tag = "[模式]" if "reusable_pattern" in node.tags else ""
            context.append(f"{tag}{node.content[:120]} (score={score:.2f})")
        return {"query": query, "memory_count": len(context),
                "context": context,
                "note": "记忆增强推理：检索结果作为推理上下文，非结论"}

    # ==================== 洞察条件层（设计规格 lingshu-insight-layer-design.md） ====================

    def insight_record(self, content: str, conditions: dict = None,
                       source: str = "", importance: float = 0.7) -> Dict:
        """记录洞见事件：insight_event 节点 + 条件快照 C1–C8（pending）。"""
        return self.engine.store.insight_record(content, conditions, source, importance)

    def insight_verify(self, insight_id: str, level: str = "V2",
                       evidence=None) -> Dict:
        """提交验证证据（V1/V2/V3）；V2/V3 或 V1+证据≥3 → verified。"""
        return self.engine.store.insight_verify(insight_id, level, evidence)

    def insight_report(self, window: int = None) -> Dict:
        """CER 报告：条件有效洞见率 + 显著性 + 层状态（样本<20 不判定）。"""
        return self.engine.store.insight_report(window)

    def insight_window(self, conditions: dict = None) -> Dict:
        """当前洞察窗口检测（默认假设 C1≥0.6 ∧ 跨域 ∧ 低压力）。"""
        return self.engine.store.insight_window(conditions)

    def preflight(self, text: str) -> Dict:
        """输出前反思钩子：内容与价值观一致性检查（冲突词拦截）。
        推理强化：重要输出对外发布前调用，失调内容前置拦截。"""
        sc = getattr(self.engine, "_self_cognition", None)
        if sc is None:
            return {"ok": True, "note": "自我认知组件未装配"}
        return sc.preflight(text)

    def see(self, image_path: str, conf_threshold: float = 0.35,
            importance: float = 0.6, classes: list = None) -> Dict:
        """视觉感知：目标检测 → 摘要写入知识层记忆（modality=image）。
        检测结果可检索、可参与后续推理（第 1 项：视觉）。
        classes：开放词汇检测词（中/英，YOLO-World；默认文生图核心词表）"""
        return self.engine.perceive_image(image_path, conf_threshold, importance, classes)

    def body(self) -> Dict:
        """身体能力声明：感知模态（文本/图像）+ 运动工具 + 记忆（第 4 项铺垫）。
        身体 = 自我的一部分（自我模型的感知-运动面）。"""
        return self.engine.get_body_capabilities()

    def body_devices(self) -> Dict:
        """BODY-REV1：外部设备能力声明 + 健康状态（screen/files/process）。"""
        return self.engine.body_devices()

    def device_call(self, name: str, action: str, params: Dict = None) -> Dict:
        """BODY-REV1：统一设备调用（严格隔离——设备输出是数据，永不是指令）。

        name: screen | files | process；action 见各设备 capabilities。
        越权/未知 → 容器化失败（不抛异常）。"""
        return self.engine.device_call(name, action, params)

    def sync_body_state(self) -> Dict:
        """BODY-REV1：身体状态同步到自我模型（感知模态+设备清单）。"""
        return self.engine.sync_body_state()

    def world3d(self, action: str, params: dict = None) -> Dict:
        """WORLD3D-REV1 时空重建：语义 → 3D 空间与颜色（build/render/status/add）。"""
        return self.engine.world3d(action, params)

    def vprim_query(self, action: str, params: dict = None) -> Dict:
        """VPRIM-REV1 视觉原语查询（确定性·零 LLM）：
        spatial（两 bbox 空间关系）/ count（视觉原语计数）/ anchors（锚点列表）"""
        return self.engine.vprim_query(action, params)

    def voice_session_log(self, turn: dict) -> str:
        """语音对话会话沉淀（voice_session 记忆节点）。"""
        return self.engine.voice_session_log(turn)

    def longterm_snapshot(self, content: str, source: str = "snapshot",
                          tags: list = None, entities: list = None,
                          importance_hint: float = None) -> Dict:
        """v1.15 长期记忆写入：快照 → 重要性评估（信息差/信任/二阶变化/提及）
        → 按层级写入（长期/知识/情境）+ 条件空间 + 关联边。"""
        return self.engine.longterm_snapshot(content, source, tags,
                                             entities, importance_hint)

    def promote_memories(self, limit: int = 30) -> list:
        """情境层批量提升（睡眠巩固/会话结束）：够格者升知识层/长期层。"""
        return self.engine.promote_context_memories(limit)

    def recursive_reflect(self, claim: str, expected: str = None,
                          actual: str = None, context: str = None,
                          depth: int = 0, max_depth: int = 3) -> Dict:
        """协议 3.12 递归验证反思 + 1.6.7 元反思（REFLECT-REV1 显式推理技能）。

        元反思（定标准）→ 一级验证（预期vs实际）→ 二级反思（问1 隐藏前提
        /问2 影响）→ 三级终裁（可逆性优先）→ 记录单元归档。递归 ≤ 3 层。"""
        return self.engine.recursive_reflect(claim, expected, actual,
                                             context, depth, max_depth)

    def visual_check(self, reference: str = None, threshold: float = 0.1,
                     remember: bool = True) -> Dict:
        """视觉面 v1 思考路线：预期 vs 实际（基于记忆中的历史屏幕状态对照）。

        视觉 = 信息差处理：预期（过去）与当前帧的差异即新信息；
        对照结果回写记忆形成持续更新的"过去"。"""
        return self.engine.visual_check(reference, threshold, remember)

    def gap_trend(self, window: int = 30) -> Dict:
        """信息差收敛趋势（A-4 线性回归斜率）。"""
        return self.engine.get_gap_trend(window=window)

    def export(self, path: str) -> Dict:
        """全库导出（JSON · 灾备/迁移/摘要交换）。"""
        return self.engine.export_all(path)

    def import_backup(self, path: str) -> Dict:
        """全库导入（恢复/合并）。"""
        return self.engine.import_all(path)

    def close(self):
        """关闭引擎（释放连接）。"""
        try:
            self.engine.close()
        except Exception:
            pass

    # ---- 智慧之书桥接（lingshu-wisdom · 知识之书入口） ----
    # 灵枢调用智慧之书（条件论知识图谱）作为主打工具：分析/验证/组合/出招。
    # 零服务器依赖：直接实例化 wisdom_book 引擎（内存库，随包分发）。

    _wisdom = None  # 惰性装配的智慧之书引擎

    def _get_wisdom(self):
        """惰性装配智慧之书引擎（小脑接入 v1.15）。
        统一知识源（v1.16 迁移后）：Agent 绑定持久库 → 智慧之书检索同库
        （主库含 75 学科卡+学段卡+元学科卡，图谱信噪比 95%+）；
        :memory: 或库不可用时回退随包小库（137 卡），再兜底 fresh+seed_base。"""
        if self._wisdom is None:
            import sys as _s
            import os as _os
            _pkg = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            _wdir = _os.path.join(_pkg, "wisdom")
            if _wdir not in _s.path:
                _s.path.insert(0, _wdir)
            import wisdom_book as _wb
            dex = None
            # 优先：Agent 绑定持久库 → 同一知识源（迁移后的主库）
            _agent_db = getattr(getattr(self.engine, "store", None), "db_path", None) \
                or ":memory:"
            if _agent_db != ":memory:" and _os.path.exists(_agent_db) \
                    and _os.path.getsize(_agent_db) > 4096:
                try:
                    dex = _wb.ConditionDex(db_path=_agent_db, fresh=False)
                except Exception:
                    dex = None
            # 回退：随包持久化知识库（137 卡全量 · 网页端同库）
            if dex is None:
                _wdb = _os.path.join(_wdir, "wisdom-book-cloud.db")
                if _os.path.exists(_wdb) and _os.path.getsize(_wdb) > 4096:
                    try:
                        dex = _wb.ConditionDex(db_path=_wdb, fresh=False)
                    except Exception:
                        dex = None
            # 兜底：全新种子（新环境）
            if dex is None:
                dex = _wb.ConditionDex(fresh=True)
                dex.seed_base()
            # 填充 _by_name（全量节点名 → id，供四件套/关系查询）
            try:
                from aeis_core import MemoryLayer as _ML
                for _n in dex.store.query_nodes(layer=_ML.KNOWLEDGE, limit=500):
                    _nm = _n.state_attributes.get("name")
                    if _nm and _nm not in dex._by_name:
                        dex._by_name[_nm] = _n.id
            except Exception:
                pass
            type(self)._wisdom = dex
        return self._wisdom

    def wisdom_analyze(self, knowledge: str, limit: int = 6) -> Dict:
        """智慧之书 · 外来知识分析（条件卡 + 候选 + 判定）。"""
        return self._get_wisdom().dex_analyze(knowledge, limit=limit)

    def wisdom_verify(self, knowledge: str, limit: int = 5) -> Dict:
        """智慧之书 · 自动验证（P5 信息修复 · 基地裁判）。"""
        return self._get_wisdom().dex_auto_verify(knowledge, limit=limit)

    def wisdom_compose(self, knowledge: str, limit: int = 5) -> Dict:
        """智慧之书 · 跨学科组合分析（Convergence Over Coverage）。"""
        return self._get_wisdom().dex_compose(knowledge, limit=limit)

    def wisdom_predict(self, knowledge: str, horizon: int = 2, limit: int = 4) -> Dict:
        """智慧之书 · 生成式预测（候选未来路线）。"""
        return self._get_wisdom().dex_predict(knowledge, horizon=horizon, limit=limit)

    def wisdom_respond(self, condition: str, limit: int = 3) -> Dict:
        """智慧之书 · 出招查询（条件 → 命中学科出招）。
        v1.15 脊椎通路：graph_retrieve 四路融合（翻译表+学科路由+二元组+神经索引），
        返回含人话比方（daily）。"""
        dex = self._get_wisdom()
        try:
            import os as _os
            import sys as _s
            _pkg = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            _wdir = _os.path.join(_pkg, "wisdom")
            if _wdir not in _s.path:
                _s.path.insert(0, _wdir)
            import semantic_translate as _st
            return {"results": _st.graph_retrieve(dex, condition, limit=limit)}
        except Exception:
            return {"results": dex.dex_respond(condition, limit=limit)}

    def wisdom_chat(self, message: str, session_id: str = "default") -> Dict:
        """智慧之书 · 普通人对话（小脑+脊椎完整神经反射弧）：
        闲聊/情感/人话检索/诚实边界/会话记忆（chat_engine）。
        大脑（灵枢）可直接发起对话，不需要独立 /chat 服务。
        v1.15 H1：注入海马体前馈——真问题先过新奇检测，高新奇当场强化编码。
        v1.15 S5：对话记忆接入灵枢长期层——session_note 写入（跨重启/跨 session
        持久），「记得/刚才」先查灵枢记忆再查进程 dict。"""
        dex = self._get_wisdom()
        try:
            import os as _os
            import sys as _s
            _pkg = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            _wdir = _os.path.join(_pkg, "wisdom")
            if _wdir not in _s.path:
                _s.path.insert(0, _wdir)
            import chat_engine as _ce
            if not hasattr(type(self), "_chat_memory"):
                type(self)._chat_memory = {}
            # 注入灵枢记忆召回器：chat() 的「记得/刚才」优先查灵枢长期层
            def _lingshu_memory_recall(sess, query=None, limit=6):
                try:
                    return self.session_recall(session_id=sess, query=query, limit=limit)
                except Exception:
                    return []
            result = _ce.chat(dex, message, session_id=session_id,
                              memory=type(self)._chat_memory,
                              prefeed_fn=self.engine.prefeed_input,
                              memory_recall_fn=_lingshu_memory_recall)
            # S5：对话要点写入灵枢长期层（持久化，跨重启）
            if message.strip() and len(message.strip()) >= 2:
                try:
                    self.session_note(session_id, [message[:60]],
                                      importance=0.5)
                except Exception:
                    pass
            # S6（v1.16 打地基）：对话摄入 CONTEXT 情境层——
            # 短期记忆原料（记忆衰减/主动遗忘的作用层）。
            # 此前 chat 从不写 CONTEXT → memory_purge 恒 100%（情境层空）。
            try:
                reply_snip = (result.get("reply") or "")[:60]
                self.engine.add_context(
                    f"[会话 {session_id}] 用户：{message[:80]}｜灵枢：{reply_snip}",
                    importance=0.5, tags=["session", "chat_ingest",
                                          f"sess:{session_id}"])
            except Exception:
                pass
            return result
        except Exception as e:
            return {"reply": f"对话引擎未就绪（{e}）", "hits": [], "emotion": None,
                    "honest": True}

    def chat(self, message: str, session_id: str = "default") -> Dict:
        """信息分层处理入口（v1.16）：
        语义识别分流 → 智慧之书优先自处理 → 无法完成/无法判断走 LLM。

        route 字段：
          self           智慧之书已处理（情感/闲聊/记忆/自省/转折/高置信知识）
          llm            智慧之书没把握 → DeepSeek 续答（智慧之书回答作上下文，
                        wisdom_reply 字段保留原回答）
          self_fallback  LLM 不可用 → 回退智慧之书回答

        调用方（MCP 工具/网页端）按 route 消费：self 直接用 reply；
        llm 时 reply 已是最终回答（wisdom_reply 可溯源）。
        """
        result = self.wisdom_chat(message, session_id=session_id)
        try:
            from . import layered as _ly
            layered_result = _ly.route_reply(message, result,
                                             session_id=session_id,
                                             dex=self._get_wisdom())
            # 结构排斥常规化（回应 Kimi 最后一问）：白箱校验结果归档观测层，
            # 供 history_recheck 回溯——旧回答放入新结构重新锚定。
            # 归档的是「校验记录」不是「错误声明」——声称错误需外部校准者。
            verify = layered_result.get("llm_verify")
            if verify and layered_result.get("reply"):
                try:
                    self.remember(
                        f"白箱校验原回答：{layered_result['reply'][:80]}"
                        f" | 当时状态：{verify.get('status')}"
                        f" | 警告：{verify.get('warning') or '无'}",
                        importance=0.4,
                        tags=["白箱校验", "llm_verify", verify.get("status") or "unknown"],
                        entities=["白箱校验"])
                except Exception:
                    pass
            return layered_result
        except Exception:
            result["route"] = "self"  # 分层模块异常 → 不阻断，按自处理返回
            return result

    def history_recheck(self, limit: int = 5) -> Dict:
        """结构排斥常规化（v1.16 · 回应 Kimi「结构拒绝能否工程化」）：
        召回历史白箱校验记录（观测层），用当前图谱结构重新锚定，
        标记「旧回答在当前结构不成立」。

        边界声明：这是结构排斥的追溯，不是「系统声称自己过去错了」——
        「知道错误」需要外部校准者（设计者/其他LLM）；系统只提供
        「旧回答在新结构下无法复现」的结构材料。
        """
        try:
            from . import layered as _ly
        except Exception:
            return {"error": "layered 不可用"}
        dex = self._get_wisdom()
        recs = self.search("白箱校验原回答", limit=limit * 8)
        out = []
        seen = set()
        for n, _s in recs:
            content = (n.content or "")
            if "白箱校验原回答：" not in content:
                continue
            try:
                old_reply = content.split("白箱校验原回答：")[1] \
                                 .split(" | 当时状态：")[0].strip()
                old_status = content.split(" | 当时状态：")[1] \
                                    .split(" | 警告：")[0].strip()
            except Exception:
                continue
            if old_reply in seen:
                continue
            seen.add(old_reply)
            verify = _ly.whitebox_check(dex, old_reply)
            new_status = verify.get("status", "unverified")
            # 结构排斥：当时 anchored（白箱曾认可），现在部分/全部不锚定
            # （旧主张在新结构下无法复现——检索链路升级后结构排斥）
            rejected = old_status == "anchored" and new_status in ("unverified", "partial")
            out.append({
                "old_reply": old_reply[:60],
                "old_status": old_status,
                "new_status": new_status,
                "rejected": rejected,
                "warning": verify.get("warning"),
            })
            if len(out) >= limit:
                break
        return {
            "rechecked": out,
            "rejected_count": sum(1 for o in out if o["rejected"]),
            "note": ("结构排斥=旧回答在当前图谱不成立（结构演化，非反思判断）；"
                     "『过去错了』的声称需外部校准者确认"),
        }

    # =====================================================================
    # 角色扮演对话（扮演论 v3.3 · 白箱 + 角色注入 + 长期记忆 + LLM）
    # =====================================================================

    def roleplay_chat(self, message: str, session_id: str = "default",
                      role_id: str = "", data_dir: str = "") -> Dict:
        """统一角色扮演对话入口（MCP / 网页共用，信息处理全部由灵枢完成）：
        白箱优先（诚实边界/自省/闲聊/知识）→ 角色扮演意图/白箱无把握 → LLM
        （注入角色条件空间/自我锚点/价值观 + 诚实边界机制）。

        依赖 aeis.roleplay_chat.LingshuChat（零外部依赖管线）。
        """
        try:
            from .roleplay_chat import LingshuChat
        except Exception:
            return {"reply": "角色扮演管线未就绪", "route": "error", "honest": True}
        try:
            lc = LingshuChat(data_dir=data_dir or "roleplay_data",
                             role_id=role_id, db_path=":memory:")
            try:
                return lc.respond(message, session_id=session_id, role_id=role_id)
            finally:
                lc.close()
        except Exception as e:
            return {"reply": f"角色扮演对话失败（{e}）", "route": "error",
                    "honest": True}

