# -*- coding: utf-8 -*-
"""md_cg · MCP server（记忆操作系统对外接口）

把 MdCGOS（认知图 + 记忆 OS 七项能力）暴露为标准 MCP 服务：
  · 传输：stdio（逐行 JSON-RPC 2.0，UTF-8）
  · 协议：2024-11-05
  · 零第三方依赖（D-005）

启动：
    MDCG_ROOT=<认知图目录> MDCG_ACTOR=<调用方> python -m md_cg.mcp_server

DSH 侧配置（cordis.yml / MCP client）：
    command: python
    args: ["-m", "md_cg.mcp_server"]
    env: { MDCG_ROOT: "...", PYTHONPATH: ".../dsh-memory" }

工具面（21 个细粒度工具 + 2 个基元 cg/stg）：
  写：mdcg_remember / mdcg_rejected / mdcg_unresolved / mdcg_propose
  目标/近期：cg(op=goal) 目标槽 / cg(op=recent) 近期事件窗口
  读：mdcg_get / mdcg_search / mdcg_recall / mdcg_review_list /
      mdcg_review_records
  认知：mdcg_reflect / mdcg_verify / mdcg_flywheel / mdcg_mine_fix_pairs
  生命周期：mdcg_forget / mdcg_restore / mdcg_review_decide
  运维：mdcg_health / mdcg_whoami / mdcg_ingest / mdcg_watermarks /
      mdcg_service_info
"""
from __future__ import annotations

import json
import os
import sys

SERVER_NAME = "mdcg-mcp"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"


# --------------------------------------------------------------------------
# 工具定义
# --------------------------------------------------------------------------

def _s(_desc, **props):
    return {"type": "object", "properties": props, "required":
            [k for k, v in props.items() if v.get("_req")]}


def _p(t, desc, req=False):
    d = {"type": t, "description": desc}
    if req:
        d["_req"] = True
    return d


def _make_query_expand(exp):
    """把调用方（LLM/多智能体）提供的扩展词包装成 query_expand 注入函数。

    黑箱只在**查询时刻**：调用方给出 {term,weight}，索引侧仍是白箱词表匹配。
    返回的函数与 md_cg.mdcg.expand_query_terms_weighted 同构，并在 __source__ 标注 llm。
    """
    if not exp:
        return None
    from .mdcg import expand_query_terms_weighted

    def _expand(q, _exp=exp):
        out = expand_query_terms_weighted(q)
        for it in _exp:
            if isinstance(it, dict):
                term = str(it.get("term") or "").strip()
                try:
                    w = float(it.get("weight", 0.5))
                except (TypeError, ValueError):
                    w = 0.5
            else:
                term, w = str(it).strip(), 0.5
            if term:
                out[term] = max(out.get(term, 0.0), max(0.0, min(1.0, w)))
        out["__source__"] = "llm"
        return out

    return _expand


