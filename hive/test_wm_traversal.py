# -*- coding: utf-8 -*-
"""蜂巢工作记忆 · progress 面防穿越守卫（v8 N67 复测成立，2026-09-25 修复）。

背景：cmd_progress 的 --job-id 无路径段校验即裸拼两处——
  os.path.join(wm, "jobs", job_id, PROGRESS_FILE)（工作区直读）
  git show task/<job_id>:jobs/<job_id>/PROGRESS_FILE（分支读）
`../../victim` 可越权读 **wm 仓外**任意 JSONL 并全文回显（entries + handoff
聚合卡）；姊妹分支 cmd_snapshot 对同款输入有四行防穿越模板（in (".","..")
or "/" in or "\\\\" in 即拒）——防御不一致。
复现实测（evidence）：rc=0、ok=true、source=wm、entries 回显仓外哑标记。

修法：cmd_progress 的 --wm+--job-id 入口接同款四行模板（最小改动，
与 cmd_snapshot 防御一致）。

本测试（临时环境：临时区 git init 的 wm 仓 + 仓外哑标记 JSONL，测毕清理）：
  [G] 攻击形态拒绝（../../victim、含 \\、绝对段、. / ..）
  [Z] 合法面零回归（工作区直读 / git 分支两级查找 / cmd_snapshot 既有模板）
  [C] CLI 端到端（python hive/wm.py progress ...）rc 与单行 JSON 契约

运行：python -X utf8 -m hive.test_wm_traversal   （退出码 0 = 全绿）
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


wm = _load("hive_wm_guard", "wm.py")

TMP = tempfile.mkdtemp(prefix="hive_wm_trav_")
WM = os.path.join(TMP, "wm")
os.makedirs(WM)


def _git(*args):
    return subprocess.run(["git", "-C", WM, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          shell=False)


_git("init", "-b", "main")
_git("config", "user.email", "t@t")
_git("config", "user.name", "t")
# main 先诞生（空 commit）：否则 main 为 unborn 分支，task 分支 commit 后
# checkout main 必败、工作区残留 task 分支文件（fixture 自身失真）。
_git("commit", "--allow-empty", "-m", "init wm")

# 仓外哑标记 JSONL（evidence 形态）：DUMMY_MARKER / DUMMY_HANDOFF
VICTIM = os.path.join(TMP, "victim")
os.makedirs(VICTIM)
DUMMY = [json.dumps({"kind": "tool", "round": 1, "brief": "DUMMY_MARKER"}),
         json.dumps({"kind": "handoff", "content": "DUMMY_HANDOFF"})]
with open(os.path.join(VICTIM, wm.PROGRESS_FILE), "w", encoding="utf-8") as f:
    f.write("\n".join(DUMMY) + "\n")

# 合法 fixture ②：git 分支面（工作区无、task/hsafe2 分支有）。
# 注意：此步 add/commit 前不得存在其他 untracked 的 jobs/ 子目录（会被
# 一并带进 task 分支，checkout main 后从工作区消失）——hsafe 工作区
# fixture 在 checkout main 之后写。
_git("checkout", "-b", "task/hsafe2")
BR_DIR = os.path.join(WM, "jobs", "hsafe2")
os.makedirs(BR_DIR)
with open(os.path.join(BR_DIR, wm.PROGRESS_FILE), "w", encoding="utf-8") as f:
    f.write(json.dumps({"kind": "final", "content": "BRANCH_FINAL"}) + "\n")
_git("add", "jobs")
_git("commit", "-m", "task hsafe2")
_git("checkout", "main")

# 合法 fixture ①：工作区直读（wm/jobs/hsafe/，untracked——checkout 不碰）
SAFE_DIR = os.path.join(WM, "jobs", "hsafe")
os.makedirs(SAFE_DIR)
SAFE_ENTRIES = [json.dumps({"kind": "start", "task": "t"}),
                json.dumps({"kind": "handoff", "content": "SAFE_HANDOFF"})]
with open(os.path.join(SAFE_DIR, wm.PROGRESS_FILE), "w", encoding="utf-8") as f:
    f.write("\n".join(SAFE_ENTRIES) + "\n")

# ---------------------------------------------------------------- [G] 攻击拒绝
print("[G] 攻击形态拒绝（--job-id 穿越即拒，不泄露仓外内容）")
attacks = [
    ("G1 ../../victim（evidence 形态）", "../../victim"),
    ("G2 含反斜杠 ..\\..\\victim", "..\\..\\victim"),
    ("G3 绝对路径段 C:\\evil", "C:\\evil"),
    ("G4 单点 .", "."),
    ("G5 双点 ..", ".."),
]
for name, jid in attacks:
    r = wm.cmd_progress(wm=WM, job_id=jid)
    leaked = json.dumps(r, ensure_ascii=False)
    check(name, r.get("ok") is False
          and "非法 job_id" in (r.get("error") or "")
          and "DUMMY_MARKER" not in leaked and "DUMMY_HANDOFF" not in leaked,
          f"got {leaked[:240]}")

# ---------------------------------------------------------------- [Z] 零回归
print("[Z] 合法面零回归（直读 / 分支两级查找 / snapshot 既有模板）")
r = wm.cmd_progress(wm=WM, job_id="hsafe")
check("Z1 合法 job_id 工作区直读（source=wm + handoff）",
      r.get("ok") is True and r.get("source") == "wm"
      and (r.get("handoff") or {}).get("content") == "SAFE_HANDOFF",
      f"got {json.dumps(r, ensure_ascii=False)[:240]}")
r = wm.cmd_progress(wm=WM, job_id="hsafe2")
check("Z2 合法 job_id 分支两级查找（source=wm_branch）",
      r.get("ok") is True and r.get("source") == "wm_branch"
      and (r.get("entries") or [{}])[0].get("content") == "BRANCH_FINAL",
      f"got {json.dumps(r, ensure_ascii=False)[:240]}")

# cmd_snapshot 既有四行模板在位（姊妹面防御一致性锚点）
snap_job = os.path.join(TMP, "snapjob")
os.makedirs(snap_job)
with open(os.path.join(snap_job, "spec.json"), "w", encoding="utf-8") as f:
    json.dump({"job_id": "../../victim", "model": "m"}, f)
with open(os.path.join(snap_job, "result.json"), "w", encoding="utf-8") as f:
    json.dump({"ok": True, "content": "x",
               "job_id": "../../victim"}, f)
r = wm.cmd_snapshot(snap_job, WM)
check("Z3 cmd_snapshot 既有防穿越模板零回归（同输入仍拒）",
      r.get("ok") is False and "非法 job_id" in (r.get("error") or ""),
      f"got {json.dumps(r, ensure_ascii=False)[:240]}")

# ---------------------------------------------------------------- [C] CLI 端到端
print("[C] CLI 端到端（python hive/wm.py progress ...）")


def _cli(job_id: str):
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, os.path.join(_HERE, "wm.py"), "progress",
         "--wm", WM, "--job-id", job_id],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, shell=False, cwd=_REPO, timeout=60)


r = _cli("../../victim")
try:
    out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
except ValueError:
    out = {}
check("C1 CLI 穿越即拒（rc!=0、单行 JSON ok=false、无哑标记泄露）",
      r.returncode != 0 and out.get("ok") is False
      and "DUMMY_MARKER" not in r.stdout and "DUMMY_HANDOFF" not in r.stdout,
      f"rc={r.returncode} out={r.stdout[:200]!r}")
r = _cli("hsafe")
try:
    out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
except ValueError:
    out = {}
check("C2 CLI 合法 job_id 零回归（rc=0、ok=true）",
      r.returncode == 0 and out.get("ok") is True,
      f"rc={r.returncode} out={r.stdout[:200]!r}")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n结果: {PASS} pass / {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
