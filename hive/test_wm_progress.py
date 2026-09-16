# -*- coding: utf-8 -*-
"""蜂巢工作记忆 · 进展面单测（v0.4 §5.3 满上下文换人续跑）。

靶面三件（本轮落地）：
  ① exec.progress 写入面 → wm 快照白名单纳入 progress.jsonl；
  ② wm.cmd_progress 读取面（job 源 / wm 已快照源两路）；
  ③ CLI 面（python hive/wm.py progress ...）单行 JSON 契约。

不触网不调 API：进展条目由 ex.progress 真实写入临时目录（跨面契约守卫：
两个模块的 PROGRESS_FILE 必须同值、条目格式必须互认）。

运行：python hive/test_wm_progress.py   （退出码 0 = 全绿）
"""
import contextlib
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
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import importlib.util


def _load(mod_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, os.path.join(_HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ex = _load("hive_exec", "exec.py")
wm = _load("hive_wm", "wm.py")

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def _job(tmp, name, with_progress=True, ok=True, entries=3, bad_line=False):
    """造 job 目录：spec.json + result.json（+ progress.jsonl）。"""
    d = os.path.join(tmp, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
        json.dump({"job_id": name, "model": "m"}, f, ensure_ascii=False)
    with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
        json.dump({"ok": ok, "content": "done" if ok else "",
                   "error": "" if ok else "boom"},
                  f, ensure_ascii=False)
    if with_progress:
        ex.progress(d, kind="start", task="靶任务")
        for i in range(entries):
            ex.progress(d, kind="tool", round=i + 1, tool="lingshu_cg",
                        brief=f"第 {i + 1} 轮")
        if bad_line:
            with open(os.path.join(d, ex.PROGRESS_FILE), "a",
                      encoding="utf-8") as f:
                f.write("{不是合法JSON\n")
    return d


print("[A] 跨面契约（exec 写入面 ↔ wm 读取面）")
check("A1 wm.PROGRESS_FILE == ex.PROGRESS_FILE == progress.jsonl",
      wm.PROGRESS_FILE == ex.PROGRESS_FILE == "progress.jsonl",
      f"{wm.PROGRESS_FILE!r} vs {ex.PROGRESS_FILE!r}")

tmp = tempfile.mkdtemp(prefix="hive_wm_prog_")
j1 = _job(tmp, "job_a")
entries, total = wm._read_progress(os.path.join(j1, ex.PROGRESS_FILE), 50)
check("A2 ex.progress 写的条目 wm 可解析（格式互认）",
      total == 4 and all(isinstance(e, dict) for e in entries)
      and entries[0].get("kind") == "start", f"total={total}")
check("A3 条目带时间戳（ts，观测面）",
      all(isinstance(e.get("ts"), (int, float)) for e in entries))

ex.progress(os.path.join(tmp, "不存在目录"), kind="tool")
check("A4 ex.progress 对非目录 no-op 不炸", True)

print("[B] 快照白名单（progress.jsonl 纳入）")
wm_repo = os.path.join(tmp, "wm")
check("B1 cmd_init 建仓成功", wm.cmd_init(wm_repo).get("ok") is True)

snap1 = wm.cmd_snapshot(j1, wm_repo)
check("B2 含进展的 job 可快照（凭证闸通过）", snap1.get("ok") is True,
      str(snap1)[:200])
check("B3 snapshot 回报 progress=True", snap1.get("progress") is True,
      str(snap1.get("progress")))
# 快照提交后 HEAD 还原 main——产物只在 task/<job_id> 分支（读取面须两级查找）
_br = wm._git(wm_repo, "show", f"task/job_a:jobs/job_a/{ex.PROGRESS_FILE}")
check("B4 进展卡随快照入分支", _br.returncode == 0,
      (_br.stderr or "")[:120])
if _br.returncode == 0:
    with open(os.path.join(j1, ex.PROGRESS_FILE), encoding="utf-8") as f:
        src_lines = [ln.rstrip("\n") for ln in f if ln.strip()]
    check("B5 入库内容与源逐行一致",
          _br.stdout.strip("\n").split("\n") == src_lines)

j2 = _job(tmp, "job_b", with_progress=False)
snap2 = wm.cmd_snapshot(j2, wm_repo)
check("B6 无进展的 job 仍可快照（可选件不阻塞）", snap2.get("ok") is True,
      str(snap2)[:200])
check("B7 无进展时回报 progress=False", snap2.get("progress") is False)
check("B8 未生成空进展卡（不伪造）",
      not os.path.isfile(os.path.join(wm_repo, "jobs", "job_b",
                                      ex.PROGRESS_FILE)))

j3 = _job(tmp, "job_c", ok=False)
bad = wm.cmd_snapshot(j3, wm_repo)
check("B9 凭证闸仍在（result.ok=false 拒绝快照）", bad.get("ok") is False
      and "凭证不足" in str(bad.get("error")), str(bad)[:160])

print("[C] 读取面 · job 源")
r1 = wm.cmd_progress(job=j1)
check("C1 job 源可读", r1.get("ok") is True and r1.get("source") == "job")
check("C2 计数正确（count=尾部数 / total=全量）",
      r1.get("count") == 4 and r1.get("total") == 4, str(r1.get("count")))
check("C3 kinds 逐类计数",
      r1.get("kinds", {}).get("start") == 1
      and r1.get("kinds", {}).get("tool") == 3, str(r1.get("kinds")))
check("C4 无 handoff 条目时 handoff=None", r1.get("handoff") is None)

j4 = _job(tmp, "job_d", entries=2)
# 用 exec 真实交回路径产出 handoff（不是手工造条目）——守卫「执行器产物 ↔ wm 读取面」互认
_hd = ex._handoff({"model": "m"}, j4,
                  [{"round": 1, "tool": "lingshu_cg", "ok": True, "brief": "第 1 轮"}],
                  {"total_tokens": 123}, 3, 210000, 200000)
check("C5a _handoff 产物带 need_continue/completed（交接信号）",
      _hd.get("need_continue") is True and _hd.get("completed") is False)
r4 = wm.cmd_progress(job=j4)
check("C5b handoff 聚合透出（续跑卡）",
      isinstance(r4.get("handoff"), dict)
      and r4["handoff"].get("reason") == "context_budget",
      str(r4.get("handoff"))[:160])
check("C5c handoff 卡携带预算证据（est/budget_tokens）",
      r4["handoff"].get("est_tokens") == 210000
      and r4["handoff"].get("budget_tokens") == 200000,
      str(r4.get("handoff"))[:200])
check("C5d handoff 卡声明不自动续跑（auto_continue=false）",
      r4["handoff"].get("auto_continue") is False)
# 跨面词汇守卫：同一交回事件的两个观测面（进展卡 / result.json handoff 块）
# 必须同词——分叉会让主代理组装续跑提示词时读到两套字段（2026-09-16 取证）。
_shared_keys = ("reason", "est_tokens", "budget_tokens", "progress_file",
                "auto_continue")
check("C5f 卡与 result 的 handoff 块词汇互认（防两套字段名）",
      all(k in r4["handoff"] and k in _hd["handoff"] for k in _shared_keys),
      f"card={sorted(r4['handoff'])} result={sorted(_hd['handoff'])}")
check("C5e 交回摘要含进展卡指引（主代理组装续跑提示词）",
      "progress.jsonl" in str(r4.get("entries", [{}])[-1].get("summary")))

r5 = wm.cmd_progress(job=j1, limit=2)
check("C7 limit 取尾部 N 条", r5.get("count") == 2 and r5.get("total") == 4,
      f"count={r5.get('count')} total={r5.get('total')}")
check("C8 limit=0 全量", wm.cmd_progress(job=j1, limit=0).get("count") == 4)

j5 = _job(tmp, "job_e", entries=1, bad_line=True)
r6 = wm.cmd_progress(job=j5)
check("C9 坏行跳过不炸（诚实降级）",
      r6.get("ok") is True and r6.get("count") == 2, str(r6.get("count")))

print("[D] 读取面 · wm 已快照源（两级查找：分支态 → 工作区）")
r7 = wm.cmd_progress(wm=wm_repo, job_id="job_a")
check("D1 分支态可读（source=wm_branch）",
      r7.get("ok") is True and r7.get("source") == "wm_branch",
      str(r7)[:200])
check("D2 与 job 源内容一致",
      [e.get("kind") for e in r7.get("entries", [])]
      == [e.get("kind") for e in r1.get("entries", [])])
check("D2b ref 记读取出处（诊断可见）",
      "task/job_a" in str(r7.get("ref")), str(r7.get("ref")))
check("D2c 未 fast 分支的 job（job_b 无进展）如实报缺",
      wm.cmd_progress(wm=wm_repo, job_id="job_b").get("ok") is False)

# 交回 job（含 handoff 卡）走完整链路：snapshot → 分支读回
snap_d = wm.cmd_snapshot(j4, wm_repo)
check("D3 交回 job 可快照（need_continue 链路闭环）",
      snap_d.get("ok") is True, str(snap_d)[:200])
r_d = wm.cmd_progress(wm=wm_repo, job_id="job_d")
check("D4 分支态透出 handoff（续跑卡可读）",
      r_d.get("ok") is True and isinstance(r_d.get("handoff"), dict)
      and r_d["handoff"].get("reason") == "context_budget", str(r_d)[:200])

# 合并到 main → 工作区直读形态
mg = wm.cmd_merge("task/job_a", wm_repo)
check("D5 cmd_merge 回主支成功", mg.get("ok") is True, str(mg)[:200])
r_ws = wm.cmd_progress(wm=wm_repo, job_id="job_a")
check("D6 合并后工作区直读（source=wm，两级查找第二级回归）",
      r_ws.get("ok") is True and r_ws.get("source") == "wm", str(r_ws)[:200])
check("D7 两级查找结果一致（分支态 vs 工作区）",
      [e.get("kind") for e in r_ws.get("entries", [])]
      == [e.get("kind") for e in r7.get("entries", [])])

r8 = wm.cmd_progress(job=j1, wm=wm_repo, job_id="job_a")
check("D8 --job 与 --wm 二选一（并用即拒）", r8.get("ok") is False,
      str(r8.get("error"))[:120])
check("D9 两者都不给即拒", wm.cmd_progress().get("ok") is False)
r9 = wm.cmd_progress(wm=wm_repo, job_id="job_zzz")
check("D10 不存在时 ok=False + hint（不静默成空进展）",
      r9.get("ok") is False and "hint" in r9, str(r9)[:160])

print("[E] CLI 面（单行 JSON 契约）")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code = wm.main(["progress", "--job", j4])
out = buf.getvalue().strip()
check("E1 --job 退出码 0", code == 0, f"code={code}")
check("E2 输出单行 JSON 且 ok=true", "\n" not in out and json.loads(out).get("ok") is True,
      out[:160])
check("E3 CLI 面同样透出 handoff",
      json.loads(out).get("handoff", {}).get("reason") == "context_budget")

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code2 = wm.main(["progress", "--wm", wm_repo, "--job-id", "job_a"])
check("E4 --wm/--job-id 退出码 0", code2 == 0
      and json.loads(buf.getvalue().strip()).get("ok") is True)

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code3 = wm.main(["progress", "--wm", wm_repo, "--job-id", "job_zzz"])
check("E5 缺进展时退出码非 0（fail 可见）", code3 != 0,
      f"code={code3}")

print("[F] 边界")
j6 = _job(tmp, "job_f", with_progress=False)
open(os.path.join(j6, ex.PROGRESS_FILE), "w", encoding="utf-8").close()
r11 = wm.cmd_progress(job=j6)
check("F1 空进展卡 → ok=true / count=0 / handoff=None",
      r11.get("ok") is True and r11.get("count") == 0
      and r11.get("handoff") is None, str(r11)[:160])

print(f"\n结果：PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