TOOLS = [
    {
        "name": "mdcg_remember",
        "description": "写入一条记忆节点（md 认知图）。content 建议含 CCG 5 要素注释"
                       "（# 功能名/# 生效条件/# 子功能/# 执行/# 验证方式/# 不适用条件）。",
        "inputSchema": _s("", node_id=_p("string", "节点 id（省略则自动生成）"),
                          content=_p("string", "节点内容", True),
                          layer=_p("string", "层：anchor|structural|knowledge|contextual|self"),
                          role=_p("string", "角色：knowledge|user|assistant|tool-output|command|edit"),
                          tags=_p("array", "标签"), importance=_p("number", "重要性 0-1"),
                          condition_space=_p("object", "条件空间"),
                          verification_basis=_p("string", "验证基底"),
                          non_applicable_conditions=_p("array", "不适用条件")),
    },
    {
        "name": "mdcg_recall",
        "description": "按 token 预算召回记忆包（RRF 多路融合，超大条目跳过而非停下）。"
                       "会话开始或重要工作前调用。可选启用第 5 路模糊召回（分级隶属度）"
                       "与第 6 路条件语义路（条件结构驱动），并注入调用方 LLM 的查询"
                       "扩展词（索引侧始终白箱）。",
        "inputSchema": _s("", query=_p("string", "描述当前任务的查询", True),
                          budget_tokens=_p("integer", "token 预算（默认 1200）"),
                          k=_p("integer", "候选上限"), context=_p("object", "当前情境条件空间"),
                          include_work=_p("boolean", "是否含工具输出/命令/编辑（默认否）"),
                          fuzzy=_p("boolean", "启用第 5 路模糊召回（分级隶属度，默认否）"),
                         semantic=_p("boolean", "启用第 6 路条件空间结构化匹配"
                                               "（白箱语义路：CCG 生效条件 + condition_space "
                                               "四槽，不适用条件命中即剔除；默认否）"),
                          expand=_p("array", "LLM 查询侧扩展词：[{term,weight}] 或 [\"词\"]；"
                                             "仅在查询时刻生效，索引侧仍白箱"),
                          goal=_p("string", "当前目标（第 5 篇第 3 章）：启用 goal 路给召回定向；"
                                            "省略则自动取活跃目标"),
                          goal_path=_p("boolean", "启用目标定向路（默认否；给 goal 即自动启用）"),
                          include_recent=_p("boolean", "是否附「近期事件」窗口（默认否）"),
                          recent_limit=_p("integer", "近期事件条数（默认 10）"),
                          fusion=_p("string", "融合模式：sum（经典 RRF，奖励多路共识）"
                                              "| max（取各路最高贡献，不奖励共识）。"
                                              "fuzzy=true 时缺省 max——实测 sum 会低估"
                                              "「只有模糊路捞到」的目标，self@1 −10.1%")),
    },
    {
        "name": "mdcg_search",
        "description": "精确检索（T0–T3 阶梯 + 四态资格判定）。返回 score/state/tier。",
        "inputSchema": _s("", query=_p("string", "查询", True), k=_p("integer", "条数"),
                          layer=_p("string", "限定层"), context=_p("object", "情境"),
                          roles=_p("array", "限定角色"), include_work=_p("boolean", "含工作角色")),
    },
    {
        "name": "mdcg_get",
        "description": "按 id 读取一个记忆节点（frontmatter + content）。",
        "inputSchema": _s("", node_id=_p("string", "节点 id", True)),
    },
    {
        "name": "mdcg_reflect",
        "description": "反思单元：记录本次查询的信息差 D(t,C) 与二阶 d²D/dt²，写 _reflection.jsonl。",
        "inputSchema": _s("", query=_p("string", "查询", True), k=_p("integer", "取前 k 条"),
                          feedback=_p("string", "用户反馈（可选）")),
    },
    {
        "name": "mdcg_verify",
        "description": "验证单元：对节点做外部裁决 confirmed/weakened/falsified"
                       "（falsified 会移入 rejected/ 负记忆）。",
        "inputSchema": _s("", node_id=_p("string", "节点 id", True),
                          evidence=_p("string", "证据", True),
                          verdict=_p("string", "confirmed|weakened|falsified", True)),
    },
    {
        "name": "mdcg_flywheel",
        "description": "知识飞轮：把一次误差（预期状态 vs 实际状态）转为 unresolved 条目，驱动补条件。",
        "inputSchema": _s("", error_report=_p("object", "错误报告 {query,expected_state,actual_state,missing}", True)),
    },
    {
        "name": "mdcg_mine_fix_pairs",
        "description": "从行为日志自动挖掘「错误→修复」对：产出可路由修复知识 + rejected 负记忆。",
        "inputSchema": _s("", events=_p("array", "事件列表 [{role,text}] 或 [{error,fix}]", True)),
    },
    {
        "name": "mdcg_rejected",
        "description": "写入负记忆（被证伪的假设），防重复踩坑；同内容幂等。",
        "inputSchema": _s("", hypothesis=_p("string", "假设", True), reason=_p("string", "否决原因", True),
                          verification_basis=_p("string", "验证基底"), tags=_p("array", "标签")),
    },
    {
        "name": "mdcg_unresolved",
        "description": "写入未解问题（驱动主动探索）。",
        "inputSchema": _s("", question=_p("string", "问题", True), known_clues=_p("string", "已知线索"),
                          goal=_p("string", "目标")),
    },
    {
        "name": "mdcg_propose",
        "description": "把一个候选记忆放入审核队列（海马体 inbox），等待 review_decide。",
        "inputSchema": _s("", node_id=_p("string", "节点 id", True), content=_p("string", "内容", True),
                          layer=_p("string", "层"), tags=_p("array", "标签"),
                          condition_space=_p("object", "条件空间"),
                          verify=_p("object", "验收判据（内联声明，裁决阶段只读）")),
    },
    {
        "name": "mdcg_review_list",
        "description": "列出待审核候选；被红队打回待再审批的条目带 status=needs_reapproval。",
        "inputSchema": _s(""),
    },
    {
        "name": "mdcg_review_decide",
        "description": "审核裁决：accept / reject / edit / merge（merge 需 merge_into）。"
                       "redteam.verdict=reject 不落库，转 needs_reapproval，"
                       "修复后须带递增 round 的 pass 再审批；判据只读不可改。",
        "inputSchema": _s("", pid=_p("string", "提案 id", True),
                          decision=_p("string", "accept|reject|edit|merge", True),
                          edits=_p("object", "edit 时的覆盖字段"), merge_into=_p("string", "merge 目标节点 id"),
                          reason=_p("string", "裁决理由"),
                          redteam=_p("object", "红队裁决 {verdict:pass|reject, issues:[], round:n}"),
                          issues=_p("array", "问题清单（打回理由）")),
    },
    {
        "name": "mdcg_review_records",
        "description": "裁决记录审计：列出 md 审计节点（self 层，供其他来源审计）；"
                       "给 node_id 则复核该记录的 record_hash 与 "
                       "hippocampus/decisions.jsonl 是否一致。",
        "inputSchema": _s("", pid=_p("string", "只看某提案的记录"),
                          node_id=_p("string", "复核该审计节点 id")),
    },
    {
        "name": "mdcg_forget",
        "description": "软删除（tombstone）：节点移入 trash/ 并写入删除清单，可审计。",
        "inputSchema": _s("", node_id=_p("string", "节点 id", True), reason=_p("string", "原因")),
    },
    {
        "name": "mdcg_restore",
        "description": "恢复被 forget 的节点；若在删除清单中且未 force 则拒绝（恢复时删除检查）。",
        "inputSchema": _s("", node_id=_p("string", "节点 id", True), force=_p("boolean", "强制恢复")),
    },
    {
        "name": "mdcg_health",
        "description": "健康度：分桶健康 + CCG 完整度 + 验证基底覆盖率 + OS 指标（审核/墓碑/审计）。",
        "inputSchema": _s(""),
    },
    {
        "name": "mdcg_whoami",
        "description": "身份与权限：tenant / actor / clearance / 可见节点数 / 可读密级列表。",
        "inputSchema": _s(""),
    },
    {
        "name": "mdcg_ingest",
        "description": "设备驱动：从会话文件增量摄取事件（自动 fix-pair 挖掘 + watermark 去重）。"
                       "source=auto 时自动发现本机 DSH 会话。",
        "inputSchema": _s("", source=_p("string", "会话文件路径，或 'auto' 自动发现 DSH 会话"),
                          max_events=_p("integer", "单次最多摄取事件数"),
                          mine_fix_pairs=_p("boolean", "是否自动挖掘错误→修复对（默认是）"),
                          dry_run=_p("boolean", "只统计不写入")),
    },
    {
        "name": "mdcg_watermarks",
        "description": "各事件源的摄取水位（增量摄取状态，可审计）。",
        "inputSchema": _s(""),
    },
    {
        "name": "mdcg_service_info",
        "description": "服务信息（信任透明度）：身份/版本/根目录/节点统计/工具数/权限。",
        "inputSchema": _s(""),
    },
]


