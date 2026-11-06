# -*- coding: utf-8 -*-
"""灵枢 1.0 接口层（iface）——四个契约的类型面，W1 骨架。

真源：docs/architecture/灵枢1.0_建设路线_v0.1.md §3「四个接口契约（最小签名）」。

    Write      write(node_id, content, conditions, provenance) -> {id, state, receipt}
    Read       read(query, context) -> [{id, score, why, state, evidence_ref}]
    Govern     revise / retire / rollback / audit(ts_range)
    SelfCheck  status() -> {counts, lag, drift, wal_ok}

本模块只声明**契约形状与不变量**，不含任何实现（M1：建空壳 + 契约类型）。
M2 起把读路径接到新内核；M3 写路径；M4 治理面。

禁止项（路线稿 §2）：本层**不得依赖任何 HTTP/MCP 类型**，只吃 dict/JSON；
适配层不得直接读写存储文件。

不变量（逐条可测，见 md_cg/test_kernel_iface_contracts.py）：
- W1  ``provenance`` 必填（依据链）；写失败必须留账。
- R1  ``why`` 必填（依据什么命中）；``state`` 只来自治理层。
- R2  打分层不得输出 ``state``（#111 既定契约）。
- G1  任何修订可回滚；回滚**覆盖正文**。
- S1  ``status()`` 必须能在不读全部节点的情况下答「我坏没坏」。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Tuple, runtime_checkable

__all__ = [
    "CONTRACT_NAMES",
    "IFACE_LAYER",
    "RecordState",
    "WriteRequest",
    "WriteReceipt",
    "ReadItem",
    "ReadRequest",
    "SelfCheckReport",
    "WriteContract",
    "ReadContract",
    "GovernContract",
    "SelfCheckContract",
    "ContractViolation",
    "require_provenance",
    "require_why",
    "reject_state_in_scoring",
]

IFACE_LAYER = "iface"

#: 四个契约的固定名字（路线稿 §3 只有四个；增删即破坏冻结面）。
CONTRACT_NAMES: Tuple[str, str, str, str] = ("Write", "Read", "Govern", "SelfCheck")


class ContractViolation(ValueError):
    """契约不变量被违反。携带稳定的 ``code`` 供守卫断言（不靠异常文案）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code


#: 节点状态枚举。**只允许治理层产出**（不变量 R2）。
RecordState = ("active", "dormant", "retired", "tombstoned")


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractViolation("not_a_mapping", f"{field} 必须是 mapping，收到 {type(value).__name__}")
    return value


def require_provenance(provenance: Any) -> Mapping[str, Any]:
    """Write 不变量：``provenance`` 必填且非空（依据链）。

    生效条件：``provenance`` 为 mapping 且至少有一个键值 → 原样返回；空 mapping、
    非 mapping、None 三态均抛 ``ContractViolation``（code 分别为
    ``empty_provenance`` / ``not_a_mapping`` / ``missing_provenance``）。
    """
    if provenance is None:
        raise ContractViolation("missing_provenance", "Write 必须带 provenance（依据链），不得为空")
    mapping = _require_mapping(provenance, "provenance")
    if not mapping:
        raise ContractViolation("empty_provenance", "provenance 不得为空 mapping——依据链必须可指认")
    return mapping


def require_why(why: Any) -> str:
    """Read 不变量：``why`` 必填且非空白（依据什么命中）。"""
    if why is None:
        raise ContractViolation("missing_why", "Read 命中必须带 why（依据什么命中）")
    if not isinstance(why, str):
        raise ContractViolation("not_a_string", f"why 必须是 str，收到 {type(why).__name__}")
    if not why.strip():
        raise ContractViolation("empty_why", "why 不得为空白字符串")
    return why


