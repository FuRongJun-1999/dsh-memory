#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hive 执行器 · 确定性分支（零 LLM）：跑命令 / 测试 / 回归 / lint / 批处理。

契约与 exec.py 完全一致（argv[1]=job 目录，读 spec.json 写 result.json，rust 侧只认
result.json 的 error 字段），区别是**不调 LLM**——把 spec 里的命令当任务执行（第 17 条
「确定性执行 = 自定义 worker」）。故 HIVE_EXEC_PY 指向本文件时，**一个 serve 同时承载
两类任务**（无 command 的 spec 转发给同目录 exec.py）；不指向时行为零变动。

确定性 spec 字段：
  command                   ["python","-m","pytest","-q"] 单条 argv 数组（推荐）
  commands                  [{"command":[...],"cwd":...,"label":...}, ...] 多步串行
  cwd                       工作目录（缺省 spec.workdir → job 目录）
  env                       {"K":"V"} 附加环境变量（覆盖继承值）
  fail_fast                 默认 true：任一步非 0 即停
  timeout_step_s            单步超时（缺省 spec.timeout_s → 600）；rust 侧另有硬超时兜底
  expect_files              ["路径"] 执行后断言存在（相对 cwd），缺失即 error
  expect_stdout_contains    ["子串"] 各步 stdout 合并文本须包含**全部**给定子串，缺一即 error
订阅约定：model 写 "cmd"、user_prompt 写任务标签——仅为过 rust 侧必填校验，本执行器不调 API。

command 只收 argv 数组，字符串形态一律拒绝（不经 shell，规避转义/GBK 陷阱，第 15 条）。

退出码：0 成功 / 2 规格错 / 3 执行错（与 exec.py 同形）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

HEAD_CHARS = 4000
DEFAULT_STEP_TIMEOUT_S = 600
EXIT_OK, EXIT_SPEC, EXIT_EXEC = 0, 2, 3


