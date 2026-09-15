# -*- coding: utf-8 -*-
"""灵枢蜂巢 · 默认 LLM 执行器（零第三方依赖，Python 标准库）。

契约（与 hive/src/exec.rs 头注释一致）：
    入参   argv[1] = job 目录
    读     spec.json（model / system_prompt / user_prompt / context_files /
             timeout_s / max_tokens / temperature / thinking / reasoning_effort /
             context_budget_tokens / tools / max_tool_rounds / ...）
    写     result.json —— 成功与 API 错误都写，error 字段区分：
             {"ok": true, "content": "...", "usage": {...}, "model": "...",
              "tool_trace": [...],                       # 仅 spec.tools 时存在
              "finished_ts": ..., "duration_s": ...}
             {"ok": false, "error": "...", ...}
           log.txt —— 详细日志（stdout/stderr 保持安静，不污染 serve 控制台）
    退出码 0 成功 / 2 规格错 / 3 API 错误

API：OpenAI 兼容 chat/completions（GLM 同形）。
env：HIVE_API_KEY（必填，缺失即 fail）、
     HIVE_API_BASE（默认 https://open.bigmodel.cn/api/paas/v4）、
     MDCG_ROOT（lingshu_cg 工具的认知图根；缺省该工具返回配置缺失错误）、
     MDCG_HOME（md_cg 包所在仓根；缺省=执行器父目录，同仓分发零配置）、
     HIVE_WEB_SEARCH（web_search 后端：zhipu[默认] | duckduckgo）、
     HIVE_WEB_SEARCH_BASE（zhipu 搜索端点 base，缺省智谱官方
       https://open.bigmodel.cn/api/paas/v4——与 HIVE_API_BASE 解耦，
       后者常为 LLM 中转网关、无 web_search 路由）、
     HIVE_WEB_SEARCH_KEY（搜索密钥，缺省回落 HIVE_API_KEY）。

工具面（agent loop）：spec.tools 白名单启用，缺省 = 无工具 = 单发调用
（行为与历史版本逐位一致）。启用后按 OpenAI function calling 循环：
模型回 tool_calls → 执行器执行 → tool 消息回喂 → 循环至终答或达
max_tool_rounds（默认 5，随后发一次不带 tools 的请求强制终答）。
  lingshu_cg  灵枢认知图（op=route|read|write 白名单）；权限硬编码 recorder
              （can_admin=False，spec 无法提权），写入过校验闸门（DEFER 入
              审核队列/REJECT 负记忆是设计行为）；会话隔离 session=hive_job_<id>。
  web_search  网页搜索；zhipu 后端复用 HIVE_API_KEY/HIVE_API_BASE 调
              /web_search 端点，duckduckgo 兜底（零 key，html 抓取）。
每轮工具调用记入 result.json 的 tool_trace（审计可回放）；工具结果回喂前
截断（TOOL_MSG_MAX_CHARS），防上下文爆炸。

HTTPS 之所以在这里而不是 rust：TLS 无第三方库在纯 std rust 不可行（D-005）；
Python urllib 走系统证书，零依赖达成。执行器是可替换子进程——换 curl /
其它 SDK 宿主时，保持「读 spec.json、写 result.json」契约即可。

上下文拼接：context_files 逐个读入，以
    <context path="...">
    ...文件全文...
    </context>
块追加在 user_prompt 之前（AI 侧归一由调用方在 spec 里完成，执行器不加工）。
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request

DEFAULT_API_BASE = "https://open.bigmodel.cn/api/paas/v4"
EXIT_OK, EXIT_SPEC, EXIT_API = 0, 2, 3


def log(job_dir: str, msg: str) -> None:
    with open(os.path.join(job_dir, "log.txt"), "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")


def write_result(job_dir: str, payload: dict) -> None:
    with open(os.path.join(job_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def read_spec(job_dir: str) -> dict:
    with open(os.path.join(job_dir, "spec.json"), encoding="utf-8") as f:
        return json.load(f)


def build_messages(spec: dict, job_dir: str) -> list:
    user_prompt = spec.get("user_prompt", "")
    ctx_blocks = []
    base = spec.get("workdir") or os.getcwd()
    for rel in spec.get("context_files") or []:
        path = rel if os.path.isabs(rel) else os.path.join(base, rel)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            log(job_dir, f"context 读取失败 {path}: {e}")
            ctx_blocks.append(f'<context path="{rel}" error="读取失败: {e}"></context>')
            continue
        ctx_blocks.append(f'<context path="{rel}">\n{text}\n</context>')
    prompt = ("\n\n".join(ctx_blocks) + "\n\n" + user_prompt) if ctx_blocks else user_prompt
    messages = []
    sys_prompt = (spec.get("system_prompt") or "").strip()
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages


_CJK_RANGES = (
    (0x4E00, 0x9FFF),  # CJK 统一表意
    (0x3400, 0x4DBF),  # 扩展 A
    (0xF900, 0xFAFF),  # 兼容表意
    (0x3000, 0x303F),  # CJK 标点
    (0xFF00, 0xFFEF),  # 全角形式
)


def est_tokens(text: str) -> int:
    """保守 token 估算——**偏高估**：宁可提前拦截，不放行超限输入白跑 API。

    CJK 1 字 ≈ 1 token（DeepSeek 中文实际约 1.6 字/token，此处高估约 60%），
    其余字符 4 个 ≈ 1 token。仅用于预算判断，不是精确计数。
    """
    if not text:
        return 0
    cjk = other = 0
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _CJK_RANGES):
            cjk += 1
        else:
            other += 1
    return cjk + (other + 3) // 4


LINGSHU_OPS_ALLOW = ("route", "read", "write")
VERIFICATION_BASIS_ALLOW = ("compiler", "test", "measurement", "formal_proof",
                            "data", "textbook", "public_kb", "other")
TOOL_MSG_MAX_CHARS = 4000    # 工具结果回喂模型的单条截断（防上下文爆炸）
DEFAULT_MAX_TOOL_ROUNDS = 5

LINGSHU_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "lingshu_cg",
        "description": (
            "灵枢认知图工具（长期记忆）。op=route：按任务意图检索相关记忆与"
            "建议能力，动手前先查；op=read：按 query 读领域知识（或 node_id "
            "定点读单节点全文）；op=write：写入一条记忆（格式：【内容】…"
            "【原因】…【位置】…【验证】…，只记核心修改）。写入过校验闸门："
            "返回 committed=false 且 moved_to=review_queue / rejected 是设计"
            "行为（DEFER 入审核队列待裁决 / 内容未过审核），不是故障，勿重试。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "op": {"type": "string",
                       "enum": list(LINGSHU_OPS_ALLOW)},
                "intent": {"type": "string",
                           "description": "op=route 必填：任务意图关键词"},
                "query": {"type": "string",
                          "description": "op=read 必填（无 node_id 时）：领域关键词"},
                "k": {"type": "integer",
                      "description": "返回条数上限（route 默认 5，read 默认 20）"},
                "node_id": {"type": "string",
                            "description": "op=read 可选：定点读单节点全文"},
                "content": {"type": "string",
                            "description": "op=write 必填：记忆正文"},
                "content_kind": {"type": "string",
                                 "description": "op=write：内容种类，如 work_done/text"},
                "layer": {"type": "string",
                          "description": "op=write：knowledge/procedural/contextual"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "importance": {"type": "number"},
                "verification_basis": {
                    "type": "string",
                    "enum": list(VERIFICATION_BASIS_ALLOW),
                    "description": "op=write：验证基底，缺省由审核闸门判定"},
            },
            "required": ["op"],
        },
    },
}

WEB_SEARCH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "网页搜索：返回与 query 相关的结果列表（标题/链接/摘要）。"
                       "用于查公开事实、时效信息；与 lingshu_cg（私有记忆）互补。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "搜索关键词"},
                "count": {"type": "integer",
                          "description": "结果条数（默认 5，上限 10）"},
            },
            "required": ["query"],
        },
    },
}

TOOL_SCHEMAS = {
    "lingshu_cg": LINGSHU_TOOL_SCHEMA,
    "web_search": WEB_SEARCH_TOOL_SCHEMA,
}


def _md_cg_import():
    """import md_cg（MDCG_HOME 优先，缺省=执行器父目录——同仓分发零配置）。"""
    home = os.environ.get("MDCG_HOME", "").strip()
    if not home:
        home = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if home not in sys.path:
        sys.path.insert(0, home)
    from md_cg.mdcos import MdCGSecure          # noqa: F401  载入即校验
    from md_cg.mcp_server import _cg_dispatch   # noqa: F401
    from md_cg.security import Principal        # noqa: F401
    return home


def tool_lingshu_cg(args: dict, job_id: str, mdcg_root: str = None) -> dict:
    """灵枢认知图工具：复用 MCP 面同一 dispatch（op 白名单 route/read/write）。

    权限边界（硬编码，spec 不可改变）：recorder 角色 + can_admin=False——
    子代理写入过校验闸门（DEFER 入审核队列 / REJECT 负记忆），裁决权留给
    设计者（写入者不得自裁自决）。会话隔离：principal.session=hive_job_<id>。
    root 来源：env MDCG_ROOT 优先（serve 级管理员控制），spec.mdcg_root 兜底
    （提交方显式指定——如任务级隔离用临时图）。
    """
    op = (args.get("op") or "").strip()
    if op not in LINGSHU_OPS_ALLOW:
        return {"ok": False, "error": f"op={op!r} 未对子代理开放（允许："
                f"{', '.join(LINGSHU_OPS_ALLOW)}）"}
    if op == "write":
        # 防卡队列：非法 verification_basis（自由文本）会在设计者 accept 落盘
        # 时才炸（入队侧不校验）——执行器侧前置拦截，让模型当场修正。
        vb = args.get("verification_basis")
        if vb is not None and vb not in VERIFICATION_BASIS_ALLOW:
            return {"ok": False, "error": f"verification_basis={vb!r} 非法（允许："
                    f"{', '.join(VERIFICATION_BASIS_ALLOW)}）；请修正后重试或省略该参数"}
    root = (os.environ.get("MDCG_ROOT", "").strip() or (mdcg_root or "").strip())
    if not root:
        return {"ok": False, "error": "lingshu_cg 未配置：执行器 env 缺 MDCG_ROOT"
                "（认知图根目录）。部署侧在 serve 环境注入后重启 hive serve。"}
    home = None
    try:
        home = _md_cg_import()
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        principal = Principal(actor="hive-worker", clearance="secret",
                              can_write=True, can_admin=False, role="recorder",
                              auth_mode="hive-exec")
        principal.session = f"hive_job_{job_id}"
        cg = MdCGSecure(root, principal=principal)
        from md_cg.mcp_server import _cg_dispatch
        out = _cg_dispatch(cg, args)
        return out if isinstance(out, dict) else {"ok": True, "data": out}
    except Exception as e:  # noqa: BLE001 —— 工具异常回喂模型自修，不终杀任务
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "mdcg_home": home}


def tool_web_search(args: dict, backend_override: str = None) -> dict:
    """网页搜索。zhipu：/web_search 端点（base/key 独立 env，见 _ws_zhipu）；
    duckduckgo：零 key 兜底（html.duckduckgo.com 抓取解析，弱依赖可被墙）。
    后端选择：env HIVE_WEB_SEARCH 优先，spec.web_search_backend 兜底。"""
    query = (args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query 必填"}
    count = max(1, min(int(args.get("count") or 5), 10))
    backend = (os.environ.get("HIVE_WEB_SEARCH", "").strip().lower()
               or (backend_override or "").strip().lower() or "zhipu")
    try:
        if backend == "zhipu":
            return _ws_zhipu(query, count, backend)
        if backend == "duckduckgo":
            return _ws_duckduckgo(query, count, backend)
        return {"ok": False, "error": f"HIVE_WEB_SEARCH={backend!r} 未知后端"
                "（允许：zhipu | duckduckgo）"}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:  # noqa: BLE001
            detail = ""
        return {"ok": False, "backend": backend, "error": f"HTTP {e.code}: {detail}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "backend": backend,
                "error": f"{type(e).__name__}: {e}"}


ZHIPU_SEARCH_BASE = "https://open.bigmodel.cn/api/paas/v4"


def _ws_zhipu(query: str, count: int, backend: str) -> dict:
    # 端点与 LLM base 解耦（实测教训：HIVE_API_BASE 常指向 LLM 中转网关，
    # 只代理 chat/completions——锚上去 web_search 必 404）。搜索端点独立：
    # HIVE_WEB_SEARCH_BASE 缺省智谱官方；key 缺省回落执行器密钥。
    api_base = (os.environ.get("HIVE_WEB_SEARCH_BASE", "").strip()
                or ZHIPU_SEARCH_BASE).rstrip("/")
    api_key = (os.environ.get("HIVE_WEB_SEARCH_KEY", "").strip()
               or os.environ.get("HIVE_API_KEY", ""))
    if not api_key:
        return {"ok": False, "backend": backend,
                "error": "搜索密钥未设置（HIVE_WEB_SEARCH_KEY 或 HIVE_API_KEY）"}
    req = urllib.request.Request(
        f"{api_base}/web_search",
        data=json.dumps({"search_engine": "search_std", "search_query": query},
                        ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    items = []
    for r in (data.get("search_result") or [])[:count]:
        items.append({"title": (r.get("title") or "")[:200],
                      "url": r.get("link") or r.get("url") or "",
                      "snippet": (r.get("content") or "")[:300],
                      "media": r.get("media") or ""})
    return {"ok": True, "backend": backend, "query": query, "results": items}


_DDG_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 "
           "Firefox/125.0")


def _ws_duckduckgo(query: str, count: int, backend: str) -> dict:
    import html
    import re
    url = ("https://html.duckduckgo.com/html/?q="
           + urllib.request.quote(query))
    req = urllib.request.Request(url, headers={"User-Agent": _DDG_UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        page = resp.read().decode("utf-8", errors="replace")
    a_re = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>')
    snip_re = re.compile(
        r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.S)
    hits = list(a_re.finditer(page))[:count]
    items = []
    for i, m in enumerate(hits):
        href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
        # DDG 重定向链接 //duckduckgo.com/l/?uddg=<urlencoded>
        if "uddg=" in href:
            href = urllib.request.unquote(
                href.split("uddg=")[-1].split("&")[0])
        snippet = ""
        nxt = hits[i + 1].start() if i + 1 < len(hits) else len(page)
        sm = snip_re.search(page, m.end(), nxt)  # 摘要归属：本结果块内最近
        if sm:
            snippet = html.unescape(re.sub(r"<[^>]+>", "", sm.group(1)))
        items.append({"title": html.unescape(title)[:200], "url": href,
                      "snippet": snippet[:300], "media": ""})
    return {"ok": True, "backend": backend, "query": query, "results": items}


def execute_tool(name: str, args_json: str, job_id: str,
                 mdcg_root: str = None, ws_backend: str = None) -> tuple:
    """执行一次工具调用，返回 (结果dict, trace简报)。未知工具诚实报错。"""
    try:
        args = json.loads(args_json or "{}")
    except json.JSONDecodeError as e:
        return ({"ok": False, "error": f"工具参数不是合法 JSON: {e}"}, "")
    if name == "lingshu_cg":
        out = tool_lingshu_cg(args, job_id, mdcg_root=mdcg_root)
    elif name == "web_search":
        out = tool_web_search(args, backend_override=ws_backend)
    else:
        out = {"ok": False,
               "error": f"未知工具 {name!r}（允许：{', '.join(TOOL_SCHEMAS)}）"}
    # 统一 ok 语义：底层 dispatch（route/read）无 ok 键——无 error 即成功，
    # 保证 trace["ok"] 与模型侧自修判断的依据可靠。
    out.setdefault("ok", "error" not in out)
    n = len(out.get("results") or out.get("knowledge") or [])
    brief = ("ok" if out.get("ok") else "error") + f" items={n}"
    return (out, brief)


def build_body(spec: dict, messages: list, tools: list = None) -> dict:
    """请求体构造：必填 model/messages + 可选参数存在才注入（不送 null/缺省键）。

    thinking 原样透传（DeepSeek V4.1 同形对象，如 {"type": "enabled"}）；
    reasoning_effort 档位已由 rust 侧白名单校验（low|medium|high）；
    tools 仅 agent loop 注入（function calling schema 列表）。
    """
    body: dict = {"model": spec["model"], "messages": messages}
    if tools:
        body["tools"] = tools
    if spec.get("thinking"):
        body["thinking"] = spec["thinking"]
    if spec.get("reasoning_effort"):
        body["reasoning_effort"] = spec["reasoning_effort"]
    if spec.get("max_tokens"):
        body["max_tokens"] = spec["max_tokens"]
    if spec.get("temperature") is not None:
        body["temperature"] = spec["temperature"]
    return body


def _post_chat(body: dict, timeout: float) -> dict:
    """裸 POST chat/completions，返回原始响应 dict。HTTP 异常向上传播。"""
    api_base = os.environ.get("HIVE_API_BASE", DEFAULT_API_BASE).rstrip("/")
    api_key = os.environ.get("HIVE_API_KEY", "")
    if not api_key:
        raise RuntimeError("HIVE_API_KEY 未设置（执行器环境缺密钥）")
    url = f"{api_base}/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_llm(spec: dict, messages: list) -> dict:
    """单发调 chat/completions（无工具历史路径）；返回归一化 result。"""
    data = _post_chat(build_body(spec, messages),
                      float(spec.get("timeout_s") or 300))
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    return {
        "content": content,
        "usage": data.get("usage") or {},
        "model": data.get("model") or spec["model"],
    }


def _acc_usage(total: dict, u: dict) -> None:
    for k, v in (u or {}).items():
        if isinstance(v, (int, float)):
            total[k] = total.get(k, 0) + v


def _choice(data: dict) -> dict:
    return (data.get("choices") or [{}])[0]


def run_with_tools(spec: dict, messages: list, job_id: str) -> dict:
    """agent loop：模型回 tool_calls → 执行 → tool 消息回喂 → 循环至终答。

    轮次上限 max_tool_rounds（spec 可配，默认 5）：达到后若模型仍要求工具，
    发一次不带 tools 的请求强制终答（保证 result.content 有值，trace 诚实
    记 _force_final）。API 异常不抛出——以 {"_error","tool_trace"} 返回，
    由 main 写失败 result（trace 不丢，审计可回放）。
    """
    names = [t for t in (spec.get("tools") or []) if t in TOOL_SCHEMAS]
    schemas = [TOOL_SCHEMAS[t] for t in names]
    max_rounds = max(1, int(spec.get("max_tool_rounds")
                            or DEFAULT_MAX_TOOL_ROUNDS))
    timeout = float(spec.get("timeout_s") or 300)
    budget = spec.get("context_budget_tokens")
    trace, usage_total = [], {}

    def _budget_check() -> str:
        if not budget:
            return ""
        total = sum(est_tokens(m.get("content") or "") for m in messages
                    if isinstance(m.get("content"), str))
        return (f"上下文超预算: 保守估算 {total} tokens > 预算 {int(budget)}"
                "（工具轮累积所致；请收窄任务或调大 context_budget_tokens）"
                if total > int(budget) else "")

    rnd = 0
    while rnd <= max_rounds:
        over = _budget_check()
        if over:
            return {"_error": over, "tool_trace": trace}
        try:
            data = _post_chat(build_body(spec, messages,
                                         tools=schemas if schemas else None),
                              timeout)
        except Exception as e:  # noqa: BLE001 —— main 统一写失败 result
            return {"_error": _api_err_text(e), "tool_trace": trace}
        _acc_usage(usage_total, data.get("usage") or {})
        msg = _choice(data).get("message") or {}
        calls = msg.get("tool_calls") or []
        if not calls:
            out = {"content": msg.get("content") or "",
                   "usage": usage_total,
                   "model": data.get("model") or spec["model"],
                   "tool_trace": trace}
            if rnd > 0:
                out["tool_rounds"] = rnd
            return out
        if rnd >= max_rounds:  # 超轮次仍要求工具 → 强制终答
            try:
                data = _post_chat(build_body(spec, messages, tools=None),
                                  timeout)
            except Exception as e:  # noqa: BLE001
                return {"_error": _api_err_text(e), "tool_trace": trace}
            _acc_usage(usage_total, data.get("usage") or {})
            msg = _choice(data).get("message") or {}
            trace.append({"round": rnd, "tool": "_force_final",
                          "ok": True, "brief": "轮次上限，强制终答"})
            return {"content": msg.get("content") or "",
                    "usage": usage_total,
                    "model": data.get("model") or spec["model"],
                    "tool_trace": trace, "tool_rounds": rnd,
                    "forced_final": True}
        messages.append({"role": "assistant",
                         "content": msg.get("content") or "",
                         "tool_calls": calls})
        for tc in calls:
            fn = tc.get("function") or {}
            out, brief = execute_tool(fn.get("name"), fn.get("arguments"),
                                      job_id,
                                      mdcg_root=spec.get("mdcg_root"),
                                      ws_backend=spec.get("web_search_backend"))
            trace.append({"round": rnd, "tool": fn.get("name"),
                          "args": (fn.get("arguments") or "")[:300],
                          "ok": bool(out.get("ok")), "brief": brief,
                          "result": json.dumps(out, ensure_ascii=False)[:800]})
            messages.append({
                "role": "tool", "tool_call_id": tc.get("id") or "",
                "content": json.dumps(out, ensure_ascii=False)
                [:TOOL_MSG_MAX_CHARS]})
        rnd += 1
    return {"_error": "工具轮次循环异常退出（不应到达）", "tool_trace": trace}


def _api_err_text(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        try:
            detail = e.read().decode("utf-8", errors="replace")[:2000]
        except Exception:  # noqa: BLE001
            detail = ""
        return f"HTTP {e.code}: {detail or e.reason}"
    return f"{type(e).__name__}: {e}"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: exec.py <job_dir>", file=sys.stderr)
        return EXIT_SPEC
    job_dir = sys.argv[1]
    t0 = time.time()
    try:
        spec = read_spec(job_dir)
    except Exception as e:  # noqa: BLE001 —— 顶层兜底必须写 result
        write_result(job_dir, {"ok": False, "error": f"spec 读取失败: {e}"})
        return EXIT_SPEC

    try:
        messages = build_messages(spec, job_dir)
        budget = spec.get("context_budget_tokens")
        if budget:
            total = sum(est_tokens(m["content"]) for m in messages)
            if total > int(budget):
                msg = (
                    f"上下文超预算: 保守估算 {total} tokens > 预算 {int(budget)}"
                    "（估算偏高估；请分片任务或调大 context_budget_tokens）"
                )
                write_result(job_dir, {"ok": False, "error": msg})
                log(job_dir, f"超预算拦截 est={total} budget={budget}")
                return EXIT_SPEC
        n_ctx = len(spec.get("context_files") or [])
        tool_names = [t for t in (spec.get("tools") or []) if t in TOOL_SCHEMAS]
        job_id = os.path.basename(os.path.normpath(job_dir))
        log(
            job_dir,
            f"开始调用 model={spec.get('model')} ctx={n_ctx}"
            + (f" effort={spec['reasoning_effort']}" if spec.get("reasoning_effort") else "")
            + (f" budget={budget}" if budget else "")
            + (f" tools={tool_names}" if tool_names else ""),
        )
        if tool_names:
            out = run_with_tools(spec, messages, job_id)
            if "_error" in out:
                write_result(
                    job_dir,
                    {
                        "ok": False,
                        "error": out["_error"],
                        "tool_trace": out.get("tool_trace") or [],
                        "finished_ts": time.time(),
                        "duration_s": round(time.time() - t0, 2),
                    },
                )
                log(job_dir, f"工具链失败: {out['_error'][:200]}")
                return EXIT_API
        else:
            out = call_llm(spec, messages)
        out.update(
            {
                "ok": True,
                "finished_ts": time.time(),
                "duration_s": round(time.time() - t0, 2),
            }
        )
        write_result(job_dir, out)
        tokens = out.get("usage", {}).get("total_tokens")
        n_tools = len(out.get("tool_trace") or [])
        log(job_dir, f"完成 tokens={tokens}"
            + (f" tool_calls={n_tools}" if n_tools else ""))
        return EXIT_OK
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:2000]
        except Exception:  # noqa: BLE001
            detail = ""
        write_result(
            job_dir,
            {
                "ok": False,
                "error": f"HTTP {e.code}: {detail or e.reason}",
                "finished_ts": time.time(),
                "duration_s": round(time.time() - t0, 2),
            },
        )
        log(job_dir, f"API HTTP 错误 {e.code}")
        return EXIT_API
    except Exception as e:  # noqa: BLE001
        write_result(
            job_dir,
            {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "finished_ts": time.time(),
                "duration_s": round(time.time() - t0, 2),
            },
        )
        log(job_dir, "异常:\n" + traceback.format_exc())
        return EXIT_API


if __name__ == "__main__":
    sys.exit(main())
