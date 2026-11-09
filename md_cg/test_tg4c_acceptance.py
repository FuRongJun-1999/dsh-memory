# -*- coding: utf-8 -*-
r"""g4c-20261011/t3 收口验收：写入侧六要素补齐（t1）· backfill 补全（t2）· health 计数。

【交付判据（accept 原文 → 本文件的断言映射）】
  A01 在影子根用 MdCG.add() 写入一个**六要素不全**的 content（无任何 CCG 标题行）
      + 提供 verification_basis='test'、non_applicable_conditions 列表，
      落盘后读回断言 ccg_completeness 为 True 且六行齐全、原文正文未被破坏；
  A02 对该影子根旧式节点跑 backfill.plan/apply，断言补全后 complete=True、
      rollback 后还原；
  A03 断言 health()（影子根）ccg_complete 从 0 变为 >0。

【忠实度纪律（本文件的第一原则）】
  判据逐字落实，**不因实现缺口放宽断言**；同样地，**也不保留任何与实测不符的
  叙述**——文件头的结论小节若写「A01 红」而实测是绿，读者的判断会被文字带偏，
  比断言写错更坏。本节的每个结论都必须是本文件当次运行能复现的读数。
  本文件是本次任务的唯一产物：绝不改任何实现文件。

【本次实测结论（2026-10-11，t3 收口轮实测，与本文件当次运行输出一致）】
  · t1（写入侧补齐）**已完整合入**：`MdCG._ensure_ccg_six`（mdcg.py:2273）在
    写盘前被调用（mdcg.py:2748），其推导源函数 `MdCG._ccg_six_candidates`
    （mdcg.py:2208）**六要素全有来源**，含「执行 ← comment.执行/执行方式」
    （mdcg.py:2250-2254，与 backfill.derive_fields 同款口径）。
  · 故 A01 实测 **6/6 行齐全、ratio=1.00、complete == True**——写入路径达标。
  · A02 回填链路独立成立（直写文件绕过写入侧补齐，故不被 A01 状态污染）：
    plan 判 backfillable → apply 后 complete=True → rollback 逐字节还原。
  · 【已修正的过时结论】本文件上一版曾在文件头宣称「A01 只有 5/6 行、缺『执行』、
    写入路径结构上无法 complete=True」。该结论在 t1 补上「执行」推导源之后已**不成立**；
    本版以实测读数替换，避免留下一个把绿的说成红的假缺口。

【两条断言口径的自我校正（写明以免被误读成放水）】
  · 「原文正文未被破坏」**不是** `c.startswith(原首行)`。`_upsert_ccg_line`
    （consolidate.py:581）在正文无「# 功能名」行时**前置** CCG 行（consolidate.py:607），
    前置是设计本意、不是破坏。故本断言按判据真意取「原正文逐字保留为读回正文的
    连续片段」，并**额外**断言正文的每一行都原样出现、且行内字符未被改写。
  · A01 的「六行齐全 / complete is True」保持严格原样——它现在**真的**绿了，
    且绿在实现上（不是放宽得来的）。

【A03 的口径修正（专用影子根，与 A01/A02 隔离）】
  · `health()` 的 `ccg_by_layer` **只统计已存在的节点**：空影子根下它是 `{}`，
    `(layer_stats).get("knowledge", {}).get("ccg_complete", 0) == 0` 会**空洞通过**
    （键不存在，取的是默认值 0，而不是一条真实的「0 个齐全」读数）。
  · 判据原文要求「**从 0 变为** >0」——「0」必须是一条**同一影子根上真实测得**
    的基线，且把 0 变 >0 的必须是本次回填。**A01 的节点在同一根上会先让
    ccg_complete 变成 1**，所以 A03 用**独立影子根**：只放一个旧式节点
    （无 CCG 行）→ 基线真实测得 knowledge 层存在、total>=1、ccg_complete==0 →
    backfill.apply 后同一根上 ccg_complete 变为 >0 → rollback 后回到 0（往返闭环）。
  · 空根的 `ccg_by_layer == {}` 作为**前置事实**单独断言（不冒充 A03 的「0」）。

【影子根与零污染】
  影子根建在 `<repo>/.tmp/tg4c_accept_<pid>` 下（accept 原文点名 .tmp），
  finally 里整棵删除；不读不写任何真实数据根，不起子进程、不碰 git。

运行：python -X utf8 D:\wook\lingshu-src\md_cg\test_tg4c_acceptance.py
退出码：0 全绿 ／ 1 任一断言失败（失败也跑完全部判据并汇总）
"""
from __future__ import annotations

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from md_cg import backfill, nodefile            # noqa: E402
from md_cg.mdcg import MdCG                     # noqa: E402