# --------------------------------------------------------------------------
# 基元接口（kernel 暴露面）
#
# 架构决定（2026-09-09）：对外只暴露 2 个认知基元，其余细粒度工具下沉为
# 本地函数（MDCG_MCP_SURFACE=full 时仍可见，供兼容与调试）。
# 认知图只给「知识与建议能力名」，不执行——执行权归调用方。
# --------------------------------------------------------------------------

KERNEL_TOOLS = [
    {
        "name": "cg",
        "description": "认知图接口（唯一入口）。op=route：按情境条件路由，返回相关知识 + "
                       "建议能力名（不执行，由调用方决定）；op=read：召回/检索/按 id 取；"
                       "op=write：写入前按 content_kind 审核（ACCEPT 落盘 / REJECT 进负记忆 / "
                       "DEFER 进审核队列）；op=verify：外部裁决回填；op=review：审核队列；"
                       "op=forget：软删除/恢复；op=goal：目标槽（第 5 篇七件套之「目标」，"
                       "action=add|list|status；目标不进召回，只给 read 定向）；"
                       "op=recent：近期事件窗口（七件套之「近期事件」，"
                       "action=add|list|clear，滚动保留最近 N 条）；"
                       "op=info：身份+健康+审核体系自描述；"
                       "op=index_code：按目录（大域）索引代码，只存注释/接口，"
                       "code_ref 指回源文件，不复制完整代码。",
        "inputSchema": _s("",
            op=_p("string", "route|read|write|verify|review|forget|goal|recent|info|index_code", True),
            intent=_p("string", "route 的查询意图"), query=_p("string", "read 的查询"),
            goal=_p("string", "goal op 的目标文本；read 的定向目标（缺省用活跃目标）"),
            goal_status=_p("string", "goal op：active|done|dropped"),
            priority=_p("number", "goal op：优先级 0-1（兼作定向偏置依据）"),
            deadline=_p("string", "goal op：截止时间（仅排序用，不做硬约束）"),
            conditions=_p("string", "goal op：生效条件"),
            action_hint=_p("string", "goal op：执行说明（写入 CCG 的「执行」栏）"),
            text=_p("string", "recent op 的事件文本"),
            role=_p("string", "recent op 的事件角色：user|assistant|tool-output|command"),
            meta=_p("object", "recent op：附加元数据"),
            window=_p("integer", "recent op：滚动窗口大小（默认 200）"),
            include_recent=_p("boolean", "read：是否附近期事件窗口（默认否）"),
            limit=_p("integer", "goal/recent 的返回条数；read 的近期事件条数"),
            node_id=_p("string", "节点 id"),
            content=_p("string", "write 的内容（建议含 CCG 5 要素注释）"),
            content_kind=_p("string", "write 的内容类型：code|image_desc|text|permission|work_done|work_wip"),
            layer=_p("string", "层：anchor|structural|knowledge|contextual|self"),
            tags=_p("array", "标签（cap:xxx 会作为 route 的建议能力名）"),
            importance=_p("number", "重要性 0-1"),
            condition_space=_p("object", "条件空间"),
            verification_basis=_p("string", "验证基底"),
            non_applicable_conditions=_p("array", "不适用条件"),
            context=_p("object", "当前情境"),
            k=_p("integer", "返回条数"), budget_tokens=_p("integer", "read 的 token 预算"),
            evidence=_p("string", "verify 的证据"),
            verdict=_p("string", "verify 裁决：confirmed|weakened|falsified"),
            action=_p("string", "review: list|decide|rounds；forget: forget|restore；"
                                "goal: add|list|status；recent: add|list|clear"),
            pid=_p("string", "review decide 的提案 id"),
            decision=_p("string", "review 裁决：accept|reject|edit|merge"),
            edits=_p("object", "review edit 的覆盖字段（不可含 verify）"),
            merge_into=_p("string", "review merge 的目标节点 id"),
            redteam=_p("object", "红队裁决 {verdict:pass|reject, issues:[], round:n}"),
            issues=_p("array", "问题清单（红队打回理由）"),
            reason=_p("string", "原因"), force=_p("boolean", "restore 强制"),
            path=_p("string", "index_code 的目录（大域）"),
            patterns=_p("array", "index_code 的文件后缀，默认 ['.py']"),
            max_files=_p("integer", "index_code 最多扫描文件数")),
    },
    {
        "name": "stg",
        "description": "语义时空图接口：精确得到信息的时间/空间关系。"
                       "op=relation：两节点时空关系（Allen 时间 6 态 + RCC 空间 7 态）；"
                       "op=timeline：按时间排序；op=anchors：落在时间窗/空间范围的节点；"
                       "op=consistency：时空字段自洽性检查。",
        "inputSchema": _s("",
            op=_p("string", "relation|timeline|anchors|consistency", True),
            a=_p("string", "relation 的节点 a"), b=_p("string", "relation 的节点 b"),
            time_window=_p("array", "anchors 的时间窗 [t1,t2]"),
            bbox=_p("array", "anchors 的包围盒 [x1,y1,x2,y2]"),
            layer=_p("string", "限定层"), limit=_p("integer", "返回条数"),
            desc=_p("boolean", "timeline 是否倒序（默认是）")),
    },
]

