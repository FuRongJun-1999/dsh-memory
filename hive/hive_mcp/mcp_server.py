# -*- coding: utf-8 -*-
"""灵枢蜂巢 · MCP server（蜂群多智能体并发运行时对外接口）。

形态对齐 md_cg/mcp_server.py：手写 stdio JSON-RPC 2.0，零第三方依赖。
与 hive 的通信走**文件协议**（jobs/<id>/{spec,status,result,kill} + _serve.json
心跳），零 IPC 依赖；serve 未存活时 spawn/poll 自动拉起（detached）。

启动：
    HIVE_JOBS_DIR=<jobs 目录> python -m hive.hive_mcp.mcp_server
（hive/ 为 python 包：PYTHONPATH 指向 dsh-memory 仓根）

工具面（4 个）：
  hive_spawn   提交任务（model/user_prompt 必填；system_prompt/context_files/
               timeout_s/max_tokens/temperature 可选）→ job_id 毫秒即返
  hive_poll    查状态：传 job_id 单查（含全文），不传=活跃任务摘要
               （content 截断 800 字防上下文爆炸，全文读 result_path）
  hive_kill    写 kill 标志（worker ≤1s 强杀）
  hive_doctor  serve 存活 / 任务状态统计 / env 检查 / 启动指引

env：HIVE_JOBS_DIR（默认 <仓>/hive/jobs）、HIVE_EXE（默认 <仓>/hive/target/
release/hive.exe，自动探测）、HIVE_API_KEY / HIVE_API_BASE / HIVE_WORKERS
（由 serve 进程环境透传给执行器）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid

SERVER_NAME = "hive-mcp"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _jobs_dir() -> str:
    d = os.environ.get("HIVE_JOBS_DIR") or os.path.join(REPO, "hive", "jobs")
    os.makedirs(d, exist_ok=True)
    return d


def _exe_path() -> str:
    exe = os.environ.get("HIVE_EXE")
    if exe:
        return exe
    name = "hive.exe" if os.name == "nt" else "hive"
    return os.path.join(REPO, "hive", "target", "release", name)


# ---------------------------------------------------------------- serve 管理

def _serve_alive(jobs: str) -> bool:
    """serve 心跳新鲜度（<5s）判活。"""
    p = os.path.join(jobs, "_serve.json")
    try:
        with open(p, encoding="utf-8") as f:
            hb = json.load(f)
        return (time.time() - hb.get("ts", 0) / 1000.0) < 5.0
    except (OSError, ValueError):
        return False


def _ensure_serve(jobs: str) -> dict:
    """serve 未存活则 detached 拉起；返回 {started: bool, note: str}。"""
    if _serve_alive(jobs):
        return {"started": False, "note": "serve 存活"}
    exe = _exe_path()
    if not os.path.isfile(exe):
        return {
            "started": False,
            "note": f"serve 未运行且未找到可执行文件 {exe}——先 cargo build --release（hive/ 下）",
        }
    log_path = os.path.join(jobs, "_serve.log")
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True
    with open(log_path, "ab") as logf:
        subprocess.Popen(
            [exe, "serve", "--jobs", jobs],
            stdout=logf,
            stderr=logf,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
    for _ in range(30):
        if _serve_alive(jobs):
            return {"started": True, "note": "serve 已自动拉起"}
        time.sleep(0.1)
    return {"started": True, "note": "serve 已拉起（心跳未就绪，稍后自愈）"}


# ---------------------------------------------------------------- 工具实现

def _submit(jobs: str, spec: dict) -> str:
    job_id = f"h{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    d = os.path.join(jobs, job_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "job_id": job_id,
                "state": "pending",
                "created_ts": int(time.time() * 1000),
                "started_ts": None,
                "heartbeat_ts": None,
                "elapsed_s": 0.0,
                "timeout_s": spec.get("timeout_s", 300),
                "model": spec.get("model"),
                "pid": None,
                "error": None,
            },
            f,
            ensure_ascii=False,
        )
    return job_id


def _read_status(jobs: str, job_id: str):
    p = os.path.join(jobs, job_id, "status.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _result_view(job_dir: str, head):
    p = os.path.join(job_dir, "result.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            r = json.load(f)
    except (OSError, ValueError) as e:
        return {"error": f"result.json 解析失败: {e}"}
    content = r.get("content") or ""
    if head is not None and len(content) > head:
        r = dict(r)
        r["content_head"] = content[:head]
        r["content_truncated"] = True
        r.pop("content", None)
    r["result_path"] = p
    return r


def _t_spawn(a: dict) -> dict:
    if not (a.get("model") or "").strip():
        return {"ok": False, "error": "缺必填参数 model"}
    if not (a.get("user_prompt") or "").strip():
        return {"ok": False, "error": "缺必填参数 user_prompt"}
    jobs = _jobs_dir()
    for rel in a.get("context_files") or []:
        path = rel if os.path.isabs(rel) else os.path.join(os.getcwd(), rel)
        if not os.path.isfile(path):
            return {"ok": False, "error": f"context 文件不存在: {path}"}
    ensure = _ensure_serve(jobs)
    spec = {"model": a["model"].strip(), "user_prompt": a["user_prompt"]}
    if a.get("system_prompt"):
        spec["system_prompt"] = a["system_prompt"]
    if a.get("context_files"):
        spec["context_files"] = a["context_files"]
    if a.get("timeout_s"):
        spec["timeout_s"] = int(a["timeout_s"])
    if a.get("max_tokens"):
        spec["max_tokens"] = a["max_tokens"]
    if a.get("temperature") is not None:
        spec["temperature"] = a["temperature"]
    spec["workdir"] = os.getcwd()
    job_id = _submit(jobs, spec)
    return {
        "ok": True,
        "job_id": job_id,
        "jobs_dir": jobs,
        "serve": ensure,
        "hint": "hive_poll(job_id) 轮询；done 后 result.content_head 取摘要、result_path 读全文",
    }


def _t_poll(a: dict) -> dict:
    jobs = _jobs_dir()
    job_id = a.get("job_id")
    if job_id:
        d = os.path.join(jobs, job_id)
        if not os.path.isdir(d):
            return {"ok": False, "error": f"任务不存在: {job_id}"}
        st = _read_status(jobs, job_id) or {"error": "status 不可读"}
        st["result"] = _result_view(d, head=None)  # 单查给全文
        return {"ok": True, "job": st}
    ids = sorted(
        n for n in os.listdir(jobs)
        if n.startswith("h") and os.path.isdir(os.path.join(jobs, n))
    )
    active_states = {"pending", "claimed", "running"}
    items = []
    for jid in ids:
        st = _read_status(jobs, jid)
        if not st:
            continue
        active = st.get("state") in active_states
        recent_done = st.get("state") in {"done", "error", "timeout", "killed"} and (
            time.time() * 1000 - (st.get("heartbeat_ts") or st.get("created_ts") or 0)
        ) < 3600_000
        if not (active or recent_done):
            continue
        st["result"] = _result_view(os.path.join(jobs, jid), head=800)  # 摘要防爆炸
        items.append(st)
    return {"ok": True, "count": len(items), "jobs": items}


def _t_kill(a: dict) -> dict:
    jobs = _jobs_dir()
    job_id = a.get("job_id") or ""
    d = os.path.join(jobs, job_id)
    if not os.path.isdir(d):
        return {"ok": False, "error": f"任务不存在: {job_id}"}
    flag = os.path.join(d, "kill")
    if not os.path.exists(flag):
        open(flag, "w").close()
    return {"ok": True, "job_id": job_id, "hint": "worker 检测到 kill 标志后强杀（≤1s）"}


def _t_doctor(_a: dict) -> dict:
    jobs = _jobs_dir()
    exe = _exe_path()
    states = {}
    for jid in sorted(
        n for n in os.listdir(jobs)
        if n.startswith("h") and os.path.isdir(os.path.join(jobs, n))
    ):
        st = _read_status(jobs, jid)
        s = (st or {}).get("state") or "unknown"
        states[s] = states.get(s, 0) + 1
    return {
        "ok": True,
        "serve_alive": _serve_alive(jobs),
        "exe_found": os.path.isfile(exe),
        "exe_path": exe,
        "jobs_dir": jobs,
        "task_states": states,
        "env": {
            "api_key_set": bool(os.environ.get("HIVE_API_KEY")),
            "api_base": os.environ.get("HIVE_API_BASE", "https://open.bigmodel.cn/api/paas/v4"),
            "workers": os.environ.get("HIVE_WORKERS", "4"),
        },
        "start_cmd": "hive serve（或 cargo run -p lingshu-hive -- serve；MCP spawn 会自动拉起）",
    }


# ---------------------------------------------------------------- JSON-RPC 面

TOOLS = [
    {
        "name": "hive_spawn",
        "description": "灵枢蜂巢：提交 LLM 任务到并发队列，毫秒级返回 job_id（后台执行，不阻塞）。rust 并发调度：心跳/超时强杀/kill 全生命周期可观测。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "LLM 模型名（必填）"},
                "user_prompt": {"type": "string", "description": "用户提示词（必填）"},
                "system_prompt": {"type": "string", "description": "系统提示词（可选）"},
                "context_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "上下文文件路径列表（相对 cwd 或绝对，可选）",
                },
                "timeout_s": {"type": "integer", "description": "硬超时秒（默认 300，5..3600）"},
                "max_tokens": {"type": "number", "description": "可选"},
                "temperature": {"type": "number", "description": "可选，[0,2]"},
            },
            "required": ["model", "user_prompt"],
        },
    },
    {
        "name": "hive_poll",
        "description": "灵枢蜂巢：查任务状态。传 job_id 单查（含结果全文）；不传=活跃+近 1h 完成任务摘要（content 截 800 字）。含 elapsed_s/tokens 心跳观测。",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "任务 id（可选）"}},
        },
    },
    {
        "name": "hive_kill",
        "description": "灵枢蜂巢：写 kill 标志，worker 检测后强杀子进程（≤1s），任务终态 killed。",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "任务 id（必填）"}},
            "required": ["job_id"],
        },
    },
    {
        "name": "hive_doctor",
        "description": "灵枢蜂巢：健康检查——serve 存活/可执行文件/任务状态统计/env（密钥只报存在性不回显）/启动指引。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_DISPATCH = {
    "hive_spawn": _t_spawn,
    "hive_poll": _t_poll,
    "hive_kill": _t_kill,
    "hive_doctor": _t_doctor,
}


def _rpc(req: dict):
    method = req.get("method", "")
    rid = req.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = (req.get("params") or {}).get("name", "")
        args = (req.get("params") or {}).get("arguments") or {}
        fn = _DISPATCH.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32602, "message": f"未知工具 {name}"}}
        try:
            out = fn(args)
        except Exception as e:  # noqa: BLE001 —— 工具层兜底不崩 server
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": f"未知方法 {method}"}}
    return None


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        resp = _rpc(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
