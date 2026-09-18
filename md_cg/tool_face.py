# -*- coding: utf-8 -*-
"""工具面渐进披露（pi ① 上下文经济学 · 灵枢落地）。

【为什么】
MCP 工具的 op 参数空间全量 schema 常驻调用方上下文：kernel 暴露面（cg+stg）
达 ~20k 字符，其中 cg 一个工具就有 169 个参数——绝大多数是「长尾 op 专属参数的
解释文字」，只在少数场景才需要，却每次会话都要付费注入。

pi 的做法（`system-prompt.ts:82-84` 工具只以一行 snippet 常驻系统提示，完整描述
只进 API tools 字段；`skills.ts:355-383` 索引常驻、正文按需 read）证明：
**常驻面只需「我知道它存在、且知道怎么问」**，完整语义按需取回即可。

【怎么做 · 信息零丢失】
本模块**不改 schema 真源**（`mcp_server.KERNEL_TOOLS` / `TOOLS` 仍是完整定义），
只做运行时**投影**：
  · 工具 description → `TOOL_BRIEFS` 一行职责（缺省回退首句）；
  · 参数 description → 短提示：通用参数保留首段（≤30 字符）、op 专属参数压到
    ≤16 字符，枚举型参数保留**完整值集**（值集是调用契约，不可省）；
  · 顺带剔除 `_req`（`_p()` 写的内部标记，本不该出现在对外 schema）。
被投影掉的原文既不复制也不搬运——`cg(op=help, query=…)` 直接从真源渲染，
故不存在第二真源、无漂移面，信息守恒是结构性的而非靠人工维护。

【守卫】`md_cg/test_tool_face.py` 机械断言：注入面 ≥50% 削减 + 工具名/参数名/
required/类型/枚举值集逐位不变 + 每个被投影掉的参数描述都能由 op=help 无损取回。

【关闭】`MDCG_TOOL_FACE=full` 返回完整真源（调试/兼容）。
"""
from __future__ import annotations

import os
import re

FULL_ENV = "MDCG_TOOL_FACE"

# --------------------------------------------------------------------------
# 一行职责（唯一手写面：必须由人写，不能机械生成）
# --------------------------------------------------------------------------
CG_HELP_HINT = '完整 op/参数语义：cg(op="help", query="<op 名 | 参数名 | 工具名>")'

TOOL_BRIEFS = {
    "cg": "灵枢认知图唯一入口（32 op：写/读/审/护/演化/元认知/预测/白箱…）。" + CG_HELP_HINT,
    "stg": "语义时空图 4 op：relation|timeline|anchors|consistency。" + CG_HELP_HINT,
    "mdcg_remember": "写入记忆节点（gated=true 走主动遗忘闸门；正文建议含 CCG 五要素）。",
    "mdcg_recall": "按 token 预算召回记忆包（RRF 多路融合，可开模糊/条件语义路与查询扩展）。",
    "mdcg_search": "精确检索（T0–T3 阶梯 + 四态资格判定）。",
    "mdcg_get": "按 id 读取单个节点（frontmatter + content）。",
    "mdcg_reflect": "记录信息差 D(t,C) 与二阶 d²D/dt²（写 _reflection.jsonl）。",
    "mdcg_verify": "节点外部裁决 confirmed/weakened/falsified（falsified 入负记忆）。",
    "mdcg_flywheel": "误差（预期 vs 实际）转为 unresolved 条目，驱动补条件。",
    "mdcg_mine_fix_pairs": "从行为日志挖掘「错误→修复」对（产修复知识 + 负记忆）。",
    "mdcg_rejected": "写入负记忆（被证伪假设），同内容幂等。",
    "mdcg_unresolved": "写入未解问题（驱动主动探索）。",
    "mdcg_propose": "候选记忆入审核队列（海马体 inbox）。",
    "mdcg_review_list": "列出待审核候选（红队打回者带 needs_reapproval）。",
    "mdcg_review_decide": "审核裁决 accept|reject|edit|merge（redteam 打回需再审批）。",
    "mdcg_review_records": "裁决记录审计（可复核 record_hash 一致性）。",
    "mdcg_forget": "软删除（tombstone → trash/，受保护节点需 override）。",
    "mdcg_protect": "写保护：stats|check|mark|snapshot|history|forgetting（mark 需 admin）。",
    "mdcg_forgetting_history": "主动遗忘裁决留痕（四态 + 三问判据）。",
    "mdcg_identity": "身份特征识别（self/user/role/agent 的锚点、位置效应、条件特征）。",
    "mdcg_consistency": "节点间冲突检测（L0 情绪 → L1 反思 → L2 递归反思；可投飞轮）。",
    "mdcg_metacognition": "独立元认知（情绪/校准/盲区/信任四面；只读留痕）。",
    "mdcg_self_state": "自我状态层（薄自我 + 富索引：状态卡单例 + 关系节点）。",
    "mdcg_predict": "生成式预测（候选未来；过滤门 + 四维评分 + 命中反馈校准）。",
    "mdcg_causal": "因果推理（causal 边 = 条件依赖；path|gate|chain|explain）。",
    "mdcg_evolution": "演化账本（每次修改 = 补一条缺失条件；可 rollback 留痕）。",
    "mdcg_restore": "恢复被 forget 的节点（在删除清单中且未 force 则拒绝）。",
    "mdcg_health": "健康度（分桶健康 + CCG 完整度 + 验证基底覆盖 + OS 指标）。",
    "mdcg_whoami": "身份与权限（tenant/actor/clearance/可见节点/可读密级）。",
    "mdcg_ingest": "设备驱动：从会话文件增量摄取事件（fix-pair 挖掘 + watermark 去重）。",
    "mdcg_watermarks": "各事件源的摄取水位（增量摄取状态，可审计）。",
    "mdcg_whitebox": "白箱能力库调用与能力验证（ask|remember|verify_*|ping|report）。",
    "mdcg_service_info": "服务信息（身份/版本/根目录/节点统计/工具数/权限）。",
}

