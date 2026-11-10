#!/usr/bin/env python3
"""md_cg HTTP 常驻入口（E1 判据 / 账62 的正解）。

**为什么需要它**：`md_cg/mcp_server.py` 是**纯 stdio**（`main()` 读 `sys.stdin` 逐行），
`run-server.sh` 头注释写明它是给「DSH 插件经 ssh stdio 直通」用的。systemd 把一个
stdio server 当 daemon 起，stdin 立刻 EOF → 3 秒退出、`SuccessExitStatus=0` 不算失败
→ 永不重启（2026-10-12 16:45:48 起就死了）。结果：接真库的 **31 个 mdcg_* 工具**
一个都不在线（账62），而网关那 8 个记忆工具对着 0 条的 Mem0。

**本文件不改 `mcp_server.py` 一行**——只把它的 `_serve_line(cg, msg)` 包进 HTTP：
    POST /mcp    单条 JSON-RPC（MCP streamable-http 的 JSON 响应模式）
    GET  /health 就绪探测（不带认证）
    GET  /mcp    405（本实现不推流，客户端要用 push 请另接）
认证：`Authorization: Bearer $MDCG_TOKEN`，与 stdio 版同一把令牌（`verify_token`）。

单例 `cg` + 全局锁：`_serve_line` 与 `MdCGSecure` 都不是多线程安全的，单用户场景串行化足够。
"""
import io
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_env(path: str = os.path.expanduser("~/.mdcg/run-server.env")) -> None:
    """把 `export K=V` 格式的部署环境读进来（systemd 的 EnvironmentFile 不认 export 前缀）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:]
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
    except OSError:
        pass


_load_env()
os.environ.setdefault("MDCG_ROOT", "/home/ubuntu/mdcg-data")   # 部署事实；可用 MDCG_ROOT 覆盖
os.environ.setdefault("MDCG_ACTOR", "dsh-memory")
os.environ.setdefault("MDCG_TENANT", "default")
os.environ.setdefault("MDCG_CLEARANCE", "private")

# 部署级默认密级：与 run-server.sh 同一条纪律（未声明 sensitivity 的写入落成密文）
try:
    import seal_default_private as _seal
    _seal.pin_default_sensitivity(os.environ.get("MDCG_DEFAULT_SENSITIVITY", "private"))
except Exception:                                  # noqa: BLE001  钉不上就按上游缺省跑
    pass

from md_cg import mcp_server, mdcos               # noqa: E402
from md_cg.tokens import verify_token             # noqa: E402

_LOCK = threading.Lock()
_CG = None
_STARTED = 0.0


# R1（账 158 冷启 / 判据 E 组）：/health 必须能区分「进程起来了」与「随时能查」。
#
# 冷启首查 25.7 秒（10,801 节点全解密）只在**第一次检索**发生；进程早已 listening，
# 所以只看 TCP 探活会把「还没预热」报成健康。这里起一个后台线程跑一次空转检索，
# 把 idf / postings / 指纹载入做掉，并把状态暴露成 warm。
_WARM = {"ready": False, "took_s": None, "error": None}


def _warm_bg() -> None:
    import time as _t
    t0 = _t.time()
    try:
        cg = _cg()
        cg.search("预热", k=1, record=False)
        _WARM["ready"] = True
    except Exception as exc:                   # noqa: BLE001
        _WARM["error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        _WARM["took_s"] = round(_t.time() - t0, 2)


def _cg():
    global _CG, _STARTED
    if _CG is None:
        tok = (os.environ.get("MDCG_TOKEN") or "").strip()
        if not tok:
            raise RuntimeError("MDCG_TOKEN 未设置（应来自 ~/.mdcg/run-server.env）")
        principal = verify_token(tok)
        _CG = mdcos.MdCGSecure(os.environ["MDCG_ROOT"], principal=principal, autoflush=8)
        import time
        _STARTED = time.time()
    return _CG


def _dispatch(msg):
    """把一条 JSON-RPC 交给 stdio 版的分派器，截下它写到 stdout 的应答。"""
    raw = io.BytesIO()
    buf = io.TextIOWrapper(raw, encoding="utf-8", newline="")
    old, sys.stdout = sys.stdout, buf
    try:
        mcp_server._serve_line(_cg(), msg)
        buf.flush()
    finally:
        sys.stdout = old
    out = raw.getvalue().decode("utf-8", "replace").strip()
    return out.splitlines()[0] if out else ""


class _H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "mdcg-http/1.0"

    def log_message(self, fmt, *args):             # noqa: A003  静音访问日志
        pass

    def _send(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def do_GET(self):                              # noqa: N802
        if self.path.rstrip("/") in ("/health", "/healthz"):
            import time
            try:
                cg = _cg()
                nodes = len(cg.index.get("nodes") or {})
                ok, why = True, None
            except Exception as exc:               # noqa: BLE001
                cg, nodes, ok, why = None, None, False, "%s: %s" % (type(exc).__name__, exc)
            return self._send(200 if ok else 503,
                              {"ok": ok, "why": why, "backend": "lingshu",
                               "root": os.environ.get("MDCG_ROOT"), "nodes": nodes,
                               "warm": _WARM["ready"],
                               "warm_s": _WARM["took_s"],
                               "warm_error": _WARM["error"],
                               "pid": os.getpid(),
                               "uptime_s": round(time.time() - _STARTED, 1) if _STARTED else 0})
        return self._send(405, {"error": "use POST /mcp"})

    def do_POST(self):                             # noqa: N802
        if not self.path.startswith("/mcp"):
            return self._send(404, {"error": "not found"})
        tok = (os.environ.get("MDCG_TOKEN") or "").strip()
        if tok:
            got = (self.headers.get("Authorization") or "").strip()
            if got != "Bearer " + tok:
                return self._send(401, {"error": "unauthorized"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw_body = self.rfile.read(n) if n else b""
        try:
            msg = json.loads(raw_body.decode("utf-8", "replace"))
        except Exception:                          # noqa: BLE001
            return self._send(400, {"jsonrpc": "2.0", "id": None,
                                    "error": {"code": -32700, "message": "parse error"}})
        with _LOCK:
            try:
                line = _dispatch(msg)
            except Exception as exc:               # noqa: BLE001  单条请求不得带走服务
                return self._send(500, {"jsonrpc": "2.0",
                                        "id": (msg or {}).get("id"),
                                        "error": {"code": -32603,
                                                  "message": "%s: %s" % (type(exc).__name__, exc)}})
        if not line:                               # 通知类：MCP 规范要求 202 无体
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            resp = json.loads(line)
        except Exception:                          # noqa: BLE001
            return self._send(500, {"jsonrpc": "2.0", "id": (msg or {}).get("id"),
                                    "error": {"code": -32603,
                                              "message": "bad reply: " + line[:300]}})
        return self._send(200, resp)


def main() -> int:
    port = int(os.environ.get("MDCG_HTTP_PORT") or 8301)
    host = os.environ.get("MDCG_HTTP_HOST") or "127.0.0.1"
    _cg()                                      # 启动即验：拿不到凭据就别假装在线
    import threading
    threading.Thread(target=_warm_bg, name="warm", daemon=True).start()
    srv = ThreadingHTTPServer((host, port), _H)
    sys.stderr.write("[mdcg-http] listening on http://%s:%d/mcp  root=%s\n"
                     % (host, port, os.environ.get("MDCG_ROOT")))
    sys.stderr.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        global _CG
        if _CG is not None:
            try:
                _CG.close()                    # 账47：close 才会把 _index.json 落盘
            except Exception:                  # noqa: BLE001
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
