# -*- coding: utf-8 -*-
"""md_cg · 第 5 篇七件套补齐验收：目标槽 + 近期事件 + 证据计数/降级

覆盖（白箱智能系列·第五篇）：
  A 目标槽（第 3 章）：写入 / 排序 / 状态机 / 不进正排
  B 目标定向路（第 3 章）：goal 路召回、显式启用、可审计 goal_used
  C 近期事件滚动窗口（第 3 章）：最新在前 / 角色过滤 / 滚动截断 / recall 附带
  D 证据计数 + 可信度降级（第 4 章）：evidence_count、正反例分离、跌破阈值降级
  E MCP 接口面：cg(op=goal) / cg(op=recent) / mdcg_recall(goal, include_recent)
  F 健康度覆盖：health_os 报告 goals / recent_events

运行：python -m md_cg.test_p7_goals_recent
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

from .mdcos import MdCGOS
from .mcp_server import call_tool

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def ccg(title, cond="任意情境", sub="验收", exe="直接调用", verify="test", body=""):
    return (f"# 功能名：{title}\n"
            f"# 生效条件：{cond}\n"
            f"# 子功能：{sub}\n"
            f"# 执行：{exe}\n"
            f"# 验证方式：{verify}\n"
            f"# 不适用条件：无\n"
            f"{body or title}\n")


def main():
    root = tempfile.mkdtemp(prefix="mdcg_p7_")
    cg = MdCGOS(root)
    try:
        # ---------- A. 目标槽 ----------
        print("\n[A] 目标槽（第 5 篇第 3 章「目标」）")
        g1 = cg.add_goal("修复登录超时", priority=0.9, deadline="2026-10-01")
        g2 = cg.add_goal("降低内存占用", priority=0.2)
        check("add_goal 落 goals 层",
              (cg.get(g1) or {}).get("frontmatter", {}).get("layer") == "goals", g1)
        check("目标文本可读回",
              (cg.get(g1) or {}).get("frontmatter", {}).get("goal_text") == "修复登录超时")
        check("add_goal 幂等（同文本同 id）", cg.add_goal("修复登录超时", priority=0.9) == g1)
        act = cg.active_goals()
        check("active_goals 按优先级排序",
              [g["id"] for g in act] == [g1, g2], str([g["goal"] for g in act]))
        check("goal_text 拼接活跃目标",
              cg.goal_text() == "修复登录超时 降低内存占用", cg.goal_text())
        cg.set_goal_status(g2, "done")
        check("done 目标退出 active", [g["id"] for g in cg.active_goals()] == [g1])
        check("list_goals 仍可见 done 目标",
              {g["id"] for g in cg.list_goals()} == {g1, g2})
        res, _m = cg.search("修复登录超时", k=20)
        check("目标节点不参与正排（只是方向）",
              g1 not in [n["id"] for n, _s, _q in res])

        # ---------- B. 目标定向路 ----------
        print("\n[B] 目标定向路（goal 路，显式启用）")
        for g in cg.list_goals(status="active"):      # 先清空活跃目标
            cg.set_goal_status(g["id"], "done")
        a = cg.add("n_login", ccg("登录会话超时处理", cond="登录态",
                                 body="登录 超时 session token 过期"),
                   tags=["login"], verification_basis="test")
        b = cg.add("n_memory", ccg("内存泄漏排查", cond="长时间运行",
                                  body="内存 泄漏 gc 回收"),
                   tags=["memory"], verification_basis="test")
        # 单独启用 goal 路，隔离 lexical 等路的影响
        _r0, m0 = cg.search_rrf("问题", k=10, paths=("goal",), record=False)
        check("无活跃目标时 goal 路为空", not m0.get("goal_used") and not _r0,
              f"goal_used={m0.get('goal_used')!r} n={len(_r0)}")
        r1, m1 = cg.search_rrf("问题", k=10, paths=("goal",),
                               record=False, goal_text="登录 超时")
        ids = [n["id"] for n, _s, _q, _p in r1]
        check("有目标时 goal 路召回目标相关记忆", a in ids, str(ids))
        check("goal 路不混入与目标无关的记忆", b not in ids, str(ids))
        check("meta 暴露 goal_used（可审计）", m1.get("goal_used") == "登录 超时")
        base, _mb = cg.search_rrf("问题", k=10, paths=("lexical",), record=False)
        same, _ms = cg.search_rrf("问题", k=10, paths=("lexical",), record=False,
                                  goal_text="登录 超时")
        check("未启用 goal 路时目标不生效（既有基线不变）",
              [n["id"] for n, *_ in base] == [n["id"] for n, *_ in same])

        # ---------- C. 近期事件滚动窗口 ----------
        print("\n[C] 近期事件滚动窗口（第 5 篇第 3 章「近期事件」）")
        cg.clear_recent()
        cg.remember_event("user", "开始重构登录模块")
        cg.remember_event("assistant", "已定位到 token 过期逻辑")
        cg.remember_event("command", "pytest -k login")
        ev = cg.recent_events(limit=10)
        check("近期事件最新在前", ev[0]["text"] == "pytest -k login", ev[0]["text"])
        check("近期事件按角色过滤",
              [e["text"] for e in cg.recent_events(roles=("user",))] == ["开始重构登录模块"])
        for i in range(6):
            cg.remember_event("user", f"事件{i}", window=3)
        ev2 = cg.recent_events(limit=10)
        check("滚动窗口截断到最近 N 条", len(ev2) == 3, f"n={len(ev2)}")
        check("窗口保留最新事件", ev2[0]["text"] == "事件5", ev2[0]["text"])
        p_no = cg.recall("登录超时", budget_tokens=400, include_recent=False)
        p_yes = cg.recall("登录超时", budget_tokens=400,
                          include_recent=True, recent_limit=3)
        check("recall 默认不带近期事件", p_no.get("recent") == [])
        check("recall(include_recent=True) 附带近期事件",
              len(p_yes.get("recent") or []) == 3, str(len(p_yes.get("recent") or [])))
        check("近期事件计入 token 预算（诚实口径）",
              p_yes["tokens_used"] > p_no["tokens_used"],
              f"{p_no['tokens_used']} → {p_yes['tokens_used']}")

        # ---------- D. 证据计数 + 可信度降级 ----------
        print("\n[D] 证据计数 + 可信度降级（第 5 篇第 4 章）")
        n = cg.add("n_ev", ccg("临时缓存策略", cond="高并发",
                               body="缓存 过期 时间 30s"),
                   verification_basis="test", confidence=0.6)
        r = cg.verify(n, "压测命中率 92%", "confirmed")
        check("confirmed 累加 evidence_count", r["evidence_count"] == 1, str(r))
        fm = cg.get(n)["frontmatter"]
        check("正例计数", fm["positive_evidence"] == 1 and fm["negative_evidence"] == 0,
              f"pos={fm['positive_evidence']} neg={fm['negative_evidence']}")
        r = cg.verify(n, "压测命中率降至 71%", "weakened")
        fm = cg.get(n)["frontmatter"]
        check("weakened 累加 evidence_count", r["evidence_count"] == 2)
        check("反例计数", fm["negative_evidence"] == 1)
        check("反例权重 > 正例（0.6 +0.05 -0.15 = 0.5）",
              abs(fm["confidence"] - 0.5) < 1e-9, str(fm["confidence"]))
        demoted = None
        for i in range(3):
            r = cg.verify(n, f"继续走弱 {i}", "weakened")
            demoted = r.get("demoted") or demoted
        fm = cg.get(n)["frontmatter"]
        check("跌破阈值后降级为 contextual", fm["layer"] == "contextual",
              str(fm.get("layer")))
        check("降级留 demotion 审计",
              bool(fm.get("demotion")) and fm["demotion"]["from"] == "knowledge",
              str(fm.get("demotion")))
        check("降级后文件搬离 knowledge/",
              not os.path.exists(os.path.join(root, "knowledge", f"{n}.md")))
        check("索引层同步更新", cg.index["nodes"][n]["layer"] == "contextual")

        # ---------- E. MCP 接口面 ----------
        print("\n[E] MCP 接口面（cg op=goal / op=recent + mdcg_recall）")
        out = call_tool(cg, "cg", {"op": "goal", "action": "add",
                                   "goal": "优化检索延迟", "priority": 0.8})
        check("cg(op=goal,action=add) 可用", out.get("ok") and out.get("id"), str(out))
        out = call_tool(cg, "cg", {"op": "goal", "action": "list"})
        check("cg(op=goal,action=list) 返回目标",
              any(g["goal"] == "优化检索延迟" for g in out.get("goals", [])),
              str(out)[:120])
        out = call_tool(cg, "cg", {"op": "recent", "action": "add",
                                   "role": "user", "text": "MCP 追加的事件"})
        check("cg(op=recent,action=add) 可用",
              out.get("event", {}).get("text") == "MCP 追加的事件", str(out)[:120])
        out = call_tool(cg, "cg", {"op": "recent", "action": "list", "limit": 1})
        check("cg(op=recent,action=list) 返回事件",
              (out.get("events") or [{}])[0].get("text") == "MCP 追加的事件",
              str(out)[:120])
        out = call_tool(cg, "mdcg_recall",
                        {"query": "登录超时", "budget_tokens": 400,
                         "goal": "登录 超时", "include_recent": True})
        check("mdcg_recall 支持 goal + include_recent",
              out.get("meta", {}).get("goal_used") == "登录 超时" and out.get("recent"),
              f"goal_used={out.get('meta', {}).get('goal_used')!r} "
              f"recent={len(out.get('recent') or [])}")

        # ---------- F. 健康度覆盖 ----------
        print("\n[F] 健康度覆盖")
        h = cg.health_os()
        check("health_os 报告 goals", h["os"]["goals"]["total"] >= 3,
              str(h["os"]["goals"]))
        check("health_os 报告 recent_events", h["os"]["recent_events"] >= 1,
              str(h["os"]["recent_events"]))
    finally:
        try:
            cg.close()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n=== PASS {PASS} / FAIL {FAIL} ===")
    if FAILS:
        print("失败项：" + ", ".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