# --------------------------------------------------------------------------
# 投影规则
# --------------------------------------------------------------------------
_ENUM_RE = re.compile(r"[A-Za-z_][\w\-]*(?:\|[A-Za-z_][\w\-]*)+")
_OP_SEC_RE = re.compile(r"op=([a-z_]+)：(.+?)(?=op=[a-z_]+：|$)", re.S)

GENERIC_LIMIT = 24      # 通用参数（k/limit/tags/importance…）保留首段长度
OP_SPECIFIC_LIMIT = 12  # op 专属参数（长尾）压缩长度；超此长度整体外置
ENUM_PLACEHOLDER = "取值随 op 变化，完整枚举见 op=help"

# 高频参数：无论描述是否带 op 前缀，都按「通用」处理（保留短提示）
# ——这些是每次调用都可能要传的旋钮，让 agent 靠 schema 就能用起来。
GENERIC_PARAMS = frozenset({
    "op", "action", "query", "content", "node_id", "k", "limit", "intent",
    "tags", "importance", "layer", "pid", "reason", "force", "dry_run",
    "session", "note", "evidence", "verdict", "decision", "content_kind",
    "budget_tokens", "text", "path", "role", "subject",
})


# 生效条件：desc 为 None/空串等假值时按 `desc or ""` 回落空串、`_OP_SEC_RE.finditer` 无匹配而返回空 dict；否则以每个匹配的组 1 为键、组 2 去首尾空白并去掉结尾「；/;」后为值填入并返回。
def op_sections(desc):
    """从工具 description 里切出 {op: 段落}（机械切分，无损）。"""
    out = {}
    for m in _OP_SEC_RE.finditer(desc or ""):
        out[m.group(1)] = m.group(2).strip().rstrip("；;")
    return out


# 生效条件：tools 为空时可迭代但无元素、返回空 set；否则遍历每个工具，并入其 `t.get("description") or ""` 经 op_sections 得到的键，以及其 `(t.get("inputSchema") or {}).get("properties") or {}` 中名为 op/action 的属性 description（缺省 ""）里 `_ENUM_RE` 匹配串按 "|" 拆出的词，返回并集 vocab。
def op_vocab(tools):
    """全量 op 词汇表（用于判定「这是 op 专属参数的描述」）。"""
    vocab = set()
    for t in tools:
        vocab |= set(op_sections(t.get("description") or ""))
        props = (t.get("inputSchema") or {}).get("properties") or {}
        for key, spec in props.items():
            if key in ("op", "action"):
                d = spec.get("description") or ""
                for m in _ENUM_RE.finditer(d):
                    vocab |= set(m.group(0).split("|"))
    return vocab