PASS = FAIL = 0
FAILS = []


# 生效条件：cond 为真时 PASS 加一并打印 [PASS] 行；为假时 FAIL 加一、记入 FAILS、
# 打印带 detail 的 [FAIL] 行；恒不抛异常（断言失败不阻断其余工况）。
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s%s" % (name, (" —— " + detail) if detail else ""))


# 生效条件：content 给定时返回 {要素名: 该要素的 CCG 行是否存在}，六键齐全；
# 判据单点走 nodefile.ccg_mark_present（与写入闸门/齐全度判据同一语义）；不抛异常。
def ccg_lines_present(content):
    return {m: nodefile.ccg_mark_present(content, m) for m in nodefile.CCG_MARKS}


# 生效条件：body 的每一行都作为完整行出现在 content 中时返回 True；否则 False。
# 用途：判「原文正文未被破坏」——比子串包含更严（子串会把行被拼接到别的行尾
# 也算通过），同时不误伤「CCG 行前置」这一设计本意。不抛异常。
def body_lines_intact(content, body):
    have = set((content or "").split("\n"))
    want = [ln for ln in (body or "").split("\n") if ln.strip()]
    return all(ln in have for ln in want)


# 生效条件：health() 返回值给定、layer 给定，返回该层的统计字典（层不存在时空 dict）。
# 用途：把「层不存在」与「层存在但计数为 0」两种形态分开——A03 的「0」必须取自后者。
def layer_stat(h, layer):
    return ((h.get("ccg_by_layer") or {}).get(layer)) or {}


# A01 正文：无任何 CCG 标题行（六个要素标题行一个都没有）
A01_BODY = ("# 无 CCG 标题行的旧式正文\n"
            "\n"
            "这是一段迁移入库的历史记忆正文，不含任何 CCG 标题行。\n"
            "第二行原文，必须原样保留。\n")

# A01 元数据：除 accept 点名的 verification_basis / non_applicable_conditions 外，
# **给足全部合法可推导源**（state_attributes.name 供功能名、condition_space 四槽
# 供生效条件、depends_on 供子功能、comment.执行 供执行）——这样「六行齐全」是
# 实现**可及**的目标；若仍缺行，缺口就是精确的、不可推给「你没给数据」。
A01_KW = dict(
    layer="knowledge",
    verification_basis="test",
    non_applicable_conditions=["二进制文件", "超过 50MB 的文件"],
    condition_space={
        "observation_position": "本地文件系统",
        "observation_tool": "扩展名映射表",
        "time_window": [0.0, 9999999999.0],
        "existence_constraint": "仅对本地可读文件生效",
    },
    state_attributes={"name": "文件摄取分派", "comment": {
        "子功能": "按扩展名路由到对应摄取器",
        "执行": "读后缀映射表→调用对应 Ingestor",
    }},
    depends_on=["ingestor_v1"],
)

