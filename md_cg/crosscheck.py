# -*- coding: utf-8 -*-
"""批量核对（P34/P35）：工单 → 反思候选 → 白箱闸门 → 验证否决 → 来源执照 → 落库。

设计约束（与计划一致）：

* **不新增 MCP op**：本模块是「模块 + `_cli`」形态（同 `backfill.py`），子代理经
  `python -m md_cg.crosscheck …` 调用；令牌决定权限边界。
* **防自证**：反思单元（`reflect`）与验证单元（`verify`）必须为**不同执行者**；
  验证单元**只能否决、不能新增**候选（越界字段在白箱闸门直接丢弃）。
* **来源执照**：文科（`humanities`）只接受来源一致性档（`textbook`/`public_kb`）；
  理科（`science`）只接受可复现档（`compiler`/`test`/`measurement`/`formal_proof`/`data`）；
  赛道未定（`undetermined`）或无来源一律不写，保持 DEFER 并登记待补。
* **诚实边界**：占位空壳节点（`骨架锚点`/`内容待填充`）不进接线，转待填充工单；
  拿不出证据的节点绝不写 `verification_basis`。
* **留痕可回滚**：写入前记录 `_crosscheck.jsonl`，`rollback` 仅在「当前值 == 写入值」
  时撤销，否则计入 conflict 跳过。

`_cli` 之外的所有函数都是纯逻辑（无网络、无第三方依赖），便于离线回归。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import OrderedDict

from . import crypto, nodefile
from .backfill import (BASIS_ENUM_DEFAULT, BASIS_TEXT, INTERNAL_LAYERS,
                       SKIP_LAYERS, SKIP_TAGS, _as_cg, _as_text, _comment,
                       _ensure_comment, _entry_id, _readable_guard,
                       _remove_ccg_line, _sha, derive_fields)
from .consolidate import _has_ccg_line, _upsert_ccg_line
from .fsutil import append_jsonl, read_jsonl
from .mdcos import _ccg_field

# ---- 常量 ----------------------------------------------------------------

CROSSCHECK_LOG = "_crosscheck.jsonl"
CROSSCHECK_BATCH = "crosscheck"

REFLECT_UNIT = "reflect"
VERIFY_UNIT = "verify"

# 可写字段（本管线只动这一处，杜绝越界面）
WRITABLE_FIELDS = ("验证方式",)
FIELD_NORMALIZE = {
    "验证方式": "验证方式",
    "verification_basis": "验证方式",
    "验证": "验证方式",
    "verification": "验证方式",
}

# 赛道 → 来源执照策略
SOURCE_POLICY = {"science": "reproducible", "humanities": "consistency"}

# 学科关键词（赛道判定；两栖词不入表 → undetermined，宁缺勿猜）
SCIENCE_SUBJECT_HINTS = (
    "数学", "物理", "化学", "生物", "科学", "信息技术", "通用技术", "计算机",
)
HUMANITIES_SUBJECT_HINTS = (
    "语文", "历史", "政治", "道德与法治", "思想政治", "思想品德", "英语",
    "文学", "哲学", "艺术", "音乐", "美术",
)

# 基底枚举 → 可读标签（条件化表述引用）
BASIS_LABEL = {
    "compiler": "编译器/静态检查",
    "test": "单元测试",
    "measurement": "实测数据",
    "formal_proof": "形式化证明",
    "data": "数据统计",
    "textbook": "人教版教材",
    "public_kb": "公开知识库",
    "other": "人工评审",
}

CLAIM_FIELDS = ("功能名", "生效条件", "子功能", "执行")
B_CLAIM = "B_valuation"
A_CLAIM = "A_fact"

# B 型（评价性断言）标记词：只收「明显是价值判断/修饰」的表达，避免把事实误判。
VALUATION_MARKERS = (
    "结晶", "瑰宝", "杰作", "卓越", "杰出", "伟大", "不朽", "巅峰", "典范",
    "精华", "珍品", "璀璨", "辉煌", "丰碑", "博大精深", "源远流长",
    "不可估量", "无与伦比", "举足轻重", "首屈一指", "独树一帜", "别具一格",
    "最优秀", "极富", "令人叹为观止", "不可磨灭", "辉煌成就", "灿烂", "崇高",
    "非凡",
)
VALUATION_PATTERNS = (
    re.compile(r"被誉为|被称[之为]|堪称|不愧[为是]"),
    re.compile(r"是[^，。；\n]{0,24}的(结晶|瑰宝|杰作|典范|精华|骄傲|象征|丰碑)"),
)

CONDITION_MARK = "〔来源限定〕"


# ---- 赛道与来源执照 ------------------------------------------------------

# 生效条件：给定 fm，若显式 track/discipline_type 命中枚举则返回对应赛道；否则用相关元数据与正文 CCG 字段匹配提示词，返回 humanities/science/undetermined。
def classify_track(fm: dict, content: str = "") -> str:
    """判定节点赛道：`humanities` / `science` / `undetermined`。

    只看**已声明**的元数据（显式字段 > 学科标记），不扫正文散文，避免误判。
    """
    fm = fm or {}
    explicit = str(fm.get("track") or fm.get("discipline_type") or "").strip().lower()
    if explicit in ("humanities", "文科", "arts"):
        return "humanities"
    if explicit in ("science", "理科", "stem"):
        return "science"
    st = fm.get("state_attributes")
    name = _as_text(st.get("name")) if isinstance(st, dict) else ""
    parts = [
        name,
        _as_text(fm.get("title")),
        _as_text(fm.get("discipline")),
        _as_text(fm.get("subject")),
        " ".join(str(t) for t in (fm.get("tags") or [])),
        _ccg_field(content, "功能名"),
        _ccg_field(content, "执行"),
        _ccg_field(content, "子功能"),
    ]
    text = " ".join(p for p in parts if p)
    has_sci = any(k in text for k in SCIENCE_SUBJECT_HINTS)
    has_hum = any(k in text for k in HUMANITIES_SUBJECT_HINTS)
    if has_sci and not has_hum:
        return "science"
    if has_hum and not has_sci:
        return "humanities"
    return "undetermined"


# 生效条件：给定 track，返回 SOURCE_POLICY 中映射的策略名；未知 track 返回空串。
def source_policy(track: str) -> str:
    """赛道 → 来源策略名（空串表示不可判定，应 DEFER）。"""
    return SOURCE_POLICY.get(track or "", "")


# 生效条件：给定 track，若为 science 返回 REPRODUCIBLE_BASIS，若为 humanities 返回 CONSISTENCY_BASIS，否则返回 ()。
def allowed_basis(track: str) -> tuple:
    if track == "science":
        return tuple(nodefile.REPRODUCIBLE_BASIS)
    if track == "humanities":
        return tuple(nodefile.CONSISTENCY_BASIS)
    return ()


# 生效条件：给定 track 与 basis，当 basis 非空且其字符串形式属于 allowed_basis(track) 时返回 True，否则 False。
def basis_licensed(track: str, basis) -> bool:
    """来源执照：理科要可复现证据，文科要来源一致性；赛道未定一律不发放。"""
    return bool(basis) and str(basis) in allowed_basis(track)


# 生效条件：给定 field，返回 FIELD_NORMALIZE 映射值；未知字段返回空串。
def normalize_field(field) -> str:
    return FIELD_NORMALIZE.get(str(field or "").strip(), "")


# 生效条件：给定 v，若为 None 返回 []；否则将单值或列表转为去除空白后非空字符串的列表。
def _as_source(v) -> list:
    if v is None:
        return []
    items = list(v) if isinstance(v, (list, tuple)) else [v]
    return [str(x).strip() for x in items if str(x).strip()]


# ---- B 型识别与条件化改写 ------------------------------------------------

# 生效条件：给定 text，若含 VALUATION_MARKERS 或匹配 VALUATION_PATTERNS 则返回 B_CLAIM，否则 A_CLAIM。
def claim_type(text) -> str:
    """`A_fact`（事实性）或 `B_valuation`（评价性断言）。"""
    s = str(text or "")
    if not s.strip():
        return A_CLAIM
    if any(m in s for m in VALUATION_MARKERS):
        return B_CLAIM
    if any(p.search(s) for p in VALUATION_PATTERNS):
        return B_CLAIM
    return A_CLAIM


# 生效条件：给定 text，返回其去除首尾空白后是否以 CONDITION_MARK 开头。
def is_conditioned(text) -> bool:
    return str(text or "").strip().startswith(CONDITION_MARK)


# 生效条件：给定 text、label、source，若 text 非空且 label 非空且 source 解析后非空，则返回带 CONDITION_MARK 的来源限定表述；已条件化原样返回；否则 None。
def conditioned_claim(text, label, source):
    """把评价性断言改写为**带来源限定的条件表述**；缺来源/标签则返回 `None`（不写）。

    形态：`〔来源限定〕据<来源标签>（<来源>）的表述：<原文>`——
    原文完整保留（可追溯），前缀显式声明「这是某来源的表述」而非无条件事实。
    已条件化的文本原样返回（幂等）。
    """
    body = str(text or "").strip()
    if not body or not label:
        return None
    if is_conditioned(body):
        return body
    src = "；".join(_as_source(source))
    if not src:
        return None
    return f"{CONDITION_MARK}据{label}（{src}）的表述：{body}"


# 生效条件：给定 fm 与 content，提取 CCG 声明字段、comment 值与正文长句，返回断言列表，每项含 text/type/where/field。
def extract_claims(fm: dict, content: str) -> list:
    """提取可核对断言：CCG 声明字段 + comment 值 + 正文长句。

    每条：`{"text", "type", "where", "field"}`；`where` ∈ ccg/comment/body。
    占位标记不成为断言。
    """
    out, seen = [], set()

# 生效条件：仅当 str(text or "").strip() 得到的 s 长度 >= 4、s 不在 seen 中、且 nodefile.is_placeholder_text(s) 为假时，把 {text: s, type: claim_type(s), where, field} 追加进 out 并把 s 加入 seen，否则直接返回（field 默认 ""）。
    def _push(text, where, field=""):
        s = str(text or "").strip()
        if len(s) < 4 or s in seen or nodefile.is_placeholder_text(s):
            return
        seen.add(s)
        out.append({"text": s, "type": claim_type(s), "where": where,
                    "field": field})

    for f in CLAIM_FIELDS:
        v = _ccg_field(content, f)
        if v:
            _push(v, "ccg", f)
    c = _comment(fm)
    for f in CLAIM_FIELDS:
        v = c.get(f)
        if isinstance(v, list):
            for item in v:
                _push(item, "comment", f)
        elif v:
            _push(v, "comment", f)
    for line in (content or "").split("\n"):
        raw = line.strip()
        if not raw:
            continue
        body = raw.lstrip("#").strip()
        if body.split("：", 1)[0].strip() in nodefile.CCG_MARKS:
            continue            # 声明行已按 CCG 字段处理，不重复断言
        for sent in re.split(r"[。！？]", body):
            s = sent.strip()
            if len(s) >= 8 and not s.startswith(CONDITION_MARK):
                _push(s, "body", "")
    return out


# 生效条件：给定 fm、content、claim、new_text，按 claim.where 定位并在唯一匹配时替换断言返回 (content, True)，否则返回 (content, False)。
def _rewrite_claim(fm: dict, content: str, claim: dict, new_text: str):
    """节点内定位并替换一条断言 → `(content, ok)`；定位不唯一则 fail-closed 不动。"""
    where, field = claim.get("where"), claim.get("field")
    before = str(claim.get("text") or "")
    if where == "ccg" and field:
        if _ccg_field(content, field).strip() == before.strip():
            return _upsert_ccg_line(content, field, new_text), True
        return content, False
    if where == "comment" and field:
        c = _comment(fm)
        v = c.get(field)
        if isinstance(v, list):
            if before in v:
                c[field] = [new_text if x == before else x for x in v]
                return content, True
            return content, False
        if str(v or "").strip() == before.strip():
            c[field] = new_text
            return content, True
        return content, False
    if where == "body":
        if before and content.count(before) == 1:
            return content.replace(before, new_text), True
        return content, False
    return content, False


# ---- 工单 ----------------------------------------------------------------

# 生效条件：给定 fm 与 content，返回缺失项列表：verification_basis 无效则加入该名，正文无 "# 验证方式" 行则加入该名。
def _need(fm: dict, content: str) -> list:
    need = []
    if not nodefile.verification_basis_valid(fm):
        need.append("verification_basis")
    if not _has_ccg_line(content, "验证方式"):
        need.append("验证方式")
    return need


# 生效条件：给定 nid、e、fm、content，返回含 id、layer、track、claims、need、source_policy 的工单行字典。
def _worklist_row(nid: str, e: dict, fm: dict, content: str) -> dict:
    track = classify_track(fm, content)
    return {
        "id": nid,
        "layer": e.get("layer"),
        "track": track,
        "claims": extract_claims(fm, content),
        "need": _need(fm, content),
        "source_policy": source_policy(track),
    }


# 生效条件：给定 fm 与 content，若正文或 comment 中声明的执行字段为占位文本则返回 True；未声明执行时以正文整体占位判定。
def _is_placeholder_shell(fm: dict, content: str) -> bool:
    """空壳判定：核心可执行内容未被填充 → 禁止接线（不得把「待填充」固化成事实）。

    口径（宁漏判不误判）：
      1. 已声明 `执行`（正文 `# 执行：` 行优先，其次 `state_attributes.comment.执行`）
         且值为占位标记 → 空壳；
      2. 未声明 `执行` 时，以正文整体是否为空/占位标记为准——无 comment 但正文写实的
         `kp_archaeo_*` 类节点因此不被误判为空壳。
    """
    decl = _ccg_field(content, "执行") or _as_text(_comment(fm).get("执行"))
    if decl:
        return nodefile.is_placeholder_text(decl)
    return nodefile.is_placeholder_text(content)


# 生效条件：给定 cg，逐节点按 layer/ids/prefix 过滤后产出状态为 skip（internal/denied/locked/derived/present/placeholder/unreadable 等）或 row 的扫描结果。
def _scan(cg, layer=None, ids=None, prefix=None):
    """逐节点产出扫描结果：`{"status", "reason"?, "id", "row"?}`。

    `prefix`：只纳入 id 以该前缀开头的节点（真实库以 `kp_` 收窄到用户知识节点，
    避免 `node_`/`note_`/`imgpart_` 等派生记忆混入工单）；**不计数**，与 `layer` 同理。
    """
    want = set(ids) if ids else None
    for nid, e in list((cg.index.get("nodes") or {}).items()):
        if want is not None and nid not in want:
            continue
        if prefix and not str(nid).startswith(prefix):
            continue
        if layer and e.get("layer") != layer:
            continue
        if e.get("layer") in INTERNAL_LAYERS:
            yield {"status": "skip", "reason": "internal", "id": nid}
            continue
        if not _readable_guard(cg, e):
            yield {"status": "skip", "reason": "denied", "id": nid}
            continue
        fm, content = cg._read(e)
        if fm is None:
            yield {"status": "skip", "reason": "unreadable", "id": nid}
            continue
        if crypto.is_encrypted(content):
            yield {"status": "skip", "reason": "locked", "id": nid}
            continue
        if e.get("layer") in SKIP_LAYERS or any(
                t in SKIP_TAGS for t in (fm.get("tags") or [])):
            yield {"status": "skip", "reason": "derived", "id": nid}
            continue
        need = _need(fm, content)
        if not need:                                    # 已齐备
            yield {"status": "skip", "reason": "present", "id": nid}
            continue
        ph = []
        der = derive_fields(fm, content, placeholder_out=ph)
        if _is_placeholder_shell(fm, content):          # 空壳：转待填充工单
            yield {"status": "skip", "reason": "placeholder", "id": nid,
                   "placeholder_fields": ph}
            continue
        yield {"status": "row", "id": nid,
               "row": _worklist_row(nid, e, fm, content)}


_SKIP_KEY = {"locked": "skipped_locked", "derived": "skipped_derived",
             "present": "skipped_present", "denied": "skipped_denied",
             "unreadable": "skipped_unreadable", "internal": "skipped_internal"}


# 生效条件：给定 x（路径或 MdCGOS），只读扫描并生成缺 verification_basis 或 "# 验证方式" 的节点工单，返回统计 rep。
def build_worklist(x, layer=None, limit=None, ids=None, prefix=None) -> dict:
    """生成核对工单（只读）：缺 `verification_basis`/`验证方式` 的节点入列。

    `prefix`：按 id 前缀收窄范围（真实库用 `kp_`，与计划交付边界一致）；
    内部 `anchor`/`self` 层一律出局（计入 `skipped_internal`）。
    """
    cg = _as_cg(x)
    rep = {"root": cg.root, "dry_run": True, "action": "crosscheck_worklist",
           "prefix": prefix, "nodes_scanned": 0, "skipped_locked": 0,
           "skipped_derived": 0, "skipped_internal": 0, "skipped_present": 0,
           "skipped_denied": 0, "skipped_placeholder": 0,
           "skipped_unreadable": 0, "placeholder_ids": [], "undetermined": 0,
           "targeted": 0, "items": []}
    for scan in _scan(cg, layer=layer, ids=ids, prefix=prefix):
        rep["nodes_scanned"] += 1
        if scan["status"] == "skip":
            reason = scan["reason"]
            if reason == "placeholder":
                rep["skipped_placeholder"] += 1
                rep["placeholder_ids"].append(scan["id"])
            else:
                key = _SKIP_KEY.get(reason)
                if key:
                    rep[key] += 1
            continue
        row = scan["row"]
        if row["track"] == "undetermined":
            rep["undetermined"] += 1
        rep["targeted"] += 1
        if limit is None or len(rep["items"]) < limit:
            rep["items"].append(row)
    rep["planned_ids"] = [r["id"] for r in rep["items"]]
    return rep


# ---- 子代理接口（提示词 + 解析） -----------------------------------------

_REFLECT_TEMPLATE = """你是认知图节点的**反思单元**（reflect）。为节点补齐「验证方式」与其验证基底。
赛道：{track}；来源策略：{policy}；待补字段：{need}
节点标题：{title}
已声明断言：
{claims}
正文：
{body}

