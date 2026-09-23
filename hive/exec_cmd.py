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


# 生效条件：job_dir 与 obj 给出后无任何前置判断，直接用 UTF-8 打开 job_dir/result.json.tmp 写入 json.dump(obj, ensure_ascii=False)、flush+fsync，再 os.replace 到 job_dir/result.json（目录不可写等异常会向外抛）。
def _write_result(job_dir: str, obj: dict) -> None:
    """tmp + fsync + rename 原子替换（并发读者不读到截断空窗口）。"""
    p = os.path.join(job_dir, "result.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


# 生效条件：以 job_dir 与 msg 构造 {"ok": False, "error": msg, "model": "cmd"} 并写 result.json，extra 为真值时 r.update(extra) 合并、假值（None/{}）时不合并，最后返回 code（未传则为模块常量 EXIT_SPEC）。
def _fail(job_dir: str, msg: str, code: int = EXIT_SPEC, extra: dict | None = None) -> int:
    r: dict = {"ok": False, "error": msg, "model": "cmd"}
    if extra:
        r.update(extra)
    _write_result(job_dir, r)
    return code


# 生效条件：spec["commands"] 为非空 list 时逐项归一（dict 原样收、list 包成 {"command": item}、其它类型返回错误 err），commands 缺失/非 list/空列表时若 spec.get("command") 为真值则只生成单步，否则返回 (None, None) 走 LLM 委托；随后逐步校验 command：是字符串时报「只收 argv 数组」，是 None 或不是「非空且全为 str 的 list」时统一报「必须是非空字符串数组」。
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


# 生效条件：对 ("stdout", out) 与 ("stderr", err) 各自把全文写入 job_dir/step_<idx>_<name>.txt 并在写成功时记 rec["<name>_path"]（OSError 仅 pass 不留路径），同时无条件记 rec["<name>_head"] = text[:HEAD_CHARS]，仅当 len(text) > HEAD_CHARS 才置 rec["<name>_truncated"] = True。
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


# 生效条件：argv 直接取 step["command"]（缺键即 KeyError）；cwd 取 step.get("cwd") or default_cwd 并在非绝对时转 abspath，timeout 按 step.get("timeout_step_s") or spec.get("timeout_step_s") or spec.get("timeout_s") or DEFAULT_STEP_TIMEOUT_S 回退；cwd 非目录即返回失败 rec 与 ""，否则以 shell=False 运行 subprocess.run，FileNotFoundError / TimeoutExpired（此路先 _dump_step 再返回 out）/ OSError 各返回失败 rec，正常结束记 ok=rc==0、exit_code=rc 并 _dump_step。
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


# 生效条件：以 steps 与 elapsed 生成首行「确定性执行：{len(steps)} 步，用时 {elapsed:.2f}s」，note 为真值时追加 " | {note}"、假值（空串）不追加，再逐步行输出 [i] OK/FAIL label、exit、duration、' '.join(s.get('command') or [])、error 真值时的 "! error"、stdout_head 去空白后末 6 行与 stderr_head 去空白后末 4 行，最后 "\n".join(lines)。
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


# 生效条件：spec 为 None 时从 job_dir/spec.json 读取（OSError/ValueError 时置 {}）；spec.get("orchestrate") 真值时 exe 取 os.environ.get("HIVE_ORCH_PY")（空串视假值回落）或 here/orch.py，否则取 os.environ.get("HIVE_LLM_EXEC_PY") 或 here/exec.py；exe 非文件时返回 _fail(..., EXIT_EXEC)，否则用 sys.executable 运行 [exe, job_dir]、透传其 stdout/stderr 并返回 p.returncode。
def _delegate(job_dir: str, spec: dict | None = None) -> int:
    """无命令 → 转发执行器：`spec.orchestrate` 真值 → orch.py（编排器），否则 exec.py。

    为什么分档落在**转发层**而不是 exec.py 内部：编排器是独立 worker（要注册编排
    工具、把身份换成派生令牌编排器），放转发层后 exec.py 的累积式修复面零触碰
    （2026-09-16 Q1 裁定）。HIVE_ORCH_PY 可覆盖编排器路径（对称于 HIVE_LLM_EXEC_PY）。
    """
    if spec is None:
        try:
            with open(os.path.join(job_dir, "spec.json"), encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, ValueError):
            spec = {}
    here = os.path.dirname(os.path.abspath(__file__))
    if spec.get("orchestrate"):
        exe = os.environ.get("HIVE_ORCH_PY") or os.path.join(here, "orch.py")
        what = "orch.py（编排器）"
    else:
        exe = os.environ.get("HIVE_LLM_EXEC_PY") or os.path.join(here, "exec.py")
        what = "exec.py（LLM 委托）"
    if not os.path.isfile(exe):
        return _fail(job_dir, f"spec 无 command/commands，需转发 {what} 但未找到：{exe}",
                     EXIT_EXEC)
    p = subprocess.run([sys.executable, exe, job_dir], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.stdout:
        sys.stdout.write(p.stdout)
    if p.stderr:
        sys.stderr.write(p.stderr)
    return p.returncode


# 生效条件：job_dir/spec.json 读取抛 OSError/ValueError 即 _fail(..., EXIT_SPEC)；_norm_steps 返回 err 即 _fail(..., EXIT_SPEC)、返回 steps 为 None 即转 _delegate(job_dir, spec)；否则 env 由 spec.get("env") 字符串化后叠加在 os.environ 之上并 setdefault PYTHONUTF8="1"，default_cwd 取 spec.get("cwd") or spec.get("workdir") or job_dir，fail_fast 取 spec.get("fail_fast", True)（显式假值则不提前中断），逐步 _run_step 后按 expect_files、expect_stdout_contains 缺失项追加失败记录，写 result.json 并返回 EXIT_OK 或 EXIT_EXEC。
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
        return _delegate(job_dir, spec)

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
        "finished_ts": time.time(),
        "steps": recs,
        "model": "cmd",
        "usage": {},
    }
    if failed:
        result["error"] = "；".join(str(f.get("error") or f.get("label")) for f in failed)[:2000]
    _write_result(job_dir, result)
    return EXIT_OK if not failed else EXIT_EXEC


# 生效条件：len(sys.argv) < 2 时打印用法返回 EXIT_SPEC，sys.argv[1] 非目录时打印提示返回 EXIT_SPEC，否则返回 run_cmd(sys.argv[1])，其中任何异常由 _fail(job_dir, ..., EXIT_EXEC) 兜底转为返回码。
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
