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
    env: { MDCG_ROOT: "...", PYTHONPATH: ".../llm-adapter-poc" }

工具面（17 个）：
  写：mdcg_remember / mdcg_rejected / mdcg_unresolved / mdcg_propose
  读：mdcg_get / mdcg_search / mdcg_recall / mdcg_review_list
  认知：mdcg_reflect / mdcg_verify / mdcg_flywheel / mdcg_mine_fix_pairs
  生命周期：mdcg_forget / mdcg_restore / mdcg_review_decide
  运维：mdcg_health / mdcg_service_info
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

def _s(desc, **props):
    return {"type": "object", "properties": props, "required":
            [k for k, v in props.items() if v.get("_req")]}


def _p(t, desc, req=False):
    d = {"type": t, "description": desc}
    if req:
        d["_req"] = True
    return d


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
                       "会话开始或重要工作前调用。",
        "inputSchema": _s("", query=_p("string", "描述当前任务的查询", True),
                          budget_tokens=_p("integer", "token 预算（默认 1200）"),
                          k=_p("integer", "候选上限"), context=_p("object", "当前情境条件空间"),
                          include_work=_p("boolean", "是否含工具输出/命令/编辑（默认否）")),
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
                          condition_space=_p("object", "条件空间")),
    },
    {
        "name": "mdcg_review_list",
        "description": "列出待审核候选（inbox 中未被裁决的条目）。",
        "inputSchema": _s(""),
    },
    {
        "name": "mdcg_review_decide",
        "description": "审核裁决：accept / reject / edit / merge（merge 需 merge_into）。",
        "inputSchema": _s("", pid=_p("string", "提案 id", True),
                          decision=_p("string", "accept|reject|edit|merge", True),
                          edits=_p("object", "edit 时的覆盖字段"), merge_into=_p("string", "merge 目标节点 id"),
                          reason=_p("string", "裁决理由")),
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
# 工具实现
# --------------------------------------------------------------------------

def call_tool(cg, name, args):
    a = args or {}
    if name == "mdcg_service_info":
        return {"server": SERVER_NAME, "version": SERVER_VERSION,
                "protocol": PROTOCOL_VERSION, "root": cg.root, "actor": cg.actor,
                "nodes": len(cg.index["nodes"]), "tools": len(TOOLS),
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
        return cg.recall(a.get("query", ""),
                         budget_tokens=int(a.get("budget_tokens") or 1200),
                         k=int(a.get("k") or 20), context=a.get("context"),
                         include_work=bool(a.get("include_work")))

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
                                  tags=a.get("tags"), condition_space=a.get("condition_space"))}

    if name == "mdcg_review_list":
        return {"pending": cg.review_list()}

    if name == "mdcg_review_decide":
        return cg.review_decide(a.get("pid", ""), a.get("decision", ""),
                                edits=a.get("edits"), merge_into=a.get("merge_into"),
                                reason=a.get("reason", ""))

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
            _reply(rid, {"tools": TOOLS})
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
