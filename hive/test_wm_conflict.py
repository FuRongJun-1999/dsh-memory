# -*- coding: utf-8 -*-
"""蜂巢工作记忆 · R02 矛盾态凭证闸守卫（批次58）。

背景（R02 矛盾态，v17/DSH 专项两轮确认的欠账）：serve 被外部硬杀 → 执行器成
孤儿继续跑 → serve 重启时 recover_orphans 因产物未落盘标 error（scheduler.rs
无产物分支），此后 error 终态落入 `match _ => {}` 永不再回看——孤儿自然完成
时补写的 result.json ok=true 与已定 error 终态矛盾固化。观测面（hive poll
合体视图）修复后透出 conflict=late_result_after_error；本测试钉死消费面：
cmd_snapshot 凭证闸对矛盾态拒放行（第 5 条「未验证不写入」——记账面已判负、
产物面自报成功，矛盾未人工裁决前不许入库）。

哑 job 形态（与 scheduler.rs recover_orphans 无产物分支逐字同字段）：
  status.json {"state":"error","error":"serve 中断：任务执行被重置"}
  result.json {"ok":true,...}（孤儿补写）

本测试（临时环境：临时区 git init 的 wm 仓 + 哑 job 目录，测毕清理）：
  [G] 矛盾态拒绝（state=error + ok=true → ok=False + conflict 字段 + 无残留）
  [Z] 零回归（done+ok 正常入仓 / 无 status.json 旧格式放行）
  [C] CLI 端到端（python hive/wm.py snapshot ... rc 与单行 JSON 契约）

运行：python -X utf8 -m hive.test_wm_conflict   （退出码 0 = 全绿）
"""
from __future__ import annotations

import importlib.util
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


def _load(mod_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, os.path.join(_HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wm = _load("hive_wm_conflict", "wm.py")

TMP = tempfile.mkdtemp(prefix="hive_wm_conflict_")
WM = os.path.join(TMP, "wm")


def _git(*args):
    return subprocess.run(["git", "-C", WM, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          shell=False)


def _mk_wm() -> None:
    """全新哑 wm 仓（main 先诞生：unborn 分支 checkout 必败，fixture 失真）。"""
    os.makedirs(WM, exist_ok=True)
    _git("init", "-b", "main")
    _git("config", "user.email", "t@t")
    _git("config", "user.name", "t")
    _git("commit", "--allow-empty", "-m", "init wm")


def _mk_job(name: str, state: str | None, ok, result_extra: str = "",
            raw_status: str | None = None) -> str:
    """哑 job 目录：status.json（state 或原样残片）+ result.json + spec.json。"""
    d = os.path.join(TMP, name)
    os.makedirs(d)
    if raw_status is not None:
        with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
            f.write(raw_status)
    elif state is not None:
        with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
            json.dump({"job_id": name, "state": state,
                       "error": "serve 中断：任务执行被重置"}, f)
    with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
        json.dump({"ok": ok, "content": f"{name} 产物", "job_id": name,
                   "model": "m"} | (json.loads(result_extra) if result_extra else {}), f)
    with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
        json.dump({"model": "m", "user_prompt": "x"}, f)
    return d


# ---------------------------------------------------------------- [G] 矛盾态拒绝
print("[G] 矛盾态拒绝（state=error + result.ok=true → 拒放行，须人工裁决）")
_mk_wm()
conflict_dir = _mk_job("hconflict1", "error", True)
r = wm.cmd_snapshot(conflict_dir, WM)
leaked = json.dumps(r, ensure_ascii=False)
check("G1 矛盾态快照拒绝（ok=False + conflict=late_result_after_error）",
      r.get("ok") is False and r.get("conflict") == "late_result_after_error"
      and "矛盾" in (r.get("error") or ""),
      f"got {leaked[:300]}")
check("G2 拒绝发生在 staging 前（wm/jobs/hconflict1 无残留）",
      not os.path.isdir(os.path.join(WM, "jobs", "hconflict1")))
# git 侧双确认：无 task 分支、main 无新提交（拒得干净）
br = _git("branch", "--list", "task/hconflict1")
check("G3 未产出 task 分支", br.stdout.strip() == "", f"got {br.stdout!r}")

# ---------------------------------------------------------------- [Z] 零回归
print("[Z] 零回归（正常成功入仓 / 无 status.json 旧格式放行）")
done_dir = _mk_job("hdone1", "done", True)
r = wm.cmd_snapshot(done_dir, WM)
check("Z1 done+ok=true 正常快照仍放行（ok=True + commit 存在）",
      r.get("ok") is True and bool(r.get("commit")),
      f"got {json.dumps(r, ensure_ascii=False)[:300]}")
legacy_dir = _mk_job("hlegacy1", None, True)  # 无 status.json（旧格式/手工目录）
r = wm.cmd_snapshot(legacy_dir, WM)
check("Z2 无 status.json 旧格式凭证面零回归（ok 门单独裁决仍放行）",
      r.get("ok") is True and bool(r.get("commit")),
      f"got {json.dumps(r, ensure_ascii=False)[:300]}")
badstatus_dir = _mk_job("hbadstatus1", None, True,
                        raw_status='{"state": "err')  # 记账面残片（事故信号不吞）
r = wm.cmd_snapshot(badstatus_dir, WM)
check("Z3 status.json 不可读 fail-closed 拒绝（ok=False + 指名 status.json）",
      r.get("ok") is False and "status.json" in (r.get("error") or ""),
      f"got {json.dumps(r, ensure_ascii=False)[:300]}")

# ---------------------------------------------------------------- [C] CLI 端到端
print("[C] CLI 端到端（python hive/wm.py snapshot ...）")
_mk_wm()  # 换新仓：G 段拒绝不应在仓里留任何痕
conflict_dir2 = _mk_job("hconflict2", "error", True)
env = dict(os.environ, PYTHONUTF8="1")
p = subprocess.run(
    [sys.executable, os.path.join(_HERE, "wm.py"), "snapshot",
     "--job", conflict_dir2, "--wm", WM],
    capture_output=True, text=True, encoding="utf-8", errors="replace",
    env=env, shell=False, cwd=_REPO, timeout=60)
try:
    out = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
except ValueError:
    out = {}
check("C1 CLI 矛盾态即拒（rc!=0、单行 JSON ok=false + conflict 字段）",
      p.returncode != 0 and out.get("ok") is False
      and out.get("conflict") == "late_result_after_error",
      f"rc={p.returncode} out={p.stdout[:240]!r} err={p.stderr[:120]!r}")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n共 {PASS + FAIL} 检查：通过 {PASS}，失败 {FAIL}")
sys.exit(0 if FAIL == 0 else 1)
