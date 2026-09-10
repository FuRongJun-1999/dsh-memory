# -*- coding: utf-8 -*-
"""md_cg · 第 9 篇：主动遗忘闸门 + 自我认知写保护

覆盖：
  A 写保护（不可遗忘）
      层保护 self/anchor · 新建放行 · 覆盖拒绝 · override 放行 + 旧版本快照 +
      审计留痕 · 重要性≥0.7 自动打标 · 普通节点不受限 · 删除保护 ·
      降级保护 · 保护层内搬迁放行 · 保护面盘点
  B 主动遗忘闸门（写入侧三问）
      重复→MERGE（不新增，强化既有） · 确定性内部冗余→DROP（先于 MERGE） ·
      外部惊奇→ACCEPT · importance_hint≥0.7→ACCEPT（保护优先） ·
      半重复且不重要→DEFER · DROP/DEFER 不落库 · 留痕可审计 ·
      自信息代理单调性 · 来源分类 · 强化跨阈值自动保护 · gated=False 兼容

运行：python -m md_cg.test_p9_forget_protect
"""
from __future__ import annotations

import os
import tempfile

from .mdcos import MdCGOS
from . import forgetting, protect

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


def blocked_by(fn):
    """执行 fn，返回是否被 ProtectionError 拦下。"""
    try:
        fn()
        return False
    except protect.ProtectionError:
        return True


