# -*- coding: utf-8 -*-
"""蜂巢编排器单测（hive/orch.py + exec.py 扩展口 + exec_cmd.py 转发档）。

不打真 API、不起 serve：
  · 权限侧走**真实 md_cg.tokens 库层**（临时令牌库）
  · 子任务提交走**真实 _hm._submit 文件机械**（临时 HIVE_JOBS_DIR）
  · main() 装配组把 `_ex.main` 桩掉，只验「注册了什么、写了什么」
运行：python hive/test_orch.py   （退出码 0 = 全绿）
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile

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


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ex = _load("hive_exec", os.path.join(_HERE, "exec.py"))
cmd = _load("hive_exec_cmd", os.path.join(_HERE, "exec_cmd.py"))
orc = _load("hive_orch", os.path.join(_HERE, "orch.py"))

from md_cg import tokens as tk                       # noqa: E402
from md_cg import security as sec                    # noqa: E402

TMP = tempfile.mkdtemp(prefix="hive_orch_test_")
STORE = os.path.join(TMP, "tokens.json")
os.environ["MDCG_TOKEN_FILE"] = STORE
os.environ["MDCG_ROOT"] = os.path.join(TMP, "root")
DESIGNER_TOK = tk.issue("designer", actor="t_designer", path=STORE)["token"]
ORCH_DERIVE = tk.derive(DESIGNER_TOK, tk.ORCH_ROLE, actor="hive-orchestrator",
                        path=STORE, layers_allow=list(tk.ORCH_LAYERS_ALLOW),
                        ops_allow=list(tk.ORCH_OPS_ALLOW))
ORCH_TOK = ORCH_DERIVE["token"]

print("[A] 权限收窄面（md_cg/tokens.py ORCH_* 真源）")
check("A1 ops 清单 ⊆ ALL_OPS", set(tk.ORCH_OPS_ALLOW) <= set(tk.ALL_OPS),
      str(set(tk.ORCH_OPS_ALLOW) - set(tk.ALL_OPS)))
check("A2 layers ⊆ ALL_LAYERS 且不含核心层 anchor/self",
      set(tk.ORCH_LAYERS_ALLOW) <= set(tk.ALL_LAYERS)
      and not (set(tk.ORCH_LAYERS_ALLOW) & set(tk.CORE_LAYERS)))
_danger = [o for o in ("forget", "identity", "protect", "delegate", "maintain",
                       "consolidate") if o in tk.ALL_OPS]
check("A3 危险 op 确在 ALL_OPS（防空洞断言）", len(_danger) >= 1, str(_danger))
check("A4 危险 op 均不在编排器清单", not (set(_danger) & set(tk.ORCH_OPS_ALLOW)),
      str(set(_danger) & set(tk.ORCH_OPS_ALLOW)))
check("A5 编排器角色可派生", tk.ORCH_ROLE in tk.DELEGABLE_ROLES)
check("A6 派生 ops/layers 与真源逐位一致",
      list(ORCH_DERIVE["ops_allow"]) == list(tk.ORCH_OPS_ALLOW)
      and list(ORCH_DERIVE["layers_allow"]) == list(tk.ORCH_LAYERS_ALLOW))
check("A7 派生令牌结构上不可再派生（delegable=False）",
      (tk._load(STORE)["tokens"].get(ORCH_DERIVE["token_id"]) or {})
      .get("delegable") is False)
try:
    tk.derive(ORCH_TOK, "designer", path=STORE)
    check("A8 二次派生被库层拒", False, "未抛错")
except Exception as e:                                # noqa: BLE001
    check("A8 二次派生被库层拒", True, type(e).__name__)

P = tk.verify_token(ORCH_TOK, path=STORE)
check("A9 校验后身份 ops 收窄一致", list(P.ops_allow or []) == list(tk.ORCH_OPS_ALLOW))
check("A10 校验后身份 layers 收窄一致",
      list(P.layers_allow or []) == list(tk.ORCH_LAYERS_ALLOW))
check("A11 can_admin=True（裁决子代理冲突的前提，如实标注残余面）",
      P.can_admin is True)


def _op_ok(principal, op):
    """库层是否放行该 op。

    取证口径：`allows_op` 是 **Principal 的方法**（md_cg/security.py:118
    `def allows_op(self, op)`），不是模块级函数——写成 `sec.allows_op(p, op)`
    会 AttributeError 并被吞掉，导致所有断言恒为 False（假阴性/空洞通过）。
    """
    try:
        return bool(principal.allows_op(op))
    except Exception:                                 # noqa: BLE001
        return False


if _danger:
    check("A12 库层拒清单外 op（give forget）", not _op_ok(P, _danger[0]), _danger[0])
check("A13 库层放行 review（裁决能力所求）", _op_ok(P, "review"))

_tf = os.path.join(TMP, "designer.token")
with open(_tf, "w", encoding="utf-8") as f:
    f.write(DESIGNER_TOK)
_out = os.path.join(TMP, "orch.token")
with contextlib.redirect_stdout(io.StringIO()):
    tk_main_rc = tk.main(["--token-file", STORE, "orch",
                          "--token-file-in", _tf, "--out", _out])
check("A14 CLI orch 签发退出码 0", tk_main_rc in (0, None), str(tk_main_rc))
check("A15 CLI orch 落盘令牌文件", os.path.isfile(_out))
with open(_out, encoding="utf-8") as f:
    _cli_tok = f.read().strip()
_P2 = tk.verify_token(_cli_tok, path=STORE)
check("A16 CLI 产出令牌 ops/layers 与真源一致",
      list(_P2.ops_allow or []) == list(tk.ORCH_OPS_ALLOW)
      and list(_P2.layers_allow or []) == list(tk.ORCH_LAYERS_ALLOW))
check("A17 CLI 产出令牌可裁决 review", _op_ok(_P2, "review"))

# ------------------------------------------------------- B 工具层（orch.py）
print("[B] 编排三工具：护栏 / 防递归 / 卡片 / 按需拉取")
JOBS = os.path.join(TMP, "jobs")
os.makedirs(JOBS, exist_ok=True)
JOB_DIR = os.path.join(TMP, "orchjob")
os.makedirs(JOB_DIR, exist_ok=True)
os.environ["HIVE_JOBS_DIR"] = JOBS
orc._CFG.update({"job_id": "orchjob", "job_dir": JOB_DIR, "jobs": JOBS,
                 "model": "m_test", "max_subtasks": 2, "children": []})

_t, _added = orc.merge_tools({})
check("B1 缺省 tools 注入 lingshu_cg + web_search + read_file",
      {"lingshu_cg", "web_search", "read_file"} <= set(_t))
check("B2 编排三工具为能力下限（强制并入）", set(orc.ORCH_TOOLS) <= set(_t))
_t2, _ = orc.merge_tools({"tools": ["lingshu_cg"]})
check("B3 显式 tools 仍补编排三工具且不重复",
      set(orc.ORCH_TOOLS) <= set(_t2) and _t2.count("lingshu_cg") == 1)

check("B4 缺 user_prompt 诚实拒", orc._spawn({})["ok"] is False)
_MODEL_BAK = orc._CFG["model"]
orc._CFG["model"] = ""
_b5 = orc._spawn({"user_prompt": "x"})
orc._CFG["model"] = _MODEL_BAK
check("B5 无可用 model 诚实拒",
      _b5["ok"] is False and "model" in _b5["error"], str(_b5))
_bad = orc._spawn({"user_prompt": "x", "tools": ["spawn_subtask"]})
check("B6 子代理不可用编排工具（防递归第一道）",
      _bad["ok"] is False and "不可用工具" in _bad["error"], str(_bad))
_f = orc._spawn({"user_prompt": "x", "context_files": [os.path.join(TMP, "无此文件")]})
check("B7 缺 context 文件诚实拒", _f["ok"] is False and "不存在" in _f["error"])

_r1 = orc._spawn({"user_prompt": "子任务甲：统计 A 目录", "tools": ["lingshu_cg"]})
C1 = _r1.get("job_id", "")
check("B8 派发成功（毫秒即返，带 job_id）", _r1.get("ok") is True and bool(C1), str(_r1))
_s1 = json.load(open(os.path.join(JOBS, C1, "spec.json"), encoding="utf-8"))
check("B9 子 spec 无 orchestrate（结构性防递归）", "orchestrate" not in _s1)
check("B10 子 spec tools ⊆ 子代理白名单",
      set(_s1["tools"]) <= set(orc.SUB_TOOLS_ALLOW), str(_s1["tools"]))
check("B10b read_file 在子代理白名单内且工具描述同步（防漂移）",
      "read_file" in orc.SUB_TOOLS_ALLOW
      and "read_file" in orc._spawn_schema()["function"]["parameters"]
      ["properties"]["tools"]["description"], str(list(orc.SUB_TOOLS_ALLOW)))
check("B11 子任务默认注入与 MCP 面同源",
      _s1["timeout_s"] == orc._hm.DEFAULT_TIMEOUT_S
      and _s1["reasoning_effort"] == orc._hm.DEFAULT_REASONING_EFFORT
      and _s1["context_budget_tokens"] == orc._hm.DEFAULT_CONTEXT_BUDGET_TOKENS)
_cf = os.path.join(JOB_DIR, orc.CHILDREN_FILE)
check("B12 子任务清单落盘（换人续跑不重复派发）",
      os.path.isfile(_cf)
      and json.load(open(_cf, encoding="utf-8"))["children"][0]["job_id"] == C1)

_r2 = orc._spawn({"user_prompt": "子任务乙：统计 B 目录"})
C2 = _r2.get("job_id", "")
check("B13 并行派发第二个子任务", _r2.get("ok") is True)
_r3 = orc._spawn({"user_prompt": "子任务丙"})
check("B14 超上限诚实报错（不静默丢弃）",
      _r3["ok"] is False and "上限" in _r3["error"], str(_r3))

LONG = "甲" * 500
with open(os.path.join(JOBS, C1, "result.json"), "w", encoding="utf-8") as f:
    json.dump({"ok": True, "content": LONG,
               "tool_trace": [{"tool": "lingshu_cg", "ok": True, "brief": f"b{i}"}
                              for i in range(10)]}, f, ensure_ascii=False)
with open(os.path.join(JOBS, C1, "status.json"), "w", encoding="utf-8") as f:
    json.dump({"job_id": C1, "state": "done"}, f, ensure_ascii=False)

_card = orc._card(C1)
check("B15 卡片正文头截断到 CARD_CHARS",
      len(_card.get("content_head", "")) == orc.CARD_CHARS)
check("B16 默认不回全文（省编排者上下文）", "content" not in _card)
check("B17 截断标记在位", _card.get("content_truncated") is True)
check("B18 工具轨迹只留尾部 TRACE_MAX 条",
      len(_card.get("tool_trace_brief") or []) == orc.TRACE_MAX)
check("B19 全量调用数仍可审计", _card.get("tool_calls") == 10)
check("B20 指针 result_path 在位",
      str(_card.get("result_path", "")).endswith("result.json"))
check("B21 提示按需拉取 read_full", "read_full" in (_card.get("hint") or ""))
check("B22 状态透出", _card.get("state") == "done", str(_card.get("state")))
check("B23 full=True 给全文（编排者显式索取时）",
      orc._card(C1, full=True).get("content") == LONG)

_rf = orc._read_full({"job_id": C1})
check("B24 read_full 给原文", _rf.get("ok") is True and _rf.get("raw", "").startswith("{"))
_rf2 = orc._read_full({"job_id": C1, "max_chars": 40})
check("B25 超上限截断给头 + 指针",
      _rf2.get("truncated") is True and len(_rf2.get("head", "")) == 40)
check("B26 越权读被拒（非本编排者派发的 job）",
      orc._read_full({"job_id": "h_not_mine"}).get("ok") is False)
check("B27 缺 job_id 诚实拒", orc._read_full({}).get("ok") is False)

_p1 = orc._poll({})
check("B28 汇总本编排者全部子任务", _p1.get("count") == 2, str(_p1.get("count")))
check("B29 done/active 拆分恒等",
      _p1.get("done", 0) + _p1.get("active", 0) == 2)
check("B30 指定 job_ids 生效", orc._poll({"job_ids": [C1]}).get("count") == 1)
_bak = orc._CFG["children"]
orc._CFG["children"] = []
_p2 = orc._poll({})
orc._CFG["children"] = _bak
check("B31 未派发时诚实空报",
      _p2.get("count") == 0 and _p2.get("children") == [])

for k in ("HIVE_ORCH_TOKEN", "HIVE_ORCH_TOKEN_FILE"):
    os.environ.pop(k, None)
try:
    orc.load_principal("j")
    check("B32 令牌缺失 fail-closed（抛 OrcError）", False, "未抛错")
except orc.OrcError as e:
    check("B32 令牌缺失 fail-closed（抛 OrcError）", "令牌" in str(e), str(e)[:60])
os.environ["HIVE_ORCH_TOKEN"] = "mdcg1.zzz.zzz"
try:
    orc.load_principal("j")
    check("B33 无效令牌 fail-closed", False, "未抛错")
except orc.OrcError:
    check("B33 无效令牌 fail-closed", True)
os.environ["HIVE_ORCH_TOKEN"] = ORCH_TOK
_pp = orc.load_principal("jobz")
check("B34 正路令牌 → 编排器身份（session/harness 隔离）",
      _pp is not None and _pp.session == "hive_orch_jobz"
      and getattr(_pp, "harness", "") == "hive-orch", str(getattr(_pp, "session", None)))
check("B35 正路身份 ops 与真源一致",
      list(_pp.ops_allow or []) == list(tk.ORCH_OPS_ALLOW))

# ------------------------------------------- C exec.py 两个扩展口（默认零变更）
print("[C] exec.py 扩展口：register_tools / set_principal_factory")


def _exec_call(name, args_json, job_id):
    r = ex.execute_tool(name, args_json, job_id)
    return r[0] if isinstance(r, tuple) else r


_base = set(ex.all_schemas())
check("C1 未注册时工具面 = 内置三工具（零变更）",
      _base == {"lingshu_cg", "web_search", "read_file"}, str(_base))
ex.register_tools({"spawn_subtask": {"type": "function",
                                     "function": {"name": "spawn_subtask"}}},
                  lambda n, a, j: {"ok": True, "echo": n})
check("C2 register_tools 后 all_schemas 可见", "spawn_subtask" in ex.all_schemas())
check("C3 分发到注册 handler",
      _exec_call("spawn_subtask", "{}", "job_x").get("echo") == "spawn_subtask")
check("C4 未注册工具仍诚实报错",
      _exec_call("nope", "{}", "job_x").get("ok") is False)

ex.set_principal_factory(lambda args, jid: tk.verify_token(ORCH_TOK, path=STORE),
                         ops_allow=tk.ORCH_OPS_ALLOW)
check("C5 工具层白名单随身份同步收窄",
      tuple(ex._TOOL_OPS_ALLOW) == tuple(tk.ORCH_OPS_ALLOW))
_o1 = ex.tool_lingshu_cg({"op": "review", "pid": "p_x"}, "job_t")
check("C6 收窄后 review 过工具层前置闸（库层另裁）",
      "未对当前身份开放" not in str(_o1.get("error") or ""), str(_o1)[:120])
ex.set_principal_factory(None)
_o2 = ex.tool_lingshu_cg({"op": "review", "pid": "p_x"}, "job_t")
check("C7 恢复默认后 review 被工具层拒（默认零变更）",
      _o2.get("ok") is False and "未对当前身份开放" in _o2.get("error", ""),
      str(_o2)[:120])

# ------------------------------------- D exec_cmd.py 转发档（多态加一档）
print("[D] exec_cmd.py：spec.orchestrate → orch.py")


def _mk_job(spec):
    d = tempfile.mkdtemp(prefix="hive_job_")
    with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    return d


_calls = []


class _R:
    returncode = 0
    stdout = ""
    stderr = ""


def _fake_run(argv, **kw):
    _calls.append(list(argv))
    return _R()


from unittest import mock as _mock               # noqa: E402

_j1 = _mk_job({"model": "m", "user_prompt": "p", "orchestrate": {"max_subtasks": 4}})
_j2 = _mk_job({"model": "m", "user_prompt": "p"})
with _mock.patch.object(cmd.subprocess, "run", _fake_run):
    _rc1 = cmd.run_cmd(_j1)
    _rc2 = cmd.run_cmd(_j2)
check("D1 orchestrate 真值 → 转发 orch.py",
      _calls[0][-1] == _j1 and _calls[0][1].endswith("orch.py") and _rc1 == 0, str(_calls[0]))
check("D2 无 orchestrate → 转发 exec.py（旧行为零变更）",
      _calls[1][1].endswith("exec.py"), str(_calls[1]))
os.environ["HIVE_ORCH_PY"] = os.path.join(TMP, "nope_orch.py")
_j3 = _mk_job({"model": "m", "user_prompt": "p", "orchestrate": True})
_rc3 = cmd.run_cmd(_j3)
_err3 = json.load(open(os.path.join(_j3, "result.json"), encoding="utf-8")).get("error", "")
check("D3 目标 worker 缺失时诚实报错并点名编排器",
      _rc3 == cmd.EXIT_EXEC and "orch.py（编排器）" in _err3, f"{_rc3} {_err3[:70]}")
os.environ.pop("HIVE_ORCH_PY", None)
os.environ["HIVE_LLM_EXEC_PY"] = os.path.join(TMP, "nope_exec.py")
check("D4 HIVE_LLM_EXEC_PY 覆盖仍生效",
      cmd.run_cmd(_mk_job({"model": "m", "user_prompt": "p"})) == cmd.EXIT_EXEC)
os.environ.pop("HIVE_LLM_EXEC_PY", None)

# ----------------------------------- E main() 装配（桩掉 _ex.main，不打 LLM）
print("[E] orch.main() 装配与 fail-closed")
_CALLED = {"n": 0}
_ORIG_MAIN = orc._ex.main
_ORIG_ARGV = list(sys.argv)


def _stub_main():
    _CALLED["n"] += 1
    return 0


def _run_main(job_dir):
    sys.argv = ["orch.py", job_dir]
    try:
        return orc.main()
    finally:
        sys.argv = list(_ORIG_ARGV)


_JD = tempfile.mkdtemp(prefix="orch_job_")
with open(os.path.join(_JD, "spec.json"), "w", encoding="utf-8") as f:
    json.dump({"model": "m_orch", "user_prompt": "编排：拆三份",
               "orchestrate": {"max_subtasks": 3}}, f, ensure_ascii=False)
os.environ["HIVE_ORCH_TOKEN"] = ORCH_TOK
orc._ex.main = _stub_main
try:
    _rc = _run_main(_JD)
finally:
    orc._ex.main = _ORIG_MAIN
check("E1 装配成功交回 exec loop（rc=0，恰好一次）",
      _rc == 0 and _CALLED["n"] == 1, f"rc={_rc} n={_CALLED['n']}")
with open(os.path.join(_JD, "spec.json"), encoding="utf-8") as f:
    _spec2 = json.load(f)
check("E2 spec 补全编排三工具（写回磁盘可审计）",
      set(orc.ORCH_TOOLS) <= set(_spec2["tools"]), str(_spec2.get("tools")))
check("E3 缺省注入编排 system_prompt", "编排者" in _spec2.get("system_prompt", ""))
check("E3b 写后回读纪律在系统提示词（M3.1，删除该行必红）",
      "写后回读" in _spec2.get("system_prompt", "")
      and "不信返回的 written 计数" in _spec2.get("system_prompt", ""))
check("E4 max_subtasks 从 spec.orchestrate 生效", orc._CFG["max_subtasks"] == 3,
      str(orc._CFG["max_subtasks"]))
check("E5 已注册编排工具", set(orc.ORCH_TOOLS) <= set(orc._ex.all_schemas()))
check("E6 身份工厂已装", orc._ex._PRINCIPAL_FACTORY is not None)
check("E7 工具层白名单同步收窄",
      tuple(orc._ex._TOOL_OPS_ALLOW) == tuple(tk.ORCH_OPS_ALLOW))

_JDX = tempfile.mkdtemp(prefix="orch_job_x_")
with open(os.path.join(_JDX, "spec.json"), "w", encoding="utf-8") as f:
    json.dump({"model": "m", "user_prompt": "x", "system_prompt": "自定提示"},
              f, ensure_ascii=False)
try:
    _run_main(_JDX)
finally:
    pass
with open(os.path.join(_JDX, "spec.json"), encoding="utf-8") as f:
    _spec3 = json.load(f)
check("E8 显式 system_prompt 不被覆盖", _spec3["system_prompt"] == "自定提示")

_JD2 = tempfile.mkdtemp(prefix="orch_job_fail_")
with open(os.path.join(_JD2, "spec.json"), "w", encoding="utf-8") as f:
    json.dump({"model": "m", "user_prompt": "x", "orchestrate": True}, f, ensure_ascii=False)
os.environ.pop("HIVE_ORCH_TOKEN", None)
os.environ.pop("HIVE_ORCH_TOKEN_FILE", None)
_CALLED["n"] = 0
orc._ex.main = _stub_main
try:
    _rc2 = _run_main(_JD2)
finally:
    orc._ex.main = _ORIG_MAIN
check("E9 令牌缺失 → EXIT_SPEC 且不交回 loop（不降级）",
      _rc2 == ex.EXIT_SPEC and _CALLED["n"] == 0, f"rc={_rc2} n={_CALLED['n']}")
with open(os.path.join(_JD2, "result.json"), encoding="utf-8") as f:
    _res2 = json.load(f)
check("E10 result 诚实记 orch_token_unavailable",
      _res2.get("error_code") == "orch_token_unavailable" and _res2.get("ok") is False)

print(f"\n=== orchestration tests: {PASS} passed, {FAIL} failed ===")
sys.exit(1 if FAIL else 0)
