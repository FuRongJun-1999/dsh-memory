# -*- coding: utf-8 -*-
"""exec_cmd.py 单测（确定性执行器 · 零 LLM）。

16 例，零外部依赖、不涉网络、不依赖 serve：
    python hive/test_exec_cmd.py
覆盖：成功单步 / 退出码非 0 / 字符串 command 被拒 / 多步 fail_fast / expect_files 缺失 /
expect_stdout 命中 / cwd 不存在 / 命令不存在 / 单步超时强杀 /
**N234 规格错归因**（commands 脏类型不得静默降级为「无命令 → 转发 LLM」；
env / timeout_step_s / cwd 脏类型必须按规格错 rc=2 拒绝，不得以内部异常落到
rc=3「执行错」——与 :24「2=规格错 / 3=执行错」口径一致）。
退出码 0 = 全绿。
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import exec_cmd  # noqa: E402

PY = sys.executable
EXIT_OK, EXIT_SPEC, EXIT_EXEC = (exec_cmd.EXIT_OK, exec_cmd.EXIT_SPEC,
                                 exec_cmd.EXIT_EXEC)
fails = []


def case(name, spec, expect_ok, expect_err_sub=None, **kw):
    d = tempfile.mkdtemp(prefix="hive_selftest_")
    with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    rc = exec_cmd.run_cmd(d)
    rp = os.path.join(d, "result.json")
    got = json.load(open(rp, encoding="utf-8")) if os.path.exists(rp) else None
    ok = got is not None and got.get("ok") is expect_ok
    detail = ""
    if expect_err_sub:
        ok = ok and expect_err_sub in (got.get("error") or "")
        detail = f" err={(got or {}).get('error')!r}"
    print(f"{'PASS' if ok else 'FAIL'} {name}: rc={rc} ok={(got or {}).get('ok')} "
          f"state={kw.get('tag','')}{detail}")
    if not ok:
        fails.append(name)
    return got, d


# ① 成功单步
g, d = case("单步成功", {
    "model": "cmd", "user_prompt": "t1",
    "command": [PY, "-c", "print('HELLO_CMD')"],
}, True)
assert g["exit_code"] == 0 and "HELLO_CMD" in g["content"], "汇总应含 stdout"
assert os.path.exists(os.path.join(d, "step_1_stdout.txt")), "完整输出应落盘"

# ② 失败单步（退出码非 0 → ok=False 且有 error 字段）
g2, _ = case("单步失败", {
    "model": "cmd", "user_prompt": "t2",
    "command": [PY, "-c", "import sys; sys.exit(3)"],
}, False)
assert g2["exit_code"] == 3, f"exit_code 应为 3，实际 {g2['exit_code']}"

# ③ 字符串 command 被拒（纪律：只收 argv）
case("字符串command被拒", {
    "model": "cmd", "user_prompt": "t3", "command": "echo hi",
}, False, expect_err_sub="只收 argv 数组")

# ④ 多步 + fail_fast（第 2 步失败即停，只跑 2 步）
g4, _ = case("多步fail_fast", {
    "model": "cmd", "user_prompt": "t4",
    "commands": [
        {"command": [PY, "-c", "print(1)"], "label": "s1"},
        {"command": [PY, "-c", "import sys;sys.exit(1)"], "label": "s2"},
        {"command": [PY, "-c", "print(3)"], "label": "s3"},
    ],
}, False)
assert len(g4["steps"]) == 2, f"fail_fast 应只跑 2 步，实际 {len(g4['steps'])}"

# ⑤ expect_files 缺失 → error
case("expect_files缺失", {
    "model": "cmd", "user_prompt": "t5",
    "command": [PY, "-c", "print('x')"],
    "expect_files": ["nope.txt"],
}, False, expect_err_sub="预期产出文件不存在")

# ⑥ expect_stdout_contains 命中 → ok
case("expect_stdout命中", {
    "model": "cmd", "user_prompt": "t6",
    "command": [PY, "-c", "print('MARKER_OK')"],
    "expect_stdout_contains": ["MARKER_OK"],
}, True)

# ⑦ cwd 不存在 → error
case("cwd不存在", {
    "model": "cmd", "user_prompt": "t7",
    "command": [PY, "-c", "print(1)"],
    "cwd": os.path.join(tempfile.gettempdir(), "no_such_dir_xyz"),
}, False, expect_err_sub="cwd 不存在")

# ⑧ 命令不存在 → error
case("命令不存在", {
    "model": "cmd", "user_prompt": "t8",
    "command": ["definitely_not_a_real_binary_xyz", "--x"],
}, False)

# ⑨ 单步超时被强杀
case("单步超时", {
    "model": "cmd", "user_prompt": "t9",
    "command": [PY, "-c", "import time; time.sleep(30)"],
    "timeout_step_s": 2,
}, False, expect_err_sub="单步超时")

# ---------------------------------------------------------------- N234（规格错归因）
#
# 病灶：① `commands` 是**非 list 的真值形态**（如字符串）时，_norm_steps 静默按
# 「无命令」返回 None → run_cmd 转发 LLM（:253-254）——确定性命令从未执行却以
# ok=true 落盘；而同字段的字符串 `command` 在 :128-131 是被规格错拒绝的，同一份
# spec 面两种执法口径不一致。
# ② spec 的 `env` / `timeout_step_s`（及 step 级同名字段 / `cwd`）**脏类型零类型闸**：
# 异常逃出 run_cmd 由 main 顶层兜底成 EXIT_EXEC(3)——规格错被记成执行错，与 :24
# 「2=规格错 / 3=执行错」相悖。
#
# 判据：脏类型一律走**规格错**（rc=2 + error 点明字段），且 list 形态的合法
# commands / 真无命令的转发路径**零回归**。


def case_main(name, spec, expect_rc, expect_err_sub=None):
    """走 main()（含顶层兜底）：规格错的**退出码归因**只在这里可观测。"""
    d = tempfile.mkdtemp(prefix="hive_selftest_")
    with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    old = sys.argv
    sys.argv = ["exec_cmd.py", d]
    try:
        rc = exec_cmd.main()
    finally:
        sys.argv = old
    rp = os.path.join(d, "result.json")
    got = (json.load(open(rp, encoding="utf-8"))
           if os.path.exists(rp) else None)
    ok = got is not None and rc == expect_rc
    if expect_err_sub:
        ok = ok and expect_err_sub in (got.get("error") or "")
    print(f"{'PASS' if ok else 'FAIL'} {name}: rc={rc}（期望 {expect_rc}）"
          f" ok={(got or {}).get('ok')} err={(got or {}).get('error')!r}")
    if not ok:
        fails.append(name)
    return got, d


# 转发见证桩：被转发即写 DELEGATED 哨兵 + 落 ok=true 产物——把「静默降级」变成
# 可观测事实（绝不真调 LLM，也不出网）。
_WITNESS_DIR = tempfile.mkdtemp(prefix="hive_selftest_")
_WITNESS = os.path.join(_WITNESS_DIR, "llm_witness.py")
_SENTINEL = os.path.join(_WITNESS_DIR, "DELEGATED")
with open(_WITNESS, "w", encoding="utf-8") as f:
    f.write(
        "import json, os, sys\n"
        f"open({_SENTINEL!r}, 'w').close()\n"
        "with open(os.path.join(sys.argv[1], 'result.json'), 'w', encoding='utf-8') as fh:\n"
        "    json.dump({'ok': True, 'content': 'LLM_DELEGATED_WITNESS'}, fh)\n")


class _WitnessEnv:
    """临时把 HIVE_LLM_EXEC_PY 指向见证桩（退出还原）。"""

    def __enter__(self):
        self.old = os.environ.get("HIVE_LLM_EXEC_PY")
        os.environ["HIVE_LLM_EXEC_PY"] = _WITNESS
        if os.path.exists(_SENTINEL):
            os.unlink(_SENTINEL)
        return self

    def __exit__(self, *_e):
        if self.old is None:
            os.environ.pop("HIVE_LLM_EXEC_PY", None)
        else:
            os.environ["HIVE_LLM_EXEC_PY"] = self.old
        return False


# ⑩ commands 脏类型（字符串）→ 规格错 rc=2，且**不得**被当成「无命令」转发 LLM
with _WitnessEnv():
    g10, _d10 = case_main("commands脏类型被规格闸拒绝", {
        "model": "cmd", "user_prompt": "t10", "commands": "python x.py",
    }, EXIT_SPEC, expect_err_sub="commands 必须是数组")
    _deleg = os.path.exists(_SENTINEL)
    _ok10 = (not _deleg) and "LLM_DELEGATED_WITNESS" not in json.dumps(
        g10 or {}, ensure_ascii=False)
    print(f"{'PASS' if _ok10 else 'FAIL'} commands脏类型未被静默转发 LLM"
          f"（delegated={_deleg}）")
    if not _ok10:
        fails.append("commands脏类型未被静默转发")

# ⑪ env 脏类型（list）→ 规格错（修前：AttributeError → rc=3 执行错）
case_main("env脏类型被规格闸拒绝", {
    "model": "cmd", "user_prompt": "t11",
    "command": [PY, "-c", "print(1)"], "env": ["A=1"],
}, EXIT_SPEC, expect_err_sub="env 必须是对象")

# ⑫ spec 级 timeout_step_s 脏类型（字符串）→ 规格错（修前：ValueError → rc=3）
case_main("timeout_step_s脏类型被规格闸拒绝", {
    "model": "cmd", "user_prompt": "t12",
    "command": [PY, "-c", "print(1)"], "timeout_step_s": "abc",
}, EXIT_SPEC, expect_err_sub="timeout_step_s 必须是数字")

# ⑬ step 级 timeout_step_s 脏类型 → 规格错（同字段的另一消费点，同类错）
case_main("step级timeout_step_s脏类型被规格闸拒绝", {
    "model": "cmd", "user_prompt": "t13",
    "commands": [{"command": [PY, "-c", "print(1)"], "timeout_step_s": "abc"}],
}, EXIT_SPEC, expect_err_sub="timeout_step_s 必须是数字")

# ⑭ step 级 cwd 脏类型（int）→ 规格错（修前：TypeError → rc=3）
case_main("step级cwd脏类型被规格闸拒绝", {
    "model": "cmd", "user_prompt": "t14",
    "commands": [{"command": [PY, "-c", "print(1)"], "cwd": 123}],
}, EXIT_SPEC, expect_err_sub="cwd 必须是字符串")

# ⑮ 反向对照：合法 commands（list）照常执行
g15, _d15 = case_main("合法commands照常执行（零回归）", {
    "model": "cmd", "user_prompt": "t15",
    "commands": [{"command": [PY, "-c", "print('OK15')"]}],
}, EXIT_OK)
assert "OK15" in (g15 or {}).get("content", ""), "合法 commands 必须真跑"

# ⑯ 反向对照：commands 空列表 + command 仍在位 → 既有口径（走单步），不被规格闸误拦
g16, _d16 = case_main("commands空列表+command仍走单步（既有口径）", {
    "model": "cmd", "user_prompt": "t16", "commands": [],
    "command": [PY, "-c", "print('OK16')"],
}, EXIT_OK)
assert "OK16" in (g16 or {}).get("content", ""), "空列表须落回 command 口径"

# ⑰ 反向对照：真无命令（无 commands 无 command）仍走转发——规格闸不得吞掉该路径
with _WitnessEnv():
    g17, _d17 = case_main("真无命令仍转发（零回归）", {
        "model": "cmd", "user_prompt": "t17",
    }, EXIT_OK)
    _deleg17 = os.path.exists(_SENTINEL)
    _ok17 = _deleg17 and "LLM_DELEGATED_WITNESS" in json.dumps(g17 or {},
                                                              ensure_ascii=False)
    print(f"{'PASS' if _ok17 else 'FAIL'} 真无命令仍转发 LLM（delegated={_deleg17}）")
    if not _ok17:
        fails.append("真无命令仍转发")

print("\nRESULT:", "ALL_PASS" if not fails else f"FAILED={fails}")
sys.exit(0 if not fails else 1)
