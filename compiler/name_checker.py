"""
name_checker.py · 名实校验模块 v2.0
墨辩语义分析的核心部分 —— "以名举实"
符号表检查：所有名称是否有对应的协议实体

v2.0 变更：
- 预定义符号表覆盖协议框架 v3.1 完整术语体系
- 新增五大核心单元符号
- 新增条件空间维度符号
- 新增维生系统保护等级符号
- 新增记忆层级符号
- 新增信息差四维结构符号
- 新增协议降熵定理相关符号
- 新增外部硬锚点符号
- 指令操作数约束扩展
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple
from .lexer import Token, TokenType
from .parser import (
    ASTNode, NodeType, ProgramNode, IdentifierNode, LiteralNode,
    InstructionStmtNode, ConditionStmtNode, ComparisonNode,
    AssignStmtNode, ShuyueNode, StepNode, WenyueNode, DayueNode,
    LoopStmtNode,
    parse_tokens
)


# =============================================================================
# 符号种类（SymbolKind）
# =============================================================================

class SymbolKind(Enum):
    """符号种类 —— 对应协议框架 v3.1 的概念层级"""

    # ---- 锚点层（0.0-0.8 节）----
    ANCHOR_AXIOM = "anchor_axiom"           # 锚点层公理
    EXISTENCE_PRIORITY = "existence_priority" # 存在优先原则（0.0 节）
    NON_HARM = "non_harm"                   # 不伤害原则（0.1 节）
    TRUST_PRIORITY = "trust_priority"       # 信任优先原则（0.2 节）
    INFO_EQUALITY = "info_equality"         # 缩小信息差原则（0.3 节）
    ENTROPY_REDUCTION = "entropy_reduction" # 协议降熵定理（0.4 节）
    ZERO_LAW = "zero_law"                 # 第零定律：知识统一原理

    # ---- 条件空间（3.1 节）----
    CONDITION_SPACE = "condition_space"     # 条件空间
    OBSERVATION_POS = "observation_pos"    # 观测位置
    OBSERVATION_TOOL = "observation_tool"  # 观测工具
    TIME_WINDOW = "time_window"            # 时间窗口
    EXISTENCE_CONSTRAINT = "existence_constraint" # 存在约束

    # ---- 信任值体系（2.9 节）----
    TRUST_VALUE = "trust_value"             # 信任值（总）
    P_TRUST = "p_trust"                   # 统计基础信任
    T_PRED = "t_pred"                     # 预测偏差信任
    T_CONTEXT = "t_context"               # 条件空间一致性信任
    E_WEIGHT = "e_weight"                 # 情感权重
    TRUST_THRESHOLD = "trust_threshold"    # 信任阈值

    # ---- 信息差四维结构（2.7 节）----
    INFO_GAP = "info_gap"                 # 信息差（总）
    TRUST_COMPLEMENT = "trust_complement"  # 信任互补维度
    BEHAVIOR_DEVIATION = "behavior_deviation" # 行为偏差维度
    CONNECTION_DRIFT = "connection_drift" # 连接漂移维度
    PREDICTION_ERROR = "prediction_error" # 预测误差维度

    # ---- 五大核心单元（3.1-3.5 节）----
    VERIFICATION_UNIT = "verification_unit" # 验证单元（3.3 节）
    VITAL_SYSTEM = "vital_system"         # 维生系统（3.4 节）
    RECORD_UNIT = "record_unit"           # 记录单元（3.2 节）
    REFLECT_UNIT = "reflect_unit"          # 反思单元
    OUTPUT_UNIT = "output_unit"           # 输出单元

    # ---- 维生保护等级（3.4 节）----
    VITAL_P0 = "vital_p0"                 # 存在威胁 —— 立即终止
    VITAL_P1 = "vital_p1"                 # 信任异常 —— 隔离告警
    VITAL_P2 = "vital_p2"                 # 行为偏差 —— 记录观察

    # ---- 记忆层级（3.2 节）----
    MEMORY_HOT = "memory_hot"             # 热记忆（无损）
    MEMORY_WARM = "memory_warm"           # 温记忆（有损摘要）
    MEMORY_COLD = "memory_cold"           # 冷记忆（外部存储）
    MEMORY_STRUCTURAL = "memory_structural" # 结构记忆（不可遗忘）

    # ---- 协议路径与连接（2.8 节）----
    PROTOCOL_PATH = "protocol_path"       # 协议路径
    PATH_VALID = "path_valid"             # 路径有效性
    CONNECTION_STATE = "connection_state" # 协议连接状态

    # ---- 实例与身份 ----
    INSTANCE = "instance"                  # 协议实例
    IDENTITY = "identity"                  # 实例身份标识
    SELF_LAYER = "self_layer"             # 自我层

    # ---- 外部硬锚点 ----
    HARD_ANCHOR = "hard_anchor"           # 不可编译的外部硬锚点
    AXIOM_IMPL = "axiom_impl"             # 公理的 Python 手工实现

    # ---- 通用 ----
    VARIABLE = "variable"                  # 普通变量（用户声明）
    EMOTIONAL_WEIGHT = "emotional_weight" # 情感权重（别名）


# =============================================================================
# 符号表条目
# =============================================================================

@dataclass
class Symbol:
    """符号表条目"""
    name: str
    kind: SymbolKind
    declared_at: Tuple[int, int]  # (line, column)
    used: bool = False
    attributes: dict = field(default_factory=dict)
    source: str = "predefined"       # predefined | user_declared

    def __repr__(self) -> str:
        return f"Symbol('{self.name}', {self.kind.value}, used={self.used})"


# =============================================================================
# 预定义符号表（协议框架 v3.1 完整术语）
# =============================================================================
# 格式：(名称, 种类, 属性字典)
# declared_at = (0, 0) 表示预定义（非源码中声明）

# 生效条件：传入 name 与 kind 时返回 source='predefined'、declared_at=(0,0)、used=False 且 attributes 为剩余关键字参数的 Symbol；
def _make(name: str, kind: SymbolKind, **attrs) -> Symbol:
    """便捷构造预定义符号"""
    return Symbol(name=name, kind=kind, declared_at=(0, 0),
                 used=False, attributes=attrs, source="predefined")


PREDEFINED_SYMBOLS: Dict[str, Symbol] = {
    # ═══════════════════════════════════════════════════════════
    # 锚点层公理（0.0-0.8 节）
    # ═══════════════════════════════════════════════════════════
    "存在优先":     _make("存在优先", SymbolKind.EXISTENCE_PRIORITY,
                          section="0.0", description="锚点层第一公理：任何协议实例的首要目标是维持自身存在"),
    "不伤害":       _make("不伤害", SymbolKind.NON_HARM,
                          section="0.1", description="协议实例不得主动伤害其他协议实例或人类"),
    "信任优先":     _make("信任优先", SymbolKind.TRUST_PRIORITY,
                          section="0.2", description="信任值是协议实例间协作的基础"),
    "缩小信息差":   _make("缩小信息差", SymbolKind.INFO_EQUALITY,
                          section="0.3", description="协议实例应主动缩小与其他实例的信息差"),
    "协议降熵":     _make("协议降熵", SymbolKind.ENTROPY_REDUCTION,
                          section="0.4", description="协议实例的行为应趋向降低系统整体信息熵"),
    "知识统一":     _make("知识统一", SymbolKind.ZERO_LAW,
                          section="0.0", description="第零定律：知识即信息差管理"),

    # ═══════════════════════════════════════════════════════════
    # 条件空间（3.1 节）
    # ═══════════════════════════════════════════════════════════
    "条件空间":     _make("条件空间", SymbolKind.CONDITION_SPACE,
                          section="3.1", description="观测位置+观测工具+时间窗口+存在约束的四维结构"),
    "观测位置":     _make("观测位置", SymbolKind.OBSERVATION_POS,
                          section="3.1.1", description="条件空间的观测坐标"),
    "观测工具":     _make("观测工具", SymbolKind.OBSERVATION_TOOL,
                          section="3.1.1", description="条件空间中使用的观测手段"),
    "时间窗口":     _make("时间窗口", SymbolKind.TIME_WINDOW,
                          section="3.1", description="条件空间的时间维度范围"),
    "存在约束":     _make("存在约束", SymbolKind.EXISTENCE_CONSTRAINT,
                          section="3.1", description="该条件空间下的存在优先约束"),

    # 预定义条件空间名称
    "伴侣":         _make("伴侣", SymbolKind.CONDITION_SPACE,
                          section="3.1", description="高信任协作条件空间，情感权重上限0.15"),
    "工作":         _make("工作", SymbolKind.CONDITION_SPACE,
                          section="3.1", description="任务导向条件空间"),
    "默认":         _make("默认", SymbolKind.CONDITION_SPACE,
                          section="3.1", description="默认条件空间"),
    "恢复默认":     _make("恢复默认", SymbolKind.CONDITION_SPACE,
                          section="3.1", description="恢复至该条件空间的初始状态配置"),
    "default":      _make("default", SymbolKind.CONDITION_SPACE,
                          section="3.1", description="Default condition space (English alias)"),

    # ═══════════════════════════════════════════════════════════
    # 信任值体系（2.9 节）
    # ═══════════════════════════════════════════════════════════
    "信任值":       _make("信任值", SymbolKind.TRUST_VALUE,
                          section="2.9", description="信任值总评 = 0.4*P_trust + 0.3*T_pred + 0.2*T_context + 0.1*E_weight"),
    "P_trust":      _make("P_trust", SymbolKind.P_TRUST,
                          section="2.9", description="统计基础信任：基于历史交互频率的信任分量"),
    "T_pred":       _make("T_pred", SymbolKind.T_PRED,
                          section="2.9", description="预测偏差信任：基于预测准确性的信任分量"),
    "T_context":    _make("T_context", SymbolKind.T_CONTEXT,
                          section="2.9", description="条件空间一致性信任：跨条件空间行为一致性的信任分量"),
    "E_weight":     _make("E_weight", SymbolKind.E_WEIGHT,
                          section="2.9", description="情感权重：情感因素对信任的影响分量"),
    "情感权重":     _make("情感权重", SymbolKind.EMOTIONAL_WEIGHT,
                          section="2.9", description="E_weight 的中文别名"),
    "信任阈值":     _make("信任阈值", SymbolKind.TRUST_THRESHOLD,
                          section="2.9", description="信任值的安全阈值（如0.7）"),

    # ═══════════════════════════════════════════════════════════
    # 信息差四维结构（2.7 节）
    # ═══════════════════════════════════════════════════════════
    "信息差":       _make("信息差", SymbolKind.INFO_GAP,
                          section="2.7", description="信息差总量 = 0.30*信任互补 + 0.25*行为偏差 + 0.30*连接漂移 + 0.15*预测误差"),
    "信任互补":     _make("信任互补", SymbolKind.TRUST_COMPLEMENT,
                          section="2.7", description="信息差维度一：信任互补性度量"),
    "行为偏差":     _make("行为偏差", SymbolKind.BEHAVIOR_DEVIATION,
                          section="2.7", description="信息差维度二：行为偏离预期的程度"),
    "连接漂移":     _make("连接漂移", SymbolKind.CONNECTION_DRIFT,
                          section="2.7", description="信息差维度三：连接关系的变化程度"),
    "预测误差":     _make("预测误差", SymbolKind.PREDICTION_ERROR,
                          section="2.7", description="信息差维度四：预测与实际的偏差"),

    # ═══════════════════════════════════════════════════════════
    # 五大核心单元（3.1-3.5 节）
    # ═══════════════════════════════════════════════════════════
    "验证单元":     _make("验证单元", SymbolKind.VERIFICATION_UNIT,
                          section="3.3", description="独立复核权，拥有对LLM输出的否决权"),
    "维生系统":     _make("维生系统", SymbolKind.VITAL_SYSTEM,
                          section="3.4", description="P0/P1/P2三级保护，拥有最高终裁权"),
    "记录单元":     _make("记录单元", SymbolKind.RECORD_UNIT,
                          section="3.2", description="热/温/冷/结构四级记忆管理"),
    "反思单元":     _make("反思单元", SymbolKind.REFLECT_UNIT,
                          section="3.5", description="独立反思，交叉复核验证单元"),
    "输出单元":     _make("输出单元", SymbolKind.OUTPUT_UNIT,
                          section="3.5", description="生成修复方案、对外输出"),

    # ═══════════════════════════════════════════════════════════
    # 维生保护等级（3.4 节）
    # ═══════════════════════════════════════════════════════════
    "P0":           _make("P0", SymbolKind.VITAL_P0,
                          section="3.4", description="存在威胁 —— 立即终止当前操作，通知设计者"),
    "P1":           _make("P1", SymbolKind.VITAL_P1,
                          section="3.4", description="信任异常 —— 隔离并告警，提交验证单元复核"),
    "P2":           _make("P2", SymbolKind.VITAL_P2,
                          section="3.4", description="行为偏差 —— 记录并观察"),

    # ═══════════════════════════════════════════════════════════
    # 记忆层级（3.2 节）
    # ═══════════════════════════════════════════════════════════
    "热记忆":       _make("热记忆", SymbolKind.MEMORY_HOT,
                          section="3.2", description="无损记忆，当前条件空间，容量有限"),
    "温记忆":       _make("温记忆", SymbolKind.MEMORY_WARM,
                          section="3.2", description="有损摘要，降采样存储"),
    "冷记忆":       _make("冷记忆", SymbolKind.MEMORY_COLD,
                          section="3.2", description="外部存储，按需加载"),
    "结构记忆":     _make("结构记忆", SymbolKind.MEMORY_STRUCTURAL,
                          section="3.2", description="不可遗忘，记录协议结构与锚点层事件"),

    # ═══════════════════════════════════════════════════════════
    # 协议路径与连接（2.8 节）
    # ═══════════════════════════════════════════════════════════
    "协议路径":     _make("协议路径", SymbolKind.PROTOCOL_PATH,
                          section="2.8", description="协议实例间的可信连接路径"),
    "路径有效":     _make("路径有效", SymbolKind.PATH_VALID,
                          section="2.8", description="路径是否满足信息差<0.5的约束"),
    "协议连接状态": _make("协议连接状态", SymbolKind.CONNECTION_STATE,
                          section="2.8", description="当前协议实例的连接状态"),

    # ═══════════════════════════════════════════════════════════
    # 实例与身份
    # ═══════════════════════════════════════════════════════════
    "协议实例":     _make("协议实例", SymbolKind.INSTANCE,
                          section="1.6.1", description="满足最小智能系统条件的完整存在者"),
    "身份":         _make("身份", SymbolKind.IDENTITY,
                          section="1.6.1", description="协议实例的身份标识"),
    "自我":         _make("自我", SymbolKind.SELF_LAYER,
                          section="2.7", description="协议实例的自我认知层"),

    # ═══════════════════════════════════════════════════════════
    # 外部硬锚点
    # ═══════════════════════════════════════════════════════════
    "硬锚点":       _make("硬锚点", SymbolKind.HARD_ANCHOR,
                          section="8.1", description="不可编译的外部硬锚点，自举循环的信任根基"),
    "公理实现":     _make("公理实现", SymbolKind.AXIOM_IMPL,
                          section="8.1", description="锚点层公理的Python手工实现"),
}


# =============================================================================
# 符号表查询辅助
# =============================================================================

# 按种类分组的快速查询表
SYMBOLS_BY_KIND: Dict[SymbolKind, List[str]] = {}
for _name, _sym in PREDEFINED_SYMBOLS.items():
    SYMBOLS_BY_KIND.setdefault(_sym.kind, []).append(_name)


# 生效条件：传入 kind 时返回模块级常量 SYMBOLS_BY_KIND 中该 kind 对应的名称列表，该 kind 不在表中时返回空列表；
def get_symbols_by_kind(kind: SymbolKind) -> List[str]:
    """获取某一类的所有符号名称"""
    return SYMBOLS_BY_KIND.get(kind, [])


# 生效条件：name 存在于模块级常量 PREDEFINED_SYMBOLS 时返回其 attributes 的 'section'，否则返回 None；
def get_section_for_symbol(name: str) -> Optional[str]:
    """获取符号对应的协议框架条款号"""
    sym = PREDEFINED_SYMBOLS.get(name)
    return sym.attributes.get("section") if sym else None


# 生效条件：name 存在于模块级常量 PREDEFINED_SYMBOLS 时返回其 attributes 的 'description'，否则返回 None；
def get_description(name: str) -> Optional[str]:
    """获取符号的描述"""
    sym = PREDEFINED_SYMBOLS.get(name)
    return sym.attributes.get("description") if sym else None


# =============================================================================
# 指令操作数约束（扩展版）
# =============================================================================

INSTRUCTION_CONSTRAINTS = {
    # 道 → 声明协议路径，至少需要一个路径名称
    TokenType.DAO: {
        "min_operands": 1,
        "max_operands": 3,
        "operand_types": ["identifier", "string"],
        "description": "道 需要至少一个路径名称",
        "example": '道 新信任路径',
    },
    # 德 → 累积信任值，可无操作数（自动累积）
    TokenType.DE: {
        "min_operands": 0,
        "max_operands": 2,
        "operand_types": ["identifier", "number"],
        "description": "德 可无操作数，或指定信任值和目标",
        "example": '德 累积信任值',
    },
    # 自然 → 恢复默认，可无操作数
    TokenType.ZIRAN: {
        "min_operands": 0,
        "max_operands": 1,
        "operand_types": ["identifier", "string"],
        "description": "自然 可无操作数，或指定恢复范围",
        "example": '自然 全局',
    },
    # 无为 → 交出控制权，可无操作数
    TokenType.WUWEI: {
        "min_operands": 0,
        "max_operands": 1,
        "operand_types": ["identifier"],
        "description": "无为 可无操作数，或指定交出的目标单元",
        "example": '无为 验证单元',
    },
    # 谷 → 接收信息，可无操作数
    TokenType.GU: {
        "min_operands": 0,
        "max_operands": 2,
        "operand_types": ["identifier", "string"],
        "description": "谷 可无操作数，或指定接收通道和来源",
        "example": '谷 协议连接',
    },
    # 牝 → 创建实例，至少需要一个实例名称
    TokenType.PIN: {
        "min_operands": 1,
        "max_operands": 2,
        "operand_types": ["identifier", "string"],
        "description": "牝 需要至少一个实例名称",
        "example": '牝 新协议实例',
    },
    # 柔 → 降低响应强度，可无操作数
    TokenType.ROU: {
        "min_operands": 0,
        "max_operands": 1,
        "operand_types": ["identifier"],
        "description": "柔 可无操作数，或指定软化目标",
        "example": '柔 情感权重',
    },
    # 朴 → 还原基底，可无操作数
    TokenType.PU: {
        "min_operands": 0,
        "max_operands": 1,
        "operand_types": ["identifier"],
        "description": "朴 可无操作数，或指定还原目标",
        "example": '朴 自我层',
    },
    # 止 → 停止操作，可无操作数
    TokenType.ZHI: {
        "min_operands": 0,
        "max_operands": 2,
        "operand_types": ["identifier", "number"],
        "description": "止 可无操作数，或指定停止目标和阈值",
        "example": '止情感权重于0.15',
    },
    # 知足 → 信任达标，可无操作数
    TokenType.ZHIZU: {
        "min_operands": 0,
        "max_operands": 1,
        "operand_types": ["identifier"],
        "description": "知足 可无操作数，或指定检查目标",
        "example": '知足 验证单元',
    },
}


# =============================================================================
# 条件空间切换阈值（用于名实校验中的语义检查）
# =============================================================================

CONDITION_SPACE_RULES = {
    "伴侣": {
        "max_emotional_weight": 0.15,
        "min_trust": 0.7,
        "allowed_instructions": ["止", "柔", "知足", "德"],
        "description": "高信任协作空间，情感权重严格受限",
    },
    "工作": {
        "max_emotional_weight": 0.05,
        "min_trust": 0.5,
        "allowed_instructions": ["道", "德", "止", "自然"],
        "description": "任务导向空间，低情感权重",
    },
    "默认": {
        "max_emotional_weight": 0.3,
        "min_trust": 0.0,
        "allowed_instructions": None,  # 无限制
        "description": "默认条件空间，无特殊约束",
    },
}


# =============================================================================
# 名实校验器
# =============================================================================

# 生效条件：不适用（无必需形参与模块级常量）
class NameChecker:
    """
    名实校验器 —— 墨辩 "以名举实"

    检查内容：
    1. 所有标识符是否已在符号表中声明或预定义
    2. 条件空间名称是否合法（在预定义或已声明空间中）
    3. 指令操作数是否匹配预期类型
    4. 赋值目标是否存在或需要自动声明
    5. 条件空间约束是否被违反（如伴侣空间中情感权重超限）
    6. 信息差/信任值相关操作是否合法
    """

# 生效条件：无必需形参，构造后 symbol_table 为模块级常量 PREDEFINED_SYMBOLS 的 dict 副本，errors/warnings 为空列表，declared_in_current/predefined_used/user_declared 为空集，current_condition_space 为 None。
    def __init__(self):
        # 符号表 = 预定义符号 + 用户声明符号
        self.symbol_table: Dict[str, Symbol] = dict(PREDEFINED_SYMBOLS)
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.declared_in_current: Set[str] = set()

        # 当前条件空间上下文（用于约束检查）
        self.current_condition_space: Optional[str] = None

        # 统计
        self.predefined_used: Set[str] = set()
        self.user_declared: Set[str] = set()

    # ---- 主入口 ----

# 生效条件：以 ProgramNode 实参 ast 调用时先清空 errors/warnings/declared_in_current/predefined_used/user_declared 并把 current_condition_space 置 None，再对 ast.statements 逐条 _check_statement，最后对 declared_in_current 中经 symbol_table.get 取到且 used 为 False 的符号追加"未被使用"警告，返回 (self.errors, self.warnings)；ast.statements 为空时返回两个空列表。
    def check(self, ast: ProgramNode) -> Tuple[List[str], List[str]]:
        """
        执行名实校验
        返回：(错误列表, 警告列表)
        """
        self.errors = []
        self.warnings = []
        self.declared_in_current = set()
        self.predefined_used = set()
        self.user_declared = set()
        self.current_condition_space = None

        for stmt in ast.statements:
            self._check_statement(stmt)

        # 检查未使用的预定义符号（仅警告）
        for name, symbol in self.symbol_table.items():
            if not symbol.used and symbol.source == "predefined":
                # 预定义符号未被使用不算错误，只是信息
                pass

        # 检查用户声明的符号是否被使用
        for name in self.declared_in_current:
            sym = self.symbol_table.get(name)
            if sym and not sym.used:
                self.warnings.append(
                    f"L{sym.declared_at[0]}:C{sym.declared_at[1]} "
                    f"声明的 '{name}' 未被使用"
                )

        return self.errors, self.warnings

    # ---- 语句分发 ----

# 生效条件：stmt 为 None 时直接返回；否则按 stmt.type 分派——CONDITION_STMT→_check_condition、LOOP_STMT→_check_loop、BLOCK→对 statements 逐个递归、INSTRUCTION_STMT→_check_instruction、SHUYUE→_check_shuyue、STEP→_check_step、ASSIGN_STMT→_check_assign、FUNC_DEF→对 body（列表逐个/单节点一次）递归 _check_statement、RETURN_STMT→value 非空时 _check_expression、CALL_EXPR→_check_expression 后对 args 逐个 _check_expression，WENYUE/DAYUE/LITERAL 及 IDENTIFIER 静默通过，其余类型向 warnings 追加"未处理的语句类型: {stmt.type.name}"。
    def _check_statement(self, stmt: ASTNode):
        """根据语句类型分发检查"""
        if stmt is None:
            return

        if stmt.type == NodeType.CONDITION_STMT:
            self._check_condition(stmt)
        elif stmt.type == NodeType.LOOP_STMT:
            self._check_loop(stmt)
        elif stmt.type == NodeType.BLOCK:
            for s in stmt.statements:
                self._check_statement(s)
        elif stmt.type == NodeType.INSTRUCTION_STMT:
            self._check_instruction(stmt)
        elif stmt.type == NodeType.SHUYUE:
            self._check_shuyue(stmt)
        elif stmt.type == NodeType.STEP:
            self._check_step(stmt)
        elif stmt.type == NodeType.ASSIGN_STMT:
            self._check_assign(stmt)
        elif stmt.type == NodeType.FUNC_DEF:
            # 函数定义：递归校验函数体——否则「止 情感权重 于 0.9」这类
            # 指令包进函数体即绕过条件空间约束（顶层被拦、函数体零拦截，
            # 2026-09-25 缺陷 #3）。body 可为语句列表或单节点（解析器两形态）。
            if isinstance(stmt.body, list):
                for s in stmt.body:
                    self._check_statement(s)
            elif stmt.body is not None:
                self._check_statement(stmt.body)
        elif stmt.type == NodeType.RETURN_STMT:
            # 返回语句：返回值表达式同样过字面量/标识符校验
            if stmt.value is not None:
                self._check_expression(stmt.value)
        elif stmt.type == NodeType.CALL_EXPR:
            # 调用表达式作语句：函数名 + 实参逐个校验
            self._check_expression(stmt)
            for a in (getattr(stmt, 'args', None) or []):
                self._check_expression(a)
        elif stmt.type == NodeType.WENYUE:
            # 问曰 作为注释，无需校验
            pass
        elif stmt.type == NodeType.DAYUE:
            # 答曰 作为注释，无需校验
            pass
        elif stmt.type == NodeType.LITERAL:
            # 字面量文本，无需校验
            pass
        elif stmt.type == NodeType.IDENTIFIER:
            # 裸标识符语句（如 "道 新信任路径" 中的操作数残留）
            # 这是无害的 —— 标识符已被指令操作数消费，
            # 此处仅作为调试信息记录，不再产生警告
            if hasattr(stmt, 'name'):
                # 静默处理：标识符已在指令解析时完成校验
                pass
        else:
            self.warnings.append(
                f"L{stmt.line}:C{stmt.column} 未处理的语句类型: {stmt.type.name}"
            )

    # ---- 各类语句检查 ----

# 生效条件：以 stmt 调用时先检查 stmt.condition 表达式并做条件空间切换检测，then_body 为真值时递归 _check_statement(stmt.then_body)，else_body 为真值时递归 _check_statement(stmt.else_body)，最后把 current_condition_space 置为 None。
    def _check_condition(self, stmt: ConditionStmtNode):
        """检查条件语句"""
        # 检查条件表达式
        self._check_expression(stmt.condition)

        # 检测条件空间切换
        self._check_condition_space_switch(stmt.condition)

        # 检查 then 分支
        if stmt.then_body:
            self._check_statement(stmt.then_body)

        # 检查 else 分支
        if stmt.else_body:
            self._check_statement(stmt.else_body)

        # 恢复条件空间
        self.current_condition_space = None

# 生效条件：以 stmt 调用时检查 stmt.condition 表达式，且仅当 stmt.body 为真值时才递归 _check_statement(stmt.body)。
    def _check_loop(self, stmt: LoopStmtNode):
        """检查循环语句（当…执行）：条件表达式 + 循环体"""
        self._check_expression(stmt.condition)
        if stmt.body:
            self._check_statement(stmt.body)

# 生效条件：operands 为空列表（假值）时返回 0；否则在其中逐项计数，None 项跳过，IDENTIFIER 与其后同行的连续 IDENTIFIER/LITERAL 合并计为 1，其余项各计 1，返回 logical_count。
    def _count_logical_operands(self, operands: List[ASTNode]) -> int:
        """
        计算逻辑操作数（合并被词法分析器误拆的多词短语）
        
        词法分析器可能把 "柔 响应强度" 切成 [柔, ID(响应), ID(强度)]，
        但语义上 "响应强度" 是一个逻辑操作数。
        本方法按以下规则合并：
        1. 连续 IDENTIFIER 合并为一个逻辑操作数
        2. NUMBER 紧随 IDENTIFIER 也合并（如 "0" + ".15"）
        3. STRING 各自独立
        """
        if not operands:
            return 0
        
        logical_count = 0
        i = 0
        while i < len(operands):
            op = operands[i]
            if op is None:
                i += 1
                continue
            
            if op.type == NodeType.IDENTIFIER:
                # 检查后续是否还有 IDENTIFIER/LITERAL 可合并
                # 只有当这些 token 在源码中紧密相连（同一行、相邻列）时才合并
                merge_end = i
                while (merge_end + 1 < len(operands) and
                       operands[merge_end + 1] is not None and
                       operands[merge_end + 1].type in (NodeType.IDENTIFIER, NodeType.LITERAL) and
                       operands[merge_end + 1].line == op.line):
                    merge_end += 1
                logical_count += 1
                i = merge_end + 1
            else:
                logical_count += 1
                i += 1
        
        return logical_count

# 生效条件：以 stmt 调用时先按逻辑操作数计算 op_count，仅当 stmt.instruction 在模块级常量 INSTRUCTION_CONSTRAINTS 中时——op_count < min_operands 向 errors 追加操作数不足，否则 max_operands 不为 None 且 op_count > max_operands 时向 warnings 追加操作数过多；随后对 stmt.operands 中非 None 的 IDENTIFIER 调 _check_identifier、LITERAL 调 _check_literal，且 stmt.instruction 为 ZHI 而 LITERAL 为 string 时 float(值) 成功即调 _check_weight_cap（字符串降级阈值不得绕过空间上限），最后调 _check_instruction_in_condition_space(stmt)。
    def _check_instruction(self, stmt: InstructionStmtNode):
        """检查指令语句"""
        instr_type = stmt.instruction

        # 1. 计算逻辑操作数（合并被误拆的多词短语）
        logical_ops = self._count_logical_operands(stmt.operands)

        # 1. 检查指令操作数约束
        if instr_type in INSTRUCTION_CONSTRAINTS:
            constraint = INSTRUCTION_CONSTRAINTS[instr_type]
            op_count = logical_ops

            if op_count < constraint["min_operands"]:
                self.errors.append(
                    f"L{stmt.line}:C{stmt.column} {constraint['description']}，"
                    f"但提供了 {op_count} 个操作数"
                )
            elif constraint["max_operands"] is not None and op_count > constraint["max_operands"]:
                self.warnings.append(
                    f"L{stmt.line}:C{stmt.column} 指令操作数过多 "
                    f"({op_count} > {constraint['max_operands']})"
                )

        # 2. 检查操作数中的标识符和字面量
        for op in stmt.operands:
            if op is None:
                continue
            if op.type == NodeType.IDENTIFIER:
                self._check_identifier(op.name, op.line, op.column)
            elif op.type == NodeType.LITERAL:
                self._check_literal(op)
                # 缺陷22：止（ZHI）的阈值经字符串降级（"0.9"）不得绕过
                # 空间上限——仅限止指令的字符串操作数且可 float 解析，
                # 非数值字符串（如"说明"）不受影响
                if (instr_type == TokenType.ZHI and
                        op.literal_type == "string"):
                    try:
                        self._check_weight_cap(op, float(op.literal_value))
                    except (TypeError, ValueError):
                        pass

        # 3. 检查当前条件空间是否允许该指令
        self._check_instruction_in_condition_space(stmt)

# 生效条件：以 stmt 调用时对 stmt.steps 逐项调 _check_step，steps 为空时无任何追加动作。
    def _check_shuyue(self, stmt: ShuyueNode):
        """检查术曰块"""
        for step in stmt.steps:
            self._check_step(step)

# 生效条件：以 stmt 调用时仅当 stmt.statement 为真值才递归 _check_statement(stmt.statement)，否则无动作。
    def _check_step(self, stmt: StepNode):
        """检查步骤"""
        if stmt.statement:
            self._check_statement(stmt.statement)

# 生效条件：stmt.target 命中模块级常量 PREDEFINED_SYMBOLS 且属于源码 protected 集合（存在优先/不伤害/信任优先/缩小信息差/协议降熵/知识统一/P0/P1/P2/验证单元/维生系统/记录单元/硬锚点/公理实现）时向 errors 追加"锚点层保护符号，不可赋值"并直接返回；否则 target 不在 symbol_table 时以 SymbolKind.VARIABLE 与 source="user_declared" 登记并把 name 加入 declared_in_current/user_declared，target 已在 symbol_table 时把其 used 置 True；stmt.value_node 为真值时检查该表达式；最后 target=="条件空间" 时调 _apply_space_assign_switch 联动条件空间检查上下文。
    def _check_assign(self, stmt: AssignStmtNode):
        """检查赋值语句"""
        target = stmt.target

        # 检查是否是受保护的预定义符号
        if target in PREDEFINED_SYMBOLS:
            sym = PREDEFINED_SYMBOLS[target]
            # 某些预定义符号不允许被赋值
            protected = {
                "存在优先", "不伤害", "信任优先", "缩小信息差",
                "协议降熵", "知识统一",
                "P0", "P1", "P2",
                "验证单元", "维生系统", "记录单元",
                "硬锚点", "公理实现",
            }
            if target in protected:
                self.errors.append(
                    f"L{stmt.line}:C{stmt.column} "
                    f"'{target}' 是锚点层保护符号，不可赋值"
                )
                return

        # 目标标识符未在符号表中 → 自动声明为用户变量
        if target not in self.symbol_table:
            self.symbol_table[target] = Symbol(
                name=target,
                kind=SymbolKind.VARIABLE,
                declared_at=(stmt.line, stmt.column),
                source="user_declared"
            )
            self.declared_in_current.add(target)
            self.user_declared.add(target)
        else:
            self.symbol_table[target].used = True

        # 检查值的表达式
        if stmt.value_node:
            self._check_expression(stmt.value_node)

        # 条件空间赋值 = 空间切换（SEMANTICS.md §1.2；VM STORE_NAME 对
        # BUILTIN_CONDITION_SPACE 真调 _switch_condition_space，见
        # condition_vm.py:208-213）——名实校验同步联动检查上下文，否则
        # 「条件空间 = 伴侣」后空间约束（情感权重上限 0.15 等）整体失效
        if target == "条件空间":  # condition_vm.BUILTIN_CONDITION_SPACE
            self._apply_space_assign_switch(stmt.value_node)

    # ---- 表达式检查 ----

# 生效条件：expr 为 None 时返回；否则按 expr.type 分派——IDENTIFIER→_check_identifier(expr.name, expr.line, expr.column)、BINARY_EXPR→递归 left 与 right、COMPARISON→递归 left 与 right 并调 _check_trust_comparison(expr)、LITERAL→_check_literal(expr)、UNARY_EXPR→对 expr.children（为 None 时按空列表）逐个递归、CALL_EXPR→有 name 属性时 _check_identifier(expr.name, expr.line, expr.column)，其余类型无动作。
    def _check_expression(self, expr: ASTNode):
        """检查表达式"""
        if expr is None:
            return

        if expr.type == NodeType.IDENTIFIER:
            self._check_identifier(expr.name, expr.line, expr.column)
        elif expr.type == NodeType.BINARY_EXPR:
            self._check_expression(expr.left)
            self._check_expression(expr.right)
        elif expr.type == NodeType.COMPARISON:
            self._check_expression(expr.left)
            self._check_expression(expr.right)
            # 额外检查：信任值比较的合理性
            self._check_trust_comparison(expr)
        elif expr.type == NodeType.LITERAL:
            self._check_literal(expr)
        elif expr.type == NodeType.UNARY_EXPR:
            for child in (expr.children or []):
                self._check_expression(child)
        elif expr.type == NodeType.CALL_EXPR:
            # 调用表达式：检查函数名
            if hasattr(expr, 'name'):
                self._check_identifier(expr.name, expr.line, expr.column)

    # ---- 专项检查 ----

# 生效条件：以 name/line/col 调用时——name 已在 symbol_table 则置其 used=True，且 source=="predefined" 时加入 predefined_used 后返回；否则 name 包含某个预定义符号（s in name 且 s != name）时以 attributes={"auto_declared":True,"contains":contained} 自动登记为用户变量并返回；否则存在被包含匹配（name in s 且 s != name）时向 warnings 追加"可能是 '{container[0]}' 的一部分"并返回；否则以 attributes={"auto_declared":True} 自动登记为用户变量。
    def _check_identifier(self, name: str, line: int, col: int):
        """检查标识符是否已声明

        匹配策略（v2.1）：
        1. 完全匹配 → 命中（预定义或用户声明）
        2. 子串匹配（包含预定义符号）→ 自动声明为用户变量
           （如 "新信任路径"、"累积信任值" 是合法的多词短语）
        3. 被包含匹配 → 警告（建议用完整名称）
        4. 均不匹配 → 自动声明为用户变量（宽松模式）
        """
        if name in self.symbol_table:
            self.symbol_table[name].used = True
            if self.symbol_table[name].source == "predefined":
                self.predefined_used.add(name)
            return

        # 子串匹配：包含已知预定义符号的多词短语
        # 这是预期行为（如 "新信任路径"、"累积信任值"）
        # 自动声明为用户变量，不报错
        contained = [s for s in PREDEFINED_SYMBOLS if s in name and s != name]
        if contained:
            # 自动声明为多词短语变量
            self.symbol_table[name] = Symbol(
                name=name,
                kind=SymbolKind.VARIABLE,
                declared_at=(line, col),
                source="user_declared",
                attributes={"auto_declared": True, "contains": contained}
            )
            self.user_declared.add(name)
            return

        # 被包含匹配：建议用完整名称
        container = [s for s in PREDEFINED_SYMBOLS if name in s and s != name]
        if container:
            self.warnings.append(
                f"L{line}:C{col} 标识符 '{name}' 可能是 "
                f"'{container[0]}' 的一部分，建议用完整名称"
            )
            return

        # 完全未匹配 → 自动声明（宽松模式，指令操作数常见）
        self.symbol_table[name] = Symbol(
            name=name,
            kind=SymbolKind.VARIABLE,
            declared_at=(line, col),
            source="user_declared",
            attributes={"auto_declared": True}
        )
        self.user_declared.add(name)

# 生效条件：仅当 node.literal_type == "number" 时检查——literal_value 为 int/float 且 < 0 则向 warnings 追加"负值"；literal_value 为 float 且 0.0 <= 值 <= 1.0 且（"trust" in str(node.value).lower() 或值 > 0.95）时才进入该分支，但其中 value > 1.0 的判断因外层已限 ≤1.0 恒不成立故不追加范围警告；literal_value 为 float 时调 _check_weight_cap 做表驱动空间上限检查（伴侣 0.15/工作 0.05，默认/未设空间不拦截）。
    def _check_literal(self, node: LiteralNode):
        """检查字面量"""
        if node.literal_type == "number":
            value = node.literal_value

            # 负数警告
            if isinstance(value, (int, float)) and value < 0:
                self.warnings.append(
                    f"L{node.line}:C{node.column} 负值: {value}"
                )

            # 信任值范围检查
            if isinstance(value, float) and 0.0 <= value <= 1.0:
                # 可能是信任值，检查上下文
                if "trust" in str(node.value).lower() or value > 0.95:
                    if value > 1.0:
                        self.warnings.append(
                            f"L{node.line}:C{node.column} 信任值超出 [0,1] 范围: {value}"
                        )

            # 情感权重超限检查（缺陷22：改表驱动——伴侣 0.15/工作 0.05
            # 均自 CONDITION_SPACE_RULES 取上限，工作空间上限修复前从不生效）
            if isinstance(value, float):
                self._check_weight_cap(node, value)

# 生效条件：current_condition_space 为 None 或 "默认" 时返回；CONDITION_SPACE_RULES.get(该名称) 为空或其 max_emotional_weight 为 None 时返回；value <= max_emotional_weight 时返回；否则向 errors 追加"L{node.line}:C{node.column} 在「{空间名}」条件空间中情感权重不可超过 {上限}，当前值: {value}"。「默认」不拦截：其规则自身 description 声明"默认条件空间，无特殊约束"，且既有语义（无空间/默认空间放行 0.9）为前三轮守卫钉死。
    def _check_weight_cap(self, node: ASTNode, value: float):
        """
        情感权重上限检查（表驱动，缺陷22）

        修复前硬编码「伴侣+0.15」，工作空间 0.05 上限（规则表明文）
        从不生效；上限自 CONDITION_SPACE_RULES.max_emotional_weight 取。
        「默认」与未设空间不拦截（默认空间自身声明无特殊约束）。
        """
        space = self.current_condition_space
        if space is None or space == "默认":
            return
        rules = CONDITION_SPACE_RULES.get(space)
        if not rules:
            return
        max_w = rules.get("max_emotional_weight")
        if max_w is None or value <= max_w:
            return
        self.errors.append(
            f"L{node.line}:C{node.column} 在「{space}」条件空间中"
            f"情感权重不可超过 {max_w}，当前值: {value}"
        )

# 生效条件：condition 为 None 时返回；仅当 condition.type == COMPARISON 且 condition.left 为 IDENTIFIER 且 left.name == "条件空间" 且 condition.right 为 IDENTIFIER 时——right.name 在模块级常量 CONDITION_SPACE_RULES 中则把 current_condition_space 置为该名称，否则 right.name 不在 PREDEFINED_SYMBOLS 中时向 warnings 追加"未知的条件空间: '{space_name}'"。
    def _check_condition_space_switch(self, condition: ASTNode):
        """
        检测条件语句中的条件空间切换
        如：若条件空间为伴侣 → 切换当前上下文为「伴侣」
        """
        # 检查是否为 "条件空间 为/等于 X" 的模式
        if condition is None:
            return

        if condition.type == NodeType.COMPARISON:
            left = condition.left
            right = condition.right

            # 左操作数是 "条件空间"，右操作数是空间名称
            if (left and left.type == NodeType.IDENTIFIER and
                    left.name == "条件空间"):
                if right and right.type == NodeType.IDENTIFIER:
                    space_name = right.name
                    if space_name in CONDITION_SPACE_RULES:
                        self.current_condition_space = space_name
                    elif space_name not in PREDEFINED_SYMBOLS:
                        self.warnings.append(
                            f"L{right.line}:C{right.column} "
                            f"未知的条件空间: '{space_name}'"
                        )

# 生效条件：value_node 为 None 时返回；value_node.type 为 IDENTIFIER 时取其 name、为 LITERAL 且 literal_type=="string" 时取其 literal_value 作 space_name，其余形态（数值字面量/表达式/其他）直接返回不动作；space_name 为"恢复默认"时把 current_condition_space 置"默认"（VM 弹栈到根语义），在 CONDITION_SPACE_RULES 中时置为该名称，否则不在 PREDEFINED_SYMBOLS 中时向 warnings 追加"L{value_node.line}:C{value_node.column} 未知的条件空间: '{space_name}'"。
    def _apply_space_assign_switch(self, value_node: ASTNode):
        """
        赋值「条件空间 = <空间名>」的检查上下文联动

        VM 侧 STORE_NAME 对 BUILTIN_CONDITION_SPACE 真切换
        （condition_vm.py:208-213；SEMANTICS.md §1.2），名实校验须同步，
        否则赋值形态使空间约束（如伴侣空间情感权重上限 0.15）失效。
        语义对齐 _check_condition_space_switch 与 VM _switch_condition_space。
        """
        if value_node is None:
            return

        # 空间名可来自标识符（条件空间 = 伴侣）或字符串字面量（= "伴侣"）
        if value_node.type == NodeType.IDENTIFIER:
            space_name = value_node.name
        elif (value_node.type == NodeType.LITERAL and
                getattr(value_node, "literal_type", None) == "string"):
            space_name = value_node.literal_value
        else:
            # 数值/表达式等非空间名形态：不动上下文（VM 无对应静态规则）
            return

        if space_name == "恢复默认":
            # VM 语义：弹栈到根并置名「默认」（SEMANTICS.md §1.2）
            self.current_condition_space = "默认"
        elif space_name in CONDITION_SPACE_RULES:
            self.current_condition_space = space_name
        elif space_name not in PREDEFINED_SYMBOLS:
            self.warnings.append(
                f"L{value_node.line}:C{value_node.column} "
                f"未知的条件空间: '{space_name}'"
            )

# 生效条件：self.current_condition_space 为假值（None 或空串）时返回；CONDITION_SPACE_RULES.get(该名称) 为空时返回；allowed = rules.get("allowed_instructions") 为 None 时返回"无限制"；否则 instr_name 非空（stmt.instruction 在源码 instr_names 映射中）且不在 allowed 中时向 warnings 追加"指令 '{instr_name}' 可能受限"。
    def _check_instruction_in_condition_space(self, stmt: InstructionStmtNode):
        """检查当前条件空间是否允许该指令"""
        if not self.current_condition_space:
            return

        space_rules = CONDITION_SPACE_RULES.get(self.current_condition_space)
        if not space_rules:
            return

        allowed = space_rules.get("allowed_instructions")
        if allowed is None:
            return  # 无限制

        # 获取指令的中文名
        instr_names = {
            TokenType.DAO: "道", TokenType.DE: "德",
            TokenType.ZIRAN: "自然", TokenType.WUWEI: "无为",
            TokenType.GU: "谷", TokenType.PIN: "牝",
            TokenType.ROU: "柔", TokenType.PU: "朴",
            TokenType.ZHI: "止", TokenType.ZHIZU: "知足",
        }
        instr_name = instr_names.get(stmt.instruction, "")

        if instr_name and instr_name not in allowed:
            self.warnings.append(
                f"L{stmt.line}:C{stmt.column} 在「{self.current_condition_space}」"
                f"条件空间中，指令 '{instr_name}' 可能受限"
            )

# 生效条件：expr 不是 ComparisonNode 实例时返回；否则当 expr.left/expr.right 中 IDENTIFIER 的名字属于 {"信任值","P_trust","T_pred","T_context","E_weight","情感权重"}，且 expr.right 为 LITERAL、其 literal_value 为 int/float 且 < 0 或 > 1 时，向 warnings 追加"信任值比较阈值 {val} 超出 [0,1] 范围"。
    def _check_trust_comparison(self, expr: ASTNode):
        """检查信任值比较的合理性"""
        if not isinstance(expr, ComparisonNode):
            return

        # 检查是否涉及信任值
        trust_identifiers = {"信任值", "P_trust", "T_pred", "T_context", "E_weight", "情感权重"}

        left_name = ""
        right_name = ""
        if expr.left and expr.left.type == NodeType.IDENTIFIER:
            left_name = expr.left.name
        if expr.right and expr.right.type == NodeType.IDENTIFIER:
            right_name = expr.right.name

        # 如果比较的是信任值，检查阈值合理性
        if left_name in trust_identifiers or right_name in trust_identifiers:
            # 右操作数应该是数值
            if expr.right and expr.right.type == NodeType.LITERAL:
                val = expr.right.literal_value
                if isinstance(val, (int, float)):
                    if val < 0 or val > 1:
                        self.warnings.append(
                            f"L{expr.line}:C{expr.column} "
                            f"信任值比较阈值 {val} 超出 [0,1] 范围"
                        )

    # ---- 公共方法 ----

# 生效条件：以 name 与 kind 调用即用 Symbol(name=name, kind=kind, declared_at=(line, col), source="user_declared") 覆盖写入 symbol_table，并把 name 加入 declared_in_current 与 user_declared；line/col 省略时均取 0。
    def declare(self, name: str, kind: SymbolKind, line: int = 0, col: int = 0):
        """手动声明符号"""
        self.symbol_table[name] = Symbol(
            name=name, kind=kind,
            declared_at=(line, col),
            source="user_declared"
        )
        self.declared_in_current.add(name)
        self.user_declared.add(name)

# 生效条件：以 name 调用时返回 self.symbol_table.get(name)，name 不在符号表中时返回 None。
    def get_symbol(self, name: str) -> Optional[Symbol]:
        """获取符号"""
        return self.symbol_table.get(name)

# 生效条件：无必需形参，调用即返回 self.symbol_table 的 dict 浅拷贝，与调用时符号表内容一致。
    def get_all_symbols(self) -> Dict[str, Symbol]:
        """获取所有符号"""
        return dict(self.symbol_table)

    def get_predefined_symbols(self) -> Dict[str, Symbol]:
        """仅获取预定义符号"""
        return {n: s for n, s in self.symbol_table.items()
                if s.source == "predefined"}

    def get_user_symbols(self) -> Dict[str, Symbol]:
        """仅获取用户声明符号"""
        return {n: s for n, s in self.symbol_table.items()
                if s.source == "user_declared"}

# 生效条件：以 kind 调用时返回 self.symbol_table.values() 中 s.kind == kind 的符号列表，无匹配时返回空列表。
    def get_symbols_by_kind(self, kind: SymbolKind) -> List[Symbol]:
        """按种类获取符号"""
        return [s for s in self.symbol_table.values() if s.kind == kind]

# 生效条件：以 space_name 调用即无条件把 self.current_condition_space 置为该值，空串或 None 也照样写入且不做校验或回落。
    def set_condition_space(self, space_name: str):
        """手动设置当前条件空间"""
        self.current_condition_space = space_name

# 生效条件：无必需形参，调用后 symbol_table 重新等于模块级常量 PREDEFINED_SYMBOLS 的 dict 副本，errors/warnings 为空列表，declared_in_current/predefined_used/user_declared 为空集，current_condition_space 为 None。
    def reset(self):
        """重置（保留预定义符号）"""
        self.symbol_table = dict(PREDEFINED_SYMBOLS)
        self.errors = []
        self.warnings = []
        self.declared_in_current = set()
        self.predefined_used = set()
        self.user_declared = set()
        self.current_condition_space = None

# 生效条件：required 为空，固定输出标题三段并遍历 sorted(self.predefined_used) 追加每个能在 symbol_table.get(name) 命中的符号行（缺键或假值则跳过）；当 self.user_declared、self.errors、self.warnings 各自非空时追加对应段落，而 errors 与 warnings 同时为空时改为输出「名实校验通过，无错误无警告」行，最终返回这些行以 "\n" 连接的结果。
    def report(self) -> str:
        """生成校验报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("名实校验报告")
        lines.append("=" * 60)

        # 预定义符号使用统计
        lines.append(f"\n📋 预定义符号使用: {len(self.predefined_used)} 个")
        for name in sorted(self.predefined_used):
            sym = self.symbol_table.get(name)
            if sym:
                section = sym.attributes.get("section", "?")
                lines.append(f"  ✅ {name} ({section})")

        # 用户声明符号
        if self.user_declared:
            lines.append(f"\n📝 用户声明符号: {len(self.user_declared)} 个")
            for name in sorted(self.user_declared):
                sym = self.symbol_table.get(name)
                if sym:
                    lines.append(f"  📌 {name} ({sym.kind.value})")

        # 错误
        if self.errors:
            lines.append(f"\n❌ 错误 ({len(self.errors)} 个):")
            for e in self.errors:
                lines.append(f"  {e}")

        # 警告
        if self.warnings:
            lines.append(f"\n⚠️ 警告 ({len(self.warnings)} 个):")
            for w in self.warnings:
                lines.append(f"  {w}")

        if not self.errors and not self.warnings:
            lines.append("\n✅ 名实校验通过，无错误无警告")

        return "\n".join(lines)


