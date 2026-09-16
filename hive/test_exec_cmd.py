# -*- coding: utf-8 -*-
"""exec_cmd.py 单测（确定性执行器 · 零 LLM）。

9 例，零外部依赖、不涉网络、不依赖 serve：
    python hive/test_exec_cmd.py
覆盖：成功单步 / 退出码非 0 / 字符串 command 被拒 / 多步 fail_fast / expect_files 缺失 /
expect_stdout 命中 / cwd 不存在 / 命令不存在 / 单步超时强杀。
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

print("\nRESULT:", "ALL_PASS" if not fails else f"FAILED={fails}")
sys.exit(0 if not fails else 1)
