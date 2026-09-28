# -*- coding: utf-8 -*-
"""md_cg · stdio 主循环入口类型闸守卫（N206：一行非对象 JSON 杀整个 server）

缺陷（修复前，本守卫红态实抓）：``md_cg/mcp_server.py`` 的 stdin 主循环里
``try`` 只包 ``json.loads`` 的 ValueError，随后**裸调** ``msg.get("method")``；
``tools/call`` 分支又把 ``msg.get("params") or {}`` 的结果**裸调** ``.get("name")``。
而 ``json.loads`` 的产物不必是对象——``[]`` / ``123`` / ``null`` / ``"x"`` / ``true``
（以及批量数组）都是**合法 JSON**。任何能写该 server stdin 的一方（MCP 宿主、
被注入的宿主插件、stdio 管道交错写入者）发一行即得未捕获
``AttributeError: 'list' object has no attribute 'get'`` 逃出 ``main()``，
整个进程退出（rc=1，stdout 只到崩溃前那条）——工具面 tools/list 永无应答，
崩溃期间记忆面（含写入）全不可用；零凭据可达。同族已在位：
``hive/hive_mcp/mcp_server.py`` 的 ``_rpc`` 有 -32600/-32602 双闸 + main 入口兜底
（2026-09-25 v2-N16），md_cg 是**漏网面**（工具层 try 只包 ``call_tool``，
包不到入口解析）。

修复口径（与 hive 同族同修，fail-closed）：入口把「解析结果类型」当判据——
非 dict 行回 id=null 的 -32600 Invalid Request 并**继续服务**；
``tools/call`` 的 params 非 dict（list/str/int）回 -32602 Invalid params 且不进工具；
``_serve_line`` 整体兜底 -32603（单行请求的任何异常都不得杀 server）。

守卫构成（①③④ 实弹子进程 = 红态在「进程死」，② 单测面，⑤ 源断言，⑥ floor）：
  ① 主场景一趟（若干攻击行夹击合法行）：非对象行逐条得 -32600、非 dict params
     逐条得 -32602 且 id 回带、夹击后的 tools/list 与 initialize 全部应答、rc=0；
  ② 单测面：``_serve_line`` 逐形态不抛异常 + 错误码正确 + 非对象/坏 params 形态
     **先于一切 cg 触碰**（cg 传 @boom 探针——修前若真触 cg 会自曝）；
  ③ control 腿（只有 initialize+tools/list）：rc=0、响应数 = 2（镜像缺陷材料）；
  ④ 攻击行在握手**之前**（首行即 `[]`）：后续 initialize/tools/list 仍应答、rc=0；
  ⑤ 源断言：主循环调用 `_serve_line` 且有入口兜底；`_serve_line` 内有
     isinstance(msg, dict) / -32600 / -32602 / -32603 四判据；
  ⑥ floor：实弹断言数不足即视为「spawn/扫描面失效」的假绿。

隔离纪律（与 md_cg/test_issue39_utf8_stdio.py 同款）：env 剔净全部 MDCG_*/HIVE_*
注入面，只注入 `MDCG_ROOT`/`MDCG_AUX_ROOT`/`MDCG_STATE_ROOT`/`MDCG_DATA_ROOT`/
`MDCG_TENANT_REGISTRY`（指向不存在的临时路径=空表回落）/`MDCG_SUSTAIN=0`（关常驻
循环）/`MDCG_LEGACY_ENV_AUTH=1`（既有豁免面，零令牌、不回落真实 ~/.mdcg）；
子进程 cwd=仓根，`-X utf8`；跑完 rmtree 临时根，并删掉**本子进程自己**的那份
自报戳 `<tempdir>/md_cg_servers/<pid>.json`（诊断设施，非本次修复面）。
绝不触真实令牌库、真实在役数据目录与真实 serve。

运行：python -X utf8 -m md_cg.test_n206_stdio_jsonrpc_type
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_FLOOR = 12          # 实弹断言下限（防 spawn/扫描面失效假绿）

PASS, FAIL, LIVE = 0, 0, 0
FAILS = []


def check(name, cond, detail="", live=False):
    global PASS, FAIL, LIVE
    if live:
        LIVE += 1
    if cond:
        PASS += 1
        print("  [ok] %s" % name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  %s" % (name, detail))


# 非 dict JSON 攻击行（单行、合法 JSON、非 object）
NONDICT_LINES = [
    ("batch_array", '[{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]'),
    ("empty_array", "[]"),
    ("bare_int", "123"),
    ("bare_null", "null"),
    ("bare_str", '"x"'),
    ("bare_true", "true"),
]

# tools/call 的 params 非 dict 攻击（真值形态——假值会走 `or {}` 而侥幸不炸）
NONDICT_PARAMS = [
    ("params_list", [1, 2]),
    ("params_str", "x"),
    ("params_int", 7),
]

_HOSTILE_RIDS = (11, 12, 13)     # 非 dict params 的请求 id（须原样回带）
_ABSENT_PARAMS_RID = 14          # params 缺省（原语义：落工具层错误，不得崩）


class _Boom:
    """cg 探针：任何属性访问都自曝——证明入口闸先于一切 cg 触碰。"""

    def __getattr__(self, item):
        raise AssertionError("入口闸失效：非对象/坏 params 形态触碰了 cg.%s" % item)


# 模拟宿主前先把「身份/路径/编码」注入面清干净——子进程只吃临时目录
_DIRTY_KEYS = (
    "MDCG_TOKEN", "MDCG_CLEARANCE", "MDCG_TENANT", "MDCG_TENANT_REGISTRY",
    "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_LEGACY_ENV_AUTH",
    "MDCG_LEGACY_ENV_ADMIN", "MDCG_SESSION", "DSH_SESSION_ID",
    "MDCG_HARNESS", "MDCG_UNIT", "MDCG_ROOT", "MDCG_STATE_ROOT",
    "MDCG_DATA_ROOT", "MDCG_AUX_ROOT", "MDCG_SUSTAIN", "MDCG_SUSTAIN_NAME",
    "MDCG_MCP_SURFACE", "MDCG_TOOL_FACE", "MDCG_ACTOR",
    "MDCG_VERIFIER_MODULES", "MDCG_HIVE_JOBS",
    "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONLEGACYWINDOWSSTDIO",
)


def _env(tmp: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _DIRTY_KEYS}
    env["MDCG_ROOT"] = os.path.join(tmp, "cgroot")
    # 登记表指向**不存在**的临时路径 → 空表回落，绝不读真实 ~/.mdcg
    env["MDCG_TENANT_REGISTRY"] = os.path.join(tmp, "_tenants_absent.json")
    env["MDCG_STATE_ROOT"] = os.path.join(tmp, "state")
    env["MDCG_DATA_ROOT"] = os.path.join(tmp, "data")
    # 子目录名不可取 "aux"（Windows 保留设备名，见 test_issue39 头注）
    env["MDCG_AUX_ROOT"] = os.path.join(tmp, "auxroot")
    env["MDCG_SUSTAIN"] = "0"                # 关常驻循环（线程面归零）
    env["MDCG_LEGACY_ENV_AUTH"] = "1"        # 既有豁免面：零令牌、无二次开关
    env["MDCG_ACTOR"] = "n206-guard"
    return env


def _talk(lines, tmp, timeout=180):
    """spawn stdio server → 一次喂完 lines → (rc, stdout, stderr)。"""
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
        cwd=ROOT, env=_env(tmp), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    try:
        out, err = proc.communicate("\n".join(lines) + "\n", timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    # 自报戳残留（诊断设施，非本次修复面）：只删本子进程自己的那份
    try:
        os.remove(os.path.join(tempfile.gettempdir(), "md_cg_servers",
                               "%d.json" % proc.pid))
    except OSError:
        pass
    return proc.returncode, out or "", err or ""


def _resp_lines(out: str):
    """stdout 逐行 → [(raw, obj_or_None)]（解析失败的记 None，供「全行合法」断言）。"""
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


def _err_code(obj):
    return (obj.get("error") or {}).get("code") if isinstance(obj, dict) else None


def _rpc(rid, method, params=None):
    msg = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg, ensure_ascii=False)


def _src_window(src: str, start: str, end: str) -> str:
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i)
    return src[i:] if j < 0 else src[i:j]


def _mod():
    try:
        from . import mcp_server as M
        return M
    except Exception as exc:              # noqa: BLE001 —— 诊断用
        print("  [warn] 模块导入失败: %r" % (exc,))
        return None


def _serve_unit(cg, msg):
    """调 _serve_line(msg) → (返回值, 写出的行列表)；函数缺失（修前）返回 ("<missing>", [])。"""
    M = _mod()
    if M is None or not hasattr(M, "_serve_line"):
        return "<missing>", []
    buf = io.StringIO()
    with redirect_stdout(buf):
        ret = M._serve_line(cg, msg)
    return ret, [ln for ln in buf.getvalue().splitlines() if ln.strip()]


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_n206_")
    try:
        # ---------- ① 主场景：攻击行夹击合法行（实弹） ----------
        print("[1] 实弹主场景：6 非对象行 + 3 非 dict params + 缺省 params，"
              "夹击 initialize/tools/list")
        lines = [_rpc(1, "initialize")]
        lines += [raw for _tag, raw in NONDICT_LINES]
        for (rid, (_tag, bad)) in zip(_HOSTILE_RIDS, NONDICT_PARAMS):
            lines.append(json.dumps({"jsonrpc": "2.0", "id": rid,
                                     "method": "tools/call", "params": bad}))
        lines.append(_rpc(_ABSENT_PARAMS_RID, "tools/call"))
        lines.append(_rpc(2, "tools/list"))
        lines.append(_rpc(3, "tools/list"))
        lines.append(_rpc(4, "shutdown"))
        rc, out, err = _talk(lines, tmp)
        resps = _resp_lines(out)
        objs = [o for _raw, o in resps]
        by_id = {o.get("id"): o for o in objs if isinstance(o, dict)}

        check("1a 进程存活到正常下线 rc=0（红态：攻击行后 rc=1 崩死）",
              rc == 0, f"rc={rc} stdout_lines={len(resps)} stderr_tail={err[-300:]!r}",
              live=True)
        check("1b stdout 每一行都是合法 JSON（无半截/串行响应）",
              all(o is not None for _raw, o in resps),
              f"bad_lines={[r for r, o in resps if o is None][:3]}", live=True)
        nul_32600 = [o for o in objs if isinstance(o, dict) and o.get("id") is None
                     and _err_code(o) == -32600]
        check("1c 每条非对象行各得一条 id=null 的 -32600 Invalid Request",
              len(nul_32600) == len(NONDICT_LINES),
              f"got={len(nul_32600)} want={len(NONDICT_LINES)} "
              f"objs={json.dumps(objs, ensure_ascii=False)[:300]}", live=True)
        got_32602 = [r for r in _HOSTILE_RIDS if _err_code(by_id.get(r)) == -32602]
        check("1d 非 dict params 的 tools/call 逐条回 -32602 且 id 原样回带",
              got_32602 == list(_HOSTILE_RIDS),
              f"got={got_32602} want={list(_HOSTILE_RIDS)} "
              f"resp={str(by_id.get(_HOSTILE_RIDS[0]))[:200]}", live=True)
        init = by_id.get(1) or {}
        check("1e 攻击行夹击下 initialize 仍应答（serverInfo=mdcg-mcp）",
              (init.get("result") or {}).get("serverInfo", {}).get("name")
              == "mdcg-mcp", f"got={str(init)[:200]}", live=True)
        for rid in (2, 3):
            t = (by_id.get(rid) or {}).get("result") or {}
            check(f"1f tools/list(id={rid}) 在攻击行之后仍应答且工具表非空",
                  isinstance(t.get("tools"), list) and len(t["tools"]) > 0,
                  f"got={str(by_id.get(rid))[:200]}", live=True)
        check("1g params 缺省的 tools/call 有应答（原语义落工具层错误，不得静默/崩）",
              isinstance(by_id.get(_ABSENT_PARAMS_RID), dict),
              f"got={str(out)[-200:]!r}", live=True)
        check("1h shutdown 有应答（进程不是被攻击行提前带走）",
              isinstance(by_id.get(4), dict), f"got={str(out)[-200:]!r}", live=True)
        check("1i stderr 无 AttributeError / Traceback（旧态逃逸印迹）",
              "AttributeError" not in err
              and "Traceback (most recent call last)" not in err,
              f"err_tail={err[-300:]!r}", live=True)
        check("1j 隔离自证：记忆库落在守卫自己的临时根（cgroot 已建）",
              os.path.isdir(os.path.join(tmp, "cgroot")),
              f"tmp={os.listdir(tmp)}", live=True)

        # ---------- ② 单测面：入口闸先于一切 cg 触碰 ----------
        print("[2] 单测面 _serve_line（cg 传 @boom 探针）")
        for tag, raw in NONDICT_LINES:
            try:
                ret, wy = _serve_unit(_Boom(), json.loads(raw))
            except Exception as exc:      # noqa: BLE001 —— 红态正是抛异常
                check(f"2·{tag} 非对象行不抛异常", False,
                      f"抛 {type(exc).__name__}: {exc}")
                continue
            parsed = []
            for ln in wy:
                try:
                    parsed.append(json.loads(ln))
                except ValueError:
                    parsed.append(None)
            check(f"2·{tag} 非对象行回 id=null 的 -32600 且返回 False（未触碰 cg）",
                  ret is False and len(parsed) == 1 and isinstance(parsed[0], dict)
                  and parsed[0].get("id") is None and _err_code(parsed[0]) == -32600,
                  f"ret={ret!r} lines={wy}")
        for (tag, bad) in NONDICT_PARAMS:
            msg = {"jsonrpc": "2.0", "id": 901, "method": "tools/call",
                   "params": bad}
            try:
                ret, wy = _serve_unit(_Boom(), msg)
            except Exception as exc:      # noqa: BLE001
                check(f"2·{tag} 不抛异常", False, f"抛 {type(exc).__name__}: {exc}")
                continue
            p = json.loads(wy[0]) if wy else None
            check(f"2·{tag} 回 -32602 且 id 回带（未触碰 cg）",
                  ret is False and isinstance(p, dict) and p.get("id") == 901
                  and _err_code(p) == -32602, f"ret={ret!r} lines={wy}")
        # 合法面零回归（同样以 _Boom 作 cg——这些分支本就不该碰 cg）
        ret, wy = _serve_unit(_Boom(), {"jsonrpc": "2.0",
                                        "method": "notifications/initialized"})
        check("2·notification 仍无响应（返回 False、零写出）",
              ret is False and wy == [], f"ret={ret!r} lines={wy}")
        ret, wy = _serve_unit(_Boom(), {"jsonrpc": "2.0", "id": 9,
                                        "method": "no/such"})
        p = json.loads(wy[0]) if wy else None
        check("2·未知方法仍 -32601 且 id 回带",
              ret is False and isinstance(p, dict) and p.get("id") == 9
              and _err_code(p) == -32601, f"ret={ret!r} lines={wy}")
        ret, wy = _serve_unit(_Boom(), {"jsonrpc": "2.0", "id": 10,
                                        "method": "shutdown"})
        p = json.loads(wy[0]) if wy else None
        check("2·shutdown 回空结果并返回 True（调用方据此跳出读循环）",
              ret is True and isinstance(p, dict) and p.get("id") == 10
              and p.get("result") == {}, f"ret={ret!r} lines={wy}")
        # 入口兜底（-32603）：分派体内抛异常（未来演化面）也只回一行错误、不抛出，
        # 且必须开口（stderr 留痕，「不静默」）。
        M = _mod()
        if M is None or not hasattr(M, "_serve_line"):
            check("2·分派体异常回 -32603 且不抛出（入口兜底）", False,
                  "缺 _serve_line（修前形态）")
        else:
            _orig = M.tools_for_surface

            def _boom_tools():
                raise RuntimeError("simulated-tools-surface-fault")

            M.tools_for_surface = _boom_tools
            ebuf = io.StringIO()
            try:
                with redirect_stderr(ebuf):
                    ret, wy = _serve_unit(_Boom(), {"jsonrpc": "2.0", "id": 5,
                                                    "method": "tools/list"})
            finally:
                M.tools_for_surface = _orig
            p = json.loads(wy[0]) if wy else None
            check("2·分派体异常回 -32603 且不抛出（入口兜底不崩 server）",
                  ret is False and isinstance(p, dict) and p.get("id") == 5
                  and _err_code(p) == -32603,
                  f"ret={ret!r} lines={wy}")
            check("2·入口兜底必须开口（stderr 留痕，不静默）",
                  "主循环兜底" in ebuf.getvalue(), f"stderr={ebuf.getvalue()!r}")

        # ---------- ③ control 腿（镜像缺陷材料的对照跑法） ----------
        print("[3] control 腿：只有 initialize + tools/list")
        rc_c, out_c, err_c = _talk([_rpc(1, "initialize"), _rpc(2, "tools/list")],
                                   tmp)
        cs = _resp_lines(out_c)
        check("3a control 腿 rc=0 且恰 2 条应答（无新增杂散响应）",
              rc_c == 0 and len(cs) == 2,
              f"rc={rc_c} n={len(cs)} out={out_c[-200:]!r} err={err_c[-200:]!r}",
              live=True)
        check("3b control 腿 stderr 无 Traceback",
              "Traceback (most recent call last)" not in err_c,
              f"err_tail={err_c[-300:]!r}", live=True)

        # ---------- ④ 攻击行在握手之前（首行即 []） ----------
        print("[4] 首行即攻击行（握手前）：后续 initialize/tools/list 仍须应答")
        rc_d, out_d, err_d = _talk(["[]", _rpc(1, "initialize"),
                                    _rpc(2, "tools/list")], tmp)
        ds = _resp_lines(out_d)
        d_ids = {o.get("id") for _r, o in ds if isinstance(o, dict)}
        check("4a 首行 [] 后 rc=0 且 initialize(id=1)+tools/list(id=2) 均应答",
              rc_d == 0 and {1, 2} <= d_ids,
              f"rc={rc_d} ids={sorted(x for x in d_ids if x is not None)} "
              f"err_tail={err_d[-300:]!r}", live=True)
        check("4b 首行 [] 得 id=null 的 -32600",
              any(isinstance(o, dict) and o.get("id") is None
                  and _err_code(o) == -32600 for _r, o in ds),
              f"out={out_d[:200]!r}", live=True)

        # ---------- ⑤ 源断言（锚点：闸在入口里，且主循环调用它） ----------
        print("[5] 源断言")
        with open(os.path.join(ROOT, "md_cg", "mcp_server.py"),
                  encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        entry = _src_window(src, "def _serve_line", "def main()")
        check("5a _serve_line 入口含 isinstance(msg, dict) 类型闸",
              "isinstance(msg, dict)" in entry, f"window_len={len(entry)}")
        check("5b 入口四错误码齐备（-32600 Invalid Request / -32602 Invalid "
              "params / -32601 未知方法 / -32603 兜底）",
              all(c in entry for c in ("-32600", "-32602", "-32601", "-32603")),
              f"window_len={len(entry)}")
        loop = _src_window(src, "for line in sys.stdin", "sustain.stop_all()")
        check("5c 主循环体把每行交给 _serve_line 且带入口兜底 except",
              "_serve_line(cg, msg)" in loop and "except Exception" in loop
              and "-32603" in loop, f"window_len={len(loop)}")

        # ---------- ⑥ floor 自检 ----------
        print("[6] 守卫自检")
        check(f"6a 实弹断言数 ≥ {LIVE_FLOOR}（防 spawn/扫描面失效假绿）",
              LIVE >= LIVE_FLOOR, f"LIVE={LIVE}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n=== N206 stdio jsonrpc type gate: %d passed, %d failed (live=%d) ==="
          % (PASS, FAIL, LIVE))
    if FAILS:
        print("失败项：%s" % "；".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