ALL_TOOLS = KERNEL_TOOLS + TOOLS
SURFACE = os.environ.get("MDCG_MCP_SURFACE", "kernel").strip().lower()


def tools_for_surface():
    """kernel：只暴露 2 个基元；full：2 个基元 + 21 个细粒度工具（兼容/调试）。"""
    return ALL_TOOLS if SURFACE == "full" else KERNEL_TOOLS


# --------------------------------------------------------------------------
# 序列化
# --------------------------------------------------------------------------

def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _pick_source(path):
    """按内容嗅探源类型：DSH 会话格式 vs 通用 JSONL。"""
    from .sources import DSHSessionSource, JsonlSource
    if path.endswith(".zstd"):
        return DSHSessionSource(path)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                o = json.loads(line)
                if o.get("type") == "session" or ("type" in o and "seq" in o
                                                  and "data" in o):
                    return DSHSessionSource(path)
                return JsonlSource(path)
    except (ValueError, OSError):
        pass
    return JsonlSource(path)


def _node_view(node):
    if not node:
        return None
    return {"id": node.get("id"), "path": node.get("path"),
            "frontmatter": node.get("frontmatter"), "content": node.get("content")}


# --------------------------------------------------------------------------
# 基元实现
# --------------------------------------------------------------------------

def _cg_call(cg, a):
    """认知图唯一入口。"""
    op = (a.get("op") or "read").strip().lower()

    if op == "info":
        from . import audit
        h = cg.health_os()
        h.update({"surface": SURFACE,
                  "tools": [t["name"] for t in tools_for_surface()],
                  "audit_kinds": audit.kinds(), "whoami": cg.whoami()})
        return h

    if op == "route":
        intent = a.get("intent") or a.get("query") or ""
        res, meta = cg.search(intent, k=int(a.get("k") or 10),
                              context=a.get("context"), record=False)
        knowledge, caps = [], []
        for n, s, q in res:
            fm = n.get("frontmatter") or {}
            knowledge.append({"id": n.get("id"), "score": s, "state": q.get("state"),
                              "reason": q.get("reason"),
                              "content": (n.get("content") or "")[:500],
                              "verification_basis": fm.get("verification_basis")})
            if fm.get("capability"):
                caps.append(fm["capability"])
            for t in (fm.get("tags") or []):
                if isinstance(t, str) and t.startswith("cap:"):
                    caps.append(t[4:])
        return {"knowledge": knowledge, "suggested_capabilities": sorted(set(caps)),
                "meta": meta,
                "note": "认知图只给知识与建议能力名，不执行；由调用方决定"}

    if op == "read":
        if a.get("node_id"):
            return _node_view(cg.get(a["node_id"]))
        q = a.get("query") or a.get("intent") or ""
        if a.get("budget_tokens"):
            return cg.recall(q, budget_tokens=int(a["budget_tokens"]),
                             k=int(a.get("k") or 20), context=a.get("context"),
                             goal_text=a.get("goal"),
                             include_recent=bool(a.get("include_recent")),
                             recent_limit=int(a.get("limit") or 10))
        res, meta = cg.search(q, layer=a.get("layer"), k=int(a.get("k") or 20),
                              context=a.get("context"))
        return {"meta": meta, "results": [
            {"node": _node_view(n), "score": s, "state": q2.get("state"),
             "reason": q2.get("reason")} for n, s, q2 in res]}

    if op == "write":
        from . import audit
        verdict = audit.audit(
            (a.get("content_kind") or "").strip(),
            {"content": a.get("content", ""), "action": a.get("action"),
             "sensitivity": a.get("sensitivity"),
             "topic": a.get("query") or a.get("intent")},
            {"cg": cg, "principal": getattr(cg, "principal", None)})
        nid = a.get("node_id") or ("mem_" + str(int(__import__("time").time() * 1000)))
        st = verdict["state"]
        if st == audit.ACCEPT:
            cg.add(nid, a.get("content", ""), layer=a.get("layer") or "knowledge",
                   tags=a.get("tags"), condition_space=a.get("condition_space"),
                   importance=float(a.get("importance", 0.5)),
                   verification_basis=a.get("verification_basis") or verdict.get("basis"),
                   non_applicable_conditions=a.get("non_applicable_conditions"))
            return {"ok": True, "id": nid, "committed": True, "verdict": verdict}
        if st == audit.REJECT:
            rid = cg.add_rejected((a.get("content") or "")[:200], verdict["evidence"],
                                  verification_basis=verdict.get("basis") or "test",
                                  tags=a.get("tags"))
            return {"ok": False, "id": rid, "committed": False,
                    "moved_to": "rejected", "verdict": verdict}
        pid = cg.propose(nid, a.get("content", ""), layer=a.get("layer") or "knowledge",
                         tags=a.get("tags"), condition_space=a.get("condition_space"))
        return {"ok": True, "id": nid, "pid": pid, "committed": False,
                "moved_to": "review_queue", "verdict": verdict}

    if op == "goal":
        act = (a.get("action") or "list").strip().lower()
        if act == "add":
            gid = cg.add_goal(a.get("goal") or a.get("text") or "",
                              priority=float(a.get("priority", 0.5)),
                              deadline=a.get("deadline"),
                              conditions=a.get("conditions") or "",
                              action=a.get("action_hint") or "",
                              tags=a.get("tags"),
                              status=a.get("goal_status") or "active")
            return {"ok": True, "id": gid}
        if act in ("status", "set_status"):
            return {"ok": True,
                    "goal": cg.set_goal_status(a.get("node_id", ""),
                                               a.get("goal_status") or "done")}
        return {"goals": cg.list_goals(status=a.get("goal_status"),
                                       limit=int(a.get("limit") or 20)),
                "active": cg.active_goals(limit=int(a.get("limit") or 5))}

    if op == "recent":
        act = (a.get("action") or "list").strip().lower()
        if act in ("add", "append", "remember"):
            return cg.remember_event(a.get("role") or "user",
                                     a.get("text") or a.get("content") or "",
                                     tags=a.get("tags"), meta=a.get("meta"),
                                     window=int(a.get("window") or 200))
        if act == "clear":
            return {"cleared": cg.clear_recent()}
        return {"events": cg.recent_events(limit=int(a.get("limit") or 20),
                                           roles=a.get("roles"))}

    if op == "verify":
        return cg.verify(a.get("node_id", ""), a.get("evidence", ""),
                         a.get("verdict", ""))

    if op == "review":
        act = (a.get("action") or "list").strip().lower()
        if act == "list":
            return {"pending": cg.review_list()}
        if act == "rounds":
            pid = a.get("pid", "")
            return {"pid": pid, "rounds": cg.review_rounds(pid)}
        if act == "records":
            return {"records": cg.review_records(pid=a.get("pid"))}
        if act in ("verify_record", "verify"):
            return cg.verify_review_record(a.get("node_id", ""))
        return cg.review_decide(a.get("pid", ""), a.get("decision", ""),
                                edits=a.get("edits"), merge_into=a.get("merge_into"),
                                reason=a.get("reason", ""),
                                redteam=a.get("redteam"), issues=a.get("issues"))

    if op == "forget":
        if (a.get("action") or "forget").strip().lower() == "restore":
            return cg.restore(a.get("node_id", ""), force=bool(a.get("force")))
        return cg.forget(a.get("node_id", ""), a.get("reason", ""))

    if op == "index_code":
        from . import codeindex
        root = a.get("path") or cg.root
        if not os.path.isdir(root):
            return {"ok": False, "error": f"目录不存在：{root}"}
        items, errors = codeindex.index_dir(
            root, patterns=a.get("patterns"),
            max_files=int(a.get("max_files") or 500))
        ids = []
        for it in items:
            nid = codeindex.node_id(it)
            cg.add(nid, codeindex.render(it),
                   layer=a.get("layer") or "knowledge",
                   tags=["code", "code:" + it["kind"]],
                   condition_space={"observation_position":
                                    it["path"].split("/")[0]},
                   verification_basis="compiler",
                   code_ref={"path": it["path"], "name": it["name"],
                             "kind": it["kind"], "lineno": it["lineno"],
                             "end": it["end"]})
            ids.append(nid)
        return {"ok": True, "indexed": len(ids), "error_count": len(errors),
                "errors": errors[:10], "ids": ids[:20],
                "note": "只索引注释/接口（AST 已校验），未存完整代码；"
                        "正文用 frontmatter.code_ref 指回源文件"}

    raise ValueError(f"cg 未知 op：{op}")


