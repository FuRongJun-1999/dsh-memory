# -*- coding: utf-8 -*-
"""记忆维护 + 离线固化（P30 · P1 工程缺口验收）。

对照 docs §五：P1 新增 maintain / consolidate 两 op。验收覆盖：
  ① op 契约链：ALL_OPS == 工具 schema，且按 op / action 分级授权
  ② maintain.stat/history：只读盘点，不需管理权限
  ③ maintain.importance：dry-run 报表 → apply → 留痕 → rollback 复原
  ④ maintain.longterm：dry-run → 断面落盘 → 幂等 → list/show
  ⑤ maintain.prefeed：预演不写 → write 时 ACCEPT 新增 / MERGE 并入不新增
  ⑥ maintain.separate：相似而条件不同 → 候选 → apply 写对称边 → 幂等
  ⑦ consolidate.promote：dry-run 分流 → 迁移 → 追溯 → 回滚
  ⑧ 权限分档：写层可 stat/prefeed、不可 importance/separate/rollback
  ⑨ 未知 action 不静默成功

批量改写均可预演 / 可留痕 / 可回滚；独立临时根，重跑 ≡ 首跑。

运行：python -m md_cg.test_p30_maintain
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

from . import consistency, corpus, forgetting, subgraph, tokens, weights
from .mdcos import MdCGOS
from .mcp_server import KERNEL_TOOLS, call_tool
from .security import AccessDenied, Principal

PASS = FAIL = 0
FAILS = []

SEP_A = ("# 功能名：连接池选择\n# 生效条件：单机离线环境\n"
         "# 子功能：在无外部依赖时选本地池\n# 执行：读配置选 local 建池\n"
         "# 不适用条件：无缓存场景\n")
SEP_B = ("# 功能名：连接池选择\n# 生效条件：多租户在线服务\n"
         "# 子功能：在无外部依赖时选本地池\n# 执行：读配置选 local 建池\n"
         "# 不适用条件：嵌入式设备\n")
PROMO_HOT = ("# 功能名：重试退避策略\n# 生效条件：网络抖动且请求幂等\n"
             "# 子功能：在瞬时故障下限制重试次数\n# 执行：指数退避重试至多三次\n"
             "# 不适用条件：非幂等写操作\n")
PROMO_COLD = ("# 功能名：日志轮转策略\n# 生效条件：磁盘占用超过阈值\n"
              "# 子功能：按大小切分历史日志\n# 执行：达到上限即滚动归档\n"
              "# 不适用条件：只读挂载卷\n")
# 反复命中但四要素不全（缺「不适用条件」）
PROMO_BAD = ("# 功能名：缓存穿透保护\n# 生效条件：高频查询未命中\n"
             "# 子功能：用空值占位挡住穿透\n# 执行：写空对象并设短 TTL\n")
NOVEL = ("# 观察：本机固定使用 Windows 与 cmd\n# 生效条件：本机开发环境\n"
         "# 执行：命令示例一律给 cmd 语法\n# 不适用条件：容器内构建\n"
         "用户多次强调命令行需适配 cmd.exe 而非 bash 语法。\n")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _principal(role):
    s = tokens.role_spec(role)
    return Principal(tenant="default", actor=role, clearance="internal",
                     can_write=bool(s["can_write"]), can_admin=bool(s["can_admin"]),
                     role=role, layers_allow=s["layers_allow"],
                     ops_allow=s["ops_allow"])


def _denied(fn):
    try:
        fn()
        return False
    except AccessDenied:
        return True


def main():
    print("=" * 68)
    print("md 认知图 P30 验收 · 记忆维护 / 离线固化（P1）")
    print("=" * 68)
    tmp = tempfile.mkdtemp(prefix="mdcg_p30_")
    ROOT = os.path.join(tmp, "root")
    corpus.reset_root(ROOT)
    cg = MdCGOS(ROOT, actor="p30")
    cg.principal = Principal(tenant="default", actor="p30", clearance="internal",
                             can_write=True, can_admin=True, role="designer")
    try:
        # ---------------------------------------------- ① 契约链
        print("\n【1】op 契约链与分级授权")
        tool = next(t for t in KERNEL_TOOLS if t["name"] == "cg")
        declared = set(tool["inputSchema"]["properties"]["op"]["description"].split("|"))
        check("工具 op 枚举 == ALL_OPS（防漏改）", declared == set(tokens.ALL_OPS),
              f"diff={sorted(declared ^ set(tokens.ALL_OPS))}")
        check("maintain/consolidate 已进 ALL_OPS",
              {"maintain", "consolidate"} <= set(tokens.ALL_OPS))
        check("写层三单元获 maintain 授权",
              all("maintain" in tokens.role_spec(r)["ops_allow"]
                  for r in ("record", "reflect", "sustain")))
        check("verify/output 未获 maintain",
              all("maintain" not in tokens.role_spec(r)["ops_allow"]
                  for r in ("verify", "output")))
        check("consolidate 为 designer 专属",
              all("consolidate" not in tokens.role_spec(r)["ops_allow"]
                  for r in ("record", "reflect", "verify", "output", "sustain")))
        check("MAINTAIN_ACTIONS 覆盖 P1 五项",
              {"importance", "longterm", "prefeed", "separate", "stat"}
              <= set(cg.MAINTAIN_ACTIONS), str(cg.MAINTAIN_ACTIONS))

        # ---------------------------------------------- ② stat / history
        print("\n【2】maintain.stat / history（只读）")
        st = call_tool(cg, "cg", {"op": "maintain", "action": "stat"})
        check("stat 返回盘点字段", st.get("ok") and "by_layer" in st
              and "importance" in st, str(st)[:100])
        keep = cg.principal
        cg.principal = _principal("record")
        check("stat 对写层角色放行（只读）",
              not _denied(lambda: call_tool(cg, "cg",
                                            {"op": "maintain", "action": "stat"})))
        cg.principal = keep
        hi = call_tool(cg, "cg", {"op": "maintain", "action": "history"})
        check("history 返回记录列表",
              hi.get("ok") and isinstance(hi.get("records"), list))

        # ---------------------------------------------- ③ importance + 回滚
        print("\n【3】maintain.importance：预演 → 改写 → 留痕 → 回滚")
        cg.add("w_fp", "# 功能名：形式化证明\n# 生效条件：任意\n# 子功能：可证\n"
                       "# 执行：证\n# 不适用条件：无\n", layer="knowledge",
               verification_basis="formal_proof", importance=0.5)
        cg.add("w_no", "# 功能名：无基底经验\n# 生效条件：任意\n# 子功能：经验\n"
                       "# 执行：试\n# 不适用条件：无\n", layer="knowledge",
               importance=0.5)
        cg.flush()
        i1 = call_tool(cg, "cg", {"op": "maintain", "action": "importance"})
        check("默认 dry-run 不改写", i1.get("dry_run") and i1.get("written") == 0,
              f"changed={i1.get('changed')}")
        check("报表识别变动节点", i1.get("changed", 0) >= 1)
        check("报表含分量（可审计）",
              bool(i1.get("samples")) and "basis_trust" in
              (i1["samples"][0].get("components") or {}))
        i2 = call_tool(cg, "cg", {"op": "maintain", "action": "importance",
                                  "apply": True})
        check("apply 改写节点", i2.get("written", 0) >= 1, f"written={i2.get('written')}")
        check("写入留痕 _maintain.jsonl", len(weights.history(cg, action="importance")) >= 1)
        check("改写已落盘面",
              abs(float(cg.get("w_fp")["frontmatter"]["importance"]) - 0.5) > 0.01)
        rb = call_tool(cg, "cg", {"op": "maintain", "action": "rollback"})
        check("rollback 反向应用", rb.get("ok") and rb.get("reverted", 0) >= 1,
              str(rb)[:100])
        cg.rebuild_index()
        check("rollback 复原为 0.5",
              abs(float(cg.get("w_fp")["frontmatter"]["importance"]) - 0.5) < 1e-9)

        # ---------------------------------------------- ④ longterm
        print("\n【4】maintain.longterm：预演 → 断面 → 幂等 → list/show")
        l1 = call_tool(cg, "cg", {"op": "maintain", "action": "longterm"})
        check("dry-run 未写盘", l1.get("dry_run") and l1.get("written") == 0)
        check("报表含分层与孤岛", "tiers" in l1 and "islands" in l1)
        l2 = call_tool(cg, "cg", {"op": "maintain", "action": "longterm",
                                  "apply": True})
        check("apply 写出断面",
              l2.get("written", 0) >= 1 and l2.get("same_as_current") is False,
              f"written={l2.get('written')}")
        check("断面文件落盘", os.path.exists(os.path.join(ROOT, l2.get("path") or "")))
        l3 = call_tool(cg, "cg", {"op": "maintain", "action": "longterm",
                                  "apply": True})
        check("幂等：内容相同跳过重写",
              l3.get("same_as_current") and l3.get("written") == 0)
        l4 = call_tool(cg, "cg", {"op": "maintain", "action": "longterm",
                                  "mode": "list"})
        check("list 返回 current 与历史",
              l4.get("current") and bool(l4.get("snapshots")))
        l5 = call_tool(cg, "cg", {"op": "maintain", "action": "longterm",
                                  "mode": "show"})
        check("show 聚合断面总数", l5.get("ok") and l5.get("total") == l2.get("total"),
              f"total={l5.get('total')}")

        # ---------------------------------------------- ⑤ prefeed
        print("\n【5】maintain.prefeed：预演 → ACCEPT 新增 → MERGE 不新增")
        p0 = call_tool(cg, "cg", {"op": "maintain", "action": "prefeed",
                                  "content": NOVEL, "layer": "contextual"})
        check("默认只预演未写盘",
              p0.get("written") is None and p0.get("decision") is not None,
              f"verdict={p0.get('verdict')}")
        n0 = len(cg.index["nodes"])
        p1 = call_tool(cg, "cg", {"op": "maintain", "action": "prefeed",
                                  "content": NOVEL, "layer": "contextual",
                                  "write": True})
        check("ACCEPT 落库新增",
              p1.get("decision") == "write" and bool(p1.get("written")),
              f"decision={p1.get('decision')}")
        n1 = len(cg.index["nodes"])
        check("写入后节点 +1", n1 == n0 + 1, f"{n0} → {n1}")
        p2 = call_tool(cg, "cg", {"op": "maintain", "action": "prefeed",
                                  "content": NOVEL, "layer": "contextual",
                                  "write": True})
        check("重复内容判 MERGE 并入",
              p2.get("decision") == "reinforce" and bool(p2.get("reinforced")),
              f"decision={p2.get('decision')}")
        check("MERGE 后节点数不变", len(cg.index["nodes"]) == n1)

        # ---------------------------------------------- ⑥ separate
        print("\n【6】maintain.separate：候选 → 对称边 → 幂等")
        cg.add("sep_a", SEP_A, layer="contextual", importance=0.4)
        cg.add("sep_b", SEP_B, layer="contextual", importance=0.4)
        cg.flush()
        s1 = call_tool(cg, "cg", {"op": "maintain", "action": "separate",
                                  "layer": "contextual", "min_jaccard": 0.4})
        pairs = {(c["a"], c["b"]) for c in (s1.get("candidates") or [])}
        check("dry-run 给出候选且未写盘",
              s1.get("dry_run") and ("sep_a", "sep_b") in pairs, f"{sorted(pairs)}")
        check("候选条件重合度低",
              bool(s1.get("candidates")) and all(
                  c["cond_overlap"] <= subgraph.SEP_MAX_COND_OVERLAP
                  for c in s1["candidates"]))
        s2 = call_tool(cg, "cg", {"op": "maintain", "action": "separate",
                                  "layer": "contextual", "min_jaccard": 0.4,
                                  "apply": True})
        check("apply 写出分离边", s2.get("written_count", 0) >= 1,
              f"written_count={s2.get('written_count')}")
        fa = cg.get("sep_a")["frontmatter"]
        fb = cg.get("sep_b")["frontmatter"]
        check("sep_a → sep_b 对称边", "sep_b" in consistency.separation_targets(fa))
        check("sep_b → sep_a 对称边", "sep_a" in consistency.separation_targets(fb))
        s3 = call_tool(cg, "cg", {"op": "maintain", "action": "separate",
                                  "layer": "contextual", "min_jaccard": 0.4,
                                  "apply": True})
        newly = sum(len(r.get("written") or []) for r in (s3.get("written") or []))
        check("幂等：二次 apply 不重写", newly == 0, str(newly))

        # ---------------------------------------------- ⑦ promote
        print("\n【7】consolidate.promote：分流 → 迁移 → 追溯 → 回滚")
        cg.add("promo_hot", PROMO_HOT, layer="contextual", importance=0.5,
               merge_count=3)
        cg.add("promo_cold", PROMO_COLD, layer="contextual", importance=0.2)
        cg.add("promo_bad", PROMO_BAD, layer="contextual", importance=0.5,
               merge_count=3)
        cg.flush()
        r1 = call_tool(cg, "cg", {"op": "consolidate", "action": "promote"})
        check("dry-run 未写盘", r1.get("dry_run") and r1.get("written") == 0)
        check("命中热节点", r1.get("targeted", 0) >= 1, f"targeted={r1.get('targeted')}")
        check("剔除四要素不全", r1.get("skipped_incomplete", 0) >= 1)
        check("剔除不热节点", r1.get("skipped_not_hot", 0) >= 1)
        r2 = call_tool(cg, "cg", {"op": "consolidate", "action": "promote",
                                  "apply": True})
        check("apply 提升节点",
              r2.get("written", 0) >= 1 and "promo_hot" in (r2.get("promoted") or []),
              f"promoted={r2.get('promoted')}")
        fresh = MdCGOS(ROOT)
        check("已迁到 knowledge 层",
              (fresh.index["nodes"].get("promo_hot") or {}).get("layer") == "knowledge")
        check("留下 promoted_from=contextual 追溯",
              fresh.get("promo_hot")["frontmatter"].get("promoted_from") == "contextual")
        check("promo_bad 仍留 contextual",
              (fresh.index["nodes"].get("promo_bad") or {}).get("layer") == "contextual")
        r3 = call_tool(cg, "cg", {"op": "consolidate", "action": "promote_history"})
        check("promote_history 记录本次提升",
              any(x.get("id") == "promo_hot" for x in (r3.get("records") or [])))
        r4 = call_tool(cg, "cg", {"op": "consolidate", "action": "promote_rollback",
                                  "node_ids": ["promo_hot"]})
        check("promote_rollback 迁回", r4.get("ok") and r4.get("reverted", 0) >= 1,
              str(r4)[:100])
        fresh2 = MdCGOS(ROOT)
        check("迁回 contextual",
              (fresh2.index["nodes"].get("promo_hot") or {}).get("layer") == "contextual")

        # ---------------------------------------------- ⑧ 权限分档
        print("\n【8】权限分档")
        cg.principal = _principal("record")
        check("record 可 importance dry-run（只读预演）",
              not _denied(lambda: call_tool(cg, "cg",
                                            {"op": "maintain", "action": "importance"})))
        check("record 不可 importance apply（需 admin）",
              _denied(lambda: call_tool(cg, "cg", {"op": "maintain",
                                                   "action": "importance",
                                                   "apply": True})))
        check("record 不可 separate apply", _denied(
            lambda: call_tool(cg, "cg", {"op": "maintain", "action": "separate",
                                         "apply": True})))
        check("record 不可 rollback", _denied(
            lambda: call_tool(cg, "cg", {"op": "maintain", "action": "rollback"})))
        check("record 不可 longterm apply", _denied(
            lambda: call_tool(cg, "cg", {"op": "maintain", "action": "longterm",
                                         "apply": True})))
        cg.principal = _principal("output")
        check("output 整 op 被拒（未授权 maintain）", _denied(
            lambda: call_tool(cg, "cg", {"op": "maintain", "action": "stat"})))
        cg.principal = _principal("verify")
        check("verify 不可 consolidate（未授权）", _denied(
            lambda: call_tool(cg, "cg", {"op": "consolidate", "action": "promote"})))
        cg.principal = Principal(tenant="default", actor="p30", clearance="internal",
                                 can_write=True, can_admin=True, role="designer")

        # ---------------------------------------------- ⑨ 未知 action
        print("\n【9】未知 action 不静默成功")
        bad = None
        try:
            call_tool(cg, "cg", {"op": "maintain", "action": "no_such_action"})
        except Exception as exc:                       # noqa: BLE001
            bad = exc
        check("maintain 未知 action 抛错", bad is not None, type(bad).__name__)
        bad2 = None
        try:
            call_tool(cg, "cg", {"op": "consolidate", "action": "no_such_action"})
        except Exception as exc:                       # noqa: BLE001
            bad2 = exc
        check("consolidate 未知 action 抛错", bad2 is not None, type(bad2).__name__)

    finally:
        try:
            cg.close()
        except Exception:                              # noqa: BLE001
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    if FAILS:
        print("失败项：")
        for n in FAILS:
            print(f"  - {n}")
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
