# -*- coding: utf-8 -*-
"""ccgc.py · 对话记录 → CCG 六要素编译器（接口契约形态）。

裁定 B（使用者 2026-09-16）：六要素不是注释，是**接口契约**——
    功能名 = 签名 signature ｜ 生效条件 = 前置条件 precondition
    子功能 = 依赖 dependency ｜ 执行 = 调用 invocation
    验证方式 = 后置条件 postcondition + test ｜ 不适用条件 = 拒绝域 rejection_domain
缺任一入参即**编译错误**（E001-E004），不静默降级、不猜、不发明。

裁定 A（使用者 2026-09-16）：**LLM 不得自己验证自己**。本模块是三段式中间段——
    compile（生成候选） → attest（认知图**外**的验证方签章） → link（签章通过才写入）
LLM 若参与，只能经 `parser=` 注入（能力外置，与 compiler 的 llm_bridge 同构），
且其产物**必须**过名实门（E010/E011）：每个写入值都必须是对话记录的**字面子串**，
幻觉在编译期即被机械检出，不进「看起来合理」的灰区。
签章字段在候选结构里**没有位置**：`verifier` 只能由 attest 显式给出，
且 E041 机械拒绝 `verifier == 编译执行者`——结构级阻断，不依赖 prompt 自觉。

对齐既有实现（零发明）：
    · 验证能力外置 / 缺能力恒不通过  → md_cg/audit.py（CONTENT_KINDS + register_verifier）
    · 缺参即 error、success 由 errors 定 → compiler/api.py（CompileResult 范式）
    · 生效条件唯一合成入口            → nodefile.condition_space_text（本模块不另写合成）
    · 六行写入口径                    → consolidate._upsert_ccg_line（同款语义，就地实现防 import 环）
    · 留痕可回滚                      → 对齐 backfill 的 _backfill.jsonl 纪律
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from . import nodefile

# ---- 四态：复用 audit / judge_qualification 的裁决语汇（不新造状态机） ----
ACCEPT, REJECT, DEFER, BLINDSPOT = "ACCEPT", "REJECT", "DEFER", "BLINDSPOT"
STATES = (ACCEPT, REJECT, DEFER, BLINDSPOT)

LOG_NAME = "_ccgc.jsonl"

# ---- 裁定 B：六要素的契约角色（术语真源在 nodefile，此处只引用不另定义） ----
# 单一真源纪律：术语若在 ccgc 再写一份，会与 nodefile 漂移（谁是真源无从判定）。
CONTRACT_ROLES = nodefile.CCG_CONTRACT_ROLES

# ---- 编译错误码（裁定 B：缺参数即编译错误，绝不静默降级） ----
E_CODES = {
    "E001": "缺少源：dialog 为空（无可编译的对话记录）",
    "E002": "缺少目标：node_id 为空或节点不存在",
    "E003": "缺少主体：actor 为空（验证溯源必需）",
    "E004": "源不可读：密文或权限拒绝（fail-closed）",
    "E010": "引用定位失败：span 不是对话记录的字面子串",
    "E011": "值捏造：写入值不是对话记录的字面子串",
    "E020": "四槽不全：condition_space 缺槽，不构成生效条件",
    "E021": "槽值非法：空值、待填充占位或不可渲染",
    "E030": "验证基底非法：不在 VERIFICATION_BASIS 枚举内",
    "E040": "无验证签章：未提供 attestation（缺能力恒不写入）",
    "E041": "自证拒绝：验证方标识 == 编译执行者（LLM 不得自己验证自己）",
    "E042": "验证未通过：签章判定 REJECT / BLINDSPOT",
    "E043": "修正非法：只允许修正 condition_space 四槽",
    "E050": ("依赖声明缺失：正文以 `@<节点 id>` 声明了跨节点依赖（「# 子功能：」行），"
             "但 depends_on 未给出可解析目标——依赖必须是可解析的字段，不能只是散文"),
    "E051": "依赖目标不存在：depends_on 指向的节点不在库中（悬空依赖）",
}

# ---- 候选来源标识（写进留痕，可溯源到「谁说的」） ----
SRC_EXPLICIT = "explicit"        # 显式入参（人 / 设计者提供）
SRC_PARSER = "parser"            # 外部注入解析器（LLM 等能力外置通道）
SRC_RULE = "rule"                # 内生规则解析器（诚实下界能力）

#: 参与名实门的五要素（生效条件由四槽合成，不来自候选，故不在此列）
_CAND_MARKS = ("功能名", "子功能", "执行", "验证方式", "不适用条件")


# =============================================================================
# 结果对象（对齐 compiler/api.py 的 CompileResult 范式）
# =============================================================================

@dataclass
class CompileResult:
    """编译结果。`success = (len(errors) == 0)`——与 compiler 同口径。"""
    success: bool = False
    node_id: str = ""
    actor: str = ""
    lines: Dict[str, str] = field(default_factory=dict)         # 六要素行
    slots: Dict[str, Any] = field(default_factory=dict)         # condition_space 四槽
    spans: Dict[str, List[str]] = field(default_factory=dict)   # 要素 → 引用 span 清单
    sources: Dict[str, str] = field(default_factory=dict)       # 要素 → explicit|parser|rule
    ungrounded: List[Dict[str, str]] = field(default_factory=list)   # 未过名实门的项
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    verdict: Optional[Dict] = None                              # 验证单元终裁

    @property
# 生效条件：BLINDSPOT：缺证据（无 required 形参与模块级常量，仅有未给出的 self.errors 来源）。
    def has_errors(self) -> bool:
        return len(self.errors) > 0

# 生效条件：对任意 code，msg 取 E_CODES.get(code, code)（缺键回落 code 本身），向 self.errors 追加 "code 空格 msg"，extra 为真值时再追加 "（extra）"。
    def err(self, code: str, extra: str = "") -> None:
        msg = E_CODES.get(code, code)
        self.errors.append(code + " " + msg + (("（" + extra + "）") if extra else ""))

# 生效条件：无入参，首行按 self.success 输出「编译成功」或「编译失败（len(self.errors) 个错误）」，要素行取 nodefile.CCG_MARKS 与 self.lines 的交集，errors 列前 10 条、warnings 列前 5 条，返回 "\n".join(out)。
    def summary(self) -> str:
        out = ["编译成功" if self.success else
               "编译失败（%d 个错误）" % len(self.errors)]
        out.append("  节点: %s" % (self.node_id or "-"))
        out.append("  要素: %s" % ", ".join(k for k in nodefile.CCG_MARKS if k in self.lines))
        for e in self.errors[:10]:
            out.append("  ERROR " + e)
        for w in self.warnings[:5]:
            out.append("  WARN  " + w)
        return "\n".join(out)


@dataclass
class AttestResult:
    """验证签章结果。`ok=True` 才构成 link 的准入凭证。"""
    ok: bool = False
    node_id: str = ""
    state: str = ""
    verifier: str = ""              # 认知图**外**的验证方（子代理 / designer / user）
    compiled_by: str = ""           # 编译执行者（供 E041 比对）
    evidence: str = ""
    error: str = ""
    token: str = ""                 # 签章令牌（留痕可查）
    slot_corrections: Dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0


@dataclass
class LinkResult:
    ok: bool = False
    node_id: str = ""
    dry_run: bool = True
    written: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    entry_id: str = ""


# =============================================================================
# 工具（就地实现，避免跨模块 import 环——与 mdcg.py 复制 _ccg_line 的既有做法一致）
# =============================================================================

# 生效条件：对任意 s（含 None/空串，源码以 `(s or "")` 兜底为空串），返回 hashlib.sha1(该串 utf-8 编码).hexdigest()[:12]。
def _sha(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:12]


# 生效条件：对任意 cg，返回 os.path.join(cg.root, LOG_NAME)（即 cg.root 与模块级常量 LOG_NAME 的拼接）。
def _log_path(cg) -> str:
    return os.path.join(cg.root, LOG_NAME)


# 生效条件：x 为 None 或非 str 时原样返回 x；x 为 str 时返回 MdCGOS(x) 构造出的 cg 实例。
def _as_cg(x):
    """接受 root 路径或已构造的 cg 实例——保持密级隔离与密钥上下文。"""
    if x is None or not isinstance(x, str):
        return x
    from .mdcos import MdCGOS
    return MdCGOS(x)


# 生效条件：content 为字符串（None 视作空串）时，若其中含 "# " + field_name + "：" 或 "# " + field_name + ":" 则返回 True，否则 False。
def _has_ccg_line(content: str, field_name: str) -> bool:
    text = content or ""
    return ("# " + field_name + "：") in text or ("# " + field_name + ":") in text


# 生效条件：在 `(content or "").split("\n")` 中命中首个 strip 后以 "#" 开头、含 field_name、且去 "#" 后按全角或半角冒号切出的名字等于 field_name 的行→替换为 "# field_name：value" 并返回；否则若有行 strip 后以 "# 功能名" 开头→在该行后插入新行并返回；否则返回 `"# field_name：value\n" + (content or "")`。
def _upsert_ccg_line(content: str, field_name: str, value: str) -> str:
    """写入/替换 `# <字段>：<值>`，优先插在「# 功能名」之后。

    与 consolidate._upsert_ccg_line 同款语义（就近实现，避免 import 环）。
    """
    lines = (content or "").split("\n")
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("#") or field_name not in s:
            continue
        name = s.lstrip("#").strip().split("：")[0].split(":")[0].strip()
        if name == field_name:
            lines[i] = "# " + field_name + "：" + value
            return "\n".join(lines)
    newline = "# " + field_name + "：" + value
    for i, ln in enumerate(lines):
        if ln.strip().startswith("# 功能名"):
            lines.insert(i + 1, newline)
            return "\n".join(lines)
    return newline + "\n" + (content or "")


# 生效条件：对任意 path 与 rec，以追加模式写入 json.dumps(rec, ensure_ascii=False) + "\n"，仅 OSError 被吞掉且无返回值。
def _append_jsonl(path: str, rec: dict) -> None:
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


# 生效条件：path 为假值或 os.path.exists(path) 为假→返回 []；否则逐行 strip、跳过空行、json.loads 成功者追加、单行 json.loads 抛 ValueError 者跳过，中途 open/读取抛 OSError 时返回 []；全部读完返回 out。
def _read_jsonl(path: str) -> List[dict]:
    out: List[dict] = []
    if not path or not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    continue
    except OSError:
        return []
    return out


# =============================================================================
# 名实门（幻觉的编译期机械检出）
# =============================================================================

#: 值分片分隔符——值可为多句枚举，但**每个分片**都必须是原文子串
_FRAG_SPLIT = re.compile(r"[；;、，,]+")


# 生效条件：value 经 `str(value).strip()`（None 记 ""）后为空→False；否则按 _FRAG_SPLIT 切分并去掉空分片，若分片列表为空→False；否则返回全部分片都在 dialog 中的 all 判定结果。
def _value_grounded(dialog: str, value) -> bool:
    """值是否 grounded：按分片切分后，每个分片都是对话记录的字面子串。

    分片口径（而非整串口径）是为容纳「多句枚举」这一合法形态（`# 子功能：A；B`）；
    但**任一分片不在原文即判捏造**——改写、拼接、概括一律被挡在门外。
    """
    s = "" if value is None else str(value).strip()
    if not s:
        return False
    frags = [f.strip() for f in _FRAG_SPLIT.split(s) if f.strip()]
    if not frags:
        return False
    return all(f in dialog for f in frags)


# 生效条件：span 经 `str(span).strip()`（None 记 ""）后须非空且作为连续子串出现在 dialog 中，否则返回 False。
def _span_grounded(dialog: str, span) -> bool:
    """引用 span 是否 grounded：必须是对话记录的**连续**字面子串。"""
    s = "" if span is None else str(span).strip()
    return bool(s) and s in dialog


# =============================================================================
# 候选来源：显式入参 / 外部 parser / 内生规则解析器
# =============================================================================

#: 内生规则解析器的线索词（确定性、可审计；不做语义推断）
_CUES = {
    "observation_position": ("位于", "在本地", "在服务", "在文件", "在系统",
                             "端上", "本地", "文件系统", "服务器"),
    "observation_tool": ("使用", "采用", "通过", "调用", "借助", "依托", "方法"),
    "existence_constraint": ("仅", "只", "前提", "除非", "限于", "必须是", "应当"),
}
_NEG_CUES = ("不适用", "不处理", "除外", "例外", "排除")
_EXEC_CUES = ("先", "再", "然后", "依次", "步骤", "读", "调用", "执行")
_SUB_CUES = ("分", "包含", "由", "组成", "包括")
#: 验证基底线索词 → VERIFICATION_BASIS 枚举
_BASIS_CUES = (
    ("测试", "test"), ("实测", "test"), ("回放", "test"), ("断言", "test"),
    ("编译", "compiler"), ("测量", "measurement"), ("证明", "formal_proof"),
    ("统计", "data"), ("教材", "textbook"), ("公开知识", "public_kb"),
)

_SENT_SPLIT = re.compile(r"[。！？!?；;\n]+")
_TS_PAT = re.compile(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})")


# 生效条件：dialog 为假值时按 "" 处理，按模块级 _SENT_SPLIT 切分后 strip 并过滤空串，返回句子列表。
def _sentences(dialog: str) -> List[str]:
    return [s.strip() for s in _SENT_SPLIT.split(dialog or "") if s.strip()]


# 生效条件：对 sents 逐句判 `any(c in s for c in cues)`，命中即 append，命中后 `len(out) >= limit` 即 break——limit 为 0 或负数时首个命中项仍被 append 后立刻 break（多返 1 项）；cues 为空容器时 any 恒假、返回空列表。
def _pick_by_cues(sents: List[str], cues, limit: int = 1) -> List[str]:
    """按线索词命中挑句（命中即整句作为候选——整句天然是原文子串，不会捏造）。"""
    out: List[str] = []
    for s in sents:
        if any(c in s for c in cues):
            out.append(s)
            if len(out) >= limit:
                break
    return out


# 生效条件：类无 __init__ 形参，实例化即成立，类属性 name 恒为模块级常量 SRC_RULE，候选能力经 candidates(dialog, ctx=None) 以 dialog 为必需入参调用；
class RuleParser:
    """内生规则解析器：**诚实下界能力**，不是主路径。

    按线索词从对话记录整句摘取候选，产出天然 grounded（无幻觉可能），但覆盖率低：
    四槽不齐即 E020 编译失败——这正是「缺能力时不假装通过」的既有纪律
    （对齐 audit.py：未注入验证器恒 DEFER，绝不假装通过）。
    真正的抽取能力由外部经 `parser=` 注入（LLM 等），能力外置、认知图只留接口。
    """

    name = SRC_RULE

# 生效条件：sents（来自 _sentences(dialog)）非空时「功能名」取首句（超 30 字符截前 30）；pos/tool/cons 仅在 _pick_by_cues 用 _CUES 对应线索命中时写入对应槽；time_window 先按 _TS_PAT 在 dialog 中匹配，命中且 mktime 未抛 ValueError/OverflowError/OSError 才填 [当日0点, +86399]，否则回落 [nodefile.FULL_TIME_WINDOW_MIN, nodefile.FULL_TIME_WINDOW_MAX] 并标 synthetic="full_time_window"；「不适用条件/执行/子功能」按 _NEG_CUES/_EXEC_CUES/_SUB_CUES 命中首句写入；「验证方式」取 _BASIS_CUES 中首个出现在 dialog 中的线索。
    def candidates(self, dialog: str, ctx: Optional[dict] = None) -> Dict[str, Any]:
        sents = _sentences(dialog)
        out: Dict[str, Any] = {"marks": {}, "slots": {}}

        if sents:
            head = sents[0]
            name = head if len(head) <= 30 else head[:30]
            out["marks"]["功能名"] = {"value": name, "span": name}

        pos = _pick_by_cues(sents, _CUES["observation_position"])
        tool = _pick_by_cues(sents, _CUES["observation_tool"])
        cons = _pick_by_cues(sents, _CUES["existence_constraint"])
        if pos:
            out["slots"]["observation_position"] = {"value": pos[0], "span": pos[0]}
        if tool:
            out["slots"]["observation_tool"] = {"value": tool[0], "span": tool[0]}
        if cons:
            out["slots"]["existence_constraint"] = {"value": cons[0], "span": cons[0]}

        # 时间槽：含 ISO 日期 → 该日全天（UTC）；不含 → 全时窗。
        # 二者都是**合法声明**（nodefile 已定义全时窗语义），非占位；
        # basis 经 synthetic 标注，避免被误读为「已测得具体时刻」。
        m = _TS_PAT.search(dialog or "")
        if m:
            try:
                t = time.mktime((int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                 0, 0, 0, 0, 0, 0)) - time.timezone
                out["slots"]["time_window"] = {"value": [t, t + 86399], "span": m.group(0)}
            except (ValueError, OverflowError, OSError):
                pass
        if "time_window" not in out["slots"]:
            out["slots"]["time_window"] = {
                "value": [nodefile.FULL_TIME_WINDOW_MIN, nodefile.FULL_TIME_WINDOW_MAX],
                "span": "", "synthetic": "full_time_window"}

        for field_name, cues in (("不适用条件", _NEG_CUES), ("执行", _EXEC_CUES),
                                 ("子功能", _SUB_CUES)):
            hit = _pick_by_cues(sents, cues)
            if hit:
                out["marks"][field_name] = {"value": hit[0], "span": hit[0]}
        for cue, basis in _BASIS_CUES:
            if cue in (dialog or ""):
                out["marks"]["验证方式"] = {"value": cue, "span": cue, "basis": basis}
                break
        return out


# 生效条件：对给定 parser、dialog、ctx，getattr(parser,"candidates",parser) 得到的 fn 被调用为 fn(dialog, ctx or {})，若该调用抛 Exception 或返回非 dict 则返回 {"marks": {}, "slots": {}}，否则返回该 dict 并 setdefault("marks",{}) 与 setdefault("slots",{}) 后的结果。
def _invoke_parser(parser, dialog: str, ctx: Optional[dict]) -> Dict[str, Any]:
    """调用外部/内生解析器，统一形态；异常不视作通过（返回空候选）。"""
    fn = getattr(parser, "candidates", parser)
    try:
        out = fn(dialog, ctx or {})
    except Exception:                       # noqa: BLE001 —— 解析器异常 = 无候选，不冒充成功
        return {"marks": {}, "slots": {}}
    if not isinstance(out, dict):
        return {"marks": {}, "slots": {}}
    out.setdefault("marks", {})
    out.setdefault("slots", {})
    return out


# =============================================================================
# 核心：compile_dialog（对话记录 → 六要素候选；只编译，不入库）
# =============================================================================

# 生效条件：dialog 空记 E001、node_id 空记 E002、actor 空记 E003，且 cg 转换后非 None 而 node_id 非空时该节点不存在再记 E002，存在任一 errors 即以 verdict{passed:False, reason:errors[0], authority:VERIFICATION_UNIT} 提前返回 res；否则按「marks/slots 任一为非空 dict → SRC_EXPLICIT；二者皆空且 parser 为 None → SRC_RULE（附下界告警）；二者皆空且 parser 非 None → SRC_PARSER」收集候选，四槽逐个校验（key 不在 cand_slots 即跳过；time_window 非长度 2 的 list/tuple 记 E021；其余槽空值/占位记 E021；仅当非「src_kind==SRC_EXPLICIT 且 strict_spans=False」豁免时，值非 dialog 子串记 E011、span 非空而定位失败记 E010），clean_slots 缺必需槽或 condition_space_text 为空记 E020；五要素按同样规则过滤后入 res.lines（生效条件行只由四槽 env_text 合成），验证基底按「候选 basis → 验证方式命中 _BASIS_CUES → 默认 other 并附告警」取值、不在 nodefile.VERIFICATION_BASIS 中记 E030；最终 res.success 与 verdict.passed 同取「无 errors」，verdict 恒带 requires_attestation=True，通过时再按 nodefile.CCG_REQUIRED 缺失项补 warning；
def compile_dialog(dialog: str, node_id: str, actor: str, *,
                   marks: Optional[Dict[str, Any]] = None,
                   slots: Optional[Dict[str, Any]] = None,
                   parser: Any = None,
                   strict_spans: bool = True,
                   cg: Any = None) -> CompileResult:
    """按五环编译：前端契约检查 → 候选 → 名实门 → 四槽合成 → 生成六行 → 终裁。

    入参优先级：显式 `marks`/`slots` > 外部 `parser=` > 内生 `RuleParser`。
    显式入参在 `strict_spans=True`（默认）时**同样**过名实门——人要写条件，
    也须拿得出对话原文依据；确需写入对话之外的声明时显式传 `strict_spans=False`，
    该豁免计入 warnings 与留痕（可审计，不静默）。

    Args:
        dialog: 对话记录原文（编译源）
        node_id: 目标节点 id
        actor: 编译执行者标识（供 attest 的 E041 比对，必填）
        marks: 显式五要素（功能名/子功能/执行/验证方式/不适用条件）
        slots: 显式 condition_space 四槽
        parser: 外部候选生成器（对象含 candidates(dialog, ctx)，或直接可调用）
        strict_spans: 显式入参是否也过名实门（默认 True）
        cg: 可选 cg 实例/root——提供时校验节点存在性
    """
    res = CompileResult(node_id=str(node_id or "").strip(),
                        actor=str(actor or "").strip())

    # ---- 第 0 环：前端契约检查（缺参即编译错误，裁定 B） ----
    if not (dialog or "").strip():
        res.err("E001")
    if not res.node_id:
        res.err("E002")
    if not res.actor:
        res.err("E003")
    _cg = _as_cg(cg)
    if _cg is not None and res.node_id:
        if not ((_cg.index.get("nodes") or {}).get(res.node_id)):
            res.err("E002", "节点不存在：" + res.node_id)
    if res.errors:
        res.verdict = {"passed": False, "reason": res.errors[0],
                       "authority": "VERIFICATION_UNIT"}
        return res

    src = str(dialog)
    ctx = {"cg": _cg, "actor": res.actor, "node_id": res.node_id}

    # ---- 第 1 环：收集候选（显式 > 外部 parser > 内生 rule） ----
    cand_marks: Dict[str, Any] = {}
    cand_slots: Dict[str, Any] = {}
    if marks or slots:
        src_kind = SRC_EXPLICIT
        for k, v in (slots or {}).items():
            cand_slots[k] = v if isinstance(v, dict) else {"value": v}
        for k, v in (marks or {}).items():
            cand_marks[k] = v if isinstance(v, dict) else {"value": v}
    else:
        if parser is None:
            src_kind = SRC_RULE
            res.warnings.append(
                "未注入外部解析器（parser=）且无显式入参，退回内生规则解析器（下界能力）；"
                "四槽不齐将按 E020 编译失败——缺能力时不假装通过。")
        else:
            src_kind = SRC_PARSER
            res.warnings.append(
                "外部解析器产物已过名实门（E010/E011）：任一值非对话记录字面子串即编译失败。")
        got = _invoke_parser(parser if parser is not None else RuleParser(), src, ctx)
        cand_marks = dict(got.get("marks") or {})
        cand_slots = dict(got.get("slots") or {})

    # 显式入参在 strict_spans=True 时同样过门；豁免须显式声明且留痕
    exempt = (src_kind == SRC_EXPLICIT and not strict_spans)
    if exempt:
        res.warnings.append(
            "strict_spans=False：显式入参豁免名实门，含未经对话原文支撑的声明（已留痕）。")

# 生效条件：item 为 dict 时返回 (item.get("value"), item.get("span"), item.get("basis"), item.get("synthetic"))（各键缺失即回落 None）；item 非 dict 时返回 (item, None, None, None)。
    def _field(item):
        """候选项 → (value, span, basis, synthetic)；容忍裸值与 dict 两种形态。"""
        if isinstance(item, dict):
            return (item.get("value"), item.get("span"),
                    item.get("basis"), item.get("synthetic"))
        return (item, None, None, None)

    # ---- 第 2 环：四槽校验 + 生效条件合成（唯一入口 nodefile.condition_space_text） ----
    clean_slots: Dict[str, Any] = {}
    for key, _label in nodefile.CONDITION_SLOTS:
        if key not in cand_slots:
            continue
        value, span, _basis, synthetic = _field(cand_slots[key])
        if key == "time_window":
            # 全时窗哨兵是合法声明；其余须为 [lo, hi] 数值对
            if not (isinstance(value, (list, tuple)) and len(value) == 2):
                res.err("E021", "槽 time_window 非 [lo, hi]：" + repr(value))
                continue
        else:
            if nodefile.is_placeholder_text(value):
                res.err("E021", "槽 " + key + " 空值或待填充占位：" + repr(value))
                continue
            if not exempt and not _value_grounded(src, value):
                res.err("E011", "槽 " + key + " 值非原文子串：" + repr(value))
                res.ungrounded.append({"field": "condition_space." + key,
                                       "span": str(span), "value": str(value)})
                continue
            if not exempt and span and not _span_grounded(src, span):
                res.err("E010", "槽 " + key + " 引用定位失败：" + repr(span))
                res.ungrounded.append({"field": "condition_space." + key,
                                       "span": str(span), "value": str(value)})
                continue
        clean_slots[key] = value
        span_list = res.spans.setdefault("condition_space." + key, [])
        if span:
            span_list.append(str(span))
        if synthetic:
            res.sources["condition_space." + key] = synthetic

    missing = nodefile.condition_space_missing(clean_slots)
    env_text = nodefile.condition_space_text(clean_slots)
    if missing or not env_text:
        res.err("E020", "缺槽 " + ",".join(missing or list(nodefile.CONDITION_SLOTS_REQUIRED)))
    res.slots = clean_slots

    # ---- 第 3 环：五要素过名实门 ----
    clean_marks: Dict[str, str] = {}
    basis_from_cand = None
    for field_name in _CAND_MARKS:
        if field_name not in cand_marks:
            continue
        value, span, basis, _synthetic = _field(cand_marks[field_name])
        if nodefile.is_placeholder_text(value):
            res.err("E021", "要素 " + field_name + " 空值或待填充占位：" + repr(value))
            continue
        if not exempt:
            if not _value_grounded(src, value):
                res.err("E011", "要素 " + field_name + " 值非原文子串：" + repr(value))
                res.ungrounded.append({"field": field_name, "span": str(span),
                                       "value": str(value)})
                continue
            if span and not _span_grounded(src, span):
                res.err("E010", "要素 " + field_name + " 引用定位失败：" + repr(span))
                res.ungrounded.append({"field": field_name, "span": str(span),
                                       "value": str(value)})
                continue
        clean_marks[field_name] = str(value).strip()
        res.sources[field_name] = src_kind
        span_list = res.spans.setdefault(field_name, [])
        if span:
            span_list.append(str(span))
        if field_name == "验证方式" and basis:
            basis_from_cand = basis
    res.sources["_src_kind"] = src_kind

    # ---- 第 4 环：验证基底（显式 basis > 文本线索词 > other） ----
    basis_val = basis_from_cand
    if basis_val is None and clean_marks.get("验证方式"):
        for cue, enum_val in _BASIS_CUES:
            if cue in clean_marks["验证方式"]:
                basis_val = enum_val
                break
    if basis_val is None:
        basis_val = "other"
        res.warnings.append("未声明验证基底，落默认 other（不得据以宣称已实测）。")
    if basis_val not in nodefile.VERIFICATION_BASIS:
        res.err("E030", repr(basis_val))
    res.sources["verification_basis"] = basis_val

    # ---- 第 5 环：生成六行（生效条件**只能**由四槽合成，无第二通路） ----
    lines: Dict[str, str] = {}
    if clean_marks.get("功能名"):
        lines["功能名"] = clean_marks["功能名"]
    if env_text:
        lines["生效条件"] = env_text
    for k in ("子功能", "执行", "验证方式", "不适用条件"):
        if clean_marks.get(k):
            lines[k] = clean_marks[k]
    res.lines = lines

    # ---- 第 6 环：验证单元终裁（编译器自证部分；签章由 attest 独立完成） ----
    solid = not res.errors
    res.verdict = {
        "passed": solid,
        "reason": ("候选可提交外部验证：六要素齐备且全部 grounded" if solid
                   else (res.errors[0] if res.errors else "未知")),
        "authority": "VERIFICATION_UNIT",
        "requires_attestation": True,   # 裁定 A：编译通过 ≠ 可写入，须外部签章
    }
    if solid:
        absent = [m for m in nodefile.CCG_REQUIRED if m not in lines]
        if absent:
            res.warnings.append("六要素尚缺：" + ",".join(absent) + "（link 前须补）")
    res.success = solid
    return res


# =============================================================================
# attest：认知图**外**的验证方签章（裁定 A 的落点）
# =============================================================================

# 生效条件：依次判 strip 后的 node_id 为空→E002；verifier 为空→E003；verifier==compiled_by→E041；state（verdict.strip()）不在模块级 STATES→非法裁决；state 非 ACCEPT→E042；全部通过才 res.ok=True；随后恒算 token=_sha(...)，仅当 ledger 为真且 _as_cg(cg) 非 None 时追加一条 ccgc_attest 审计 jsonl。
def attest(node_id: str, verdict: str, verifier: str, compiled_by: str, *,
           slot_corrections: Optional[Dict[str, Any]] = None,
           evidence: str = "", cg: Any = None, ledger: bool = True) -> AttestResult:
    """验证方签章。**验证方必须是编译方之外的一方**（子代理 / 设计者 / 用户）。

    E041 机械拒绝 `verifier == compiled_by`——LLM 不得自己验证自己。
    这是结构性保证：不依赖 prompt 自觉，也不依赖验证方「愿意」自证。
    DEFER 不构成签章（未定 = 未通过）。
    """
    res = AttestResult(node_id=str(node_id or "").strip(),
                       verifier=str(verifier or "").strip(),
                       compiled_by=str(compiled_by or "").strip(),
                       state=str(verdict or "").strip(),
                       evidence=str(evidence or ""),
                       slot_corrections=dict(slot_corrections or {}),
                       ts=time.time())
    if not res.node_id:
        res.error = "E002 " + E_CODES["E002"]
    elif not res.verifier:
        res.error = "E003 缺少验证方标识（verifier）"
    elif res.verifier == res.compiled_by:
        res.error = "E041 " + E_CODES["E041"] + "（verifier=" + res.verifier + "）"
    elif res.state not in STATES:
        res.error = ("非法裁决：" + repr(res.state) + "（可选 " + ",".join(STATES) + "）")
    elif res.state != ACCEPT:
        res.error = "E042 " + E_CODES["E042"] + "（state=" + res.state + "）"
    else:
        res.ok = True
    res.token = _sha("|".join([res.node_id, res.verifier, res.state,
                               str(res.ts), res.evidence]))
    if ledger:
        _cg = _as_cg(cg)
        if _cg is not None:
            _append_jsonl(_log_path(_cg), {
                "action": "ccgc_attest", "ts": res.ts, "node": res.node_id,
                "verifier": res.verifier, "compiled_by": res.compiled_by,
                "state": res.state, "ok": res.ok, "token": res.token,
                "evidence": res.evidence,
                "slot_corrections": res.slot_corrections, "error": res.error})
    return res


# =============================================================================
# link：签章通过才写入（缺签章恒不写入）
# =============================================================================

# 生效条件：依次判 compiled.success 为假→返回带错误；attestation 为 None→E040；attestation.node_id 不等于 compiled.node_id 的取值→目标不一致拒绝；attestation.verifier 为真值且 == `(actor or compiled.actor)`→E041；attestation.ok 为假→E042；_as_cg(cg) 为 None→E002；节点不在 cg.index 的 nodes 中→E002；apply 为假→ok=True 的 dry-run 返回；否则 apply 为真时写入（fm 为 None 或 content 加密→E004），basis 为假值则回落 compiled.sources.get("verification_basis") 或 "other"，成功后 out.written=len(compiled.lines)。
def _check_deps(_cg, node_id: str) -> List[str]:
    """依赖声明硬闸门 → 错误列表（E050 / E051）。**读面失败不误杀**（返回空即放行）。

    契约口径：CCG「子功能」行的契约角色是**依赖 dependency**（nodefile 术语真源），
    但该槽同时承载**自述子功能**（描述本单元内部构成）——判据以 `@<节点 id>` 显式
    引用为界（`nodefile.declares_dependency`，收窄裁定 b）：**显式声称依赖**才要求在
    `depends_on` 给出可解析目标——否则「依赖」只剩散文，被依赖单元一旦变动，下游
    无处可传（失效传播从源头断链）。自然语言自述不算声明（依赖不是必填元数据）。
    二者齐全时目标必须真实存在：悬空依赖 = 声称依赖一个并不存在的地基。
    """
    errs: List[str] = []
    try:
        node = _cg.get(node_id)
    except Exception:                       # noqa: BLE001 —— 读面异常按「无声明」放行
        return errs
    if not node:
        return errs
    from . import trust as _trust
    fm = node.get("frontmatter") or {}
    deps = _trust.as_deps(fm.get(nodefile.DEPENDS_ON_FIELD))
    if nodefile.declares_dependency(node.get("content") or "") and not deps:
        errs.append("E050 " + E_CODES["E050"])
    known = set((getattr(_cg, "index", None) or {}).get("nodes") or {})
    missing = [d for d in deps if d not in known]
    if missing:
        errs.append("E051 " + E_CODES["E051"] + "：" + ",".join(missing[:5]))
    return errs


# 生效条件：依次判 compiled.success 为假→返回带错误；attestation 为 None→E040；attestation.node_id 不等于 compiled.node_id 的取值→目标不一致拒绝；attestation.verifier 为真值且 == `(actor or compiled.actor)`→E041；attestation.ok 为假→E042；_as_cg(cg) 为 None→E002；节点不在 cg.index 的 nodes 中→E002；依赖声明闸门（E050/E051）不通过→拒绝写入；apply 为假→ok=True 的 dry-run 返回；否则 apply 为真时写入（fm 为 None 或 content 加密→E004），basis 为假值则回落 compiled.sources.get("verification_basis") 或 "other"，成功后 out.written=len(compiled.lines)。
def link(compiled: CompileResult, attestation: Optional[AttestResult], *,
         cg: Any = None, apply: bool = False, actor: str = "",
         basis: str = "") -> LinkResult:
    """把编译产物写入节点。**准入条件 = 有效签章**（裁定 A）。

    E040 无签章 / E041 自证 / E042 未通过 —— 任一命中即拒绝写入，
    对齐 audit.py「缺能力返回 DEFER，绝不假装通过」。
    """
    node_id = getattr(compiled, "node_id", "") or ""
    out = LinkResult(node_id=node_id, dry_run=not apply,
                     entry_id=_sha("ccgc|" + node_id + "|" + time.strftime("%Y%m%d%H%M%S")))
    if not compiled.success:
        out.errors.append("编译未通过，拒绝写入：" +
                          (compiled.errors[0] if compiled.errors else "未知"))
        return out
    if attestation is None:
        out.errors.append("E040 " + E_CODES["E040"])
        return out
    if attestation.node_id != node_id:
        out.errors.append("签章与产物目标不一致：" + attestation.node_id + " != " + node_id)
        return out
    if attestation.verifier and attestation.verifier == (actor or compiled.actor):
        out.errors.append("E041 " + E_CODES["E041"])
        return out
    if not attestation.ok:
        out.errors.append("E042 " + E_CODES["E042"] +
                          (("（" + attestation.error + "）") if attestation.error else ""))
        return out

    _cg = _as_cg(cg)
    if _cg is None:
        out.errors.append("E002 " + E_CODES["E002"] + "（未提供 cg，无法写入）")
        return out
    entry = (_cg.index.get("nodes") or {}).get(node_id)
    if not entry:
        out.errors.append("E002 节点不存在：" + node_id)
        return out
    _dep_errs = _check_deps(_cg, node_id)
    if _dep_errs:
        out.errors.extend(_dep_errs)
        return out
    if not apply:
        out.ok = True
        out.warnings.append("dry-run（apply=False）：未写入；签章 token=" + attestation.token)
        return out

    from . import crypto
    fm, content = _cg._read(entry)
    if fm is None or crypto.is_encrypted(content):
        out.errors.append("E004 " + E_CODES["E004"])
        return out

    before = {"生效条件": (fm.get("state_attributes") or {}).get("comment", {}).get("生效条件")
              if isinstance((fm.get("state_attributes") or {}).get("comment"), dict) else None}
    new_content = content
    for field_name, value in compiled.lines.items():
        new_content = _upsert_ccg_line(new_content, field_name, value)

    fm["condition_space"] = compiled.slots
    fm["verification_basis"] = basis or compiled.sources.get("verification_basis") or "other"
    if compiled.lines.get("不适用条件"):
        fm["non_applicable_conditions"] = [
            s.strip() for s in re.split(r"[；;]", compiled.lines["不适用条件"]) if s.strip()]
    st = fm.get("state_attributes")
    if not isinstance(st, dict):
        st = {}
        fm["state_attributes"] = st
    comment = st.get("comment")
    if not isinstance(comment, dict):
        comment = {}
        st["comment"] = comment
    if compiled.lines.get("生效条件"):
        comment["生效条件"] = compiled.lines["生效条件"]

    _cg._write_node(node_id, os.path.join(_cg.root, entry["path"]), fm,
                    new_content, durable=True)
    _append_jsonl(_log_path(_cg), {
        "action": "ccgc_link", "ts": time.time(), "node": node_id,
        "actor": actor or compiled.actor, "verifier": attestation.verifier,
        "token": attestation.token, "entry_id": out.entry_id,
        "fields": {k: {"after": v, "source": compiled.sources.get(k, "")}
                   for k, v in compiled.lines.items()},
        "slots": compiled.slots, "before": before,
        "content_hash_after": nodefile.content_hash(new_content)})
    _cg.rebuild_index()
    out.ok = True
    out.written = len(compiled.lines)
    return out


# =============================================================================
# recalibrate：用后续验证修正生效条件（裁定 A 的闭环）
# =============================================================================

# 生效条件：node_id 空→E002；verifier 为真值且==compiled_by→E041；corrections 为假值（空 dict/None）→E043；corrections 含不在模块级 nodefile.CONDITION_SLOTS 的键→E043；_as_cg(cg) 为 None→E002；节点不在 cg.index 的 nodes 中→E002；fm 为 None 或内容加密→E004；旧槽合并 corrections 后 condition_space_text 为空→E020；apply 为假→ok=True 的 dry-run 返回；否则写入并按 1 计 written。
def recalibrate(node_id: str, corrections: Dict[str, Any], verifier: str,
                compiled_by: str, *, evidence: str = "", cg: Any = None,
                apply: bool = False) -> LinkResult:
    """用验证方给出的**四槽修正**重合成生效条件（唯一入口重算，可回滚）。

    E043：只允许修正 condition_space 四槽——生效条件行本身不是修正入口，
    否则会绕开「四槽 → 合成」的唯一通路，退回到手写条件的老问题。
    修正须由编译方**之外**的一方给出（E041）。
    """
    out = LinkResult(node_id=str(node_id or "").strip(), dry_run=not apply,
                     entry_id=_sha("ccgc_recal|" + str(node_id) + "|" + str(time.time())))
    if not out.node_id:
        out.errors.append("E002 " + E_CODES["E002"])
        return out
    if verifier and verifier == compiled_by:
        out.errors.append("E041 " + E_CODES["E041"])
        return out
    if not corrections:
        out.errors.append("E043 " + E_CODES["E043"] + "（未给出任何修正）")
        return out
    allowed = {k for k, _l in nodefile.CONDITION_SLOTS}
    bad = [k for k in corrections if k not in allowed]
    if bad:
        out.errors.append("E043 " + E_CODES["E043"] + "（非法键 " + ",".join(bad) + "）")
        return out

    _cg = _as_cg(cg)
    if _cg is None:
        out.errors.append("E002 " + E_CODES["E002"] + "（未提供 cg）")
        return out
    entry = (_cg.index.get("nodes") or {}).get(out.node_id)
    if not entry:
        out.errors.append("E002 节点不存在：" + out.node_id)
        return out

    from . import crypto
    fm, content = _cg._read(entry)
    if fm is None or crypto.is_encrypted(content):
        out.errors.append("E004 " + E_CODES["E004"])
        return out
    old_cs = dict(fm.get("condition_space") or {})
    new_cs = dict(old_cs)
    new_cs.update(corrections)
    new_text = nodefile.condition_space_text(new_cs)
    if not new_text:
        out.errors.append("E020 " + E_CODES["E020"] +
                          "（修正后仍缺 " + ",".join(nodefile.condition_space_missing(new_cs)) + "）")
        return out
    out.warnings.append("修正后生效条件：" + new_text)
    if not apply:
        out.ok = True
        return out

    new_content = _upsert_ccg_line(content, "生效条件", new_text)
    fm["condition_space"] = new_cs
    _cg._write_node(out.node_id, os.path.join(_cg.root, entry["path"]), fm,
                    new_content, durable=True)
    _append_jsonl(_log_path(_cg), {
        "action": "ccgc_recalibrate", "ts": time.time(), "node": out.node_id,
        "verifier": verifier, "compiled_by": compiled_by, "evidence": evidence,
        "entry_id": out.entry_id,
        "slots_before": old_cs, "slots_after": new_cs,
        "condition_before": nodefile.condition_space_text(old_cs),
        "condition_after": new_text})
    _cg.rebuild_index()
    out.ok = True
    out.written = 1
    return out


# =============================================================================
# pending：三段式在「跨调用」形态下的持久化（候选与签章绑定，防篡改）
# =============================================================================
#
# 为什么需要：compile / attest / link 在 MCP 面上是**三次独立调用**（签章必须由
# 认知图**外**的一方在别处完成），候选对象无法跨调用传递。若让调用方把候选 JSON
# 原样回传，改写「六行」不会被任何检查发现（签章 token 只覆盖 node/verifier/
# state/evidence，不含候选内容）。因此候选落盘到 `_ccgc_pending/`（LAYERS 之外、
# `.json` 后缀 → 索引双隐身的冷区），并对其内容取 hash；link 时校验 hash，
# 不一致即拒绝写入。
#
# 纪律：pending 是**暂存**不是存档——link 成功即删除；留痕在 _ccgc.jsonl。

PENDING_DIR = "_ccgc_pending"


# 生效条件：node_id 为 None 或空串时按 "" 处理，非 [0-9A-Za-z_.\-] 字符一律替换为 "-"，取前 80 个字符；结果为空串时返回 "unnamed"。
def _safe_name(node_id: str) -> str:
    """node_id → 文件名安全形态（分支节点形如 mem_x@br1，须剥掉非 [A-Za-z0-9_.-]）。"""
    return re.sub(r"[^0-9A-Za-z_.\-]", "-", str(node_id or ""))[:80] or "unnamed"


# 生效条件：_as_cg(cg) 的 root 属性为假值→返回 ""；否则返回 os.path.join(str(root), PENDING_DIR, _safe_name(node_id) + ".json")。
def pending_path(cg, node_id: str) -> str:
    _cg = _as_cg(cg)
    root = getattr(_cg, "root", None)
    if not root:
        return ""
    return os.path.join(str(root), PENDING_DIR, _safe_name(node_id) + ".json")


# 生效条件：lines、slots 为假值时按 {} 处理，返回 `_sha(json.dumps({"lines":..., "slots":...}, ensure_ascii=False, sort_keys=True))`。
def _payload_hash(lines, slots) -> str:
    """候选内容摘要（六行 + 四槽，键序无关）——签章与产物的绑定依据。"""
    return _sha(json.dumps({"lines": lines or {}, "slots": slots or {}},
                           ensure_ascii=False, sort_keys=True))


# 生效条件：_as_cg(cg) 为 None→返回 {'ok': False, 'error': '未提供 cg'}；pending_path 为空→返回 {'ok': False, 'error': '无法定位 pending 目录'}；否则写 json（OSError 时返回 ok=False 且带 path 与异常名），成功返回 {'ok': True, 'path': p, 'hash': rec['hash']}，其中 attest 按 `attestation is not None` 决定是否落盘。
def save_pending(cg, compiled: CompileResult,
                 attestation: Optional[AttestResult] = None) -> dict:
    """候选（+ 可选签章）落 pending；返回 {ok, path, hash}。"""
    _cg = _as_cg(cg)
    if _cg is None:
        return {"ok": False, "error": "未提供 cg"}
    p = pending_path(_cg, compiled.node_id)
    if not p:
        return {"ok": False, "error": "无法定位 pending 目录"}
    rec = {"node_id": compiled.node_id, "actor": compiled.actor, "ts": time.time(),
           "hash": _payload_hash(compiled.lines, compiled.slots),
           "compiled": asdict(compiled),
           "attest": asdict(attestation) if attestation is not None else None}
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
    except OSError as exc:
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc), "path": p}
    return {"ok": True, "path": p, "hash": rec["hash"]}


# 生效条件：_as_cg(cg) 为 None→error='未提供 cg'；pending_path 为空或 os.path.isfile(p) 为假→error=未找到 pending；open/json.load 抛 OSError 或 ValueError→error=pending 不可读；否则按 dataclasses.fields 过滤重建 CompileResult 与（rec['attest'] 为真值时的）AttestResult，hash_ok = `rec.get("hash") == _payload_hash(c.lines, c.slots)`，ok=True。
def load_pending(cg, node_id: str) -> dict:
    """读回候选与签章，并校验 hash（内容被改即 hash_ok=False，调用方须拒绝写入）。"""
    _cg = _as_cg(cg)
    out = {"ok": False, "compiled": None, "attest": None, "hash_ok": False,
           "path": "", "error": ""}
    if _cg is None:
        out["error"] = "未提供 cg"
        return out
    p = pending_path(_cg, node_id)
    out["path"] = p
    if not p or not os.path.isfile(p):
        out["error"] = "未找到待写入的编译产物（pending）：" + str(node_id)
        return out
    try:
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError) as exc:
        out["error"] = "pending 不可读：%s" % type(exc).__name__
        return out
    cfields = {f.name for f in dataclasses.fields(CompileResult)}
    afields = {f.name for f in dataclasses.fields(AttestResult)}
    c = CompileResult(**{k: v for k, v in (rec.get("compiled") or {}).items()
                         if k in cfields})
    a = None
    if rec.get("attest"):
        a = AttestResult(**{k: v for k, v in rec["attest"].items() if k in afields})
    out.update({"compiled": c, "attest": a,
                "hash_ok": rec.get("hash") == _payload_hash(c.lines, c.slots)})
    out["ok"] = True
    return out


# 生效条件：pending_path(cg, node_id) 为空→返回 False；否则 os.remove 成功→True，抛 OSError→False。
def drop_pending(cg, node_id: str) -> bool:
    """删除 pending（link 成功后调用；失败静默——待办件不是事实，无需强保证）。"""
    p = pending_path(cg, node_id)
    if not p:
        return False
    try:
        os.remove(p)
        return True
    except OSError:
        return False


# 生效条件：load_pending(cg, node_id) 的 ok 为假→带其 error 返回 LinkResult；hash_ok 为假→以「hash 不符」错误返回；否则转调 link(got["compiled"], got.get("attest"), cg=cg, apply=apply, actor=actor, basis=basis) 并返回其结果，且仅当 res.ok 与 apply 同时为真时调用 drop_pending。
def link_pending(cg, node_id: str, *, apply: bool = False, actor: str = "",
                 basis: str = "") -> LinkResult:
    """从 pending 读回候选与签章后 link：hash 校验 → 签章准入 → 写入 → 清理 pending。"""
    out = LinkResult(node_id=str(node_id or "").strip(), dry_run=not apply)
    got = load_pending(cg, node_id)
    if not got.get("ok"):
        out.errors.append(got.get("error") or "pending 不可用")
        return out
    if not got.get("hash_ok"):
        out.errors.append("pending 产物与编译时不一致（hash 不符），拒绝写入——"
                          "候选落盘后不得被改写，请重新编译")
        return out
    res = link(got["compiled"], got.get("attest"), cg=cg, apply=apply,
               actor=actor, basis=basis)
    if res.ok and apply:
        drop_pending(cg, node_id)
    return res


__all__ = ["ACCEPT", "REJECT", "DEFER", "BLINDSPOT", "STATES", "CONTRACT_ROLES",
           "E_CODES", "CompileResult", "AttestResult", "LinkResult", "RuleParser",
           "compile_dialog", "attest", "link", "recalibrate",
           "PENDING_DIR", "pending_path", "save_pending", "load_pending",
           "drop_pending", "link_pending"]