def reject_state_in_scoring(items: Iterable[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """打分层不得输出 ``state``（#111 既定契约，路线稿 §4）。

    生效条件：``items`` 中任一元素含非空 ``state`` 键即抛 ``ContractViolation``
    （code=``state_in_scoring``）；全部不含则原样返回列表。

    为什么这条要单独成函数：路线稿 §4 把「``search_rrf`` 内含资格判定调用」
    列为本轮要拆的耦合——拆分后打分与治理分属两层，**跨层泄漏必须可测**。
    """
    out: List[Mapping[str, Any]] = []
    for index, item in enumerate(items):
        _require_mapping(item, f"items[{index}]")
        if item.get("state"):
            raise ContractViolation(
                "state_in_scoring",
                f"items[{index}] 含 state={item.get('state')!r}——打分层不得输出 state（#111）",
            )
        out.append(item)
    return out


class WriteRequest:
    """``Write.write`` 的入参形状。不可变；``provenance`` 构造时即校验。"""

    __slots__ = ("node_id", "content", "conditions", "provenance")

    def __init__(
        self,
        node_id: str,
        content: str,
        conditions: Optional[Mapping[str, Any]] = None,
        provenance: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if not isinstance(node_id, str) or not node_id.strip():
            raise ContractViolation("bad_node_id", "node_id 必须是非空白字符串")
        if not isinstance(content, str):
            raise ContractViolation("bad_content", f"content 必须是 str，收到 {type(content).__name__}")
        self.node_id = node_id
        self.content = content
        self.conditions = dict(conditions or {})
        self.provenance = dict(require_provenance(provenance))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "content": self.content,
            "conditions": dict(self.conditions),
            "provenance": dict(self.provenance),
        }

    def digest(self) -> str:
        """内容指纹（供 receipt 与实际落盘对账）。纯计算，无 IO。"""
        payload = json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return f"WriteRequest(node_id={self.node_id!r}, digest={self.digest()[:12]}…)"


class WriteReceipt:
    """``Write`` 的回执。写失败**必须留账**（不变量 W1），故 ``ledger`` 为必填字段。"""

    __slots__ = ("receipt_id", "node_id", "state", "digest", "ledger")

    def __init__(
        self,
        receipt_id: str,
        node_id: str,
        state: str,
        digest: str,
        ledger: Mapping[str, Any],
    ) -> None:
        if state not in RecordState:
            raise ContractViolation("bad_state", f"state 必须属于 {RecordState}，收到 {state!r}")
        _require_mapping(ledger, "ledger")
        if not ledger:
            raise ContractViolation("empty_ledger", "写失败必须留账——ledger 不得为空")
        self.receipt_id = receipt_id
        self.node_id = node_id
        self.state = state
        self.digest = digest
        self.ledger = dict(ledger)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.receipt_id,
            "node_id": self.node_id,
            "state": self.state,
            "digest": self.digest,
            "ledger": dict(self.ledger),
        }


class ReadRequest:
    """``Read.read`` 的入参形状。``context`` 只吃 dict（禁止宿主类型）。"""

    __slots__ = ("query", "context")

    def __init__(self, query: str, context: Optional[Mapping[str, Any]] = None) -> None:
        if not isinstance(query, str) or not query.strip():
            raise ContractViolation("bad_query", "query 必须是非空白字符串")
        self.query = query
        self.context = dict(_require_mapping(context or {}, "context"))

    def as_dict(self) -> Dict[str, Any]:
        return {"query": self.query, "context": dict(self.context)}


class ReadItem:
    """``Read`` 的单条命中。``why`` / ``state`` / ``evidence_ref`` 三件套是契约核心。"""

    __slots__ = ("node_id", "score", "why", "state", "evidence_ref")

    def __init__(
        self,
        node_id: str,
        score: float,
        why: str,
        state: Optional[str],
        evidence_ref: Optional[str],
    ) -> None:
        if not isinstance(node_id, str) or not node_id.strip():
            raise ContractViolation("bad_node_id", "node_id 必须是非空白字符串")
        self.node_id = node_id
        self.score = float(score)
        self.why = require_why(why)
        if state is not None and state not in RecordState:
            raise ContractViolation("bad_state", f"state 必须属于 {RecordState}，收到 {state!r}")
        self.state = state
        if evidence_ref is not None and not isinstance(evidence_ref, str):
            raise ContractViolation("bad_evidence_ref", "evidence_ref 必须是 str 或 None")
        self.evidence_ref = evidence_ref

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.node_id,
            "score": self.score,
            "why": self.why,
            "state": self.state,
            "evidence_ref": self.evidence_ref,
        }


class SelfCheckReport:
    """``SelfCheck.status`` 的返回。四个键一个都不能少（路线稿 §3）。"""

    __slots__ = ("counts", "lag", "drift", "wal_ok")

    _REQUIRED = ("counts", "lag", "drift", "wal_ok")

    def __init__(
        self,
        counts: Mapping[str, Any],
        lag: float,
        drift: bool,
        wal_ok: bool,
    ) -> None:
        _require_mapping(counts, "counts")
        self.counts = dict(counts)
        self.lag = float(lag)
        self.drift = bool(drift)
        self.wal_ok = bool(wal_ok)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "counts": dict(self.counts),
            "lag": self.lag,
            "drift": self.drift,
            "wal_ok": self.wal_ok,
        }

    def missing_keys(self) -> List[str]:
        """供守卫断言「四个键齐备」；缺失即不满足 SelfCheck 契约。"""
        present = set(self.as_dict())
        return [key for key in self._REQUIRED if key not in present]


@runtime_checkable
class WriteContract(Protocol):
    """Write 契约（路线稿 §3）。M2 起由内核实现。"""

    def write(self, request: WriteRequest) -> WriteReceipt:  # pragma: no cover - 协议声明
        ...


@runtime_checkable
class ReadContract(Protocol):
    """Read 契约。返回的每一条都必须满足 ``require_why``。"""

    def read(self, request: ReadRequest) -> List[ReadItem]:  # pragma: no cover - 协议声明
        ...


@runtime_checkable
class GovernContract(Protocol):
    """Govern 契约：revise / retire / rollback / audit。回滚**覆盖正文**。"""

    def revise(self, node_id: str, content: str, provenance: Mapping[str, Any]) -> Mapping[str, Any]:  # pragma: no cover
        ...

    def retire(self, node_id: str, reason: str) -> Mapping[str, Any]:  # pragma: no cover
        ...

    def rollback(self, revision_id: str) -> Mapping[str, Any]:  # pragma: no cover
        ...

    def audit(self, ts_range: Tuple[float, float]) -> List[Mapping[str, Any]]:  # pragma: no cover
        ...


@runtime_checkable
class SelfCheckContract(Protocol):
    """SelfCheck 契约：不读全部节点也能答「我坏没坏」。"""

    def status(self) -> SelfCheckReport:  # pragma: no cover - 协议声明
        ...
