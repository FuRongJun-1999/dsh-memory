# -*- coding: utf-8 -*-
"""关系类型白名单（relation_type 的唯一合法域真源）。

# 功能名：关系类型白名单与分级校验
# 生效条件：写入或校验节点 edges[].relation_type 时；扫描全库关系类型分布时
# 子功能：①合法类型集（按真实边分布定，非代码字面量）②空串=未标注（合法）③分级校验纯函数
# 执行：reltype_verdict / distribution / singletons / unlabeled_rate
# 验证方式：tests/test_relation_type_whitelist_guard.py
# 不适用条件：不判「类型名对了但语义错」（语义判定不可机械验证，同 I3/I6）；
#             不适用于清理空串（那是未标注，不是错误）
"""
from __future__ import annotations

#: 合法关系类型集。实取依据（2026-10-23，全库 7350 条边）：
#:   generalizes=1034 / instance_of=456 / reference=310 / depends_on=4
#:   derived_from=2 / collaborator=1（孤例） / 空串=5543（未标注）
RELATION_TYPES = frozenset({
    "generalizes",
    "instance_of",
    "reference",
    "depends_on",
    "derived_from",
    "collaborator",   # 孤例：先进白名单避免存量变非法；列入待复核
    "tension",        # 新增（使用者裁定 A：允许写入，但无消费者遍历——只沉淀）
})

#: 空串 = 未标注。合法，但计入「未标注率」。
#: 边类型是可选标注，与条件空间（必填，缺则 REJECT）地位不同。
UNLABELED = ""

#: 核心集。孤例复核参照：不在此集且频次为 1 者列入待复核。
CORE_TYPES = frozenset({"generalizes", "instance_of", "reference"})

#: 当前已知孤例（待复核：有效类型还是笔误）。
KNOWN_SINGLETONS = ("collaborator",)

#: 分级模式默认值（env MDCG_RELTYPE_GATE 覆盖）：只报告不阻断。
DEFAULT_MODE = "observe"
VALID_MODES = ("observe", "enforce")


def normalize(relation_type) -> str:
    """去空白后的类型串；None 归一为空串。"""
    return "" if relation_type is None else str(relation_type).strip()


def reltype_verdict(relation_type):
    """返回 (ok, kind)。kind 属于 {labeled_ok, unlabeled, unknown}。"""
    rel = normalize(relation_type)
    if rel == UNLABELED:
        return True, "unlabeled"
    if rel in RELATION_TYPES:
        return True, "labeled_ok"
    return False, "unknown"


def resolve_mode(raw, default: str = DEFAULT_MODE) -> str:
    """把调用方给的原始值归一为合法模式；非法/None 回落 default。

    注意：本模块**不读环境变量**——读 env 是调用方的职责，模块只做纯判定。
    （首版曾在模块内 os.environ.get，被 check_config_env_registry 的 C1 判为新缺口；
      按「纯逻辑模块不读 env」的设计修正，而非往登记表加一行。）
    """
    m = ("" if raw is None else str(raw)).strip().lower()
    return m if m in VALID_MODES else default


def should_block(relation_type, mode: str) -> bool:
    """enforce 模式下未知类型应阻断；observe 一律不阻断。"""
    ok, _kind = reltype_verdict(relation_type)
    return (not ok) and (mode == "enforce")


def distribution(edges_iter) -> dict:
    """统计 relation_type 分布，返回 {type: count}；空串键为 UNLABELED。"""
    out = {}
    for rel in edges_iter:
        k = normalize(rel)
        out[k] = out.get(k, 0) + 1
    return out


def singletons(dist: dict) -> list:
    """频次为 1 且非未标注的类型，返回待复核列表。"""
    return sorted(k for k, v in dist.items() if v == 1 and k != UNLABELED)


def unlabeled_rate(dist: dict) -> float:
    """未标注率 = 空串边 / 全部边。无边界返回 0.0。"""
    total = sum(dist.values())
    return 0.0 if not total else dist.get(UNLABELED, 0) / total