def _stg_call(cg, a):
    """语义时空图唯一入口。"""
    from . import stg
    op = (a.get("op") or "").strip().lower()
    if op == "relation":
        return stg.relation(cg, a.get("a", ""), a.get("b", ""))
    if op == "timeline":
        return stg.timeline(cg, layer=a.get("layer"),
                            limit=int(a.get("limit") or 50),
                            desc=bool(a.get("desc", True)))
    if op == "anchors":
        return stg.anchors(cg, time_window=a.get("time_window"), bbox=a.get("bbox"),
                           layer=a.get("layer"), limit=int(a.get("limit") or 50))
    if op == "consistency":
        return stg.consistency(cg, layer=a.get("layer"),
                               limit=int(a.get("limit") or 50))
    raise ValueError(f"stg 未知 op：{op}")


# --------------------------------------------------------------------------
# 工具实现
# --------------------------------------------------------------------------

def call_tool(cg, name, args):
    a = args or {}
    if name == "cg":
        return _cg_call(cg, a)
    if name == "stg":
        return _stg_call(cg, a)
    if name == "mdcg_service_info":
        return {"server": SERVER_NAME, "version": SERVER_VERSION,
                "protocol": PROTOCOL_VERSION, "root": cg.root, "actor": cg.actor,
                "nodes": len(cg.index["nodes"]),
                "surface": SURFACE, "tools": len(tools_for_surface()),
                "tool_names": [t["name"] for t in tools_for_surface()],
                "principal": getattr(cg, "principal", None) and cg.principal.as_dict()}

    if name == "mdcg_remember":
        nid = a.get("node_id") or ("mem_" + str(int(__import__("time").time() * 1000)))
        cg.add(nid, a.get("content", ""), layer=a.get("layer") or "knowledge",
               role=a.get("role"), tags=a.get("tags"),
               condition_space=a.get("condition_space"),
               importance=float(a.get("importance", 0.5)),
               verification_basis=a.get("verification_basis"),
               non_applicable_conditions=a.get("non_applicable_conditions"))
        return {"ok": True, "id": nid}

    if name == "mdcg_recall":
        use_fuzzy = bool(a.get("fuzzy"))
        use_semantic = bool(a.get("semantic"))
        use_goal = bool(a.get("goal_path") or a.get("goal"))
        if use_fuzzy or use_semantic or use_goal:
            paths = ["lexical", "bucket", "entity", "graph"]
            if use_fuzzy:
                paths.append("fuzzy")
            if use_semantic:
                paths.append("semantic")
            if use_goal:
                paths.append("goal")
            paths = tuple(paths)
        else:
            paths = None
        # fuzzy 路缺省用 max 融合：实测（memory-bench-1000，870 查询）sum 会把
        # self@1 拉低 10.1%，因为求和奖励「多路共识」、低估「模糊路独有」的目标。
        # semantic 路同理：条件结构命中常是「独有召回」，故一并缺省 max。
        fusion = a.get("fusion") or ("max" if (use_fuzzy or use_semantic or use_goal) else None)
        return cg.recall(a.get("query", ""),
                         budget_tokens=int(a.get("budget_tokens") or 1200),
                         k=int(a.get("k") or 20), context=a.get("context"),
                         include_work=bool(a.get("include_work")),
                         paths=paths, fusion=fusion,
                         goal_text=a.get("goal"),
                         include_recent=bool(a.get("include_recent")),
                         recent_limit=int(a.get("recent_limit") or 10),
                         query_expand=_make_query_expand(a.get("expand")))

    if name == "mdcg_search":
        res, meta = cg.search(a.get("query", ""), layer=a.get("layer"),
                              k=int(a.get("k") or 20), context=a.get("context"),
                              roles=tuple(a["roles"]) if a.get("roles") else None,
                              include_work=bool(a.get("include_work")))
        return {"meta": meta,
                "results": [{"node": _node_view(n), "score": s, "state": q.get("state"),
                             "reason": q.get("reason")} for n, s, q in res]}

    if name == "mdcg_get":
        return _node_view(cg.get(a.get("node_id", "")))

    if name == "mdcg_reflect":
        res, _ = cg.search(a.get("query", ""), k=int(a.get("k") or 10), record=False)
        return cg.reflect(a.get("query", ""), res, a.get("feedback"))

    if name == "mdcg_verify":
        return cg.verify(a.get("node_id", ""), a.get("evidence", ""), a.get("verdict", ""))

    if name == "mdcg_flywheel":
        return cg.flywheel_step(a.get("error_report") or {})

    if name == "mdcg_mine_fix_pairs":
        return cg.mine_fix_pairs(a.get("events") or [])

    if name == "mdcg_rejected":
        return {"id": cg.add_rejected(a.get("hypothesis", ""), a.get("reason", ""),
                                      verification_basis=a.get("verification_basis") or "test",
                                      tags=a.get("tags"))}

    if name == "mdcg_unresolved":
        return {"id": cg.add_unresolved(a.get("question", ""), a.get("known_clues", ""),
                                        a.get("goal", ""))}

    if name == "mdcg_propose":
        return {"pid": cg.propose(a.get("node_id", ""), a.get("content", ""),
                                  layer=a.get("layer") or "knowledge",
                                  tags=a.get("tags"), condition_space=a.get("condition_space"),
                                  verify=a.get("verify"))}

    if name == "mdcg_review_list":
        return {"pending": cg.review_list()}

    if name == "mdcg_review_decide":
        return cg.review_decide(a.get("pid", ""), a.get("decision", ""),
                                edits=a.get("edits"), merge_into=a.get("merge_into"),
                                reason=a.get("reason", ""),
                                redteam=a.get("redteam"), issues=a.get("issues"))

    if name == "mdcg_review_records":
        nid = a.get("node_id")
        if nid:
            return cg.verify_review_record(nid)
        return {"records": cg.review_records(pid=a.get("pid"))}

    if name == "mdcg_forget":
        return cg.forget(a.get("node_id", ""), a.get("reason", ""))

    if name == "mdcg_restore":
        return cg.restore(a.get("node_id", ""), force=bool(a.get("force")))

    if name == "mdcg_health":
        return cg.health_os()

    if name == "mdcg_whoami":
        return cg.whoami()

    if name == "mdcg_ingest":
        from .sources import DSHSessionSource, JsonlSource, Ingestor
        src_arg = (a.get("source") or "auto").strip()
        ing = Ingestor(cg)
        if src_arg == "auto":
            files = DSHSessionSource.discover(limit=1)
            if not files:
                return {"error": "no_dsh_session_found"}
            src = DSHSessionSource(files[0])
        else:
            src = _pick_source(src_arg)
        return ing.ingest(src,
                          mine_fix_pairs=bool(a.get("mine_fix_pairs", True)),
                          max_events=a.get("max_events"),
                          dry_run=bool(a.get("dry_run")))

    if name == "mdcg_watermarks":
        from .sources import Ingestor
        return {"watermarks": Ingestor(cg).watermarks()}

    raise ValueError(f"未知工具：{name}")


