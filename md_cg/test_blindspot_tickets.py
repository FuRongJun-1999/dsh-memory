# -*- coding: utf-8 -*-
"""盲区消解票据（blindspot_tickets.make_tickets）验证。

断言面：
  ① 空库诚实：无反思记录 → 零票据、零落库（不编造消解价值）
  ② 预演：apply=False 全 dry_run、零落库
  ③ 四类分类：task（query 精确命中 unresolved 首行，优先级最高）/
     grilling（defer 主导）/ research（blindspot>=3）/ prototype（其余）
  ④ apply 落卡：tasks.list_tasks 可见、tags 带 ticket:<type>
  ⑤ 幂等：重复 apply → created=0、updated=4（不重复建卡）
  ⑥ types 仅作分类后落卡过滤（判据恒定不变）
  ⑦ 非法 types → ok=False、零落库
  ⑧ grilling 卡如实声明「执行通道=宿主侧访谈」（库内无访谈工具，不越权代答）
  ⑨ task 卡正文携带关联 unresolved node_id
  ⑩ min_blindspot 候选资格过滤（b 低且无 defer 的簇不入池）

运行：python -m md_cg.test_blindspot_tickets
"""
from __future__ import annotations

import os
import tempfile

from . import blindspot_tickets, tasks
from .fsutil import append_jsonl
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def _sig(cg, t, query, states):
    """直写一条反思记录（与 test_autonomy 同构先例：只造信号面，不动检索面）。"""
    append_jsonl(cg.reflection_log,
                 {"t": t, "query": query, "d_prev": 1.0, "d_curr": 1.0,
                  "d_delta": 0.0, "d2": 0.1, "states": states,
                  "n_results": 1, "feedback": None})


