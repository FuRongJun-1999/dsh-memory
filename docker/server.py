#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
灵枢记忆服务 Docker 入口（纯 stdlib http.server · 零外部依赖）
============================================================
REST API 暴露 aeis 大脑的 HTTP 记忆能力（供 DSH 插件 / 任意客户端经 HTTP 连接）：
  POST /remember   写入记忆（content/tags/importance）
  GET  /recall     检索记忆（query）
  GET  /search     语义检索
  GET  /timeline   时间线
  GET  /status     服务与库状态
  POST /selfcheck  安全自检跑分
所有响应 JSON。CORS 放行（允许跨源对接）。
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 确保能找到 aeis（源码 COPY 进 /app，或在 site-packages）
sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aeis.api import Agent  # noqa: E402

DB_PATH = os.environ.get("LINGSHU_DB", "/data/lingshu.db")
PORT = int(os.environ.get("PORT", "8080"))


def _ensure_agent():
    """单例 Agent（容器生命周期），库自动创建。"""
    global _AGENT
    if _AGENT is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _AGENT = Agent(db_path=DB_PATH, identity="灵枢")
    return _AGENT


def _serialize(obj):
    """把任意返回（STNode/Tuple/Dict/List）转 JSON 可序列化 dict。"""
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(x) for x in obj]
    if hasattr(obj, "__dict__"):
        d = vars(obj)
        return {k: _serialize(v) for k, v in d.items()
                if isinstance(v, (str, int, float, bool, dict, list, tuple, type(None)))}
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


_AGENT = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 静默访问日志

    # ---- CORS ----
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Type", "application/json")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _send(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n) if n else self._read_chunked()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    def _read_chunked(self) -> bytes:
        return b""

    # ---- 路由 ----
    def do_GET(self):
        path = self.path.split("?")[0]
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        try:
            if path == "/status":
                a = _ensure_agent()
                info = a.self_check() if hasattr(a, "self_check") else {}
                self._send(200, {"ok": True, "identity": "灵枢", "db": DB_PATH, "status": info})
            elif path == "/recall":
                q = qs.get("query", [""])[0]
                a = _ensure_agent()
                r = a.recall(q, limit=int(qs.get("limit", ["5"])[0]))
                self._send(200, {"ok": True, "query": q, "results": _serialize(r)})
            elif path == "/search":
                q = qs.get("query", [""])[0]
                a = _ensure_agent()
                r = a.search(q, limit=int(qs.get("limit", ["5"])[0]))
                self._send(200, {"ok": True, "query": q, "results": _serialize(r)})
            elif path == "/timeline":
                a = _ensure_agent()
                r = list(a.timeline(limit=int(qs.get("limit", ["10"])[0])))
                self._send(200, {"ok": True, "results": _serialize(r)})
            else:
                self._send(404, {"error": f"not found: {path}"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def do_POST(self):
        path = self.path.split("?")[0]
        body = self._read_body()
        try:
            if path == "/remember":
                a = _ensure_agent()
                r = a.remember(body.get("content", ""), importance=body.get("importance", 0.6),
                               tags=body.get("tags"))
                self._send(200, {"ok": True, "node": _serialize(r)})
            elif path == "/selfcheck":
                import subprocess
                # P1 修复（GPT 审查）：仓库实际文件是 selfcheck.py——
                # 此前 import demo_selfcheck（不存在）→ /selfcheck 恒 500
                from selfcheck import run_selfcheck
                out = run_selfcheck()  # 返回 dict
                self._send(200, {"ok": True, "report": out})
            else:
                self._send(404, {"error": f"not found: {path}"})
        except Exception as e:
            self._send(500, {"error": str(e)})


def main():
    print(f"灵枢记忆服务启动: http://0.0.0.0:{PORT}   DB={DB_PATH}", flush=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("停止", flush=True)


if __name__ == "__main__":
    main()
