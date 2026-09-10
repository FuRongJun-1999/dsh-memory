# -*- coding: utf-8 -*-
"""md_cg · 第 20 篇：演化账本（md 载体 · 记录规律与状态 · 可回滚）

设计立场：演化记录的价值不在机器回放，而在**认知规律可读**。
  · 载体是 md（`_evolution/ledger.md`），人类可读，单一真相源
  · 每一次修改 = 对一条缺失条件的补充（pattern 规律 + missing 缺失条件）
  · 记录的是认知规律与状态，不是实现细节（实现属于 git）
  · 回滚把状态撤回 before，且撤销本身也记一条条目（不可静默）

覆盖：
  A 载体与格式：md 生成 · 中文标签人类可读 · 状态快照内嵌可解析 · append-only
  B 规律统计：按缺失条件维度聚类 · top_patterns · evolution/rollback 分账
  C 回滚：状态撤回 before · 删除改动后才出现的字段 · 撤销留痕 · dry_run · 拒绝条件
  D 与 consolidate 联动：固化 = 补缺失条件 → 自动落账 + 可回滚
  E 自描述与 MCP：catalog / summary / health / mdcg_evolution / cg op / 管理权
  F 幂等与并发：多次追加不丢

运行：python -m md_cg.test_p20_evolution
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

from . import consolidate, evolution
from .mdcos import MdCGOS, MdCGSecure
from .security import AccessDenied, Principal

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


# ---------------- consolidate 的假双模型（同 P6 口径） ----------------
BODY = ("# 功能名：微分方程应用\n"
        "微分方程应用：建模与求解，使用数值方法迭代求解，需给定边界条件\n")
CAND = {"生效条件": ["微分方程", "数值方法"], "子功能": ["建模", "求解"],
        "执行": "使用数值方法迭代求解", "不适用条件": ["边界条件缺失"]}


def fake_reflect(prompt):
    return "```json\n" + json.dumps(CAND, ensure_ascii=False) + "\n```"


def fake_verify(prompt):
    out = {f: {"keep": v if isinstance(v, list) else [v], "drop": [],
               "reason": "逐条核验"} for f, v in CAND.items()}
    return json.dumps(out, ensure_ascii=False)


def main():
    root = tempfile.mkdtemp(prefix="mdcg_p20_")
    cg = MdCGOS(root)

    # ================= A. 载体与格式 =================
    print("\n[A] 载体与格式（md 人类可读 · 状态内嵌可解析 · append-only）")

    cg.add("n1", "# 功能名：示例节点\n用于演化账本测试\n", layer="knowledge",
           importance=0.5, confidence=0.6)

    raised = False
    try:
        cg.evolution_record(node_id="n1", pattern="", missing="执行")
    except ValueError:
        raised = True
    check("A1 缺「规律」被拒（没有规律就没有可复用认知）", raised)

    raised = False
    try:
        cg.evolution_record(node_id="n1", pattern="规律X", kind="不存在的类型")
    except ValueError:
        raised = True
    check("A2 未知演化类型被拒", raised)

    e1 = cg.evolution_record(
        node_id="n1", pattern="缺时间窗口的条件在跨季度查询里被误召回",
        missing="conditions.time_window", change="补充生效条件的时间窗口",
        evidence="replay通过", source="manual",
        before={"confidence": 0.6, "importance": 0.5},
        after={"confidence": 0.55, "importance": 0.5})

    led = os.path.join(root, evolution.EVOLUTION_DIR, evolution.LEDGER_NAME)
    check("A3 账本落在 _evolution/ledger.md", os.path.exists(led), led)

    text = evolution.read_ledger(cg)
    check("A4 正文是人类可读中文标签",
          all(f"**{k}**" in text for k in ("规律", "缺失条件", "动作", "状态", "证据")),
          text[:0] or "")
    check("A5 规律原文入账", "跨季度查询里被误召回" in text)
    check("A6 状态差异人可读", "confidence 0.6→0.55" in text,
          [l for l in text.split("\n") if "状态" in l][:1])

    blocks = evolution._STATE_RE.findall(text)
    parsed_state = json.loads(blocks[0]) if blocks else {}
    check("A7 状态快照内嵌 json 块且可解析",
          parsed_state.get("before", {}).get("confidence") == 0.6
          and parsed_state.get("kind") == "condition_gap",
          str(parsed_state)[:80])

    e2 = cg.evolution_record(node_id="n1", pattern="缺执行维的节点无法判定适用性",
                             missing="execution", change="补执行", source="manual")
    text2 = evolution.read_ledger(cg)
    check("A8 append-only：旧条目不被覆盖",
          e1["entry_id"] in text2 and e2["entry_id"] in text2)
    check("A9 账本头部说明只出现一次",
          text2.count("# 演化账本 · md_cg") == 1)

    ents = cg.evolution_entries(limit=10)["entries"]
    check("A10 entries 倒序（最新在前）", ents and ents[0]["entry_id"] == e2["entry_id"])
    check("A11 entries limit 生效",
          len(cg.evolution_entries(limit=1)["entries"]) == 1)
    check("A12 show 取单条", cg.evolution_show(e1["entry_id"])["entry"]["node_id"] == "n1")

    # ================= B. 规律统计 =================
    print("\n[B] 规律统计（认知功能记录规律：看清反复缺什么）")

    cg.evolution_record(node_id="n1", pattern="缺时间窗口的条件在跨季度查询里被误召回",
                        missing="conditions.time_window", source="consolidate")
    pat = cg.evolution_patterns()
    check("B1 按缺失条件维度聚类", pat["by_missing"].get("conditions.time_window") == 2,
          str(pat["by_missing"]))
    check("B2 top_patterns 计数重复规律",
          pat["top_patterns"] and pat["top_patterns"][0]["count"] == 2,
          str(pat["top_patterns"][:1]))
    check("B3 来源统计", pat["by_source"].get("manual") == 2
          and pat["by_source"].get("consolidate") == 1, str(pat["by_source"]))
    check("B4 evolution 与 rollback 分账（此时无回滚）",
          pat["evolutions"] == 3 and pat["rollbacks"] == 0, str(pat["total"]))

    # ================= C. 回滚 =================
    print("\n[C] 回滚（撤回补充 · 撤销留痕 · 拒绝条件）")

    fm0 = cg.get("n1")["frontmatter"]
    fm0["non_applicable_conditions"] = ["边界条件缺失"]
    fm0["confidence"] = 0.55
    cg._write_node("n1", os.path.join(root, cg.get("n1")["path"]), fm0,
                   cg.get("n1")["content"])

    before = {"confidence": 0.6, "importance": 0.5}
    after = {"confidence": 0.55, "importance": 0.5,
             "non_applicable_conditions": ["边界条件缺失"]}
    e3 = cg.evolution_record(node_id="n1", pattern="补负条件以防误召回",
                             missing="non_applicable_conditions",
                             change="补充不适用条件", source="manual",
                             before=before, after=after)

    dry = cg.evolution_rollback(e3["entry_id"], dry_run=True)
    check("C1 dry_run 预演列出将删除的字段",
          dry["ok"] and dry["would_remove"] == ["non_applicable_conditions"],
          str(dry.get("would_remove")))
    check("C2 dry_run 不落盘", cg.get("n1")["frontmatter"].get("confidence") == 0.55)
    n_before = len(cg.evolution_entries(limit=0)["entries"])
    check("C3 dry_run 不写条目",
          len(cg.evolution_entries(limit=0)["entries"]) == n_before)

    rb = cg.evolution_rollback(e3["entry_id"])
    fm1 = cg.get("n1")["frontmatter"]
    check("C4 回滚把状态撤回 before", fm1.get("confidence") == 0.6, str(fm1.get("confidence")))
    check("C5 回滚删除「改动后才出现」的字段（真的撤回补充）",
          "non_applicable_conditions" not in fm1, str(fm1.get("non_applicable_conditions")))
    check("C6 回滚本身记一条条目且不可静默",
          rb["rollback_entry"]["kind"] == evolution.KIND_ROLLBACK
          and rb["rollback_entry"]["rollback_of"] == e3["entry_id"],
          str(rb["rollback_entry"].get("rollback_of")))
    pat2 = cg.evolution_patterns()
    check("C7 回滚计入 rollbacks 分账", pat2["rollbacks"] == 1, str(pat2))

    again = cg.evolution_rollback(rb["rollback_entry"]["entry_id"])
    check("C8 不能回滚一条回滚记录", again["ok"] is False, str(again.get("error")))

    e4 = cg.evolution_record(node_id="n1", pattern="无状态快照的条目")
    no_state = cg.evolution_rollback(e4["entry_id"])
    check("C9 无 before 的条目拒绝回滚", no_state["ok"] is False, str(no_state.get("error")))

    missing = cg.evolution_rollback("evo-19700101-000000-dead")
    check("C10 不存在的条目拒绝回滚", missing["ok"] is False, str(missing.get("error")))

    # 层迁移回滚
    cg._move_layer("n1", "contextual", reason="p20 test")
    e5 = cg.evolution_record(node_id="n1", pattern="上下文相关，降级到 contextual",
                             missing="conditions", change="层间迁移",
                             source="manual",
                             before={"layer": "knowledge"},
                             after={"layer": "contextual"})
    rb5 = cg.evolution_rollback(e5["entry_id"])
    check("C11 回滚层迁移（contextual → knowledge）",
          "layer" in rb5["applied"] and cg.get("n1")["frontmatter"].get("layer") == "knowledge",
          str(rb5["applied"]))

    # ================= D. 与 consolidate 联动 =================
    print("\n[D] 与 consolidate 联动（每一次固化 = 补一条缺失条件）")

    root2 = tempfile.mkdtemp(prefix="mdcg_p20c_")
    try:
        cg2 = MdCGOS(root2)
        cg2.add("n1", BODY, layer="knowledge")
        n0 = len(cg2.evolution_entries(limit=0)["entries"])
        rep = consolidate.consolidate(root2, apply=True, reflect_fn=fake_reflect,
                                      verify_fn=fake_verify, verification_basis="测试依据",
                                      verbose=False)
        ents = cg2.evolution_entries(limit=0)["entries"]
        check("D1 固化前账本为空", n0 == 0, str(n0))
        check("D2 固化后自动落账 1 条", len(ents) == 1 and rep["written"] == 1,
              f"entries={len(ents)} written={rep['written']}")
        ce = ents[0]
        check("D3 来源标记 consolidate", ce["source"] == "consolidate", str(ce.get("source")))
        check("D4 缺失条件记全（含执行维）",
              all(f in ce["missing"] for f in ("执行", "生效条件", "不适用条件")),
              str(ce.get("missing")))
        check("D5 状态快照记下补充后的负条件",
              (ce["state"].get("after") or {}).get("non_applicable_conditions") == ["边界条件缺失"],
              str(ce["state"].get("after")))
        check("D6 规律可读且非空", len(ce["pattern"]) > 8, ce["pattern"])

        rb = cg2.evolution_rollback(ce["entry_id"])
        fm = cg2.get("n1")["frontmatter"]
        check("D7 consolidate 的补充可回滚（负条件被撤回）",
              rb["ok"] and not fm.get("non_applicable_conditions"),
              str(fm.get("non_applicable_conditions")))
        cg2.close()
    finally:
        shutil.rmtree(root2, ignore_errors=True)

    # ================= E. 自描述与 MCP =================
    print("\n[E] 自描述与 MCP（可发现 · 可路由 · 管理权）")

    cat = cg.evolution_catalog()
    check("E1 原则含「每一次修改 = 对一条缺失条件的补充」",
          any("缺失条件" in p for p in cat["principles"]), str(cat["principles"][:1]))
    check("E2 自描述写清回滚范围与未覆盖项",
          "scope" in cat["rollback"] and cat["rollback"].get("not_covered"),
          str(cat["rollback"].get("not_covered")))
    check("E3 自描述列出状态字段与条件维度",
          "confidence" in cat["state_fields"] and "execution" in cat["condition_dims"])

    s = cg.evolution_summary()
    check("E4 summary 一句话 + 最近条目", "演化" in s["text"] and s["recent"],
          s["text"])
    h = cg.health_os()
    check("E5 health_os 并入 evolution 面", "evolution" in h["os"],
          str(list(h["os"].keys()))[:60])

    from . import mcp_server as ms
    names = {t["name"] for t in ms.TOOLS}
    check("E6 MCP 注册 mdcg_evolution", "mdcg_evolution" in names)
    r = ms._cg_call(cg, {"op": "evolution", "action": "catalog"})
    check("E7 cg op=evolution 路由到账本", r.get("module") == "evolution",
          str(r.get("module")))
    r2 = ms._evolution_call(cg, {"action": "patterns", "limit": 3})
    check("E8 细粒度入口与 cg op 同源", "by_missing" in r2, str(list(r2.keys())))

    root3 = tempfile.mkdtemp(prefix="mdcg_p20s_")
    try:
        cg_s = MdCGSecure(root3, principal=Principal(
            tenant="private", actor="op", clearance="private",
            can_write=True, can_admin=False))
        cg_s.add("n1", "# 受管节点\n", layer="knowledge")
        es = cg_s.evolution_record(node_id="n1", pattern="管理权测试",
                                   before={"confidence": 0.6},
                                   after={"confidence": 0.5})
        denied = False
        try:
            cg_s.evolution_rollback(es["entry_id"])
        except AccessDenied:
            denied = True
        check("E9 回滚需 can_admin（直接 API 亦拦截）", denied)
        cg_s.close()
    finally:
        shutil.rmtree(root3, ignore_errors=True)

    # ================= F. 幂等与并发 =================
    print("\n[F] 幂等与并发（append-only 不丢）")

    root4 = tempfile.mkdtemp(prefix="mdcg_p20f_")
    try:
        cg4 = MdCGOS(root4)
        cg4.add("n1", "# 节点\n", layer="knowledge")
        ids = [cg4.evolution_record(node_id="n1", pattern=f"规律{i}",
                                    missing="execution")["entry_id"]
               for i in range(10)]
        got = {e["entry_id"] for e in cg4.evolution_entries(limit=0)["entries"]}
        check("F1 连续 10 次追加全部保留", set(ids) <= got and len(got) == 10,
              f"got={len(got)}")
        cg4.evolution_record(node_id="other", pattern="别的节点", missing="conditions")
        hh = cg4.evolution_history("n1")
        check("F2 history 按节点过滤", len(hh["entries"]) == 10, str(len(hh["entries"])))
        check("F3 账本可被重新解析（幂等读取）",
              len(cg4.evolution_entries(limit=0)["entries"]) == 11)
        cg4.close()
    finally:
        shutil.rmtree(root4, ignore_errors=True)

    cg.close()
    shutil.rmtree(root, ignore_errors=True)

    print(f"\n结果：PASS={PASS}  FAIL={FAIL}")
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
