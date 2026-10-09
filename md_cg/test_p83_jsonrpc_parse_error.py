# -*- coding: utf-8 -*-
"""守卫 · MCP stdio 非法 JSON 应回 -32700（issue #83.1，2026-10-09 DSH 端修复随附）。

修前：mcp_server.py 主循环 try: msg = json.loads(line) / except ValueError: continue
—— 非法 JSON 静默跳过：客户端收不到任何应答，只能等超时；全文件无 -32700。

修后：回 JSON-RPC 2.0 的 -32700 Parse error（id=null），进程继续服务。

判据（真跑：起真 stdio 子进程喂输入、读应答）：
  G1 喂一行非法 JSON  ⇒ 收到 error.code == -32700（修前：无任何输出 ⇒ 超时）
  G2 紧接着喂一行合法 initialize ⇒ 收到正常应答 ⇒ 证明进程存活、循环未死
  G3 全文件仍含 -32600/-32602 双闸（不被本次改动破坏）
运行：python -X utf8 -m md_cg.test_p83_jsonrpc_parse_error
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PYEXE = sys.executable

PASS = 0
FAIL = 0
FAILS = []


def _read_line(proc, timeout=8.0):
    """带超时的读一行：超时返回 None（修前/变异后走这条 ⇒ 守卫判红而非挂起）。

    注：Windows 上 select 不支持管道（WinError 10093 WSAStartup），故用线程 + join。
    """
    box = {}

    def _rd():
        try:
            box["line"] = proc.stdout.readline()
        except Exception as exc:      # noqa: BLE001
            box["err"] = exc

    th = threading.Thread(target=_rd, daemon=True)
    th.start()
    th.join(timeout)
    return box.get("line")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def main():
    root = tempfile.mkdtemp(prefix="p83_guard_")
    env = {**os.environ, "MDCG_ROOT": root, "PYTHONUTF8": "1",
           "PYTHONPATH": REPO, "PYTHONIOENCODING": "utf-8"}
    # 隔离宿主鉴权态：本 case 只测 stdio 帧面（非法 JSON → -32700），与鉴权无关。
    # 宿主若带**陈旧/已吊销**的 MDCG_TOKEN（本机实测：开发机 env 里有一个失效令牌），
    # mcp_server 启动即 fail-closed 拒绝（rc=3）→ 无任何应答 → G1 超时、随后写
    # stdin 撞已关管道（OSError Errno 22）。摘掉该键即复现 CI（裸环境）口径。
    env.pop("MDCG_TOKEN", None)
    proc = subprocess.Popen([PYEXE, "-X", "utf8", "-m", "md_cg.mcp_server"],
                            cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", env=env)
    try:
        proc.stdin.write("{ this is not json\n")
        proc.stdin.flush()
        line = _read_line(proc, 8.0)
        code = None
        try:
            got = json.loads(line) if line.strip() else None
            if isinstance(got, dict):
                code = (got.get("error") or {}).get("code")
        except ValueError:
            code = "UNPARSABLE"
        check("G1 非法 JSON 回 -32700 Parse error（修前=静默无应答）",
              code == -32700,
              "code=%r line=%r" % (code, (line or "<TIMEOUT: 无任何应答>")[:110]))

        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1,
                                     "method": "initialize", "params": {}}) + "\n")
        proc.stdin.flush()
        line2 = _read_line(proc, 8.0)
        ok2 = False
        try:
            got2 = json.loads(line2) if line2.strip() else None
            ok2 = isinstance(got2, dict) and (("result" in got2) or ("error" in got2))
        except ValueError:
            ok2 = False
        check("G2 随后合法 initialize 正常应答（进程存活、循环未死）", ok2,
              (line2 or "")[:110])
    finally:
        try:
            proc.kill()
        except Exception:
            pass

    src = open(os.path.join(HERE, "mcp_server.py"), encoding="utf-8").read()
    check("G3 既有 -32600/-32602 双闸未被破坏",
          ("-32600" in src) and ("-32602" in src), "")

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