def _card(cg, ttype, q):
    nid = tasks.TASK_PREFIX + tasks.slugify("票据:%s:%s" % (ttype, q[:24]))
    node = cg.get(nid) or {}
    return node, nid


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_tickets_")
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root, exist_ok=True)
        cg = MdCGOS(root)

        Q_R = "如何审计蜂巢的 gossip 收敛性"   # blindspot×3 → research
        Q_G = "上次说的那个修复方案细节"       # defer×2     → grilling
        Q_P = "数据迁移的回滚口径"             # blindspot×1 → prototype
        Q_T = "跨库事务一致性边界"             # blindspot×1 + unresolved 首行命中 → task

        # ---------- ① 空库诚实 ----------
        r0 = blindspot_tickets.make_tickets(cg)
        ok(r0["ok"] and r0["scanned"] == 0 and r0["created"] == 0
           and not r0["tickets"],
           "①空反思日志 → 零票据（不编造消解价值）")
        r0a = blindspot_tickets.make_tickets(cg, apply=True)
        ok(r0a["ok"] and r0a["created"] == 0 and len(tasks.list_tasks(cg)["tasks"]) == 0,
           "①b空库 apply → 零落卡")

        # ---------- ② 造四类信号（t 递增：task/prototype 同 b，last_t 定序） ----------
        t = 1.0
        for i in range(3):
            t += 1
            _sig(cg, t, Q_R, {"BLINDSPOT": 1})
        for i in range(2):
            t += 1
            _sig(cg, t, Q_G, {"DEFER": 1})
        _sig(cg, 10.0, Q_P, {"BLINDSPOT": 1})
        _sig(cg, 11.0, Q_T, {"BLINDSPOT": 1})
        cg.add("t_unres", Q_T + "\n悬挂：等待架构裁决", layer="unresolved")

        # ---------- ③ 预演 ----------
        dry = blindspot_tickets.make_tickets(cg)
        ok(dry["ok"] and dry["scanned"] == 4 and dry["applied"] is False,
           "③四簇入池、预演不落库")
        by_q = {tk["query"]: tk for tk in dry["tickets"]}
        ok(all(tk.get("dry_run") for tk in dry["tickets"]),
           "③b预演票据全 dry_run 标记")
        ok(len(tasks.list_tasks(cg)["tasks"]) == 0,
           "③c预演零落库")
        ok(by_q[Q_T]["type"] == "task" and by_q[Q_R]["type"] == "research"
           and by_q[Q_G]["type"] == "grilling" and by_q[Q_P]["type"] == "prototype",
           "③d四类分类各就位（task 判据优先于 b/d 计数）")

        # ---------- ④ apply 落卡 ----------
        r1 = blindspot_tickets.make_tickets(cg, apply=True, actor="test")
        ok(r1["ok"] and r1["created"] == 4 and r1["errors"] == 0,
           "④apply 建 4 卡、零错误")
        lt = tasks.list_tasks(cg, status="active")
        ok(len(lt["tasks"]) == 4, "④b任务清单可见 4 张 active 卡")
        tags_ok = True
        for ttype, q in (("research", Q_R), ("grilling", Q_G),
                         ("prototype", Q_P), ("task", Q_T)):
            node_i, _ = _card(cg, ttype, q)
            fm_i = (node_i or {}).get("frontmatter") or {}
            if "ticket:%s" % ttype not in (fm_i.get("tags") or []):
                tags_ok = False
        ok(tags_ok, "④c四卡 fm tags 带 ticket:<type> 族标")
        # 分类落卡实体抽查
        node_r, _ = _card(cg, "research", Q_R)
        ok(node_r and "ticket:research" in (node_r["frontmatter"].get("tags") or []),
           "④dresearch 卡以 ticket:research 落库")

        # ---------- ⑤ 幂等 ----------
        r2 = blindspot_tickets.make_tickets(cg, apply=True)
        ok(r2["ok"] and r2["created"] == 0 and r2["updated"] == 4,
           "⑤重复 apply → created=0、updated=4（同 slug 不重复建卡）")
        ok(len(tasks.list_tasks(cg)["tasks"]) == 4, "⑤b卡数不增")

        # ---------- ⑥ types 过滤（仅过滤，不改判据） ----------
        r3 = blindspot_tickets.make_tickets(cg, types=["research"], apply=True)
        tk3 = {tk["query"]: tk for tk in r3["tickets"]}
        ok(r3["ok"] and tk3[Q_R].get("node_id") and tk3[Q_G].get("skipped")
           and tk3[Q_T].get("skipped") and tk3[Q_P].get("skipped"),
           "⑥types=research → 其余三类 skipped（判据未被 types 改写）")
        ok(tk3[Q_R].get("created") is False,
           "⑥bresearch 卡幂等更新（created=False，重复过滤轮不重复建）")

        # ---------- ⑦ 非法 types ----------
        r4 = blindspot_tickets.make_tickets(cg, types=["nope"], apply=True)
        ok(r4["ok"] is False and "nope" in r4["error"]
           and len(tasks.list_tasks(cg)["tasks"]) == 4,
           "⑦非法类型 → ok=False 点名可选集、零落库")

        # ---------- ⑧⑨ 卡正文边界与关联 ----------
        node_g, _ = _card(cg, "grilling", Q_G)
        plan_g = node_g["content"] if node_g else ""
        ok(node_g and "宿主侧访谈" in plan_g and "不越权代答" in plan_g,
           "⑧grilling 卡如实声明执行通道=宿主侧访谈")
        node_t, _ = _card(cg, "task", Q_T)
        plan_t = node_t["content"] if node_t else ""
        ok(node_t and "t_unres" in plan_t and "关联悬挂" in plan_t,
           "⑨task 卡携带关联 unresolved node_id")

        # ---------- ⑩ min_blindspot 资格过滤 ----------
        r5 = blindspot_tickets.make_tickets(cg, min_blindspot=3)
        qs5 = {tk["query"] for tk in r5["tickets"] if not tk.get("skipped")}
        ok(Q_R in qs5 and Q_G in qs5 and Q_P not in qs5 and Q_T not in qs5,
           "⑩min_blindspot=3 → 仅 research(b=3) 与 grilling(d≥1) 入池")

        print("[test_blindspot_tickets] PASS=%d FAIL=%d" % (PASS, FAIL))
        if FAILS:
            raise SystemExit(1)
    finally:
        pass


if __name__ == "__main__":
    main()
