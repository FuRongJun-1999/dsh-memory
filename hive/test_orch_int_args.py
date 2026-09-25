# -*- coding: utf-8 -*-
"""蜂巢编排器脏参数守卫（v2 N13 复测成立，2026-09-25 修复）。

背景：orch 面 _spawn/_read_full 对**模型可控**参数裸 int()——
function calling 常见脏值 '600s'/'20k'/[600] 抛 ValueError/TypeError 逃出
工具处理器，穿透 run_with_tools（调用点无 try）直达 exec.main 兜底
except，以 EXIT_API 判死**整个编排 job**——已派发子任务全部成孤儿。
附带负数形态：max_chars=-100 → cap=-100，len(raw)>cap 恒真而 head=
raw[:-100]——truncated=True 却返回 ~90% 全文（截断契约破坏）。
exec._int_arg 容错模板（int() 失败/非正回落 default）在位但未接 orch 面。

修法：① orch 三处（timeout_s/context_budget_tokens/max_chars）接
_ex._int_arg（脏值/非正回落默认，不引入新上限）；② exec.execute_tool
对 _EXTRA_TOOLS 分派包 try——handler 抛异常回 {'ok': False, 'error': …}
（与 mcp_server 工具层兜底同款模板），不再杀 job。

本测试把「脏参数不得抛异常杀 job、负数不得破坏截断」固化为断言：
  [A] _spawn 脏参六形态（哑捕获桩拦 _hm._submit，不触文件机械/serve）
  [B] _read_full 脏参/负数/合法截断（临时 jobs 目录）
  [C] execute_tool 分派兜底 + run_with_tools 集成（抛错哑 handler）

运行：python -X utf8 -m hive.test_orch_int_args   （退出码 0 = 全绿）
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from unittest import mock

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (_REPO, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
        return
    FAIL += 1
    print(f"  [FAIL] {name}  {detail}")


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ex = _load("hive_exec_intguard", os.path.join(_HERE, "exec.py"))
orc = _load("hive_orch_intguard", os.path.join(_HERE, "orch.py"))

TMP = tempfile.mkdtemp(prefix="hive_orch_intargs_")
JOB_DIR = os.path.join(TMP, "orchjob")
JOBS = os.path.join(TMP, "jobs")
os.makedirs(JOB_DIR)
os.makedirs(os.path.join(JOBS, "hguard"))

# ---------------------------------------------------------------- [A] _spawn
print("[A] _spawn 脏参数（哑捕获桩，不触文件机械/serve）")
SUBMITTED: list = []


def _fake_submit(jobs, sub):
    SUBMITTED.append(dict(sub))
    return "hfake%d" % len(SUBMITTED)


orc._CFG.update({"job_id": "orchjob", "job_dir": JOB_DIR, "jobs": JOBS,
                 "model": "mock-model", "children": []})

_spawn_cases = [
    ("A1 timeout_s='600s'（脏串）", {"timeout_s": "600s"},
     ("timeout_s", orc._hm.DEFAULT_TIMEOUT_S)),
    ("A2 timeout_s='600'（数字串保留解析）", {"timeout_s": "600"},
     ("timeout_s", 600)),
    ("A3 timeout_s=[600]（列表）", {"timeout_s": [600]},
     ("timeout_s", orc._hm.DEFAULT_TIMEOUT_S)),
    ("A4 timeout_s=0（非正回落默认）", {"timeout_s": 0},
     ("timeout_s", orc._hm.DEFAULT_TIMEOUT_S)),
    ("A5 budget='20k'（脏串）", {"context_budget_tokens": "20k"},
     ("context_budget_tokens", orc._hm.DEFAULT_CONTEXT_BUDGET_TOKENS)),
    ("A6 budget=8000（合法 int 直传）", {"context_budget_tokens": 8000},
     ("context_budget_tokens", 8000)),
]
with mock.patch.dict(os.environ, {"HIVE_JOBS_DIR": JOBS}), \
        mock.patch.object(orc._hm, "_submit", side_effect=_fake_submit):
    for name, extra, (key, want) in _spawn_cases:
        try:
            r = orc._spawn({"user_prompt": "p", **extra})
        except Exception as e:  # noqa: BLE001 —— 旧缺陷正是异常逃出杀 job
            check(f"{name} → 不抛且回落 {key}={want}", False,
                  f"抛 {type(e).__name__}: {e}")
            continue
        got = (SUBMITTED[-1] or {}).get(key) if SUBMITTED else None
        check(f"{name} → 不抛且回落 {key}={want}",
              r.get("ok") is True and got == want,
              f"ok={r.get('ok')} sub[{key}]={got!r}")

# ---------------------------------------------------------------- [B] read_full
print("[B] _read_full 脏参数/负数/合法截断")
RAW = "x" * 25000
with open(os.path.join(JOBS, "hguard", "result.json"), "w",
          encoding="utf-8") as f:
    f.write(RAW)
orc._CFG["children"] = [{"job_id": "hguard", "prompt_head": "p",
                         "tools": [], "model": "m", "ts": 0, "source_group": ""}]

_read_cases = [
    ("B1 max_chars='2k'（脏串回落 FULL_MAX_CHARS）", "2k",
     None, orc.FULL_MAX_CHARS),
    ("B2 max_chars=-100（负数不得返回 ~90% 全文）", -100,
     None, orc.FULL_MAX_CHARS),
    ("B3 max_chars=100（合法截断）", 100, True, 100),
    ("B4 max_chars=50000（>全文 → 不截断）", 50000, False, None),
]
for name, mc, want_trunc, want_head_len in _read_cases:
    try:
        r = orc._read_full({"job_id": "hguard", "max_chars": mc})
    except Exception as e:  # noqa: BLE001
        check(name, False, f"抛 {type(e).__name__}: {e}")
        continue
    if want_trunc is None:  # 脏值回落 → truncated=True + head=FULL_MAX_CHARS
        ok = (r.get("ok") is True and r.get("truncated") is True
              and len(r.get("head") or "") == want_head_len)
    elif want_trunc:       # 合法截断
        ok = (r.get("ok") is True and r.get("truncated") is True
              and len(r.get("head") or "") == want_head_len)
    else:                  # 不截断 → raw 全文
        ok = (r.get("ok") is True and r.get("truncated") is False
              and r.get("raw") == RAW)
    check(name, ok, json.dumps({k: (len(v) if isinstance(v, str) else v)
                                for k, v in r.items()}, ensure_ascii=False))

# ---------------------------------------------------------------- [C] 分派兜底
print("[C] execute_tool 分派兜底 + run_with_tools 集成")


def _raising_handler(name, args, job_id):
    raise ValueError("dummy handler boom")


ex._EXTRA_TOOLS["dummy_raise"] = {"schema": {"type": "function"},  # noqa: E501
                                  "handler": _raising_handler}
try:
    try:
        out, brief = ex.execute_tool("dummy_raise", "{}", "j1")
        check("C1 抛错 handler → 兜底 ok=False 不逃出",
              out.get("ok") is False and "ValueError" in (out.get("error") or ""),
              f"got {json.dumps(out, ensure_ascii=False)[:200]}")
    except Exception as e:  # noqa: BLE001
        check("C1 抛错 handler → 兜底 ok=False 不逃出", False,
              f"抛 {type(e).__name__}: {e}")

    def _ok_handler(name, args, job_id):
        return {"ok": True, "v": 1}

    ex._EXTRA_TOOLS["dummy_ok"] = {"schema": {"type": "function"},
                                   "handler": _ok_handler}
    out, _ = ex.execute_tool("dummy_ok", "{}", "j1")
    check("C2 正常 handler 零回归（兜底不误伤）", out.get("ok") is True
          and out.get("v") == 1,
          f"got {json.dumps(out, ensure_ascii=False)[:200]}")

    TOOL_CALL = {"choices": [{"message": {"content": "", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "dummy_raise", "arguments": "{}"}}]}}]}
    FINAL = {"choices": [{"message": {"content": "终答正常"}}]}
    spec_c = {"model": "mock-model", "user_prompt": "q",
              "tools": ["dummy_raise"], "max_tool_rounds": 1, "timeout_s": 5}
    # 序列 3 元素：rnd0 工具调用（handler 抛错被兜）→ rnd1 仍要求工具 →
    # 超轮次强制终答（不带 tools 的请求）拿到正常 content。注意序列须在
    # lambda 外构造（内联列表每次调用重建，pop(0) 恒弹第一个）。
    _seq = [TOOL_CALL, TOOL_CALL, FINAL]
    try:
        with mock.patch.dict(os.environ, {"HIVE_API_KEY": "dummy"}), \
                mock.patch.object(ex, "_post_chat",
                                  side_effect=lambda b, t: _seq.pop(0)):
            out = ex.run_with_tools(spec_c, [{"role": "user", "content": "q"}],
                                    "j1", job_dir=None)
        check("C3 run_with_tools 集成：handler 异常不杀 loop（终答正常、trace 记错）",
              "_error" not in out and out.get("content") == "终答正常"
              and (out.get("tool_trace") or [{}])[0].get("ok") is False,
              f"got {json.dumps(out, ensure_ascii=False)[:300]}")
    except Exception as e:  # noqa: BLE001
        check("C3 run_with_tools 集成：handler 异常不杀 loop（终答正常、trace 记错）",
              False, f"抛 {type(e).__name__}: {e}")
finally:
    ex._EXTRA_TOOLS.pop("dummy_raise", None)
    ex._EXTRA_TOOLS.pop("dummy_ok", None)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n结果: {PASS} pass / {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
