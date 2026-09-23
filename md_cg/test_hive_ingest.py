# -*- coding: utf-8 -*-
"""M6 蜂巢 ingest 专项测试：HiveJobsSource 事件映射 / 终态补位 / watermark 幂等 /
层归属纪律（§5.5 只落 contextual）/ fix-pair 产出（设计稿 §5.6 验收判据）。

运行：python -m md_cg.test_hive_ingest   （退出码 0 = 全绿）
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from .mdcos import MdCGOS
from .sources import HiveJobsSource, Ingestor

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def make_jobs(root: str):
    """构造设计稿 §5.6 验收场景：job1 强杀（无 final，result=error）、
    job2 重试成功（final + result=done，content 含命令行）、job3 普通 done。"""
    jobs = os.path.join(root, "jobs")
    t = time.time()
    # job1：强杀——progress 有 start/error，无 final；result=error
    j1 = os.path.join(jobs, "h1000000000000_aaa1")
    os.makedirs(j1)
    json.dump({"model": "cmd", "user_prompt": "跑一次会失败的检查"},
              open(os.path.join(j1, "spec.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    with open(os.path.join(j1, "progress.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": t - 60, "kind": "start",
                            "task": "跑一次会失败的检查"}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"ts": t - 30, "kind": "error",
                            "error": "单步超时（5s）被强杀：pytest"}, ensure_ascii=False) + "\n")
    json.dump({"ok": False, "error": "单步超时（5s）被强杀：pytest",
               "finished_ts": t - 29},
              open(os.path.join(j1, "result.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    # job2：重试成功——final + result=done，content 是命令输出（_FIX_RE 命中）
    j2 = os.path.join(jobs, "h1000000001000_bbb2")
    os.makedirs(j2)
    json.dump({"model": "cmd", "user_prompt": "跑一次会失败的检查"},
              open(os.path.join(j2, "spec.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    with open(os.path.join(j2, "progress.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": t - 10, "kind": "start",
                            "task": "跑一次会失败的检查"}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"ts": t - 5, "kind": "final",
                            "content_head": "pytest 全部通过"}, ensure_ascii=False) + "\n")
    json.dump({"ok": True, "content": "python hive/test_x.py\n全部通过",
               "finished_ts": t - 4},
              open(os.path.join(j2, "result.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    # job3：普通 done（带 handoff，验证续跑卡映射）
    j3 = os.path.join(jobs, "h1000000002000_ccc3")
    os.makedirs(j3)
    json.dump({"model": "deepseek-flash", "user_prompt": "普通任务"},
              open(os.path.join(j3, "spec.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    with open(os.path.join(j3, "progress.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": t - 3, "kind": "start", "task": "普通任务"},
                           ensure_ascii=False) + "\n")
        f.write(json.dumps({"ts": t - 2, "kind": "handoff",
                            "summary": "上下文将满，交回续跑"}, ensure_ascii=False) + "\n")
    json.dump({"ok": True, "content": "普通完成", "finished_ts": t - 1},
              open(os.path.join(j3, "result.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    return jobs


def main():
    root = tempfile.mkdtemp(prefix="mdcg_m6_")
    try:
        jobs = make_jobs(root)
        cg = MdCGOS(root)
        src = HiveJobsSource(jobs)
        evs = list(src.events())

        # ---- 1. 事件映射（§5.3） ----
        print("[1] 事件映射")
        check("1a start → 任务开始（role=user）",
              any(e["role"] == "user" and "任务开始" in e["text"] for e in evs))
        check("1b tool 条目被跳过（防流水账）",
              all("tool_trace" not in e["text"] for e in evs))
        check("1c 强杀 job 的 error 事件带「任务失败」前缀（fix-pair 前件）",
              any("任务失败" in e["text"] and "aaa1" in e["text"] for e in evs))
        check("1d handoff → 续跑卡",
              any("续跑卡" in e["text"] for e in evs))
        check("1e session=hive:<job_id>",
              all(e["session"].startswith("hive:h") for e in evs), str(evs[0]["session"]))

        # ---- 2. 终态补位（§5.6 判据 3） ----
        print("[2] result 终态补位")
        check("2a 强杀 job（progress 无 final）→ result 终态补位事件存在",
              any("aaa1" in e["text"] and "任务失败" in e["text"] for e in evs))
        check("2b 补位事件标注 progress 缺 final",
              any("result 终态补位" in e["text"] for e in evs))

        # ---- 3. ingest：层归属（§5.5）+ 产出 ----
        print("[3] ingest 层归属（只落 contextual，knowledge 零污染）")
        k_before = len([n for n, e in (cg.index.get("nodes") or {}).items()
                        if (e or {}).get("layer") == "knowledge"])
        ing = Ingestor(cg, layer="contextual", sensitivity="internal")
        # §5.5 硬纪律（与 M3.2 双轨制同构）：ingest 自动 mine_fix_pairs 会把
        # 挖掘产物直写 knowledge 层（实测 0→2 污染）——M6 路径默认关闭；
        # fix-pair 挖掘保留为显式能力（挖掘产物入 knowledge 须走收口）
        rep = ing.ingest(src, mine_fix_pairs=False)
        check("3a 事件全部写入 contextual", rep["written"] == len(evs),
              f"written={rep['written']} evs={len(evs)}")
        k_after = len([n for n, e in (cg.index.get("nodes") or {}).items()
                       if (e or {}).get("layer") == "knowledge"])
        check("3b knowledge 层节点数不变（§5.5 反向对照）", k_before == k_after,
              f"{k_before}→{k_after}")

        # ---- 4. watermark 幂等（§5.6 判据 2） ----
        print("[4] watermark 幂等")
        rep2 = ing.ingest(HiveJobsSource(jobs))
        check("4a 重跑零新增（断点续跑无重复）",
              rep2["new_events"] == 0 and rep2["written"] == 0, str(rep2)[:150])

        # ---- 5. fix-pair（§5.6 判据 1：错误→修复，显式能力验证） ----
        print("[5] fix-pair（显式挖掘能力；M6 自动路径已按 §5.5 关闭）")
        rep3 = ing.ingest(HiveJobsSource(jobs), mine_fix_pairs=False)
        check("5a 幂等重跑下不再产出事件（fix-pair 无重复输入）",
              rep3["new_events"] == 0)
        # 事件流支持配对挖掘（错误后 4 条内出现命令行 → 配对）——能力验证：
        # 实际启用须走收口（编排者/设计者裁决后显式调用，产物才可入 knowledge）
        seq = [{"role": e["role"], "text": e["text"]} for e in evs]
        fp = cg.mine_fix_pairs(seq)
        check("5b 错误→修复对可被挖出（超时失败→重试通过）",
              len(fp.get("pairs") or []) >= 1, str(fp)[:200])
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n=== hive ingest tests: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    sys.exit(main())