# --------------------------------------------------------------------------
# JSON-RPC / stdio 主循环
# --------------------------------------------------------------------------

def _reply(rid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(_j(msg) + "\n")
    sys.stdout.flush()


def main():
    root = os.environ.get("MDCG_ROOT")
    if not root:
        sys.stderr.write("[mdcg-mcp] 缺少 MDCG_ROOT 环境变量\n")
        return 2
    # 权限模型：clearance / tenant / 写权限 / 管理权限（默认 internal，只读为主）
    from .mdcos import MdCGSecure
    from .security import Principal
    clearance = os.environ.get("MDCG_CLEARANCE", "internal")
    principal = Principal(
        tenant=os.environ.get("MDCG_TENANT", "default"),
        actor=os.environ.get("MDCG_ACTOR", "mcp-client"),
        clearance=clearance,
        can_write=os.environ.get("MDCG_CAN_WRITE", "1") not in ("0", "false", "False"),
        can_admin=os.environ.get("MDCG_CAN_ADMIN", "0") in ("1", "true", "True"),
    )
    cg = MdCGSecure(root, principal=principal)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method = msg.get("method")
        rid = msg.get("id")

        if method == "initialize":
            _reply(rid, {"protocolVersion": PROTOCOL_VERSION,
                         "capabilities": {"tools": {}},
                         "serverInfo": {"name": SERVER_NAME,
                                        "version": SERVER_VERSION}})
        elif method in ("notifications/initialized", "initialized"):
            continue                      # 通知，无响应
        elif method == "tools/list":
            _reply(rid, {"tools": tools_for_surface()})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            try:
                out = call_tool(cg, name, args)
                _reply(rid, {"content": [{"type": "text", "text": _j(out)}],
                             "isError": False})
            except Exception as exc:      # noqa: BLE001 —— 工具错误以 MCP 结果返回
                _reply(rid, {"content": [{"type": "text",
                                          "text": _j({"error": f"{type(exc).__name__}: {exc}"})}],
                             "isError": True})
        elif method == "shutdown":
            _reply(rid, {})
            break
        elif rid is not None:
            _reply(rid, error={"code": -32601, "message": f"method not found: {method}"})

    try:
        cg.close()
    except Exception:                     # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
