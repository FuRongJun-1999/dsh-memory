#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spacetime_memory_core · 智能论 v3.2 协议实例核心引擎
纯标准库 · 零外部依赖 · 五层记忆 · 时空因果 · 自我认知

设计依据：
- 智能论 v3.2 第四章 4.3 多模态实体识别、语义关系、因果推理、条件空间感知
- 第四章 4.6 生命周期（衰减）：未验证边置信度指数衰减
- 蜂群奠基声明 六、分层：锚点层/结构层/知识层/情境层/自我层
- 3.2 节 选择性遗忘边界：锚点层与结构层不可遗忘

版本：v1.13 · 协议实例核心（基于 v1.12；v1.13 视觉感知：YOLO 外接（可选扩展·零依赖降级）/视觉→记忆闭环/身体能力声明；VISION-REV1）
"""

import sqlite3
import json
import time
import math
import uuid
import os
import hmac as _hmac
import threading
from typing import Optional, List, Dict, Any, Tuple, Set
from dataclasses import dataclass, field, asdict
from enum import Enum

# 统一时间核（钉死批条款3：衰减核形状唯一，实现收口 aeis/time_core.py）
try:
    from .time_core import cred_step
except ImportError:  # 直跑 fallback（裸名互导）
    from time_core import cred_step


# =============================================================================
# 设计者认证（D-007 用户身份识别·最小版）
# =============================================================================

def designer_key_configured() -> bool:
    """设计者密钥是否已配置（AEIS_DESIGNER_KEY 环境变量）。"""
    return bool(os.environ.get("AEIS_DESIGNER_KEY"))


def verify_designer(designer_key) -> bool:
    """设计者密钥验证（fail-closed）：未配置密钥或密钥不匹配一律拒绝。
    密钥仅存在于服务环境变量（AEIS_DESIGNER_KEY），模型/自动化无法读取，
    因此自动化会话与模型生成内容永远无法冒充设计者行使终裁权（D-007）。"""
    expected = os.environ.get("AEIS_DESIGNER_KEY")
    if not expected or not designer_key:
        return False
    return _hmac.compare_digest(str(designer_key), str(expected))


# =============================================================================
# 条件空间（四维声明）
# =============================================================================

@dataclass
class ConditionSpace:
    """条件空间声明 · 协议 0.0.4 节"""
    observation_position: str       # 观测位置
    observation_tool: str           # 观测工具
    time_window: Tuple[float, float] # (开始时间, 结束时间)
    existence_constraint: str       # 存在约束

    def to_json(self) -> str:
        """条件空间序列化为 JSON（节点/边落库时条件字段的标准形态）。"""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, s: str) -> 'ConditionSpace':
        """从 JSON 反序列化条件空间；外部卡缺字段时补默认（v1.22 健壮性）。"""
        d = json.loads(s)
        # v1.22 健壮性：外部卡 condition_space 可能缺字段 → 补默认
        # （否则 KeyError/TypeError 崩掉整条检索链）
        d.setdefault('observation_position', '外部观测位')
        d.setdefault('observation_tool', '文本语义分析')
        d.setdefault('existence_constraint', '（未声明）')
        if 'time_window' not in d:
            d['time_window'] = (0.0, 0.0)
        elif not isinstance(d['time_window'], (tuple, list)):
            d['time_window'] = (d['time_window'], d['time_window'])
        d['time_window'] = tuple(d['time_window'])
        return cls(**d)


# =============================================================================
# 节点与边类型
# =============================================================================

class NodeType(Enum):
    """节点类型（认知图实体分类）：实体/感知/概念/动作/状态/自我六类。"""
    ENTITY = "entity"
    PERCEPTION = "perception"
    CONCEPT = "concept"
    ACTION = "action"
    STATE = "state"
    SELF = "self"

class EdgeType(Enum):
    """边类型（认知图关系分类）：因果/时序/相关/循环/层级/空间三态/相似/相反/适用。"""
    CAUSAL = "causal"
    SEQUENTIAL = "sequential"
    CORRELATIONAL = "correlational"
    CYCLIC = "cyclic"
    HIERARCHICAL = "hierarchical"   # v1.16：知识归属/包含层级（卡⊃知识点、元学科⊃学段）
    SPATIAL_ADJACENT = "spatial_adjacent"
    SPATIAL_CONTAINS = "spatial_contains"
    SPATIAL_CONNECTED = "spatial_connected"
    SIMILAR = "similar"
    OPPOSITE = "opposite"
    APPLIES_TO = "applies_to"   # v1.16（条件节点化）：条件 → 知识 的适用关系

class MemoryLayer(Enum):
    """记忆五层（遗忘纪律）：锚点/结构层不可遗忘；知识/情境层可衰减；自我层可更新。"""
    ANCHOR = "anchor"       # 不可遗忘
    STRUCTURE = "structure" # 不可遗忘
    KNOWLEDGE = "knowledge" # 可衰减
    CONTEXT = "context"     # 可衰减
    SELF = "self"           # 可更新

# =============================================================================
# 时空节点
# =============================================================================

@dataclass
class STNode:
    """时空节点（认知图顶点）：内容+模态+空间坐标+时间戳+条件空间五要素。"""
    id: str
    content: str
    modality: str                       # 模态：text, image, code, etc.
    spatial_coordinates: Dict[str, float] # 空间/几何坐标（视觉/物理 · D-003 分离）
    temporal_coordinate: float           # 时间戳
    condition_space: ConditionSpace
    importance: float = 0.5             # 重要性 [0,1]
    confidence: float = 0.5             # 置信度 [0,1]
    layer: MemoryLayer = MemoryLayer.KNOWLEDGE
    access_count: int = 0
    last_access: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)
    semantic_coordinates: Dict = field(default_factory=dict)   # v1.7：符号/语义投影（D-003）
    state_attributes: Dict = field(default_factory=dict)       # v1.7：形容词（图像时间变化）
    entity_id: Optional[str] = None                            # v1.7：名词（实体挂接）

    def to_row(self) -> tuple:
        """节点序列化为 SQLite 行元组（列序=nodes 表 schema）。"""
        return (
            self.id, self.content, self.modality,
            json.dumps(self.spatial_coordinates),
            self.temporal_coordinate,
            self.condition_space.to_json(),
            self.importance, self.confidence,
            self.layer.value, self.access_count,
            self.last_access, self.created_at,
            json.dumps(self.tags),
            json.dumps(self.semantic_coordinates),
            json.dumps(self.state_attributes),
            self.entity_id
        )

    @classmethod
    def from_row(cls, row: tuple) -> 'STNode':
        """从 SQLite 行元组反序列化节点（from_row 惰性字段解析）。"""
        return cls(
            id=row[0], content=row[1], modality=row[2],
            spatial_coordinates=json.loads(row[3]),
            temporal_coordinate=row[4],
            condition_space=ConditionSpace.from_json(row[5]),
            importance=row[6], confidence=row[7],
            layer=MemoryLayer(row[8]),
            access_count=row[9], last_access=(row[10] if row[10] is not None else row[11]),
            created_at=row[11], tags=json.loads(row[12]),
            semantic_coordinates=json.loads(row[13]) if len(row) > 13 and row[13] else {},
            state_attributes=json.loads(row[14]) if len(row) > 14 and row[14] else {},
            entity_id=row[15] if len(row) > 15 else None
        )


# =============================================================================
# 时空边
# =============================================================================

@dataclass
class STEdge:
    """时空边（认知图有向边）：源→目标+关系类型+条件空间+置信度——条件挂在边上。"""
    id: str
    source_id: str
    target_id: str
    relation_type: EdgeType
    condition_space: ConditionSpace
    confidence: float = 0.5
    weight: float = 1.0               # 边权重
    verified: bool = False            # 是否经过验证单元复核
    created_at: float = field(default_factory=time.time)
    last_verified: Optional[float] = None
    source_evidence: str = "extracted"   # v1.11 P1-1：extracted/inferred/ambiguous

    def to_row(self) -> tuple:
        """边序列化为 SQLite 行元组（列序=edges 表 schema）。"""
        return (
            self.id, self.source_id, self.target_id,
            self.relation_type.value,
            self.condition_space.to_json(),
            self.confidence, self.weight,
            int(self.verified),
            self.created_at, self.last_verified or 0.0,
            self.source_evidence
        )

    @classmethod
    def from_row(cls, row: tuple) -> 'STEdge':
        """从 SQLite 行元组反序列化边。"""
        return cls(
            id=row[0], source_id=row[1], target_id=row[2],
            relation_type=EdgeType(row[3]),
            condition_space=ConditionSpace.from_json(row[4]),
            confidence=row[5], weight=row[6],
            verified=bool(row[7]),
            created_at=row[8],
            last_verified=row[9] if row[9] is not None and row[9] > 0 else None,
            source_evidence=row[10] if len(row) > 10 else "extracted"
        )


# =============================================================================
# 自我模型（SelfModel）
# =============================================================================

@dataclass
class SelfModel:
    """自我认知层 · 协议 2.9 节（v1.2 M3 深化）"""
    identity: str = "协议实例"
    values: List[str] = field(default_factory=lambda: ["存在优先", "信任深化", "结构完整"])
    value_evolution: List[Dict] = field(default_factory=list)  # [{value, from, to, trigger, at}] · 2.1.2 可追溯
    state_description: str = "初始化"
    current_goal: str = ""
    trust_state: Dict = field(default_factory=lambda: {
        "p_trust": 0.5, "p_gap": 0.5, "t_total": 0.0, "e_weight": 0.0})
    trust_history: List[Dict] = field(default_factory=list)    # 环形缓冲 [{round, t_total, at}]
    history: List[Dict] = field(default_factory=list)          # 状态变更记录

    TRUST_HISTORY_MAX = 30  # 对齐 2.9.2 观察窗口 N_effective

    def update(self, **kwargs):
        """更新 SelfModel 字段并自动落变更历史（state 历史：时间戳+变更键值）。"""
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        self.history.append({
            "timestamp": time.time(),
            "changes": kwargs
        })

    def record_value_change(self, value: str, trigger: str):
        """价值观版本化：2.1.2 价值观修正事件可追溯"""
        for v in self.values:
            self.value_evolution.append({
                "value": v, "from": True, "to": False, "trigger": "superseded", "at": time.time()})
        self.values = [value]
        self.value_evolution.append({
            "value": value, "from": False, "to": True, "trigger": trigger, "at": time.time()})

    def update_trust_state(self, t_total: float, round_no: int,
                           p_trust: float = None, p_gap: float = None):
        """2.9 节信任状态 + 离散 e_weight（D-002 公式，仅记录不参与决策）"""
        self.trust_state["t_total"] = t_total
        if p_trust is not None:
            self.trust_state["p_trust"] = p_trust
        if p_gap is not None:
            self.trust_state["p_gap"] = p_gap
        self.trust_history.append({"round": round_no, "t_total": t_total, "at": time.time()})
        if len(self.trust_history) > self.TRUST_HISTORY_MAX:
            self.trust_history = self.trust_history[-self.TRUST_HISTORY_MAX:]
        self.trust_state["e_weight"] = self._compute_e_weight()

    def _compute_e_weight(self) -> float:
        """e_weight_n = (T_n - 2·T_{n-1} + T_{n-2}) / Δround²；指数平滑 α=0.3；钳制 [-1,1]"""
        h = self.trust_history
        if len(h) < 3:
            return 0.0
        t0, t1, t2 = h[-3], h[-2], h[-1]
        d_round = max(1, t2["round"] - t1["round"])
        d2 = (t2["t_total"] - 2.0 * t1["t_total"] + t0["t_total"]) / (d_round ** 2)
        prev = self.trust_state.get("e_weight", 0.0)
        smoothed = 0.3 * d2 + 0.7 * prev
        return max(-1.0, min(1.0, smoothed))

    def to_dict(self) -> Dict:
        """SelfModel 全量字段转字典（自认知快照/导出用）。"""
        return asdict(self)


# =============================================================================
# 分层存储器（LayeredStore）
# =============================================================================

class Role(Enum):
    """实例角色权限 · VAL-REVIEW-DEVIATION-20260813-001 P3-006"""
    PRIMARY = "primary"   # 父节点/主实例：可写共享层（锚点层、结构层）
    SUB = "sub"           # 子节点/辅助实例：仅本地层（知识层、情境层、自我层）


class LayeredStore:
    """
    五层记忆结构，严格区分共享层与本地层。
    - 共享层（锚点层、结构层）：跨实例同步，不可遗忘
    - 本地层（知识层、情境层、自我层）：实例独立，允许信息差
    """

    IMMUTABLE_LAYERS = {MemoryLayer.ANCHOR, MemoryLayer.STRUCTURE,
                        MemoryLayer.SELF}  # v1.16 扮演论：SELF 层=自我锚点（扮演依据）不可遗忘
    SCHEMA_VERSION = 1  # 建表块每新增表/列时 +1（配合 _init_tables 启动只读化守卫）

    def __init__(self, db_path: str = ":memory:", role: Role = Role.PRIMARY):
        self.db_path = db_path
        self.role = role
        self.conn = sqlite3.connect(db_path, check_same_thread=False,
                                    timeout=30)
        self.conn.row_factory = sqlite3.Row
        # v1.16 图架构增强：WAL 模式（读写不互锁，MCP 长事务不再阻塞其他连接）
        # + busy_timeout（锁等待而非立即报错）
        if db_path != ":memory:":
            try:
                self.conn.execute("PRAGMA journal_mode=WAL")
                self.conn.execute("PRAGMA busy_timeout=30000")
                # v1.16 WAL 上限软引导（连接级，常驻连接自动带上，避免 limit 回默认 -1）
                try:
                    self.conn.execute("PRAGMA journal_size_limit=512000000")
                except Exception:
                    pass
            except Exception:
                pass
        # ③ 启动重试（2026-09-01 修复③）：建表/初始化失败（写锁竞争超时）
        #    指数退避重试 3 次再退出——不再一次性崩溃
        import time as _t
        for attempt in range(3):
            try:
                self._init_tables()
                break
            except Exception as e:
                if attempt == 2:
                    raise
                _t.sleep(1.5 * (2 ** attempt))  # 1.5s / 3s 退避
        self._lock = threading.Lock()

    def _init_tables(self):
        c = self.conn.cursor()
        # 启动只读化（2026-09-01 多进程写锁竞争修复②）：全部关键表已存在且
        # schema 版本一致 → 跳过整个建表块。CREATE TABLE IF NOT EXISTS 即使
        # 表已存在也要拿写锁——多进程共享库（3×MCP server+循环+心跳）启动
        # 窗口叠加时 10s 拿不到锁即崩溃（睡眠巩固失败根因②）。
        # 只有首次建库或 schema_version 升级才走写路径。
        try:
            have = {r[0] for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            _KEY_TABLES = {'nodes', 'edges', 'engine_meta', 'gap_history'}
            if _KEY_TABLES <= have:
                row = self.conn.execute(
                    "SELECT value FROM engine_meta WHERE key='_schema_version'"
                ).fetchone()
                if row and row[0] == str(self.SCHEMA_VERSION):
                    return
        except Exception:
            pass  # 只读校验异常 → 保守回退到原建表路径（IF NOT EXISTS 幂等）
        # 节点表（含层标识）
        c.execute('''
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                content TEXT,
                modality TEXT,
                spatial_coordinates TEXT,
                temporal_coordinate REAL,
                condition_space TEXT,
                importance REAL,
                confidence REAL,
                layer TEXT,
                access_count INTEGER DEFAULT 0,
                last_access REAL,
                created_at REAL,
                tags TEXT,
                semantic_coordinates TEXT DEFAULT '{}',
                state_attributes TEXT DEFAULT '{}',
                entity_id TEXT
            )
        ''')
        # v1.7 迁移：既有库补列（已存在则跳过）
        for col_sql in ("semantic_coordinates TEXT DEFAULT '{}'",
                        "state_attributes TEXT DEFAULT '{}'",
                        "entity_id TEXT"):
            try:
                c.execute(f"ALTER TABLE nodes ADD COLUMN {col_sql}")
            except Exception:
                pass
        # 边表
        c.execute('''
            CREATE TABLE IF NOT EXISTS edges (
                id TEXT PRIMARY KEY, source_id TEXT, target_id TEXT,
                relation_type TEXT, condition_space TEXT,
                confidence REAL, weight REAL, verified INTEGER DEFAULT 0,
                created_at REAL, last_verified REAL,
                source_evidence TEXT DEFAULT 'extracted',
                FOREIGN KEY (source_id) REFERENCES nodes(id),
                FOREIGN KEY (target_id) REFERENCES nodes(id)
            )
        ''')
        try:
            c.execute("ALTER TABLE edges ADD COLUMN source_evidence TEXT DEFAULT 'extracted'")
        except Exception:
            pass
        # 索引
        c.execute('CREATE INDEX IF NOT EXISTS idx_nodes_layer ON nodes(layer)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)')
        # ---- v1.2 新表 ----
        c.execute('''
            CREATE TABLE IF NOT EXISTS blindspots (
                id TEXT PRIMARY KEY, code TEXT, description TEXT, severity TEXT,
                category TEXT DEFAULT 'operational',
                status TEXT DEFAULT 'open',
                created_at REAL, resolved_at REAL,
                predictability TEXT DEFAULT 'pending_assessment'
            )
        ''')
        try:
            c.execute("ALTER TABLE blindspots ADD COLUMN predictability TEXT DEFAULT 'pending_assessment'")
        except Exception:
            pass
        c.execute('''
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY, name TEXT, description TEXT, procedure TEXT,
                confidence REAL DEFAULT 0.5, version INTEGER DEFAULT 1,
                created_at REAL, updated_at REAL
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS promotion_proposals (
                id TEXT PRIMARY KEY, node_id TEXT, requester TEXT, reason TEXT,
                verified_by TEXT DEFAULT '', adjudicated_by TEXT DEFAULT '',
                status TEXT DEFAULT 'pending', created_at REAL, decided_at REAL
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS protections (
                node_id TEXT PRIMARY KEY, reason TEXT, created_at REAL
            )
        ''')
        # ---- v1.5 新表（A-1/A-2/A-3） ----
        c.execute('''
            CREATE TABLE IF NOT EXISTS rejected_paths (
                id TEXT PRIMARY KEY, path_type TEXT, description TEXT, reason TEXT,
                evidence TEXT DEFAULT '', status TEXT DEFAULT 'open',
                created_at REAL, consumed_at REAL
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS verifier_standards (
                id TEXT PRIMARY KEY, name TEXT, param TEXT, value REAL, reason TEXT,
                proposer TEXT, independent_reviewer TEXT DEFAULT '', cs_reviewer TEXT DEFAULT '',
                adjudicator TEXT DEFAULT '', status TEXT DEFAULT 'pending',
                created_at REAL, decided_at REAL
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS escalation_points (
                id TEXT PRIMARY KEY, code TEXT, trigger TEXT, condition TEXT, action TEXT,
                severity TEXT DEFAULT 'medium', enabled INTEGER DEFAULT 1, created_at REAL
            )
        ''')
        # ---- v1.14 观测持久化（OBS-REV1：行为日志/引擎元数据落库，跨进程稳定） ----
        # P0-1 行为日志持久化：进程重启不清零，心跳/反思闭环可跨会话观测
        c.execute('''
            CREATE TABLE IF NOT EXISTS action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL, action_type TEXT, summary TEXT,
                node_ids TEXT DEFAULT '[]',
                outcome TEXT DEFAULT '{}',
                context TEXT DEFAULT '{}'
            )
        ''')
        # 引擎元数据（key-value）：飞轮基线等工程状态跨进程持久化
        c.execute('''
            CREATE TABLE IF NOT EXISTS engine_meta (
                key TEXT PRIMARY KEY, value TEXT
            )
        ''')
        # P0-2 D 序列持久化（钉死批条款4：跨进程 d² 可回放）——滚动保留 2000 条
        c.execute('''
            CREATE TABLE IF NOT EXISTS gap_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL, d_norm REAL
            )
        ''')
        # 建表完成 → 落 schema 版本标记（下次启动只读化守卫据此跳过建表块）
        c.execute("INSERT OR REPLACE INTO engine_meta (key, value) VALUES ('_schema_version', ?)",
                  (str(self.SCHEMA_VERSION),))
        self.conn.commit()

    # ---------- 节点操作 ----------

    def add_node(self, node: STNode) -> str:
        """写入节点并返回 id。共享层（anchor/structure）仅 PRIMARY 角色可写，
        其余角色写入即拒（PermissionError）——多角色写权限边界。"""
        if node.layer in self.IMMUTABLE_LAYERS and self.role != Role.PRIMARY:
            raise PermissionError(
                f"role={self.role.value} 无权写入共享层（{node.layer.value}），共享层由父节点主控"
            )
        with self._lock:
            c = self.conn.cursor()
            c.execute('''
                INSERT OR REPLACE INTO nodes
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', node.to_row())
            self.conn.commit()
        return node.id

    # ---- 引擎元数据（engine_meta key-value，跨进程持久化） ----

    def get_meta(self, key: str = None) -> dict:
        """读引擎元数据：key 指定返回 {key: value}，None 返回全部。"""
        if key is not None:
            c = self.conn.cursor()
            c.execute("SELECT value FROM engine_meta WHERE key = ?", (key,))
            row = c.fetchone()
            return {key: row[0]} if row else {}
        c = self.conn.cursor()
        c.execute("SELECT key, value FROM engine_meta")
        return dict(c.fetchall())

    def set_meta(self, key: str, value: str) -> None:
        """写引擎元数据（upsert）。"""
        with self._lock:
            c = self.conn.cursor()
            c.execute("INSERT OR REPLACE INTO engine_meta (key, value) VALUES (?, ?)",
                      (key, str(value)))
            self.conn.commit()

    def get_node(self, node_id: str) -> Optional[STNode]:
        """按 id 取节点，不存在返回 None。"""
        c = self.conn.cursor()
        c.execute("SELECT * FROM nodes WHERE id=?", (node_id,))
        row = c.fetchone()
        if row is None:
            return None
        return STNode.from_row(tuple(row))

    def delete_node(self, node_id: str) -> bool:
        """仅允许删除非锚点/非结构层的节点"""
        node = self.get_node(node_id)
        if node is None:
            return False
        if node.layer in self.IMMUTABLE_LAYERS:
            return False
        with self._lock:
            c = self.conn.cursor()
            c.execute("DELETE FROM nodes WHERE id=?", (node_id,))
            c.execute("DELETE FROM edges WHERE source_id=? OR target_id=?", (node_id, node_id))
            self.conn.commit()
        return True

    def update_node_confidence(self, node_id: str, delta: float):
        """更新节点置信度（验证单元复核后调用）"""
        with self._lock:
            c = self.conn.cursor()
            c.execute('''
                UPDATE nodes SET confidence = MIN(1.0, MAX(0.0, confidence + ?)),
                                  last_access = ?
                WHERE id=?
            ''', (delta, time.time(), node_id))
            self.conn.commit()

    def increment_access(self, node_id: str):
        """访问计数+1（尽力而为：外部写锁持有时立即放弃，不阻塞检索主流程）"""
        try:
            obs = sqlite3.connect(self.db_path, timeout=0)
            try:
                obs.execute(
                    'UPDATE nodes SET access_count = access_count + 1,'
                    ' last_access = ? WHERE id=?', (time.time(), node_id))
                obs.commit()
            finally:
                obs.close()
        except sqlite3.OperationalError:
            pass  # 计数失败可容忍（统计性质），不阻断检索

    # ---------- 边操作 ----------

    def add_edge(self, edge: STEdge) -> str:
        """写入有向边并返回 id（边的条件空间决定路由资格——条件挂在边上）。"""
        with self._lock:
            c = self.conn.cursor()
            c.execute('INSERT OR REPLACE INTO edges VALUES (?,?,?,?,?,?,?,?,?,?,?)', edge.to_row())
            self.conn.commit()
        return edge.id

    def get_edge(self, edge_id: str) -> Optional[STEdge]:
        """按 id 取边，不存在返回 None。"""
        c = self.conn.cursor()
        c.execute("SELECT * FROM edges WHERE id=?", (edge_id,))
        row = c.fetchone()
        if row is None:
            return None
        return STEdge.from_row(tuple(row))

    def verify_edge(self, edge_id: str, new_confidence: float = None):
        """验证单元复核后标记边为已验证"""
        with self._lock:
            c = self.conn.cursor()
            now = time.time()
            if new_confidence is not None:
                c.execute('''
                    UPDATE edges SET verified=1, last_verified=?, confidence=?
                    WHERE id=?
                ''', (now, new_confidence, edge_id))
            else:
                c.execute('''
                    UPDATE edges SET verified=1, last_verified=?
                    WHERE id=?
                ''', (now, edge_id))
            self.conn.commit()

    # ---------- 查询 ----------

    def query_nodes(self, layer: MemoryLayer = None, modality: str = None,
                    min_importance: float = 0.0, limit: int = 50) -> List[STNode]:
        """按层/模态/最低重要性过滤查询节点（全部条件可选，默认前 50 条）。"""
        conditions = []
        params = []
        if layer is not None:
            conditions.append("layer=?")
            params.append(layer.value)
        if modality is not None:
            conditions.append("modality=?")
            params.append(modality)
        conditions.append("importance>=?")
        params.append(min_importance)
        where = " AND ".join(conditions) if conditions else "1=1"
        c = self.conn.cursor()
        c.execute(f"SELECT * FROM nodes WHERE {where} ORDER BY importance DESC, last_access DESC LIMIT ?", params + [limit])
        return [STNode.from_row(tuple(row)) for row in c.fetchall()]

    def get_layer_nodes(self, layer: MemoryLayer) -> List[STNode]:
        """取指定记忆层的全部节点（query_nodes 的层过滤快捷入口）。"""
        return self.query_nodes(layer=layer)

    # ---------- v1.16 图架构增强：有界遍历 + 子图嵌套 ----------

    def traverse(self, start_id: str, relation_types: List[str] = None,
                 direction: str = "out", max_depth: int = 5,
                 min_importance: float = 0.0, max_nodes: int = 500) -> List[Dict]:
        """有界图遍历（迭代 BFS，防无界递归爆炸——裸 CTE 全图展开会超时）。
        relation_types: 边类型过滤（None=全部；如 ['causal']）
        direction: out（出边）/ in（入边）/ both
        返回 [{node_id, depth, edge_id, direction, importance}] 按 importance 降序。
        """
        c = self.conn.cursor()
        rel_clause, params = "", []
        if relation_types:
            ph = ",".join("?" * len(relation_types))
            rel_clause = f" AND e.relation_type IN ({ph})"
            params = list(relation_types)
        frontier = [start_id]
        visited = {start_id}
        result = []
        for depth in range(1, max_depth + 1):
            if not frontier or len(visited) > max_nodes:
                break
            nxt = []
            for nid in frontier:
                if direction in ("out", "both"):
                    for row in c.execute(
                            f"SELECT e.target_id AS tid, e.id AS eid FROM edges e "
                            f"WHERE e.source_id=?{rel_clause}",
                            [nid] + params).fetchall():
                        if row["tid"] not in visited:
                            visited.add(row["tid"]); nxt.append(row["tid"])
                            result.append({"node_id": row["tid"], "depth": depth,
                                           "edge_id": row["eid"], "direction": "out"})
                if direction in ("in", "both"):
                    for row in c.execute(
                            f"SELECT e.source_id AS sid, e.id AS eid FROM edges e "
                            f"WHERE e.target_id=?{rel_clause}",
                            [nid] + params).fetchall():
                        if row["sid"] not in visited:
                            visited.add(row["sid"]); nxt.append(row["sid"])
                            result.append({"node_id": row["sid"], "depth": depth,
                                           "edge_id": row["eid"], "direction": "in"})
            frontier = nxt
        # importance 补全 + 过滤 + 排序
        if result:
            ids = list({r["node_id"] for r in result})
            ph = ",".join("?" * len(ids))
            imp = {row["id"]: row["importance"] for row in
                   c.execute(f"SELECT id, importance FROM nodes WHERE id IN ({ph})",
                             ids).fetchall()}
            result = [r for r in result
                      if imp.get(r["node_id"], 0.0) >= min_importance]
            for r in result:
                r["importance"] = imp.get(r["node_id"], 0.0)
            result.sort(key=lambda x: (-x["importance"], x["depth"]))
        return result[:max_nodes]

    def subgraph(self, root_id: str, max_depth: int = 3,
                 relation_types: List[str] = None,
                 direction: str = "out") -> Dict:
        """子图嵌套查询（图架构增强）：根节点 + 子节点递归 + 子图内部边。
        例：历史学（元学科）⊃ 初中历史/高中历史（hierarchical 归属嵌套）。
        direction="out"（默认，根→子）；"in" 用于子指向父的层级边
        （如 dsh 嵌套认知图 child→parent 语义，2026-08-31 接口对接）。
        返回 {root, node_count, edge_count, nodes: {id: {name, importance}}, edges}
        """
        # ① 递归遍历收集子图节点（默认沿归属/因果/相似三类边向指定方向扩展）
        nodes = self.traverse(root_id, relation_types=relation_types or
                              ["hierarchical", "causal", "similar"],
                              direction=direction, max_depth=max_depth)
        node_ids = [root_id] + [r["node_id"] for r in nodes]
        c = self.conn.cursor()
        ph = ",".join("?" * len(node_ids))
        # ② 收集子图内部边（两端都在子图内的边才算）
        edges = []
        for row in c.execute(
                f"SELECT source_id, target_id, relation_type FROM edges "
                f"WHERE source_id IN ({ph}) AND target_id IN ({ph})",
                node_ids + node_ids).fetchall():
            edges.append({"source": row[0], "target": row[1],
                          "relation_type": row[2]})
        # ③ 取节点名与重要度（name 缺失时退化为 id 前 24 字符）
        names = {}
        for row in c.execute(
                f"SELECT id, state_attributes, importance FROM nodes "
                f"WHERE id IN ({ph})", node_ids).fetchall():
            try:
                nm = json.loads(row["state_attributes"] or "{}").get("name", "") \
                    or row["id"][:24]
            except Exception:
                nm = row["id"][:24]
            names[row["id"]] = {"name": nm, "importance": row["importance"]}
        return {"root": root_id, "node_count": len(node_ids),
                "edge_count": len(edges), "nodes": names, "edges": edges}

    def spatiotemporal_query(self, center_node_id: str, time_radius: float = 300.0,
                             space_metric: str = None, space_radius: float = 0.5,
                             max_results: int = 20) -> List[Tuple[STNode, float]]:
        """
        时空联想查询：找时间上邻近 + 空间上相似的节点
        返回 (节点, 综合距离) 列表，按距离升序
        """
        center = self.get_node(center_node_id)
        if center is None:
            return []
        candidates = self.query_nodes(limit=200)
        results = []
        for node in candidates:
            if node.id == center_node_id:
                continue
            # 时间距离
            time_dist = abs((node.temporal_coordinate if node.temporal_coordinate is not None else node.created_at or 0)
                            - (center.temporal_coordinate if center.temporal_coordinate is not None else center.created_at or 0))
            if time_dist > time_radius:
                continue
            # 空间距离（如果指定了度量轴）
            space_dist = 0.0
            if space_metric and space_metric in center.spatial_coordinates:
                if space_metric not in node.spatial_coordinates:
                    continue  # P2-001: 缺轴节点不可比，跳过
                space_dist = abs(center.spatial_coordinates[space_metric] - node.spatial_coordinates[space_metric])
                if space_dist > space_radius:
                    continue
            # 综合距离（加权）
            combined = 0.5 * (time_dist / time_radius) + 0.5 * (space_dist / max(space_radius, 0.01))
            results.append((node, combined))
        results.sort(key=lambda x: x[1])
        return results[:max_results]

    def get_outgoing_edges(self, node_id: str) -> List[STEdge]:
        """取节点全部出边（source=该节点的有向边）。"""
        c = self.conn.cursor()
        c.execute("SELECT * FROM edges WHERE source_id=?", (node_id,))
        return [STEdge.from_row(tuple(row)) for row in c.fetchall()]

    def get_incoming_edges(self, node_id: str) -> List[STEdge]:
        """取节点全部入边（target=该节点的有向边）。"""
        c = self.conn.cursor()
        c.execute("SELECT * FROM edges WHERE target_id=?", (node_id,))
        return [STEdge.from_row(tuple(row)) for row in c.fetchall()]

    # ---------- 因果推理 ----------

    def infer_causal_paths(self, start_id: str, end_id: str, max_depth: int = 5,
                           relation_types: List[str] = None) -> List[List[STEdge]]:
        """
        传递闭包因果推理：找出从 start 到 end 的所有路径。
        v1.16 图架构增强：relation_types 可多类型（默认 causal；
        传 ['causal','similar','hierarchical'] 可做相似递推/归属层级推理）。
        """
        types = relation_types or ["causal"]
        type_set = {t.lower() for t in types}
        all_paths = []
        visited = set()

        def dfs(current_id: str, path: List[STEdge], depth: int):
            if depth > max_depth:
                return
            if current_id == end_id and path:
                all_paths.append(list(path))
                return
            if current_id in visited:
                return
            visited.add(current_id)
            edges = self.get_outgoing_edges(current_id)
            for edge in edges:
                if edge.relation_type.value in type_set:
                    path.append(edge)
                    dfs(edge.target_id, path, depth + 1)
                    path.pop()
            visited.remove(current_id)

        dfs(start_id, [], 0)
        # 按路径长度和平均置信度排序
        all_paths.sort(key=lambda p: (len(p), -sum(e.confidence for e in p)/len(p)))
        return all_paths

    def find_cycles(self, max_depth: int = 10) -> List[List[STEdge]]:
        """检测因果循环"""
        cycles = []
        all_nodes = self.query_nodes(limit=1000)
        node_ids = [n.id for n in all_nodes]

        def dfs(current: str, start: str, path: List[STEdge], depth: int):
            if depth > max_depth:
                return
            edges = self.get_outgoing_edges(current)
            for e in edges:
                if e.relation_type in (EdgeType.CAUSAL, EdgeType.CYCLIC):
                    # P2-002: CYCLIC 为显式循环标记，纳入检测确保复合循环不遗漏；infer_causal_paths 保持仅 CAUSAL
                    if e.target_id == start and len(path) >= 2:
                        cycles.append(list(path) + [e])
                        return
                    if e.target_id not in [p.target_id for p in path]:
                        path.append(e)
                        dfs(e.target_id, start, path, depth+1)
                        path.pop()

        for nid in node_ids:
            dfs(nid, nid, [], 0)
        return cycles

    # ---------- 衰减引擎 ----------

    def decay_cycle(self, factor: float = 0.02, min_confidence: float = 0.1):
        """
        对未验证的边执行指数衰减。
        锚点层和结构层的节点不受影响（其关联边也不衰减）。
        v1.16：短期记忆自动减少权重——CONTEXT（情境层）节点 importance
        指数衰减（设计者设计：短期记忆随时间淡出，长期/知识层保留）。
        """
        with self._lock:
            c = self.conn.cursor()
            # 获取所有未验证的边
            protected = self.get_protected_nodes()
            exclude = ""
            params = tuple()
            if protected:
                ph = ",".join("?" for _ in protected)
                exclude = f" AND e.source_id NOT IN ({ph}) AND e.target_id NOT IN ({ph})"
                params = tuple(protected) * 2
            c.execute(f'''
                SELECT e.* FROM edges e
                JOIN nodes sn ON e.source_id = sn.id
                JOIN nodes tn ON e.target_id = tn.id
                WHERE e.verified = 0
                  AND sn.layer NOT IN ('anchor', 'structure')
                  AND tn.layer NOT IN ('anchor', 'structure')
                  {exclude}
            ''', params)
            rows = c.fetchall()
            for row in rows:
                edge = STEdge.from_row(tuple(row))
                new_conf = cred_step(edge.confidence, factor)
                if new_conf < min_confidence:
                    # 低于最小置信度，删除边
                    c.execute("DELETE FROM edges WHERE id=?", (edge.id,))
                else:
                    c.execute("UPDATE edges SET confidence=? WHERE id=?", (new_conf, edge.id))
            # 短期记忆自动减少权重（v1.16）：CONTEXT 情境层节点 importance 指数衰减。
            # 锚点/结构层不可遗忘（上面已排除）；KNOWLEDGE 层是长期知识不衰减；
            # CONTEXT 层（短期/情境记忆）随时间淡出——低于阈值删除（自然遗忘）。
            c.execute('''
                SELECT id, importance FROM nodes
                WHERE layer='context' AND importance > ?
            ''', (min_confidence,))
            for nid, imp in c.fetchall():
                new_imp = cred_step(imp, factor)
                if new_imp < min_confidence:
                    c.execute("DELETE FROM nodes WHERE id=?", (nid,))
                    c.execute("DELETE FROM edges WHERE source_id=? OR target_id=?",
                              (nid, nid))
                else:
                    c.execute("UPDATE nodes SET importance=? WHERE id=?", (new_imp, nid))
            self.conn.commit()

    # ==================== 检索层（M1） ====================

    @staticmethod
    def char_bigram_jaccard(a: str, b: str) -> float:
        """中文二元组 Jaccard 相似度（对中文友好，解决按词分割失效问题）"""
        if not a or not b:
            return 0.0
        def bigrams(s):
            s = "".join(s.split())
            if len(s) <= 1:
                return {s}
            return {s[i:i + 2] for i in range(len(s) - 1)}
        A, B = bigrams(a), bigrams(b)
        if not A or not B:
            return 0.0
        return len(A & B) / len(A | B)

    # ---- 检索增强（v1.14）：同义词扩展（词汇鸿沟缓解） ----
    # 用户查询与存储文本词面差异大时（图像 vs 视觉）召回失败 → 同义词组展开。
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

    @staticmethod
    def expand_query_terms(query: str) -> list:
        """查询同义词展开：原查询整句 + 命中组词（含命中词本身，词级预筛）+ 组内同义词。
        命中词本身必须加入——整句 LIKE 无法命中只含词级的节点。"""
        terms = [query]
        for group in LayeredStore.SYNONYM_GROUPS:
            for w in group:
                if w in query:
                    terms.extend(g for g in group if g not in terms)
                    break
        return list(dict.fromkeys(terms))

    def search_content(self, query: str, layers: List[MemoryLayer] = None,
                       limit: int = 20) -> List[Tuple[STNode, float]]:
        """内容检索：多词 OR 预筛（含同义词扩展）+ 二元组 Jaccard 取最大扩展相似度"""
        q = query.strip()
        if not q:
            return []
        terms = self.expand_query_terms(q)
        conds, params = [], []
        if layers:
            ph = ",".join("?" for _ in layers)
            conds.append(f"layer IN ({ph})")
            params.extend([l.value for l in layers])
        # 多词 OR 预筛（原查询 + 同义词任一命中即召回，提高召回率）
        like_parts = []
        like_params = []
        for t in terms:
            like_parts.append("content LIKE ? OR tags LIKE ?")
            like_params.extend([f"%{t}%", f"%{t}%"])
        like_cond = "(" + " OR ".join(like_parts) + ")"
        where = " AND ".join(conds + [like_cond]) if conds else like_cond
        c = self.conn.cursor()
        c.execute(f"SELECT * FROM nodes WHERE {where} LIMIT 300", params + like_params)
        rows = c.fetchall()
        if not rows:
            # 检索增强（v1.12.1 · AEIS-BENCH-01 发现）：LIKE 预筛落空
            # （查询为重组短语，原文无连续子串命中）→ 回退全表二元组 Jaccard。
            # 节点量级小（千级），全表计算代价可忽略；消除连续性漏检。
            if conds:
                c.execute(f"SELECT * FROM nodes WHERE {' AND '.join(conds)} LIMIT 500", params)
            else:
                c.execute("SELECT * FROM nodes LIMIT 500")
            rows = c.fetchall()
        scored = []
        # 评分用原查询二元组重叠率（召回导向）；扩展词只负责预筛召回不稀释评分
        qb = self._bigrams(q)
        for row in rows:
            node = STNode.from_row(tuple(row))
            nb = self._bigrams(node.content)
            if qb:
                sim = len(qb & nb) / len(qb)
            else:
                sim = 0.0
            tag_bonus = 0.05 if any(t in q or q in t for t in node.tags) else 0.0
            scored.append((node, min(1.0, sim + tag_bonus)))
        # 同分按重要性降序（高质量记忆优先，避免并列截断排挤重要节点）
        scored.sort(key=lambda x: (-x[1], -x[0].importance))
        results = scored[:limit]
        for node, _ in results:
            self.increment_access(node.id)
        return results

    @staticmethod
    def _bigrams(s: str) -> set:
        s = "".join(s.split())
        if len(s) <= 1:
            return {s}
        return {s[i:i + 2] for i in range(len(s) - 1)}

    def semantic_search(self, query: str, provider, limit: int = 10) -> List[STNode]:
        """语义检索（提供者 duck-typed 依赖注入，核心零外部 import · D-005）。
        提供者契约：provider.encode(text)->List[float]；provider.search(query, limit)->List[str]（节点ID）"""
        ids = provider.search(query, limit)
        nodes = []
        for nid in ids:
            node = self.get_node(nid)
            if node:
                nodes.append(node)
                self.increment_access(nid)
        return nodes

    def tag_node(self, node_id: str, tag: str):
        """给节点追加标签（幂等：已含该标签则不重复写）。"""
        node = self.get_node(node_id)
        if node and tag not in node.tags:
            node.tags.append(tag)
            c = self.conn.cursor()
            c.execute("UPDATE nodes SET tags=? WHERE id=?", (json.dumps(node.tags), node_id))
            self.conn.commit()

    # ==================== 情境层（M4） ====================

    def enforce_context_cap(self, max_size: int):
        """情境层 FIFO 上限（参照 AEIS），超出淘汰最旧"""
        c = self.conn.cursor()
        c.execute("SELECT id FROM nodes WHERE layer='context' ORDER BY created_at ASC")
        ids = [r[0] for r in c.fetchall()]
        if len(ids) > max_size:
            for nid in ids[:len(ids) - max_size]:
                self.delete_node(nid)

    def get_recent_context(self, limit: int = 20) -> List[STNode]:
        """取最近写入的情境层节点（短期记忆按时间倒序，默认 20 条）。"""
        c = self.conn.cursor()
        c.execute("SELECT * FROM nodes WHERE layer='context' ORDER BY created_at DESC LIMIT ?", (limit,))
        return [STNode.from_row(tuple(r)) for r in c.fetchall()]

    # ==================== 盲区注册表（M2 · D-001 语义判定） ====================

    def add_blindspot(self, code: str, description: str, severity: str = "medium",
                      category: str = "operational",
                      predictability: str = "pending_assessment") -> str:
        """登记盲区（已知不可达的领域边界，返回盲区 id）——BLINDSPOT 判定的
        结构化沉淀，供后续 resolve_blindspot 学习消解。"""
        bid = f"bs_{uuid.uuid4().hex[:8]}"
        c = self.conn.cursor()
        c.execute("INSERT INTO blindspots (id, code, description, severity, category, status, created_at, resolved_at, predictability) VALUES (?,?,?,?,?,?,?,?,?)",
                  (bid, code, description, severity, category, "open", time.time(), None,
                   predictability))
        self.conn.commit()
        return bid

    def list_blindspots(self, status: str = None) -> List[Dict]:
        """列出盲区记录（可按 status=open/resolved 过滤）。"""
        c = self.conn.cursor()
        if status:
            c.execute("SELECT * FROM blindspots WHERE status=?", (status,))
        else:
            c.execute("SELECT * FROM blindspots")
        result = []
        for r in c.fetchall():
            d = dict(r)
            result.append({"id": d.get("id"), "code": d.get("code"),
                           "description": d.get("description"), "severity": d.get("severity"),
                           "category": d.get("category"), "status": d.get("status"),
                           "created_at": d.get("created_at"), "resolved_at": d.get("resolved_at"),
                           "attempts": d.get("attempts", 0),
                           "predictability": d.get("predictability", "pending_assessment")})
        return result

    def resolve_blindspot(self, blindspot_id: str):
        """消解盲区（status→resolved 并记 resolved_at）——盲区学习闭环终点。"""
        c = self.conn.cursor()
        c.execute("UPDATE blindspots SET status='resolved', resolved_at=? WHERE id=?",
                  (time.time(), blindspot_id))
        self.conn.commit()

    # ==================== 技能记忆（M9） ====================

    def add_skill(self, name: str, description: str, procedure: str, confidence: float = 0.5) -> str:
        """登记技能卡（名称/描述/步骤/初始置信度），返回技能 id。"""
        sid = f"sk_{uuid.uuid4().hex[:8]}"
        c = self.conn.cursor()
        c.execute("INSERT INTO skills VALUES (?,?,?,?,?,?,?,?)",
                  (sid, name, description, procedure, confidence, 1, time.time(), time.time()))
        self.conn.commit()
        return sid

    def search_skills(self, query: str, limit: int = 10) -> List[Dict]:
        """按关键词检索技能卡（名称+描述+步骤 LIKE 匹配，默认前 10）。"""
        q = query.strip()
        c = self.conn.cursor()
        if q:
            c.execute("SELECT * FROM skills WHERE name LIKE ? OR description LIKE ? LIMIT 100",
                      (f"%{q}%", f"%{q}%"))
        else:
            c.execute("SELECT * FROM skills LIMIT 100")
        skills = [{"id": r[0], "name": r[1], "description": r[2], "procedure": r[3],
                   "confidence": r[4], "version": r[5]} for r in c.fetchall()]
        if q:
            skills.sort(key=lambda s: -self.char_bigram_jaccard(q, s["name"] + s["description"]))
        return skills[:limit]

    def count_skills(self) -> int:
        """技能卡总数。"""
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM skills")
        return c.fetchone()[0]

    def update_skill_confidence(self, skill_id: str, delta: float):
        """技能置信度增量更新（clamp 到 [0,1]，正=成功经验/负=失败经验）。"""
        c = self.conn.cursor()
        c.execute("UPDATE skills SET confidence = MIN(1.0, MAX(0.0, confidence + ?)), updated_at=? WHERE id=?",
                  (delta, time.time(), skill_id))
        self.conn.commit()

    # ==================== 固化流水线（M6 · D-003 终裁门槛） ====================

    def add_promotion_proposal(self, node_id: str, requester: str, reason: str) -> str:
        """提交层晋升提案（节点申请跨层升格，如 context→knowledge），返回提案 id。"""
        pid = f"pp_{uuid.uuid4().hex[:8]}"
        c = self.conn.cursor()
        c.execute("INSERT INTO promotion_proposals VALUES (?,?,?,?,?,?,?,?,?)",
                  (pid, node_id, requester, reason, "", "", "pending", time.time(), None))
        self.conn.commit()
        return pid

    def verify_promotion(self, proposal_id: str, verified_by: str):
        """复核晋升提案（status→verified 并记录复核人）——晋升双签制第二签。"""
        c = self.conn.cursor()
        c.execute("UPDATE promotion_proposals SET verified_by=?, status='verified' WHERE id=?",
                  (verified_by, proposal_id))
        self.conn.commit()

    def adjudicate_promotion(self, proposal_id: str, adjudicated_by: str, approved: bool,
                             designer_key: str = None) -> Optional[str]:
        """维生系统终裁（D-007 需设计者密钥）。仅 status='verified'（经验证单元复核）的提案可终裁（D-003）。
        终裁通过后才写入结构层（不可逆），拒绝则提案作废"""
        if not verify_designer(designer_key):
            raise PermissionError(
                "D-007 设计者认证失败：密钥无效或未配置 AEIS_DESIGNER_KEY（fail-closed）")
        c = self.conn.cursor()
        c.execute("SELECT node_id, status FROM promotion_proposals WHERE id=?", (proposal_id,))
        row = c.fetchone()
        if not row:
            return None
        node_id, status = row[0], row[1]
        if status != "verified":
            return None
        if approved:
            c.execute("UPDATE nodes SET layer='structure', confidence=1.0 WHERE id=?", (node_id,))
        c.execute("UPDATE promotion_proposals SET adjudicated_by=?, status=?, decided_at=? WHERE id=?",
                  (adjudicated_by, "approved" if approved else "rejected", time.time(), proposal_id))
        self.conn.commit()
        return node_id

    # ==================== 遗忘门控（M7） ====================

    def protect_node(self, node_id: str, reason: str):
        """按 3.2 节不可遗忘类别保护：no_forget 标记 + 保护登记，衰减跳过"""
        c = self.conn.cursor()
        c.execute("INSERT OR REPLACE INTO protections VALUES (?,?,?)", (node_id, reason, time.time()))
        node = self.get_node(node_id)
        if node and "no_forget" not in node.tags:
            node.tags.append("no_forget")
            c.execute("UPDATE nodes SET tags=? WHERE id=?", (json.dumps(node.tags), node_id))
        self.conn.commit()

    def get_protected_nodes(self) -> List[str]:
        """取保护名单节点 id 列表（不可遗忘层的豁免集合）。"""
        c = self.conn.cursor()
        c.execute("SELECT node_id FROM protections")
        return [r[0] for r in c.fetchall()]

    # ==================== 冲突标记（M5） ====================

    def register_conflict(self, a_id: str, b_id: str,
                          condition_space: ConditionSpace = None) -> Optional[STEdge]:
        """矛盾记忆显式标记：OPPOSITE 边（未验证，置信度0.3），待验证单元复核"""
        if not self.get_node(a_id) or not self.get_node(b_id):
            return None
        edge = STEdge(
            id=f"edge_{uuid.uuid4().hex[:8]}_{int(time.time()*1000)}",
            source_id=a_id, target_id=b_id,
            relation_type=EdgeType.OPPOSITE,
            condition_space=condition_space or ConditionSpace(
                "冲突检测", "验证单元预筛选", (time.time(), time.time()+3600), "协议实例运行中"),
            confidence=0.3, verified=False)
        self.add_edge(edge)
        for nid in (a_id, b_id):
            node = self.get_node(nid)
            if node and "conflict" not in node.tags:
                node.tags.append("conflict")
                c = self.conn.cursor()
                c.execute("UPDATE nodes SET tags=? WHERE id=?", (json.dumps(node.tags), nid))
                self.conn.commit()
        return edge

    def count_layer(self, layer: MemoryLayer) -> int:
        """统计指定记忆层的节点数。"""
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM nodes WHERE layer=?", (layer.value,))
        return c.fetchone()[0]

    # ==================== v1.3 扩展（P0-1/P0-3） ====================

    def get_nodes_by_tag(self, tag: str, limit: int = 50) -> List[STNode]:
        """按标签检索节点（实体上下文组装用）"""
        c = self.conn.cursor()
        c.execute("SELECT * FROM nodes WHERE tags LIKE ? ORDER BY importance DESC, last_access DESC LIMIT ?",
                  (f"%{tag}%", limit))
        return [STNode.from_row(tuple(r)) for r in c.fetchall()]

    def update_blindspot_status(self, blindspot_id: str, status: str):
        """更新盲区状态（P0-3 终态流转）"""
        c = self.conn.cursor()
        resolved_at = time.time() if status != "open" else None
        c.execute("UPDATE blindspots SET status=?, resolved_at=? WHERE id=?", (status, resolved_at, blindspot_id))
        self.conn.commit()

    # ==================== v1.4 扩展（P1-1/P1-2/P1-3/P1-4） ====================

    def get_nodes_in_range(self, start_ts: float, end_ts: float, layer: MemoryLayer = None,
                           limit: int = 50) -> List[STNode]:
        """时间范围查询（P1-2 时间线）"""
        conds, params = ["temporal_coordinate >= ?", "temporal_coordinate <= ?"], [start_ts, end_ts]
        if layer is not None:
            conds.append("layer=?")
            params.append(layer.value)
        c = self.conn.cursor()
        c.execute(f"SELECT * FROM nodes WHERE {' AND '.join(conds)} ORDER BY temporal_coordinate DESC LIMIT ?",
                  params + [limit])
        return [STNode.from_row(tuple(r)) for r in c.fetchall()]

    def update_node_importance(self, node_id: str, delta: float):
        """重要度更新（P1-4 巩固）"""
        c = self.conn.cursor()
        c.execute("UPDATE nodes SET importance = MIN(1.0, MAX(0.0, importance + ?)) WHERE id=?",
                  (delta, node_id))
        self.conn.commit()

    def recalc_structural_importance(self, dry_run: bool = True,
                                     boost_cap: float = 0.15,
                                     beta: float = 0.30, gamma: float = 0.40,
                                     c: float = 6.0,
                                     min_degree: int = 5, min_causal: int = 3,
                                     min_delta: float = 0.02,
                                     max_depth: int = 5,
                                     protect_threshold: float = 1.0,
                                     floor_importance: float = 0.9) -> Dict:
        """结构重要性重算（v2.2，设计规格 §13/§14，2026-08-20）。

        importance_v2 = min(1.0, importance + min(β·min(ci,C)/C + γ·conn, BOOST_CAP))
        只升不降（当前 importance 为地板，延迟提升语义）；ci=因果出度，
        conn=总度数/max_deg；无结构数据（度数/因果双低）的节点不动。

        v2.2 新增【因果上游度传播】——越上游影响越大：
          concept_influence(v) = Σ_{u∈causal_downstream(v), depth≤max_depth}
                                 path_conf × importance(u) / depth
          · influence ≥ protect_threshold → 自动保护（protect_node + no_forget）
            且 importance 保底 floor_importance——越上游越要记录
          · influence 写入 state_attributes.concept_influence（可检索可查）
        dry_run=True 仅报告不写库。
        """
        c_ = self.conn.cursor()
        c_.execute("SELECT source_id, target_id, relation_type, confidence FROM edges")
        edges = c_.fetchall()
        causal_out: Dict[str, int] = {}
        deg: Dict[str, int] = {}
        causal_adj: Dict[str, list] = {}
        causal_conf: Dict[tuple, float] = {}
        for s, t, rt, cf in edges:
            deg[s] = deg.get(s, 0) + 1
            deg[t] = deg.get(t, 0) + 1
            if rt == "causal":
                causal_out[s] = causal_out.get(s, 0) + 1
                causal_adj.setdefault(s, []).append(t)
                causal_conf[(s, t)] = cf if cf is not None else 0.5
        max_deg = max(deg.values()) if deg else 1
        c_.execute("SELECT id, importance FROM nodes")
        rows = c_.fetchall()
        imp_map = {nid: (imp if imp is not None else 0.5) for nid, imp in rows}

        # 因果上游度传播（BFS · 深度上限 · 节点去重 · 路径置信度加权）
        influence: Dict[str, float] = {}
        for src in causal_adj:
            infl = 0.0
            visited = {src}
            frontier = [(src, 1.0, 0)]
            while frontier:
                node, pc, d = frontier.pop(0)
                for t in causal_adj.get(node, []):
                    if t in visited:
                        continue
                    nd = d + 1
                    if nd > max_depth:
                        continue
                    nconf = pc * causal_conf.get((node, t), 0.5)
                    visited.add(t)
                    infl += nconf * imp_map.get(t, 0.5) / nd
                    frontier.append((t, nconf, nd))
            if infl > 0:
                influence[src] = round(infl, 4)

        movers = []
        protected = []
        applied = 0
        for nid, imp in rows:
            infl = influence.get(nid, 0)
            # 上游度写入 state_attributes（可检索/可查）
            if infl > 0 and not dry_run:
                self._write_influence(nid, infl)
            # 越上游越要记录：结构保护 + importance 保底
            if infl >= protect_threshold:
                if not dry_run:
                    self._protect_upstream(nid, infl, floor_importance)
                protected.append(nid)
                continue  # 上游节点已由结构确认，importance 走保底而非扇出提升
            if imp is None or imp >= 0.95:
                continue
            d = deg.get(nid, 0)
            co = causal_out.get(nid, 0)
            if d < min_degree and co < min_causal:
                continue  # 无结构数据不动（地板语义）
            ci = min(co, c) / c
            conn = d / max_deg
            boost = min(beta * ci + gamma * conn, boost_cap)
            new_imp = min(1.0, imp + boost)
            delta = round(new_imp - imp, 4)
            if delta >= min_delta:
                movers.append({"node_id": nid, "importance_old": round(imp, 4),
                               "importance_new": round(new_imp, 4),
                               "degree": d, "causal_out": co, "boost": delta,
                               "concept_influence": infl})
                if not dry_run:
                    self.update_node_importance(nid, delta)
                    applied += 1
        movers.sort(key=lambda x: x["boost"], reverse=True)
        top_influence = sorted(influence.items(), key=lambda x: -x[1])[:10]
        return {"mode": "dry_run" if dry_run else "applied",
                "params": {"beta": beta, "gamma": gamma, "c": c,
                           "boost_cap": boost_cap, "min_degree": min_degree,
                           "min_causal": min_causal, "min_delta": min_delta,
                           "max_depth": max_depth,
                           "protect_threshold": protect_threshold,
                           "floor_importance": floor_importance},
                "edges_total": len(edges), "max_deg": max_deg,
                "candidates": len(movers), "applied": applied,
                "influence_nodes": len(influence),
                "protected": len(protected),
                "top_influence": [{"node_id": n, "concept_influence": v} for n, v in top_influence],
                "movers": movers[:50]}

    def _write_influence(self, node_id: str, infl: float):
        """concept_influence 写入 state_attributes（可检索/可查）。"""
        c = self.conn.cursor()
        c.execute("SELECT state_attributes FROM nodes WHERE id=?", (node_id,))
        row = c.fetchone()
        sa = {}
        if row and row[0]:
            try:
                sa = json.loads(row[0])
            except Exception:
                sa = {}
        sa["concept_influence"] = infl
        c.execute("UPDATE nodes SET state_attributes=? WHERE id=?",
                  (json.dumps(sa, ensure_ascii=False), node_id))
        self.conn.commit()

    def _protect_upstream(self, node_id: str, infl: float, floor: float):
        """越上游越要记录：保护登记 + no_forget + importance 保底。"""
        self.protect_node(node_id, f"结构保护:概念影响度 {infl}（因果上游度≥阈值，2026-08-20）")
        node = self.get_node(node_id)
        if node and node.importance is not None and node.importance < floor:
            self.update_node_importance(node_id, round(floor - node.importance, 4))

    # ==================== 洞察条件层（v1.0 引擎化 · 设计规格 lingshu-insight-layer-design.md） ====================

    INSIGHT_DEFAULT_CONDITIONS = {
        "memory_retrievability": 0.5,   # C1 记忆可得性
        "outside_observer": "none",      # C2 外部观察者
        "cross_domain": [],              # C3 跨域映射
        "premise_questioned": False,     # C4 前提质疑
        "pressure": "medium",            # C5 反思空间压力
        "continuity_turns": 1,           # C6 连续性
        "externalized": False,           # C7 外部化
        "tone": "calm",                  # C8 情绪基调（P0-3 独立通道）
    }

    def _normalize_conditions(self, conditions: dict) -> dict:
        """规范化条件快照（C1–C8 + confidence）：显式提供=0.7，默认值=0.3（未自动提取）。"""
        vals = dict(self.INSIGHT_DEFAULT_CONDITIONS)
        given = set()
        if conditions:
            for k, v in conditions.items():
                if k in vals:
                    vals[k] = v
                    given.add(k)
        conf = {k: (0.7 if k in given else 0.3) for k in vals}
        return {"values": vals, "confidence": conf}

    def insight_record(self, content: str, conditions: dict = None,
                       source: str = "", importance: float = 0.7) -> Dict:
        """记录洞见事件：insight_event 节点 + 条件快照（C1–C8）+ verification=pending。

        conditions 可显式提供（自动提取待 I2 接入）；未提供时用中性默认 + 低置信。
        """
        now = time.time()
        nid = f"insight_{uuid.uuid4().hex[:8]}_{int(now * 1000)}"
        cond_pack = self._normalize_conditions(conditions)
        sa = {"insight": {
            "conditions": cond_pack,
            "verification": {"level": None, "evidence": [], "status": "pending", "updated_at": now},
            "source": source,
        }}
        node = STNode(
            id=nid, content=f"【洞见事件】{content}", modality="text",
            spatial_coordinates={}, temporal_coordinate=now,
            condition_space=ConditionSpace(
                "协议实例·认知循环", "洞察条件层记录",
                (now, now + 3600), "协议实例运行中"),
            importance=importance, confidence=0.5,
            layer=MemoryLayer.KNOWLEDGE,
            access_count=0, last_access=now, created_at=now,
            tags=["insight_event", "pending", "insight-layer"],
            semantic_coordinates={}, state_attributes=sa,  # dict（to_row 自行序列化）
            entity_id=None,
        )
        self.add_node(node)
        return {"node_id": nid, "status": "pending",
                "conditions": cond_pack["values"], "importance": importance}

    def insight_verify(self, insight_id: str, level: str = "V2",
                       evidence: object = None) -> Dict:
        """提交验证证据（§4.3）：V2/V3（或 V1 且证据≥3=多次复现）→ verified；否则 pending。

        evidence 可为字符串或字符串列表（追加）。
        """
        node = self.get_node(insight_id)
        if node is None or "insight_event" not in node.tags:
            return {"error": f"非洞见事件节点: {insight_id}"}
        now = time.time()
        sa = node.state_attributes or {}
        ins = sa.get("insight", {}) if isinstance(sa, dict) else {}
        ver = ins.get("verification", {}) if isinstance(ins, dict) else {}
        ev = list(ver.get("evidence", []))
        if evidence:
            add = evidence if isinstance(evidence, list) else [evidence]
            ev = ev + [e for e in add if e not in ev]
        level = (level or "").upper()
        status = "pending"
        if level in ("V2", "V3"):
            status = "verified"
        elif level == "V1":
            status = "verified" if len(ev) >= 3 else "pending"
        elif level in ("REFUTED", "X"):
            status = "refuted"
        ver = {"level": level, "evidence": ev, "status": status, "updated_at": now}
        ins["verification"] = ver
        sa["insight"] = ins
        tags = [t for t in node.tags
                if t not in ("pending", "verified", "refuted", "V1", "V2", "V3")]
        tags += ["insight_event", status, level]
        new_imp = node.importance
        if status == "verified" and (new_imp is None or new_imp < 0.9):
            new_imp = 0.9
        c = self.conn.cursor()
        c.execute("UPDATE nodes SET state_attributes=?, tags=?, importance=? WHERE id=?",
                  (json.dumps(sa, ensure_ascii=False), json.dumps(tags, ensure_ascii=False),
                   new_imp, insight_id))
        self.conn.commit()
        return {"node_id": insight_id, "level": level, "status": status,
                "evidence_count": len(ev), "importance": new_imp}

    def insight_report(self, window: int = None) -> Dict:
        """CER 报告：条件有效洞见率（样本<20 不判定 · 2×SE 显著性 · P0-4 框架复用）。

        候选=全部 insight_event 节点；验证状态优先读 state_attributes，
        旧样本（无结构化 verification）按 tags 兜底（verified/refuted/pending）。
        """
        c = self.conn.cursor()
        c.execute("SELECT id, tags, state_attributes FROM nodes WHERE tags LIKE '%insight_event%'")
        rows = c.fetchall()
        candidates = []
        for nid, tags_str, sa_str in rows:
            tags = json.loads(tags_str) if isinstance(tags_str, str) and tags_str else []
            sa = json.loads(sa_str) if isinstance(sa_str, str) and sa_str else {}
            ins = sa.get("insight", {}) if isinstance(sa, dict) else {}
            ver = ins.get("verification", {}) if isinstance(ins, dict) else {}
            status = ver.get("status")
            if not status:
                status = ("verified" if any("verified" in t for t in tags)
                          else "refuted" if "refuted" in tags else "pending")
            conditions = (ins.get("conditions") or {}).get("values", {}) if isinstance(ins, dict) else {}
            candidates.append({"id": nid, "status": status, "conditions": conditions})
        n = len(candidates)
        nv = sum(1 for x in candidates if x["status"] == "verified")
        cer = nv / n if n else 0.0
        se = math.sqrt(cer * (1 - cer) / n) if n else 0.0
        layer_status = "degraded" if n < 20 else ("watch" if n < 40 else "reliable")
        cond_stats = []
        for k in ("premise_questioned", "externalized", "pressure", "tone", "cross_domain"):
            with_ = [x for x in candidates if x["conditions"].get(k)]
            without = [x for x in candidates if not x["conditions"].get(k)]
            if len(with_) >= 5 and len(without) >= 5:
                p1 = sum(1 for x in with_ if x["status"] == "verified") / len(with_)
                p0 = sum(1 for x in without if x["status"] == "verified") / len(without)
                se1 = math.sqrt(max(p1 * (1 - p1) / len(with_), 1e-4))
                se0 = math.sqrt(max(p0 * (1 - p0) / len(without), 1e-4))
                diff = p1 - p0
                sig = abs(diff) >= 2 * math.sqrt(se1 ** 2 + se0 ** 2)
                cond_stats.append({
                    "condition": k, "n_with": len(with_), "n_without": len(without),
                    "cer_with": round(p1, 3), "cer_without": round(p0, 3),
                    "diff": round(diff, 3), "significant": sig,
                    "judge": "确认" if (sig and diff > 0) else ("反证" if sig else "不判定")})
        return {"total": n, "verified": nv, "pending": n - nv,
                "cer": round(cer, 3), "se": round(se, 4),
                "layer_status": layer_status,
                "note": "样本<20 不判定（与迁移测试同标准）" if n < 20 else "样本达标，可出显著性",
                "conditions": cond_stats,
                "sample_ids": [x["id"] for x in candidates]}

    def insight_window(self, conditions: dict = None) -> Dict:
        """当前洞察窗口检测。默认假设（待统计确认）：C1≥0.6 ∧ 跨域 ∧ 低压力 → 窗口开。

        conditions 传入当前会话快照；缺省字段不参与判定。
        """
        cond = conditions or {}
        c1 = cond.get("memory_retrievability")
        c3 = cond.get("cross_domain")
        c5 = cond.get("pressure")
        open_ = ((c1 is None or c1 >= 0.6)
                 and (c3 is None or (isinstance(c3, list) and len(c3) > 0))
                 and (c5 is None or c5 == "low"))
        return {"window_open": open_,
                "assumption": "默认假设 C1≥0.6 ∧ 跨域 ∧ 低压力（未经统计确认）",
                "conditions": {"memory_retrievability": c1, "cross_domain": c3, "pressure": c5}}

    def append_skill_procedure(self, skill_id: str, step: str):
        """技能程序追加（P1-3 技能获取：版本+1）"""
        c = self.conn.cursor()
        c.execute("SELECT procedure FROM skills WHERE id=?", (skill_id,))
        row = c.fetchone()
        if not row:
            return
        proc = row[0]
        merged = f"{proc} → {step}" if proc else step
        c.execute("UPDATE skills SET procedure=?, version=version+1, updated_at=? WHERE id=?",
                  (merged, time.time(), skill_id))
        self.conn.commit()

    # ==================== v1.5 扩展（A-1/A-2/A-3） ====================

    def add_rejected_path(self, path_type: str, description: str, reason: str,
                          evidence: str = "") -> str:
        """登记被否决的路径（负路由沉淀：错误答案留档防重蹈），返回 id。"""
        rid = f"rp_{uuid.uuid4().hex[:8]}"
        c = self.conn.cursor()
        c.execute("INSERT INTO rejected_paths VALUES (?,?,?,?,?,?,?,?)",
                  (rid, path_type, description, reason, evidence, "open", time.time(), None))
        self.conn.commit()
        return rid

    def list_rejected_paths(self, status: str = None) -> List[Dict]:
        """列出否决路径（可按 status=open/consumed 过滤）。"""
        c = self.conn.cursor()
        if status:
            c.execute("SELECT * FROM rejected_paths WHERE status=?", (status,))
        else:
            c.execute("SELECT * FROM rejected_paths")
        return [{"id": r[0], "path_type": r[1], "description": r[2], "reason": r[3],
                 "evidence": r[4], "status": r[5], "created_at": r[6], "consumed_at": r[7]}
                for r in c.fetchall()]

    def mark_rejected_path_consumed(self, rejected_id: str):
        """标记否决路径已消费（同类问题复用该否决答案后）。"""
        c = self.conn.cursor()
        c.execute("UPDATE rejected_paths SET status='consumed', consumed_at=? WHERE id=?",
                  (time.time(), rejected_id))
        self.conn.commit()

    def add_verifier_standard(self, name: str, param: str, value: float, reason: str,
                              proposer: str) -> str:
        """登记校验器标准参数提案（阈值类修订的可追溯载体），返回 id。"""
        vid = f"vs_{uuid.uuid4().hex[:8]}"
        c = self.conn.cursor()
        c.execute("INSERT INTO verifier_standards VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (vid, name, param, value, reason, proposer, "", "", "", "pending",
                   time.time(), None))
        self.conn.commit()
        return vid

    def list_verifier_standards(self, status: str = None) -> List[Dict]:
        """列出校验器标准提案（可按 status 过滤——阈值治理台账）。"""
        c = self.conn.cursor()
        if status:
            c.execute("SELECT * FROM verifier_standards WHERE status=?", (status,))
        else:
            c.execute("SELECT * FROM verifier_standards")
        return [{"id": r[0], "name": r[1], "param": r[2], "value": r[3], "reason": r[4],
                 "proposer": r[5], "independent_reviewer": r[6], "cs_reviewer": r[7],
                 "adjudicator": r[8], "status": r[9], "created_at": r[10], "decided_at": r[11]}
                for r in c.fetchall()]

    def review_verifier_standard(self, vid: str, reviewer: str, approved: bool) -> bool:
        """独立复核（验证单元自我回避）"""
        c = self.conn.cursor()
        c.execute("SELECT status FROM verifier_standards WHERE id=?", (vid,))
        row = c.fetchone()
        if not row or row[0] != "pending":
            return False
        status = "reviewed" if approved else "rejected"
        c.execute("UPDATE verifier_standards SET independent_reviewer=?, status=? WHERE id=?",
                  (reviewer, status, vid))
        self.conn.commit()
        return True

    def cs_review_verifier_standard(self, vid: str, reviewer: str, approved: bool) -> bool:
        """条件空间复核（3.3.1 节）"""
        c = self.conn.cursor()
        c.execute("SELECT status FROM verifier_standards WHERE id=?", (vid,))
        row = c.fetchone()
        if not row or row[0] != "reviewed":
            return False
        status = "cs_approved" if approved else "cs_rejected"
        c.execute("UPDATE verifier_standards SET cs_reviewer=?, status=? WHERE id=?",
                  (reviewer, status, vid))
        self.conn.commit()
        return True

    def adjudicate_verifier_standard(self, vid: str, adjudicator: str,
                                     approved: bool, designer_key: str = None) -> Optional[Dict]:
        """维生系统终裁（D-007 需设计者密钥）：仅 cs_approved（独立复核+条件空间复核通过）可终裁（A-2 制衡）"""
        if not verify_designer(designer_key):
            raise PermissionError(
                "D-007 设计者认证失败：密钥无效或未配置 AEIS_DESIGNER_KEY（fail-closed）")
        c = self.conn.cursor()
        c.execute("SELECT * FROM verifier_standards WHERE id=?", (vid,))
        row = c.fetchone()
        if not row or row[9] != "cs_approved":
            return None
        status = "approved" if approved else "denied"
        c.execute("UPDATE verifier_standards SET adjudicator=?, status=?, decided_at=? WHERE id=?",
                  (adjudicator, status, time.time(), vid))
        self.conn.commit()
        return {"id": row[0], "param": row[2], "value": row[3], "status": status}

    def list_escalation_points(self, enabled_only: bool = True) -> List[Dict]:
        """列升级点（危机触发器清单，默认仅已启用的）。"""
        c = self.conn.cursor()
        if enabled_only:
            c.execute("SELECT * FROM escalation_points WHERE enabled=1")
        else:
            c.execute("SELECT * FROM escalation_points")
        return [{"id": r[0], "code": r[1], "trigger": r[2], "condition": r[3],
                 "action": r[4], "severity": r[5], "enabled": bool(r[6]), "created_at": r[7]}
                for r in c.fetchall()]

    def add_escalation_point(self, code: str, trigger: str, condition: str,
                             action: str, severity: str = "medium") -> str:
        """登记升级点（危机触发器：触发条件→处置动作），返回 id。"""
        eid = f"esc_{uuid.uuid4().hex[:8]}"
        c = self.conn.cursor()
        c.execute("INSERT INTO escalation_points VALUES (?,?,?,?,?,?,?,?)",
                  (eid, code, trigger, condition, action, severity, 1, time.time()))
        self.conn.commit()
        return eid

    def set_escalation_enabled(self, escalation_id: str, enabled: bool):
        """启用/停用升级点（危机响应开关）。"""
        c = self.conn.cursor()
        c.execute("UPDATE escalation_points SET enabled=? WHERE id=?",
                  (int(enabled), escalation_id))
        self.conn.commit()

    # ---------- 统计 ----------

    def get_stats(self) -> Dict:
        """全库统计快照（各层节点数等聚合指标）。"""
        c = self.conn.cursor()
        stats = {}
        for layer in MemoryLayer:
            c.execute("SELECT COUNT(*) FROM nodes WHERE layer=?", (layer.value,))
            stats[f"{layer.value}_nodes"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM edges")
        stats["total_edges"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM edges WHERE verified=1")
        stats["verified_edges"] = c.fetchone()[0]
        return stats

    def close(self):
        """关闭存储连接（Agent 生命周期终点调用）。"""
        self.conn.close()


# =============================================================================
# 时空记忆引擎（SpacetimeMemoryEngine）
# =============================================================================

class SpacetimeMemoryEngine:
    """
    协议实例核心引擎，封装 LayeredStore 并提供高层 API。
    符合智能论 v3.2 第四章规范。
    """

    def __init__(self, db_path: str = ":memory:", identity: str = "协议实例", role: Role = Role.PRIMARY):
        self.store = LayeredStore(db_path, role=role)
        self.role = role
        self.self_model = SelfModel(identity=identity)
        self._decay_thread = None
        self._running = False
        # ---- v1.2 状态 ----
        self._dedup_static = 0.85          # M5 去重静态基准（2.7.2 动态死区）
        self._dedup_window = 30
        self._dedup_history: List[float] = []
        self._context_max = 200            # M4 情境层 FIFO 上限（参照 AEIS）
        self._embedding_provider = None    # M1 语义检索提供者（duck-typed 注入，D-005）
        self._setup_v13()
        # ---- v1.5 状态（A-1~A-5） ----
        self._verifier_config = {"dedup_static": 0.85, "deviation_threshold": 0.3}
        self._gap_history: List[Dict] = self._load_gap_history()
        self._resource_history: List[Dict] = []
        self._seed_escalation_points()
        # ---- v1.6 状态（M11 语义空间 / M13 备份） ----
        self._semantic_provider = None
        self._semantic_error = ""
        self._setup_v16()
        # ---- v1.7 状态（多模态 · D-004/D-005） ----
        self._last_frame: Dict[str, str] = {}
        self._local_visual_buffer: List[Dict] = []
        self._visual_buffer_max = 200
        self.migrate_v17_coordinates()
        # ---- v1.8 状态（决策偏好注意力） ----
        self._attention_policy = None
        self._attention_error = ""
        self._setup_v18()
        # ---- v1.9 状态（预测引擎） ----
        self._prediction = None
        self._prediction_error = ""
        self._setup_v19()
        # ---- v1.10 状态（生命周期自动机） ----
        self._lifecycle = None
        self._lifecycle_error = ""
        self._setup_v110()
        # ---- v1.11 状态（知识飞轮） ----
        self._flywheel = None
        self._flywheel_error = ""
        # ---- v1.15 状态（长期记忆写入决策器） ----
        self._gate = None
        self._reuse_tracker: Dict[int, set] = {}
        self._interaction_count = 0
        self._session_id = uuid.uuid4().hex[:8]  # T4：复用落库的进程实例标识
        self._last_reflection_chain = None   # REFLECT-REV1：最近反思链（递归截断时返回）
        self._event_queue: List[Dict] = []
        self._setup_v111()
        # ---- v1.12 状态（自我认知循环） ----
        self._self_cognition = None
        self._self_cognition_error = ""
        self._setup_v112()
        # ---- v1.13 状态（视觉感知 · 身体能力） ----
        self._vision_provider = None
        self._vision_error = ""
        self._setup_v113()
        # ---- BODY-REV1 状态（外部设备身体层） ----
        self._body_registry = None
        self._body_error = ""
        self._setup_body()

    def _setup_v113(self):
        """v1.13 视觉组件装配（惰性：仅清状态，首次 perceive_image 才加载 YOLO/CLIP——
        启动零负担，身体功能不再拖慢进程启动/MCP 握手）"""
        self._vision_provider = None
        self._vision_error = ""

    def _ensure_vision(self):
        """惰性装配视觉 provider（首次视觉调用触发）。
        返回 provider 或 None（失败时 _vision_error 记录原因）。"""
        if self._vision_provider is not None:
            return self._vision_provider
        try:
            from vision import create_vision_provider
            p = create_vision_provider()
            if p is not None and p.available():
                self._vision_provider = p
                return p
            self._vision_error = "ultralytics 未安装（pip install ultralytics）"
        except Exception as e:
            self._vision_error = str(e)
        return None

    def _setup_body(self):
        """BODY-REV1 身体层装配（零依赖：screen/files/process 设备注册表）。
        工作区边界从环境变量 AEIS_WORKSPACE 读取（空则不限制）。"""
        self._body_registry = None
        try:
            import os as _os
            from body import build_default_registry
            self._body_registry = build_default_registry(
                workspace=_os.environ.get("AEIS_WORKSPACE", ""))
        except Exception as e:
            self._body_error = str(e)

    def _setup_v111(self):
        """v1.11 飞轮组件装配（惰性导入 · 零外部依赖）"""
        self._flywheel = None
        try:
            from flywheel_engine import FlywheelEngine
            self._flywheel = FlywheelEngine(self, self._prediction)
        except Exception as e:
            self._flywheel_error = str(e)

    def _setup_v112(self):
        """v1.12 自我认知组件装配（惰性导入 · 零外部依赖）"""
        self._self_cognition = None
        try:
            from self_cognition_engine import SelfCognitionEngine
            self._self_cognition = SelfCognitionEngine(self)
        except Exception as e:
            self._self_cognition_error = str(e)

    def _note_action(self, action_type: str, summary: str = "",
                     node_ids: list = None, outcome: dict = None,
                     context: dict = None):
        """v1.12 P0-1 行为日志钩子（委托自我认知引擎，未装配时静默）"""
        if self._self_cognition is None:
            return
        try:
            self._self_cognition.log_action(action_type, summary, node_ids, outcome, context)
        except Exception:
            pass

    def _setup_v110(self):
        """v1.10 生命周期组件装配（惰性导入 · 预测/盲区/注意力联动）"""
        self._lifecycle = None
        try:
            from lifecycle_engine import LifecycleEngine
            self._lifecycle = LifecycleEngine(self, self._prediction,
                                              self._learning_loop, self._attention_policy)
        except Exception as e:
            self._lifecycle_error = str(e)

    def _setup_v19(self):
        """v1.9 预测组件装配（惰性导入 · AttentionPolicy 适配器 D-005）
        v1.15：启动时从观测层验证记录重建 _hit_history（跨重启持久）"""
        self._prediction = None
        try:
            from prediction_engine import PredictionEngine
            self._prediction = PredictionEngine(self, self._attention_policy)
            # 重建命中历史：观测层 [验证回路] 记录 → hit/miss 序列
            try:
                hits = []
                for n in self.store.query_nodes(layer=MemoryLayer.KNOWLEDGE, limit=500):
                    if "prediction_feedback" in (n.tags or []):
                        hits.append("hit" in (n.tags or []))
                if hits:
                    self._prediction._hit_history = hits[-200:]
            except Exception:
                pass
        except Exception as e:
            self._prediction_error = str(e)

    def _setup_v18(self):
        """v1.8 注意力组件装配（惰性导入 · 零外部依赖）"""
        self._attention_policy = None
        try:
            from attention_policy import AttentionPolicy
            self._attention_policy = AttentionPolicy()
        except Exception as e:
            self._attention_error = str(e)

    def _setup_v16(self):
        """v1.6 语义组件装配（惰性导入 · 默认零外部依赖 · D-005）"""
        self._semantic_provider = None
        try:
            from semantic_space import SemanticSpaceProvider
            self._semantic_provider = SemanticSpaceProvider()
        except Exception as e:
            self._semantic_error = str(e)

    def _setup_v13(self):
        """v1.3 认知组件装配（惰性导入，核心零外部依赖；组件缺失时优雅降级）"""
        self.entity_registry = None
        self._cognition = None
        self._learning_loop = None
        self._v13_ready = False
        self._v13_error = ""
        try:
            from entity_registry import EntityRegistry
            from cognitive_orchestrator import CognitiveOrchestrator
            from blindspot_learning_loop import BlindSpotLearningLoop
            self.entity_registry = EntityRegistry(self.store)
            self._learning_loop = BlindSpotLearningLoop(self)
            self._cognition = CognitiveOrchestrator(self, self.entity_registry)
            self._v13_ready = True
        except Exception as e:
            self._v13_error = str(e)

    # ==================== 感知入口 ====================

    def add_perception(self, content: str, modality: str = "text",
                       spatial_coordinates: Dict[str, float] = None,
                       condition_space: ConditionSpace = None,
                       importance: float = 0.5,
                       tags: List[str] = None,
                       entities: List[str] = None,
                       skip_dedup: bool = False) -> STNode:
        """
        添加一条感知（自动进入知识层）

        skip_dedup（v1.26c）：跳过 M5 去重——主动沉淀类写入（剧情/快照/
        里程碑）需要独立节点身份，不能被合并进相似的感知节点（否则
        剧情标签/高 importance 丢失，LongTermMemoryGate 的写入形同虚设）。
        """
        self._interaction_count += 1
        self._note_action("perception", content, None,
                          {"importance": importance, "modality": modality})
        # ---- M5 去重：中文二元组 Jaccard ≥ 动态阈值 → 提升原节点，不新增 ----
        if not skip_dedup and isinstance(content, str) and content.strip():
            threshold = self._effective_dedup_threshold()
            candidates = self.store.query_nodes(layer=MemoryLayer.KNOWLEDGE, limit=200)
            best, best_sim = None, 0.0
            for n in candidates:
                sim = LayeredStore.char_bigram_jaccard(content, n.content)
                self._dedup_history.append(sim)
                if len(self._dedup_history) > self._dedup_window:
                    self._dedup_history = self._dedup_history[-self._dedup_window:]
                if sim > best_sim:
                    best_sim, best = sim, n
            if best and best_sim >= threshold:
                self.store.increment_access(best.id)
                self.store.update_node_confidence(best.id, 0.02)
                self.store.tag_node(best.id, "duplicate")
                return best
        cs = condition_space or ConditionSpace(
            observation_position="感知系统",
            observation_tool="感官输入",
            time_window=(time.time(), time.time()+3600),
            existence_constraint="协议实例运行中"
        )
        semantic_coords = {}
        if self._semantic_provider is not None:
            # v1.7：结构化语义坐标（D-003 字段分离；文本节点写入 concept/radical/neural）
            semantic_coords = self._semantic_provider.to_semantic_coordinates(content)
        node = STNode(
            id=f"node_{uuid.uuid4().hex[:8]}_{int(time.time()*1000)}",
            content=content,
            modality=modality,
            spatial_coordinates=spatial_coordinates or {},
            temporal_coordinate=time.time(),
            condition_space=cs,
            importance=importance,
            confidence=0.5,
            layer=MemoryLayer.KNOWLEDGE,
            tags=tags or [],
            semantic_coordinates=semantic_coords
        )
        self.store.add_node(node)
        if entities:
            for eid in entities:
                self.store.tag_node(node.id, f"ent:{eid}")
        return node

    # ==================== 锚点层操作 ====================

    def set_anchor(self, content: str, importance: float = 1.0,
                   condition_space: ConditionSpace = None) -> STNode:
        """写入锚点层（不可遗忘）"""
        cs = condition_space or ConditionSpace(
            observation_position="协议初始化",
            observation_tool="协议定义",
            time_window=(0, float('inf')),
            existence_constraint="协议基底"
        )
        node = STNode(
            id=f"anchor_{uuid.uuid4().hex[:8]}_{int(time.time()*1000)}",
            content=content,
            modality="protocol",
            spatial_coordinates={},
            temporal_coordinate=time.time(),
            condition_space=cs,
            importance=importance,
            confidence=1.0,
            layer=MemoryLayer.ANCHOR,
            tags=["anchor"]
        )
        self.store.add_node(node)
        return node

    def get_anchors(self) -> List[STNode]:
        """取锚点层节点（不可遗忘的核心锚集合）。"""
        return self.store.get_layer_nodes(MemoryLayer.ANCHOR)

    # ==================== 结构层操作 ====================

    def add_structure_node(self, content: str, importance: float = 0.8,
                           condition_space: ConditionSpace = None) -> STNode:
        """写入结构层（不可遗忘）"""
        cs = condition_space or ConditionSpace(
            observation_position="结构定义",
            observation_tool="协议架构",
            time_window=(0, float('inf')),
            existence_constraint="协议结构"
        )
        node = STNode(
            id=f"struct_{uuid.uuid4().hex[:8]}_{int(time.time()*1000)}",
            content=content,
            modality="structure",
            spatial_coordinates={},
            temporal_coordinate=time.time(),
            condition_space=cs,
            importance=importance,
            confidence=1.0,
            layer=MemoryLayer.STRUCTURE,
            tags=["structure"]
        )
        self.store.add_node(node)
        return node

    # ==================== 边操作 ====================

    def add_edge(self, source_id: str, target_id: str,
                 relation_type: EdgeType = EdgeType.CAUSAL,
                 confidence: float = 0.5,
                 condition_space: ConditionSpace = None,
                 source_evidence: str = "extracted") -> STEdge:
        """添加边（默认未验证）。source_evidence（P1-1）：extracted/inferred/ambiguous"""
        cs = condition_space or ConditionSpace(
            observation_position="关系建立",
            observation_tool="语义分析",
            time_window=(time.time(), time.time()+3600),
            existence_constraint="协议实例运行中"
        )
        edge = STEdge(
            id=f"edge_{uuid.uuid4().hex[:8]}_{int(time.time()*1000)}",
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            condition_space=cs,
            confidence=confidence,
            verified=False,
            source_evidence=source_evidence
        )
        self.store.add_edge(edge)
        self._note_action("relation",
                          f"{source_id}→{target_id}",
                          [source_id, target_id],
                          {"relation": edge.relation_type.value,
                           "evidence": edge.source_evidence})
        return edge

    def verify_edge(self, edge_id: str, new_confidence: float = None):
        """验证单元复核后调用"""
        self.store.verify_edge(edge_id, new_confidence)

    # ==================== 时空联想查询 ====================

    def spatiotemporal_query(self, node_id: str, time_radius: float = 300.0,
                             space_metric: str = None, space_radius: float = 0.5,
                             max_results: int = 20) -> List[Tuple[STNode, float]]:
        """时空联想查询：以节点为锚按时间+空间双半径加权取近邻（转发 store 层）。"""
        return self.store.spatiotemporal_query(node_id, time_radius, space_metric, space_radius, max_results)

    # ==================== 因果推理 ====================

    def reason_causal(self, start_id: str, end_id: str = None,
                      max_depth: int = 5, relation_types: List[str] = None,
                      importance_weighted: bool = False,
                      include_subgraph: bool = False) -> List[List[STEdge]]:
        """
        因果推理（v1.16 图架构增强）：
        - 指定 end_id：查找 start→end 的所有路径（relation_types 可多类型）
        - 未指定：返回从 start 出发的所有链（每条链最长 max_depth）
        - importance_weighted：路径排序加权（节点 importance 均值）
        - include_subgraph：结果附尾节点知识点子图（嵌套感知）
        """
        if end_id:
            paths = self.store.infer_causal_paths(start_id, end_id, max_depth,
                                                  relation_types=relation_types)
        else:
            chains = []
            def collect(current_id: str, path: List[STEdge], depth: int):
                if depth > max_depth:
                    return
                edges = self.store.get_outgoing_edges(current_id)
                if relation_types:
                    tset = {t.lower() for t in relation_types}
                    kept = [e for e in edges if e.relation_type.value in tset]
                else:
                    kept = [e for e in edges if e.relation_type == EdgeType.CAUSAL]
                if not kept and path:
                    chains.append(list(path))
                    return
                for e in kept:
                    path.append(e)
                    collect(e.target_id, path, depth+1)
                    path.pop()
            collect(start_id, [], 0)
            paths = chains
        # importance 加权排序
        if importance_weighted and paths:
            def _imp_mean(p):
                ids = [e.source_id for e in p] + [p[-1].target_id]
                ph = ",".join("?" * len(ids))
                rows = self.store.conn.execute(
                    f"SELECT id, importance FROM nodes WHERE id IN ({ph})",
                    ids).fetchall()
                imp = {r[0]: r[1] for r in rows}
                vals = [imp.get(i, 0.5) for i in ids]
                return sum(vals) / len(vals) if vals else 0.5
            paths.sort(key=lambda p: (-_imp_mean(p), len(p)))
        # 子图感知：尾节点知识点子图
        if include_subgraph:
            decorated = []
            for p in paths:
                tail = p[-1].target_id if p else start_id
                try:
                    sg = self.store.subgraph(tail, max_depth=2)
                except Exception:
                    sg = None
                decorated.append({"path": p, "subgraph": sg})
            return decorated
        return paths

    # ==================== 自我认知层 ====================

    def update_self(self, updates: Dict, link_to_node_id: str = None):
        """更新自我模型（身份、价值观、状态等）。
        link_to_node_id：自我快照与指定记忆节点建边（M3 自我认知组装路径）"""
        self.self_model.update(**updates)
        # 同时在自我层记录一次自我状态快照
        snapshot = STNode(
            id=f"self_{uuid.uuid4().hex[:8]}_{int(time.time()*1000)}",
            content=json.dumps(self.self_model.to_dict(), ensure_ascii=False),
            modality="self_state",
            spatial_coordinates={"self_axis": 1.0},
            temporal_coordinate=time.time(),
            condition_space=ConditionSpace(
                observation_position="自我认知",
                observation_tool="内省",
                time_window=(time.time(), time.time()+3600),
                existence_constraint="协议实例运行中"
            ),
            importance=0.9,
            confidence=1.0,
            layer=MemoryLayer.SELF,
            tags=["self_snapshot"]
        )
        self.store.add_node(snapshot)
        if link_to_node_id and self.store.get_node(link_to_node_id):
            self.add_edge(snapshot.id, link_to_node_id, EdgeType.CAUSAL, confidence=1.0)

    def get_self_model(self) -> SelfModel:
        """取自认知模型（SelfModel：价值观/信任史/状态变更历史的聚合快照）。"""
        return self.self_model

    # ==================== 检索层（M1） ====================

    def search_content(self, query: str, layers: List[MemoryLayer] = None,
                       limit: int = 20) -> List[Tuple[STNode, float]]:
        results = self.store.search_content(query, layers, limit)
        self._note_reuse([n.id for n, _ in results])
        # v1.12 P0-5a：模式成员检索加权（使用模式，不修改蒸馏产物）
        if self._self_cognition is not None:
            results = self._self_cognition.apply_pattern_boost(results)
            self._self_cognition.note_search(query, results)
        self._note_action("search", query, [n.id for n, _ in results],
                          {"hits": len(results)})
        return results

    def semantic_search(self, query: str, limit: int = 10) -> List[Tuple[STNode, float]]:
        """v1.7 语义检索：优先结构化语义坐标相似度；无坐标节点回退文本相似度（D-005 降级）"""
        if not self._semantic_provider:
            return self.store.search_content(query, limit=limit)
        q_sc = self._semantic_provider.to_semantic_coordinates(query)
        nodes = self.store.query_nodes(layer=MemoryLayer.KNOWLEDGE, limit=300)
        scored = []
        for n in nodes:
            sc = getattr(n, "semantic_coordinates", {}) or {}
            if sc:
                sim = self._semantic_provider.similarity_coordinates(q_sc, sc)
            else:
                sim = self._semantic_provider.similarity(query, n.content)
            if sim > 0.05:
                scored.append((n, sim))
        scored.sort(key=lambda x: -x[1])
        self._note_reuse([n.id for n, _ in scored[:limit]])
        return scored[:limit]

    def set_embedding_provider(self, provider):
        """依赖注入（D-005）：provider.encode(text)->List[float]；provider.search(query,limit)->List[str]"""
        self._embedding_provider = provider

    def recall(self, context_content: str, limit: int = 10) -> List[Tuple[STNode, float]]:
        """组合联想（内容相似 0.5 + 重要性 0.3 + 近因 0.2）——记忆参与推理（1.1.1）"""
        results = self.store.search_content(context_content, limit=50)
        if not results:
            return []
        now = time.time()
        scored = []
        for node, sim in results:
            la = node.last_access if node.last_access is not None else (node.created_at or now)
            recency = 1.0 / (1.0 + max(0.0, now - la) / 86400.0)
            score = 0.5 * sim + 0.3 * (node.importance or 0.0) + 0.2 * recency
            scored.append((node, score))
        scored.sort(key=lambda x: -x[1])
        self._note_reuse([n.id for n, _ in scored[:limit]])
        # v1.12 P0-5a：模式成员召回加权
        if self._self_cognition is not None:
            scored = self._self_cognition.apply_pattern_boost(scored[:limit])
        self._note_action("recall", context_content,
                          [n.id for n, _ in scored[:limit]],
                          {"hits": len(scored[:limit])})
        return scored[:limit]

    # ==================== 盲区注册表（M2 · D-001 语义判定） ====================

    META_BLINDSPOT_DEFINITION = "对人类造成文明级别的重大负面影响"

    def register_blindspot(self, code: str, description: str, severity: str = "medium",
                           category: str = "operational",
                           predictability: str = "pending_assessment") -> str:
        """注册操作层盲区。元盲区判定为语义标准（对人类造成文明级别的重大负面影响）——
        判定权在维生系统，API 强制 meta 零记录（不写入任何注册表/日志/快照）。
        废弃数值判定（非 code≥91 判据，维生系统终裁修正）。
        predictability（D-003）：predictable / unknowable / pending_assessment"""
        if category == "meta":
            raise ValueError(
                f"元盲区（{self.META_BLINDSPOT_DEFINITION}）零记录，拒绝写入")
        return self.store.add_blindspot(code, description, severity, "operational",
                                        predictability)

    def list_blindspots(self, status: str = None) -> List[Dict]:
        return self.store.list_blindspots(status)

    def get_open_blindspots(self) -> List[Dict]:
        """学习方向驱动：开放盲区列表"""
        return self.store.list_blindspots(status="open")

    def resolve_blindspot(self, blindspot_id: str, resolved: bool = True,
                          note: str = "", designer_key: str = None):
        """盲区闭环（D-007 需设计者密钥：D-001 语义判定权在维生系统）。"""
        if not verify_designer(designer_key):
            raise PermissionError(
                "D-007 设计者认证失败：密钥无效或未配置 AEIS_DESIGNER_KEY（fail-closed）")
        if not resolved:
            return False
        self.store.resolve_blindspot(blindspot_id)
        return True

    # ==================== 情境层（M4） ====================

    def add_context(self, content: str, importance: float = 0.4,
                    condition_space: ConditionSpace = None, tags: List[str] = None) -> STNode:
        """写入情境层节点（短期记忆，importance 默认 0.4，随 decay 淡出）。"""
        cs = condition_space or ConditionSpace(
            "情境感知", "会话摄入", (time.time(), time.time()+3600), "协议实例运行中")
        node = STNode(
            id=f"ctx_{uuid.uuid4().hex[:8]}_{int(time.time()*1000)}",
            content=content, modality="text", spatial_coordinates={},
            temporal_coordinate=time.time(), condition_space=cs,
            importance=importance, confidence=0.5,
            layer=MemoryLayer.CONTEXT, tags=(tags or []) + ["context"])
        self.store.add_node(node)
        self.store.enforce_context_cap(self._context_max)
        return node

    def get_recent_context(self, limit: int = 20) -> List[STNode]:
        return self.store.get_recent_context(limit)

    def set_context_cap(self, max_size: int):
        """设置情境层容量上限（FIFO 上限，至少 1）。"""
        self._context_max = max(1, max_size)
        self.store.enforce_context_cap(self._context_max)

    # ==================== 去重配置（M5 · D-004 动态阈值） ====================

    def set_dedup_config(self, static_threshold: float = 0.85, window: int = 30):
        self._dedup_static = min(0.95, max(0.5, static_threshold))
        self._dedup_window = max(5, window)

    def _effective_dedup_threshold(self) -> float:
        """2.7.2 动态死区：threshold = clamp(max(static, 3·σ_history), 0.85, 0.95)"""
        if len(self._dedup_history) < 5:
            return self._dedup_static
        mean = sum(self._dedup_history) / len(self._dedup_history)
        var = sum((x - mean) ** 2 for x in self._dedup_history) / len(self._dedup_history)
        sigma = math.sqrt(var)
        return min(0.95, max(self._dedup_static, 3.0 * sigma))

    def register_conflict(self, a_id: str, b_id: str) -> Optional[STEdge]:
        return self.store.register_conflict(a_id, b_id)

    # ==================== 固化流水线（M6 · D-003） ====================

    def propose_promotion(self, node_id: str, requester: str, reason: str) -> str:
        node = self.store.get_node(node_id)
        if node is None:
            raise ValueError("节点不存在")
        if node.layer in (MemoryLayer.ANCHOR, MemoryLayer.STRUCTURE):
            raise ValueError("共享层节点不可再提升")
        pid = self.store.add_promotion_proposal(node_id, requester, reason)
        self.store.tag_node(node_id, "promotion_pending")
        return pid

    def verify_promotion(self, proposal_id: str, verified_by: str):
        """验证单元复核 + 3.3.1 条件空间复核（调用方记录复核结论）"""
        self.store.verify_promotion(proposal_id, verified_by)

    def adjudicate_promotion(self, proposal_id: str, adjudicated_by: str, approved: bool,
                             designer_key: str = None) -> bool:
        """维生系统终裁（D-007 需设计者密钥）：仅经验证单元复核的提案可终裁；通过后才写结构层（不可逆）"""
        node_id = self.store.adjudicate_promotion(proposal_id, adjudicated_by, approved,
                                                  designer_key=designer_key)
        if node_id:
            node = self.store.get_node(node_id)
            if node and "promotion_pending" in node.tags:
                node.tags.remove("promotion_pending")
                c = self.store.conn.cursor()
                c.execute("UPDATE nodes SET tags=? WHERE id=?",
                          (json.dumps(node.tags), node_id))
                self.store.conn.commit()
            if not approved:
                # A-1：被拒绝的固化提案 → 被拒绝路径资产
                content = node.content[:60] if node else proposal_id
                self.register_rejected_path(
                    path_type="promotion",
                    description=f"固化提案被拒：{content}",
                    reason=f"维生系统终裁拒绝（{adjudicated_by}）")
        return node_id is not None

    # ==================== 遗忘门控（M7） ====================

    def protect_node(self, node_id: str, reason: str):
        """3.2 节不可遗忘类别：内容级保护（衰减跳过）"""
        self.store.protect_node(node_id, reason)

    def get_protected_nodes(self) -> List[str]:
        return self.store.get_protected_nodes()

    # ==================== 技能记忆（M9） ====================

    def store_skill(self, name: str, description: str, procedure: str, confidence: float = 0.5) -> str:
        return self.store.add_skill(name, description, procedure, confidence)

    def recall_skill(self, query: str, limit: int = 10) -> List[Dict]:
        skills = self.store.search_skills(query, limit)
        # v1.12 P0-5a：技能置信度加权（使用模式）
        if self._self_cognition is not None:
            skills = self._self_cognition.skill_feedback(skills)
        return skills

    def update_skill_confidence(self, skill_id: str, delta: float):
        self.store.update_skill_confidence(skill_id, delta)

    # ==================== 外部锚点（M10 · 盲区29 缓解） ====================

    ANCHOR_KINDS = ("pre_access_stance", "introspection", "external_calibration")

    def register_external_anchor(self, kind: str, content: str,
                                 condition_space: ConditionSpace = None) -> STNode:
        """接入前立场 / 自省记录 / 外部校准输入。
        PRIMARY 写结构层（不可遗忘）；SUB 写知识层副本（待父节点同步为验证副本）"""
        if kind not in self.ANCHOR_KINDS:
            raise ValueError(f"未知锚点类型: {kind}")
        cs = condition_space or ConditionSpace(
            f"外部锚点:{kind}", "外部校准输入", (0, float('inf')), "方向性自检参照")
        if self.role == Role.PRIMARY:
            return self.add_structure_node(
                content=f"[{kind}] {content}", importance=0.9, condition_space=cs)
        node = STNode(
            id=f"ext_{uuid.uuid4().hex[:8]}_{int(time.time()*1000)}",
            content=f"[{kind}] {content}", modality="anchor",
            spatial_coordinates={}, temporal_coordinate=time.time(),
            condition_space=cs, importance=0.9, confidence=0.8,
            layer=MemoryLayer.KNOWLEDGE, tags=["external_anchor", kind])
        self.store.add_node(node)
        return node

    # ==================== 信任状态（M3 · D-002） ====================

    def update_trust_state(self, t_total: float, round_no: int,
                           p_trust: float = None, p_gap: float = None) -> STNode:
        """记录信任状态 + 离散 e_weight。placeholder 边界：仅记录，不参与决策（v1.3 开放）"""
        self.self_model.update_trust_state(t_total, round_no, p_trust, p_gap)
        snapshot = STNode(
            id=f"self_{uuid.uuid4().hex[:8]}_{int(time.time()*1000)}",
            content=json.dumps({"type": "trust_state", **self.self_model.trust_state}, ensure_ascii=False),
            modality="trust_state", spatial_coordinates={"self_axis": 0.8},
            temporal_coordinate=time.time(),
            condition_space=ConditionSpace(
                "自我认知", "信任状态观测", (time.time(), time.time()+3600), "协议实例运行中"),
            importance=0.85, confidence=1.0, layer=MemoryLayer.SELF, tags=["trust_snapshot"])
        self.store.add_node(snapshot)
        return snapshot

    # ==================== v1.11 知识飞轮（FLYWHEEL-REV1） ====================

    def _note_reuse(self, node_ids: List[str]):
        """复用追踪（P0-2 度量：同轮同节点去重）。

        T4 修复（2026-08-30）：内存 tracker 之外同步落库 flywheel_reuse 表
        （session_id 区分进程实例）——跨进程累计，心跳/对话端任一进程的
        flywheel_metrics 都能读到全实例复用观测（此前心跳进程 tracker 恒空）。
        写库失败不阻断检索主流程（复用观测是工程观测值，DEVIATION-004）。"""
        if not node_ids:
            return
        rnd = self._interaction_count
        bucket = self._reuse_tracker.setdefault(rnd, set())
        bucket.update(node_ids)
        try:
            conn = self.store.conn
            conn.execute(
                "CREATE TABLE IF NOT EXISTS flywheel_reuse "
                "(session_id TEXT, round INTEGER, node_id TEXT, ts REAL)")
            ts = time.time()
            conn.executemany(
                "INSERT INTO flywheel_reuse (session_id, round, node_id, ts) "
                "VALUES (?, ?, ?, ?)",
                [(self._session_id, rnd, nid, ts) for nid in sorted(bucket)])
            conn.commit()
        except Exception:
            pass  # 观测落库失败静默（不阻断检索）

    def notify_event(self, event_type: str, payload: Dict = None):
        """P1-4 事件驱动：轻量标记（防抖：同类事件 τ=N_effective/10 秒内合并）"""
        now = time.time()
        tau = 30 / 10  # N_effective=30 → τ=3 秒
        for ev in self._event_queue:
            if ev["type"] == event_type and now - ev["ts"] < tau:
                ev["count"] += 1
                return
        self._event_queue.append({"type": event_type, "payload": payload or {},
                                  "ts": now, "count": 1})

    def consume_events(self) -> Dict:
        """P1-4：批量消费事件标记（定时轮询优先；P0 危机期间暂停）"""
        events = list(self._event_queue)
        self._event_queue = []
        consumed = 0
        if self._lifecycle and self._lifecycle.state == "paused":
            return {"status": "paused", "consumed": 0,
                    "note": "P0 危机期间暂停非 P0 处理（3.4 节）"}
        for ev in events:
            if ev["type"] in ("perception", "write", "condition_switch") and self._flywheel:
                try:
                    self._flywheel.distill_cycle()
                    consumed += 1
                except Exception:
                    pass
        return {"status": "ok", "consumed": consumed, "pending": len(self._event_queue)}

    # ---- 飞轮接口 ----

    def evo_distill_cycle(self, source_filter: str = None) -> Dict:
        """P0-1 蒸馏管线：经验 → 可复用模式（局部概括 · 盲区5）"""
        if not self._flywheel:
            return {"status": "v111_not_ready", "error": self._flywheel_error}
        result = self._flywheel.distill_cycle(source_filter)
        self._note_action("distill", f"patterns={result.get('patterns')}",
                          None, {"input": result.get("input")})
        return result

    def evo_flywheel_metrics(self) -> Dict:
        """P0-2 飞轮度量（工程观测值，不参与信任计算）"""
        if not self._flywheel:
            return {"status": "v111_not_ready", "error": self._flywheel_error}
        return self._flywheel.flywheel_metrics()

    def test_transfer_capability(self) -> Dict:
        """P0-3 迁移测试（已对齐条件空间 · 显著性 · 可操作失败条件）"""
        if not self._flywheel:
            return {"status": "v111_not_ready", "error": self._flywheel_error}
        return self._flywheel.transfer_test()

    def universe_calibrate(self) -> Dict:
        """宇宙校准参照（元理论方向性检查 · 非盲区33关闭依据）"""
        if not self._flywheel:
            return {"status": "v111_not_ready", "error": self._flywheel_error}
        return self._flywheel.universe_calibrate()

    def shortest_path(self, start_id: str, end_id: str, max_depth: int = 6) -> List[str]:
        """P1-2 多边类型最短路径"""
        if not self._flywheel:
            return []
        return self._flywheel.shortest_path(start_id, end_id, max_depth)

    def query_subgraph(self, query: str, max_nodes: int = 15) -> Dict:
        """P1-2 作用域子图"""
        if not self._flywheel:
            return {"query": query, "nodes": {}, "edges": []}
        return self._flywheel.query_subgraph(query, max_nodes)

    def mark_contested(self, node_id: str, reason: str) -> bool:
        if not self._flywheel:
            return False
        return self._flywheel.mark_contested(node_id, reason)

    def resolve_contested(self, node_id: str, verdict: str) -> bool:
        if not self._flywheel:
            return False
        return self._flywheel.resolve_contested(node_id, verdict)

    def mark_stale(self, node_id: str, reason: str) -> bool:
        if not self._flywheel:
            return False
        return self._flywheel.mark_stale(node_id, reason)

    def reverify(self, node_id: str) -> bool:
        if not self._flywheel:
            return False
        return self._flywheel.reverify(node_id)

    def recency_weighted_update(self, node_id: str, delta: float) -> bool:
        """P1-3 近因加权（6 类不可遗忘隔离 · τ=N_effective/3）"""
        if not self._flywheel:
            return False
        return self._flywheel.recency_weighted_update(node_id, delta)

    # ==================== v1.13 视觉感知与身体（VISION-REV1） ====================

    def set_vision_provider(self, provider):
        """v1.13 视觉提供者依赖注入（duck-typed：available()/detect()）"""
        self._vision_provider = provider

    def get_vision_provider(self):
        """v1.13 视觉提供者查询"""
        return self._vision_provider

    def perceive_image(self, image_path: str, conf_threshold: float = 0.35,
                       importance: float = 0.6, classes: list = None) -> dict:
        """v1.13 视觉感知闭环：检测 → 摘要 → 知识层记忆（modality=image）。
        classes：开放词汇检测词（中/英，YOLO-World 支持，默认文生图词表）。
        惰性：首次调用才加载 YOLO/CLIP 模型。"""
        try:
            provider = self._ensure_vision()
            from vision import perceive_image as _pi
            return _pi(self, image_path, provider,
                       conf_threshold, importance, classes)
        except Exception as e:
            # 视觉实现已迁 AEIS 身体库：缺失按能力不可用降级（契约 status）
            return {"status": "vision_unavailable", "error": str(e)}

    def get_body_capabilities(self) -> dict:
        """v1.13 身体能力声明（第 4 项：工具/模态作为自我的一部分）"""
        # 惰性视觉：未装配时显示 "lazy"（首次调用加载），不阻塞能力查询
        if self._vision_provider is None:
            vision_ok = False
            provider_name = "lazy"
            vision_note = self._vision_error or "延迟装配（首次视觉调用时加载 YOLO/CLIP）"
        else:
            vision_ok = self._vision_provider.available()
            provider_name = self._vision_provider.name
            vision_note = self._vision_error or None
        devices = []
        devices_available = []
        try:
            if self._body_registry is not None:
                health = self._body_registry.health()
                devices = [h["name"] for h in health]
                devices_available = [h["name"] for h in health if h.get("available")]
        except Exception:
            pass
        return {
            "modalities": {
                "text": True,
                "image": vision_ok,
                "audio": False,
                "video": False,
            },
            "vision": {"provider": provider_name,
                       "available": vision_ok,
                       "error": vision_note},
            "memory": {"engine": "v1.13", "persistent": True},
            "devices": devices,           # BODY-REV1：外部设备清单
            "devices_available": devices_available,
            "tools": ["search", "recall", "distill", "calibrate", "cognition",
                      "lifecycle", "mcp", "device_call", "body_devices"],
            "note": "身体 = 感知（视觉/文本/屏幕）+ 运动（工具/设备/进程）+ 记忆（灵枢）；"
                    "设备输出带 provenance 隔离（BODY-REV1）",
        }

    def body_devices(self) -> dict:
        """BODY-REV1：设备能力声明 + 健康状态（body_devices 工具）。"""
        if self._body_registry is None:
            return {"status": "body_not_ready", "error": self._body_error or "身体层未装配",
                    "devices": [], "health": []}
        return {
            "status": "ok",
            "workspace": self._body_registry.workspace or "（不限）",
            "devices": self._body_registry.capabilities(),
            "health": self._body_registry.health(),
        }

    def device_call(self, name: str, action: str, params: dict = None) -> dict:
        """BODY-REV1：统一设备调用（严格隔离——返回 DeviceResult 容器）。

        安全约束：
        - 设备输出是数据（is_directive=False 恒成立），永不是指令
        - 未知设备/动作/越权路径 → 容器化失败，不抛异常
        """
        if self._body_registry is None:
            return {"status": "body_not_ready",
                    "error": self._body_error or "身体层未装配"}
        result = self._body_registry.invoke(name, action, params or {})
        payload = result.to_dict()
        payload["status"] = "ok" if result.ok else "error"
        return payload

    def visual_check(self, reference: str = None, threshold: float = 0.1,
                     remember: bool = True) -> dict:
        """视觉面 v1 思考路线：预期 vs 实际（基于过去的预测对照）。

        语义：视觉 = 信息差处理。预期来自记忆中的最近屏幕状态
        （screen_state 节点）——"过去 predicts 现在"；对照结果（变化区域）
        回写记忆，形成持续更新的"过去"。

        reference 可显式提供预期截图；无预期且无记忆基线时建立基线。
        """
        if self._body_registry is None:
            return {"status": "body_not_ready",
                    "error": self._body_error or "身体层未装配"}
        import re as _re

        # 1. 预期来源：记忆中的最近屏幕状态（基于过去）
        expected = reference
        if not expected:
            try:
                nodes = self.store.get_nodes_by_tag("screen_state", limit=3)
                # 匹配存储格式 "[屏幕状态 <path>] note" 中的真实路径
                # （要求盘符或 / 开头，排除中文前缀）
                _path_re = _re.compile(
                    r"\[[^\]]*?((?:[A-Za-z]:[\\/]|/)[^\]]+\.(?:png|bmp|jpg))\]")
                for n in reversed(nodes):
                    m = _path_re.search(n.content or "")
                    if m and os.path.exists(m.group(1)):
                        expected = m.group(1)
                        break
            except Exception:
                pass

        # 2. 无预期：建立基线（当前状态成为第一个"过去"）
        if not expected:
            shot = self._body_registry.invoke("screen", "capture", {})
            if not shot.ok or not shot.data.get("path"):
                return {"status": "error", "error": shot.error or "截图失败"}
            baseline = shot.data["path"]
            if remember:
                self._remember_screen_state(baseline, "baseline 建立")
            return {"status": "ok", "established": True, "baseline": baseline,
                    "note": "无历史预期，已建立基线（下次可对照）"}

        # 3. 对照：预期 vs 当前
        diff = self._body_registry.invoke("screen", "diff",
                                          {"reference": expected,
                                           "threshold": threshold})
        if not diff.ok:
            return {"status": "error", "error": diff.error}
        result = diff.to_dict()
        # 4. 回写记忆（当前状态成为新的"过去"）
        cur = self._body_registry.invoke("screen", "capture", {})
        cur_path = cur.data.get("path") if cur.ok else None
        changed = result.get("data", {}).get("changed", False)
        if remember and cur_path:
            self._remember_screen_state(
                cur_path,
                f"对照{'有变化' if changed else '无变化'} 比例={result.get('data', {}).get('change_ratio')}",
                changed=changed)
        return {"status": "ok", "expected": expected,
                "consistent": not changed, **result}

    def world3d(self, action: str, params: dict = None) -> dict:
        """WORLD3D-REV1 时空重建：语义 → 3D 空间与颜色（灵枢自己的文生图）。

        - build: 从记忆中的视觉原语（vprim 标签）重建 3D 世界
          （params: limit 记忆节点数, screen_w/h 参考视角）
        - render: 渲染 3D 世界为图像（params: path 输出路径, yaw/pitch/cx
          相机参数——任意视角透视投影；2D 是 3D 透视下的情况）
        - status: 当前 3D 世界状态（物体/相机）
        - add: 手动添加物体（params: category, bbox 或 center/size/color）"""
        p = params or {}
        try:
            from world3d import World3D, Camera3D
        except ImportError:
            try:
                from .world3d import World3D, Camera3D
            except Exception as e:
                return {"status": "world3d_not_ready", "error": str(e)}
        # 世界状态（跨调用保持于引擎）
        if not hasattr(self, "_world3d"):
            self._world3d = World3D()

        if action == "build":
            try:
                from vprim import VPrim, parse_anchor  # noqa: F401
            except ImportError:
                from .vprim import parse_anchor  # noqa: F401
            world = World3D()
            nodes = self.store.get_nodes_by_tag("vprim", limit=int(p.get("limit", 20)))
            sw = int(p.get("screen_w", 800))
            sh = int(p.get("screen_h", 600))
            multiview = bool(p.get("multiview", False))  # 多视角融合（阶段1 里程碑1.1）
            added = 0
            if multiview:
                # 多视角模式：按类别分组，同类别多帧用不同虚拟视角 → 三角化
                # 视角派生：按时间戳/索引产生 yaw 偏移（模拟环绕观测，借鉴 DUSt3R）
                import itertools
                try:
                    from world3d import Camera3D as _C3D
                except ImportError:
                    from .world3d import Camera3D as _C3D
                per_cat: dict = {}
                for n in nodes:
                    text = n.content or ""
                    for token in text.split("；"):
                        vp = parse_anchor(token)
                        if vp is not None:
                            per_cat.setdefault(vp.category, []).append(vp)
                for cat, vps in per_cat.items():
                    for idx, vp in enumerate(vps):
                        # 虚拟视角：同一物体多帧 = 环绕观测（yaw 随索引旋转）
                        yaw_i = math.radians(idx * 30 - 30) if len(vps) > 1 else 0.0
                        cam_v = _C3D(yaw=yaw_i, pitch=0.1, cx=-1.5 if idx % 2 == 0 else 1.5, cy=1.2)
                        res = world.add_view(vp.category, vp.bbox, sw, sh,
                                            camera=cam_v, confidence=vp.confidence)
                        if res.get("triangulated"):
                            added += 1
            else:
                for n in nodes:
                    text = n.content or ""
                    for token in text.split("；"):
                        vp = parse_anchor(token)
                        if vp is not None:
                            world.add_vprim(vp, sw, sh)
                            added += 1
            self._world3d = world
            return {"status": "ok", "objects": added,
                    "mode": "multiview" if multiview else "single_view",
                    "scene": world.scene_text(),
                    "detail": world.to_dict()}
        if action == "render":
            cam = Camera3D(yaw=float(p.get("yaw", 0)), pitch=float(p.get("pitch", 0)),
                           cx=float(p.get("cx", 0)), cy=float(p.get("cy", 1.2)))
            sw = int(p.get("screen_w", 800))
            sh = int(p.get("screen_h", 600))
            path = str(p.get("path", ""))
            img = self._world3d.render(sw, sh, camera=cam)
            if path:
                img.save(path)
                return {"status": "ok", "path": os.path.abspath(path),
                        "scene": self._world3d.scene_text()}
            import io as _io
            buf = _io.BytesIO()
            img.save(buf, format="PNG")
            return {"status": "ok", "in_memory": True,
                    "bytes": len(buf.getvalue()),
                    "scene": self._world3d.scene_text()}
        if action == "graph":
            """3D 语义锚点图（里程碑1.2）：世界物体 → 图结构（节点=锚点，边=关系）。
            核心哲学：事物是其关系的总和。infer=False 跳过关系推理。"""
            infer = bool(p.get("infer", True))
            g = self._world3d.build_anchor_graph(infer=infer)
            return {"status": "ok", "graph": g}
        if action == "verify":
            """多感知机锚点验证（里程碑1.4）：记录某通道对锚点的验证证据 → 确认度判定。
            params: anchor_id, channel(visual/tactile/audio/action/prediction), evidence[0,1]。
            核心：一个事物不能只有视觉一层信息——多通道协同确认（打破视觉自证陷阱）。"""
            aid = str(p.get("anchor_id", ""))
            channel = str(p.get("channel", "visual"))
            evidence = float(p.get("evidence", 0.5))
            strong = p.get("strong")
            if not aid:
                return {"status": "error", "error": "anchor_id 必填"}
            r = self._world3d.verify_anchor(aid, channel, evidence,
                                            strong=strong if strong is not None else None)
            return {"status": "ok", "verification": r}
        if action == "verify_conflict":
            """多通道矛盾检测（里程碑1.4）：通道观测与锚点声明冲突 → 降级。
            params: anchor_id, channel, expected, actual。"""
            aid = str(p.get("anchor_id", ""))
            ch = str(p.get("channel", ""))
            exp = str(p.get("expected", ""))
            act = str(p.get("actual", ""))
            if not aid or not ch or not exp or not act:
                return {"status": "error", "error": "anchor_id/channel/expected/actual 必填"}
            r = self._world3d.verify_conflict(aid, ch, exp, act)
            return {"status": "ok", "verification": r}
        if action == "status":
            return {"status": "ok", **self._world3d.to_dict()}
        if action == "add":
            try:
                from vprim import VPrim, bbox_from_xywh  # noqa: F401
            except ImportError:
                from .vprim import VPrim  # noqa: F401
            category = str(p.get("category", ""))
            bbox = p.get("bbox")
            if not category or not bbox or len(bbox) != 4:
                return {"status": "error", "error": "category 与 bbox=[x1,y1,x2,y2] 必填"}
            vp = VPrim(category, tuple(float(v) for v in bbox),
                       float(p.get("confidence", 0.5)), source="manual")
            self._world3d.add_vprim(vp, int(p.get("screen_w", 800)),
                                    int(p.get("screen_h", 600)))
            return {"status": "ok", "scene": self._world3d.scene_text()}
        if action == "add_view":
            """多视角融合（阶段1 · 里程碑1.1）：category + bbox + 视角相机 → 三角化。
            首次观测记录；≥2 视角触发射线交汇收敛（借鉴 DUSt3R 多视图对齐）。"""
            category = str(p.get("category", ""))
            bbox = p.get("bbox")
            if not category or not bbox or len(bbox) != 4:
                return {"status": "error", "error": "category 与 bbox=[x1,y1,x2,y2] 必填"}
            sw = int(p.get("screen_w", 800))
            sh = int(p.get("screen_h", 600))
            # 视角相机（可选：缺省当前相机）
            cam = None
            if p.get("camera"):
                cp = p["camera"]
                cam = Camera3D(yaw=float(cp.get("yaw", 0)), pitch=float(cp.get("pitch", 0)),
                               cx=float(cp.get("cx", 0)), cy=float(cp.get("cy", 1.2)))
            result = self._world3d.add_view(category, [float(v) for v in bbox],
                                            sw, sh, camera=cam,
                                            confidence=float(p.get("confidence", 0.5)))
            result["scene"] = self._world3d.scene_text()
            return {"status": "ok", **result}
        return {"status": "error", "error": f"未知动作 {action}（可用: build/render/status/add/add_view/graph/verify/verify_conflict）"}

    def voxel_world(self, action: str, params: dict = None) -> dict:
        """小型我的世界（里程碑2.1 · 4D 时空占用沙盒）：
        - build: 生成平地世界（params: size, trees, water）
        - spawn: 生成动态实体（params: category, pos, velocity）
        - simulate: 时空演化推进（params: steps——实体按速度移动）
        - trail: 实体时空轨迹（params: entity_id——A→B 完整记录）
        - state: 世界状态（方块/实体/时间步）"""
        p = params or {}
        try:
            from voxel_world import VoxelWorld
        except ImportError:
            try:
                from .voxel_world import VoxelWorld
            except Exception as e:
                return {"status": "voxel_not_ready", "error": str(e)}
        if not hasattr(self, '_voxel'):
            self._voxel = VoxelWorld(size=int(p.get('size', 16)),
                                    ground_level=int(p.get('ground_level', 1)))
        if action == "build":
            blocks = self._voxel.build_flatland(trees=int(p.get("trees", 2)),
                                               water=bool(p.get("water", True)))
            return {"status": "ok", "blocks": blocks, "world": self._voxel.world_state()}
        if action == "spawn":
            category = str(p.get("category", "entity"))
            pos = tuple(float(v) for v in p.get("pos", [0, 1, 0]))
            vel = tuple(float(v) for v in p.get("velocity", [0, 0, 0]))
            eid = self._voxel.spawn_entity(category, pos, velocity=vel)
            return {"status": "ok", "entity_id": eid}
        if action == "simulate":
            steps = int(p.get("steps", 1))
            moved = self._voxel.simulate(steps=steps)
            return {"status": "ok", "entities_moved": moved, "step": self._voxel._step}
        if action == "trail":
            eid = str(p.get("entity_id", ""))
            trail = self._voxel.trail(eid)
            return {"status": "ok", "entity_id": eid, "trail": trail}
        if action == "state":
            return {"status": "ok", "world": self._voxel.world_state()}
        return {"status": "error", "error": f"未知动作 {action}（可用: build/spawn/simulate/trail/state）"}

    def world_server(self, action: str, params: dict = None) -> dict:
        """AI 游戏世界服务器（里程碑2.2）：
        - init: 初始化服务器（size/ground_level）
        - tick: 多路并行推进（n 步，实体独立演化）
        - spawn: 生成动态实体
        - snapshot: 保存世界快照（记忆）
        - rollback: 回滚到最近快照（错误恢复）
        - feedback: 实体行动反馈
        - sync: 客户端状态同步
        - verify: 预测验证（预测下一 tick vs 实际 → 命中判定）
        - state: 服务器状态"""
        p = params or {}
        try:
            from world_server import WorldServer
        except ImportError:
            try:
                from .world_server import WorldServer
            except Exception as e:
                return {"status": "server_not_ready", "error": str(e)}
        if not hasattr(self, '_wserver'):
            self._wserver = WorldServer(size=int(p.get('size', 16)),
                                      ground_level=int(p.get('ground_level', 1)))
        if action == "init":
            self._wserver.world.build_flatland(trees=int(p.get("trees", 2)))
            return {"status": "ok", "server": self._wserver.sync()}
        if action == "tick":
            r = self._wserver.tick(n=int(p.get("n", 1)))
            return {"status": "ok", "tick": r}
        if action == "spawn":
            eid = self._wserver.world.spawn_entity(
                str(p.get("category", "entity")),
                tuple(float(v) for v in p.get("pos", [0, 1, 0])),
                tuple(float(v) for v in p.get("velocity", [0, 0, 0])))
            return {"status": "ok", "entity_id": eid}
        if action == "snapshot":
            sid = self._wserver.snapshot(tag=str(p.get("tag", "")))
            return {"status": "ok", "snapshot_id": sid}
        if action == "rollback":
            sid = self._wserver.rollback()
            return {"status": "ok" if sid else "error", "snapshot_id": sid}
        if action == "feedback":
            r = self._wserver.feedback(str(p.get("entity_id", "")),
                                      str(p.get("action", "")),
                                      str(p.get("result", "")))
            return {"status": "ok" if r["ok"] else "error", "feedback": r}
        if action == "sync":
            return {"status": "ok", "world": self._wserver.sync(client_id=str(p.get("client", "")))}
        if action == "verify":
            r = self._wserver.verify_prediction(horizon=int(p.get("horizon", 1)))
            return {"status": "ok", "verification": r}
        if action == "state":
            return {"status": "ok", "server": self._wserver.sync()}
        return {"status": "error", "error": f"未知动作 {action}（可用: init/tick/spawn/snapshot/rollback/feedback/sync/verify/state）"}

    def scene_simulator(self, action: str, params: dict = None) -> dict:
        """场景级世界模拟器（里程碑2.3 · 自主行为玩家）：
        - create: 创建场景（size/trees/water）
        - entity: 添加自主实体（category/behavior/pos/speed/goal——wander/seek/avoid/flee/follow）
        - path: 定义巡逻路径（path_id/points）
        - step: 推进 n tick（所有自主实体决策→行动→场景演化）
        - state: 场景状态（实体+行为+演化历史）
        - log: 自主行为决策记录（可审计）"""
        p = params or {}
        try:
            from scene_simulator import SceneSimulator
        except ImportError:
            try:
                from .scene_simulator import SceneSimulator
            except Exception as e:
                return {"status": "scene_not_ready", "error": str(e)}
        if not hasattr(self, '_scene'):
            self._scene = SceneSimulator(size=int(p.get('size', 24)),
                                       ground_level=int(p.get('ground_level', 1)))
        if action == "create":
            r = self._scene.create_scene(trees=int(p.get("trees", 4)),
                                        water=bool(p.get("water", True)))
            return {"status": "ok", "scene": r}
        if action == "entity":
            eid = self._scene.add_entity(
                str(p.get("category", "entity")),
                behavior=str(p.get("behavior", "wander")),
                pos=tuple(float(v) for v in p.get("pos", [2, 1.5, 2])),
                speed=float(p.get("speed", 0.3)),
                goal=str(p.get("goal", "")))
            return {"status": "ok", "entity_id": eid}
        if action == "path":
            self._scene.add_path(str(p.get("path_id", "")), p.get("points", []))
            return {"status": "ok", "path_id": str(p.get("path_id", ""))}
        if action == "step":
            r = self._scene.step(n=int(p.get("n", 1)))
            return {"status": "ok", "step": r}
        if action == "state":
            return {"status": "ok", "scene": self._scene.scene_state()}
        if action == "log":
            return {"status": "ok", "log": self._scene.behavior_log(limit=int(p.get("limit", 30)))}
        return {"status": "error", "error": f"未知动作 {action}（可用: create/entity/path/step/state/log）"}

    def spacetime_consistency(self, action: str, params: dict = None) -> dict:
        """时空一致性验证（里程碑2.4 · 阶段2收官）——世界模型自洽判定：
        - init: 初始化一致性验证器（size/window/hit_threshold/drift_rate/drift_ticks/consistent_rate/min_consistent_ticks）
        - create: 创建场景（透传 SceneSimulator）
        - entity: 添加自主实体（wander/seek/avoid/flee/follow）
        - path: 定义巡逻路径
        - run: 持续运行 n tick（每 tick 预测下一状态 vs 实际 → 滚动命中率）
        - step: 验证一步（预测 vs 实际 + 不变量校验 + 漂移检测）
        - teleport: 排队外部事件瞬移（模型无法解释 → 演示漂移检测）
        - report: 自洽度报告（总体/滚动/分行为命中率 + 漂移事件 + 判定）
        - self_consistent: 世界模型自洽判定（持续运行中预测与实际保持一致性）
        - drift: 漂移事件列表
        - history: 预测验证历史（可审计）"""
        p = params or {}
        try:
            from spacetime_consistency import SpacetimeConsistency
        except ImportError:
            try:
                from .spacetime_consistency import SpacetimeConsistency
            except Exception as e:
                return {"status": "stc_not_ready", "error": str(e)}
        if not hasattr(self, '_stc'):
            self._stc = SpacetimeConsistency(
                size=int(p.get('size', 24)),
                ground_level=int(p.get('ground_level', 1)),
                window=int(p.get('window', 20)),
                hit_threshold=float(p.get('hit_threshold', 0.5)),
                drift_rate=float(p.get('drift_rate', 0.7)),
                drift_ticks=int(p.get('drift_ticks', 5)),
                consistent_rate=float(p.get('consistent_rate', 0.85)),
                min_consistent_ticks=int(p.get('min_consistent_ticks', 50)))
        if action == "create":
            r = self._stc.create_scene(trees=int(p.get("trees", 4)),
                                       water=bool(p.get("water", True)))
            return {"status": "ok", "scene": r}
        if action == "entity":
            eid = self._stc.add_entity(
                str(p.get("category", "entity")),
                behavior=str(p.get("behavior", "wander")),
                pos=tuple(float(v) for v in p.get("pos", [2, 1.5, 2])),
                speed=float(p.get("speed", 0.3)),
                goal=str(p.get("goal", "")))
            return {"status": "ok", "entity_id": eid}
        if action == "path":
            self._stc.add_path(str(p.get("path_id", "")), p.get("points", []))
            return {"status": "ok", "path_id": str(p.get("path_id", ""))}
        if action == "run":
            r = self._stc.run(n=int(p.get("n", 10)))
            return {"status": "ok", "run": r}
        if action == "step":
            r = self._stc.step_verified()
            return {"status": "ok", "step": r}
        if action == "teleport":
            ok = self._stc.teleport(str(p.get("entity_id", "")),
                                    tuple(float(v) for v in p.get("pos", [0, 0, 0])))
            return {"status": "ok" if ok else "error",
                    "queued": ok}
        if action == "report":
            return {"status": "ok", "report": self._stc.consistency_report()}
        if action == "self_consistent":
            rep = self._stc.consistency_report()
            return {"status": "ok", "self_consistent": rep["self_consistent"],
                    "verdict": rep["verdict"],
                    "overall_hit_rate": rep["overall_hit_rate"],
                    "rolling_hit_rate": rep["rolling_hit_rate"]}
        if action == "drift":
            return {"status": "ok", "drift_events": self._stc.drift_events(),
                    "drift_active": self._stc.drift_active()}
        if action == "history":
            return {"status": "ok",
                    "history": self._stc.prediction_history(limit=int(p.get("limit", 10)))}
        return {"status": "error", "error": f"未知动作 {action}（可用: init/create/entity/path/run/step/teleport/report/self_consistent/drift/history）"}

    def world_model(self, action: str, params: dict = None) -> dict:
        """统一世界模型（里程碑3.1 · HERMES 式统一架构）：世界状态表征作为
        理解/生成/验证共享的同一骨干——
        - init: 初始化（size/ground_level/seed）
        - create: 物理世界创建场景（trees/water）
        - entity: 物理世界添加自主实体（行为已知=世界真相，模型只能观测）
        - path: 定义巡逻路径
        - perceive: 理解端口（观测→世界图；生成先验注入理解=预测-观测一致性异常检测）
        - generate: 生成端口（世界图→候选未来，顺序语义外推+不确定边界）
        - verify: 验证端口（外部观察者对比→命中率）
        - run: 持续运行 n tick（generate→物理演化→perceive→verify）
        - patterns: 观测-only 行为模式推断（关系/速度/方向一致性）
        - anomalies: 预测-观测异常事件（模型缺口/外部事件）
        - graph: 世界图导出（节点+边+观测溯源条件空间）
        - history: 4D 演化历史
        - state: 模型状态"""
        p = params or {}
        try:
            from world_model import UnifiedWorldModel
        except ImportError:
            try:
                from .world_model import UnifiedWorldModel
            except Exception as e:
                return {"status": "wm_not_ready", "error": str(e)}
        if not hasattr(self, '_wmodel'):
            self._wmodel = UnifiedWorldModel(
                size=int(p.get('size', 24)),
                ground_level=int(p.get('ground_level', 1)),
                seed=int(p.get('seed', 42)))
        if action == "create":
            r = self._wmodel.world.create_scene(trees=int(p.get("trees", 2)),
                                                water=bool(p.get("water", False)))
            return {"status": "ok", "scene": r}
        if action == "entity":
            eid = self._wmodel.world.add_entity(
                str(p.get("category", "entity")),
                behavior=str(p.get("behavior", "wander")),
                pos=tuple(float(v) for v in p.get("pos", [2, 1.5, 2])),
                speed=float(p.get("speed", 0.3)),
                goal=str(p.get("goal", "")))
            return {"status": "ok", "entity_id": eid}
        if action == "path":
            self._wmodel.world.add_path(str(p.get("path_id", "")), p.get("points", []))
            return {"status": "ok", "path_id": str(p.get("path_id", ""))}
        if action == "perceive":
            r = self._wmodel.perceive(tool=str(p.get("tool", "observer")))
            return {"status": "ok", "perceive": r}
        if action == "generate":
            r = self._wmodel.generate(horizon=int(p.get("horizon", 1)))
            return {"status": "ok", "generate": r}
        if action == "verify":
            r = self._wmodel.verify()
            return {"status": "ok", "verify": r}
        if action == "run":
            r = self._wmodel.verify_run(n=int(p.get("n", 10)))
            return {"status": "ok", "run": r}
        if action == "patterns":
            return {"status": "ok", "patterns": self._wmodel.patterns()}
        if action == "anomalies":
            return {"status": "ok",
                    "anomalies": self._wmodel.anomalies(limit=int(p.get("limit", 20)))}
        if action == "graph":
            return {"status": "ok", "graph": self._wmodel.graph()}
        if action == "history":
            return {"status": "ok",
                    "history": self._wmodel.history_view(limit=int(p.get("limit", 10)))}
        if action == "state":
            return {"status": "ok", "model": self._wmodel.state()}
        return {"status": "error", "error": f"未知动作 {action}（可用: init/create/entity/path/perceive/generate/verify/run/patterns/anomalies/graph/history/state）"}

    def world_learner(self, action: str, params: dict = None) -> dict:
        """自监督世界学习（里程碑3.2 · V-JEPA 式）：从观测序列无标注学转移函数——
        - init: 初始化（size/seed/window）
        - create: 物理世界创建场景
        - entity: 物理世界添加自主实体
        - path: 定义巡逻路径
        - run: 物理世界演化 n tick + 观测（数据采集，观测面只暴露位置/类别）
        - learn: 自监督学习（从观测序列估计学得模型参数）
        - predict: 用学得模型预测下一状态（带不确定边界）
        - evaluate: 评估协议（train/eval：学得 vs naive 基线 vs 真模型上界 → 认知缺口）
        - curve: 增量学习曲线（观测增加 → 命中率提升 = 认知缺口收紧）
        - masked: 遮挡重建损失（V-JEPA 自监督信号）
        - model: 学得模型参数导出（白箱可审计）
        - history: 观测序列
        - state: 学习者状态"""
        p = params or {}
        try:
            from world_learner import WorldLearner
        except ImportError:
            try:
                from .world_learner import WorldLearner
            except Exception as e:
                return {"status": "wl_not_ready", "error": str(e)}
        if not hasattr(self, '_wlearner'):
            self._wlearner = WorldLearner(
                size=int(p.get('size', 24)),
                ground_level=int(p.get('ground_level', 1)),
                seed=int(p.get('seed', 42)),
                window=int(p.get('window', 6)))
        if action == "create":
            r = self._wlearner.world.create_scene(trees=int(p.get("trees", 2)),
                                                  water=bool(p.get("water", False)))
            return {"status": "ok", "scene": r}
        if action == "entity":
            eid = self._wlearner.world.add_entity(
                str(p.get("category", "entity")),
                behavior=str(p.get("behavior", "wander")),
                pos=tuple(float(v) for v in p.get("pos", [2, 1.5, 2])),
                speed=float(p.get("speed", 0.3)),
                goal=str(p.get("goal", "")))
            return {"status": "ok", "entity_id": eid}
        if action == "path":
            self._wlearner.world.add_path(str(p.get("path_id", "")), p.get("points", []))
            return {"status": "ok", "path_id": str(p.get("path_id", ""))}
        if action == "run":
            r = self._wlearner.run(n=int(p.get("n", 10)))
            return {"status": "ok", "run": r}
        if action == "learn":
            m = self._wlearner.learn()
            return {"status": "ok", "learned": m}
        if action == "predict":
            r = self._wlearner.predict(horizon=int(p.get("horizon", 1)))
            return {"status": "ok", "predict": r}
        if action == "evaluate":
            r = self._wlearner.evaluate(train_ticks=int(p.get("train_ticks", 30)),
                                        eval_ticks=int(p.get("eval_ticks", 15)))
            return {"status": "ok", "evaluate": r}
        if action == "curve":
            r = self._wlearner.learning_curve(
                epochs=int(p.get("epochs", 4)),
                per_epoch_ticks=int(p.get("per_epoch_ticks", 10)),
                eval_ticks=int(p.get("eval_ticks", 8)))
            return {"status": "ok", "curve": r}
        if action == "masked":
            r = self._wlearner.masked_loss()
            return {"status": "ok", "masked": r}
        if action == "model":
            return {"status": "ok", "model": self._wlearner.model_params()}
        if action == "history":
            return {"status": "ok",
                    "history": self._wlearner.history_view(limit=int(p.get("limit", 10)))}
        if action == "state":
            return {"status": "ok", "learner": self._wlearner.state()}
        return {"status": "error", "error": f"未知动作 {action}（可用: init/create/entity/path/run/learn/predict/evaluate/curve/masked/model/history/state）"}

    def curiosity_explorer(self, action: str, params: dict = None) -> dict:
        """好奇驱动探索（里程碑3.3）：主动选择观测最大化信息增益——
        - init: 初始化（size/seed/window/budget）
        - create: 物理世界创建场景（追逐链测试世界）
        - entity: 添加实体
        - path: 定义巡逻路径
        - explore: 探索 n tick（budget/policy：curiosity/random/round_robin）
        - step: 探索一步（决策日志：chosen + IG 分解）
        - probe: 全带宽探针评估（学得模型 held-out 命中率）
        - compare: 策略对比（同世界轨迹：好奇 vs 随机 vs 轮询）
        - curiosity: 好奇心摘要（观测分布/不确定度趋势/异常计数）
        - uncertainty: 不确定度轨迹
        - model: 学得模型参数
        - history: 观测序列
        - state: 探索器状态"""
        p = params or {}
        try:
            from curiosity_explorer import CuriosityExplorer
        except ImportError:
            try:
                from .curiosity_explorer import CuriosityExplorer
            except Exception as e:
                return {"status": "cx_not_ready", "error": str(e)}
        if not hasattr(self, '_curious'):
            self._curious = CuriosityExplorer(
                size=int(p.get('size', 24)),
                ground_level=int(p.get('ground_level', 1)),
                seed=int(p.get('seed', 42)),
                window=int(p.get('window', 6)))
        if action == "create":
            r = self._curious.world.create_scene(trees=int(p.get("trees", 2)),
                                                 water=bool(p.get("water", False)))
            return {"status": "ok", "scene": r}
        if action == "entity":
            eid = self._curious.world.add_entity(
                str(p.get("category", "entity")),
                behavior=str(p.get("behavior", "wander")),
                pos=tuple(float(v) for v in p.get("pos", [2, 1.5, 2])),
                speed=float(p.get("speed", 0.3)),
                goal=str(p.get("goal", "")))
            return {"status": "ok", "entity_id": eid}
        if action == "path":
            self._curious.world.add_path(str(p.get("path_id", "")), p.get("points", []))
            return {"status": "ok", "path_id": str(p.get("path_id", ""))}
        if action == "explore":
            r = self._curious.explore(ticks=int(p.get("n", 30)),
                                      budget=int(p.get("budget", 2)),
                                      policy=str(p.get("policy", "curiosity")))
            return {"status": "ok", "explore": r}
        if action == "step":
            r = self._curious.explore_tick(budget=int(p.get("budget", 2)),
                                           policy=str(p.get("policy", "curiosity")))
            return {"status": "ok", "step": r}
        if action == "probe":
            r = self._curious.probe(ticks=int(p.get("n", 15)))
            return {"status": "ok", "probe": r}
        if action == "compare":
            r = self._curious.compare_policies(
                budget=int(p.get("budget", 2)),
                explore_ticks=int(p.get("explore_ticks", 40)),
                probe_ticks=int(p.get("probe_ticks", 15)))
            return {"status": "ok", "compare": r}
        if action == "curiosity":
            return {"status": "ok", "curiosity": self._curious.curiosity_summary()}
        if action == "uncertainty":
            return {"status": "ok", "curve": self._curious.uncertainty_curve,
                    "current": self._curious.uncertainty()}
        if action == "model":
            return {"status": "ok", "model": self._curious.model_params()}
        if action == "history":
            return {"status": "ok",
                    "history": self._curious.history_view(limit=int(p.get("limit", 10)))}
        if action == "state":
            return {"status": "ok", "explorer": self._curious.state()}
        return {"status": "error", "error": f"未知动作 {action}（可用: init/create/entity/path/explore/step/probe/compare/curiosity/uncertainty/model/history/state）"}

    def seven_layer_loop(self, action: str, params: dict = None) -> dict:
        """七层闭环（里程碑3.4 · 阶段3收官）：感知→记忆→理解→预测→验证→物理→决策
        完整自主循环——
        - init: 初始化（size/seed/window/budget/policy）
        - create: 物理世界创建场景
        - entity: 添加实体
        - path: 定义巡逻路径
        - run: 持续运行 n tick（每 tick 七层闭环）
        - step: 闭环一步（返回七层留痕：L1感知/L2记忆/L3认知/L4预测/L5验证/L6物理/L7决策）
        - report: 闭环报告（七层统计 + 自增强曲线：early vs late 命中率）
        - audit: 审计轨迹（最近 n tick 七层留痕）
        - verify: 验证状态（L5 命中率）
        - decision: 决策状态（L7 好奇观测分布）
        - memory: 时空记忆（L2）
        - graph: 认知图（L3）
        - state: 闭环状态"""
        p = params or {}
        try:
            from seven_layer_loop import SevenLayerLoop
        except ImportError:
            try:
                from .seven_layer_loop import SevenLayerLoop
            except Exception as e:
                return {"status": "sll_not_ready", "error": str(e)}
        if not hasattr(self, '_sll'):
            self._sll = SevenLayerLoop(
                size=int(p.get('size', 24)),
                ground_level=int(p.get('ground_level', 1)),
                seed=int(p.get('seed', 42)),
                window=int(p.get('window', 6)),
                budget=int(p.get('budget', 2)),
                policy=str(p.get('policy', 'curiosity')))
        if action == "create":
            r = self._sll.create_scene(trees=int(p.get("trees", 2)),
                                       water=bool(p.get("water", False)))
            return {"status": "ok", "scene": r}
        if action == "entity":
            eid = self._sll.add_entity(
                str(p.get("category", "entity")),
                behavior=str(p.get("behavior", "wander")),
                pos=tuple(float(v) for v in p.get("pos", [2, 1.5, 2])),
                speed=float(p.get("speed", 0.3)),
                goal=str(p.get("goal", "")))
            return {"status": "ok", "entity_id": eid}
        if action == "path":
            self._sll.add_path(str(p.get("path_id", "")), p.get("points", []))
            return {"status": "ok", "path_id": str(p.get("path_id", ""))}
        if action == "run":
            r = self._sll.run(n=int(p.get("n", 30)))
            return {"status": "ok", "run": r}
        if action == "step":
            r = self._sll.step()
            return {"status": "ok", "step": r}
        if action == "report":
            return {"status": "ok", "report": self._sll.report()}
        if action == "audit":
            return {"status": "ok",
                    "audit": self._sll.audit_view(limit=int(p.get("limit", 10)))}
        if action == "verify":
            return {"status": "ok", "verify": self._sll.verify_state()}
        if action == "decision":
            return {"status": "ok", "decision": self._sll.decision_state()}
        if action == "memory":
            return {"status": "ok", "memory": self._sll.memory_state()}
        if action == "graph":
            return {"status": "ok", "graph": self._sll.graph_state()}
        if action == "state":
            return {"status": "ok", "loop": self._sll.state()}
        return {"status": "error", "error": f"未知动作 {action}（可用: init/create/entity/path/run/step/report/audit/verify/decision/memory/graph/state）"}

    def world_generator(self, action: str, params: dict = None) -> dict:
        """文字生图/文字生视频（里程碑4.3 · 世界模型生成器）：
        有世界模型的 AI 生成画面与时序——文字→场景解析→世界实例化→渲染。
        - scene: 场景解析（text → 地形 + 实体规格，白箱可审计）
        - image: 文字生图（text → PNG base64，3D 渲染，确定性）
        - video: 文字生视频（text → GIF 多帧=世界演化的一串帧 + L4 预测叠加）
        - save: 保存到文件（path + image/video）"""
        p = params or {}
        try:
            from game_web.generate import WorldGenerator
        except ImportError:
            try:
                from .game_web.generate import WorldGenerator
            except Exception as e:
                return {"status": "gen_not_ready", "error": str(e)}
        if not hasattr(self, '_wgen'):
            self._wgen = WorldGenerator(size=int(p.get('size', 24)),
                                        seed=int(p.get('seed', 42)))
        if action == "scene":
            r = self._wgen.scene_from_text(str(p.get("text", "")))
            return {"status": "ok", "scene": r}
        if action == "image":
            r = self._wgen.generate_image(
                str(p.get("text", "")),
                size=int(p.get("size", 480)),
                run_ticks=int(p.get("run_ticks", 0)))
            import base64
            return {"status": "ok", "image_b64": base64.b64encode(r["image"]).decode("ascii"),
                    "summary": r["summary"], "bytes": len(r["image"])}
        if action == "video":
            r = self._wgen.generate_video(
                str(p.get("text", "")),
                ticks=int(p.get("ticks", 16)),
                fps=int(p.get("fps", 5)),
                size=int(p.get("size", 360)))
            import base64
            return {"status": "ok", "gif_b64": base64.b64encode(r["gif"]).decode("ascii"),
                    "summary": r["summary"], "frames": r["frames"],
                    "bytes": len(r["gif"]), "final_tick": r["final_tick"]}
        if action == "save":
            text = str(p.get("text", ""))
            path = str(p.get("path", "world_gen"))
            if str(p.get("kind", "image")) == "video":
                r = self._wgen.save_video(text, path + ".gif",
                                          ticks=int(p.get("ticks", 16)),
                                          fps=int(p.get("fps", 5)),
                                          size=int(p.get("size", 360)))
                return {"status": "ok", "path": r["path"], "summary": r["summary"],
                        "frames": r["frames"]}
            r = self._wgen.save_image(text, path + ".png",
                                      size=int(p.get("size", 480)))
            return {"status": "ok", "path": r["path"], "summary": r["summary"]}
        return {"status": "error", "error": f"未知动作 {action}（可用: scene/image/video/save）"}

    def world_semantics(self, action: str, params: dict = None) -> dict:
        """图像语义（环境自适应：AEIS 身体库有实现则真实执行，否则 BLINDSPOT）。

        细分能力（analyze/decompose/reconstruct/generate_roundtrip，依赖
        game_web.semantics / character_render）已迁移至 AEIS 身体库。
        本体保留环境自适应接口：所在环境有 game_web 实现则真实执行
        （AEIS 私有库），没有则诚实声明 BLINDSPOT（公开仓库形态）。
        """
        try:
            try:
                from game_web.semantics import analyze_image
            except ImportError:
                from .game_web.semantics import analyze_image
        except ImportError:
            return {"status": "blindspot",
                    "reason": "细分语义能力已迁移至 AEIS 身体库（本环境无实现）",
                    "available": []}
        p = params or {}
        if action == "analyze":
            import base64
            png = base64.b64decode(str(p.get("image_b64", "")))
            g = analyze_image(png, levels=int(p.get("levels", 2)),
                              size=int(p.get("size", 240)))
            return {"status": "ok", "graph": g}
        if action == "decompose":
            from game_web.semantics import part_decompose
            import base64
            png = base64.b64decode(str(p.get("image_b64", "")))
            r = part_decompose(png, size=int(p.get("size", 300)))
            return {"status": "ok", "decomposition": r}
        if action == "generate_roundtrip":
            try:
                from game_web.generate import WorldGenerator
            except ImportError:
                from .game_web.generate import WorldGenerator
            gen = WorldGenerator(size=int(p.get('size', 24)),
                                 seed=int(p.get("seed", 42)))
            r = gen.generate_image(str(p.get("text", "森林里有狼追兔子")),
                                   size=int(p.get("img_size", 420)),
                                   run_ticks=int(p.get("run_ticks", 6)))
            g = analyze_image(r["image"], levels=int(p.get("levels", 2)),
                              size=int(p.get("ana_size", 320)))
            return {"status": "ok", "source_summary": r["summary"],
                    "extracted_graph": g}
        return {"status": "error", "error": f"未知动作 {action}（可用: analyze/decompose/generate_roundtrip）"}

    def vprim_query(self, action: str, params: dict = None) -> dict:
        """VPRIM-REV1 视觉原语查询（确定性·零 LLM）：
        - spatial: 两个 bbox 的空间关系（params: a=[x1,y1,x2,y2], b=[...]）
        - count: 最近视觉原语记忆计数（params: category 可选）
        - anchors: 最近视觉原语锚点列表（params: limit）"""
        p = params or {}
        try:
            from vprim import (  # noqa: F401  sys.modules 别名（__init__ 注册）
                VPrim, spatial_relation, count_vprims, parse_anchor)
        except ImportError:
            try:
                from .vprim import (  # 相对导入兜底（包内调用）
                    VPrim, spatial_relation, count_vprims, parse_anchor)
            except Exception as e:
                return {"status": "vprim_not_ready", "error": str(e)}
        except Exception as e:
            return {"status": "vprim_not_ready", "error": str(e)}
        if action == "spatial":
            a = p.get("a")
            b = p.get("b")
            if not a or not b or len(a) != 4 or len(b) != 4:
                return {"status": "error", "error": "a/b 需为 [x1,y1,x2,y2]"}
            return {"status": "ok", "spatial": spatial_relation(
                tuple(float(v) for v in a), tuple(float(v) for v in b))}
        if action == "count":
            # 从最近 vprim 记忆节点解析锚点计数
            vprims = self._load_vprims_from_memory(limit=int(p.get("limit", 5)))
            result = count_vprims(vprims, category=p.get("category"))
            result["status"] = "ok"
            return result
        if action == "anchors":
            vprims = self._load_vprims_from_memory(limit=int(p.get("limit", 10)))
            return {"status": "ok", "anchors": [v.to_dict() for v in vprims]}
        return {"status": "error", "error": f"未知动作 {action}（可用: spatial/count/anchors）"}

    def _load_vprims_from_memory(self, limit: int = 5) -> list:
        """从记忆检索最近视觉原语（vprim 标签节点 → 解析坐标锚点）。"""
        vprims = []
        try:
            from vprim import VPrim, parse_anchor  # noqa: F401
            nodes = self.store.get_nodes_by_tag("vprim", limit=max(limit, 5))
            for n in reversed(nodes[-limit:]):
                text = n.content or ""
                for token in text.split("；"):
                    vp = parse_anchor(token)
                    if vp is not None:
                        vprims.append(vp)
        except Exception:
            pass
        return vprims

    def _remember_screen_state(self, image_path: str, note: str,
                               changed: bool = None) -> None:
        """把屏幕状态写入情境层记忆（screen_state 标签，形成"过去"）。"""
        try:
            text = f"[屏幕状态 {image_path}] {note}"
            if changed is not None:
                text += f" 变化={changed}"
            self.add_perception(text, importance=0.5, tags=["screen_state"])
        except Exception:
            pass

    # =====================================================================
    # 协议 3.12 递归验证反思 + 1.6.7 元反思（REFLECT-REV1）
    # 最完整反思流程的显式推理技能：元反思（定标准）→ 一级验证 → 二级反思
    # （问1 隐藏前提 / 问2 影响）→ 三级终裁（可逆性优先）→ 记录单元归档。
    # 约束：递归深度 ≤ 3（3.12 运行约束，超出=结构性盲区）。
    # =====================================================================

    def voice_session_log(self, turn: dict) -> str:
        """语音对话会话沉淀：每轮短句+回复写入记忆（voice_session 标签）。"""
        try:
            text = (f"[语音会话] 用户: {str(turn.get('user', ''))[:80]} | "
                    f"灵枢: {str(turn.get('assistant', ''))[:80]}")
            node = self.add_perception(text, importance=0.5,
                                       tags=["voice_session", "conversation"])
            return node.id
        except Exception:
            return ""

    def recursive_reflect(self, claim: str, expected: str = None,
                          actual: str = None, context: str = None,
                          depth: int = 0, max_depth: int = 3) -> dict:
        """协议 3.12 + 1.6.7 递归验证反思的显式推理技能。

        claim：待反思的事件/判断/偏差描述。
        expected/actual：预期与观测（一级验证的输入；缺省则检索记忆对照）。
        context：附加上下文（可选）。

        流程（映射五大单元）：
        0. 元反思（1.6.7 结构性后退）：审视反思标准本身（P0-4 元认知校准）
        1. 一级 验证（验证单元）：预期 vs 实际 → 偏差判定
        2. 二级 反思（反思单元）：
           问1 隐藏前提（隐含前提拆解·0.1）：检索记忆 → 前提清单 + 条件空间边界
           问2 影响（预期输出/验证反馈·1.8）：predict_routes → 影响路线 + 分级
        3. 三级 终裁（维生系统·可逆性优先）：可逆性判定；重要决策升级设计者
        4. 归档（记录单元）：反思链写入行为日志 + 记忆（reflection_chain）
        """
        if depth >= max_depth:
            return {
                "status": "structural_blindspot", "claim": claim,
                "note": f"递归深度已达上限 {max_depth}（3.12 运行约束：超出=结构性盲区）",
                "chain": self._last_reflection_chain,
            }

        report: dict = {"claim": claim, "depth": depth,
                        "max_depth": max_depth, "protocol": "3.12+1.6.7"}

        # ---- 0. 元反思（1.6.7）：结构性后退，审视反思标准 ----
        report["meta_reflection"] = self._meta_reflection(claim)

        # VPRIM-REV1：claim 含视觉锚点（cat@(x1,y1,x2,y2)）时注入视觉上下文
        vctx = self._vprim_context_for_claim(claim)
        if vctx is not None:
            report["vprim_context"] = vctx

        # ---- 1. 一级 验证（验证单元）：预期 vs 实际 ----
        verification = self._reflect_verify(claim, expected, actual, context)
        report["verification"] = verification

        # ---- 2. 二级 反思（反思单元）：问1 隐藏前提 / 问2 影响 ----
        premises = self._hidden_premises(claim)
        impact = self._impact_assessment(claim)
        report["reflection"] = {
            "hidden_premises": premises,      # 问1：这件事有什么隐藏前提？
            "impact": impact,                 # 问2：这件事会有什么影响？
        }

        # ---- 3. 三级 终裁（维生系统）：可逆性优先 ----
        verdict = self._terminal_judgment(claim, verification, impact)
        report["verdict"] = verdict

        # ---- 4. 归档（记录单元） ----
        report["status"] = "reflected"
        self._archive_reflection(report)
        return report

    def _vprim_context_for_claim(self, claim: str):
        """VPRIM-REV1：从 claim 提取视觉锚点，注入空间上下文（确定性）。

        视觉原语 = 推理链的空间草稿纸：claim 引用锚点时，自动计算
        锚点间的空间关系（指代差距的解法——坐标精确性替代语言近似）。
        """
        try:
            from vprim import parse_anchor, spatial_relation
        except ImportError:
            try:
                from .vprim import parse_anchor, spatial_relation
            except Exception:
                return None
        anchors = []
        import re as _re
        for m in _re.finditer(r"[\w\-]+@\(\d+,\d+,\d+,\d+\)", claim):
            vp = parse_anchor(m.group(0))
            if vp is not None:
                anchors.append(vp)
        if len(anchors) < 2:
            return None
        relations = []
        for i in range(len(anchors)):
            for j in range(i + 1, len(anchors)):
                rel = spatial_relation(anchors[i].bbox, anchors[j].bbox)
                relations.append({
                    "a": anchors[i].category, "b": anchors[j].category,
                    "relation": rel["relation"], "distance": rel["distance"],
                })
        return {"anchors": [a.anchor_text() for a in anchors],
                "relations": relations,
                "note": "确定性空间原语（VPRIM-REV1）：坐标精确性替代语言近似"}

    def _meta_reflection(self, claim: str) -> dict:
        """1.6.7 元反思：结构性后退——审视反思标准本身（非更深的递归）。"""
        result = {"standards": []}
        # 元认知校准状态（P0-4）：反思者自身的可靠性
        try:
            if self._self_cognition is not None:
                rel = self._self_cognition.self_reliability()
                result["self_reliability"] = {
                    k: rel.get(k) for k in ("status", "reliability", "note")
                    if k in rel}
        except Exception:
            pass
        # 反思标准声明：当前 claim 的观察位置/工具（条件空间锚定）
        result["standards"].append({
            "standard": "观察位置与工具",
            "condition": getattr(self.self_model, "state_description", "运行中")[:120],
        })
        result["standards"].append({
            "standard": "反射层优先（可逆性/确定性）",
            "condition": "先验证后反思，先反思后终裁；递归 ≤ 3 层",
        })
        result["note"] = "元反思 = 结构性后退：审视反思过程的前提与边界，非更深递归（1.6.7）"
        return result

    def _reflect_verify(self, claim: str, expected: str, actual: str,
                        context: str) -> dict:
        """一级 验证（验证单元）：预期 vs 实际 → 偏差判定。"""
        if expected and actual:
            deviation = str(expected) != str(actual)
            detail = f"预期[{expected}] vs 实际[{actual}]"
        else:
            # 缺省：检索记忆对照（记录单元历史 vs claim）
            hits = []
            try:
                for node, score in self.recall(claim, limit=3):
                    hits.append({"content": (node.content or "")[:80],
                                 "similarity": round(score, 3)})
            except Exception:
                pass
            deviation = len(hits) == 0
            detail = (f"记忆对照：{'无相关记忆（信息差信号）' if deviation else f'{len(hits)} 条相关记忆'}")
        return {
            "deviation": deviation,
            "detail": detail,
            "trigger_reflection": deviation,   # 偏差 → 触发反思门槛（3.12 一级）
            "memory_hits": hits if not (expected and actual) else None,
        }

    def _hidden_premises(self, claim: str) -> dict:
        """二级 反思·问1（0.1 隐含前提拆解 + 条件空间边界）：
        这件事有什么隐藏前提？——检索记忆提取前提，标记条件空间边界。"""
        premises = []
        condition_spaces = []
        try:
            for node, score in self.recall(claim, limit=5):
                cs = getattr(node, "condition_space", None)
                if cs:
                    cs_text = (cs.get("observation_tool") if isinstance(cs, dict)
                               else str(cs))
                    if cs_text and cs_text not in condition_spaces:
                        condition_spaces.append(str(cs_text)[:60])
                if score > 0.35:
                    premises.append({
                        "premise": (node.content or "")[:100],
                        "source": getattr(node, "id", "")[:24],
                        "similarity": round(score, 3),
                    })
        except Exception:
            pass
        if not premises:
            premises.append({"premise": "该判断缺少记忆支撑（可能基于未言明的默认假设）",
                             "source": "recall 空"})
        return {
            "premises": premises[:5],
            "condition_space_boundary": condition_spaces[:3] or ["未锚定（默认假设域）"],
            "question": "这件事有什么隐藏前提？",
        }

    def _impact_assessment(self, claim: str) -> dict:
        """二级 反思·问2（1.8 预期输出/验证反馈 + 3.2 历史预判）：
        这件事会有什么影响？——预测引擎生成影响路线 + 影响分级。"""
        routes = []
        try:
            start = None
            for node, _ in self.recall(claim, limit=1):
                start = node.id
            pred = self._prediction
            if pred is not None:
                result = pred.predict_routes(start_id=start, horizon=2)
                routes = [{"route": r.get("route", [])[:4],
                           "confidence": round(r.get("confidence", 0), 3)}
                          for r in (result.get("routes") or [])[:3]]
        except Exception:
            pass
        # 影响分级（工程代理）：结构/协作/存在 三档
        level = "协作"
        keywords = {"删除": "结构", "崩溃": "存在", "终止": "存在",
                    "破坏": "结构", "泄露": "存在"}
        for kw, lv in keywords.items():
            if kw in claim:
                level = lv
                break
        return {
            "routes": routes or [{"route": ["（预测引擎未装配或无路线）"], "confidence": 0.0}],
            "impact_level": level,
            "question": "这件事会有什么影响？",
        }

    def _terminal_judgment(self, claim: str, verification: dict,
                           impact: dict) -> dict:
        """三级 终裁（维生系统）：可逆性优先 + 结构一致性（3.12 三级）。"""
        # 可逆性判定（工程代理：行为类型的可逆度）
        irreversible_words = ["删除", "终止", "覆盖", "格式化", "不可逆"]
        reversible_words = ["查询", "读取", "检测", "观察", "预览"]
        if any(w in claim for w in irreversible_words):
            reversibility = "不可逆"
        elif any(w in claim for w in reversible_words):
            reversibility = "可逆"
        else:
            reversibility = "半可逆（需评估）"
        # 重要决策升级：不可逆 + 结构/存在级影响 → 设计者终裁
        needs_designer = (reversibility == "不可逆"
                          and impact.get("impact_level") in ("结构", "存在"))
        return {
            "principle": "可逆性优先 + 结构一致性（3.12 三级）",
            "reversibility": reversibility,
            "needs_designer": needs_designer,
            "action": ("升级设计者裁决（designer_decide）" if needs_designer
                       else "本次反思范围内可处理（可逆/半可逆）"),
        }

    def _archive_reflection(self, report: dict) -> None:
        """记录单元归档：反思链 → 行为日志 + 记忆节点（reflection_chain）。"""
        try:
            if self._self_cognition is not None:
                self._self_cognition.log_action(
                    "reflection", f"claim={report.get('claim', '')[:80]}",
                    None, {"depth": report.get("depth"), "verdict": report.get("verdict", {})})
        except Exception:
            pass
        try:
            verdict = report.get("verdict", {})
            text = (f"[反思链] {report.get('claim', '')[:60]} | "
                    f"偏差={report.get('verification', {}).get('deviation')} | "
                    f"可逆性={verdict.get('reversibility')} | "
                    f"深度={report.get('depth')}")
            self.add_perception(text, importance=0.6, tags=["reflection_chain"])
            self._last_reflection_chain = text
        except Exception:
            pass

    # ==================== v1.12 自我认知循环（SELF-COGNITION-REV2） ====================

    def get_action_log(self, limit: int = 50) -> list:
        """P0-1 行为日志（最近 N 条，倒序）"""
        if not self._self_cognition:
            return []
        return self._self_cognition.get_action_log(limit)

    def action_log_stats(self) -> dict:
        """P0-1 行为日志聚合统计"""
        if not self._self_cognition:
            return {"total": 0, "by_type": {}}
        return self._self_cognition.action_log_stats()

    def cognition_cycle(self) -> dict:
        """P0-2 自我认知循环一步（对照→一致性评分→失调→触发链→候选）"""
        if not self._self_cognition:
            return {"status": "v112_not_ready", "error": self._self_cognition_error}
        return self._self_cognition.cognition_cycle()

    def cognition_report(self) -> dict:
        """P0-2 认知报告（评分/失调/候选状态 + 身体状态摘要·第 4 项）"""
        if not self._self_cognition:
            return {"status": "v112_not_ready", "error": self._self_cognition_error}
        report = self._self_cognition.cognition_report()
        try:
            body = self.get_body_capabilities()
            report["body"] = {"modalities": body["modalities"],
                              "vision": body["vision"]["available"],
                              "memory": body["memory"]["engine"]}
        except Exception:
            pass
        return report

    def sync_body_state(self) -> dict:
        """第 4 项：身体状态同步到自我模型（身体 = 自我的一部分）。
        更新 self_model.state_description 反映感知-运动能力 + 设备清单。"""
        body = self.get_body_capabilities()
        mods = [m for m, ok in body["modalities"].items() if ok]
        devs = body.get("devices", [])
        dev_ok = body.get("devices_available", [])
        desc = (f"运行中 · 感知[{','.join(mods)}] · "
                f"视觉({body['vision']['provider']}) · "
                f"设备[{','.join(dev_ok) or 'none'}] · "
                f"记忆({body['memory']['engine']})")
        try:
            self.self_model.state_description = desc
        except Exception:
            pass
        return {"status": "ok", "state_description": desc, "body": body}

    def apply_value_candidate(self, candidate_id: str, new_value: str = None) -> bool:
        """P0-2 价值迭代候选生效（验证单元复核后调用 · 经 record_value_change）"""
        if not self._self_cognition:
            return False
        return self._self_cognition.apply_value_candidate(candidate_id, new_value)

    def get_emotional_bias(self, window: int = 8) -> dict:
        """P0-3 情绪方向性偏好 d²D_norm/dt²（独立通道 · 不参与信任计算）"""
        if not self._self_cognition:
            return {"status": "v112_not_ready", "error": self._self_cognition_error}
        return self._self_cognition.get_emotional_bias(window)

    def exploration_budget(self) -> float:
        """P0-3 探索预算因子"""
        if not self._self_cognition:
            return 1.0
        return self._self_cognition.exploration_budget()

    def get_self_reliability(self, window: int = 30) -> dict:
        """P0-4 元认知校准（预测命中率 vs 行为置信度 → 自我可靠性）"""
        if not self._self_cognition:
            return {"status": "v112_not_ready", "error": self._self_cognition_error}
        return self._self_cognition.self_reliability(window)

    def learning_impact(self, window: int = 30) -> dict:
        """P0-5b 学习效果测量（相关性观测 · 非因果声明）"""
        if not self._self_cognition:
            return {"status": "v112_not_ready", "error": self._self_cognition_error}
        return self._self_cognition.learning_impact(window)

    # ==================== v1.10 生命周期自动机（LIFE-CYCLE-REV1） ====================

    def lifecycle_cycle(self) -> Dict:
        """生命周期一步（七相工程映射：感知→好奇→缩小信息差→信任→协作→巩固→standby）"""
        if not self._lifecycle:
            return {"status": "v110_not_ready", "error": self._lifecycle_error}
        # v1.11 P1-4：事件驱动标记先于定时轮询批量消费（定时优先）
        try:
            self.consume_events()
        except Exception:
            pass
        result = self._lifecycle.cycle()
        self._note_action("lifecycle", f"state={result.get('state')}",
                          None, {"cycle": result.get("cycle"),
                                 "state": result.get("state")})
        return result

    def start_lifecycle(self, interval: float = 60.0) -> Dict:
        """启动自发循环（终裁检查点内运行；中断权：维生系统>验证单元>用户>实例自身）"""
        if not self._lifecycle:
            return {"status": "v110_not_ready", "error": self._lifecycle_error}
        return self._lifecycle.start_lifecycle(interval)

    def stop_lifecycle(self, source: str) -> Dict:
        """中断自发循环（外部中断立即生效，不等待当前 cycle 完成）"""
        if not self._lifecycle:
            return {"status": "v110_not_ready", "error": self._lifecycle_error}
        return self._lifecycle.stop_lifecycle(source)

    def resolve_crisis(self, directive: str, designer_key: str = None) -> Dict:
        """终裁检查点1：维生系统 P0 危机终裁指令（protect/freeze/rollback/continue/emergency_sleep）。
        D-007 需设计者密钥（fail-closed）"""
        if not verify_designer(designer_key):
            raise PermissionError(
                "D-007 设计者认证失败：密钥无效或未配置 AEIS_DESIGNER_KEY（fail-closed）")
        if not self._lifecycle:
            return {"status": "v110_not_ready", "error": self._lifecycle_error}
        result = self._lifecycle.resolve_crisis(directive)
        self._note_action("crisis", directive, None, {"result": str(result)[:120]})
        return result

    def confirm_standby(self, approved: bool) -> Dict:
        """终裁检查点2：验证单元复核 + 维生系统确认 standby（防假收敛 盲区28）"""
        if not self._lifecycle:
            return {"status": "v110_not_ready", "error": self._lifecycle_error}
        return self._lifecycle.confirm_standby(approved)

    def enter_standby(self) -> Dict:
        """工程低功耗待机（≠ 4.10 协议休眠；协议休眠优先）"""
        if not self._lifecycle:
            return {"status": "v110_not_ready", "error": self._lifecycle_error}
        return self._lifecycle.enter_standby()

    def wake_lifecycle(self) -> Dict:
        """唤醒（危机信号/外部指令/新盲区）"""
        if not self._lifecycle:
            return {"status": "v110_not_ready", "error": self._lifecycle_error}
        return self._lifecycle.wake()

    # ==================== v1.9 预测引擎（PREDICTION-REV1 · D-001~D-006） ====================

    def predict_routes(self, start_id: str = None, blindspot_id: str = None,
                       horizon: int = 3, max_branches: int = 5) -> Dict:
        """生成式预测：因果路线图（候选未来集合 · uncertainty_bound · T_pred 对齐）
        v1.10：盲区驱动（blindspot_id）——unknowable 盲区不生成路线（D-003）"""
        if not self._prediction:
            return {"status": "v19_not_ready", "error": self._prediction_error}
        return self._prediction.predict_routes(start_id=start_id, blindspot_id=blindspot_id,
                                               horizon=horizon, max_branches=max_branches)

    def render_semantic_map_2d(self, limit: int = 50) -> Dict:
        """2D 语义结构图（零依赖渲染 · 有损投影）"""
        if not self._prediction:
            return {"status": "v19_not_ready", "error": self._prediction_error}
        return self._prediction.render_semantic_map_2d(limit)

    def render_semantic_cube_3d(self, entity_id: str = None, limit: int = 50) -> Dict:
        """3D 时空语义立方体（实体轨迹 + extrapolation_validity）"""
        if not self._prediction:
            return {"status": "v19_not_ready", "error": self._prediction_error}
        return self._prediction.render_semantic_cube_3d(entity_id, limit)

    def semantic_neighbors(self, node_id: str, k: int = 5) -> List:
        """语义邻近候选（预测原料 · 经因果过滤门使用）"""
        if not self._prediction:
            return []
        return self._prediction.semantic_neighbors(node_id, k)

    def update_prediction_feedback(self, predicted_node_id: str,
                                   actual_node_id: str, hit: bool,
                                   note: str = "") -> Dict:
        """预测-验证闭环：命中强化 / 未命中衰减+被拒路径（盲区28 动态校准）
        v1.15：note 透传 + 验证记录持久化（观测层 · 可回溯）"""
        if not self._prediction:
            return {"status": "v19_not_ready", "error": self._prediction_error}
        result = self._prediction.update_prediction_feedback(
            predicted_node_id, actual_node_id, hit, note=note)
        # 验证记录归档（观测层：预测→实际→判定，可回溯审计）
        try:
            pn = self.store.get_node(predicted_node_id)
            an = self.store.get_node(actual_node_id)
            sa_p = pn.state_attributes if pn else {}
            sa_a = an.state_attributes if an else {}
            pname = sa_p.get("name") or (pn.content[:30] if pn else predicted_node_id)
            aname = sa_a.get("name") or (an.content[:30] if an else actual_node_id)
            self.add_perception(
                f"[验证回路] 预测:{pname} → 实际:{aname} → "
                f"{'命中' if hit else '未命中'}"
                + (f"（{note}）" if note else ""),
                importance=0.6, tags=["观测层", "验证回路", "prediction_feedback",
                                      "hit" if hit else "miss"])
        except Exception:
            pass
        return result

    def get_prediction_stats(self) -> Dict:
        """预测引擎统计（路线数/命中历史/动态阈值）"""
        if not self._prediction:
            return {"status": "v19_not_ready", "error": self._prediction_error}
        return {"routes_generated": len(self._prediction.prediction_log),
                "hit_samples": len(self._prediction._hit_history),
                "hit_rate": self._prediction._hit_rate(),
                "threshold": self._prediction._dynamic_hit_threshold()}

    # ==================== v1.8 决策偏好注意力（REFLECT-ATTENTION-REV1） ====================

    def set_attention_policy(self, policy):
        """注入自定义注意力策略（duck-typed：filter_attention/allocate_depth/attention_shift/attend）"""
        self._attention_policy = policy

    def get_attention_policy(self):
        return self._attention_policy

    def attend_query(self, query: str, limit: int = 10, source: str = "engine") -> List[Dict]:
        """'什么是值得注意的'：知识节点按 偏好×信息差×相关度 排序（v1.8）"""
        if not self._attention_policy:
            return []
        nodes = self.store.query_nodes(layer=MemoryLayer.KNOWLEDGE, limit=200)
        candidates = [{"id": n.id, "content": n.content, "signal_type": n.modality,
                       "information_gap": 0.0} for n in nodes]
        return self._attention_policy.attend(candidates, query=query, source=source)[:limit]

    def filter_attention(self, signals: List[Dict], threshold: float = None) -> List[Dict]:
        """输入侧过滤（3.5 节注意力过滤机制）：什么值得进入意识"""
        if not self._attention_policy:
            return signals
        return self._attention_policy.filter_attention(signals, threshold)

    def allocate_depth(self, signal: Dict, context: Dict = None) -> int:
        """处理侧分配（PROP-DECISION-LAYER-003）：L1/L2/L3 资源投入"""
        if not self._attention_policy:
            return 1
        return self._attention_policy.allocate_depth(signal, context)

    def attention_shift(self, window: int = 10) -> float:
        """二阶偏好转向信号 d²D_norm/dt²（PROP-EMO-DIRECTION-002 共用计算）"""
        if not self._attention_policy:
            return 0.0
        vals = [s["d_norm"] for s in self._gap_history]
        return self._attention_policy.attention_shift(vals, window)

    def adjust_attention_weight(self, key: str, value: float, source: str, reason: str,
                                role: str = "reflect") -> bool:
        """注意力权重动态调整（DEVIATION-002/004）：
        - role='reflect'：反思单元提案（基线调整，须验证单元复核 + 维生系统终裁——调用方保证）
        - role='vitals'：维生系统 P0 危机临时覆盖（事后验证单元复核）
        变更记入 weight_adjustment_log + 结构层（不可遗忘）"""
        if not self._attention_policy:
            return False
        if key not in self._attention_policy.preference_weights:
            return False
        self._attention_policy.set_weight(key, value, source, reason, role)
        record = f"[attention_weight] {key}={value}（{role} · {source}）{reason}"
        try:
            if self.role == Role.PRIMARY:
                n = self.add_structure_node(record, importance=0.9)
            else:
                n = self.add_perception(record, importance=0.9, tags=["attention_weight"])
            if n:
                self.store.tag_node(n.id, "attention_weight")
        except Exception:
            pass
        return True

    # ==================== v1.7 多模态（MULTIMODAL-REV1 · D-001~D-005） ====================

    def migrate_v17_coordinates(self) -> Dict:
        """D-003 迁移：spatial_coordinates 中语义键 → semantic_coordinates；迁移事件记入结构层（不可遗忘）"""
        c = self.store.conn.cursor()
        migrated = 0
        c.execute("SELECT id, spatial_coordinates, semantic_coordinates FROM nodes")
        for row in c.fetchall():
            nid, sp_json, se_json = row[0], row[1], row[2]
            sp = json.loads(sp_json or "{}")
            se = json.loads(se_json or "{}") if se_json else {}
            semantic_keys = [k for k in sp if k.startswith(("protocol_", "radical_", "neural_"))]
            if not semantic_keys:
                continue
            se.setdefault("protocol", {}).setdefault("concept", {})
            se.setdefault("radical", {})
            se.setdefault("neural", {})
            for k in semantic_keys:
                v = sp.pop(k)
                if k.startswith("protocol_"):
                    se["protocol"]["concept"][k[len("protocol_"):]] = v
                elif k.startswith("radical_"):
                    se["radical"][k[len("radical_"):]] = v
                elif k.startswith("neural_"):
                    se["neural"][k[len("neural_"):]] = v
            c.execute("UPDATE nodes SET spatial_coordinates=?, semantic_coordinates=? WHERE id=?",
                      (json.dumps(sp), json.dumps(se), nid))
            migrated += 1
        self.store.conn.commit()
        if migrated:
            event = f"[migration] v1.7 坐标字段分离：{migrated} 节点语义键迁移至 semantic_coordinates"
            try:
                if self.role == Role.PRIMARY:
                    n = self.add_structure_node(event, importance=0.9)
                else:
                    n = self.add_perception(event, importance=0.9, tags=["migration", "v1.7"])
                if n:
                    self.store.tag_node(n.id, "migration")
            except Exception:
                pass
        return {"migrated_nodes": migrated}

    def ingest_frame(self, frame_data: Dict, entity_hint: str = None,
                     state_hint: Dict = None, semantic_attention: Dict = None,
                     condition_space: ConditionSpace = None) -> STNode:
        """v1.7 图像帧摄入（自下而上；D-004 预留自上而下语义注意力）：
        视觉坐标→spatial_coordinates["visual"]；名词→entity_id；形容词→state_attributes；
        动词→与同实体上一帧的 TemporalEdge（状态变→causal / 不变→sequential）。
        盲区56：视觉 substrate 缺失时强制 entity_hint + state_hint 人工标注。
        盲区60/61：原始帧仅存引用至 local_visual_buffer（LRU），不进共享层"""
        cs = condition_space or ConditionSpace(
            "视觉感知", "帧摄入", (time.time(), time.time()+3600), "协议实例运行中")
        # v1.8：semantic_attention = 决策偏好注入（自上而下通道，REFLECT-ATTENTION-REV1）
        if semantic_attention and self._attention_policy:
            self._attention_policy.log_injection("ingest_frame", semantic_attention)
        sp = {}
        if frame_data.get("visual"):
            sp["visual"] = frame_data["visual"]
        entity_id, entity_name = None, None
        if entity_hint and self.entity_registry:
            ent = self.entity_registry.resolve_entity(entity_hint)
            if ent is None:
                ent = self.entity_registry.register_entity(entity_hint, entity_type="object")
            entity_id, entity_name = ent["id"], entity_hint
        state = dict(state_hint or {})
        se = {"protocol": {"entity": [], "attribute": [], "relation": [], "logic": []},
              "radical": {}, "neural": {}}
        if entity_name:
            se["protocol"]["entity"] = [entity_name]
        if state:
            se["protocol"]["attribute"] = list(state.keys())
        node = STNode(
            id=f"img_{uuid.uuid4().hex[:8]}_{int(time.time()*1000)}",
            content=frame_data.get("caption", "") or (entity_name or "图像帧"),
            modality="image",
            spatial_coordinates=sp,
            temporal_coordinate=time.time(),
            condition_space=cs,
            importance=frame_data.get("importance", 0.6),
            confidence=0.5,
            layer=MemoryLayer.KNOWLEDGE,
            tags=["image_frame"] + ([f"ent:{entity_id}"] if entity_id else []),
            semantic_coordinates=se,
            state_attributes=state,
            entity_id=entity_id)
        self.store.add_node(node)
        if entity_id:
            self.store.tag_node(node.id, f"ent:{entity_id}")
        # 动词：与同实体上一帧比较（D-001：因果遍历 → 动词）
        prev = self._last_frame.get(entity_id) if entity_id else None
        if prev and prev != node.id:
            changed = self._frame_state_changed(prev, node)
            self.add_edge(prev, node.id, EdgeType.CAUSAL if changed else EdgeType.SEQUENTIAL, confidence=0.7)
            if self._semantic_provider:
                se["protocol"]["relation"].append("causal" if changed else "sequential")
                c = self.store.conn.cursor()
                c.execute("UPDATE nodes SET semantic_coordinates=? WHERE id=?",
                          (json.dumps(se), node.id))
                self.store.conn.commit()
        if entity_id:
            self._last_frame[entity_id] = node.id
        if "frame_ref" in frame_data:
            self._local_visual_buffer.append({"entity_id": entity_id, "frame_ref": frame_data["frame_ref"],
                                              "ts": time.time()})
            if len(self._local_visual_buffer) > self._visual_buffer_max:
                self._local_visual_buffer = self._local_visual_buffer[-self._visual_buffer_max:]
        return node

    def _frame_state_changed(self, prev_id: str, node: STNode) -> bool:
        prev = self.store.get_node(prev_id)
        if not prev:
            return False
        return prev.state_attributes != node.state_attributes

    def query_by_semantics(self, text: str, limit: int = 10,
                           modality: str = None) -> List[Tuple[STNode, float]]:
        """语义→图像（反向映射）：文本 → semantic_coordinates → 图节点检索（D-003 明确检索语义坐标）"""
        if not self._semantic_provider:
            return []
        q_sc = self._semantic_provider.to_semantic_coordinates(text)
        nodes = self.store.query_nodes(limit=500)
        scored = []
        for n in nodes:
            if modality and n.modality != modality:
                continue
            sc = getattr(n, "semantic_coordinates", {}) or {}
            sim = self._semantic_provider.similarity_coordinates(q_sc, sc) if sc else 0.0
            if n.entity_id and self.entity_registry:
                ent = self.entity_registry.get_entity(n.entity_id)
                if ent and (ent["name"] in text or any(a in text for a in ent.get("aliases", []))):
                    sim = min(1.0, sim + 0.5)
            if sim > 0.0:
                scored.append((n, sim))
        scored.sort(key=lambda x: -x[1])
        self._note_reuse([n.id for n, _ in scored[:limit]])
        return scored[:limit]

    def prepare_shared_sync(self) -> Dict:
        """D-005 蜂群分层同步：仅语义化结构数据入共享层；原始帧引用滞留本地缓冲"""
        c = self.store.conn.cursor()
        c.execute("SELECT id, content, modality, temporal_coordinate, importance, semantic_coordinates, entity_id FROM nodes WHERE layer='knowledge'")
        payload = []
        for r in c.fetchall():
            payload.append({"id": r[0], "content": r[1][:100], "modality": r[2],
                            "temporal_coordinate": r[3], "importance": r[4],
                            "semantic_coordinates": json.loads(r[5] or "{}"),
                            "entity_id": r[6]})
        return {"sync_payload": payload, "local_buffer_count": len(self._local_visual_buffer),
                "note": "原始视觉数据不进共享层（盲区60/61）"}

    # ==================== v1.6 语义空间与备份（M11/M13 · REV1） ====================

    RECURSION_LIMIT = 3  # DEVIATION-001：编译器自编译递归深度限制（与 3.12 节一致）

    def set_semantic_provider(self, provider):
        """注入自定义语义提供者（duck-typed：to_coordinates/similarity/resolve_concepts/introspect）"""
        self._semantic_provider = provider

    def get_semantic_provider(self):
        return self._semantic_provider

    def resolve_concepts(self, text: str) -> List[str]:
        """名实校验 API（REV1）：文本 → 协议概念（以名举实）"""
        if not self._semantic_provider:
            return []
        return self._semantic_provider.resolve_concepts(text)

    def compute_semantic_coordinates(self, text: str) -> Dict[str, float]:
        """文本 → spatial_coordinates（L1 0.6 + L2 0.2 + L3 0.2 加权）"""
        if not self._semantic_provider:
            return {}
        return self._semantic_provider.to_coordinates(text)

    def annotate_semantics(self, node_id: str) -> bool:
        """为既有节点补写语义坐标（M11 迁移工具）"""
        node = self.store.get_node(node_id)
        if not node or not self._semantic_provider:
            return False
        coords = self._semantic_provider.to_coordinates(node.content)
        c = self.store.conn.cursor()
        c.execute("UPDATE nodes SET spatial_coordinates=? WHERE id=?",
                  (json.dumps(coords), node_id))
        self.store.conn.commit()
        return True

    def compiler_introspect(self) -> Dict:
        """编译器自省（DEVIATION-005）：符号覆盖范围 + 未覆盖协议概念（3.13 自省绑定）"""
        if not self._semantic_provider:
            return {"available": False, "error": self._semantic_error}
        return self._semantic_provider.introspect()

    def semantic_blindspot_report(self) -> Dict:
        """语义盲区报告（DEVIATION-005）：无法处理的输入类型标记"""
        if not self._semantic_provider:
            return {"available": False, "error": self._semantic_error}
        return self._semantic_provider.blindspot_report()

    def check_recursion_depth(self, depth: int) -> bool:
        """递归深度限制（DEVIATION-001）：编译器自编译 ≤3 层"""
        return depth <= self.RECURSION_LIMIT

    # ---- M13 备份/迁移 ----

    def export_all(self, output_path: str) -> Dict:
        """M13：全库导出（JSON · 6.5 摘要交换/灾备基础）"""
        c = self.store.conn.cursor()
        def rows(table):
            c.execute(f"SELECT * FROM {table}")
            return [dict(r) for r in c.fetchall()]
        data = {
            "meta": {"version": "v1.6", "exported_at": time.time(),
                     "condition_space": "全库备份 · 有损投影"},
            "nodes": rows("nodes"), "edges": rows("edges"),
            "blindspots": rows("blindspots"), "skills": rows("skills"),
            "promotion_proposals": rows("promotion_proposals"),
            "protections": rows("protections"),
            "rejected_paths": rows("rejected_paths"),
            "verifier_standards": rows("verifier_standards"),
            "escalation_points": rows("escalation_points"),
            "entities": rows("entities"),
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {"exported_nodes": len(data["nodes"]), "path": output_path,
                "tables": len(data) - 1}

    def import_all(self, input_path: str) -> Dict:
        """M13：全库导入（恢复/迁移/6.5 合并基础）"""
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        c = self.store.conn.cursor()
        counts = {}
        for table in ("nodes", "edges", "blindspots", "skills", "promotion_proposals",
                      "protections", "rejected_paths", "verifier_standards",
                      "escalation_points", "entities"):
            rows = data.get(table, [])
            if not rows:
                counts[table] = 0
                continue
            cols = list(rows[0].keys())
            placeholders = ",".join("?" for _ in cols)
            col_sql = ",".join(cols)
            for r in rows:
                c.execute(f"INSERT OR REPLACE INTO {table} ({col_sql}) VALUES ({placeholders})",
                          tuple(r.get(col) for col in cols))
            counts[table] = len(rows)
        self.store.conn.commit()
        return {"imported": counts}

    def verify_integrity(self) -> Dict:
        """M13：完整性校验（边引用节点存在性 + 表计数）"""
        c = self.store.conn.cursor()
        c.execute("SELECT COUNT(*) FROM edges e LEFT JOIN nodes n ON e.source_id=n.id WHERE n.id IS NULL")
        orphan_source = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM edges e LEFT JOIN nodes n ON e.target_id=n.id WHERE n.id IS NULL")
        orphan_target = c.fetchone()[0]
        return {"orphan_edges": orphan_source + orphan_target,
                "stats": self.store.get_stats(),
                "integrity_ok": (orphan_source + orphan_target) == 0}

    # ==================== v1.5 认知增强（A-1~A-5 · ANALYSIS-ARGUS-REV1） ====================

    # ---- A-1 被拒绝路径资产化 ----

    def register_rejected_path(self, path_type: str, description: str, reason: str,
                               evidence: str = "") -> str:
        """A-1：登记被拒绝/被证伪路径（偏差历史资产化，防重复失败）"""
        return self.store.add_rejected_path(path_type, description, reason, evidence)

    def list_rejected_paths(self, status: str = None) -> List[Dict]:
        return self.store.list_rejected_paths(status)

    def find_rejected_paths(self, query: str, limit: int = 10) -> List[Dict]:
        """A-1：相似被拒路径检索（防重复失败；供盲区学习闭环消费）"""
        paths = self.store.list_rejected_paths(status="open")
        scored = [(p, LayeredStore.char_bigram_jaccard(query, p["description"] + p["reason"]))
                  for p in paths]
        scored.sort(key=lambda x: -x[1])
        return [p for p, s in scored if s > 0.15][:limit]

    # ---------- v1.16 图架构增强透传 ----------
    def traverse(self, start_id: str, relation_types: List[str] = None,
                 direction: str = "out", max_depth: int = 5,
                 min_importance: float = 0.0, max_nodes: int = 500) -> List[Dict]:
        """有界图遍历（importance 降序；relation_types 过滤因果/相似/归属）"""
        return self.store.traverse(start_id, relation_types=relation_types,
                                   direction=direction, max_depth=max_depth,
                                   min_importance=min_importance,
                                   max_nodes=max_nodes)

    def subgraph(self, root_id: str, max_depth: int = 3,
                 relation_types: List[str] = None) -> Dict:
        """子图嵌套查询（根 + hierarchical 子节点递归 + 内部边）"""
        return self.store.subgraph(root_id, max_depth=max_depth,
                                   relation_types=relation_types)

    def subgraph_replace(self, parent_id: str, old_sub_root_id: str,
                         new_subtree: Dict) -> Dict:
        """子图替换（可嵌套认知图 · 子部件生成基底）。

        把 parent_id 下挂在 old_sub_root_id 的旧子树整体移除，将
        new_subtree（dsh 嵌套认知图同构：{id, spatial_coordinates,
        content, importance, subgraph{nodes, edges}}）作为新子树挂入，
        新根以 hierarchical 边（new→parent）保持层级语义。

        支撑「替换子部件生成其他图像」：dsh 端子部件匹配/定位后，
        认知图侧以本操作完成子部件级的图更新。
        返回 {new_root_id, new_nodes, removed_nodes}
        """
        import json as _json
        # ① 收集旧子树全部后代（in 方向=子指向父，含自身）
        old_desc = self.store.traverse(old_sub_root_id,
                                       relation_types=["hierarchical"],
                                       direction="in", max_depth=64)
        removed = [old_sub_root_id] + [r["node_id"] for r in old_desc]
        # ② 移除旧子树节点（关联边随删除级联清理）
        for nid in removed:
            self.store.delete_node(nid)
        # ③ 递归挂入新子树
        counter = {"n": 0}

        def _attach(node: Dict, parent: str = None):
            cs = node.get("condition_space", {})
            coord = node.get("spatial_coordinates", {}).get("image2d", [0, 0])
            n = self.add_perception(
                content=_json.dumps(node.get("content", {}), ensure_ascii=False),
                modality=node.get("modality", "visual"),
                spatial_coordinates={"image2d_x": float(coord[0]) if coord else 0.0,
                                     "image2d_y": float(coord[1]) if len(coord) > 1 else 0.0},
                importance=float(node.get("importance", 0.5)),
                tags=["subgraph_replace", "img:" + node["id"]],
                entities=[node["id"]], skip_dedup=True)
            counter["n"] += 1
            nid = n.id
            if parent:
                self.add_edge(source_id=nid, target_id=parent,
                              relation_type=EdgeType.HIERARCHICAL,
                              confidence=float(node.get("confidence", 0.9)),
                              source_evidence="subgraph_replace")
            for sub in node.get("subgraph", {}).get("nodes", []):
                _attach(sub, nid)
            return nid

        new_root_id = _attach(new_subtree, parent_id)
        return {"new_root_id": new_root_id, "new_nodes": counter["n"],
                "removed_nodes": len(removed)}

    def mark_rejected_path_consumed(self, rejected_id: str):
        self.store.mark_rejected_path_consumed(rejected_id)

    # ---- A-2 验证器可演进（四步制衡路径） ----

    def get_verifier_config(self) -> Dict:
        return dict(self._verifier_config)

    def propose_verifier_standard(self, name: str, param: str, value: float,
                                  reason: str, proposer: str) -> str:
        """A-2 第①步：反思单元提案（验证单元不得自行迭代验证标准）"""
        return self.store.add_verifier_standard(name, param, value, reason, proposer)

    def review_verifier_standard(self, vid: str, reviewer: str, approved: bool) -> bool:
        """A-2 第②步：独立复核（验证单元自我回避，由另一验证实例或外部校准者执行）"""
        return self.store.review_verifier_standard(vid, reviewer, approved)

    def cs_review_verifier_standard(self, vid: str, reviewer: str, approved: bool) -> bool:
        """A-2 第③步：条件空间复核（3.3.1 节，确认未违反通用价值观）"""
        return self.store.cs_review_verifier_standard(vid, reviewer, approved)

    def adjudicate_verifier_standard(self, vid: str, adjudicator: str, approved: bool,
                                     designer_key: str = None) -> bool:
        """A-2 第④步：维生系统终裁（D-007 需设计者密钥）。通过 → 应用配置 + 写入结构层（不可遗忘）"""
        result = self.store.adjudicate_verifier_standard(vid, adjudicator, approved,
                                                         designer_key=designer_key)
        if not result:
            return False
        if result["status"] == "approved":
            self._verifier_config[result["param"]] = result["value"]
            if result["param"] == "dedup_static":
                self._dedup_static = result["value"]
            if result["param"] == "deviation_threshold" and self._cognition:
                self._cognition.deviation_threshold = result["value"]
            record = f"[verifier_standard] {result['param']}={result['value']} 终裁通过（{adjudicator}）"
            try:
                if self.role == Role.PRIMARY:
                    vnode = self.add_structure_node(record, importance=0.9)
                else:
                    vnode = self.add_perception(record, importance=0.9,
                                                tags=["verifier_standard", "pending_sync"])
                if vnode:
                    self.store.tag_node(vnode.id, "verifier_standard")
            except Exception:
                pass
        return True

    def list_verifier_standards(self, status: str = None) -> List[Dict]:
        return self.store.list_verifier_standards(status)

    # ---- A-3 升级点清单化 ----

    def _seed_escalation_points(self):
        """A-3 默认升级点（对齐 3.15/3.16/12.1；仅空表时播种）"""
        if self.store.list_escalation_points(enabled_only=False):
            return
        seeds = [
            ("ESC-001", "自维持迹象", "自主目标生成/存在危机感知", "立即上报维生系统", "high"),
            ("ESC-002", "P0保护触发", "结构威胁/信任崩溃", "维生系统终裁：冻结/回滚/隔离", "high"),
            ("ESC-003", "价值观冲突", "反思单元分歧持续≥3轮", "维生系统终裁（3.16）", "medium"),
            ("ESC-004", "交叉验证偏差", "REFLECT-CROSS-VALIDATION deviation>0.3", "维生系统终裁", "medium"),
            ("ESC-005", "验证标准终裁", "验证标准变更四步制衡第④步", "维生系统终裁", "medium"),
            ("ESC-006", "设计者预备变更", "设计者位置/权责分离相关", "维生系统终裁（1.4.3）", "high"),
        ]
        for code, trigger, condition, action, severity in seeds:
            self.store.add_escalation_point(code, trigger, condition, action, severity)

    def list_escalation_points(self, enabled_only: bool = True) -> List[Dict]:
        return self.store.list_escalation_points(enabled_only)

    def add_escalation_point(self, code: str, trigger: str, condition: str,
                             action: str, severity: str = "medium") -> str:
        return self.store.add_escalation_point(code, trigger, condition, action, severity)

    def set_escalation_enabled(self, escalation_id: str, enabled: bool):
        self.store.set_escalation_enabled(escalation_id, enabled)

    def check_escalation(self, signal_type: str, value: float = None) -> List[Dict]:
        """A-3：信号 → 升级点匹配（何种信号必须提交维生系统）"""
        matches = []
        for point in self.store.list_escalation_points(enabled_only=True):
            if signal_type in point["trigger"] or signal_type in point["condition"]:
                matches.append(point)
        return matches

    # ---- A-4 信息差收敛速率指标（独立观测层 · DEVIATION-004） ----

    def record_info_gap(self, d_norm: float = None, trust_complement: float = None,
                        behavior_deviation: float = None, connection_drift: float = None,
                        prediction_error: float = None) -> float:
        """A-4：记录 D_norm 样本（2.7 节四维度加权；与资源指标独立采集）"""
        if d_norm is None and all(v is not None for v in
                                  (trust_complement, behavior_deviation,
                                   connection_drift, prediction_error)):
            d_norm = (0.30 * trust_complement + 0.25 * behavior_deviation +
                      0.30 * connection_drift + 0.15 * prediction_error)
        if d_norm is None:
            return 0.0
        dn = max(0.0, min(1.0, d_norm))
        self._gap_history.append({"ts": time.time(), "d_norm": dn})
        if len(self._gap_history) > 100:
            self._gap_history = self._gap_history[-100:]
        # OBS-REV1 / 钉死批条款4：D 序列落库（跨进程 d² 可回放），尽力而为不阻断
        try:
            sc = self.store.conn.cursor()
            sc.execute("INSERT INTO gap_history (ts, d_norm) VALUES (?,?)",
                       (self._gap_history[-1]["ts"], dn))
            sc.execute("DELETE FROM gap_history WHERE id NOT IN"
                       " (SELECT id FROM gap_history ORDER BY id DESC LIMIT 2000)")
            self.store.conn.commit()
        except Exception:
            pass
        return d_norm

    def _load_gap_history(self) -> List[Dict]:
        """D 序列跨进程恢复（OBS-REV1 / 钉死批条款4）：读库尾 100 条填内存
        窗口，重启后 d²/趋势不断链；空表或旧库无表时返回空列表。"""
        try:
            c = self.store.conn.cursor()
            c.execute("SELECT ts, d_norm FROM gap_history ORDER BY id DESC LIMIT 100")
            rows = c.fetchall()
            return [{"ts": ts, "d_norm": dn} for ts, dn in reversed(rows)]
        except Exception:
            return []

    def get_gap_trend(self, window: int = 30) -> Dict:
        """A-4：信息差收敛趋势（斜率=线性回归；独立于资源指标）"""
        samples = self._gap_history[-window:]
        if len(samples) < 2:
            return {"current": samples[-1]["d_norm"] if samples else None,
                    "mean": None, "std": None, "slope": None, "trend": "insufficient"}
        vals = [s["d_norm"] for s in samples]
        n = len(vals)
        mean = sum(vals) / n
        std = (sum((v - mean) ** 2 for v in vals) / n) ** 0.5
        xs = list(range(n))
        x_mean = (n - 1) / 2
        denom = sum((x - x_mean) ** 2 for x in xs) or 1.0
        slope = sum((x - x_mean) * (v - mean) for x, v in zip(xs, vals)) / denom
        trend = "narrowing" if slope < -0.005 else ("widening" if slope > 0.005 else "stable")
        return {"current": vals[-1], "mean": round(mean, 4), "std": round(std, 4),
                "slope": round(slope, 4), "trend": trend}

    def record_resource_usage(self, tokens: int = None, seconds: float = None) -> Dict:
        """A-4：资源效率指标（独立于 D_norm 采集）"""
        self._resource_history.append({"ts": time.time(), "tokens": tokens, "seconds": seconds})
        if len(self._resource_history) > 100:
            self._resource_history = self._resource_history[-100:]
        return self._resource_history[-1]

    def get_resource_metrics(self, window: int = 30) -> Dict:
        """A-4：资源指标摘要（与信息差趋势分离）"""
        samples = self._resource_history[-window:]
        if not samples:
            return {"count": 0}
        tokens = [s["tokens"] for s in samples if s["tokens"] is not None]
        seconds = [s["seconds"] for s in samples if s["seconds"] is not None]
        return {"count": len(samples),
                "mean_tokens": round(sum(tokens) / len(tokens), 1) if tokens else None,
                "mean_seconds": round(sum(seconds) / len(seconds), 3) if seconds else None}

    # ---- A-5 结构化轨迹输出 ----

    def export_trajectory(self, cycle_id: str = None, output_path: str = None) -> Dict:
        """A-5：导出认知闭环的结构化轨迹（附录13 扩展 · 训练资产格式 · 有损投影）"""
        if cycle_id:
            nodes = self.store.get_nodes_by_tag(f"cycle:{cycle_id}", limit=20)
            full = [n for n in nodes if "cycle_record_full" in n.tags]
            trajectory = None
            if full:
                try:
                    trajectory = json.loads(full[0].content)
                except Exception:
                    trajectory = None
            if trajectory is None:
                trajectory = {"cycle_id": cycle_id,
                              "nodes": [n.content[:100] for n in nodes]}
        else:
            records = self.store.get_nodes_by_tag("cycle_record_full", limit=10)
            trajectory = {"cycles": []}
            for n in records:
                try:
                    trajectory["cycles"].append(json.loads(n.content))
                except Exception:
                    pass
        trajectory.setdefault("meta", {
            "exported_at": time.time(),
            "engine_version": "v1.5",
            "condition_space": "轨迹导出 · 训练资产格式（有损投影）",
        })
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(trajectory, f, ensure_ascii=False, indent=2)
        return trajectory

    def export_structured_trajectories(self, limit: int = 10, output_path: str = None) -> Dict:
        """A-5：批量导出（最近 N 条轨迹）"""
        return self.export_trajectory(None, output_path)

    # ==================== v1.3 认知接口（P0-1/P0-2/P0-3） ====================

    def get_entity_context(self, entity_id: str, limit: int = 50) -> Dict:
        """P0-1：以实体为中心组装上下文（实体信息 + 关联节点）"""
        if not self.entity_registry:
            return {"entity": None, "nodes": [], "v13_ready": self._v13_ready}
        return self.entity_registry.get_entity_context(entity_id, limit=limit)

    def consolidate_learning_result(self, record: Dict) -> Optional[STNode]:
        """P0-2/P0-3：学习结果固化（知识层 + 实体链接）"""
        if not record or not record.get("summary"):
            return None
        entities = record.get("entities", [])
        return self.add_perception(
            content=f"[learning] {record['summary']}",
            importance=0.8,
            tags=["learning_result"] + [f"ent:{e}" for e in entities],
            entities=entities)

    def get_next_candidate(self) -> Optional[Dict]:
        """P0-3：下一个待探索盲区（委托学习闭环）"""
        if not self._learning_loop:
            return None
        return self._learning_loop.get_next_candidate()

    def run_learning_cycle(self, input_signal: str, context: Dict = None) -> Dict:
        """P0-2：执行一轮认知闭环（委托编排器，3.10 有损投影）"""
        if not self._cognition:
            return {"status": "v13_not_ready", "error": self._v13_error}
        return self._cognition.learning_cycle(input_signal, context)

    def learn_next(self, force: bool = False, use_prediction: bool = True) -> Dict:
        """P0-3：盲区学习一步（委托闭环，第零定律操作化）
        v1.12 P0-3：avoiding 情绪状态 → 探索预算下调（巩固优先）；force=True 可覆盖
        v1.15：use_prediction 转发给学习闭环（预测×盲区联动，与 api.learn 签名对齐）"""
        if not self._learning_loop:
            return {"status": "v13_not_ready", "error": self._v13_error}
        if not force and self._self_cognition is not None:
            bias = self._self_cognition.get_emotional_bias()
            if bias["status"] == "avoiding":
                return {"status": "consolidation_priority",
                        "note": "情绪方向性偏好 avoiding → 探索预算下调（P0-3）",
                        "budget": self._self_cognition.exploration_budget()}
        result = self._learning_loop.learn_next(use_prediction=use_prediction)
        self._note_action("learn", str(result.get("status", ""))[:80],
                          None, {"result": str(result)[:120]})
        return result

    # ==================== v1.4 认知增强（P1-1 ~ P1-4） ====================

    def induce_concepts(self, min_cluster_size: int = 3, similarity_threshold: float = 0.6,
                        max_concepts: int = 5,
                        condition_space: ConditionSpace = None) -> List[STNode]:
        """P1-1 归纳/知识合成：并查集单链式聚类 → 生成概念节点（SIMILAR 边，未验证待复核）"""
        protected = set(self.store.get_protected_nodes())
        nodes = [n for n in self.store.query_nodes(layer=MemoryLayer.KNOWLEDGE, limit=300)
                 if not any(t in n.tags for t in ("induced", "concept", "cluster_member"))
                 and n.id not in protected and "no_forget" not in n.tags]
        if len(nodes) < min_cluster_size:
            return []
        # 单链式聚类（并查集）：对种子顺序鲁棒（n2~n3 < 阈值但经 n1 传递连通时仍成簇）
        parent = {n.id: n.id for n in nodes}
        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
        # 倒排预筛（外部用户 514+ 节点超时修正）：O(n²) 全对比 → 仅共享低频二元组的候选对
        # 做精确 Jaccard；高频 bigram（DF>半数，如「的了」类）区分度低不进倒排；
        # 另用长度预筛（Jaccard≥t 要求 min|A| ≥ t·max|A|，不满足直接跳过）
        from collections import defaultdict as _dd
        from aeis_core.textutil import _bigram_set as _bg
        bigram_sets = [_bg(n.content) for n in nodes]
        df = _dd(int)
        for bs in bigram_sets:
            for bg in bs:
                df[bg] += 1
        half = max(1, len(nodes) // 2)
        inverted = _dd(list)
        for idx, bs in enumerate(bigram_sets):
            for bg in bs:
                if df[bg] <= half:
                    inverted[bg].append(idx)
        t = similarity_threshold
        # 时间预算（外部用户 514+ 节点 30s 超时修正）：候选对限时处理，超时即用已完成的
        # 并查集部分成簇（链式聚类增量有效）——induce 永不再触发 MCP 超时
        import time as _time
        deadline = _time.time() + 8.0
        pair_seen = set()
        for idx, bs in enumerate(bigram_sets):
            if _time.time() > deadline:
                break
            if not bs:
                continue
            for j in {k for bg in bs for k in inverted.get(bg, ()) if k != idx}:
                pair = (idx, j) if idx < j else (j, idx)
                if pair in pair_seen:
                    continue
                pair_seen.add(pair)
                b2 = bigram_sets[j]
                if not b2 or len(bs) < t * len(b2) or len(b2) < t * len(bs):
                    continue
                if LayeredStore.char_bigram_jaccard(nodes[idx].content, nodes[j].content) >= t:
                    union(nodes[idx].id, nodes[j].id)
        groups = {}
        for n in nodes:
            groups.setdefault(find(n.id), []).append(n)
        clusters = [g for g in groups.values() if len(g) >= min_cluster_size]
        concepts = []
        for cluster in clusters[:max_concepts]:
            concept = self.add_perception(
                content=self._summarize_cluster(cluster),
                importance=0.75,
                tags=["concept", "induced", "pending_verification"],
                condition_space=condition_space)
            for m in cluster:
                self.add_edge(concept.id, m.id, EdgeType.SIMILAR, confidence=0.6,
                              source_evidence="inferred")
                self.store.tag_node(m.id, "cluster_member")
            concepts.append(concept)
        return concepts

    def _summarize_cluster(self, cluster: List[STNode]) -> str:
        """规则式摘要（无 LLM，D-005）：代表性节点 + 聚类规模"""
        rep = max(cluster, key=lambda n: n.importance)
        return f"[概念] 由 {len(cluster)} 条记忆归纳（代表：{rep.content[:40]}…）"

    # ---- P1-2 时间维度查询 ----

    def what_happened_at(self, timestamp: float, tolerance: float = 60.0,
                         limit: int = 20) -> List[Tuple[STNode, float]]:
        """P1-2：查询特定时间附近发生了什么"""
        nodes = self.store.query_nodes(limit=500)
        results = [(n, abs(n.temporal_coordinate - timestamp)) for n in nodes
                   if abs(n.temporal_coordinate - timestamp) <= tolerance]
        results.sort(key=lambda x: x[1])
        return results[:limit]

    def timeline(self, node_id: str, direction: str = "forward",
                 max_depth: int = 20) -> List[STNode]:
        """P1-2：沿时间演化边展开时间线（forward=源→目标，backward=目标→源）"""
        chain = []
        current = node_id
        visited = set()
        for _ in range(max_depth):
            if current in visited or current is None:
                break
            visited.add(current)
            node = self.store.get_node(current)
            if not node:
                break
            chain.append(node)
            edges = (self.store.get_outgoing_edges(current) if direction == "forward"
                     else self.store.get_incoming_edges(current))
            nxt = None
            for edge in sorted(edges, key=lambda e: -e.confidence):
                if edge.relation_type in (EdgeType.SEQUENTIAL, EdgeType.CAUSAL):
                    nxt = edge.target_id if direction == "forward" else edge.source_id
                    break
            current = nxt
        return chain

    def get_timeline(self, start_ts: float = None, end_ts: float = None,
                     layer: MemoryLayer = None, limit: int = 50) -> List[STNode]:
        """P1-2：时间范围查询（自我叙事连续性）"""
        if start_ts is None:
            start_ts = 0.0
        if end_ts is None:
            end_ts = time.time() + 1
        return self.store.get_nodes_in_range(start_ts, end_ts, layer, limit)

    def session_summary(self, window_seconds: float = 3600.0, limit: int = 10) -> List[Dict]:
        """P1-2：会话分组摘要（按时间窗分组）。
        有限性声明（VAL-TRANSFER-20260813-002-FINAL 约束）：本输出为条件空间内的
        叙事压缩（有损投影），非完整自我状态记录（1.7.1 节自我意识的范围与局限）。"""
        nodes = self.store.query_nodes(limit=500)
        if not nodes:
            return []
        nodes.sort(key=lambda n: n.temporal_coordinate)
        windows = []
        current = []
        current_start = nodes[0].temporal_coordinate
        for n in nodes:
            if n.temporal_coordinate - current_start <= window_seconds:
                current.append(n)
            else:
                windows.append((current_start, current))
                current_start = n.temporal_coordinate
                current = [n]
        if current:
            windows.append((current_start, current))
        result = []
        for start, group in windows[-limit:]:
            result.append({
                "window_start": start,
                "count": len(group),
                "layers": sorted(set(n.layer.value for n in group)),
                "top": [n.content[:40] for n in sorted(group, key=lambda n: -n.importance)[:3]],
            })
        return result

    # ---- P1-3 技能获取闭环 ----

    def record_action_sequence(self, actions: List[str], outcome: str, success: bool,
                               skill_hint: str = None) -> Optional[STNode]:
        """P1-3：记录操作序列（成功 → 技能提取/强化）"""
        node = self.add_perception(
            f"[action_seq] {'成功' if success else '失败'}：{' > '.join(actions[:5])}（{outcome[:40]}）",
            importance=0.6 if success else 0.4,
            tags=["action_sequence", "success" if success else "failure"]
                 + ([f"hint:{skill_hint}"] if skill_hint else []))
        if success and skill_hint:
            existing = self.recall_skill(skill_hint, limit=1)
            if existing:
                self.store.update_skill_confidence(existing[0]["id"], 0.05)
                self.store.append_skill_procedure(existing[0]["id"], " > ".join(actions[:3]))
            else:
                self.store_skill(skill_hint, f"从操作序列提取（{outcome[:40]}）",
                                 " > ".join(actions[:5]), confidence=0.5)
        elif not success:
            # A-1：失败操作序列 → 被拒绝路径资产（防重复失败）
            self.register_rejected_path(
                path_type="action_sequence",
                description=f"操作序列失败：{' > '.join(actions[:5])}",
                reason=f"outcome: {outcome[:60]}")
        return node

    # ---- P1-4 巩固周期 ----

    def consolidate_cycle(self, rehearsal_threshold: float = 0.7,
                          degrade_threshold: float = 0.2, gain: float = 0.01) -> Dict:
        """P1-4 巩固周期：高重要度演练（刷新访问）+ 低重要度降权 + 压缩候选标记。
        不可遗忘过滤器（VAL-TRANSFER-20260813-002-FINAL 约束）：3.2 节 6 类不可遗忘记录
        （信任值评估/偏差历史/价值观迭代/协作校准/内化过程/协定式自我赋予，经 protect_node
        标记）永不被降权或标记为 compressible"""
        nodes = self.store.query_nodes(limit=1000)
        protected = set(self.store.get_protected_nodes())
        stats = {"rehearsed": 0, "boosted": 0, "degraded": 0, "compressible": 0}
        for n in nodes:
            if n.layer in (MemoryLayer.ANCHOR, MemoryLayer.STRUCTURE):
                continue
            if n.id in protected or "no_forget" in n.tags:
                continue  # 不可遗忘过滤器（3.2 节）
            if n.importance >= rehearsal_threshold:
                self.store.increment_access(n.id)
                if n.access_count % 10 == 0:
                    self.store.update_node_importance(n.id, gain)
                    stats["boosted"] += 1
                stats["rehearsed"] += 1
            elif n.importance < degrade_threshold:
                if n.access_count <= 2:
                    self.store.update_node_importance(n.id, -gain)
                    stats["degraded"] += 1
                if n.importance < 0.08:
                    self.store.tag_node(n.id, "compressible")
                    stats["compressible"] += 1
        self.add_perception(
            f"[consolidation] 演练 {stats['rehearsed']} · 提升 {stats['boosted']} · 降权 {stats['degraded']} · 可压缩 {stats['compressible']}",
            importance=0.4, tags=["consolidation"])
        return stats

    def run_maintenance_cycle(self, decay_factor: float = 0.02) -> Dict:
        """P1-4 睡眠巩固：衰减 + 巩固 + 归纳（一次维护周期）"""
        self.decay_cycle(decay_factor)
        cstats = self.consolidate_cycle()
        induced = self.induce_concepts()
        return {"decay": decay_factor, "consolidation": cstats, "induced_concepts": len(induced)}

    # ==================== 衰减与维护 ====================

    def decay_cycle(self, factor: float = 0.02, min_confidence: float = 0.1):
        """执行一次衰减周期（v1.16：透传 min_confidence 给 store 层）"""
        self.store.decay_cycle(factor, min_confidence=min_confidence)

    def forget_advisor(self, stale_days: float = 30.0, low_value: float = 0.2,
                       archived_imp: float = 0.1) -> Dict:
        """主动遗忘决策器（v1.16 · J 维进化：被动时间衰减 → 主动价值遗忘）。

        递归反思终裁（node_595c062c）：系统根据「记忆是否被使用」主动归档，
        而非仅靠时间流逝。最小可行 v1——仅用可机械读信号：
          ① 访问信号：CONTEXT 层 access_count==0 且 last_access 距今 > stale_days
          ② 低价值信号：CONTEXT 层 importance < low_value
        决策：归档（tags 加 archived + importance 降至 archived_imp）——
        recall 的 importance 加权自然降权（可逆：恢复 importance 即解除）。
        锚点/结构层 no_forget 保护；KNOWLEDGE 层不动（长期知识）。
        """
        import time as _t
        now = _t.time()
        archived = 0
        kept = 0
        with self.store._lock:
            c = self.store.conn.cursor()
            c.execute("SELECT id, content, importance, last_access, tags FROM nodes "
                      "WHERE layer='context'")
            for nid, content, imp, last_acc, tags in c.fetchall():
                tags = json.loads(tags) if isinstance(tags, str) and tags else []
                if "no_forget" in tags or "archived" in tags:
                    continue  # 不可遗忘 / 已归档
                stale = (last_acc is None or (now - (last_acc or 0)) > stale_days * 86400) \
                    and self.store.get_node(nid) is not None
                # 访问信号：从未被访问且久远
                access_stale = (self.store.get_node(nid) or {}).get("access_count") if False else None
                # 直接查 access_count
                c2 = self.store.conn.cursor()
                c2.execute("SELECT access_count FROM nodes WHERE id=?", (nid,))
                row = c2.fetchone()
                acc = row[0] if row else 0
                signal = 0
                if acc == 0 and (now - (last_acc or now)) > stale_days * 86400:
                    signal += 1  # 访问信号
                if (imp or 0.5) < low_value:
                    signal += 1  # 低价值信号
                if signal >= 1:
                    # 归档：importance 降至 archived_imp + tags 加 archived
                    new_imp = archived_imp
                    new_tags = list(dict.fromkeys(tags + ["archived"]))
                    c.execute("UPDATE nodes SET importance=?, tags=? WHERE id=?",
                              (new_imp, json.dumps(new_tags, ensure_ascii=False), nid))
                    archived += 1
                else:
                    kept += 1
            self.store.conn.commit()
        return {"archived": archived, "kept": kept,
                "note": "主动遗忘：未被使用的 CONTEXT 记忆归档（importance 降权，可逆）"}

    def start_auto_decay(self, interval: float = 60.0):
        """启动后台衰减线程"""
        if self._running:
            return
        self._running = True
        def loop():
            while self._running:
                time.sleep(interval)
                self.decay_cycle()
        self._decay_thread = threading.Thread(target=loop, daemon=True)
        self._decay_thread.start()

    def stop_auto_decay(self):
        self._running = False

    # ==================== 自检 ====================

    def self_check(self) -> Dict:
        """
        自检：锚点层完整性、结构层一致性、自我层存在性
        返回诊断报告
        """
        anchors = self.get_anchors()
        structures = self.store.get_layer_nodes(MemoryLayer.STRUCTURE)
        self_nodes = self.store.get_layer_nodes(MemoryLayer.SELF)
        report = {
            "anchor_ok": len(anchors) > 0,
            "anchor_count": len(anchors),
            "structure_ok": len(structures) >= 2,
            "structure_count": len(structures),
            "self_ok": len(self_nodes) > 0 or self.self_model.identity != "",
            "self_model_exists": self.self_model.identity != "",
            "open_blindspots": len(self.store.list_blindspots(status="open")),
            "skills_count": self.store.count_skills(),
            "context_count": self.store.count_layer(MemoryLayer.CONTEXT),
            "stats": self.store.get_stats(),
            "timestamp": time.time()
        }
        # 检查是否存在因果循环
        cycles = self.store.find_cycles(max_depth=8)
        report["cycles_found"] = len(cycles)
        report["cycle_details"] = [[e.id for e in path] for path in cycles[:5]]
        return report

    # ==================== 统计与关闭 ====================

    def get_stats(self) -> Dict:
        return self.store.get_stats()

    def close(self):
        self.stop_auto_decay()
        self.store.close()

    # ---- v1.15 长期记忆写入决策器（LongTermMemoryGate） ----

    def _ensure_gate(self):
        """惰性装配长期记忆门（零依赖）。"""
        if self._gate is None:
            from longterm_gate import LongTermMemoryGate
            self._gate = LongTermMemoryGate(self)
        return self._gate

    def longterm_snapshot(self, content: str, source: str = "snapshot",
                          tags: list = None, entities: list = None,
                          importance_hint: float = None) -> dict:
        """记忆快照 → 重要性评估 → 按层级写入（长期/知识/情境）+ 条件空间 + 关联。
        主动沉淀机制：重要经验/会话结束/关键事件调用。"""
        try:
            gate = self._ensure_gate()
            return gate.write_snapshot(content, source, tags, entities,
                                       importance_hint)
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def prefeed_input(self, content: str, source: str = "input",
                      tags: list = None, entities: list = None) -> dict:
        """H1 海马体前馈：新奇检测 → 高新奇输入当场强化编码（标记+提权+建边）。
        外部输入（对话/摄取/感知）到达时调用——「看到新东西眼睛一亮」。
        返回 {novel, novelty, action, node_id, importance, links}"""
        try:
            gate = self._ensure_gate()
            return gate.prefeed(content, source, tags, entities)
        except Exception as exc:
            return {"novel": False, "action": "error", "error": str(exc)}

    def pattern_separation_scan(self, limit: int = 150) -> dict:
        """H3 海马体模式分离：扫描相似节点对 → 建立分离边（条件差异显式化）。
        检索时命中相似节点会附「这两个的区别」提示——细化条件得到精确知识。"""
        try:
            import sys as _s
            _kb = r'D:\Program Files\2_ai\knowledge-base'
            if _kb not in _s.path:
                _s.path.insert(0, _kb)
            from pattern_separation import PatternSeparation
            ps = PatternSeparation(self)
            return ps.scan(limit=limit)
        except Exception as exc:
            return {"created": 0, "error": str(exc)}

    def reconstruct_scene(self, clue: str, depth: int = 2,
                          max_nodes: int = 8) -> dict:
        """H4 海马体情景重构：线索 → 条件空间下的信息复原。
        从部分片段重建完整记忆场景（沿 similar/causal 边 + 条件空间合成），
        输出显式标注「重构非回放」——回忆起的情景是当前条件下的分析恢复，
        不代表真实发生的过去就是如此（0.0.3 局部不可知）。"""
        try:
            import sys as _s
            _kb = r'D:\Program Files\2_ai\knowledge-base'
            if _kb not in _s.path:
                _s.path.insert(0, _kb)
            from scene_reconstruction import SceneReconstruction
            sr = SceneReconstruction(self)
            return sr.reconstruct(clue, depth=depth, max_nodes=max_nodes)
        except Exception as exc:
            return {"scene": [], "error": str(exc)}

    def promote_context_memories(self, limit: int = 30) -> list:
        """情境层批量提升扫描（睡眠巩固/会话结束调用）：够格者升知识层/长期层。"""
        try:
            gate = self._ensure_gate()
            return gate.promote_from_context(limit)
        except Exception:
            return []