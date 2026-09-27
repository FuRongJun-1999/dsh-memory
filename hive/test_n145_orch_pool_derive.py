# -*- coding: utf-8 -*-
"""N145 守卫（第 23 轮，2026-09-28）：编排器子任务池解析不含 job_dir 父目录
推导——`hive serve --jobs X` 无键形态下 spawn_subtask 落错池静默饿死。
（历轮口径 N142，v17 重编 N145；N142 已被 orch.py:271-313 批次 49
children/spec 原子写占用，本守卫取重编后的 N145。）

病灶（hive/orch.py:477 / :662，本轮 HEAD 读核在位；git log -- hive/orch.py
末触 0817b2cf 批次 49 N89 双源同一决策函数——env/config 同源而**不含
job_dir 推导**）：编排器 _spawn 的池解析 `jobs = _hm._jobs_dir()` 只吃
进程 env + config.local.json（hive_mcp/mcp_server.py:96 经
serve_start._jobs_from 合并，两键皆空回落 REPO/hive/jobs 默认池），不读
自身 job_dir。rust spawn_executor（hive/src/exec.rs:91-107）Command 继承
serve env 且仅注入 HIVE_RESULT_ANCHOR 不注入 HIVE_JOBS_DIR——serve 以
`hive serve --jobs X` 显式钉池启动且 env/config 均未设键时，编排 worker
的 _jobs_dir() 回落默认池 ≠ X：spawn_subtask 把子任务提交进默认池，serve
在池 X 无人领取，子任务永久饿死；spawn 返回 ok=True，编排者模型无感知。

红守卫（全部子进程隔离：env 弹 HIVE_JOBS_DIR + 空临时 config 经
HIVE_CONFIG 指定，防触仓内真实 config 与真实池；只做解析面观测零提交）：
  R1 核心红面（对应缺陷报告独立子进程复现口径）：双键皆空 + 编排
     job_dir 在临时池 X 下 → 池解析必须得 X 的父目录（旧口径回落
     REPO/hive/jobs 默认池，DIVERGED）；
  R2 env 设键（N89 对照组，零闸变）：HIVE_JOBS_DIR=Y → 解析 = Y；
  R3 config 设键（N89 config 同权，零闸变）：HIVE_CONFIG 指 config 键
     Z 且 env 无键 → 解析 = Z；
  R4 config 优先（N89 合并语义）：env=Y 且 config=Z → 解析 = Z；
  R5 回落面（修后新增分支防误伤）：双键皆空 + job_dir 未就位（空串）
     → 回落 _hm._jobs_dir() 默认池，不崩不产怪值；
  R6 源码装配面：_spawn 的池解析行与 run() 的 _CFG['jobs'] 行必须走
     _resolve_jobs_dir（:477 与 :662 双点位同修，防只修读面或只修写面）。
运行：python -X utf8 hive/test_n145_orch_pool_derive.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))          # hive/
REPO = os.path.dirname(HERE)

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        fails.append(name)


# 子进程脚本：真实 orch 模块 + 真实解析路径。修后走 orch._resolve_jobs_dir()；
# 旧代码无该函数 → 回落 :477 的原内联表达式 _hm._jobs_dir()（与部署代码
# 逐字同路，非第二实现）。
_CHILD = r"""
import os, sys
hive_dir, job_dir = sys.argv[1], sys.argv[2]
sys.path.insert(0, hive_dir)
import orch
orch._CFG["job_dir"] = job_dir
fn = getattr(orch, "_resolve_jobs_dir", None)
jobs = fn() if fn is not None else orch._hm._jobs_dir()
print("RESOLVED=" + jobs)
"""


def _resolve(env_overrides, job_dir, tmp):
    """子进程跑一次解析，返回 (resolved|None, stderr 尾)。"""
    child = os.path.join(tmp, "_child_resolve.py")
    if not os.path.exists(child):
        with open(child, "w", encoding="utf-8") as f:
            f.write(_CHILD)
    env = {k: v for k, v in os.environ.items() if k != "HIVE_JOBS_DIR"}
    env.update(env_overrides)
    env["PYTHONUTF8"] = "1"
    p = subprocess.run([sys.executable, "-X", "utf8", child, HERE, job_dir],
                       capture_output=True, text=True, env=env,
                       cwd=tmp, timeout=120)
    out = (p.stdout or "").strip().splitlines()
    resolved = None
    for line in out:
        if line.startswith("RESOLVED="):
            resolved = line[len("RESOLVED="):]
    return resolved, (p.stderr or "")[-300:]


def _job_in(tmp, pool_name, job_name):
    pool = os.path.join(tmp, pool_name)
    jd = os.path.join(pool, job_name)
    os.makedirs(jd, exist_ok=True)
    return pool, jd


def _config(tmp, name, mapping):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False)
    return p


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tmp = tempfile.mkdtemp(prefix="hive_n145_")
    try:
        empty_cfg = _config(tmp, "empty_config.json", {})
        pool_x, job_x = _job_in(tmp, "poolX", "h_orch_a")
        default_pool = os.path.join(HERE, "jobs")

        # ---------- R1 核心红面：双键皆空 + serve --jobs X 形态 ----------
        print("== R1 双键皆空：池解析必须从编排 job_dir 父目录推导 ==")
        r1, err1 = _resolve({"HIVE_CONFIG": empty_cfg}, job_x, tmp)
        check("R1 解析 = serve 实际监听池 X（旧口径回落默认池即红）",
              r1 is not None
              and os.path.normcase(os.path.abspath(r1))
              == os.path.normcase(os.path.abspath(pool_x)),
              f"resolved={r1} poolX={pool_x} stderr={err1[:120]}")

        # ---------- R2 env 设键（N89 对照组，零闸变） ----------
        print("== R2 env 设键：HIVE_JOBS_DIR=Y → 解析 = Y（N89 不动） ==")
        pool_y, _jy = _job_in(tmp, "poolY", "h_probe")
        r2, _ = _resolve({"HIVE_CONFIG": empty_cfg,
                          "HIVE_JOBS_DIR": pool_y}, job_x, tmp)
        check("R2 env 键生效（零闸变）",
              r2 is not None
              and os.path.normcase(os.path.abspath(r2))
              == os.path.normcase(os.path.abspath(pool_y)),
              f"resolved={r2}")

        # ---------- R3 config 设键（N89 config 同权，零闸变） ----------
        print("== R3 config 设键：config 键 Z 且 env 无键 → 解析 = Z ==")
        pool_z, _jz = _job_in(tmp, "poolZ", "h_probe")
        cfg_z = _config(tmp, "cfg_z.json", {"HIVE_JOBS_DIR": pool_z})
        r3, _ = _resolve({"HIVE_CONFIG": cfg_z}, job_x, tmp)
        check("R3 config 键生效（N89 同权，零闸变）",
              r3 is not None
              and os.path.normcase(os.path.abspath(r3))
              == os.path.normcase(os.path.abspath(pool_z)),
              f"resolved={r3}")

        # ---------- R4 config 优先（N89 合并语义） ----------
        print("== R4 env=Y 且 config=Z → 解析 = Z（config 胜出） ==")
        r4, _ = _resolve({"HIVE_CONFIG": cfg_z,
                          "HIVE_JOBS_DIR": pool_y}, job_x, tmp)
        check("R4 config 键胜出（N89 合并语义不动）",
              r4 is not None
              and os.path.normcase(os.path.abspath(r4))
              == os.path.normcase(os.path.abspath(pool_z)),
              f"resolved={r4}")

        # ---------- R5 回落面：job_dir 未就位不崩、回落默认池 ----------
        print("== R5 job_dir 未就位（空串）→ 回落默认池不崩 ==")
        r5, err5 = _resolve({"HIVE_CONFIG": empty_cfg}, "", tmp)
        check("R5 回落 _hm._jobs_dir() 默认池（无键时 serve_start.JOBS 口径）",
              r5 is not None
              and os.path.normcase(os.path.abspath(r5))
              == os.path.normcase(os.path.abspath(default_pool)),
              f"resolved={r5} stderr={err5[:120]}")

        # ---------- R6 源码装配面：双点位同修 ----------
        print("== R6 源码装配：_spawn 与 run() 的池解析都走 _resolve_jobs_dir ==")
        with open(os.path.join(HERE, "orch.py"), encoding="utf-8") as f:
            src = f.read()
        check("R6a _spawn 池解析行走 _resolve_jobs_dir()",
              "jobs = _resolve_jobs_dir()" in src
              and "_hm._jobs_dir()\n    cid = _hm._submit" not in src)
        check("R6b run() _CFG['jobs'] 走 _resolve_jobs_dir(job_dir)",
              '"jobs": _resolve_jobs_dir(job_dir)' in src)
        check("R6c 推导函数在位（含父目录推导）",
              "def _resolve_jobs_dir" in src
              and "os.path.dirname" in src)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nRESULT:", "ALL_PASS" if not fails else f"FAILED={fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
