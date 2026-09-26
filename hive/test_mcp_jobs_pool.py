# -*- coding: utf-8 -*-
"""hive MCP jobs 池单源守卫（N89：MCP 面与 serve 面 jobs 池双源分叉）。

背景（v2 N17 首报，v10/v15/第17轮四轮维持）：mcp_server._jobs_dir() 只读
**MCP 进程 env**（os.environ["HIVE_JOBS_DIR"]，缺省 <仓>/hive/jobs），而 serve
侧 serve_start.start() 以 `{**os.environ, **config}` 合并环境经 _jobs_from
延迟求值（serve_start.py:231/:236）——**config.local.json 的 HIVE_JOBS_DIR
键覆盖进程 env**。config 设该键且 MCP 进程 env 未设的部署态（合法配置面）：
hive_spawn 返回 ok=True 但任务落进默认池，serve 只盯 config 池——任务永无人
领取，poll/doctor 观测面全绿与实况相悖。os.environ.setdefault 不构成补救
（_ensure_serve :196 设的是 env，:231 的 config 键照样覆盖）。

修法（一行级）：_jobs_dir 改经 serve_start._jobs_from({**os.environ,
**(load_config(CONFIG_LOCAL)[0] or {})})——与 serve 侧同一决策函数、同一合并
语义；config 缺失/解析失败时 cfg={} 自然回落 env/默认（与 serve_start
_lifecycle_jobs 的「stop 不能因 config 笔误而停不掉」宽容语义一致）。

本测试（临时 config+哑 key+临时双池，HIVE_CONFIG 钉临时文件，绝不触真实
池/真实 serve；_jobs_dir 只是路径决策点，不拉起任何进程）：
  [A] 分叉复现：config 设池 + env 未设 → _jobs_dir() 须==serve 侧决策池
      （旧代码回落默认仓池 → 红=DIVERGED）
  [B] 优先级对齐：config 键胜过 MCP 进程 env（旧代码 env 池 → 红）
  [C] 零回归：config 无该键→env 池；HIVE_CONFIG 不存在→env/默认池；
      config 解析失败→fail-soft 回落（与 _lifecycle_jobs 同宽容度）
  [D] 源断言：spawn/poll/kill/doctor/restart 五面同走 _jobs_dir（改一处即全修）
运行：python -X utf8 -m hive.test_mcp_jobs_pool   （退出码 0 = 全绿）
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
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
        return
    FAIL += 1
    print(f"  [FAIL] {name}  {detail}")


def _load(tag: str, filename: str, here: str):
    spec = importlib.util.spec_from_file_location(
        f"hive_n89_{tag}", os.path.join(here, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ss = _load("serve_start", "serve_start.py", _HERE)
MCP_PATH = os.path.join(_HERE, "hive_mcp", "mcp_server.py")

TMP = tempfile.mkdtemp(prefix="hive_n89_")
SERVE_POOL = tempfile.mkdtemp(prefix="hive_n89_serve_pool_")   # config 指定池
MCP_ENV_POOL = tempfile.mkdtemp(prefix="hive_n89_env_pool_")   # 进程 env 池
CFG = os.path.join(TMP, "config.local.json")

with open(CFG, "w", encoding="utf-8") as f:
    json.dump({"HIVE_API_KEY": "DUMMY-KEY-n89-not-a-real-credential-0123456789",
               "HIVE_JOBS_DIR": SERVE_POOL}, f)
CFG_NOKEY = os.path.join(TMP, "config_nokey.json")
with open(CFG_NOKEY, "w", encoding="utf-8") as f:
    json.dump({"HIVE_API_KEY": "DUMMY-KEY-n89-not-a-real-credential-0123456789"},
              f)
CFG_BAD = os.path.join(TMP, "config_bad.json")
with open(CFG_BAD, "w", encoding="utf-8") as f:
    f.write("{{{ 不是 JSON")

_BASE = {k: v for k, v in os.environ.items() if k != "HIVE_JOBS_DIR"}
DEFAULT_POOL = os.path.join(_load("mcp_probe", "mcp_server.py",
                                  os.path.join(_HERE, "hive_mcp")).REPO,
                            "hive", "jobs")


def _serve_decision(cfg_path: str, env_map: dict) -> str:
    """serve 侧决策原式（serve_start.start 合并环境 :231 + _jobs_from :236）。"""
    cfg, err = ss.load_config(cfg_path)
    return ss._jobs_from({**env_map, **(cfg or {})}), err


def _mcp_jobs_dir(tag: str, cfg_path: str, env_extra: dict) -> str:
    """按指定 HIVE_CONFIG/env 装载全新 mcp_server 实例并取 _jobs_dir()。

    只控 HIVE_CONFIG/HIVE_JOBS_DIR 两键（其余真实 env 保持——Windows 下清空
    全部 env 有连坐风险），退出时由 mock.patch.dict 原样恢复。
    """
    with mock.patch.dict(os.environ):
        os.environ.pop("HIVE_JOBS_DIR", None)
        os.environ["HIVE_CONFIG"] = cfg_path
        for k, v in env_extra.items():
            os.environ[k] = v
        mcp = _load(f"mcp_{tag}", "mcp_server.py",
                    os.path.join(_HERE, "hive_mcp"))
        return mcp._jobs_dir()


# ------------------------------------------------------- [A] 分叉复现（主攻面）
print("[A] 分叉复现：config 设池 + MCP env 未设 → 两面必须同池")
serve_pool_a, err_a = _serve_decision(CFG, _BASE)
check("A0 serve 侧决策=config 池（前提成立）",
      serve_pool_a == SERVE_POOL and err_a is None,
      f"serve={serve_pool_a} err={err_a}")
mcp_pool_a = _mcp_jobs_dir("a", CFG, {})
check("A1 MCP 面 _jobs_dir()==serve 侧决策池（旧代码=默认仓池→DIVERGED 红）",
      mcp_pool_a == serve_pool_a,
      f"mcp={mcp_pool_a} serve={serve_pool_a}")

# ------------------------------------------------- [B] 优先级对齐（config 胜 env）
print("[B] 优先级对齐：config 键胜过 MCP 进程 env（:231 合并语义）")
serve_pool_b, _ = _serve_decision(CFG, {**_BASE, "HIVE_JOBS_DIR": MCP_ENV_POOL})
mcp_pool_b = _mcp_jobs_dir("b", CFG, {"HIVE_JOBS_DIR": MCP_ENV_POOL})
check("B1 serve 侧=config 池（config 覆盖 env）", serve_pool_b == SERVE_POOL,
      f"got {serve_pool_b}")
check("B2 MCP 面同判 config 池（旧代码=env 池→与 serve 分叉红）",
      mcp_pool_b == serve_pool_b,
      f"mcp={mcp_pool_b} serve={serve_pool_b}")

# ------------------------------------------------------- [C] 零回归（三态回落）
print("[C] 零回归：config 无该键/缺失/坏配置 → env/默认池回落不变")
mcp_pool_c = _mcp_jobs_dir("c", CFG_NOKEY, {"HIVE_JOBS_DIR": MCP_ENV_POOL})
check("C1 config 无 HIVE_JOBS_DIR → env 池",
      mcp_pool_c == MCP_ENV_POOL, f"got {mcp_pool_c}")
mcp_pool_d = _mcp_jobs_dir("d", os.path.join(TMP, "不存在.json"), {})
check("D1 HIVE_CONFIG 指向不存在文件 → 默认仓池（fail-soft 不崩）",
      mcp_pool_d == DEFAULT_POOL, f"got {mcp_pool_d}")
mcp_pool_e = _mcp_jobs_dir("e", CFG_BAD, {})
check("E1 config 解析失败 → 默认仓池（与 _lifecycle_jobs 同宽容度）",
      mcp_pool_e == DEFAULT_POOL, f"got {mcp_pool_e}")
check("E2 坏配置不阻断决策（返回真实存在可写的池路径）",
      os.path.isdir(mcp_pool_e))

# ------------------------------------------------------------- [D] 源断言
print("[D] 源断言：五面同走 _jobs_dir（单点修复即全修）")
with open(MCP_PATH, encoding="utf-8") as f:
    MCP_PY = f.read()
check("D1 决策口径与 serve 同源（_jobs_from 进入 mcp_server）",
      "_jobs_from(" in MCP_PY and "_load_local_config()" in MCP_PY)
for fn in ("_t_spawn", "_t_poll", "_t_kill", "_t_doctor", "_t_restart"):
    check(f"D2 {fn} 走 _jobs_dir()",
          f"def {fn}" in MCP_PY
          and MCP_PY.split(f"def {fn}", 1)[1].split("\ndef ", 1)[0]
          .count("_jobs_dir()") >= 1)
_body = MCP_PY.split("def _jobs_dir", 1)[1].split("\ndef ", 1)[0]
check("D3 _jobs_dir 体走 _load_local_config→_jobs_from（单源合一）",
      "_load_local_config()" in _body and "_jobs_from(" in _body,
      f"body={_body[:200]!r}")

shutil.rmtree(TMP, ignore_errors=True)
for p in (SERVE_POOL, MCP_ENV_POOL):
    shutil.rmtree(p, ignore_errors=True)
print(f"\n结果: {PASS} pass / {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