# A02 旧式节点 frontmatter：完整声明（comment 含子功能/执行 = backfill 的合法来源）。
# 该节点由 nodefile.dumps **直写文件**，绕过 add() 的写前补齐，故无论 t1 合入与否
# 都是「无 CCG 行的旧式形态」——A02 因此不被 A01 的状态污染，可独立成立。
A02_FM = {
    "id": "a02_old",
    "layer": "knowledge",
    "modality": "text",
    "importance": 0.5,
    "confidence": 0.6,
    "condition_space": {
        "observation_position": "本地文件系统（旧式迁移）",
        "observation_tool": "Ingestor 表",
        "time_window": [0.0, 9999999999.0],
        "existence_constraint": "仅对本地可读文件生效",
    },
    "tags": [],
    "created_at": 1000.0,
    "access_count": 0,
    "last_access": 0,
    "edges": [],
    "verification_basis": "test",
    "non_applicable_conditions": ["二进制文件", "超过 50MB 的文件"],
    "evidence_count": 0,
    "positive_evidence": 0,
    "negative_evidence": 0,
    "state_attributes": {"name": "旧式迁移节点", "comment": {
        "子功能": "按扩展名路由",
        "执行": "读映射表分派",
    }},
    "depends_on": ["ingestor_v1"],
}
A02_BODY = "# 旧式迁移正文\n\n不含 CCG 标题行，frontmatter 已带完整声明。\n"


