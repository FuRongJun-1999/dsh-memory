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


# ---- R-405c（2026-11-10 审计 P2 外围 3）：检索后端可切换 ----
# `MDCG_BACKEND=lingshu`（缺省，Python 内嵌）/ `rust`（server/rust_bridge.py 桥）。
# 纪律：**切到 rust 但桥不通 ⇒ /health 必须报 degraded 且 5xx**，不许静默回落
# 到 Python —— 静默回落等于「读数说是 rust、实际跑的是 Python」，比不可用更糟。
BACKEND = (os.environ.get("MDCG_BACKEND") or "lingshu").strip().lower()
_BACKENDS = ("lingshu", "rust")


def _bridge():
    """取（必要时拉起）Rust 桥；失败返回 (None, 原因) —— 调用方负责报 degraded。"""
    if BACKEND != "rust":
        return None, None
    from . import rust_bridge as _rb
    b = _rb.bridge(os.environ.get("MDCG_ROOT"))
    if b.start() if not b.degraded else False:
        return b, None
    return None, b.error or "rust 桥不可用"


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
            _br, _brwhy = (None, None)
            if BACKEND == "rust":
                try:
                    _br, _brwhy = _bridge()
                except Exception as exc:           # noqa: BLE001
                    _br, _brwhy = None, "%s: %s" % (type(exc).__name__, exc)
                if _br is None:                    # 切了 rust 但桥不通 ⇒ 明确降级
                    ok, why = False, "backend=rust 但桥不可用：%s" % (_brwhy,)
            _bstat = (_br.status() if _br is not None else
                      ({"backend": BACKEND, "degraded": BACKEND == "rust",
                        "error": _brwhy} if BACKEND == "rust" else
                       {"backend": "lingshu", "degraded": False}))
            return self._send(200 if ok else 503,
                              {"ok": ok, "why": why, "backend": BACKEND,
                               "bridge": _bstat,
                               "root": os.environ.get("MDCG_ROOT"), "nodes": nodes,
                               "warm": _WARM["ready"],
                               "warm_s": _WARM["took_s"],
                               "warm_error": _WARM["error"],
                               "pid": os.getpid(),
                               "uptime_s": round(time.time() - _STARTED, 1) if _STARTED else 0})
        return self._send(405, {"error": "use POST /mcp"})

    def _do_search(self):
        """`POST /search {"query": …, "k": …}` —— 按 `MDCG_BACKEND` 选后端（R-405c）。"""
        # 鉴权与 `/mcp` **同一口径**：`/search` 也是对外面，不能因为「只读」就免鉴权
        # （2026-11-11 部署后复核发现：初版漏了这一行，会把检索面开成匿名可读）。
        _tok = (os.environ.get('MDCG_TOKEN') or '').strip()
        if _tok:
            _got = (self.headers.get('Authorization') or '').strip()
            if _got != 'Bearer ' + _tok:
                return self._send(401, {'error': 'unauthorized'})
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = 0
        try:
            _raw = (self.rfile.read(n) if n else b'').decode('utf-8', 'replace')
            body = json.loads(_raw or '{}')
        except Exception:                      # noqa: BLE001
            return self._send(400, {'error': 'parse error'})
        q = str(body.get('query') or '')
        k = int(body.get('k') or 10)
        import time as _t
        t0 = _t.perf_counter()
        if BACKEND == 'rust':
            br, why = _bridge()
            if br is None:
                return self._send(503, {'ok': False, 'backend': 'rust',
                                        'degraded': True, 'error': why,
                                        'hint': '切回 MDCG_BACKEND=lingshu 或先 cargo build --release'})
            try:
                rows = br.search(q, k)
            except Exception as exc:           # noqa: BLE001  桥半路死 ⇒ 明确降级
                return self._send(503, {'ok': False, 'backend': 'rust',
                                        'degraded': True,
                                        'error': '%s: %s' % (type(exc).__name__, exc)})
        else:
            cg = _cg()
            res, _meta = cg.search_rrf(q, k=k)
            rows = [(h.get('id'), h.get('score')) for h in (res or [])]
        return self._send(200, {'ok': True, 'backend': BACKEND, 'query': q,
                                'k': k,
                                'hits': [{'id': a, 'score': b} for a, b in rows],
                                'took_ms': round((_t.perf_counter() - t0) * 1000.0, 2)})

    def do_POST(self):                             # noqa: N802
        # R-405c：`POST /search` 是后端可切换的检索面（写路径仍只走 Python）。
        if self.path.rstrip('/') == '/search':
            return self._do_search()
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

    # R-409（2026-11-10 审计 D1/D2/D3）：把 sustain 自维持循环挂进**常驻进程**。
    #
    # 为什么现在才挂：`mcp_server._start_sustain` 是 sustain 的唯一触发点，而它只在
    # `mdcg_http.py` 之外被调（DSH 拉起的**短命 stdio 子进程**）。本文件是 systemd
    # 起的长命进程（实测 uptime 24.3h），却从来没启动过 sustain ⇒ 心跳/睡眠永远不跑
    # （`~/.mdcg/sustain/` 空、`_sleep.jsonl` 不存在、`_heartbeat.jsonl` 停在 11-05）。
    #
    # 前置条件（均已就绪，故此处才敢挂）：
    #   · R-104 默认值定案（auto_scrub/auto_evolve/scrub_apply 三处口径统一）
    #   · R-203 索引 rebuild 改用日志字节水位（不再锁外扫描 13.4s）
    #   · R-301 心跳 severity 分级（死掉会让 ok 变假、自愈能看见）
    # 三者缺一，挂上去就是「定时丢节点 + 每晚真改盘 + 没有红灯」。
    #
    # 失败不阻塞 HTTP 服务：sustain 是增益，不是收请求的前提；但必须上报（stderr）。
    try:
        from md_cg import mcp_server as _ms
        _ms._start_sustain(_cg())
        sys.stderr.write("[mdcg-http] sustain 自维持循环已挂载（R-409）\n")
    except Exception as _exc:                  # noqa: BLE001
        sys.stderr.write("[mdcg-http] sustain 挂载失败（不阻塞 HTTP）: %r\n" % (_exc,))
    sys.stderr.flush()
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