只输出 JSON 数组，元素形如：
{{"field":"验证方式","value":"<一句可核对的验证方式声明>","basis":"<基底枚举>","source":["<教材版本+章节 或 公开知识库条目地址>"],"verdict":"accept|defer","reason":"<理由>"}}
硬约束：
1. 文科（humanities）basis 只能是 textbook / public_kb；
2. 理科（science）basis 只能是 compiler / test / measurement / formal_proof / data；
3. 来源必须可追溯（教材名称+章节，或公开知识库条目地址）；拿不出来就把 verdict 置 defer、source 留空；
4. 只能补 field=验证方式，禁止新增其它字段。"""

_VERIFY_TEMPLATE = """你是独立**验证单元**（verify）。对下列候选逐条复核：来源是否真实可追溯、基底是否与赛道相容。
赛道：{track}；来源策略：{policy}
候选（JSON）：
{candidates}

只输出 JSON 数组，元素形如：
{{"field":"验证方式","value":"<原样回填候选 value>","verdict":"accept|drop|defer","reason":"<理由>"}}
硬约束：你只能否决（drop）或存疑（defer），**不得新增候选、不得改写 value**。"""


# 生效条件：给定 row、fm、content，用 row 的 track/source_policy/need/claims 与 fm 标题、content 前 1200 字符填充反思模板并返回字符串。
def reflect_prompt(row: dict, fm: dict, content: str) -> str:
    claims = "\n".join(f"- [{c['type']}] {c['text']}" for c in (row.get("claims") or []))
    return _REFLECT_TEMPLATE.format(
        track=row.get("track"), policy=row.get("source_policy") or "（未定）",
        need="、".join(row.get("need") or []),
        title=_as_text(fm.get("title")) or row.get("id"),
        claims=claims or "（无）",
        body=(content or "")[:1200])


# 生效条件：给定 row 与 rows，把候选字段、值、依据、来源序列化为 JSON 并填充验证模板返回字符串。
def verify_prompt(row: dict, rows: list) -> str:
    cands = [{"field": r.get("field"), "value": r.get("value"),
              "basis": r.get("basis"), "source": r.get("source")} for r in rows]
    return _VERIFY_TEMPLATE.format(
        track=row.get("track"), policy=row.get("source_policy") or "（未定）",
        candidates=json.dumps(cands, ensure_ascii=False))


# 生效条件：raw 经 str(raw or "") 得 s 后，want_list 为真时先试 s 首个 "[" 至末个 "]"、再试首个 "{" 至末个 "}"（want_list 假值时只试花括号），区间可被 json.loads 解析且结果为 list 时原样返回该 list；结果为 dict 时按 rows/items/verdicts/candidates/data 顺序取首个 obj.get(key) 为 list 的 obj[key]，都不满足则返回 [obj]，非 list/dict 或区间缺失、解析抛 ValueError 时继续下一组括号，全部落空（含 raw 为假值使 s 为空串）返回 []。
def _extract_json(raw, want_list=True):
    """从模型输出里抽取 JSON（容忍代码围栏与前后废话）。"""
    s = str(raw or "")
    pairs = ([("[", "]")] if want_list else []) + [("{", "}")]
    for op, cl in pairs:
        i, j = s.find(op), s.rfind(cl)
        if i < 0 or j <= i:
            continue
        try:
            obj = json.loads(s[i:j + 1])
        except ValueError:
            continue
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            for key in ("rows", "items", "verdicts", "candidates", "data"):
                if isinstance(obj.get(key), list):
                    return obj[key]
            return [obj]
    return []


# 生效条件：给定 item，若为 dict 则规范化 field/value/basis/source/verdict/reason 后返回字典，否则返回 {}。
def _norm_row(item) -> dict:
    if not isinstance(item, dict):
        return {}
    return {
        "field": normalize_field(item.get("field")) or str(item.get("field") or "").strip(),
        "value": _as_text(item.get("value")),
        "basis": str(item.get("basis") or "").strip(),
        "source": _as_source(item.get("source")),
        "verdict": str(item.get("verdict") or "").strip().lower(),
        "reason": str(item.get("reason") or "").strip(),
    }


# 生效条件：给定 raw，解析 JSON 行并保留 field 为“验证方式”或“verification_basis”（统一为“验证方式”）的行，返回列表。
def parse_reflect_rows(raw) -> list:
    out = []
    for item in _extract_json(raw, want_list=True):
        r = _norm_row(item)
        if not r or r["field"] not in ("验证方式", "verification_basis"):
            continue
        r["field"] = "验证方式"
        out.append(r)
    return out


# 生效条件：遍历 _extract_json(raw, want_list=False)（只认花括号 JSON）的结果，仅当 item 经 _norm_row 后为真且 r["field"] 非空时产出 {field,value,verdict,reason} 四键行，否则跳过（raw 无可解析花括号对象时 out 为空列表）。
def parse_verify_rows(raw) -> list:
    out = []
    for item in _extract_json(raw, want_list=False):
        r = _norm_row(item)
        if not r or not r["field"]:
            continue
        out.append({k: r[k] for k in ("field", "value", "verdict", "reason")})
    return out


# ---- 白箱闸门与双单元折叠 ------------------------------------------------

# 生效条件：逐行处理 rows，仅当 normalize_field(r.get("field")) 落在 WRITABLE_FIELDS、basis_licensed(track, r.get("basis")) 为真、r.get("source") 为真、且 r.get("value") or BASIS_TEXT.get(str(r.get("basis")), "") 非空时进入 kept（附 verdict="accept"），否则该行带对应 reason 进入 gated。
def gate_rows(rows: list, track: str) -> tuple:
    """零模型白箱闸门：字段越界 / 来源执照不通过 / 无来源 → 一律降级为 defer。

    返回 `(kept, gated)`；`kept` 只含「执照齐全」的候选，可进验证单元。
    """
    kept, gated = [], []
    for r in rows:
        f = normalize_field(r.get("field"))
        row = dict(r, field=f)
        if f not in WRITABLE_FIELDS:
            gated.append(dict(row, reason=f"越界字段：{r.get('field')}"))
            continue
        if not basis_licensed(track, r.get("basis")):
            gated.append(dict(row, reason=f"{track or '未定赛道'} 不接受基底 {r.get('basis') or '（缺）'}"))
            continue
        if not r.get("source"):
            gated.append(dict(row, reason="无来源，不写"))
            continue
        value = r.get("value") or BASIS_TEXT.get(str(r.get("basis")), "")
        if not value:
            gated.append(dict(row, reason="无验证方式声明"))
            continue
        kept.append(dict(row, value=value, verdict="accept"))
    return kept, gated


# 生效条件：按 (r.get("id"), normalize_field(r.get("field")) or r.get("field"), r.get("value")) 分组后，组内缺 unit==REFLECT_UNIT 或 unit==VERIFY_UNIT 的行时进 deferred，否则 verify 侧出现 verdict=="drop" 即进 dropped（veto 优先），再否则仅当 reflect 与 verify 各存在 verdict=="accept" 时才进 accepted（附 units），其余进 deferred。
def fold_verdicts(rows: list) -> tuple:
    """把两单元裁决折叠为可落库结论 → `(accepted, deferred, dropped)`。

    接受条件：同 `(id, field, value)` 同时存在 reflect-accept 与 verify-accept；
    任一 verify-drop 即否决（veto 优先）。
    """
    groups = OrderedDict()
    for r in rows:
        key = (r.get("id"), normalize_field(r.get("field")) or r.get("field"),
               r.get("value"))
        groups.setdefault(key, []).append(r)
    accepted, deferred, dropped = [], [], []
    for (nid, field, value), rs in groups.items():
        refl = [r for r in rs if r.get("unit") == REFLECT_UNIT]
        ver = [r for r in rs if r.get("unit") == VERIFY_UNIT]
        base = {"id": nid, "field": field or "验证方式", "value": value,
                "basis": next((r.get("basis") for r in refl if r.get("basis")), ""),
                "source": next((r.get("source") for r in refl if r.get("source")), []),
                "track": next((r.get("track") for r in refl if r.get("track")), "")}
        if not refl or not ver:
            base["reason"] = "缺" + ("反思裁决" if not refl else "验证裁决")
            deferred.append(base)
            continue
        if any(r.get("verdict") == "drop" for r in ver):
            base["reason"] = next((r.get("reason") for r in ver
                                   if r.get("verdict") == "drop"), "验证单元否决")
            dropped.append(base)
            continue
        ra = any(r.get("verdict") == "accept" for r in refl)
        va = any(r.get("verdict") == "accept" for r in ver)
        if ra and va:
            base["units"] = {
                "reflect": sorted({str(r.get("actor") or REFLECT_UNIT) for r in refl}),
                "verify": sorted({str(r.get("actor") or VERIFY_UNIT) for r in ver}),
            }
            accepted.append(base)
        else:
            base["reason"] = f"单元未确认（reflect={ra}, verify={va}）"
            deferred.append(base)
    return accepted, deferred, dropped


# 生效条件：当 rows 中 unit==REFLECT_UNIT 与 unit==VERIFY_UNIT 的执行者经 str(x.get("actor") or "") 后存在相同的非空值（空串被 discard）时返回 True，否则返回 False。
def detect_self_verify(rows: list) -> bool:
    """同一执行者同时充当反思与验证 = 自证（禁止）。"""
    r = {str(x.get("actor") or "") for x in rows if x.get("unit") == REFLECT_UNIT}
    v = {str(x.get("actor") or "") for x in rows if x.get("unit") == VERIFY_UNIT}
    r.discard("")
    v.discard("")
    return bool(r & v)


# ---- 落库写入 ------------------------------------------------------------

# 生效条件：verdicts 为 None 时返回 None；verdicts 为 dict 时对每个键值把 (rs or []) 中的 dict 元素收为 {str(nid): [...]}；否则遍历 verdicts or []，仅当元素为 dict 且 str(r.get("id") or "") 非空时按该 id 追加到对应列表。
def _norm_verdicts(verdicts):
    """外部裁决（子代理落盘）→ `{id: [rows]}`。"""
    if verdicts is None:
        return None
    out = OrderedDict()
    if isinstance(verdicts, dict):
        for nid, rs in verdicts.items():
            out[str(nid)] = [dict(x) for x in (rs or []) if isinstance(x, dict)]
        return out
    for r in verdicts or []:
        if not isinstance(r, dict):
            continue
        nid = str(r.get("id") or "")
        if nid:
            out.setdefault(nid, []).append(dict(r))
    return out


# 生效条件：accepted 非空（取 accepted[0]）时，先以 basis=str(a.get("basis") or BASIS_ENUM_DEFAULT) 与 value=str(a.get("value") or BASIS_TEXT.get(basis, "")).strip() 写「验证方式」行与 comment，之后才在 nodefile.verification_basis_valid(fm) 为真时把 basis 换成 fm.get("verification_basis")、否则把该 basis 写入 fm["verification_basis"]；condition_claims 为真时仅对 row.get("claims") 中 type==B_CLAIM 且未被 is_conditioned 的条目做条件化改写，返回含 fm_before、content_hash_before 等留痕的 dict。
def _apply_node(cg, nid, e, fm, content, accepted, row, batch, actor,
                condition_claims=True):
    """把一个节点的已接受结论写入 md，返回留痕记录（含回滚所需现场）。"""
    a = accepted[0]
    basis = str(a.get("basis") or BASIS_ENUM_DEFAULT)
    source = _as_source(a.get("source"))
    content_before = content
    value = str(a.get("value") or BASIS_TEXT.get(basis, "")).strip()

    vb_before = {"had": "verification_basis" in fm,
                 "value": fm.get("verification_basis")}
    prov_before = {"had": "verification_evidence" in fm,
                   "value": fm.get("verification_evidence")}
    line_before = {"had": _has_ccg_line(content, "验证方式"),
                   "value": _ccg_field(content, "验证方式")}
    comment0 = _comment(fm)
    cv_before = {"had": "验证方式" in comment0, "value": comment0.get("验证方式")}

    # 1) 落「验证方式」规范行 + comment + verification_basis（已有合法基底不覆盖）
    content = _upsert_ccg_line(content, "验证方式", value)
    _ensure_comment(fm)["验证方式"] = value
    if nodefile.verification_basis_valid(fm):
        basis = str(fm.get("verification_basis"))
    else:
        fm["verification_basis"] = basis

    # 2) B 型评价断言 → 条件化表述（A 型保持原样；无来源已由闸门挡掉）
    conditioned = []
    if condition_claims:
        label = BASIS_LABEL.get(basis, basis)
        for c in row.get("claims") or []:
            if c.get("type") != B_CLAIM or is_conditioned(c.get("text")):
                continue
            new = conditioned_claim(c.get("text"), label, source)
            if not new or new == c.get("text"):
                continue
            nc, ok = _rewrite_claim(fm, content, c, new)
            if not ok:
                continue
            content = nc
            conditioned.append({"where": c.get("where"), "field": c.get("field") or "",
                                "before": c.get("text"), "after": new})

    wid = _sha(f"{nid}|{batch}|{time.time()}")
    fm["verification_evidence"] = {
        "at": round(time.time(), 3), "batch": batch, "basis": basis,
        "source": source, "track": row.get("track"),
        "policy": row.get("source_policy"), "write_id": wid,
        "units": a.get("units") or {},
        "conditioned": len(conditioned),
    }

    cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                   durable=True)
    return {
        "action": "crosscheck", "ts": time.time(), "batch": batch,
        "actor": actor, "entry_id": _entry_id(batch, nid), "write_id": wid,
        "node": nid, "layer": e.get("layer"), "track": row.get("track"),
        "policy": row.get("source_policy"), "basis": basis,
        "verification_value": value, "source": source,
        "units": a.get("units") or {},
        "fm_before": {"verification_basis": vb_before,
                      "verification_evidence": prov_before,
                      "comment_verification": cv_before},
        "verification_line_before": line_before,
        "claims_conditioned": conditioned,
        "content_hash_before": _sha(content_before),
        "content_hash_after": _sha(content),
    }


# ---- 主流程 --------------------------------------------------------------

# 生效条件：reflect_fn(reflect_prompt(scan_row, fm, content)) 经 parse_reflect_rows 得到非空候选时返回 (rrows, vrows)，rrows 为空则返回 ([], [])；verify_fn 为 None 时 vrows 为空列表，非 None 时由 parse_verify_rows(verify_fn(verify_prompt(scan_row, rrows))) 生成、每行 value 为 c.get("value") or rrows 中同 field 的 value、再回落 ""。
def _rows_for(scan_row, fm, content, reflect_fn, verify_fn, r_actor, v_actor):
    """调用两单元子代理，返回合并后的裁决行（reflect + verify）。"""
    prompt = reflect_prompt(scan_row, fm, content)
    cands = parse_reflect_rows(reflect_fn(prompt))
    rrows = [dict(c, id=scan_row["id"], unit=REFLECT_UNIT, actor=r_actor,
                  track=scan_row["track"]) for c in cands]
    if not rrows:
        return [], []
    vrows = []
    if verify_fn is not None:
        vp = verify_prompt(scan_row, rrows)
        vrows = [dict(c, id=scan_row["id"], unit=VERIFY_UNIT, actor=v_actor,
                      track=scan_row["track"],
                      value=c.get("value") or next(
                          (x.get("value") for x in rrows
                           if x.get("field") == c.get("field")), ""))
                 for c in parse_verify_rows(verify_fn(vp))]
    return rrows, vrows


# 生效条件：对 pre 中每个 r，str(r.get("unit") or REFLECT_UNIT).strip().lower() 等于 VERIFY_UNIT 时进 vrows，否则（含 unit 缺失回落到 REFLECT_UNIT 及任何其他取值）进 rrows，两组行均覆盖 id=nid、unit、track=track。
def _rows_from_verdicts(nid, track, pre):
    """从外部裁决中拆出 (reflect, verify) 两组行。"""
    rrows, vrows = [], []
    for r in pre:
        unit = str(r.get("unit") or REFLECT_UNIT).strip().lower()
        base = dict(r, id=nid, unit=unit, track=track)
        (vrows if unit == VERIFY_UNIT else rrows).append(base)
    return rrows, vrows


# 生效条件：x 经 _as_cg 解析且 batch = batch or CROSSCHECK_BATCH 后逐节点扫描，裁决来源按 vmap（verdicts 归一化后非 None）→ reflect_fn 非 None → 二者皆无记 no_reflect 三条分支取行；allow_self_verify=False 时同执行者自证记 self_verify_disallowed，再经 gate_rows 闸门与 require_verify 后 fold_verdicts，仅 apply=True 才 _apply_node 写盘并在有写入时 cg.rebuild_index；limit 非 None 且已达标数 >= limit 时用 continue 跳过（非终止）。
def crosscheck(x, layer=None, limit=None, ids=None, reflect_fn=None,
               verify_fn=None, verdicts=None, apply=False,
               batch=CROSSCHECK_BATCH, actor=None, require_verify=True,
               allow_self_verify=False, reflect_actor=None, verify_actor=None,
               condition_claims=True, verbose=True, prefix=None) -> dict:
    """批量核对主流程：工单 → 反思候选 → 白箱闸门 → 验证否决 → 落库。

    `reflect_fn`/`verify_fn`：可注入的子代理函数（接收提示词、返回 JSON 文本）；
    `verdicts`：子代理离线产出的裁决行（`[VERDICT_ROW]` 或 `{id: [rows]}`），
    二选一。`apply=True` 才写盘。
    """
    cg = _as_cg(x)
    batch = batch or CROSSCHECK_BATCH
    vmap = _norm_verdicts(verdicts)
    r_actor = reflect_actor or getattr(reflect_fn, "__name__", "") or REFLECT_UNIT
    v_actor = verify_actor or getattr(verify_fn, "__name__", "") or VERIFY_UNIT

    rep = {"root": cg.root, "dry_run": not apply, "action": "crosscheck",
           "batch": batch, "actor": actor, "prefix": prefix, "nodes_scanned": 0,
           "targeted": 0,
           "accepted": 0, "rejected": 0, "deferred": 0, "written": 0,
           "claims_conditioned": 0, "skipped_locked": 0, "skipped_derived": 0,
           "skipped_internal": 0, "skipped_present": 0, "skipped_denied": 0,
           "skipped_unreadable": 0, "skipped_placeholder": 0,
           "placeholder_ids": [], "undetermined": 0,
           "reasons": {}, "samples": [], "entry_ids": []}

# 生效条件：无条件执行 rep["reasons"][reason] = rep["reasons"].get(reason, 0) + 1（reason 缺键时按 .get 的第二参数 0 起算），返回 None。
    def _bump(reason):
        rep["reasons"][reason] = rep["reasons"].get(reason, 0) + 1

# 生效条件：仅当外层 verbose 为真且 len(rep["samples"]) < 20 时把 {kind, id: nid, detail} 追加进 rep["samples"]，否则不追加（已达 20 条即停止采样）。
    def _sample(kind, nid, detail=""):
        if verbose and len(rep["samples"]) < 20:
            rep["samples"].append({"kind": kind, "id": nid, "detail": detail})

    seen_targets = 0
    for scan in _scan(cg, layer=layer, ids=ids, prefix=prefix):
        rep["nodes_scanned"] += 1
        if scan["status"] == "skip":
            reason = scan["reason"]
            if reason == "placeholder":
                rep["skipped_placeholder"] += 1
                rep["placeholder_ids"].append(scan["id"])
            else:
                key = _SKIP_KEY.get(reason)
                if key:
                    rep[key] += 1
            continue
        row = scan["row"]
        if row["track"] == "undetermined":
            rep["undetermined"] += 1
        if limit is not None and seen_targets >= limit:
            continue
        seen_targets += 1
        rep["targeted"] += 1
        nid = row["id"]
        e = cg.index["nodes"].get(nid)
        fm, content = cg._read(e) if e else (None, None)
        if fm is None or crypto.is_encrypted(content):
            rep["skipped_locked"] += 1
            continue

        # ---- 取两单元裁决 ----
        if vmap is not None:
            pre = vmap.get(nid)
            if not pre:
                rep["deferred"] += 1
                _bump("no_verdict")
                continue
            rrows, vrows = _rows_from_verdicts(nid, row["track"], pre)
        elif reflect_fn is not None:
            try:
                rrows, vrows = _rows_for(row, fm, content, reflect_fn,
                                         verify_fn, r_actor, v_actor)
            except Exception as exc:                    # noqa: BLE001
                rep["deferred"] += 1
                _bump(f"unit_error:{type(exc).__name__}")
                continue
        else:
            rep["deferred"] += 1
            _bump("no_reflect")
            continue

        # 自证：同一执行者既反思又验证 → 拒收
        if not allow_self_verify and detect_self_verify(rrows + vrows):
            rep["deferred"] += 1
            _bump("self_verify_disallowed")
            _sample("self_verify", nid)
            continue

        # ---- 白箱闸门（对反思候选；验证行只做字段归位） ----
        kept, gated = gate_rows(rrows, row["track"])
        for g in gated:
            _bump(f"gate:{g.get('reason')[:24]}")
        if not kept:
            rep["deferred"] += 1
            _bump("no_candidate")
            _sample("gated", nid, gated[0].get("reason") if gated else "")
            continue
        if require_verify and not vrows:
            rep["deferred"] += 1
            _bump("verify_unavailable")
            continue

        rows = kept + vrows
        accepted, deferred, dropped = fold_verdicts(rows)
        if dropped and not accepted:
            rep["rejected"] += 1
            _bump("verify_veto")
            _sample("veto", nid, dropped[0].get("reason", ""))
            continue
        if not accepted:
            rep["deferred"] += 1
            _bump("verdict_deferred")
            _sample("deferred", nid, deferred[0].get("reason", "") if deferred else "")
            continue

        rep["accepted"] += 1
        rep["claims_conditioned"] += sum(
            1 for c in (row.get("claims") or []) if c.get("type") == B_CLAIM)
        if apply:
            rec = _apply_node(cg, nid, e, fm, content, accepted, row, batch,
                              actor, condition_claims=condition_claims)
            append_jsonl(_log_path(cg), rec)
            rep["written"] += 1
            rep["entry_ids"].append(rec["entry_id"])
        _sample("accepted", nid, accepted[0].get("basis", ""))

    if rep["written"]:
        cg.rebuild_index()
    return rep


# ---- 留痕查询 / 回滚 -----------------------------------------------------

# 生效条件：无条件返回 os.path.join(cg.root, CROSSCHECK_LOG)（以 cg.root 与常量 CROSSCHECK_LOG 拼接，无分支）。
def _log_path(cg) -> str:
    return os.path.join(cg.root, CROSSCHECK_LOG)


# 生效条件：box 非 dict 时返回 False；box 为 dict 且 key=="comment_verification" 时按 box.get("had") 为真则把 comment 的「验证方式」设为 box.get("value")、否则删除该键并返回 True；其他 key 时 had 为真赋 fm[key]=value、否则 fm.pop(key, None) 并返回 True。
def _reattach(fm: dict, content: str, box: dict, key: str):
    """把 `fm_before[key]` 现场还原到 fm，返回是否发生还原。"""
    if not isinstance(box, dict):
        return False
    had, value = box.get("had"), box.get("value")
    if key == "comment_verification":
        c = _ensure_comment(fm)
        if had:
            c["验证方式"] = value
        else:
            c.pop("验证方式", None)
        return True
    if had:
        fm[key] = value
    else:
        fm.pop(key, None)
    return True


# 生效条件：仅当 str(c.get("after") or "") 非空，且分别满足 where=="ccg" 且 field 真值且 _ccg_field(content, field).strip()==after.strip()（用 before 覆盖该行）、where=="comment" 且 field 真值且 comment 该 field 为含 after 的 list 或 str(v or "").strip()==after.strip()（改为 before）、where=="body" 且 after 出现在 content 中（替换首个匹配）时返回 (content, True)；其余情形（含 where 为其他值、字段缺失、当前值不等于写入值）返回 (content, False)。
def _rewind_claim(fm: dict, content: str, c: dict):
    """撤销一条条件化改写（仅当前值 == 写入值时才动）→ `(content, ok)`。"""
    where, field = c.get("where"), c.get("field")
    before, after = str(c.get("before") or ""), str(c.get("after") or "")
    if not after:
        return content, False
    if where == "ccg" and field:
        if _ccg_field(content, field).strip() == after.strip():
            return _upsert_ccg_line(content, field, before), True
        return content, False
    if where == "comment" and field:
        cc = _comment(fm)
        v = cc.get(field)
        if isinstance(v, list):
            if after in v:
                cc[field] = [before if x == after else x for x in v]
                return content, True
            return content, False
        if str(v or "").strip() == after.strip():
            cc[field] = before
            return content, True
        return content, False
    if where == "body":
        if after in content:
            return content.replace(after, before, 1), True
        return content, False
    return content, False


# 生效条件：x 经 _as_cg 后，对 read_jsonl(_log_path(cg)) 中 action=="crosscheck"、batch 为 None 或等于参数 batch、且 entry_ids 为假值不做 id 过滤（为真值时仅取 entry_id 在集合中的）的记录逐条处理：node 缺失或已处理则跳过，索引无该 node 或 cg._read 得 fm 为 None 或 crypto.is_encrypted(content) 为真时 skipped_drift 加一，write_id 双方非空且不等时 conflict 加一，否则撤销 claims_conditioned、在当前「验证方式」行非空且等于 rec 的 verification_value 时撤销该行、再按 fm_before 还原，reverted 为空则 conflict 加一，非空则写回节点、追加 crosscheck_rollback 日志、reverted 与 entry_ids 加一，最终 reverted 非零时 cg.rebuild_index()，返回 rep；
def rollback(x, batch=None, entry_ids=None, actor=None) -> dict:
    """按留痕反向应用：撤销核对写入（当前值 ≠ 写入值时跳过，计入 conflict）。"""
    cg = _as_cg(x)
    want = set(entry_ids) if entry_ids else None
    done = set()
    rep = {"root": cg.root, "dry_run": False, "action": "crosscheck_rollback",
           "batch": batch, "actor": actor, "planned": 0, "reverted": 0,
           "skipped_drift": 0, "conflict": 0, "entry_ids": []}
    recs = [r for r in (read_jsonl(_log_path(cg)) or [])
            if r.get("action") == "crosscheck"
            and (batch is None or r.get("batch") == batch)
            and (want is None or r.get("entry_id") in want)]
    rep["planned"] = len(recs)
    for rec in recs:
        nid = rec.get("node")
        if not nid or nid in done:
            continue
        e = cg.index["nodes"].get(nid)
        if not e:
            rep["skipped_drift"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None or crypto.is_encrypted(content):
            rep["skipped_drift"] += 1
            continue
        # 写入现场校验：write_id 一致才回滚（防「写入后又被改过」被误撤）
        wid = (fm.get("verification_evidence") or {}).get("write_id")
        if wid and rec.get("write_id") and wid != rec.get("write_id"):
            rep["conflict"] += 1
            continue
        # 1) 撤销条件化改写（先于验证方式行，避免行被覆盖影响定位）
        reverted = []
        for c in rec.get("claims_conditioned") or []:
            content, ok = _rewind_claim(fm, content, c)
            if ok:
                reverted.append(c.get("field") or c.get("where"))
        # 2) 撤销「验证方式」行
        lb = rec.get("verification_line_before") or {}
        cur_line = _ccg_field(content, "验证方式")
        if cur_line.strip() and cur_line.strip() == str(
                rec.get("verification_value") or "").strip():
            content = (_upsert_ccg_line(content, "验证方式", lb.get("value") or "")
                       if lb.get("had") else _remove_ccg_line(content, "验证方式"))
            reverted.append("验证方式")
        # 3) 还原 frontmatter 现场
        for key, box in (rec.get("fm_before") or {}).items():
            _reattach(fm, content, box, key)
        if not reverted:
            rep["conflict"] += 1
            continue
        cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                       durable=True)
        append_jsonl(_log_path(cg), {
            "action": "crosscheck_rollback", "ts": time.time(),
            "batch": rec.get("batch"), "actor": actor,
            "entry_id": rec.get("entry_id"), "node": nid,
            "reverted": reverted, "content_hash_after": _sha(content)})
        rep["reverted"] += 1
        rep["entry_ids"].append(rec.get("entry_id"))
        done.add(nid)
    if rep["reverted"]:
        cg.rebuild_index()
    return rep


# 生效条件：遍历 _log_path(cg) 的记录时，action 为真值只留 rec.get("action")==action 的行、batch 为真值只留 rec.get("batch")==batch 的行；limit 非 None 且 limit>=0 时按 recs[-limit:] 截取（limit 为 0 时 [-0:] 即整表不被削减），否则保留全部；返回 {'root','total','returned','records'}。
def history(x, limit=100, action=None, batch=None) -> dict:
    cg = _as_cg(x)
    recs = []
    for rec in read_jsonl(_log_path(cg)) or []:
        if action and rec.get("action") != action:
            continue
        if batch and rec.get("batch") != batch:
            continue
        recs.append(rec)
    total = len(recs)
    if limit is not None and limit >= 0:
        recs = recs[-limit:]
    return {"root": cg.root, "total": total, "returned": len(recs),
            "records": recs}


# ---- 权限与 CLI ----------------------------------------------------------

# 生效条件：principal 为 None 时返回 False；否则仅当 principal.expired() 为假、principal.can_write 为真、且 principal.allows_layer("knowledge") 为真时返回 True，期间任一步抛 Exception 亦返回 False。
def can_write_knowledge(principal) -> bool:
    """落 knowledge 层必须持有可写该层的令牌（designer 派生）；否则 fail-closed。"""
    if principal is None:
        return False
    try:
        if principal.expired() or not principal.can_write:
            return False
        return bool(principal.allows_layer("knowledge"))
    except Exception:                                   # noqa: BLE001
        return False


# 生效条件：path 为假值（空串/None）返回 None；path 不存在则 raise SystemExit；已存在且读取文本 strip 后为空串返回 []，非空时整段 json.loads 成功即返回该值，抛 ValueError 时按行解析（跳过空行与 "//" 开头行）返回行列表。
def _load_verdicts(path: str):
    if not path:
        return None
    if not os.path.exists(path):
        raise SystemExit(f"裁决文件不存在：{path}")
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read().strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except ValueError:
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            rows.append(json.loads(line))
        return rows


# 生效条件：argv（为 None 时由 argparse 读 sys.argv）解析后按 --action 分派——worklist 调 build_worklist，history 调 history（--limit 默认 None，为 None 时传 100），rollback 在 can_write_knowledge(principal) 为假时抛 SystemExit 否则调 rollback，crosscheck 在 --apply 为真且 can_write_knowledge(principal) 为假时抛 SystemExit 否则调 crosscheck；--token（默认 os.environ.get("MDCG_TOKEN") or ""）为真值时先 tokens.verify_token 校验、失败抛 SystemExit；最后打印 rep 并返回 0；
def _cli(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m md_cg.crosscheck",
        description="kp_ 批量核对管线（工单/核对/回滚/留痕）")
    ap.add_argument("--root", default=os.environ.get("MDCG_ROOT") or ".")
    ap.add_argument("--token", default=os.environ.get("MDCG_TOKEN") or "")
    ap.add_argument("--token-file", default=None)
    ap.add_argument("--action", default="worklist",
                    choices=("worklist", "crosscheck", "rollback", "history"))
    ap.add_argument("--verdicts", default="", help="子代理裁决 JSON/JSONL 路径")
    ap.add_argument("--apply", action="store_true", help="真正写盘（默认 dry-run）")
    ap.add_argument("--batch", default=CROSSCHECK_BATCH)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--layer", default=None)
    ap.add_argument("--prefix", default=None, help="按 id 前缀收窄（真实库用 kp_）")
    ap.add_argument("--ids", default="", help="逗号分隔节点 id")
    ap.add_argument("--no-verify", action="store_true", help="允许无验证单元（不建议）")
    ap.add_argument("--allow-self-verify", action="store_true")
    ap.add_argument("--reflect-actor", default=None)
    ap.add_argument("--verify-actor", default=None)
    args = ap.parse_args(argv)

    from . import tokens
    principal = None
    if args.token:
        try:
            principal = tokens.verify_token(args.token, path=args.token_file)
        except tokens.TokenError as exc:
            raise SystemExit(f"令牌校验失败：{exc}")
    actor = getattr(principal, "actor", None)
    ids = [s.strip() for s in args.ids.split(",") if s.strip()] or None

    if args.action == "worklist":
        rep = build_worklist(args.root, layer=args.layer, limit=args.limit,
                             ids=ids, prefix=args.prefix)
    elif args.action == "history":
        rep = history(args.root, limit=args.limit if args.limit is not None else 100,
                      batch=args.batch)
    elif args.action == "rollback":
        if not can_write_knowledge(principal):
            raise SystemExit("权限不足：回滚需要可写 knowledge 层的令牌")
        rep = rollback(args.root, batch=args.batch, actor=actor)
    else:
        if args.apply and not can_write_knowledge(principal):
            raise SystemExit("权限不足：落库需要可写 knowledge 层的令牌（designer 派生）")
        rep = crosscheck(args.root, layer=args.layer, limit=args.limit, ids=ids,
                         prefix=args.prefix,
                         verdicts=_load_verdicts(args.verdicts), apply=args.apply,
                         batch=args.batch,
                         require_verify=not args.no_verify,
                         allow_self_verify=args.allow_self_verify,
                         reflect_actor=args.reflect_actor,
                         verify_actor=args.verify_actor, actor=actor)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":                              # pragma: no cover
    sys.exit(_cli())