# 生效条件：依次跑 空根前置 / A01 写入侧 / A02 回填链 / A03 专用根 0→>0→0 闭环
# 四组工况，逐条 check；恒在 finally 里删掉全部影子根；任一工况异常都会被 main
# 兜住并计一次失败。
def run_cases():
    root = os.path.join(REPO, ".tmp", "tg4c_accept_%d" % os.getpid())
    root_a03 = os.path.join(REPO, ".tmp", "tg4c_accept_a03_%d" % os.getpid())
    for _p in (root, root_a03):
        shutil.rmtree(_p, ignore_errors=True)
        os.makedirs(_p, exist_ok=True)
    print("影子根：%s" % root)
    print("A03 专用影子根：%s" % root_a03)
    try:
        cg = MdCG(root)
        BATCH = "tg4c_accept"

        # ===== 前置事实：真空根下 ccg_by_layer 为空表（层不存在，不是「0 个齐全」）====
        # 这条**不**充当 A03 的「0」：它证明的是「层不存在时读数为空」，
        # 与判据要求的「同一根上真实测得的 0」是两件事，分开记以免空洞通过。
        print("— 前置 · 真空影子根 health() 的 ccg_by_layer 为空表（无层可计）")
        h_empty = cg.health()
        check("前置 真空根 knowledge 层不存在（ccg_by_layer 内无该键）",
              "knowledge" not in (h_empty.get("ccg_by_layer") or {}),
              "ccg_by_layer=%r total_nodes=%r"
              % (h_empty.get("ccg_by_layer"), h_empty.get("total_nodes")))

        # ============ A01：MdCG.add() 写前六要素补齐 ==============================
        print("— A01 · MdCG.add() 写入无 CCG 标题行 content + 元数据，落盘读回")
        check("A01 前置：待写 content 确无任何 CCG 标题行（“六要素不全”）",
              not any(ccg_lines_present(A01_BODY).values()),
              str(ccg_lines_present(A01_BODY)))

        cg.add("a01_node", A01_BODY, **A01_KW)
        cg.flush()
        # 落盘读回（走真文件，不是内存态）——判据的「落盘后读回」逐字落实
        fm1, c1 = cg._read(cg.index["nodes"]["a01_node"])
        cpl1 = nodefile.ccg_completeness(c1)
        lines1 = ccg_lines_present(c1)
        missing1 = [m for m, ok in lines1.items() if not ok]

        check("A01 ccg_completeness.complete is True（六要素齐全）",
              cpl1["complete"] is True,
              "present=%r ratio=%.2f" % (cpl1["present"], cpl1["ratio"]))
        check("A01 六行齐全（功能名/生效条件/子功能/执行/验证方式/不适用条件）",
              all(lines1.values()),
              ("缺失：" + "、".join(missing1)) if missing1 else "无")
        # 「原文正文未被破坏」的真意 = 原正文逐字保留（不是“首行仍居首”——见文件头）
        _lost1 = [ln for ln in A01_BODY.split("\n")
                  if ln.strip() and ln not in set(c1.split("\n"))]
        check("A01 原文正文未被破坏（原正文逐行原样保留、未被改写）",
              not _lost1,
              ("读回正文缺失原行：" + repr(_lost1)) if _lost1 else "")
        check("A01 原文正文整段仍是读回正文的连续片段（非仅逐行存在）",
              A01_BODY.strip() in c1,
              "" if A01_BODY.strip() in c1
              else ("读回正文尾部 120 字符：" + repr(c1[-120:])))
        check("A01 frontmatter 携带 verification_basis='test'",
              fm1.get("verification_basis") == "test",
              "got=%r" % (fm1.get("verification_basis"),))
        check("A01 frontmatter 携带 non_applicable_conditions 列表",
              fm1.get("non_applicable_conditions") == A01_KW["non_applicable_conditions"],
              "got=%r" % (fm1.get("non_applicable_conditions"),))

        # ============ A02：旧式节点 backfill plan/apply/rollback =================
        print("— A02 · 旧式节点（直写文件，绕过 add 补齐）→ plan/apply/rollback")
        os.makedirs(os.path.join(root, "knowledge"), exist_ok=True)
        with open(os.path.join(root, "knowledge", "a02_old.md"),
                  "w", encoding="utf-8") as f:
            f.write(nodefile.dumps(A02_FM, A02_BODY))
        cg.rebuild_index()
        _fm_b, c_b = cg._read(cg.index["nodes"]["a02_old"])
        cpl_b = nodefile.ccg_completeness(c_b)
        check("A02 前置：旧式节点确无 CCG 行且 complete=False",
              (not cpl_b["complete"]) and (not any(ccg_lines_present(c_b).values())),
              "complete=%r present=%r" % (cpl_b["complete"], cpl_b["present"]))

        # ---- A03：独立影子根上 ccg_complete 由 0 变为 >0（专用根，见文件头口径）----
        print("— A03 · 专用影子根：只放旧式节点 → 回填 → 计数 0 → >0 → 回 0")
        cg3 = MdCG(root_a03)
        os.makedirs(os.path.join(root_a03, "knowledge"), exist_ok=True)
        # A03_FM 与 A02_FM 同构，但 id 必须与盘上文件名 a03_old 一致
        # （_scan_nodes 以文件名派定 node_id，fm.id 不一致会被跳过）。
        A03_FM = dict(A02_FM, id="a03_old")
        with open(os.path.join(root_a03, "knowledge", "a03_old.md"),
                  "w", encoding="utf-8") as f:
            f.write(nodefile.dumps(A03_FM, A02_BODY))
        cg3.rebuild_index()
        _fm_b3, c_b3 = cg3._read(cg3.index["nodes"]["a03_old"])
        check("A03 前置：专用根旧式节点确无 CCG 行且 complete=False",
              (not nodefile.ccg_completeness(c_b3)["complete"])
              and (not any(ccg_lines_present(c_b3).values())),
              "complete=%r present=%r"
              % (nodefile.ccg_completeness(c_b3)["complete"],
                 nodefile.ccg_completeness(c_b3)["present"]))

        h3_0 = cg3.health()
        k3_0 = layer_stat(h3_0, "knowledge")
        check("A03 基线：knowledge 层**存在**（不是缺键取默认值）",
              "knowledge" in (h3_0.get("ccg_by_layer") or {}),
              "ccg_by_layer keys=%r" % (sorted((h3_0.get("ccg_by_layer") or {}).keys()),))
        check("A03 基线：knowledge.total >= 1（确有节点被统计）",
              k3_0.get("total", 0) >= 1, "total=%r" % (k3_0.get("total"),))
        check("A03 基线：knowledge.ccg_complete == 0（“从 0”是真读数）",
              k3_0.get("ccg_complete") == 0,
              "ccg_complete=%r total=%r" % (k3_0.get("ccg_complete"), k3_0.get("total")))

        ap3 = backfill.apply(cg3, ids=["a03_old"], batch=BATCH + "_a03", actor="tg4c")
        check("A03 apply：written >= 1", ap3.get("written") >= 1,
              "written=%r" % (ap3.get("written"),))
        h3_1 = cg3.health()
        k3_1 = layer_stat(h3_1, "knowledge")
        check("A03 回填后 knowledge.ccg_complete > 0（“变为 >0”成立）",
              k3_1.get("ccg_complete", 0) > 0,
              "ccg_complete=%r total=%r（同一根基线 %r）"
              % (k3_1.get("ccg_complete"), k3_1.get("total"), k3_0.get("ccg_complete")))
        check("A03 回填后 knowledge.ccg_complete > 基线（增量确由本次回填造成）",
              k3_1.get("ccg_complete", 0) > k3_0.get("ccg_complete", 0),
              "before=%r after=%r" % (k3_0.get("ccg_complete"), k3_1.get("ccg_complete")))
        _fm3, c3x = cg3._read(cg3.index["nodes"]["a03_old"])
        check("A03 回填后该节点 complete=True（计数变化的落点）",
              nodefile.ccg_completeness(c3x)["complete"] is True,
              "present=%r" % (nodefile.ccg_completeness(c3x)["present"],))

        rb3 = backfill.rollback(cg3, batch=BATCH + "_a03", actor="tg4c")
        check("A03 rollback：reverted >= 1", rb3.get("reverted") >= 1,
              "reverted=%r" % (rb3.get("reverted"),))
        h3_2 = cg3.health()
        k3_2 = layer_stat(h3_2, "knowledge")
        check("A03 rollback 后 knowledge.ccg_complete 回到 0（往返闭环）",
              k3_2.get("ccg_complete") == 0,
              "ccg_complete=%r total=%r（before=%r after=%r）"
              % (k3_2.get("ccg_complete"), k3_2.get("total"),
                 k3_0.get("ccg_complete"), k3_1.get("ccg_complete")))
        _fm3r, c3r = cg3._read(cg3.index["nodes"]["a03_old"])
        check("A03 rollback 后节点正文逐字节还原",
              c3r == A02_BODY,
              ("" if c3r == A02_BODY
               else "正文不一致（尾部 120 字符：" + repr(c3r[-120:]) + "）"))

        # ---- A02 收尾：rollback 必须「还原」 -----------------------------------

        pl = backfill.plan(cg, ids=["a02_old"])
        item = next((i for i in (pl.get("items") or [])
                     if i.get("id") == "a02_old"), None)
        check("A02 plan：dry_run=True 且 targeted 含旧式节点",
              pl.get("dry_run") is True and pl.get("targeted") >= 1
              and "a02_old" in (pl.get("planned_ids") or []),
              "dry_run=%r targeted=%r" % (pl.get("dry_run"), pl.get("targeted")))
        check("A02 plan：旧式节点判为 backfillable（有来源可回填）",
              item is not None and item.get("class") == "backfillable",
              "class=%r missing_undeducible=%r"
              % ((item or {}).get("class"), (item or {}).get("missing_undeducible")))
        _fm_p, c_plan = cg._read(cg.index["nodes"]["a02_old"])
        check("A02 plan 预演未改盘（正文仍无 CCG 行）",
              not any(ccg_lines_present(c_plan).values()),
              "present=%r" % (nodefile.ccg_completeness(c_plan)["present"],))

        ap = backfill.apply(cg, ids=["a02_old"], batch=BATCH, actor="tg4c")
        check("A02 apply：written >= 1", ap.get("written") >= 1,
              "written=%r" % (ap.get("written"),))
        _fm2, c2 = cg._read(cg.index["nodes"]["a02_old"])
        cpl2 = nodefile.ccg_completeness(c2)
        lines2 = ccg_lines_present(c2)
        missing2 = [m for m, ok in lines2.items() if not ok]
        check("A02 apply 后 complete=True",
              cpl2["complete"] is True,
              "present=%r ratio=%.2f" % (cpl2["present"], cpl2["ratio"]))
        check("A02 apply 后六行齐全（含 comment 推导的执行）",
              all(lines2.values()),
              ("缺失：" + "、".join(missing2)) if missing2 else "无")
        check("A02 apply 未破坏原文正文（原正文逐行原样保留）",
              body_lines_intact(c2, A02_BODY),
              ("读回正文尾部 120 字符：" + repr(c2[-120:]))
              if not body_lines_intact(c2, A02_BODY) else "")

        # ---- A03：独立影子根上 ccg_complete 由 0 变为 >0（专用根，见文件头口径）----

        # ---- A02 收尾：rollback 必须「还原」 -----------------------------------
        rb = backfill.rollback(cg, batch=BATCH, actor="tg4c")
        check("A02 rollback：reverted >= 1", rb.get("reverted") >= 1,
              "reverted=%r" % (rb.get("reverted"),))
        fm3, c3 = cg._read(cg.index["nodes"]["a02_old"])
        check("A02 rollback 后正文逐字节还原（CCG 行移除、原文不变）",
              c3 == A02_BODY,
              ("" if c3 == A02_BODY
               else "正文不一致（尾部 120 字符：" + repr(c3[-120:]) + "）"))
        check("A02 rollback 后 frontmatter 还原（state_attributes/基底/不适用条件）",
              fm3.get("state_attributes") == A02_FM.get("state_attributes")
              and fm3.get("verification_basis") == "test"
              and fm3.get("non_applicable_conditions")
              == A02_FM.get("non_applicable_conditions"),
              "state_attributes=%r" % (fm3.get("state_attributes"),))
        check("A02 rollback 后 ccg_completeness 回到 False（还原为旧式）",
              not nodefile.ccg_completeness(c3)["complete"],
              "present=%r" % (nodefile.ccg_completeness(c3)["present"],))
        # rollback 只撤销 a02_old，A01 节点仍齐全 —— 故 knowledge 层计数应回到
        # 「只剩 a01_node 一个齐全」而非 0；把它记成读数，不当作判据（判据只要求
        # 从 0 变 >0，回滚后的具体值由 A01 是否同层决定）。
        h2 = cg.health()
        k2 = layer_stat(h2, "knowledge")
        print("      （信息）rollback 后 health knowledge.ccg_complete = %r / total = %r"
              % (k2.get("ccg_complete"), k2.get("total")))

        # 幂等复验：还原后可再次回填（证明 rollback 是真逆操作、不是把节点弄坏）
        ap2 = backfill.apply(cg, ids=["a02_old"], batch=BATCH + "_2", actor="tg4c")
        check("A02 还原后可再次回填（apply 再次 written>=1）",
              ap2.get("written") >= 1, "written=%r" % (ap2.get("written"),))
        _fm4, c4 = cg._read(cg.index["nodes"]["a02_old"])
        check("A02 二次回填后仍 complete=True（往返可复现）",
              nodefile.ccg_completeness(c4)["complete"] is True,
              "present=%r" % (nodefile.ccg_completeness(c4)["present"],))
        backfill.rollback(cg, batch=BATCH + "_2", actor="tg4c")
    finally:
        for _p in (root, root_a03):
            shutil.rmtree(_p, ignore_errors=True)
        print("影子根已清理：%s" % root)
        print("A03 专用影子根已清理：%s" % root_a03)


# 生效条件：跑完全部工况并打印「N 通过，M 失败」汇总（有失败则附失败项名），
# 返回 0 当且仅当 FAIL==0；run_cases 抛出的任何异常被计为一次失败并带 traceback。
def main():
    print("tg4c acceptance：写入侧六要素补齐 / backfill 补全 / health 计数")
    print("-" * 68)
    try:
        run_cases()
    except Exception as exc:                                   # noqa: BLE001
        import traceback
        check("运行期无未捕获异常", False,
              "%s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc()))
    print("-" * 68)
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("tg4c acceptance：%d 通过，%d 失败" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
