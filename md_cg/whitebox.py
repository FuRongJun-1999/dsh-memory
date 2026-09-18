# -*- coding: utf-8 -*-
"""md_cg · 白箱能力调用与验证（显式调用层）。

架构定位（2026-09-10 修订）
--------------------------
  · md_cg = 记忆操作系统 / **唯一真源**：负责记忆的写、读、裁决、留痕。
  · 白箱知识库 = **随主仓自带**（`md_cg/whitebox_kb/`，原理论仓 `aeis/wisdom`
                等内迁）：不再需要外部 `aeis` 包，也不再需要跨库调用。
  · AEIS  = **身体 / 世界模型库**：本层不再依赖它（自带内核中 vision / body /
            world_model 等均为方法内惰性导入，缺失即自动降级）。

为什么单独成层
--------------
白箱需要一个可审计的调用入口。本模块是「md_cg 调用白箱」的**唯一显式入口**：
  · 调用方式：**进程内**直调自带引擎（默认，见 `LocalWhiteboxClient`）；
    仅当显式设置 `MDCG_WHITEBOX_CMD` / `MDCG_WHITEBOX_ARGS` 时，
    才回退外部 MCP stdio 子进程（legacy 路径）。
  · 调用结果：验证结论写回认知图（self 层，tags 含 `whitebox:verify`），可追溯。

显式调用映射（详见 docs/mdcg/功能调用映射表_v0.1.md）
------------------------------------------------
  功能                 → 代码                                   → MCP
  白箱问答             → md_cg.whitebox.ask                     → cg(op=whitebox, action=ask)
  白箱编码             → md_cg.whitebox.remember                → cg(op=whitebox, action=remember)
  验证编码能力         → md_cg.whitebox.verify_encoding         → cg(op=whitebox, action=verify_encoding)
  验证已有知识回答能力 → md_cg.whitebox.verify_existing         → cg(op=whitebox, action=verify_existing)
  白箱能力验证报告     → md_cg.whitebox.report                  → cg(op=whitebox, action=report)
  白箱连通性探测       → md_cg.whitebox.ping                    → cg(op=whitebox, action=ping)

环境变量
--------
  WHITEBOX_DB / MDCG_WHITEBOX_DB  白箱图库路径
                                  （默认 MDCG_ROOT/data/whitebox/graph.db；
                                   独立运行时落 ~/.md_cg/whitebox/graph.db，
                                   首次以随包云库为底 + 卡源播种）
  MDCG_WHITEBOX_CMD    外部白箱启动命令（设置后走 legacy 子进程路径）
  MDCG_WHITEBOX_ARGS   外部白箱启动参数（同上，默认 "-m aeis.mcp.server"）
  MDCG_WHITEBOX_TIMEOUT 子进程单次调用超时秒数（默认 60）
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "md_cg-whitebox"
VERIFY_TAG = "whitebox:verify"

#: 已有知识回答能力的默认探针（白箱应能从自身知识库直接作答）。
DEFAULT_KNOWLEDGE_PROBES = [
    "你是谁？请用一句话介绍你自己。",
    "什么是条件论？",
]


# --------------------------------------------------------------------------
# 启动命令
# --------------------------------------------------------------------------

# 生效条件：无必需形参；exe 取 MDCG_WHITEBOX_CMD，该值为假时取 sys.executable、再为假时取 "python"，args 取 MDCG_WHITEBOX_ARGS.split()（该值为真时）否则 ["-m","aeis.mcp.server"]，返回 [exe]+args。
def _launch_cmd():
    """外部白箱 MCP server 启动命令（legacy 路径，需显式配置）。

    主仓自带白箱知识库后，本路径**不再默认启用**（见 `WhiteboxClient` 工厂）。
    默认参数 `-m aeis.mcp.server` 仅为兼容既有部署保留。
    """
    exe = os.environ.get("MDCG_WHITEBOX_CMD") or sys.executable or "python"
    raw = os.environ.get("MDCG_WHITEBOX_ARGS")
    args = raw.split() if raw else ["-m", "aeis.mcp.server"]
    return [exe] + args


# --------------------------------------------------------------------------
# 白箱 MCP stdio 客户端（零第三方依赖）
# --------------------------------------------------------------------------

# 生效条件：类无自定义 __init__（无必需构造形参）；实例化后仅当子类覆写 call 时 ask/remember 才走通，否则 call 抛 NotImplementedError。
class _WhiteboxApi:
    """白箱业务接口（`ask` / `remember`）。

    两种载体共享同一实现，保证行为**按构造方式一致**（验证结论不受载体影响）：
      · `LocalWhiteboxClient`       —— 进程内直调自带引擎（默认）
      · `_SubprocessWhiteboxClient` —— MCP stdio 子进程（legacy，显式配置时）
    """

# 生效条件：以 required 形参 name 与 args 调用该抽象方法时无条件抛出 NotImplementedError，不产生任何返回。
    def call(self, name, args):
        """调用白箱工具，返回 {isError, text, data}。"""
        raise NotImplementedError

# 生效条件：给定 required 形参 message（session_id 省略时取默认 "md_cg-whitebox-verify"）即转调 self.call("wisdom_chat", {...})，按返回 r 组装 {ok: not r["isError"], route: _extract_route(data), reply: _extract_reply(data, r.get("text")), raw}，其中 data 由 r.get("data") or {} 得到（data 缺失或为假值时为 {}），故 raw 恒取该 data、不回落到 r.get("text")。
    def ask(self, message, session_id="md_cg-whitebox-verify"):
        """白箱问答（wisdom_chat）。返回归一化的 {ok, route, reply, raw}。"""
        r = self.call("wisdom_chat", {"message": message, "session_id": session_id})
        data = r.get("data") or {}
        return {"ok": not r["isError"],
                "route": _extract_route(data),
                "reply": _extract_reply(data, r.get("text")),
                "raw": data if data is not None else r.get("text")}

# 生效条件：给定 required 形参 content（importance 省略时取 0.9 并 float() 转换；tags 为 None/[]/"" 等假值时按 tags or ["md_cg","whitebox-probe"] 回落为 list(["md_cg","whitebox-probe"])）即转调 self.call("remember", {...})，返回 {ok: not r["isError"], raw: r.get("data") or r.get("text")}。
    def remember(self, content, importance=0.9, tags=None):
        """白箱编码（remember）：把一条知识交给白箱写入其记忆库。"""
        r = self.call("remember", {"content": content,
                                   "importance": float(importance),
                                   "tags": list(tags or ["md_cg", "whitebox-probe"])})
        return {"ok": not r["isError"], "raw": r.get("data") or r.get("text")}


class _SubprocessWhiteboxClient(_WhiteboxApi):
    """外部白箱 MCP stdio 客户端（legacy 路径，需显式配置才启用）。

    只做一件事：把 md_cg 的显式调用翻译成 MCP `tools/call`。
    进程懒启动、调用串行化、超时即杀（下次调用自动重启）。
    """

# 生效条件：cmd 为真值时 self.cmd=list(cmd)，否则回落 _launch_cmd()；timeout 为真值则直接用，否则回落 os.environ.get("MDCG_WHITEBOX_TIMEOUT")，再否则 60.0；env 为真值时其键值经 str() 合并进 os.environ 副本。
    def __init__(self, cmd=None, env=None, timeout=None):
        self.cmd = list(cmd) if cmd else _launch_cmd()
        self.timeout = float(timeout or os.environ.get("MDCG_WHITEBOX_TIMEOUT") or 60.0)
        self.env = dict(os.environ)
        if env:
            self.env.update({k: str(v) for k, v in env.items()})
        self.proc = None
        self._q = queue.Queue()
        self._next_id = 1
        self._lock = threading.Lock()

    # -- 生命周期 ---------------------------------------------------------
# 生效条件：当 self.proc 非 None 且 self.proc.poll() 为 None 时直接返回 self；否则启动 self.cmd 子进程并以模块级常量 PROTOCOL_VERSION 与 CLIENT_NAME 发 initialize 请求和 notifications/initialized 通知后返回 self。
    def start(self):
        if self.proc is not None and self.proc.poll() is None:
            return self
        self.proc = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, env=self.env)
        threading.Thread(target=self._reader, daemon=True).start()
        self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": CLIENT_NAME, "version": "0.1.0"},
        })
        self._notify("notifications/initialized", {})
        return self

    def close(self):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # -- 内部 IO ----------------------------------------------------------
# 生效条件：self.proc 为 None 或 proc.stdout 为 None 时直接返回；否则逐行 strip 后跳过空行，非空行 json.loads 成功则放入 self._q，抛 ValueError 则跳过该行。
    def _reader(self):
        stream = self.proc.stdout if self.proc else None
        if stream is None:
            return
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                self._q.put(json.loads(line))
            except ValueError:
                continue

# 生效条件：给定 required 形参 payload 时，若 self.proc is None 或 self.proc.poll() is not None 则抛 RuntimeError("白箱进程未运行（启动失败或已退出）")，否则把 json.dumps(payload, ensure_ascii=False) + "\n" 写入 self.proc.stdin 并 flush，无返回。
    def _write(self, payload):
        if self.proc is None or self.proc.poll() is not None:
            raise RuntimeError("白箱进程未运行（启动失败或已退出）")
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

# 生效条件：给定 required 形参 method 与 params 时，以 {"jsonrpc": "2.0", "method": method, "params": params}（无 id）调用 self._write，自身无返回。
    def _notify(self, method, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

# 生效条件：给定 required 形参 method 与 params 时在 self._lock 内取自增 id 并写入请求，随后循环取 self._q：remain <= 0 或 queue.Empty 时先 self.close() 再抛 TimeoutError，msg.get("id") 不等于 rid 时 continue，msg.get("error") 为真时抛 RuntimeError，id 匹配且无 error 时返回 msg.get("result")（缺 "result" 键返回 None）。
    def _request(self, method, params):
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            self._write({"jsonrpc": "2.0", "id": rid, "method": method,
                         "params": params})
            deadline = time.time() + self.timeout
            while True:
                remain = deadline - time.time()
                if remain <= 0:
                    self.close()
                    raise TimeoutError(f"白箱调用超时（{self.timeout}s）：{method}")
                try:
                    msg = self._q.get(timeout=remain)
                except queue.Empty:
                    self.close()
                    raise TimeoutError(f"白箱调用超时（{self.timeout}s）：{method}")
                if msg.get("id") != rid:
                    continue
                if msg.get("error"):
                    raise RuntimeError(f"白箱返回错误：{msg['error']}")
                return msg.get("result")

    # -- 业务接口 ---------------------------------------------------------
# 生效条件：给定 required 形参 name 与 args（args 为假值时按 {"name": name, "arguments": args or {}} 发空字典）即以 "tools/call" 发请求，把结果 content 中 type=="text" 的块文本拼接后 json.loads，失败（ValueError/TypeError）则 data=None，返回 {"isError": bool((result or {}).get("isError")), "text": text, "data": data}。
    def call(self, name, args):
        """调用白箱 MCP 工具，返回 {isError, text, data}。"""
        result = self._request("tools/call", {"name": name, "arguments": args or {}})
        text = ""
        for block in (result or {}).get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text += block.get("text") or ""
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            data = None
        return {"isError": bool((result or {}).get("isError")),
                "text": text, "data": data}

# --------------------------------------------------------------------------
# 进程内白箱客户端（默认路径）+ 客户端工厂
# --------------------------------------------------------------------------

class LocalWhiteboxClient(_WhiteboxApi):
    """白箱**进程内**客户端（默认载体）。

    白箱知识库已随主仓自带（`md_cg/whitebox_kb/`），直接调用其引擎：
    无子进程、无 MCP、无理论仓依赖。接口与子进程版完全一致，
    故 `ask / remember / ping / verify_*` 及其留痕逻辑无需任何改动。
    """

    def __init__(self, db_path=None, **_ignored):
        self.db_path = db_path
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = _load_get_engine()(db_path=self.db_path)
        return self._engine

    # -- 生命周期（与子进程版语义对齐：start 即确保可用，失败即抛） --------
    def start(self):
        _ = self.engine.service_info()
        return self

    def close(self):
        if self._engine is not None:
            self._engine.close()
            self._engine = None

    # -- 业务接口 ---------------------------------------------------------
# 生效条件：给定 required 形参 name 与 args 时直接转调 self.engine.call_tool(name, args) 并返回其结果，不做任何形参改写或校验。
    def call(self, name, args):
        """调用白箱工具，返回 {isError, text, data}（形状对齐 MCP）。"""
        return self.engine.call_tool(name, args)


# 生效条件：无必需形参；包内 from .whitebox_kb.engine import get_engine 成功时返回它，ImportError 时改为 from whitebox_kb.engine import get_engine 并返回。
def _load_get_engine():
    """兼容两种导入方式（包内 / 平铺）。"""
    try:
        from .whitebox_kb.engine import get_engine
    except ImportError:  # pragma: no cover - 平铺运行场景
        from whitebox_kb.engine import get_engine
    return get_engine


# 生效条件：cmd 或 env 为真，或 MDCG_WHITEBOX_CMD / MDCG_WHITEBOX_ARGS 为真时返回 _SubprocessWhiteboxClient(cmd=cmd, env=env, timeout=timeout)，否则返回 LocalWhiteboxClient(db_path=db_path)。
def WhiteboxClient(cmd=None, env=None, timeout=None, db_path=None):
    """白箱客户端工厂。

    默认返回 `LocalWhiteboxClient`（进程内 · 随仓自带知识库）。
    仅当显式给出 `cmd` / `env`，或设置了 `MDCG_WHITEBOX_CMD` /
    `MDCG_WHITEBOX_ARGS` 时，才返回 legacy 的外部 MCP 子进程客户端。
    """
    if cmd or env or os.environ.get("MDCG_WHITEBOX_CMD") \
            or os.environ.get("MDCG_WHITEBOX_ARGS"):
        return _SubprocessWhiteboxClient(cmd=cmd, env=env, timeout=timeout)
    return LocalWhiteboxClient(db_path=db_path)


# --------------------------------------------------------------------------
# 结果归一化
# --------------------------------------------------------------------------

# 生效条件：data 为 dict 时按 route、mode、path 顺序取首个非空 str 值返回，否则（含 data 非 dict、三键均无或均为空/非 str）返回 ""。
def _extract_route(data):
    if isinstance(data, dict):
        for key in ("route", "mode", "path"):
            val = data.get(key)
            if isinstance(val, str) and val:
                return val
    return ""


# 生效条件：data 为 dict 时先按 reply/answer/text/response/content/message 取首个 strip 后非空的 str 返回，再对 result、data 两键的 dict 值递归取非空结果，均无则返回 fallback or ""。
def _extract_reply(data, fallback=""):
    if isinstance(data, dict):
        for key in ("reply", "answer", "text", "response", "content", "message"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val
        for key in ("result", "data"):
            val = data.get(key)
            if isinstance(val, dict):
                nested = _extract_reply(val, "")
                if nested:
                    return nested
    return fallback or ""


# --------------------------------------------------------------------------
# 验证：编码能力 / 已有知识回答能力
# --------------------------------------------------------------------------

# 生效条件：client 为 None 时自建 WhiteboxClient() 并在 finally 关闭；marker、fact、question 为假值时分别用带毫秒时间戳的默认口令、默认事实、默认追问，cg 仅传给 _record（cg 为 None 则 node_id 为 None，不自建 client），异常时返回 ok=False 并同样 _record。
def verify_encoding(cg=None, client=None, marker=None, fact=None,
                    question=None, session_id="md_cg-whitebox-verify"):
    """验证白箱「编码能力」。

    步骤：remember 一条带唯一口令的事实 → 追问口令 → 命中即通过。
    """
    own = client is None
    cli = client or WhiteboxClient()
    marker = marker or ("白箱探针" + str(int(time.time() * 1000)))
    fact = fact or f"md_cg 白箱编码验证：本次口令是 {marker}，请记住。"
    question = question or "请只回答刚才记住的口令本身，不要解释。"
    try:
        cli.start()
        enc = cli.remember(fact, importance=0.95, tags=["md_cg", "whitebox-probe"])
        ans = cli.ask(question, session_id=session_id)
        hit = marker in (ans.get("reply") or "")
        out = {"kind": "encoding", "ok": bool(enc["ok"] and hit),
               "marker": marker, "encoded": bool(enc["ok"]),
               "recalled": hit, "route": ans.get("route"),
               "reply": (ans.get("reply") or "")[:300]}
        out["node_id"] = _record(cg, "encoding", out["ok"], out)
        return out
    except Exception as exc:  # 白箱不可用：如实记录失败，不抛断调用方
        out = {"kind": "encoding", "ok": False, "marker": marker,
               "error": f"{type(exc).__name__}: {exc}"}
        out["node_id"] = _record(cg, "encoding", False, out)
        return out
    finally:
        if own:
            cli.close()


# 生效条件：client 为 None 时自建 WhiteboxClient() 并在 finally 关闭；questions 为假值（None 或空）时用 DEFAULT_KNOWLEDGE_PROBES，逐问后仅当至少一问 reply 非空且 route 为 self 或 self_fallback 时 ok=True，异常返回 ok=False。
def verify_existing(cg=None, client=None, questions=None,
                    session_id="md_cg-whitebox-verify"):
    """验证白箱「已有知识回答能力」。

    步骤：问白箱本应已知的问题 → route=self 且回答非空即通过（至少一问命中）。
    """
    own = client is None
    cli = client or WhiteboxClient()
    questions = list(questions or DEFAULT_KNOWLEDGE_PROBES)
    try:
        cli.start()
        probes = []
        for q in questions:
            ans = cli.ask(q, session_id=session_id)
            route = ans.get("route") or ""
            reply = ans.get("reply") or ""
            probes.append({"question": q, "route": route,
                           "answered": bool(reply.strip()),
                           "self_route": route in ("self", "self_fallback"),
                           "reply": reply[:300]})
        ok = any(p["answered"] and p["self_route"] for p in probes)
        out = {"kind": "existing_knowledge", "ok": ok, "probes": probes}
        out["node_id"] = _record(cg, "existing_knowledge", ok, out)
        return out
    except Exception as exc:
        out = {"kind": "existing_knowledge", "ok": False,
               "error": f"{type(exc).__name__}: {exc}"}
        out["node_id"] = _record(cg, "existing_knowledge", False, out)
        return out
    finally:
        if own:
            cli.close()


# 生效条件：client 为 None 时自建 WhiteboxClient() 并在 finally 关闭；依次对 service_info、mdcg_service_info、info 调用 call，首个 isError 为假即返回 ok=True 与该 tool/info，全部不可用返回 ok=False，start 或整体异常返回 ok=False。
def ping(client=None, session_id="md_cg-whitebox-ping"):
    """白箱连通性探测：调 service_info（或 info）判断能力库是否在线。"""
    own = client is None
    cli = client or WhiteboxClient()
    try:
        cli.start()
        for name in ("service_info", "mdcg_service_info", "info"):
            try:
                r = cli.call(name, {})
                if not r["isError"]:
                    return {"ok": True, "tool": name,
                            "info": r.get("data") or r.get("text")}
            except Exception:
                continue
        return {"ok": False, "error": "白箱在线但未找到 service_info/info 工具"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if own:
            cli.close()


# 生效条件：client 为 None 时以 WhiteboxClient(timeout=kw.get("timeout")) 自建并在 finally 关闭；随后 cli.start() 并返回 cli.ask(message, session_id=session_id)。
def ask(message, session_id="md_cg-whitebox-verify", client=None, **kw):
    """显式调用白箱回答一个问题。"""
    own = client is None
    cli = client or WhiteboxClient(timeout=kw.get("timeout"))
    try:
        cli.start()
        return cli.ask(message, session_id=session_id)
    finally:
        if own:
            cli.close()


# 生效条件：client 为 None 时以 WhiteboxClient(timeout=kw.get("timeout")) 自建并在 finally 关闭；随后 cli.start() 并返回 cli.remember(content, importance=importance, tags=tags)。
def remember(content, importance=0.9, tags=None, client=None, **kw):
    """显式调用白箱编码一条知识。"""
    own = client is None
    cli = client or WhiteboxClient(timeout=kw.get("timeout"))
    try:
        cli.start()
        return cli.remember(content, importance=importance, tags=tags)
    finally:
        if own:
            cli.close()


# --------------------------------------------------------------------------
# 留痕与报告
# --------------------------------------------------------------------------

# 生效条件：cg 为 None 时返回 None；否则以 whitebox_verify_{kind}_{毫秒时间戳} 为 id 调 cg.add 写入 self 层，成功返回该 nid，cg.add 抛异常时返回 None。
def _record(cg, kind, ok, payload):
    """把验证结论写入认知图（self 层）。失败不阻断验证本身。"""
    if cg is None:
        return None
    nid = f"whitebox_verify_{kind}_{int(time.time() * 1000)}"
    body = json.dumps(payload, ensure_ascii=False, default=str)[:1800]
    try:
        cg.add(nid, f"[白箱能力验证·{kind}] ok={ok} {body}",
               layer="self", tags=[VERIFY_TAG, f"whitebox:{kind}"],
               importance=0.6, verification_basis="test",
               consistency=False)
        return nid
    except Exception:
        return None


# 生效条件：cg 为 None 时返回 {'ok': False, 'error': '需要 cg 实例'}；否则以 k=int(limit or 20)（limit 为 0/空串/None 时 k 变 20）调 cg.search("白箱能力验证", layer="self", record=False)，只保留 tags 中任一以 "whitebox:" 开头的项并返回 count 与 items。
def report(cg=None, limit=20):
    """汇总最近的「白箱能力验证」留痕。"""
    if cg is None:
        return {"ok": False, "error": "需要 cg 实例"}
    res, _meta = cg.search("白箱能力验证", layer="self",
                           k=int(limit or 20), record=False)
    items = []
    for node, score, _q in res:
        fm = node.get("frontmatter") or {}
        tags = fm.get("tags") or []
        if not any(isinstance(t, str) and t.startswith("whitebox:") for t in tags):
            continue
        items.append({"id": node.get("id"), "score": score, "tags": tags,
                      "content": (node.get("content") or "")[:800]})
    return {"ok": True, "count": len(items), "items": items}


# --------------------------------------------------------------------------
# MCP 统一入口（由 mcp_server._whitebox_call 调用）
# --------------------------------------------------------------------------

# 生效条件：action=(args.action or "ping") 小写后，ask/chat/query 走 ask（question/message/query 均假则传 ""），remember/encode/write 走 remember 且 importance=float(a.get("importance", 0.9))，verify_encoding/encoding 走 verify_encoding，verify_existing/existing/knowledge 走 verify_existing（questions 取 a.questions 或 a.question 单元素列表），report/history 走 report(limit=int(a.get("limit") or 20))，ping/status/info 走 ping()，其余抛 ValueError。
def dispatch(cg, args):
    """cg(op=whitebox) 的分发：action=ask|remember|verify_encoding|verify_existing|ping|report。"""
    a = args or {}
    action = (a.get("action") or "ping").strip().lower()
    if action in ("ask", "chat", "query"):
        return ask(a.get("question") or a.get("message") or a.get("query") or "",
                   session_id=a.get("session_id") or "md_cg-whitebox-verify")
    if action in ("remember", "encode", "write"):
        return remember(a.get("content") or a.get("text") or "",
                        importance=float(a.get("importance", 0.9)),
                        tags=a.get("tags"))
    if action in ("verify_encoding", "encoding"):
        return verify_encoding(cg, marker=a.get("marker"), fact=a.get("fact"),
                               question=a.get("question"),
                               session_id=a.get("session_id") or "md_cg-whitebox-verify")
    if action in ("verify_existing", "existing", "knowledge"):
        qs = a.get("questions") or ([a["question"]] if a.get("question") else None)
        return verify_existing(cg, questions=qs,
                               session_id=a.get("session_id") or "md_cg-whitebox-verify")
    if action in ("report", "history"):
        return report(cg, limit=int(a.get("limit") or 20))
    if action in ("ping", "status", "info"):
        return ping()
    raise ValueError(f"whitebox 未知 action：{action}")


if __name__ == "__main__":  # 手动自检：python -m md_cg.whitebox
    print(json.dumps(ping(), ensure_ascii=False, indent=2))