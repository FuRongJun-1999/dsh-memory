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
from .sources import HiveJobsSource, Ingestor, run as sources_run

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

        # ---- 6. MCP/CLI 暴露口（sources.run action=hive）+ 事件级密级（双态） ----
        print("[6] 暴露口 sources.run(action=hive) + error 事件 private（双态）")
        root2 = tempfile.mkdtemp(prefix="mdcg_m6b_")
        try:
            jobs2 = make_jobs(root2)
            # 6a-6c：高 clearance（secret）调用方 → error 事件正常落 private
            from .mdcos import MdCGSecure
            from .security import Principal
            cg_sec = MdCGSecure(root2, principal=Principal(
                actor="t_secret", clearance="secret", can_write=True,
                role="designer", auth_mode="test"))
            rep_h = sources_run(cg_sec, action="hive", path=jobs2)
            check("6a run(action=hive) 摄取成功（统一暴露口）",
                  rep_h.get("written", 0) > 0 and rep_h.get("source", "").startswith(
                      "hive_jobs:"), str(rep_h)[:150])
            priv = inter = 0
            for nid, e in (cg_sec.index.get("nodes") or {}).items():
                if not str(nid).startswith("src_"):
                    continue
                fm = e or {}
                if fm.get("sensitivity") == "private":
                    priv += 1
                elif fm.get("layer") == "contextual":
                    inter += 1
            check("6b error 事件节点=private（secret clearance 落盘成功）",
                  priv >= 2, f"private={priv}")
            check("6c 非 error 事件保持 internal",
                  inter >= 3, f"internal={inter}")
            # 6d-6e：internal clearance 调用方 → private 写入 AccessDenied，
            # denied 明细可见（不静默丢失，误差归因原料可查可重放）
            cg_int = MdCGSecure(tempfile.mkdtemp(prefix="mdcg_m6c_"))
            rep_i = sources_run(cg_int, action="hive", path=jobs2)
            check("6d internal clearance 写 private 被拒且明细可见",
                  rep_i.get("denied", 0) >= 2
                  and len(rep_i.get("denied_events") or []) == rep_i["denied"],
                  str(rep_i.get("denied_events"))[:160])
            # 6f：显式降级 error_sensitivity=internal → 全部落盘（显式权衡）
            cg_low = MdCGSecure(tempfile.mkdtemp(prefix="mdcg_m6d_"))
            rep_l = sources_run(cg_low, action="hive", path=jobs2,
                                error_sensitivity="internal")
            check("6f 显式降级 error_sensitivity=internal 全部落盘",
                  rep_l.get("denied", 0) == 0 and rep_l.get("written", 0) > 0,
                  str({k: rep_l.get(k) for k in ("written", "denied")}))
            # fail-closed：无 path 无 env → 人话指引
            os.environ.pop("MDCG_HIVE_JOBS", None)
            rep_nc = sources_run(cg_low, action="hive")
            check("6g 无 root 时 fail-closed 人话指引（不猜布局）",
                  rep_nc.get("ok") is False and "MDCG_HIVE_JOBS" in rep_nc["error"])
            # dry_run：只统计不写盘
            rep_d = sources_run(cg_low, action="hive", path=jobs2, dry_run=True)
            check("6h dry_run 预演不写盘",
                  rep_d.get("dry_run") is True and rep_d.get("written", 1) == 0)
        finally:
            shutil.rmtree(root2, ignore_errors=True)

        # ---- 7. §5.5 系统纪律化（zcode 外评 break#2/P1）：默认不挖矿 + 产物入队 ----
        print("[7] mine_fix_pairs 默认翻转 + 自动产物走 propose 队列")
        root3 = tempfile.mkdtemp(prefix="mdcg_m7_")
        try:
            # 造一个含「错误→修复」对的 jsonl 会话文件
            jl = os.path.join(root3, "sess.jsonl")
            with open(jl, "w", encoding="utf-8") as f:
                f.write(json.dumps({"role": "assistant",
                                    "text": "执行失败：ModuleNotFoundError: no x"}) + "\n")
                # 修复行必须是行首命令（_FIX_RE 行首启发式）
                f.write(json.dumps({"role": "assistant",
                                    "text": "执行修复：\npip install x"}) + "\n")
            cg3 = MdCGOS(root3)
            kn_before = sum(1 for e in (cg3.index.get("nodes") or {}).values()
                            if (e or {}).get("layer") == "knowledge")
            # 7a：不传 mine_fix_pairs（吃新默认 False）→ 不挖矿
            rep_a = sources_run(cg3, action="jsonl", path=jl)
            check("7a 默认不挖矿（file/jsonl 不再直写知识层——旧行为即红）",
                  "fix_pairs" not in rep_a, str(rep_a.get("fix_pairs"))[:120])
            kn_after = sum(1 for e in (cg3.index.get("nodes") or {}).values()
                           if (e or {}).get("layer") == "knowledge")
            check("7b 默认路径 knowledge 层零新增（污染反向对照）",
                  kn_after == kn_before, f"{kn_before} -> {kn_after}")
            # 7c：显式开启 → 自动产物走 propose 队列（不直写）
            from .sources import JsonlSource
            rep_c = Ingestor(cg3).ingest(JsonlSource(jl), mine_fix_pairs=True,
                                         dry_run=True)
            # dry_run 不挖矿；改真实写（换新 root 避免水位吃掉事件）
            cg4 = MdCGOS(tempfile.mkdtemp(prefix="mdcg_m7b_"))
            rep_c = Ingestor(cg4).ingest(JsonlSource(jl), mine_fix_pairs=True)
            fp = rep_c.get("fix_pairs") or {}
            check("7c 显式开启时自动产物走提案（as_proposals=True，pids 非空）",
                  fp.get("as_proposals") is True and len(fp.get("pids") or []) >= 1
                  and not fp.get("knowledge_ids"), str(fp)[:160])
            kn_c = sum(1 for e in (cg4.index.get("nodes") or {}).values()
                       if (e or {}).get("layer") == "knowledge")
            check("7d 提案模式下 knowledge 层仍零新增（收口前不入层）",
                  kn_c == 0, f"knowledge={kn_c}")
            check("7e 提案入审核队列（review_list 可见）",
                  len(cg4.review_list() or []) >= 1,
                  str(cg4.review_list())[:120])
            # 7f：显式工具语义直调（不带 as_proposals）→ 保持直写
            r_tools = cg4.mine_fix_pairs([
                {"error": "ModuleNotFoundError: no y", "fix": "pip install y"}])
            check("7f 显式调用保持直写（knowledge_ids 非空）",
                  len(r_tools.get("knowledge_ids") or []) == 1, str(r_tools)[:120])
            # 7g：payload_hash 幂等——同内容再入队返回原 pid
            r2 = cg4.mine_fix_pairs([
                {"error": "ModuleNotFoundError: no x", "fix": "pip install x"}],
                as_proposals=True)
            r3 = cg4.mine_fix_pairs([
                {"error": "ModuleNotFoundError: no x", "fix": "pip install x"}],
                as_proposals=True)
            check("7g 同内容重试幂等（返回原 pid 不重复入队）",
                  r2["pids"] == r3["pids"] and len(r2["pids"]) >= 1,
                  f"{r2['pids']} vs {r3['pids']}")
        finally:
            shutil.rmtree(root3, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n=== hive ingest tests: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    sys.exit(main())
