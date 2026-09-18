# -*- coding: utf-8 -*-
"""记忆评审流水线 · M3 定位模块（D1 字段级定位，确定性、零写入）。

真源：docs/记忆评审系统_立项设计与施工交接_20260915.md §5 D1。

D1 契约：

    locate(node_id, issue_hint) -> [{"field", "span", "issue_kind", "evidence"}, ...]

* **field**      —— frontmatter 字段名，或 `"content"`（正文）
* **span**       —— 命中处的字符区间 `[start, end)`（半开），**相对正文 content**；
                    纯字段级缺失无字符区间可指 → `None`
* **issue_kind** —— dup / missing_field / stale / contradiction / weak_source / template_flow
                    （`ISSUE_KINDS`＝问题面）；另有 `ADVISORY_KINDS`（观测面，可显式定位
                    但**不进默认全量、不进评审告警面**，见下「stale 与 observation_aged」）
* **evidence**   —— 白箱判据：为什么算问题（人可复核、机器可断言）

定位的职责边界：M2 的意见说「这一条有问题」，D1 回答「问题在这一条的哪个字段/哪一段」。
故本模块只做**确定性可判定**的事——语义级矛盾（正文自相矛盾）**不猜**，如实返回
BLINDSPOT 项交回 LLM 意见层（`status="blindspot"`，见 `locate()` 返回值）。

口径全部引用既有唯一真源，**不在本模块另立一份**（防「术语双写法」漂移）：

=============== ==================================================================
字段/正文结构   ``nodefile``（CCG_MARKS / CONDITION_SLOTS / VERIFICATION_BASIS /
                loads / content_hash / is_placeholder_text / time_window_text）
模板骨架        ``writelimit._skeleton`` / ``MIN_SKELETON``
赛道×基底相容    ``crosscheck``（与 M1 `ruleset._chk_basis_licensed` 同源）
字段层门限      ``ruleset``（即 `rules/*.json` 的 `matcher.layer`，见
                `field_layer_scope`——**派生**，不在此另立一份）
索引快照        ``conformance.load_index``
=============== ==================================================================

与 M1（`ruleset` 机械层）的用词归并：D1 说 `dup`，M1 的 `dup_hash_group` 说
`dup_content`——同一件事两种写法，由 `KIND_ALIASES` 单一归口（`canonical_kind`）。

超出 D1 最小契约的**增强键**（供人工核对直接跳文件/跳行，不影响四键契约）：
`line`（节点文件原文 1-based 行号）、`sentence`（正文句索引，0 基）、
`snippet`（命中片段）、`rule`（触发定位的判据名，审计用）、`peer`（同组对照节点）、
`cause`（`contradiction` 的**成因**判定，见 `hash_mismatch_cause`——同一条命中
可能是「真不一致」也可能是「索引快照滞后」，两种成因不分会让复核者误判为数据损坏）。

**`stale` 与 `observation_aged` 的判据源分工（2026-09-16 修正）**：

* `stale`（**问题面**）—— **依赖存在性**：`code_ref`/`doc_ref` 指的源文件已不存在
  （悬空）或已漂移（区间哈希不符）。判据直接调 `refindex.probe_ref`，**不另立一份**
  （防「术语双写法」漂移）。代码知识的真值挂在源文件上，源没了/改了才是适用边界越出。
* `observation_aged`（**观测面**，`ADVISORY_KINDS`，**不进默认全量**）——
  `condition_space.time_window` 已过。这是**观测时刻**不是失效声明：写入端
  （`mdcg.add`，见其 `OBSERVATION_WINDOW_SEC`）在未给 time_window 时以**写入时刻**
  自动填 1 小时窗，故真库中「已过期」绝大多数是「写入超过 1 小时」，与知识是否失效
  无关——把它当问题投进评审告警面就是系统性误报（实测：全库 1453 条过期里 1434 条
  属默认窗填充）。需要时效判定用 `stale`（依赖存在性），不是这里。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

from .. import conformance as CF
from .. import crosscheck as CC
from .. import nodefile as NF
from .. import refindex as RI
from .. import writelimit as WL
from . import ruleset as RS

__all__ = ["ISSUE_KINDS", "ADVISORY_KINDS", "KIND_ALIASES", "canonical_kind", "locate",
           "locate_many", "locate_package", "sentence_spans", "mark_spans", "load_node",
           "main", "field_layer_scope", "hash_mismatch_cause", "HASH_CAUSES"]

#: D1 的问题类别（真源：立项文档 §5 D1）——**问题面**：命中即「知识有问题」
ISSUE_KINDS = ("dup", "missing_field", "stale", "contradiction",
               "weak_source", "template_flow")

#: **观测面**（咨询级）：可显式定位，但**不进默认全量定位、不进评审告警面**。
#: 判据：本类命中说的是「观测手段的副产品」（如「这条记忆写入超过 1 小时」），
#: 不是「知识有问题」——把它混进 ISSUE_KINDS 会让每一次写入在 1 小时后自动变成
#: 待评审问题（系统性误报）。故与问题面分表，只有显式点名才产出。
ADVISORY_KINDS = ("observation_aged",)

#: M1（ruleset 机械层）与 D1 的用词归并——两处说的是同一件事，不许各说各话
KIND_ALIASES = {"dup_content": "dup",        # M1 `dup_hash_group`
                "missing": "missing_field",
                "flow": "template_flow",
                "template_flow_digits_only": "template_flow"}

#: 扫描 frontmatter 的字段清单（真源字段名取自 nodefile 口径，不自由发明）
FM_SCAN_FIELDS = ("role", "tags", "importance", "evidence_count",
                  "verification_basis", "lifecycle_state", "condition_space")

#: 判为「同模板流水」所需的最少同骨架句数——单句偶合不算流水（防误报）
MIN_FLOW_SENTENCES = 2

#: 一句话摘要的最大长度
SNIPPET_MAX = 120

#: 索引快照与节点文件的 mtime 差**小于**此值 → 视为同一批写入，不判「快照滞后」
MTIME_TOLERANCE = 1.0

#: `content_hash` 不一致的**成因**（确定性判据，不猜；见 `hash_mismatch_cause`）
HASH_CAUSES = ("index_lag", "true_mismatch", "unknown")

#: `refindex.probe_ref` 的五态里，哪些构成「依赖已失效」（`stale` 判据，见 `_loc_stale`）：
#: 只有这两态说明**载体真的没了/改了**；`unresolved`（拿不到 root）与 `error`（读盘失败）
#: 是观测手段不足，按「不猜」纪律不判。
_REF_DEAD_STATUSES = ("dangling", "stale")

#: 字段层门限缓存（规则库是包内数据文件，进程内不变 → 惰性算一次）
_FIELD_LAYER_CACHE = None


# 生效条件：kind 经 str(kind or "").strip() 得 k（None/空串等假值 → 空串 ""），k 命中 KIND_ALIASES 时返回其规范名，否则原样返回 k。
def canonical_kind(kind) -> str:
    """M1/D1 用词 → D1 规范名（未知原样返回，不假装认路）。"""
    k = str(kind or "").strip()
    return KIND_ALIASES.get(k, k)


# 生效条件：仅当 rules 与 rules_dir 均为 None 且模块级 _FIELD_LAYER_CACHE 非 None 时直接返回该缓存；否则遍历 rules（dict 取其 "rules" 键的列表、非 dict 直接 list(rules)）或 rules_dir 经 RS.load_rules 取得的 rules 列表，从限了 matcher.layer 的 mechanical 规则中收集 field_absent 的 spec["field"] 与 evidence_zero 的 evidence_count，返回 {字段: 排序列}，且只在 rules 与 rules_dir 均为 None 时写回 _FIELD_LAYER_CACHE。
def field_layer_scope(rules=None, rules_dir=None) -> dict:
    """字段 → 适用层清单（**派生**自 M1 规则库，不在此另立一份）。

    真源 = `md_cg/mreview/rules/*.json` 的 `matcher.layer`：只收录**限了层**的
    机械规则字段（`field_absent` 取 `spec["field"]`、`evidence_zero` 取
    `evidence_count`）；未限层的规则 = 全层适用，不入表。

    理由：字段范围两处各写一份 ⇒ 必然漂移（同「术语双写法」）。派生使 M1 改规则
    时 M3 自动跟随。规则库损坏 → `load_rules` 抛错（fail-closed，不静默降级成全层）。
    """
    global _FIELD_LAYER_CACHE
    if rules is None and rules_dir is None and _FIELD_LAYER_CACHE is not None:
        return _FIELD_LAYER_CACHE
    if isinstance(rules, dict):
        rl = list(rules.get("rules") or [])
    elif rules is not None:
        rl = list(rules)
    else:
        rl = list(RS.load_rules(rules_dir)["rules"])
    scope = {}
    for r in rl:
        layers = set((r.get("matcher") or {}).get("layer") or [])
        if not layers:
            continue
        for spec in r.get("mechanical") or []:
            chk = spec.get("check")
            if chk == "field_absent" and spec.get("field"):
                scope.setdefault(str(spec["field"]), set()).update(layers)
            elif chk == "evidence_zero":
                scope.setdefault("evidence_count", set()).update(layers)
    out = {k: sorted(v) for k, v in sorted(scope.items())}
    if rules is None and rules_dir is None:
        _FIELD_LAYER_CACHE = out
    return out


# 生效条件：(scope or {}).get(field) 为假值（scope 为 None、空 dict 或 field 不在其中）→ 返回 True；want 为真值时仅当 str((meta or {}).get("layer")) 在 set(want) 内返回 True，否则 False。
def _layer_ok(field, scope, meta) -> bool:
    """字段层门限：**限层的字段只在该层的节点上检查**。

    口径与 M1 `ruleset._scope`（`str(e.get("layer")) in want`）逐字一致——缺层
    （`None`）不在任何层清单内 ⇒ 不检查。两处判据同源，防「越层误报」：
    M1 不在某层报的问题，M3 也不该报。
    """
    want = (scope or {}).get(field)
    if not want:
        return True
    return str((meta or {}).get("layer")) in set(want)


# 生效条件：os.path.getmtime(path) 成功则返回该 mtime；抛 OSError 或 TypeError → 返回 None。
def _mtime(path):
    """文件 mtime（不可读 → `None`，不假装知道）。"""
    try:
        return os.path.getmtime(path)
    except (OSError, TypeError):
        return None


# 生效条件：root 或 rel（path 为真值时取 path，否则取 meta 的 "path"）为空 → 返回 ("unknown", "无 root/path 可用，取不到盘上 mtime，成因未判定")；两者都有时取节点文件与 CF.INDEX_FILE 的 mtime，任一为 None → 返回 ("unknown", "节点文件或索引快照不可读，成因未判定")，节点 mtime 减索引 mtime 之差 > MTIME_TOLERANCE → 返回 ("index_lag", …)，否则返回 ("true_mismatch", …)。
def hash_mismatch_cause(meta, *, root=None, path=None) -> tuple:
    """`content_hash` 声明值 ≠ 正文实算值 → **成因**判定（靠 mtime 证据，不猜）。

    → `(cause, note)`；cause ∈ `HASH_CAUSES`；取不到盘上证据 → `"unknown"`。

    写路径真源（`md_cg/mdcg.py`）：写走 `_stage()` 落**分片日志**，`rebuild_index()`
    才写 `_index.json` 快照——故「节点文件比索引快照新」是**正常写路径现象**
    （快照滞后），不是文件被篡改；把两种成因合并成一句「索引与文件不一致」会让
    复核者误判为数据损坏（实测滞后可达 14s 量级）。
    """
    rel = path if path else (meta or {}).get("path")
    if not root or not rel:
        return "unknown", "无 root/path 可用，取不到盘上 mtime，成因未判定"
    fp = str(rel) if os.path.isabs(str(rel)) else os.path.join(str(root), str(rel))
    fm_t = _mtime(fp)
    idx_t = _mtime(os.path.join(str(root), CF.INDEX_FILE))
    if fm_t is None or idx_t is None:
        return "unknown", "节点文件或索引快照不可读，成因未判定"
    delta = fm_t - idx_t
    if delta > MTIME_TOLERANCE:
        return "index_lag", ("节点文件比索引快照新 %.2fs——分片日志已写、_index.json "
                             "未 rebuild（快照滞后属正常写路径现象）" % delta)
    return "true_mismatch", ("节点文件不晚于索引快照（差 %.2fs）——非快照滞后，"
                             "索引声明与文件真源相抵触" % delta)


# ---------------------------- 基础工具（纯函数） ----------------------------

# 生效条件：v 为 list/tuple/dict 时返回 not v（空容器 → True）；其余类型返回 v is None 或 str(v).strip() 为 "" 或 "None"。
def _blank(v) -> bool:
    if isinstance(v, (list, tuple, dict)):
        return not v
    return v is None or str(v).strip() in ("", "None")


# 生效条件：int(float(v)) 可算（含数字字符串）则返回该整数；抛 TypeError 或 ValueError（含 v 为 None、非数字串）→ 返回 None。
def _as_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# 生效条件：float(v) 可算则返回该浮点数；抛 TypeError 或 ValueError（含 v 为 None、非数字串）→ 返回 None。
def _as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


_SENT_END = "。！？；!?;\n"


# 生效条件：content 为假值（None/空串）按 "" 处理，逐字符命中 _SENT_END 切出且 seg.strip() 非空的段以 len(out) 为序号追加 (索引, start, i+1, 原文)，末尾 tail.strip() 非空亦追加；无合格段 → 返回空列表。
def sentence_spans(content: str) -> list:
    """正文 → `[(句索引, start, end, 原文)]`；空句不编号（索引连续，确定性）。"""
    text, out, start = content or "", [], 0
    for i, ch in enumerate(text):
        if ch in _SENT_END:
            seg = text[start:i + 1]
            if seg.strip():
                out.append((len(out), start, i + 1, seg))
            start = i + 1
    tail = text[start:]
    if tail.strip():
        out.append((len(out), start, len(text), tail))
    return out


#: 正文要素行：`# 功能名：…` / `# 生效条件: …`（间隔与分隔符两形态都收）
_RE_MARK = re.compile(r"^#[ \t]*(?P<mark>[^：:\n]{1,16})[：:][^\n]*", re.M)


# 生效条件：在 content（假值 → ""）上用模块级 _RE_MARK 迭代匹配，以 m.group("mark").strip() 为键 setdefault 记下首次出现的 [m.start(), m.end())；无匹配（含 content 为假值）→ 返回空 dict。
def mark_spans(content: str) -> dict:
    """正文 CCG 要素行 → `{要素名: [start, end)}`；同要素取首次出现（确定性）。"""
    out = {}
    for m in _RE_MARK.finditer(content or ""):
        out.setdefault(m.group("mark").strip(), [m.start(), m.end()])
    return out


# 生效条件：(text or "").split("\n") 的每行 strip 后非空、不以 "#" 开头且含 ":" 时，取首个冒号前的键 k，k 非空且尚未入表则记 (1-based 行号, [该行起始偏移, 起始偏移+len(line)])；text 为假值或无合格行 → 返回空 dict。
def key_line_spans(text: str) -> dict:
    """节点文件原文 → `{键: (1-based 行号, [start, end))}`。

    只认**无 `#` 前缀**且含 `:` 的行——即 frontmatter 行；`---` 分隔线无冒号，
    自然被排除。同键取首次出现。
    """
    out, pos = {}, 0
    for i, line in enumerate((text or "").split("\n")):
        s = line.strip()
        if s and not s.startswith("#") and ":" in s:
            k = s.split(":", 1)[0].strip()
            if k and k not in out:
                out[k] = (i + 1, [pos, pos + len(line)])
        pos += len(line) + 1
    return out


# 生效条件：index 为 dict 时其 "nodes" 为 dict 则返回 index["nodes"]，否则返回 index 本身；index 为 None/非 dict 时调 CF.load_index(root)，抛 OSError 或 ValueError → 返回 {}，返回值为 dict 且其 "nodes" 为 dict → 返回该 "nodes"，是 dict → 原样返回，否则返回 {}。
def _index(root, index=None) -> dict:
    """索引节点表 `{node_id: meta}`（兼容 load_index 的 `{"nodes": …}` 形态）。"""
    if isinstance(index, dict):
        return index.get("nodes") if isinstance(index.get("nodes"), dict) else index
    try:
        idx = CF.load_index(root)
    except (OSError, ValueError):
        return {}
    if isinstance(idx, dict) and isinstance(idx.get("nodes"), dict):
        return idx["nodes"]
    return idx if isinstance(idx, dict) else {}


# 生效条件：_index(root, index) 中 node_id 对应值非 dict → 返回 None；否则用 meta.get("path")（绝对路径直接用，否则 join(root, str(rel or ""))）读文件——OSError 时返回 content/text 为 None、fm 为 {} 的 dict，成功则把 NF.loads(text) 得到的 content 与 fm（假值 → {}）连同 meta/path/text 一并返回。
def load_node(node_id, root, *, index=None) -> dict:
    """读一个节点（索引 meta + 文件 frontmatter + 正文原文）。

    → `{"node_id","meta","fm","content","text","path"}`；索引无此项 → `None`。
    `meta` 是**索引快照**（含索引侧 content_hash，矛盾判定要用），`fm` 是**文件真源**。
    """
    nodes = _index(root, index)
    meta = nodes.get(node_id)
    if not isinstance(meta, dict):
        return None
    rel = meta.get("path")
    fp = rel if (rel and os.path.isabs(str(rel))) else os.path.join(root, str(rel or ""))
    try:
        with open(fp, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {"node_id": node_id, "meta": dict(meta), "fm": {}, "content": None,
                "text": None, "path": fp}
    fm, content = NF.loads(text)
    return {"node_id": node_id, "meta": dict(meta), "fm": fm or {}, "content": content,
            "text": text, "path": fp}


# 生效条件：span 为 None → 返回 ""；否则取 (text or "")[span[0]:span[1]] 去空白并把换行替换为 "⏎"，长度超 SNIPPET_MAX 时截断并追加 "…"。
def _snippet(text, span) -> str:
    """命中片段（供人工核对肉眼确认「指的是不是这一句」）。"""
    if span is None:
        return ""
    seg = (text or "")[span[0]:span[1]].strip().replace("\n", "⏎")
    return seg[:SNIPPET_MAX] + ("…" if len(seg) > SNIPPET_MAX else "")


# 生效条件：任意 node_id/kind/field/span/evidence 均原样写入返回 dict 的 node_id/issue_kind/field/span/evidence 键，可选 rule/line/sentence/snippet/peer/cause/severity 未传时为 None、status 未传时为 "located"，不做任何校验。
def _hit(node_id, kind, field, span, evidence, *, rule=None, line=None,
         sentence=None, snippet=None, peer=None, cause=None, status="located",
         severity=None) -> dict:
    """命中行（四键契约 + 增强键）。

    `severity` 是**观测面专用**的等级标注（`ADVISORY_KINDS` 命中带 `"info"`）：
    问题面命中不带（问题即问题，无等级可降）；本键让下游一眼分清「这是观测
    副产品」与「这是待修的问题」，不必靠 issue_kind 名字去猜。
    """
    return {"node_id": node_id, "field": field, "span": span, "issue_kind": kind,
            "evidence": evidence, "rule": rule, "line": line, "sentence": sentence,
            "snippet": snippet, "peer": peer, "cause": cause, "status": status,
            "severity": severity}


# 生效条件：text 为真值、span 与 content 均非 None 且 text.find(content)>=0 时，返回 text.count("\n",0,min(off+span[0],len(text)))+1 的 1-based 行号；text 假值或 span/content 为 None 或 content 未找到时返回 None。
def _line_of(text, content, span):
    """正文区间 → 节点文件原文的 1-based 行号（供人工核对直接跳文件）。"""
    if not text or span is None or content is None:
        return None
    off = text.find(content)
    if off < 0:
        return None
    return text.count("\n", 0, min(off + span[0], len(text))) + 1


# ---------------------------- 定位器注册表 ----------------------------
#
# 每个定位器是**纯函数**：只吃 (node_id, meta, content, ctx)，只吐 hits。
# 新增判据 = 加函数 + 注册，不改 locate 主流程（与 M1「引擎冻结、规则可增删」同构）。
# ctx = {"fm", "text", "root", "index", "peers", "now"}

# 生效条件：在 node_id/meta/content/ctx 下，对 FM_SCAN_FIELDS 中除 verification_basis、condition_space 外且 _layer_ok(f,scope,meta) 为真的字段，若 meta.get(f) 与 ctx.get("fm") 或 {} 中的同名字段皆 _blank 则记 field_absent；对过 _layer_ok 且 _as_int(meta.get("evidence_count"))==0 记 evidence_zero；对 meta.get("importance") 非 None 且 _as_float 为 None 或不在 [0.0,1.0] 记 field_invalid；对 condition_space 经 meta 或回落 ctx.get("fm") 后 NF.condition_space_missing 非空记 condition_slots；对正文缺 NF.CCG_MARKS 行记 ccg_incomplete，返回这些命中列表。
def _loc_missing_field(node_id, meta, content, ctx):
    """frontmatter/正文结构字段为空（判据与 M1 `field_absent`/`evidence_zero` 同源）。

    **层门限**：限层的字段（如 `role`/`evidence_count` 限 `knowledge`）只在
    该层节点上检查——与 M1 `_scope` 同口径，否则 M1 不报的问题会被 M3 越层报出。
    """
    fm = ctx.get("fm") or {}
    scope = ctx.get("field_layers")
    if scope is None:
        scope = field_layer_scope()
    lines = key_line_spans(ctx.get("text") or "")
    marks = mark_spans(content or "")
    hits = []

    for f in FM_SCAN_FIELDS:
        if f in ("verification_basis", "condition_space"):
            continue        # 基底空属 weak_source；四槽缺失单独报（要点名缺哪几槽）
        if not _layer_ok(f, scope, meta):
            continue        # 越层不报（层门限真源 = M1 规则库 matcher.layer）
        if _blank(meta.get(f)) and _blank(fm.get(f)):
            hits.append(_hit(node_id, "missing_field", f, None,
                             "字段 %s 为空（索引与文件两处皆空）" % f,
                             rule="field_absent",
                             line=(lines.get(f) or (None, None))[0]))

    if _layer_ok("evidence_count", scope, meta) \
            and _as_int(meta.get("evidence_count")) == 0:
        hits.append(_hit(node_id, "missing_field", "evidence_count", None,
                         "evidence_count=0（无验证证据计数）", rule="evidence_zero",
                         line=(lines.get("evidence_count") or (None, None))[0]))

    imp = meta.get("importance")
    if imp is not None:
        fv = _as_float(imp)
        if fv is None or not 0.0 <= fv <= 1.0:
            hits.append(_hit(node_id, "missing_field", "importance", None,
                             "importance=%r 不在 [0,1]（字段存在但不可用）"
                             % (imp,), rule="field_invalid",
                             line=(lines.get("importance") or (None, None))[0]))

    cs = meta.get("condition_space")
    if not isinstance(cs, dict):
        cs = fm.get("condition_space")
    miss = NF.condition_space_missing(cs)
    if miss:
        span = marks.get("生效条件")
        hits.append(_hit(node_id, "missing_field", "condition_space", span,
                         "条件空间缺槽 %s（%d/4 已声明）——四槽不全不构成生效条件"
                         % ("/".join(miss), len(NF.CONDITION_SLOTS) - len(miss)),
                         rule="condition_slots",
                         snippet=_snippet(content, span)))

    # 正文 CCG 要素缺行：行不存在 → 无字符区间可指（span=None），点名缺哪几行
    missing_marks = [m for m in NF.CCG_MARKS if m not in marks]
    if missing_marks:
        hits.append(_hit(node_id, "missing_field", "content", None,
                         "正文缺 CCG 要素行 %s（# 要素名：值）——缺声明即缺证据"
                         % "/".join(missing_marks), rule="ccg_incomplete"))
    return hits


# 生效条件：meta.get("verification_basis") 为空时回落 ctx.get("fm") 或 {} 的 verification_basis，若两者皆 _blank 返回 basis_absent 命中；非空但 str(basis) 不在 NF.VERIFICATION_BASIS 返回 basis_enum 命中；在枚举内时按 CC.classify_track 依 meta.get("layer")、meta.get("tags") 与 content 判赛道，若 CC.basis_licensed 为假返回 basis_licensed 命中；否则返回 []。
def _loc_weak_source(node_id, meta, content, ctx):
    """验证基底缺失/越枚举/与赛道不相容（与 M1 `basis_licensed` 判据逐字同源）。"""
    fm = ctx.get("fm") or {}
    basis = meta.get("verification_basis")
    if _blank(basis):
        basis = fm.get("verification_basis")
    _ln = key_line_spans(ctx.get("text") or "").get("verification_basis")
    ln = (_ln or (None, None))[0]

    if _blank(basis):
        return [_hit(node_id, "weak_source", "verification_basis", None,
                     "verification_basis 为空——无验证基底的断言不可裁决",
                     rule="basis_absent", line=ln)]
    if str(basis) not in NF.VERIFICATION_BASIS:
        return [_hit(node_id, "weak_source", "verification_basis", None,
                     "基底 %s 不在合法枚举（%s）"
                     % (basis, "/".join(NF.VERIFICATION_BASIS)),
                     rule="basis_enum", line=ln)]
    track = CC.classify_track({"layer": meta.get("layer"),
                               "tags": meta.get("tags") or []}, content or "")
    if not CC.basis_licensed(track, basis):
        allow = "/".join(CC.allowed_basis(track)) or "—"
        return [_hit(node_id, "weak_source", "verification_basis", None,
                     "赛道 %s（政策 %s）不允许基底 %s；允许 %s"
                     % (track, CC.source_policy(track) or "—", basis, allow),
                     rule="basis_licensed", line=ln)]
    return []


# 生效条件：ctx.get("fm") 或 {} 中 code_ref 或 doc_ref 为非空 dict 且 RI.probe_ref(ref) 返回的 status 属于 _REF_DEAD_STATUSES（dangling 或 stale）时，返回对应 stale 命中（dangling 归因载体消失、stale 归因区间哈希不符）；否则返回 []。
def _loc_stale(node_id, meta, content, ctx):
    """**依赖存在性**——声明的载体（源文件）已不存在 / 已漂移（真正的适用边界越出）。

    知识的真值挂在它描述的对象上：代码知识挂在源文件的符号上，源没了或改了，
    知识才真的不再成立。判据与 `refindex` **同源**（`probe_ref`，不另立一份）：

    ============== ====================================== ==========
    probe_ref 态    含义                                   本判据
    ============== ====================================== ==========
    ``ok``         源文件在、区间哈希匹配                  不判
    ``stale``      源文件在、区间哈希不符（源被改，漂移）  **stale**
    ``dangling``   源文件不存在（载体消失）                **stale**
    ``unresolved`` 拿不到 root（判不了）                    不判（不猜）
    ``error``      读盘失败                                不判（不猜）
    ============== ====================================== ==========

    后两态是**观测手段不足**，不是「依赖已失效」——按「不猜」纪律如实不报。

    **时间窗不在此处判**（2026-09-16 修正的原缺陷）：`condition_space.time_window`
    是写入端**观测时刻**栏（`mdcg.add` 未给时自动填「写入时刻 +1h」，见其
    `OBSERVATION_WINDOW_SEC`），不是知识的有效期——拿它判「适用边界越出」，
    等于把「这条记忆写入超过 1 小时」冒充为「失效」。真实适用前提由知识自己
    声明在 `code_ref`/`doc_ref` 上，故改由依赖存在性裁决；观测时刻本身不丢，
    降级为 `observation_aged`（观测面，见 `ADVISORY_KINDS`）。
    """
    fm = ctx.get("fm") or {}
    hits = []
    for key in ("code_ref", "doc_ref"):
        ref = fm.get(key)
        if not isinstance(ref, dict) or not ref:
            continue
        # root 基准必须取自 ref 自身（`_code_ref`/`_doc_ref` 落的是**源大域** root，
        # path 相对它）；`ctx["root"]` 是**认知图** root——拿它去拼会把每一条依赖
        # 都误判成悬空。ref 无 root（旧节点）时 probe 返回 `unresolved` → 不判。
        probe = RI.probe_ref(ref)
        st = str(probe.get("status") or "")
        if st not in _REF_DEAD_STATUSES:
            continue
        rel = str(ref.get("path") or "?")
        if st == "dangling":
            ev = ("依赖的源文件已不存在（%s：%s）——知识所指的载体消失，适用边界越出"
                  % (key, rel))
        else:
            ev = ("依赖的源文件已漂移（%s：%s）：索引区间哈希 %s ≠ 现算 %s——"
                  "源被改动，知识所指的符号可能已不是原物"
                  % (key, rel, probe.get("hash_expected"), probe.get("hash")))
        hits.append(_hit(node_id, "stale", key, None, ev, rule="ref_" + st))
    return hits


# 生效条件：从 meta.get("condition_space") 或回落 ctx.get("fm") 的 condition_space（须为 dict）取 time_window，缺则取 meta.get("time_window")，若 NF.is_full_time_window(tw) 或 float(tw[1]) 抛 TypeError/ValueError/IndexError/KeyError 或 ctx.get("now") 为 None 或 hi>=float(now) 则返回 []；否则返回一条 severity="info" 的 observation_aged 命中。
def _loc_observation_aged(node_id, meta, content, ctx):
    """时间窗已过——**这是观测时刻，不是失效声明**（观测面，不进告警面）。

    时间窗来源链与 `_loc_missing_field` 的槽检查同构：`meta.condition_space`
    （显式注入面）→ `fm.condition_space`（文件真源）→ `meta.time_window`
    （索引快照字段）。**索引快照只透传 `time_window`**（`mdcg.py` `_stage` 口径：
    时空字段入快照、condition_space 整块不入），故第三跳必留。

    **不进默认全量**（不在 `ISSUE_KINDS`）：写入端未给 time_window 时以写入时刻
    自动填 1 小时窗，故真库「已过期」绝大多数是「写入超过 1 小时」，与知识是否
    失效无关。观测时刻本身仍如实报（审计有用），只是**不冒充问题**——命中带
    `severity="info"` 标记它是咨询级。
    """
    fm = ctx.get("fm") or {}
    cs = meta.get("condition_space")
    if not isinstance(cs, dict):
        csf = fm.get("condition_space")
        cs = csf if isinstance(csf, dict) else None
    tw = (cs or {}).get("time_window")
    if tw is None:
        tw = meta.get("time_window")
    if NF.is_full_time_window(tw):
        return []           # 全时窗是**合法声明**（任意时刻成立），不判
    try:
        hi = float(tw[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return []
    now = ctx.get("now")
    if now is None or hi >= float(now):
        return []
    span = mark_spans(content or "").get("生效条件")
    return [_hit(node_id, "observation_aged", "condition_space", span,
                 "观测时间窗 %s 已过（hi=%.0f < now=%.0f）——这是**观测时刻**，"
                 "不是失效声明（知识不因观测过去而失效）；时效判定见 stale"
                 % (NF.time_window_text(tw) or "?", hi, float(now)),
                 rule="observation_window_passed", severity="info",
                 line=_line_of(ctx.get("text"), content, span),
                 snippet=_snippet(content, span))]


# 生效条件：h 取 str(meta.get("content_hash") or "").strip()，若 _blank(h) 则 h=NF.content_hash(content 或 "")；对 ctx.get("peers") 或 [] 中 node_id 不等于本节点且 ph=str(p.get("hash") or "") 或回落 NF.content_hash(p.get("content") or "") 后非空且等于 h 的 peer 计入 matched；matched 非空时返回一条 dup 命中（span=[0,len(body)]），否则返回 []。
def _loc_dup(node_id, meta, content, ctx):
    """同组同内容指纹（与 M1 `dup_hash_group` 同判据；D1 名 `dup`）。"""
    body = content if content is not None else ""
    h = str(meta.get("content_hash") or "").strip()
    if _blank(h):
        h = NF.content_hash(body)        # 索引无指纹 → 用正文实算（诚实标注来源）
    matched = []
    for p in ctx.get("peers") or []:
        if p.get("node_id") == node_id:
            continue
        ph = str(p.get("hash") or "") or NF.content_hash(p.get("content") or "")
        if ph and ph == h:
            matched.append(p)
    if not matched:
        return []
    span = [0, len(body)]
    return [_hit(node_id, "dup", "content_hash", span,
                 "与 %s 同内容指纹 %s（同类共 %d 条），整篇正文重复"
                 % (matched[0].get("node_id"), h, len(matched) + 1),
                 rule="dup_hash_group", peer=matched[0].get("node_id"),
                 snippet=_snippet(body, span))]


# 生效条件：对 ctx.get("peers") 或 [] 中每个非自身 peer，按 sentence_spans 对齐 content 与 peer content 的句子，当同一句位上去数字骨架相同（WL._skeleton(seg) 非空、长度 ≥ WL.MIN_SKELETON 且等于 peer 骨架）且 seg.strip() != ptext.strip() 的句子数达到 MIN_FLOW_SENTENCES 时，为这些句各返回一条 template_flow 命中；否则返回 []。
def _loc_template_flow(node_id, meta, content, ctx):
    """同模板流水：与同组节点逐句「去数字骨架相同、字面不同」→ 指向那些句。

    与 M1 `template_flow_digits_only` 同判据（都走 `writelimit._skeleton`），
    差别只在产物：M1 给一条条目级 issue，D1 给出**具体是哪几句**（span + 句索引）。
    单句偶合不算流水 → 需同组至少 `MIN_FLOW_SENTENCES` 句同时成立。
    """
    tgt = sentence_spans(content or "")
    hits = []
    for p in ctx.get("peers") or []:
        if p.get("node_id") == node_id:
            continue
        pseg = sentence_spans(p.get("content") or "")
        same = []
        for (i, s, e, seg) in tgt:
            if i >= len(pseg):
                break
            ptext = pseg[i][3]
            sk = WL._skeleton(seg)
            if not sk or len(sk) < WL.MIN_SKELETON or sk != WL._skeleton(ptext):
                continue
            if seg.strip() == ptext.strip():
                continue    # 字面全同属整篇重复（dup），不是「只换数字」的流水
            same.append((i, s, e, seg, sk))
        if len(same) < MIN_FLOW_SENTENCES:
            continue
        for (i, s, e, seg, sk) in same:
            hits.append(_hit(node_id, "template_flow", "content", [s, e],
                             "同模板流水（与 %s 第 %d 句去数字骨架相同、仅字面数值不同）：%s"
                             % (p.get("node_id"), i, sk[:40]),
                             rule="template_flow_digits_only", sentence=i,
                             peer=p.get("node_id"),
                             line=_line_of(ctx.get("text"), content, [s, e]),
                             snippet=seg.strip()[:SNIPPET_MAX]))
    return hits


# 生效条件：meta.get("content_hash") 非 _blank 且 content 非 None 且 h != NF.content_hash(content) 时，返回一条 hash_declared_vs_actual 的 contradiction 命中（cause 由 hash_mismatch_cause 依 meta/ctx.get("root")/ctx.get("path") 判）；ctx.get("fm") 或 {} 的 id 非 _blank 且 str(fm_id) != str(node_id) 时额外返回一条 id_declared_vs_index 命中；两者皆不成立返回 []。
def _loc_contradiction(node_id, meta, content, ctx):
    """**确定性**矛盾：声明与事实不符（指纹 / 标识）。

    语义级矛盾（正文自相矛盾）不在此处——那是 LLM 的活，D1 不猜（见 `SEMANTIC_ONLY`）。
    指纹不一致**必须带成因**（`cause`）：`index_lag`（快照滞后，属正常写路径现象，
    复核者无需修数据）与 `true_mismatch`（真不一致，需查）处置完全不同。
    """
    hits = []
    lines = key_line_spans(ctx.get("text") or "")
    h = str(meta.get("content_hash") or "").strip()
    if not _blank(h) and content is not None:
        actual = NF.content_hash(content)
        if h != actual:
            cause, note = hash_mismatch_cause(meta, root=ctx.get("root"),
                                              path=ctx.get("path"))
            hits.append(_hit(node_id, "contradiction", "content_hash", None,
                             "索引声明指纹 %s ≠ 正文实算 %s（%s）"
                             % (h, actual, note), rule="hash_declared_vs_actual",
                             cause=cause,
                             line=(lines.get("content_hash") or (None, None))[0]))
    fm_id = (ctx.get("fm") or {}).get("id")
    if not _blank(fm_id) and str(fm_id) != str(node_id):
        hits.append(_hit(node_id, "contradiction", "id", None,
                         "文件 frontmatter id=%s ≠ 索引键 %s" % (fm_id, node_id),
                         rule="id_declared_vs_index",
                         line=(lines.get("id") or (None, None))[0]))
    return hits


LOCATORS = {
    "missing_field": _loc_missing_field,
    "weak_source": _loc_weak_source,
    "stale": _loc_stale,
    "observation_aged": _loc_observation_aged,
    "dup": _loc_dup,
    "template_flow": _loc_template_flow,
    "contradiction": _loc_contradiction,
}

#: D1 **不定位**的判定：属语义层，交回 LLM 意见（不猜 = 不编造字符区间）
SEMANTIC_ONLY = {
    "contradiction_semantic": "正文自相矛盾属语义判定；D1 只做确定性矛盾"
                              "（索引指纹 / 标识与事实不符）",
}


# 生效条件：始终返回 SEMANTIC_ONLY 中以 str(kind or "").strip() 为键查得的值，缺键时返回空串（空串表示可定位）。
def blindspot_reason(kind) -> str:
    """D1 拒绝定位的类别 → 理由（空串表示可定位）。"""
    return SEMANTIC_ONLY.get(str(kind or "").strip(), "")


# ---------------------------- 主入口 ----------------------------

# 生效条件：items 中每项按 content=it.get("content") or ""、hash=str(it.get("hash") or "").strip() 或回落 NF.content_hash(content)、sk=WL.template_signature(content) or "" 预处理后，返回 {node_id: [同 hash 或同非空 sk 的其他 peer]}；items 为空/None 返回空 dict。
def build_peers(items) -> dict:
    """`[{node_id, content, hash?, …}]` → `{node_id: [peer, …]}`。

    只有**同内容指纹**或**同模板骨架**才互为对照——不是「同一批就是一组」。
    组的作用域由调用方给定（批 / 包），与 M1 机械层「组 = 同一个包」的口径一致。
    """
    prep = []
    for it in items or []:
        c = it.get("content") or ""
        prep.append({"node_id": it.get("node_id"), "content": c, "meta": it.get("meta"),
                     "text": it.get("text"), "fm": it.get("fm"),
                     "hash": str(it.get("hash") or "").strip() or NF.content_hash(c),
                     "sk": WL.template_signature(c) or ""})
    by_hash, by_sk = {}, {}
    for p in prep:
        by_hash.setdefault(p["hash"], []).append(p)
        if p["sk"]:
            by_sk.setdefault(p["sk"], []).append(p)
    out = {}
    for p in prep:
        grp = {q["node_id"]: q for q in by_hash.get(p["hash"], [])
               if q["node_id"] != p["node_id"]}
        for q in (by_sk.get(p["sk"], []) if p["sk"] else []):
            if q["node_id"] != p["node_id"]:
                grp.setdefault(q["node_id"], q)
        out[p["node_id"]] = list(grp.values())
    return out


# 生效条件：对 issue_hint（None/str/dict 或其 list/tuple）逐 hint 分类，返回 (kinds, fields, blind)：能 canonical_kind 到 ISSUE_KINDS 或 ADVISORY_KINDS 的入 kinds，blindspot_reason 非空的入 blind，其余非空 kind 与 field 入 fields；issue_hint 为 None 时 kinds/fields 为空集、blind 为空列表。
def _norm_hint(issue_hint):
    """issue_hint → `(kinds, fields, blindspot)`。

    形态：`None`（全量）｜str（issue_kind 或 field）｜dict（issue_kind/field）
    ｜上述的 list。
    """
    kinds, fields, blind = set(), set(), []
    hints = issue_hint if isinstance(issue_hint, (list, tuple)) else [issue_hint]
    for h in hints:
        if h is None:
            continue
        if isinstance(h, dict):
            s = h.get("issue_kind") or h.get("kind") or ""
            f = h.get("field")
        else:
            s, f = str(h).strip(), None
        if s:
            why = blindspot_reason(s)
            if why:
                blind.append("%s：%s" % (s, why))
            else:
                ck = canonical_kind(s)
                if ck in ISSUE_KINDS or ck in ADVISORY_KINDS:
                    kinds.add(ck)
                else:
                    fields.add(s)       # 不是类别 → 当作字段过滤
        if f:
            fields.add(str(f).strip())
    return kinds, fields, blind


# 生效条件：当 meta 与 content 均非 None 时不读盘；否则 root 为 None 抛 ValueError，经 load_node 读不到节点返回 {"hits": [], "blindspot": blind+["节点 %s 不在索引"%node_id], "load": None}；读到时补 meta/content/text/fm/path，按 kinds 非空时只跑 sorted(kinds)、否则 fields 非空或 issue_hint 为 None 时跑 sorted(ISSUE_KINDS)、否则 run=[] 执行 LOCATORS，对命中按 fields 过滤、补 line 并排序后返回 {"hits": hits, "blindspot": blind, "load": {...}}。
def locate_ex(node_id, issue_hint=None, *, meta=None, content=None, fm=None, text=None,
              root=None, index=None, peers=None, now=None, path=None,
              field_layers=None) -> dict:
    """D1 定位（完整返回）：`{"hits": [...], "blindspot": [...], "load": {...}}`。

    `meta`/`content` 显式给出则**不读盘**（纯函数用法——测试与批量复用都走这条）；
    否则 `root` 必填，经 `load_node` 从索引+文件取。返回的 hits 已按
    `(issue_kind, field, span起点, peer)` 排序，**确定性可复算**。

    `path`（节点文件绝对路径——供 `contradiction` 判成因）、`field_layers`
    （字段层门限，缺省 `field_layer_scope()`）可显式注入，便于纯函数测试。
    """
    kinds, fields, blind = _norm_hint(issue_hint)
    if meta is None or content is None:
        if root is None:
            raise ValueError("locate 需要 meta+content，或给出 root 以便读节点")
        nd = load_node(node_id, root, index=index)
        if nd is None:
            return {"hits": [], "blindspot": blind + ["节点 %s 不在索引" % node_id],
                    "load": None}
        if meta is None:
            meta = nd["meta"]
        if content is None:
            content = nd["content"]
        if text is None:
            text = nd["text"]
        if fm is None:
            fm = nd["fm"]
        if path is None:
            path = nd.get("path")
    meta = meta or {}
    ctx = {"fm": fm or {}, "text": text, "root": root, "index": index,
           "peers": peers or [], "now": time.time() if now is None else float(now),
           "path": path, "field_layers": field_layers}
    hits = []
    # 定位范围：显式类别 → 只跑该类；给出字段 → 全量再由字段收窄；
    # 无提示 → 全量。**提示全部落 blindspot 时范围为空**——不借机报别的类
    # （否则「给了语义提示」会顺手退回全量，与「不猜」纪律相悖）。
    if kinds:
        run = sorted(kinds)
    elif fields or issue_hint is None:
        run = sorted(ISSUE_KINDS)
    else:
        run = []
    for k in run:
        fn = LOCATORS.get(k)
        if fn is None:
            continue
        for h in fn(node_id, meta, content, ctx):
            if fields and h.get("field") not in fields:
                continue
            if h.get("line") is None and h.get("span") is not None:
                h["line"] = _line_of(text, content, h["span"])
            hits.append(h)
    hits.sort(key=lambda h: (h["issue_kind"], str(h.get("field") or ""),
                             -1 if h.get("span") is None else h["span"][0],
                             str(h.get("peer") or "")))
    return {"hits": hits, "blindspot": blind,
            "load": {"node_id": node_id, "meta": meta,
                     "content_len": len(content or "")}}


# 生效条件：给定 node_id（必填）与可选 issue_hint 及 kw 后，直接返回 locate_ex(node_id, issue_hint, **kw) 结果的 "hits" 列表。
def locate(node_id, issue_hint=None, **kw) -> list:
    """**D1 契约入口**：`locate(node_id, issue_hint) -> [{field, span, issue_kind, evidence}]`。"""
    return locate_ex(node_id, issue_hint, **kw)["hits"]


# 生效条件：给定 hits 与 key 后，返回 hits 中每个 h.get(key) 字符串化取值到出现次数的字典（键升序）；hits 为 None/空时返回空 dict。
def _counts(hits, key) -> dict:
    out = {}
    for h in hits or []:
        k = h.get(key)
        out[str(k)] = out.get(str(k), 0) + 1
    return dict(sorted(out.items()))


# 生效条件：items 显式给出时不读盘；items 为 None 时 root 为 None 抛 ValueError，否则按 node_ids 逐节点 load_node 组装 items（读不到的记入 missing）；随后对每个 item 调 locate_ex 汇总 hits 或 clean，并返回含 nodes/hits/by_kind/by_field/by_rule/clean/missing 的 dict。
def locate_many(node_ids=None, *, root=None, index=None, items=None,
                issue_hint=None, now=None) -> dict:
    """批量定位：**同一批内**互为对照（`dup` / `template_flow` 的组 = 本批）。

    `items` 显式给出 `[{node_id, content, meta?, text?, fm?, hash?}]` 则不再读盘。
    返回 `{nodes, hits, by_kind, by_field, clean, missing}`；`clean` 是**无命中**的节点、
    `missing` 是**读不到**的节点——两者分开报（「没问题」≠「没看」）。
    """
    missing = []
    if items is None:
        if root is None:
            raise ValueError("locate_many 需要 root（读盘）或 items（显式给出）")
        items = []
        for nid in node_ids or []:
            nd = load_node(nid, root, index=index)
            if nd is None:
                missing.append(nid)
                continue
            items.append({"node_id": nid, "content": nd["content"] or "",
                          "text": nd["text"], "fm": nd["fm"], "meta": nd["meta"],
                          "path": nd.get("path"),
                          "hash": nd["meta"].get("content_hash")})
    peers = build_peers(items)
    now = time.time() if now is None else float(now)
    hits, clean = [], []
    for it in items:
        nid = it["node_id"]
        ex = locate_ex(nid, issue_hint, meta=it.get("meta") or {},
                       content=it.get("content") or "", fm=it.get("fm"),
                       text=it.get("text"), peers=peers.get(nid) or [], now=now,
                       root=root, path=it.get("path"))
        if ex["hits"]:
            hits.extend(ex["hits"])
        else:
            clean.append(nid)
    hits.sort(key=lambda h: (str(h.get("node_id")), h["issue_kind"],
                             str(h.get("field") or ""),
                             -1 if h.get("span") is None else h["span"][0]))
    return {"nodes": len(items), "hits": hits, "by_kind": _counts(hits, "issue_kind"),
            "by_field": _counts(hits, "field"), "by_rule": _counts(hits, "rule"),
            "clean": clean, "missing": missing}


# 生效条件：从 pkg.get("entries") or [] 取条目并跳过 e.get("node_id") 为空者，root 非 None 时逐个 load_node 取正文，取不到时回落 e.get("excerpt") or ""，组装 items 调 locate_many 后返回其结果并附加 bundle_id 与 entries 数量；pkg 为 None 时 entries 为空列表。
def locate_package(pkg, *, root=None, index=None, issue_hint=None, now=None) -> dict:
    """M1 包 → 定位汇总（组的作用域 = 本包，与 M1 机械层同口径）。

    正文优先读盘（准确）；文件不可读时退回包内 `excerpt`（可能截断——宁可降级也不
    假装读到了全文，`missing` 会如实记下读不到的节点）。
    """
    entries = (pkg or {}).get("entries") or []
    items = []
    for e in entries:
        nid = e.get("node_id")
        if not nid:
            continue
        nd = load_node(nid, root, index=index) if root else None
        body = (nd or {}).get("content")
        items.append({"node_id": nid,
                      "content": body if body is not None else (e.get("excerpt") or ""),
                      "text": (nd or {}).get("text"), "fm": (nd or {}).get("fm"),
                      "meta": (nd or {}).get("meta") or e,
                      "path": (nd or {}).get("path") or e.get("path"),
                      "hash": ((nd or {}).get("meta") or {}).get("content_hash")
                              or e.get("content_hash")})
    out = locate_many(items=items, issue_hint=issue_hint, now=now)
    out["bundle_id"] = (pkg or {}).get("bundle_id")
    out["entries"] = len(entries)
    return out


# 生效条件：给定 hits 后返回 total=len(hits or [])、去重 node_id 数、排序后的 node_ids、以及 by_kind/by_field/by_rule 计数；hits 为 None/空时 total=0、nodes=0、node_ids=[]。
def summary(hits) -> dict:
    """命中汇总（审计留痕用）。"""
    nodes = sorted({str(h.get("node_id")) for h in hits or []})
    return {"total": len(hits or []), "nodes": len(nodes), "node_ids": nodes,
            "by_kind": _counts(hits, "issue_kind"), "by_field": _counts(hits, "field"),
            "by_rule": _counts(hits, "rule")}


# 生效条件：给定 hits 后逐条生成 Markdown 行并返回表头加各行：field/line/snippet 取 h.get(...) or "—"（假值回落 "—"），span 为 None 时显示 "—" 否则 "起-止"，evidence 取 (h.get("evidence") or "").replace("|","\\|")（假值回落空串）。
def markdown_table(hits) -> str:
    """人工核对清单：每行一条命中，末列留空供核对者填判定（D1 验收抽样用）。"""
    head = ("| # | node_id | issue_kind | field | span | line | 片段 | evidence | 人工判定 |\n"
            "|---|---|---|---|---|---|---|---|---|\n")
    rows = []
    for i, h in enumerate(hits or [], 1):
        sp = "—" if h.get("span") is None else "%d-%d" % (h["span"][0], h["span"][1])
        rows.append("| %d | %s | %s | %s | %s | %s | %s | %s |  |"
                    % (i, h.get("node_id"), h.get("issue_kind"), h.get("field") or "—",
                       sp, h.get("line") or "—",
                       (h.get("snippet") or "—").replace("|", "\\|"),
                       (h.get("evidence") or "").replace("|", "\\|")))
    return head + "\n".join(rows)


# 生效条件：解析 argv（缺省 sys.argv）后，--root 为假值（含默认 os.environ.get("MDCG_ROOT") 为 None 或空串）时打印提示并返回 2；--node 追加列表为空时打印提示并返回 2；否则以 --root 与 --node 调 locate_many，并按 --json 或 --markdown 输出后返回 0，两者皆无则逐行打印命中与汇总后返回 0。
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m md_cg.mreview.locate",
                                 description="记忆评审 M3 · D1 字段级定位")
    ap.add_argument("--root", default=os.environ.get("MDCG_ROOT"),
                    help="真源根（缺省读环境变量 MDCG_ROOT）")
    ap.add_argument("--node", action="append", default=[],
                    help="节点 id（可多次；同一批内互为对照）")
    ap.add_argument("--kind", action="append", default=[], help="只定位该类问题")
    ap.add_argument("--field", action="append", default=[], help="只保留该字段的命中")
    ap.add_argument("--json", action="store_true", help="输出 JSON（缺省人读表）")
    ap.add_argument("--markdown", action="store_true", help="输出人工核对清单")
    a = ap.parse_args(argv)
    if not a.root:
        print("需要 --root 或环境变量 MDCG_ROOT", file=sys.stderr)
        return 2
    if not a.node:
        print("需要 --node <id>（可多次）", file=sys.stderr)
        return 2
    rep = locate_many(a.node, root=a.root,
                      issue_hint=(list(a.kind) + list(a.field)) or None)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0
    if a.markdown:
        print(markdown_table(rep["hits"]))
        return 0
    for h in rep["hits"]:
        print("%-14s %-20s %-14s %s" % (h["node_id"], h["field"], h["issue_kind"],
                                        h["evidence"]))
    print("-- 命中 %d 条｜干净 %d 条｜缺项 %d 条"
          % (len(rep["hits"]), len(rep["clean"]), len(rep["missing"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