def main():
    root = tempfile.mkdtemp(prefix="mdcg_p9_")
    cg = MdCGOS(root)
    try:
        # ================= A. 自我认知写保护 =================
        print("\n[A] 自我认知写保护（不可遗忘）")

        cg.add("self_identity", ccg("身份", body="我是灵枢"), layer="self")
        check("self 层新建放行（保护的是已有认知，不是禁止产生）",
              cg.get("self_identity") is not None)

        check("self 层覆盖被拒",
              blocked_by(lambda: cg.add("self_identity", ccg("身份", body="篡改"),
                                        layer="self")))
        cg.add("self_identity", ccg("身份", body="我是灵枢 v2"), layer="self",
               override=True)
        check("override 覆盖成功",
              "我是灵枢 v2" in cg.get("self_identity")["content"])
        hist = protect.history(cg, "self_identity")
        check("override 前自动快照旧版本", len(hist) >= 1, str(hist))
        check("写保护动作留痕 _protected_audit.jsonl",
              os.path.exists(os.path.join(root, protect.AUDIT_FILE)))

        cg.add("anc1", ccg("锚点", body="核心锚点"), layer="anchor")
        prot, why = protect.is_protected(cg, "anc1")
        check("anchor 层受保护", prot and "层保护" in why, why)

        cg.add("imp9", ccg("高重要", body="关键知识"), layer="knowledge",
               importance=0.9)
        fm9 = cg.get("imp9")["frontmatter"]
        check("importance≥0.7 自动打保护标记",
              fm9.get("protected") is True, str(fm9.get("protection_reason")))
        cg.add("imp9", ccg("高重要", body="关键知识 v2"), layer="knowledge",
               importance=0.9)
        check("高重要性节点仍可更新（不可遗忘 ≠ 不可覆盖）",
              "v2" in cg.get("imp9")["content"])
        check("高重要性节点删除被拒（不可遗忘）",
              blocked_by(lambda: cg.forget("imp9", "想删掉")))

        cg.add("imm1", ccg("不可覆盖", body="显式不可覆盖"), layer="knowledge",
               immutable=True)
        check("显式 immutable 节点覆盖被拒",
              blocked_by(lambda: cg.add("imm1", ccg("不可覆盖", body="改写"),
                                        layer="knowledge")))

        cg.add("plain", ccg("普通", body="普通知识"), layer="knowledge",
               importance=0.5)
        cg.add("plain", ccg("普通", body="普通知识v2"), layer="knowledge",
               importance=0.5)
        check("普通节点可自由覆盖（保护不过度扩张）",
              "v2" in cg.get("plain")["content"])

        check("受保护节点删除被拒",
              blocked_by(lambda: cg.forget("anc1", "测试删除")))
        r = cg.forget("anc1", "确实要删", override=True)
        check("override 删除放行",
              r.get("ok") is True and cg.get("anc1") is None, str(r))

        cg.add("anc2", ccg("锚点2", body="锚点2"), layer="anchor")
        check("受保护节点降级被拒",
              blocked_by(lambda: cg._move_layer("anc2", "knowledge", "降级测试")))
        moved = cg._move_layer("anc2", "self", "保护层内搬迁")
        check("保护层之间搬迁放行",
              (moved or {}).get("to") == "self", str(moved))

        st = cg.protect_stats()
        check("保护面盘点（受保护数 + 自动保护计数）",
              st["protected_count"] >= 2 and st["auto_by_importance"] >= 1,
              str({k: st[k] for k in ("protected_count", "by_layer",
                                      "auto_by_importance")}))

        # ================= B. 主动遗忘闸门 =================
        print("\n[B] 主动遗忘闸门（写入侧三问）")

        body = ("# 功能名：编译缓存清理\n# 生效条件：缓存目录超过 2GB 时\n"
                "# 子功能：删除最旧的分片\n# 执行：按 mtime 排序删除\n"
                "# 验证方式：test\n# 不适用条件：缓存被其他进程占用\n"
                "清理编译缓存目录释放磁盘空间\n")
        cg.add("c1", body, layer="contextual", importance=0.5)
        n_before = len(cg.index["nodes"])
        r1 = cg.remember_gated("c2", body, layer="contextual", role="user")
        check("重复内容 → MERGE（并入既有）",
              r1["verdict"] == "MERGE" and r1["merged_into"] == "c1",
              f"{r1['verdict']} · {r1['gate']['reason']}")
        check("MERGE 不新增节点", len(cg.index["nodes"]) == n_before)
        check("MERGE 强化既有节点 importance",
              cg.get("c1")["frontmatter"]["importance"] > 0.5,
              str(cg.get("c1")["frontmatter"]["importance"]))

        r2 = cg.remember_gated("c3", ccg("重要结论", body="这是一条关键结论"),
                               layer="contextual", importance_hint=0.8)
        check("importance_hint≥0.7 → ACCEPT（保护优先）",
              r2["verdict"] == "ACCEPT", r2["gate"]["reason"])
        check("保护优先写入后自动打保护标记",
              cg.get("c3")["frontmatter"].get("protected") is True)

        r3 = cg.remember_gated("c4", body, layer="contextual", role="command")
        check("确定性内部冗余 → DROP（先于 MERGE，不强化既有）",
              r3["verdict"] == "DROP", r3["gate"]["reason"])
        check("DROP 不落库", cg.get("c4") is None)
        check("DROP 未污染既有节点 importance（未走 MERGE 强化）",
              abs(cg.get("c1")["frontmatter"]["importance"] - 0.55) < 1e-6,
              str(cg.get("c1")["frontmatter"]["importance"]))

        fresh = ("# 功能名：奇点事故复盘\n# 生效条件：集群出现未知内存泄漏时\n"
                 "# 子功能：定位泄漏点\n# 执行：堆转储对比\n"
                 "# 验证方式：data\n# 不适用条件：非 JVM 进程\n"
                 "首次观测到未知内存泄漏，与既有记忆无重叠\n")
        r4 = cg.remember_gated("c5", fresh, layer="contextual", role="user")
        check("外部惊奇（全新内容）→ ACCEPT", r4["verdict"] == "ACCEPT",
              r4["gate"]["reason"])
        ent = r4["gate"]["entropy"]
        check("高熵判定：novelty 高 / 自信息代理高",
              ent["novelty"] > 0.8 and ent["self_information_bits"] > 2.0, str(ent))
        check("来源分类：外部惊奇",
              ent["source_kind"] == "external_surprising")
        g = r4["gate"]
        check("裁决含三问完整判据",
              all(k in g for k in ("redundancy", "importance", "entropy"))
              and {"novelty", "self_information_bits", "duplicate_ratio",
                   "source_kind"} <= set(g["entropy"]))

        a2 = "订单退款审批流程校验优惠券叠加规则"
        cg.add("d1", a2, layer="contextual", importance=0.5)
        r5 = cg.remember_gated("d2", a2 + "新增风控节点", layer="contextual",
                               role="assistant", importance_hint=0.1)
        check("半重复且不重要 → DEFER（待定复核）",
              r5["verdict"] == "DEFER",
              f"{r5['verdict']} · dup={r5['gate']['entropy']['duplicate_ratio']:.2f}")
        check("DEFER 不落库", cg.get("d2") is None)

        check("自信息代理单调：dup↑ → bits↓",
              forgetting.self_information(0.0) > forgetting.self_information(0.5)
              > forgetting.self_information(0.99))
        check("来源分类函数",
              forgetting.source_kind(role="user") == "external_surprising"
              and forgetting.source_kind(role="command") == "internal_deterministic"
              and forgetting.source_kind(role="assistant") == "self_generated"
              and forgetting.source_kind(verification_basis="data")
              == "internal_deterministic")

        for _ in range(6):
            forgetting.reinforce(cg, "c1")
        check("重复强化跨 0.7 自动打保护标记",
              cg.get("c1")["frontmatter"].get("protected") is True,
              str(cg.get("c1")["frontmatter"].get("importance")))

        hist = cg.forgetting_history(limit=50)
        check("遗忘裁决留痕（含 ACCEPT/MERGE/DROP/DEFER）",
              {"ACCEPT", "MERGE", "DROP", "DEFER"} <= {h["verdict"] for h in hist},
              str(sorted({h["verdict"] for h in hist})))
        check("留痕文件 _forgetting.jsonl 存在",
              os.path.exists(os.path.join(root, forgetting.LOG_FILE)))

        r6 = cg.remember_gated("c6", body, layer="contextual", gated=False)
        check("gated=False 绕过闸门（兼容既有写入路径）",
              r6.get("bypass") is True and cg.get("c6") is not None)

        check("公开 API：remember_gated / forgetting_history / protect_stats",
              all(hasattr(cg, n) for n in ("remember_gated", "forgetting_history",
                                           "protect_stats")))
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n==== P9 结果：{PASS} 通过 / {FAIL} 失败 ====")
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