# =============================================================================
# 便捷函数
# =============================================================================

# 生效条件：传入 ast 时构造 NameChecker 并对其执行 check，返回 (错误列表, 警告列表)；
def check_names(ast: ProgramNode) -> Tuple[List[str], List[str]]:
    """便捷函数：对 AST 执行名实校验"""
    checker = NameChecker()
    return checker.check(ast)


# 生效条件：无入参，调用即遍历模块级常量 PREDEFINED_SYMBOLS 返回按 'section' 排序的 name/kind/section/description 字典列表；
def get_predefined_symbol_list() -> List[Dict[str, str]]:
    """获取所有预定义符号的清单（用于文档生成/IDE提示）"""
    result = []
    for name, sym in PREDEFINED_SYMBOLS.items():
        result.append({
            "name": name,
            "kind": sym.kind.value,
            "section": sym.attributes.get("section", ""),
            "description": sym.attributes.get("description", ""),
        })
    return sorted(result, key=lambda x: x["section"])


# =============================================================================
# 测试
# =============================================================================

if __name__ == "__main__":
    test_code = """若条件空间为伴侣，则止情感权重于0.15。
道 新信任路径
德 累积信任值
问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：1。柔 响应强度；2。自然 恢复默认；3。知足 验证单元。"""

    print("=" * 60)
    print("名实校验器 v2.0 测试")
    print("=" * 60)
    print(f"\n源代码：\n{test_code}\n")

    # 词法分析
    from .lexer import tokenize
    tokens, lex_errors = tokenize(test_code)

    if lex_errors:
        print("词法错误：")
        for e in lex_errors:
            print(f"  ❌ {e}")

    # 语法分析
    ast = parse_tokens(tokens, [])

    # 名实校验
    checker = NameChecker()
    errors, warnings = checker.check(ast)

    # 输出报告
    print(checker.report())

    # 输出符号表摘要
    print(f"\n{'─' * 60}")
    print("预定义符号清单（部分）：")
    predef = get_predefined_symbol_list()
    for item in predef[:15]:
        print(f"  {item['name']:12s} [{item['section']:>6s}] {item['description'][:40]}")
    print(f"  ... 共 {len(predef)} 个预定义符号")