def _write_result(job_dir: str, obj: dict) -> None:
    """tmp + fsync + rename 原子替换（并发读者不读到截断空窗口）。"""
    p = os.path.join(job_dir, "result.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def _fail(job_dir: str, msg: str, code: int = EXIT_SPEC, extra: dict | None = None) -> int:
    r: dict = {"ok": False, "error": msg, "model": "cmd"}
    if extra:
        r.update(extra)
    _write_result(job_dir, r)
    return code


def _norm_steps(spec: dict):
    """→ (steps, err)；两者皆 None 表示「无命令 → 走 LLM 委托」。"""
    raw = spec.get("commands")
    steps: list = []
    if isinstance(raw, list) and raw:
        for item in raw:
            if isinstance(item, dict):
                steps.append(item)
            elif isinstance(item, list):
                steps.append({"command": item})
            else:
                return None, "commands 元素必须是对象或 argv 数组"
    elif spec.get("command"):
        steps.append({"command": spec["command"]})
    else:
        return None, None
    for i, s in enumerate(steps, 1):
        argv = s.get("command")
        if isinstance(argv, str):
            return None, (f"第 {i} 步 command 是字符串——只收 argv 数组（不经 shell），"
                          '请改 ["python","scripts/x.py"] 形态')
        if not (isinstance(argv, list) and argv and all(isinstance(x, str) for x in argv)):
            return None, f"第 {i} 步 command 必须是非空字符串数组"
    return steps, None


def _dump_step(job_dir: str, idx: int, out: str, err: str, rec: dict) -> None:
    """完整输出落 step_<i>_stdout/stderr.txt，result 只留 head（防爆炸）。"""
    for name, text in (("stdout", out), ("stderr", err)):
        path = os.path.join(job_dir, f"step_{idx}_{name}.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            rec[f"{name}_path"] = path
        except OSError:
            pass
        rec[f"{name}_head"] = text[:HEAD_CHARS]
        if len(text) > HEAD_CHARS:
            rec[f"{name}_truncated"] = True


def _run_step(step: dict, idx: int, job_dir: str, spec: dict, env: dict, default_cwd: str):
    argv = list(step["command"])
    cwd = step.get("cwd") or default_cwd
    cwd = cwd if os.path.isabs(cwd) else os.path.abspath(cwd)
    label = step.get("label") or f"step {idx}"
    timeout = step.get("timeout_step_s") or spec.get("timeout_step_s") or \
        spec.get("timeout_s") or DEFAULT_STEP_TIMEOUT_S
    t0 = time.time()
    rec = {"label": label, "command": argv, "cwd": cwd}
    if not os.path.isdir(cwd):
        rec.update({"ok": False, "exit_code": None, "duration_s": 0.0,
                    "error": f"cwd 不存在：{cwd}"})
        return rec, ""
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=float(timeout), shell=False)
        out, err, rc = p.stdout or "", p.stderr or "", p.returncode
    except FileNotFoundError:
        rec.update({"ok": False, "exit_code": None, "duration_s": round(time.time() - t0, 3),
                    "error": f"命令不存在：{argv[0]}（检查 PATH 或改用解释器全名）"})
        return rec, ""
    except subprocess.TimeoutExpired as e:
        dec = lambda b: b.decode("utf-8", "replace") if isinstance(b, bytes) else (b or "")  # noqa: E731
        out, err = dec(e.stdout), dec(e.stderr)
        rec.update({"ok": False, "exit_code": None, "duration_s": round(time.time() - t0, 3),
                    "error": f"单步超时（{timeout}s）被强杀"})
        _dump_step(job_dir, idx, out, err, rec)
        return rec, out
    except OSError as e:
        rec.update({"ok": False, "exit_code": None, "duration_s": round(time.time() - t0, 3),
                    "error": f"启动失败：{type(e).__name__}: {e}"})
        return rec, ""
    rec.update({"ok": rc == 0, "exit_code": rc, "duration_s": round(time.time() - t0, 3)})
    _dump_step(job_dir, idx, out, err, rec)
    return rec, out


def _render(steps: list, elapsed: float, note: str = "") -> str:
    head = f"确定性执行：{len(steps)} 步，用时 {elapsed:.2f}s" + (f" | {note}" if note else "")
    lines = [head]
    for i, s in enumerate(steps, 1):
        lines.append(f"[{i}] {'OK ' if s.get('ok') else 'FAIL'} {s.get('label')} — "
                     f"exit={s.get('exit_code')} {s.get('duration_s')}s")
        lines.append(f"    $ {' '.join(s.get('command') or [])}")
        if s.get("error"):
            lines.append(f"    ! {s['error']}")
        for ln in (s.get("stdout_head") or "").strip().splitlines()[-6:]:
            lines.append(f"    | {ln}")
        for ln in (s.get("stderr_head") or "").strip().splitlines()[-4:]:
            lines.append(f"    E {ln}")
    return "\n".join(lines)


def _delegate(job_dir: str) -> int:
    """无命令 → 转发 exec.py（LLM 委托型），行为逐位不变。"""
    exe = os.environ.get("HIVE_LLM_EXEC_PY") or \
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "exec.py")
    if not os.path.isfile(exe):
        return _fail(job_dir, f"spec 无 command/commands，需 LLM 委托但未找到 exec.py：{exe}", EXIT_EXEC)
    p = subprocess.run([sys.executable, exe, job_dir], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.stdout:
        sys.stdout.write(p.stdout)
    if p.stderr:
        sys.stderr.write(p.stderr)
    return p.returncode


def run_cmd(job_dir: str) -> int:
    t0 = time.time()
    try:
        with open(os.path.join(job_dir, "spec.json"), encoding="utf-8") as f:
            spec = json.load(f)
    except (OSError, ValueError) as e:
        return _fail(job_dir, f"spec.json 读取失败：{e}", EXIT_SPEC)

    steps, err = _norm_steps(spec)
    if err:
        return _fail(job_dir, err, EXIT_SPEC)
    if steps is None:
        return _delegate(job_dir)

    env = {str(k): str(v) for k, v in (spec.get("env") or {}).items()}
    env = {**os.environ, **env}
    env.setdefault("PYTHONUTF8", "1")
    default_cwd = spec.get("cwd") or spec.get("workdir") or job_dir
    fail_fast = spec.get("fail_fast", True)
    recs: list = []
    outs: list = []
    for i, step in enumerate(steps, 1):
        rec, out = _run_step(step, i, job_dir, spec, env, default_cwd)
        recs.append(rec)
        outs.append(out)
        if fail_fast and not rec.get("ok"):
            break

    elapsed = round(time.time() - t0, 3)
    failed = [r for r in recs if not r.get("ok")]
    notes: list = []
    for rel in spec.get("expect_files") or []:
        path = rel if os.path.isabs(rel) else os.path.join(default_cwd, rel)
        ok = os.path.exists(path)
        notes.append(f"expect_files {rel}: {'OK' if ok else 'MISSING'}")
        if not ok:
            failed.append({"label": f"expect_files:{rel}", "ok": False, "exit_code": None,
                           "duration_s": 0.0, "command": [],
                           "error": f"预期产出文件不存在：{path}", "stdout_head": "", "stderr_head": ""})
    joined = "\n".join(outs)
    for sub in spec.get("expect_stdout_contains") or []:
        hit = sub in joined
        notes.append(f"expect_stdout_contains {sub!r}: {'OK' if hit else 'MISSING'}")
        if not hit:
            failed.append({"label": f"expect_stdout:{sub}", "ok": False, "exit_code": None,
                           "duration_s": 0.0, "command": [],
                           "error": f"输出未命中预期子串：{sub}", "stdout_head": "", "stderr_head": ""})

    result = {
        "ok": not failed,
        "content": _render(recs, elapsed, "；".join(notes)),
        "exit_code": 0 if not failed else (failed[0].get("exit_code") or 1),
        "duration_s": elapsed,
        "steps": recs,
        "model": "cmd",
        "usage": {},
    }
    if failed:
        result["error"] = "；".join(str(f.get("error") or f.get("label")) for f in failed)[:2000]
    _write_result(job_dir, result)
    return EXIT_OK if not failed else EXIT_EXEC


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python exec_cmd.py <job_dir>", file=sys.stderr)
        return EXIT_SPEC
    job_dir = sys.argv[1]
    if not os.path.isdir(job_dir):
        print(f"job 目录不存在: {job_dir}", file=sys.stderr)
        return EXIT_SPEC
    try:
        return run_cmd(job_dir)
    except Exception as e:  # noqa: BLE001 —— 顶层兜底：任何异常也落 result.json，不留无终态任务
        return _fail(job_dir, f"执行器内部异常：{type(e).__name__}: {e}", EXIT_EXEC)


if __name__ == "__main__":
    sys.exit(main())
