# -*- coding: utf-8 -*-
"""test_issue39_utf8_stdio.py · Windows 控制台代码页下 stdio MCP 中文必炸的守卫（issue #39）

现场（外部用户实测，issue #39）：Windows 控制台代码页（GBK/CP936）下，md_cg 的
stdio MCP server 写中文必失败——宿主按 UTF-8 发来的中文参数被按 GBK 解码：
· ``gbk:strict`` → 读侧直接 ``UnicodeDecodeError``（本守卫实弹注入的形态，已实证
  「中文标题：编码守卫」的 UTF-8 字节序列按 GBK 严格解码必非法）；
· ``surrogateescape`` → 解出代理对 ``\\udcXX``，``_j()``（ensure_ascii=False）
  按 UTF-8 编码时抛 ``UnicodeEncodeError: surrogates not allowed``。
两种形态整条请求同亡；写英文正常，用户难自查。桥层 0.4.10 已在
``src/lib/mdcg_client.ts`` 的 ``mdcgChildEnv()`` 注入 ``PYTHONUTF8=1``，但只覆盖
DSH 桥路径——Claude Code / code CLI 直接 mcp.json 接入不经桥，仍踩。

修复（本守卫的红绿两态锚点）：``md_cg/mcp_server.py`` 与
``hive/hive_mcp/mcp_server.py``（同族全修）各加模块级 ``_force_utf8_stdio()``，
并在 ``main()`` **首行**调用——进程内把 stdio 三流 reconfigure 成
``utf-8``/``errors="replace"``，是对桥层 PYTHONUTF8=1 的纵深补位；``replace``
保证坏字节最多丢字符、不炸整条请求。

实弹形态：subprocess spawn ``[sys.executable, "-m", "md_cg.mcp_server"]``
（cwd=仓根，**不带** ``-X utf8``），env 显式设 ``PYTHONIOENCODING=gbk:strict``
模拟 CP936 控制台；按行分隔 JSON-RPC（initialize → notifications/initialized →
tools/call cg {op:"write", content:中文}）。断言：响应行是合法 JSON、write 响应
不含 ``UnicodeEncodeError`` 且返回 ``ok``/``moved_to`` 字段。hive 面同款实弹
（中文 hive_spawn；HIVE_EXE 指向不存在的探针路径——``_ensure_serve`` 在 isfile
即返回，绝不拉起真 serve）。修复前此面红（进程在读侧崩、响应行缺失），修复后绿。

隔离纪律：MDCG_ROOT/MDCG_STATE_ROOT/MDCG_DATA_ROOT/MDCG_AUX_ROOT/
MDCG_TENANT_REGISTRY/HIVE_JOBS_DIR/HIVE_CONFIG 全部指向 tempfile.mkdtemp 临时
目录（登记表指向不存在的临时路径=空表回落），身份走既有豁免面
``MDCG_LEGACY_ENV_AUTH=1``（env 直连 designer，零令牌、不回落真实 ~/.mdcg），
MDCG_SUSTAIN=0 关常驻循环；finally rmtree——绝不触真实令牌库与真实数据目录。

自检 floor：实弹断言低于 LIVE_FLOOR 视为失败——防止「spawn 面失效 → 假绿」。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_FLOOR = 2          # 实弹断言下限（md_cg 面 ≥1 + hive 面 ≥1）
PROBE = "中文标题：编码守卫"   # UTF-8 字节按 GBK strict 解码必非法（红态机制，见头注）

PASS, FAIL, LIVE = 0, 0, 0


def check(name, cond, detail="", live=False):
    global PASS, FAIL, LIVE
    if live:
        LIVE += 1
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


# 模拟 CP936 控制台前，先把父进程可能携带的「身份/路径/编码」注入面清干净——
# 守卫子进程只吃临时目录，绝不吃本机真实 ~/.mdcg / 真实 MDCG_ROOT。
_DIRTY_KEYS = (
    "MDCG_TOKEN", "MDCG_CLEARANCE", "MDCG_TENANT", "MDCG_TENANT_REGISTRY",
    "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_LEGACY_ENV_AUTH",
    "MDCG_LEGACY_ENV_ADMIN", "MDCG_SESSION", "DSH_SESSION_ID",
    "MDCG_HARNESS", "MDCG_UNIT", "MDCG_ROOT", "MDCG_STATE_ROOT",
    "MDCG_DATA_ROOT", "MDCG_AUX_ROOT", "MDCG_SUSTAIN", "MDCG_SUSTAIN_NAME",
    "MDCG_MCP_SURFACE", "MDCG_TOOL_FACE", "MDCG_ACTOR",
    "MDCG_VERIFIER_MODULES", "MDCG_HIVE_JOBS",
    "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONLEGACYWINDOWSSTDIO",
    "HIVE_JOBS_DIR", "HIVE_CONFIG", "HIVE_EXE", "HIVE_API_KEY",
)


def _base_env(tmp: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _DIRTY_KEYS}
    env["PYTHONIOENCODING"] = "gbk:strict"     # 模拟 CP936 控制台（无 -X utf8）
    env["MDCG_SUSTAIN"] = "0"                  # 关常驻循环（线程面归零）
    env["MDCG_ACTOR"] = "issue39-guard"
    # 身份走既有豁免面：env 直连 designer（二次开关齐全），零令牌、不回落真实凭据面
    env["MDCG_LEGACY_ENV_AUTH"] = "1"
    env["MDCG_CAN_ADMIN"] = "1"
    env["MDCG_LEGACY_ENV_ADMIN"] = "1"
    _ = tmp
    return env


def _mdcg_env(tmp: str) -> dict:
    env = _base_env(tmp)
    env["MDCG_ROOT"] = os.path.join(tmp, "cgroot")
    env["MDCG_TENANT_REGISTRY"] = os.path.join(tmp, "_tenants_absent.json")
    env["MDCG_STATE_ROOT"] = os.path.join(tmp, "state")
    env["MDCG_DATA_ROOT"] = os.path.join(tmp, "data")
    # 子目录名不可取 "aux"：AUX 是 Windows 保留设备名，ntpath.abspath 经
    # GetFullPathNameW 会把末段 aux 解析成设备路径 \\.\aux（实测），导致
    # aux_root() 覆盖键静默失联——取名 auxroot 避开。
    env["MDCG_AUX_ROOT"] = os.path.join(tmp, "auxroot")
    return env


def _hive_env(tmp: str) -> dict:
    env = _base_env(tmp)
    env["HIVE_JOBS_DIR"] = os.path.join(tmp, "hivejobs")
    # 指向不存在的配置与可执行文件：_ensure_serve 在 isfile 即返回，绝不拉起真 serve
    env["HIVE_CONFIG"] = os.path.join(tmp, "hive_config_absent.json")
    env["HIVE_EXE"] = os.path.join(tmp, "no_such_hive.exe")
    return env


def _rpc(rid, method, params=None):
    msg = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg, ensure_ascii=False)


def _talk(cmd_args, env, lines, timeout=180):
    """spawn server → 写 JSON-RPC 行 → 收 (returncode, stdout_text, stderr_text)。"""
    proc = subprocess.Popen(
        cmd_args, cwd=ROOT, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace")
    try:
        out, err = proc.communicate("\n".join(lines) + "\n", timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    return proc.returncode, out or "", err or ""


def _resp_lines(out: str):
    """stdout 逐行解析成 (raw_line, obj_or_None)。"""
    got = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            got.append((ln, json.loads(ln)))
        except ValueError:
            got.append((ln, None))
    return got


def _find_resp(resps, rid):
    for _raw, obj in resps:
        if isinstance(obj, dict) and obj.get("id") == rid:
            return obj
    return None


def _main_body_has_call(src: str) -> bool:
    """源断言：main() 函数体首段含 _force_utf8_stdio() 调用（定义与调用都在）。"""
    if "def _force_utf8_stdio()" not in src:
        return False
    idx = src.find("def main")
    if idx < 0:
        return False
    window = src[idx:idx + 400]
    return "_force_utf8_stdio()" in window


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_issue39_")
    try:
        # ---- 1. md_cg 面实弹：GBK 代码页下写中文 ----
        print("[1] md_cg stdio 实弹（PYTHONIOENCODING=gbk:strict，无 -X utf8）")
        rc, out, err = _talk(
            [sys.executable, "-m", "md_cg.mcp_server"], _mdcg_env(tmp), [
                _rpc(1, "initialize", {}),
                _rpc(None, "notifications/initialized"),
                _rpc(3, "tools/call", {"name": "cg", "arguments": {
                    "op": "write", "content": PROBE}}),
            ])
        resps = _resp_lines(out)
        init = _find_resp(resps, 1)
        check("1a initialize 握手在 GBK 控制台下存活（合法 JSON 响应）",
              isinstance(init, dict)
              and (init.get("result") or {}).get("serverInfo", {}).get(
                  "name") == "mdcg-mcp",
              f"rc={rc} lines={len(resps)} err_tail={err[-200:]!r}", live=True)
        wr = _find_resp(resps, 3)
        wr_ok = False
        if isinstance(wr, dict):
            try:
                payload = json.loads(
                    (wr.get("result") or {}).get("content", [{}])[0].get(
                        "text", "{}"))
                wr_ok = ("ok" in payload) or ("moved_to" in payload)
            except (ValueError, AttributeError, IndexError):
                wr_ok = False
        check("1b 中文 write 响应合法且返回 ok/moved_to 字段（红态：进程在读侧崩，本条缺失）",
              wr_ok, f"wr={str(wr)[:200]}", live=True)
        check("1c 全程无 UnicodeEncodeError（stdout/stderr 不见代理对编码炸点）",
              "UnicodeEncodeError" not in out and "UnicodeEncodeError" not in err,
              f"out_tail={out[-160:]!r} err_tail={err[-160:]!r}", live=True)
        check("1d 进程正常下线（EOF 后 returncode=0，非中途崩死）",
              rc == 0, f"rc={rc} err_tail={err[-200:]!r}", live=True)

        # ---- 2. hive 面实弹：同族 server 同款代码页 ----
        print("[2] hive stdio 实弹（同款 PYTHONIOENCODING=gbk:strict）")
        rc2, out2, err2 = _talk(
            [sys.executable, "-m", "hive.hive_mcp.mcp_server"],
            _hive_env(tmp), [
                _rpc(1, "initialize", {}),
                _rpc(None, "notifications/initialized"),
                _rpc(3, "tools/call", {"name": "hive_spawn", "arguments": {
                    "model": "probe-model", "user_prompt": PROBE}}),
            ])
        resps2 = _resp_lines(out2)
        init2 = _find_resp(resps2, 1)
        check("2a initialize 握手存活（合法 JSON 响应，serverInfo=hive-mcp）",
              isinstance(init2, dict)
              and (init2.get("result") or {}).get("serverInfo", {}).get(
                  "name") == "hive-mcp",
              f"rc={rc2} lines={len(resps2)} err_tail={err2[-200:]!r}", live=True)
        sp = _find_resp(resps2, 3)
        sp_ok = False
        if isinstance(sp, dict):
            try:
                payload = json.loads(
                    (sp.get("result") or {}).get("content", [{}])[0].get(
                        "text", "{}"))
                sp_ok = payload.get("ok") is True and bool(payload.get("job_id"))
            except (ValueError, AttributeError, IndexError):
                sp_ok = False
        check("2b 中文 hive_spawn 返回 ok=true+job_id（探针 exe 不存在，绝不拉真 serve）",
              sp_ok, f"resp={str(sp)[:200]}", live=True)
        check("2c hive 面无 UnicodeEncodeError",
              "UnicodeEncodeError" not in out2
              and "UnicodeEncodeError" not in err2,
              f"err_tail={err2[-160:]!r}", live=True)
        # 探针诚实边界：任务必须落在守卫自己的临时池，真实 jobs 池零触碰
        jobs_dir = os.path.join(tmp, "hivejobs")
        probe_jobs = [n for n in (os.listdir(jobs_dir) if os.path.isdir(jobs_dir)
                                  else []) if n.startswith("h")]
        check("2d 任务落在临时 jobs 池（隔离面自证）",
              len(probe_jobs) == 1 if sp_ok else len(probe_jobs) == 0,
              f"probe_jobs={probe_jobs}")

        # ---- 3. 源断言：两 server 的 main() 首段强制 UTF-8 ----
        print("[3] 源断言（main() 首段 _force_utf8_stdio()）")
        for rel in ("md_cg/mcp_server.py", "hive/hive_mcp/mcp_server.py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8",
                      errors="replace") as fh:
                src = fh.read()
            check(f"3·{rel}: 定义存在且 main() 首段调用 _force_utf8_stdio()",
                  _main_body_has_call(src),
                  "缺定义或 main() 首段未调用（必须早于一切 stderr 中文写与 stdin 读取）")

        # ---- 4. 守卫自检 floor：实弹断言不足即假绿 ----
        print("[4] 守卫自检")
        check(f"4a 实弹断言数 ≥ {LIVE_FLOOR}（防 spawn/扫描面失效假绿）",
              LIVE >= LIVE_FLOOR, f"LIVE={LIVE}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n=== issue39 utf8 stdio tests: {PASS} passed, {FAIL} failed "
          f"(live={LIVE}) ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    sys.exit(main())
