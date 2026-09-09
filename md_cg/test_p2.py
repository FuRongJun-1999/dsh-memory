# -*- coding: utf-8 -*-
"""md_cg · P2 记忆 OS 验收（7 项能力 + MCP 前置）

运行：python -m md_cg.test_p2
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

from .mdcos import MdCGOS, WORK_ROLES, est_tokens

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


CCG = ("# 功能名：{n}\n# 生效条件：{c}\n# 子功能：{s}\n# 执行：{e}\n"
       "# 验证方式：test\n# 不适用条件：{neg}\n\n{body}\n")


def mk(n, cond, body, neg="其它"):
    return CCG.format(n=n, c=cond, s=body[:20], e=body, neg=neg, body=body)


def main():
    root = tempfile.mkdtemp(prefix="mdcgos_")
    try:
        cg = MdCGOS(root, actor="test")

        # ---------------- 0. 观测时间（条件论「观测时间」栏） ----------------
        print("\n【0】观测时间（条件论）")
        cg.add("ts1", mk("无观测时间参数", "问观测", "调用方未提供 condition_space"))
        fm1 = cg.get("ts1")["frontmatter"]
        cs1 = fm1.get("condition_space") or {}
        tw1 = cs1.get("time_window")
        check("写入自动补 time_window", isinstance(tw1, list) and len(tw1) == 2, str(tw1))
        check("time_window 锚定写入时刻",
              bool(tw1) and abs(tw1[0] - fm1.get("created_at", 0)) < 1e-6,
              f"tw[0]={tw1[0] if tw1 else None} created_at={fm1.get('created_at')}")
        check("默认观测窗口为 1 小时", bool(tw1) and abs((tw1[1] - tw1[0]) - 3600) < 1e-6,
              f"跨度={tw1[1]-tw1[0] if tw1 else None}")

        cg.add("ts2", mk("显式观测时间", "问观测", "调用方给了 time_window"),
               condition_space={"observation_position": "测试", "time_window": [1000.0, 2000.0]})
        tw2 = (cg.get("ts2")["frontmatter"].get("condition_space") or {}).get("time_window")
        check("显式 time_window 被保留", tw2 == [1000.0, 2000.0], str(tw2))

        cg.add("ts3", mk("指定 created_at", "问观测", "回填历史时间"), created_at=1700000000.0)
        fm3 = cg.get("ts3")["frontmatter"]
        tw3 = (fm3.get("condition_space") or {}).get("time_window")
        check("created_at 回填时 time_window 同步锚定",
              bool(tw3) and abs(tw3[0] - 1700000000.0) < 1e-6, str(tw3))

        # ---------------- 2. role 分层索引 ----------------
        print("\n【2】role 分层索引")
        cg.add("k1", mk("红按钮移动", "问红按钮", "红按钮控制角色左移"), role="knowledge")
        cg.add("w1", mk("工具输出噪声", "问红按钮", "红按钮工具输出：左移成功"), role="tool-output")
        cg.add("w2", mk("命令记录", "问红按钮", "npm test 执行了红按钮测试"), role="command")
        r_default, _ = cg.search("红按钮", k=10)
        ids_default = {r[0]["id"] for r in r_default}
        r_work, _ = cg.search("红按钮", k=10, include_work=True)
        ids_work = {r[0]["id"] for r in r_work}
        check("默认检索剔除 work 角色", "w1" not in ids_default and "w2" not in ids_default,
              f"默认={sorted(ids_default)}")
        check("include_work=True 时可见 work 角色", "w1" in ids_work or "w2" in ids_work,
              f"含work={sorted(ids_work)}")
        r_roles, _ = cg.search("红按钮", k=10, roles=("tool-output",))
        check("按 roles 精确过滤", all(r[0]["id"].startswith("w") for r in r_roles) and r_roles,
              f"{[r[0]['id'] for r in r_roles]}")

        # ---------------- 3. RRF 并行多路召回 ----------------
        print("\n【3】RRF 并行多路召回")
        cg.add("k2", mk("蓝按钮开门", "问蓝按钮", "蓝按钮打开门"), role="knowledge",
               tags=["game"], condition_space={"关卡": 1})
        res, meta = cg.search_rrf("红按钮", k=5, context={"关卡": 1})
        check("search_rrf 返回结果", len(res) > 0, f"{len(res)} 条")
        check("meta 自报各路候选数", set(meta.get("paths", {})) >= {"lexical"},
              json.dumps(meta.get("paths"), ensure_ascii=False))
        check("结果带 provenance（可审计）", all(len(r) == 4 for r in res),
              f"元素长度={[len(r) for r in res]}")

        # ---------------- 7. budget-driven pack ----------------
        print("\n【7】budget-driven pack")
        big = mk("超长条目", "问超长", "超长内容" * 500)
        cg.add("big1", big, role="knowledge")
        small = mk("小条目", "问小条目", "小内容")
        cg.add("small1", small, role="knowledge")
        rec = cg.recall("超长 小内容", budget_tokens=200, k=10)
        check("recall 遵守 token 预算", rec["tokens_used"] <= rec["budget"],
              f"used={rec['tokens_used']}/{rec['budget']}")
        check("超大条目被跳过而非停下", any(s["id"] == "big1" for s in rec["skipped"]),
              f"skipped={[s['id'] for s in rec['skipped']]}")
        check("跳过超大后仍装入小条目", any(p["id"] == "small1" for p in rec["pack"]),
              f"pack={[p['id'] for p in rec['pack']]}")

        # ---------------- 1. Fix pairs 自动挖掘 ----------------
        print("\n【1】Fix pairs 自动挖掘")
        events = [
            {"role": "user", "text": "跑测试报错了"},
            {"role": "tool-output", "text": "Traceback (most recent call last):\n  File x, line 1\nModuleNotFoundError: No module named 'foo'"},
            {"role": "assistant", "text": "pip install foo"},
            {"role": "user", "text": "好了"},
        ]
        fp = cg.mine_fix_pairs(events)
        check("挖掘出错误→修复对", len(fp["pairs"]) >= 1, json.dumps(fp["pairs"], ensure_ascii=False)[:120])
        check("产出可路由修复知识", len(fp["knowledge_ids"]) >= 1, str(fp["knowledge_ids"]))
        check("产出负记忆（不必深挖根因）", len(fp["rejected_ids"]) >= 1, str(fp["rejected_ids"]))
        # 修复知识应可被检索命中
        r_fix, _ = cg.search("ModuleNotFoundError", k=5)
        check("修复知识可被检索命中", any("fix_" in r[0]["id"] for r in r_fix),
              f"{[r[0]['id'] for r in r_fix]}")
        # 幂等：重复挖掘不重复记录
        fp2 = cg.mine_fix_pairs(events)
        check("重复挖掘幂等（不重复建节点）",
              all(rid in fp["rejected_ids"] for rid in fp2["rejected_ids"]),
              f"第二次={fp2['rejected_ids']}")

        # ---------------- 4. 审核队列 edit/merge ----------------
        print("\n【4】审核队列 edit/merge")
        pid = cg.propose("p1", mk("候选知识", "问候选", "候选内容"), tags=["t1"])
        check("propose 进入 inbox", any(r["pid"] == pid for r in cg.review_list()),
              f"pending={len(cg.review_list())}")
        d1 = cg.review_decide(pid, "accept")
        check("accept 落库", d1.get("ok") and cg.get("p1") is not None, str(d1))
        check("已裁决项从 inbox 移除", not any(r["pid"] == pid for r in cg.review_list()))

        pid2 = cg.propose("p2", mk("待编辑", "问编辑", "旧内容"))
        d2 = cg.review_decide(pid2, "edit", edits={"content": mk("待编辑", "问编辑", "新内容")})
        check("edit 用修改后内容落库", d2.get("ok") and "新内容" in cg.get("p2")["content"], str(d2))

        pid3 = cg.propose("p3", mk("待合并", "问合并", "追加内容"))
        d3 = cg.review_decide(pid3, "merge", merge_into="k1")
        merged = cg.get("k1")
        check("merge 内容追加进目标节点", d3.get("ok") and "追加内容" in merged["content"],
              f"ok={d3.get('ok')}")

        pid4 = cg.propose("p4", mk("待拒绝", "问拒绝", "垃圾"))
        d4 = cg.review_decide(pid4, "reject")
        check("reject 不落节点", d4.get("ok") and cg.get("p4") is None, str(d4))
        check("decisions 日志有 4 条裁决", len(cg.decisions()) >= 4, str(len(cg.decisions())))

        # ---------------- 5. tombstone + 恢复检查 ----------------
        print("\n【5】tombstone + 恢复时删除检查")
        cg.add("t1", mk("待删除", "问删除", "将被软删"), role="knowledge")
        fg = cg.forget("t1", reason="测试删除")
        check("forget 软删除成功", fg.get("ok") and cg.get("t1") is None, str(fg))
        check("节点文件移入 trash/", os.path.exists(os.path.join(root, "trash", "t1.md")))
        check("删除清单记录墓碑", cg.is_tombstoned("t1"), str(cg.deletions()[-1:]))
        rs = cg.restore("t1")
        check("恢复被删除检查拦截", not rs.get("ok") and rs.get("error") == "tombstoned", str(rs))
        rs2 = cg.restore("t1", force=True)
        check("force=True 可恢复", rs2.get("ok") and cg.get("t1") is not None, str(rs2))

        # ---------------- 6. payload-free 审计 ----------------
        print("\n【6】payload-free 审计")
        audits = cg.audit_records()
        check("审计有记录", len(audits) > 0, f"{len(audits)} 条")
        leaked = []
        for a in audits:
            blob = json.dumps(a, ensure_ascii=False)
            if "红按钮控制角色左移" in blob or "超长内容" in blob:
                leaked.append(a.get("op"))
        check("审计不含内容（payload-free）", not leaked, f"泄漏={leaked}")
        check("审计含载荷哈希", all("payload_hash" in a or a.get("op") in
                                ("forget", "review_decide", "restore") for a in audits),
              f"样例={audits[0]}")

        # ---------------- OS 健康度 ----------------
        print("\n【8】OS 健康度")
        h = cg.health_os()
        check("health_os 报告 role 分布", "roles" in h.get("os", {}),
              json.dumps(h["os"].get("roles"), ensure_ascii=False))
        check("health_os 报告审核/墓碑/审计计数",
              all(k in h["os"] for k in ("review_pending", "tombstones", "audit_events")),
              json.dumps({k: h["os"][k] for k in ("review_pending", "tombstones", "audit_events")}))

        cg.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + ", ".join(FAILS))
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