# 生效条件：head=(desc or "")[:prefix_len]（desc 假值即空串、prefix_len 默认 18），当 vocab 中存在长度 ≥3 且作为子串出现在 head 中的元素时返回 True，否则（含 vocab 为空）返回 False。
def _is_op_specific(desc, vocab, prefix_len=18):
    head = (desc or "")[:prefix_len]
    return any(len(o) >= 3 and o in head for o in vocab)


def short_desc(desc, vocab, op_specific=False):
    """投影一条参数描述。

    返回 None 表示「整体外置」——该参数（长尾 op 专属）的描述不进常驻面，
    由 ``cg(op=help, query="<参数名>")`` 按需取回。
    """
    if not desc:
        return None
    d = " ".join(str(desc).split())
    groups = _ENUM_RE.findall(d)
    if len(groups) == 1:
        return groups[0]
    if len(groups) > 1:
        return ENUM_PLACEHOLDER
    if op_specific:
        # 长尾参数：短的原样留（信息本就少），长的一句话整体外置。
        return d if len(d) <= OP_SPECIFIC_LIMIT else None
    if len(d) > GENERIC_LIMIT:
        return d[:GENERIC_LIMIT].rstrip() + "…"
    return d


# 生效条件：tool 的 "inputSchema" 键存在且值为真时原样返回该值；键缺失或值为 None/{} 等假值时按 `or {}` 回落返回空 dict。
def _schema_of(tool):
    return tool.get("inputSchema") or {}


# 生效条件：tool 须含 "name" 键（缺失即 KeyError），desc=`tool.get("description") or ""`、isch=`_schema_of(tool)`；逐条属性去掉 "_req" 键后，若其 description 为真则按「key 在 GENERIC_PARAMS 或 `not _is_op_specific(d, vocab)`」判为 generic，再经 short_desc 投影——非空则替换 description、空则弹出该 description 键；返回 name 与 `TOOL_BRIEFS.get(name) or _first_sentence(desc,140)` 的 description，inputSchema 的 type 取 `isch.get("type") or "object"`，仅当 required 非空时才带 "required"。
def slim_tool(tool, vocab):
    """投影单个工具（不修改入参）。"""
    name = tool["name"]
    desc = tool.get("description") or ""
    isch = _schema_of(tool)
    req = list(isch.get("required") or [])
    props = isch.get("properties") or {}
    new_props = {}
    for key, spec in props.items():
        clean = {k: v for k, v in spec.items() if k != "_req"}
        d = clean.get("description")
        if d:
            generic = key in GENERIC_PARAMS or not _is_op_specific(d, vocab)
            short = short_desc(d, vocab, op_specific=not generic)
            if short:
                clean["description"] = short
            else:
                clean.pop("description", None)
        new_props[key] = clean
    out_schema = {"type": isch.get("type") or "object", "properties": new_props}
    if req:
        out_schema["required"] = req
    return {"name": name, "description": TOOL_BRIEFS.get(name) or _first_sentence(desc, 140),
            "inputSchema": out_schema}


# 生效条件：d=折叠 (desc or "") 空白，按 "。"、"；"、";" 顺序取各字符在 d 中 `find` 的首次出现位置 i，遇到首个满足 0<i<=limit 者即返回 d[:i+1]；三个字符的首次位置均不满足时，len(d)>limit 返回 d[:limit].rstrip()+"…"，否则原样返回 d（limit=0 时无 i 满足，d 非空则返回 "…"）。
def _first_sentence(desc, limit):
    d = " ".join((desc or "").split())
    for ch in ("。", "；", ";"):
        i = d.find(ch)
        if 0 < i <= limit:
            return d[:i + 1]
    return (d[:limit].rstrip() + "…") if len(d) > limit else d


# 生效条件：环境变量 FULL_ENV 取值 `(os.environ.get(FULL_ENV) or "").strip().lower()=="full"`（未设或设为空串均不成立）时原样返回入参 tools；否则以 tools 算出 vocab 并返回 `[slim_tool(t, vocab) for t in tools]`（tools 为空则返回空列表）。
def slim_tools(tools):
    """投影整个工具面。MDCG_TOOL_FACE=full 时原样返回（调试/兼容）。"""
    if (os.environ.get(FULL_ENV) or "").strip().lower() == "full":
        return tools
    vocab = op_vocab(tools)
    return [slim_tool(t, vocab) for t in tools]


# --------------------------------------------------------------------------
# 按需披露：cg(op=help, query=…)
# --------------------------------------------------------------------------
# 生效条件：取 `_schema_of(tool)` 的 properties，仅保留 description（缺省 ""）满足 `_is_op_specific(desc, {op})` 的属性，每项记为 name/type/required(k in required)/desc，返回该列表的 `out[:limit]` 切片（limit 默认 40，limit=0 得空列表，负值从尾部削减）。
def _params_for(tool, op, limit=40):
    isch = _schema_of(tool)
    props = isch.get("properties") or {}
    req = set(isch.get("required") or [])
    vocab = {op}
    out = [{"name": k, "type": v.get("type"), "required": k in req,
            "desc": v.get("description") or ""}
           for k, v in props.items()
           if _is_op_specific(v.get("description") or "", vocab)]
    return out[:limit]


# 生效条件：tools 用于建 `by_name={t["name"]: t}`（某工具缺 "name" 即 KeyError），q=(query or "").strip()——q 为空串返回 {"ok":True,"tool_index":[每工具 name 与 `TOOL_BRIEFS.get(name) or _first_sentence(desc,120)`],"usage":...}；q 等于某工具名时返回该工具的 description/ops（op_sections 键排序）/params/required；否则逐工具收集「q 出现在 op 段落键中」与「pname==q 或 len(q)>=4 且 pname 以 q 开头」两类命中（不互斥、可同时追加），全部工具遍历后无命中返回 {"ok":False,"error",...,"hint",...}，有命中返回 {"ok":True,"query":q,"hits":hits[:max(1, limit)]}（limit≤1 时按 1 条截取）。
def help_text(tools, query=None, limit=40):
    """从**完整真源**按需渲染说明——被投影掉的原文在此无损取回。"""
    q = (query or "").strip()
    by_name = {t["name"]: t for t in tools}
    if not q:
        return {"ok": True,
                "tool_index": [{"name": t["name"],
                                "brief": TOOL_BRIEFS.get(t["name"])
                                or _first_sentence(t.get("description") or "", 120)}
                               for t in tools],
                "usage": 'query 取 op 名 / 参数名 / 工具名，例如 '
                         'cg(op="help", query="write")'}
    if q in by_name:
        t = by_name[q]
        isch = _schema_of(t)
        props = isch.get("properties") or {}
        req = list(isch.get("required") or [])
        return {"ok": True, "tool": t["name"],
                "description": t.get("description") or "",
                "ops": sorted(op_sections(t.get("description") or "")),
                "params": [{"name": k, "type": v.get("type"),
                            "required": k in req,
                            "desc": v.get("description") or ""}
                           for k, v in props.items()],
                "required": req}
    hits = []
    for t in tools:
        isch = _schema_of(t)
        props = isch.get("properties") or {}
        req = set(isch.get("required") or [])
        secs = op_sections(t.get("description") or "")
        if q in secs:
            hits.append({"tool": t["name"], "op": q, "doc": secs[q],
                         "params": _params_for(t, q, limit)})
        # 不短路：op 名与参数名同名时（如 goal/ref/consistency），两者都要能取回。
        for pname, spec in props.items():
            if pname == q or (len(q) >= 4 and pname.startswith(q)):
                hits.append({"tool": t["name"], "param": pname,
                             "type": spec.get("type"), "required": pname in req,
                             "desc": spec.get("description") or ""})
    if not hits:
        return {"ok": False, "error": f"未找到 op / 参数 / 工具：{q}",
                "hint": "cg(op=help) 不带 query 可列出全部工具与一行职责"}
    return {"ok": True, "query": q, "hits": hits[:max(1, limit)]}