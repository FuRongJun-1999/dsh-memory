# -*- coding: utf-8 -*-
"""md_cg · 主动遗忘闸门（写入情景层前的三问筛选）

理论出处（全部来自本仓已有文档）：

  · `memory_score.md:12`
      J 判断引擎 9-10 档 = 「独立元认知 + **主动遗忘**」；灵枢正因「无主动遗忘」
      停在 8.0。→ 主动遗忘是 J 维上 9 分的门槛项，不是可选优化。
  · `docs/白箱智能系列·第五篇:174-180`
      「把经历兑换成结构…整理完之后记忆库变小了，但信息量反而更可用——
      噪音被扔掉了，骨架被留下。」
  · AEIS 工具表 `docs/mdcg/tool_table_v0.3.0.md:15-19`
      `prefeed`（H1 新奇检测 → 高新奇输入当场强化编码）、
      `pattern_separation`（H3 扫描相似节点对）、
      `nightly_cleanup`（知识层夜间整理、无边孤岛降级）。
      本模块 = 这三件事的**写入侧前置版**：不等夜间整理，写之前就裁决。
  · `docs/theory/智能的公理化基石.md:758-763` —— **诚实边界**
      「信息差与热力学熵之间只能进行结构类比，不应宣称数学同构」。
      故本模块一律称「自信息代理 / 惊奇度」，**不称香农熵**，也不做熵的物理断言。

三问 → 四态裁决（对齐白箱四态，落库动作分四种）：

    Q1 重复？    redundancy  = 新内容被既有同层节点覆盖的最大比例（bigram 覆盖率）
    Q2 重要？    importance  = 显式 hint 优先，否则启发式（新奇/来源/长度）
    Q3 惊奇？    self_info   = -log2(dup + ε)（bit，**代理量**，非香农熵）

    ACCEPT 写入      /  MERGE 并入既有（不新增，强化既有节点）
    DROP   丢弃      /  DEFER 待定（不写，留痕待复核）

裁决顺序（**顺序即语义**）：
    1) 重要度 ≥0.7            → ACCEPT（保护优先）
    2) 确定性内部产生 且 冗余 → DROP  ← 先于 MERGE：机器例行输出再"重复"也只是
                                        噪音，不该去强化既有记忆（否则例行日志
                                        会把普通记忆刷成高重要性）
    3) 冗余 ≥0.85             → MERGE ← 外部/未知来源的重复 = 又一次确认，强化
    4) 半重复 且 不重要       → DEFER
    5) 重要度 ≥0.30           → ACCEPT
    6) 新信息 ≥0.15           → ACCEPT
    7) 其余                   → DEFER

一切裁决都写进 `_forgetting.jsonl`（append-only），可审计：
「这条为什么没被记住」和「为什么被记住」同样有据可查。
"""
import hashlib
import json
import math
import os
import time

from . import lifecycle, nodefile, protect
from . import crypto
from . import security as _security
from .fsutil import append_jsonl, atomic_write, publish, read_jsonl
from .mdcg import bigrams

# ---------------------------------------------------------------- 判据常量

DUP_MERGE = 0.85            # 重复度 ≥ 此值 → MERGE
DUP_DROP = 0.60             # 重复度 ≥ 此值 → 进入 DROP / DEFER 判据
NOVELTY_MIN = 0.15          # 新信息 < 此值 → 视为无新信息
IMPORTANCE_MIN = 0.30       # 重要度 < 此值 → 不予写入
PROTECT_IMPORTANCE = 0.70   # 对齐 tool_table：≥0.7 触发不可遗忘保护
MAX_BITS = 4.0              # 自信息归一化上限（dup=0 时 4.0 bit）
EPS = 0.0625                # 自信息平滑（避免 dup=0 时取 log(0)）
MAX_COMPARE = 240           # 单次重复检测最多比对的同层节点数（写入非热路径）

# 来源类型 → 权重（确定性内部产生 = 低权；外部惊奇 = 高权）
SOURCE_WEIGHT = {
    "external_surprising": 1.00,
    "unknown": 0.60,
    "self_generated": 0.50,
    "internal_deterministic": 0.25,
}
EXTERNAL_ROLES = ("user",)
INTERNAL_ROLES = ("command", "tool-output", "edit", "system")
# 注意：文科的 textbook/public_kb **不在此列**——它们是「权威来源表述一致」，
# 不是「内部确定性产生」，故仍按外部来源计权（见 source_kind）。
DETERMINISTIC_BASIS = ("data", "measurement", "compiler", "test", "formal_proof")

LOG_FILE = "_forgetting.jsonl"

# 合并面「新正文去向」/「归属并列」的常量（B3 / H3，2026-09-30）
MERGE_SOURCES_KEEP = 20         # fm.merge_sources 只保留最近 N 条「新写入方归属」
AGG_MARK = "聚合"               # 聚合行标记（与 writelimit.converge_into 同款）


# ---------------------------------------------------------------- 三问

# 生效条件：role 与 verification_basis 各自经 str(x or "").strip().lower() 后按序判——role 命中模块常量 EXTERNAL_ROLES 返回 "external_surprising"；否则 role 命中 INTERNAL_ROLES、或两者都不命中前者时 verification_basis 命中 DETERMINISTIC_BASIS，返回 "internal_deterministic"；否则 role 为 "assistant"/"agent" 返回 "self_generated"；全不命中返回 "unknown"。
def source_kind(role=None, verification_basis=None):
    """Q3 的来源面：内部确定性产生 vs 外部惊奇来源。"""
    r = str(role or "").strip().lower()
    vb = str(verification_basis or "").strip().lower()
    if r in EXTERNAL_ROLES:
        return "external_surprising"
    if r in INTERNAL_ROLES:
        return "internal_deterministic"
    if vb in DETERMINISTIC_BASIS:
        return "internal_deterministic"
    if r in ("assistant", "agent"):
        return "self_generated"
    return "unknown"


# 生效条件：new_grams 为空集（假值）时返回 0.0；非空时返回 len(new_grams & body_grams)/len(new_grams)。
def _coverage(new_grams, body_grams):
    if not new_grams:
        return 0.0
    return len(new_grams & body_grams) / float(len(new_grams))


# CCG 五要素的固定标签：所有节点都一样，属**模板骨架而非内容**。
# 不剥离它们，任何两条记忆都会因共享 `# 功能名：`/`# 生效条件：` 而虚高重复度
# （实测：两条毫不相关的记忆 dup≈0.33，全部来自模板）。故重复检测只看"值"。
_TEMPLATE_LABELS = ("功能名", "生效条件", "子功能", "执行", "验证方式", "不适用条件")


# 生效条件：content 为 None 或假值时按 "" 处理，结果为空串；否则逐行剥离 "#" 与 _TEMPLATE_LABELS 标签后以 "" 直接拼接。
def payload(content):
    """剥离 CCG 固定标签后的**内容骨架**（保留字段值，丢弃字段名与标记）。"""
    out = []
    for line in (content or "").splitlines():
        s = line.strip()
        if s.startswith("#"):
            s = s.lstrip("#").strip()
            for lab in _TEMPLATE_LABELS:
                if s.startswith(lab):
                    s = s[len(lab):].lstrip("：: ").strip()
                    break
        if s:
            out.append(s)
    return "".join(out)


# 生效条件：node_id 为真值且 cg.index 的 nodes 中已有该 id 时返回该 id（本次写入是覆写既有同 id 节点）；node_id 为空、cg 无 index 或取 index 抛异常、id 不在索引中时返回 None。
def prior_node(cg, node_id):
    """本次写入是否为**覆写既有同 id 节点**——返回既有 id 或 None（存在性判据单点）。

    P-9b(a) 根因（探针实测）：同 id 覆写时 `redundancy(exclude=node_id)` 自排除
    （「不与自身比正文」本身正确），但该层若只此一个节点 ⇒ `compared=0`、
    `duplicate_with=None`、`duplicate_ratio=0.0`——裁决里「覆写」与「全新写入」
    **完全不可区分**（审计面全 null，静默洞）。存在性判据收敛在此一处：`assess`
    的 entropy 标注与直写路径的返回体共用，不各写一份。

    边界（如实）：判据读 `cg.index`，与 `redundancy` 同一数据面（同代际假设）；
    index 陈旧时最坏是漏标一次覆写提示，不影响任何落盘行为。
    """
    if not node_id:
        return None
    try:
        nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    except Exception:
        return None
    return node_id if node_id in nodes else None


# 生效条件：node_id 为真值且 cg.get(node_id) 返回真值时返回覆盖度（_coverage(bigrams(payload(content)), bigrams(payload(既有正文)))，1.0＝逐字同构的重写）；node_id 为空、节点取不到、既有正文为空时返回 None。
def self_coverage(cg, node_id, content):
    """「本次正文 vs 同 id 既有正文」的覆盖度（1.0 = 内容等同的重写）。

    与 `redundancy` 共用同一套骨架（payload/bigrams/_coverage），不另写一份
    重复度算法；差别只在比较对象是**自己**（故不适用 exclude）。用途：同 id
    覆写时回答「这次是空写还是真改了」（P-9b(a) 提示的主体信息）。
    """
    try:
        node = cg.get(node_id)
    except Exception:
        node = None
    if not node:
        return None
    body = bigrams(payload(node.get("content") or ""))
    if not body:
        return None
    return round(_coverage(bigrams(payload(content)), body), 4)


# 生效条件：content 经 payload/bigrams 得空集合时直接返回零值 best（max=0.0、with=None、compared=0）；否则遍历 cg.index 的 nodes，跳过 nid==exclude，layer 为真值时只比较 str(layer 字段 or "")==layer 的节点，cg.get(nid) 抛异常/返回假值、或该节点 content 的 bigrams 为空则跳过，每计入一个节点后若 n>=limit 立即 break（故 limit 为 0 或负数时只比较首项即停），返回覆盖度最大者 best（无覆盖度提升时不更新 with/jaccard，compared 为实际计入数）。
def redundancy(cg, content, layer="contextual", exclude=None, limit=MAX_COMPARE):
    """Q1 重复？——新内容被既有同层节点覆盖的最大比例。"""
    new = bigrams(payload(content))
    best = {"max": 0.0, "with": None, "jaccard": 0.0, "compared": 0}
    if not new:
        return best
    nodes = ((getattr(cg, "index", None) or {}).get("nodes") or {})
    n = 0
    for nid in list(nodes.keys()):
        if nid == exclude:
            continue
        if layer and str(nodes[nid].get("layer") or "") != layer:
            continue
        try:
            node = cg.get(nid)
        except Exception:
            node = None
        if not node:
            continue
        body = bigrams(payload(node.get("content") or ""))
        if not body:
            continue
        n += 1
        cov = _coverage(new, body)
        if cov > best["max"]:
            best = {"max": cov, "with": nid,
                    "jaccard": len(new & body) / float(len(new | body) or 1),
                    "compared": n}
        if n >= limit:
            break
    best["compared"] = n
    return best


# 生效条件：dup 必填并转 float；dup=0 时 p 取 EPS，返回 -log2(EPS) 这一有限大值；dup>=1 时返回 0.0。
def self_information(dup):
    """Q3 的自信息代理：I = -log2(min(1, dup + ε))，单位 bit。

    注意：dup 是「被既有记忆覆盖率」的估计，不是概率模型的真实 P(x)，
    因此这是**结构类比的代理量**（见模块 docstring 的诚实边界）。
    """
    p = min(1.0, max(0.0, float(dup)) + EPS)
    return -math.log(p, 2.0)


# 生效条件：hint 非 None 且可转 float（含 hint=0）时返回 from="hint" 的裁剪分数；否则用 novelty、SOURCE_WEIGHT.get(kind, SOURCE_WEIGHT["unknown"])、len(content)/200 三因子启发式。
def importance_score(hint, novelty, kind, content):
    """Q2 重要？——显式 hint 优先，否则启发式（对齐 longterm_snapshot 四因子简化版）。"""
    if hint is not None:
        try:
            return {"score": round(max(0.0, min(1.0, float(hint))), 4),
                    "from": "hint"}
        except (TypeError, ValueError):
            pass
    lf = min(1.0, len(content or "") / 200.0)
    s = (0.5 * novelty
         + 0.3 * SOURCE_WEIGHT.get(kind, SOURCE_WEIGHT["unknown"])
         + 0.2 * lf)
    return {"score": round(max(0.0, min(1.0, s)), 4), "from": "heuristic"}


# 生效条件：以 source_kind(role,verification_basis) 的 kind 与 redundancy(cg,content,layer=layer,exclude=node_id) 的 red["max"] 为输入，按 if/elif 顺序取首个命中分支——imp["score"]≥PROTECT_IMPORTANCE→"ACCEPT"；否则 kind=="internal_deterministic" 且 red["max"]≥DUP_DROP→"DROP"；否则 red["max"]≥DUP_MERGE→"MERGE"；否则 red["max"]≥DUP_DROP 且 imp["score"]<IMPORTANCE_MIN→"DEFER"；否则 imp["score"]≥IMPORTANCE_MIN→"ACCEPT"；否则 novelty≥NOVELTY_MIN→"ACCEPT"；否则→"DEFER"。返回体附带 P-9b 可见性字段：entropy.overwrite_of / entropy.overwrite_ratio（同 id 覆写时非 null）、dedup_skipped（**仅 PROTECT 分支**非 null，标注「因保护优先未走去重」+ 去重判据读数）——两者都不改 verdict、不改落盘行为。
def assess(cg, content, layer="contextual", role=None, verification_basis=None,
           importance_hint=None, node_id=None):
    """三问 → 四态裁决。返回完整判据（可审计，不只给结论）。

    P-9b（2026-09-30）：本函数此前有两处**静默洞**（探针实测），都只补可见性、
    不动裁决语义：
      (a) 同 id 覆写：`redundancy(exclude=node_id)` 自排除 ⇒ 该层只此一节点时
          compared=0、dup 字段全 null，「覆写」与「全新写入」不可区分。处置：
          entropy 增 `overwrite_of`（既有 id）+ `overwrite_ratio`（新正文对既有
          正文的覆盖度，1.0=空写）——判据单点在 `prior_node`/`self_coverage`。
      (b) importance≥PROTECT_IMPORTANCE 的保护优先分支**排在冗余判定之前** ⇒
          高重要度的近重复内容直接 ACCEPT，绕过 MERGE/DROP 而审计面只剩一句
          「触发不可遗忘保护」。处置：该分支返回 `dedup_skipped`
          （reason=protect_importance + duplicate_with/duplicate_ratio/compared +
          overwrite_of），并在 reason 文案里显式写出「因保护优先未走去重」。
          **为何不把 PROTECT 挪到冗余判定之后**（依据）：① 该分支语义是「不可
          遗忘保护」（PROTECT_IMPORTANCE 与 writelimit.py 模块头注 :9-12 的
          「importance_hint≥0.7 保护优先」是跨模块同一口径，且 writelimit 是
          文档化设计不许动）；挪位后高重要度内容会被 DROP（内部确定性来源）或
          MERGE 并入低重要度节点，**削弱的正是保护本身**，且造成两模块对同一
          阈值的语义分叉；② DROP 分支的伤害（重要内容被丢弃）不可逆，MERGE 会把
          关键正文并入他节点、检索归属漂移——风险高于收益；③ 缺陷本体是「绕过
          去重而不可见」而非「保护存在」，标注即可消除静默且零回归面
          （test_p9_forget_protect.py 的「importance_hint≥0.7→ACCEPT」逐字不变）。
    """
    kind = source_kind(role, verification_basis)
    red = redundancy(cg, content, layer=layer, exclude=node_id)
    novelty = round(1.0 - red["max"], 4)
    bits = round(self_information(red["max"]), 4)
    imp = importance_score(importance_hint, novelty, kind, content)
    # P-9b(a)：同 id 覆写的存在性/覆盖度（不与自身比的 redundancy 之外的另一读法）
    prior = prior_node(cg, node_id)
    entropy = {
        "source_kind": kind,
        "novelty": novelty,
        "self_information_bits": bits,
        "normalized": round(min(1.0, bits / MAX_BITS), 4),
        "duplicate_with": red["with"],
        "duplicate_ratio": round(red["max"], 4),
        "compared": red["compared"],
        # 非 null = 本次是覆写既有同 id 节点（原先此处无法与全新写入区分）
        "overwrite_of": prior,
        "overwrite_ratio": (self_coverage(cg, prior, content)
                            if prior is not None else None),
    }

    dedup_skipped = None
    if imp["score"] >= PROTECT_IMPORTANCE:
        # P-9b(b)：保护优先分支先于冗余判定——近重复/覆写时不静默，给出去重读数
        due = []
        if prior is not None:
            due.append("覆写既有同 id 节点 %s（正文覆盖度 %s）"
                       % (prior, "—" if entropy["overwrite_ratio"] is None
                          else "%.2f" % entropy["overwrite_ratio"]))
        if red["with"] and red["max"] >= DUP_MERGE:
            due.append("与 %s 重复度 %.2f≥%.2f（够 MERGE 阈值）"
                       % (red["with"], red["max"], DUP_MERGE))
        verdict, why = "ACCEPT", (f"重要度 {imp['score']:.2f}≥{PROTECT_IMPORTANCE}"
                                 f"（触发不可遗忘保护）")
        dedup_skipped = {
            "reason": "protect_importance",
            "detail": ("保护优先分支排在冗余判定之前：本次未走 MERGE/DROP"
                       + ("（" + "；".join(due) + "）" if due else
                          "（重复度 %.2f<%.2f 且非覆写，无近重复）"
                          % (red["max"], DUP_MERGE))),
            "duplicate_with": red["with"] if red["max"] >= DUP_MERGE else None,
            "duplicate_ratio": round(red["max"], 4),
            "compared": red["compared"],
            "overwrite_of": prior,
        }
        if due:
            why += "；⚠ 因保护优先未走去重（" + "；".join(due) + "）"
    elif kind == "internal_deterministic" and red["max"] >= DUP_DROP:
        verdict, why = "DROP", (f"确定性内部产生且冗余 {red['max']:.2f}≥{DUP_DROP}"
                               f"（低熵噪音，不编码）")
    elif red["max"] >= DUP_MERGE:
        verdict, why = "MERGE", (f"重复度 {red['max']:.2f}≥{DUP_MERGE}"
                                f"（并入 {red['with']}，强化既有）")
    elif red["max"] >= DUP_DROP and imp["score"] < IMPORTANCE_MIN:
        verdict, why = "DEFER", (f"半重复 {red['max']:.2f}∈[{DUP_DROP},{DUP_MERGE})"
                                f" 且重要度 {imp['score']:.2f}<{IMPORTANCE_MIN}"
                                f"（待定复核）")
    elif imp["score"] >= IMPORTANCE_MIN:
        verdict, why = "ACCEPT", f"重要度 {imp['score']:.2f}≥{IMPORTANCE_MIN}"
    elif novelty >= NOVELTY_MIN:
        verdict, why = "ACCEPT", f"新信息 {novelty:.2f}≥{NOVELTY_MIN}"
    else:
        verdict, why = "DEFER", "重要度与新信息均不足判据（待定）"

    return {"verdict": verdict, "reason": why, "redundancy": red,
            "importance": imp, "entropy": entropy,
            # P-9b(b) 可见性字段：仅 PROTECT 分支非 null（其余分支本来就去重/裁决）
            "dedup_skipped": dedup_skipped}


# ---------------------------------------------------------------- 落库动作

# 生效条件：cg 与 rec 必填；append_jsonl 写 cg.root/LOG_FILE 抛任意异常时被吞掉，仍返回 rec。
def log(cg, rec):
    """裁决留痕（append-only）。DROP/DEFER 也留痕——否则遗忘变黑箱。"""
    try:
        append_jsonl(os.path.join(cg.root, LOG_FILE), rec)
    except Exception:
        pass
    return rec


# 生效条件：body 与 content 必传（None 按空串）；把 content 逐行空白归一去重、剔除已出现在 body 中的行；delta 为空（零新增信息）时返回 (None, None, None)，否则返回 (追加后的正文, 追加行, 行号)。
def aggregate_line(body, content, stamp=None):
    """MERGE 聚合行（**单点**）：新正文里「目标正文还没有的」行 → 追加一行。

    B3（2026-09-30）根因：近重复合并（`forgetting.reinforce`，MERGE）与同构
    聚合（`writelimit.converge_into`，CONVERGE）都只改 frontmatter
    （importance/merge_count），新正文**逐字节丢弃**——「近重复但关键值不同」
    的第二次写入在库里 0 命中（探针实测：新值 9595 全库 0 命中、节点未落盘）。
    本函数是「新正文怎么进目标正文」的**唯一实现点**：两处落库动作共用，
    第二处委托调用（硬约束：单点优先），不各自再写一份追加口径。

    与 `converge_into` 旧口径（`" ".join(content.split())[:80]`）的两点差别，
    均为**收窄信息损失**而非放宽判据：
      · 不截断——旧口径把新值丢在 80 字外即整体丢失（P-3 实测：端口 9090
        变体在库中 0 次落盘），而「新值必须在库里可检索」正是本修的目标；
      · 只追加 delta——旧口径无条件追加，逐字重复的再写也会让目标正文无限
        增长。按「归一化行是否已出现在目标正文（含已追加的聚合行）中」判，
        纯重复零追加（不增长），带新信息的变体各追加一次（新值原样落盘，
        可被 read/search 命中）。**幂等性靠子串判据**：聚合行自带
        `- 【聚合 …】` 前缀，故比对用的是「归一化后的整段目标正文」而非
        逐行集合——否则第二次同文再写会因前缀差异重复追加。
    """
    have = " ".join((body or "").split())
    delta, seen = [], set()
    for l in (content or "").splitlines():
        s = " ".join(l.split())
        if not s or s in seen or s in have:
            continue
        seen.add(s)
        delta.append(s)
    if not delta:
        return None, None, None
    stamp = stamp or time.strftime("%m-%d %H:%M", time.localtime())
    line = f"- 【{AGG_MARK} {stamp}】" + "；".join(delta)
    new_body = ((body or "") + "\n" if body else "") + line
    return new_body, line, len(new_body.splitlines())


# 生效条件：session 与 actor 均为假值（None/空串等）时返回 None 且不改 fm；否则把 {"session","actor","t"} 追加进 fm["merge_sources"]（只保留最近 MERGE_SOURCES_KEEP 条）并返回该条。
def note_source(fm, session=None, actor=None, t=None):
    """H3 归属并列（**单点**）：把「新写入方」的归属记进目标 frontmatter。

    跨会话合并的处置选择与依据（探针读数：合并判定完全不看会话——`redundancy`
    按同层全量比、`writelimit.check` 的键是 `f"{layer}:{role}"`，两处都无会话维；
    实测 B 会话的近重复被并入 A 会话节点，B 的内容与归属双双消失）：
      · **不动合并判定**（不按会话切分）。依据：同一事实在另一会话再次出现
        仍是「又一次见到」= 确认信号，正是冗余闸门的既有语义；按会话切分会让
        同一事实在每个会话各长一个节点，与「噪声丢掉、骨架留下」的目的相悖。
      · **把双方归属并列落 fm**：目标自己的 `fm.session` 原样保留，新写入方
        记进 `fm.merge_sources`（保序、有界）。召回侧据此可识别「这条记忆被
        哪些会话/主体确认过」——当前会话的新内容不再无名无姓地消失。
    """
    if not session and not actor:
        return None
    src = {"session": None if session is None else str(session),
           "actor": None if actor is None else str(actor),
           "t": float(t if t is not None else time.time())}
    rows = list(fm.get("merge_sources") or [])
    rows.append(src)
    fm["merge_sources"] = rows[-MERGE_SOURCES_KEEP:]
    return src


# 生效条件：cg 与 node_id 必传，content 为本次被丢弃的正文，target 为近重复目标，verdict 为 forgetting.assess 的判据字典；恒写一条 verdict=="DROP" 的留痕并返回「去向单」（含 trace_id / 全文或摘要 / 检索入口）；密级属 crypto.ENCRYPTED_LEVELS 时 dropped_content 为 None 且 content_redacted 为 True（明文不落留痕）。
def record_drop(cg, content, node_id, target=None, verdict=None, layer=None,
                sensitivity=None, session=None, actor=None):
    """DROP 去向留痕（**单点**，B3-④）：被丢的新正文「去哪了」。

    为什么需要它：`assess` 的 `:214` 分支（internal_deterministic 且
    dup≥DUP_DROP，0.60）**先于** MERGE 分支命中，于是「近重复但关键值不同」的
    确定性内部写入走 DROP，连既有节点都不强化——新正文只在日志里留一个
    「低熵噪音，不编码」，正文本身零去向（探针实测：全库 0 命中）。

    处置：**不追加进目标正文**（该分支的既有语义是「例行输出不该污染既有
    记忆」，不能靠追加把它变相强化成 MERGE），改为把新正文**全文**与去向目标
    一并落进 `_forgetting.jsonl`，返回单给出可检索的句柄（trace_id / 文件 /
    sha1）。密级为加密级时不落明文（与写面 `mdcg._check_sensitivity_landing`
    的「加密级却明文落盘」fail-closed 同口径）——只留摘要与长度，返回单显式
    声明这一处取舍，不假装全文可检索。
    """
    flat = " ".join((content or "").split())
    digest = hashlib.sha1(flat.encode("utf-8")).hexdigest()[:12] if flat else ""
    enc = bool(flat) and str(sensitivity or "").strip().lower() \
        in crypto.ENCRYPTED_LEVELS
    t = time.time()
    trace_id = f"drop-{node_id}-{int(t * 1000)}"
    log(cg, {"t": t, "node_id": node_id, "layer": layer, "verdict": "DROP",
             "reason": (verdict or {}).get("reason", ""),
             "importance": (verdict or {}).get("importance"),
             "entropy": (verdict or {}).get("entropy"),
             "duplicate_with": target, "actor": actor, "session": session,
             "trace_id": trace_id, "content_sha1": digest,
             "content_chars": len(flat),
             "dropped_content": None if enc else (flat or None),
             "content_redacted": enc})
    sink = {"verdict": "DROP", "duplicate_with": target, "trace_id": trace_id,
            "kept_in": LOG_FILE,
            "retrieval": (f"{LOG_FILE} 内 trace_id={trace_id}"
                          f"（forgetting_history 读回；节点未落盘，"
                          f"按 N229 读可见性过滤仅治理面可见）"),
            "content_sha1": digest, "content_chars": len(flat),
            "content_kept": bool(flat) and not enc}
    if enc:
        sink["redacted_reason"] = ("密级为加密级：明文不入留痕（与写面"
                                   "「加密级却明文落盘」fail-closed 同口径）")
    return sink


# 生效条件：cg 与 node_id 必填，delta 默认 0.05，content 默认 None（不传即与改动前逐位一致：只改 frontmatter、正文原样写回）；cg.get(node_id) 抛异常或返回假值时返回 None；随后以节点真层/敏感度过 protect.guard_overwrite（层闸 + 保护闸，override 为真时先快照 + 审计）；imp 跨过 PROTECT_IMPORTANCE 即写 protected；content 非 None 时按 forgetting.aggregate_line 把「目标正文没有的」行追加为聚合行（零新增信息则不追加），session/actor 非空时按 forgetting.note_source 并列记归属；写盘后同步内存索引条目并**标脏**（cg._dirty[node_id]=e，推进读缓存代际与索引增量日志）；返回体带 content_sink（新正文去向：节点/行/行号）与 source（归属）。
def reinforce(cg, node_id, delta=0.05, override=False, actor=None,
              content=None, session=None):
    """MERGE 的落库动作：不新增节点，把「又一次见到」折算成既有节点的强化。

    重要性 +delta，merge_count +1；一旦跨过 0.7 自动打上保护标记
    （对齐「importance 提升（保护：不可遗忘…且受保护标记）」）。

    B3（2026-09-30）：本函数此前**没有 content 槽**——MERGE 时新正文 100%
    丢弃（写回的是 `node.get("content")`，即既有正文），调用方手上正握着
    新正文却无处可传。现加 `content=None`（**缺省行为与改动前逐位一致**：
    不传即正文原样写回，既有调用零破坏）；MERGE 时按 `aggregate_line`
    （单点，与 `writelimit.converge_into` 共用）把新正文里目标还没有的行
    追加为聚合行，`merge_count` 口径不变。注意**不动 importance 之外的既有
    语义**：聚合行是「又一次见到 + 新值留痕」，不是新增节点、不改层、不改
    密级、不绕保护闸（`guard_overwrite` 仍在本函数内、写盘之前，见 :278）。

    H3（2026-09-30）：`session` 槽把「新写入方归属」并列记进目标
    frontmatter（`note_source`，单点）——跨会话合并时目标自己的
    `fm.session` 保留，新写入方记进 `fm.merge_sources`。

    C-1（2026-09-29）：写盘后**标脏**（`cg._dirty[node_id] = e`，对照
    `md_cg/mdcg.py` 的 update_tags / verify 直写分支先例）——不标脏时
    `_dirty.path_gen` 不推进，默认开（`MDCG_READ_CACHE=1`）的读缓存会把写盘前
    旧 fm 判新鲜，同进程「reinforce 后读」永久拿到旧 importance（FI-M03 实测）。

    N214（2026-09-28，同族未接线写点）：本函数此前**裸调 `cg._write_node`**
    覆写既有节点，两个入口（`mdcos.remember_gated` 的 MERGE 分支 :3380、
    `mdcos.maintain(action="prefeed", write=True)` 的 reinforce 分支 :2783）
    全程无 principal 层闸、无保护闸、无快照无审计——同一身份对**同层**的 `add` 被
    `AccessDenied`，而此路照样覆写（持 write 的 reflect 令牌以 `layer='self'`
    发 `mdcg_remember(gated=true)`：`writelimit.check` 因形参层≠contextual 放行、
    `assess` 按形参层比得重复度 1.0 → MERGE → 改写 self 层节点的
    importance/merge_count 并自动打保护位）。落盘前统一过
    `protect.guard_overwrite`（单点，对照 `MdCGSecure.add` 的层闸 + `MdCG.add`
    的保护闸），`override=True` 时先快照进 `_protected_history` 并写
    `_protected_audit.jsonl`。
    """
    try:
        node = cg.get(node_id)
    except Exception:
        node = None
    if not node:
        return None
    fm = node.get("frontmatter") or {}
    protect.guard_overwrite(cg, node_id, layer=fm.get("layer"),
                            sensitivity=fm.get("sensitivity"),
                            override=override, actor=actor)
    imp = min(1.0, float(fm.get("importance") or 0.5) + delta)
    fm["importance"] = imp
    fm["merge_count"] = int(fm.get("merge_count") or 0) + 1
    fm["last_merge_at"] = time.time()
    if imp >= PROTECT_IMPORTANCE:
        fm["protected"] = True
        fm["protection_reason"] = (f"importance={imp:.2f}≥{PROTECT_IMPORTANCE}"
                                   f"（重复强化）")
    # ② 显式状态机收口（2026-09-16）：MERGE 的语义是「又一次见到」= **重新激活**
    # 信号——已降权（demoted）/已定型（converged）的节点经状态机**逐级回升**到
    # active（archived→active 亦合法，归档节点被再次见到即恢复参与）；active 为
    # 幂等 no-op（不写字段、不留痕）。protected 只豁免**降级**，回升不受限。
    lifecycle.stamp(fm, "active", reason="MERGE 重复强化（回升）",
                    actor="forgetting:reinforce")
    # B3：新正文去向（content 缺省 None → new_body 为 None → 正文原样写回，
    # 与改动前逐位一致）。聚合行只补「目标还没有的」行，纯重复零追加。
    new_body, line, line_no = (None, None, None)
    if content is not None:
        new_body, line, line_no = aggregate_line(node.get("content"), content)
    # H3：归属并列（新写入方 → fm.merge_sources；目标自己的 fm.session 不动）
    source = note_source(fm, session=session, actor=actor)
    cg._write_node(node_id, os.path.join(cg.root, node["path"]),
                   fm, new_body if new_body is not None
                   else (node.get("content") or ""))
    e = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(node_id)
    if e is not None:
        e["importance"] = imp
        if fm.get(lifecycle.STATE_FIELD):
            e[lifecycle.STATE_FIELD] = fm[lifecycle.STATE_FIELD]
        if fm.get("protected"):
            e["protected"] = True
            e["protection_reason"] = fm["protection_reason"]
        # H3 索引镜像（2026-09-30）：merge_sources 同款镜像（对照组
        # `writelimit.converge_into` :257-258 的 `entry["merge_sources"]`）。
        # 此前本段只同步 importance / lifecycle state / protected，盘面 fm 已
        # 有新写入方归属而同进程索引条目读到 None，直到索引重载——与
        # 「写盘后标脏、同进程读到新值」的既有纪律（C-1 / N133 同族，见下方
        # 标脏注释）不一致：CONVERGE 落点（converge_into）与 MERGE 落点
        # （reinforce）的读面行为必须同口径。
        if fm.get("merge_sources"):
            e["merge_sources"] = fm["merge_sources"]
        # 标脏（N133 修复，对照先例 mdcg.py 的 update_tags / verify 直写分支
        # `self._dirty[node_id] = e`）：只改内存 entry 时 path_gen 不推进，
        # 读缓存（默认开，MDCG_READ_CACHE=1）按 `_fresh` 把写盘前的旧 fm 判
        # 为新鲜——同进程「写后读」永久拿到旧 importance（FI-M03 实测）。
        # 标脏同时让本写进 `_dirty → flush → _index_log` 重放（重启后索引
        # 与盘面不再漂移）。**不把标脏下沉进 `_write_node`**：该函数另有
        # 「只对账索引、不落盘」的调用方（backfill 对账支路等），下沉会让
        # 它们凭空产生一次写入代际与自重载；此处按既有 48 处显式标脏同款
        # 补，口径与 `_sync_edge_entry` 一致。
        _dirty = getattr(cg, "_dirty", None)
        if isinstance(_dirty, dict):
            _dirty[node_id] = e
    return {"node_id": node_id, "importance": imp,
            "merge_count": fm["merge_count"], "protected": bool(fm.get("protected")),
            # 新正文去向（②）：写进了哪个节点/哪一行——调用方不必猜。
            "content_sink": {
                "node_id": node_id,
                "action": ("appended" if line else
                           ("already_covered" if content is not None
                            else "not_provided")),
                "line": line, "line_no": line_no,
                "chars": len(new_body if new_body is not None
                             else (node.get("content") or ""))},
            "source": source}


# 生效条件：cg 必填，limit 默认 100；日志路径不存在时返回 []；否则逐行 json.loads 后按行所属 node_id 做读可见性过滤（security.node_visible 为假的行整条剔除），再返回 out[-limit:]（limit=0 时 -0 退化为 out[0:] 即全量）。
def history(cg, limit=100):
    """读取遗忘留痕（最近 limit 条，**按节点读可见性过滤**）。

    N229（2026-09-28）：此前逐行 json.loads 原文返回（actor/verdict/reason/
    importance/layer/duplicate_with…），零可见性、零归属过滤 ⇒ 任何持 read op
    的身份（含无令牌 guest 经 `mdcg_forgetting_history`）读走全库他人的写入
    闸留痕，并可借 `duplicate_with` 枚举 private 目标 id。口径与库读面统一：
    逐行按 `security.node_visible`（跨层单点）判定行所属节点对本身份是否可见，
    不可见/已删（索引无条目）→ 整条不出；设计者豁免（治理面本职）。

    如实标注：行内 `duplicate_with` 指向的**另一**节点不做二次判定（那是
    「去重目标」，与行所属节点不同源）——本轮按行所属节点收口，见报告残留。
    """
    p = os.path.join(cg.root, LOG_FILE)
    if not os.path.exists(p):
        return []
    out = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        r = __import__("json").loads(line)
                    except Exception:
                        continue
                    if not _security.node_visible(cg, (r or {}).get("node_id")):
                        continue
                    out.append(r)
    except Exception:
        return []
    return out[-limit:]


# 生效条件：cg 必填；日志路径不存在返回 {"total": 0, "by_verdict": {}}；否则流式累计行数与 verdict 分布。
def summary(cg):
    """遗忘留痕聚合（流式，不把全量日志读进内存）：总数 + 四态分布。"""
    p = os.path.join(cg.root, LOG_FILE)
    counts, total = {}, 0
    if not os.path.exists(p):
        return {"total": 0, "by_verdict": {}}
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    v = json.loads(line).get("verdict") or "?"
                except Exception:
                    continue
                counts[v] = counts.get(v, 0) + 1
                total += 1
    except Exception:
        return {"total": total, "by_verdict": counts}
    return {"total": total, "by_verdict": counts}


# ==========================================================================
# 长期记忆快照（maintain.longterm）
# ==========================================================================
#
# 目标：评估后**分层落盘**，形成可回溯的历史断面（哪一刻哪些记忆处于长期态）。
# 与上面写入侧闸门的分工：闸门管「这条要不要记」，快照管「记住的现在稳稳站在哪一层」。
#
# 性能纪律：全部判据来自**索引快照**（免读节点文件），流式写 JSONL，不全量载入内存。
# 4500+ 节点下 dry-run 为 O(N) 纯内存计算；apply 为顺序写文件。

MAINTAIN_LOG = "_maintain.jsonl"
LONGTERM_DIR = "_longterm"
LONGTERM_KEEP = 10                 # 保留最近 N 个断面（多了自动清理）
TIERS = ("longterm", "working", "candidate")
# 白箱可 ACCEPT 的基底档位；文科来源一致性档同样认账（否则「白箱判定已通过、
# 长期分层却视作未验证」自相矛盾）。
VERIFIED_BASES = ("formal_proof", "compiler", "test", "textbook", "public_kb")
TIER_WORKING = 0.40


# 生效条件：e 必填；protected 为真、importance>=PROTECT_IMPORTANCE、或 evidence_count>=3 且 verification_basis 在 VERIFIED_BASES → "longterm"；importance>=TIER_WORKING 或 vb 在 VERIFIED_BASES → "working"；否则 "candidate"。
def _tier_of(e: dict) -> str:
    """索引快照 → 分层：longterm（长期）/ working（工作）/ candidate（候选待评估）。"""
    imp = float(e.get("importance", 0.5) or 0.5)
    vb = e.get("verification_basis")
    ev = int(e.get("evidence_count", 0) or 0)
    if e.get("protected") or imp >= PROTECT_IMPORTANCE or (ev >= 3 and vb in VERIFIED_BASES):
        return "longterm"
    if imp >= TIER_WORKING or vb in VERIFIED_BASES:
        return "working"
    return "candidate"


# 生效条件：e 必填；e["edges"] 为假值（缺失/空列表）且 e["subgraph"] 为假值时返回 True，否则 False。
def _is_island(e: dict) -> bool:
    """无边孤岛：既无出边也无子图声明（夜间整理的首要候选）。"""
    return (not (e.get("edges") or [])) and (not e.get("subgraph"))


# 生效条件：cg 必填且提供 cg.root，恒返回 os.path.join(cg.root, LONGTERM_DIR)。
def longterm_dir(cg) -> str:
    return os.path.join(cg.root, LONGTERM_DIR)


# 生效条件：cg 必填，恒返回 longterm_dir(cg) 下的 "current.json" 路径。
def current_path(cg) -> str:
    return os.path.join(longterm_dir(cg), "current.json")


# 生效条件：apply 为真且由 cg.index 的 nodes（layer 为假值时不过滤、为真时仅取 layer 字段相等者，max_rows 为真值时先取 ids[:int(max_rows)]）算出的 snapshot_id 与 current.json 所记 snapshot_id 不同或其记录的 path 文件不存在（same 为假）时，才写断面文件、原子更新 current 指针、执行 _prune 并追加维护日志；apply 为假时只返回 dry_run=True 的统计（out 与 force 在源码中未被引用）。
def longterm_assess(cg, apply=False, out=None, layer=None, keep=LONGTERM_KEEP,
                    max_rows=None, force=False, actor="maintain"):
    """评估后分层落盘：生成一个可回溯的长期记忆断面。

    apply=False（默认）只出报表；apply=True 写 `_longterm/<ts>.jsonl` 并更新
    `current.json` 指针。幂等：断面内容相同则跳过重写（除非 force=True）。
    """
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    ids = sorted(nid for nid, e in list(nodes.items())
                 if not layer or e.get("layer") == layer)
    if max_rows:
        ids = ids[:int(max_rows)]
    tiers, by_layer, islands, digest = {}, {}, 0, hashlib.sha1()
    t0 = time.time()
    total = len(ids)
    for nid in ids:
        e = nodes.get(nid) or {}
        t = _tier_of(e)
        tiers[t] = tiers.get(t, 0) + 1
        lay = e.get("layer") or "?"
        bl = by_layer.setdefault(lay, {k: 0 for k in TIERS})
        bl[t] += 1
        if _is_island(e):
            islands += 1
        digest.update(f"{nid}:{e.get('importance')}:{t};".encode("utf-8"))
    snapshot_id = digest.hexdigest()[:12]
    ts = time.strftime("%Y%m%d-%H%M%S")
    rel = f"{LONGTERM_DIR}/{ts}-{snapshot_id}.jsonl"
    path = os.path.join(cg.root, rel)
    cur = None
    try:
        with open(current_path(cg), encoding="utf-8") as f:
            cur = json.load(f)
    except (OSError, ValueError):
        cur = None
    same = bool(cur and cur.get("snapshot_id") == snapshot_id
                and os.path.exists(os.path.join(cg.root, cur.get("path") or "")))
    written, pruned = 0, []
    if apply and not same:
        d = longterm_dir(cg)
        os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for nid in ids:
                e = nodes.get(nid) or {}
                row = {"t": time.time(), "id": nid, "layer": e.get("layer"),
                       "importance": e.get("importance"),
                       "tier": _tier_of(e),
                       "verification_basis": e.get("verification_basis"),
                       "evidence_count": e.get("evidence_count", 0),
                       "edges": len(e.get("edges") or []),
                       "island": _is_island(e),
                       "content_hash": e.get("content_hash")}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
        publish(tmp, path)
        atomic_write(current_path(cg), json.dumps(
            {"snapshot_id": snapshot_id, "ts": time.time(), "path": rel,
             "total": total, "tiers": tiers, "by_layer": by_layer,
             "islands": islands}, ensure_ascii=False))
        pruned = _prune(cg, keep)
        append_jsonl(os.path.join(cg.root, MAINTAIN_LOG), {
            "t": time.time(), "action": "longterm", "snapshot_id": snapshot_id,
            "path": rel, "total": total, "tiers": tiers, "actor": actor})
    return {
        "ok": True, "action": "longterm", "dry_run": not apply,
        "snapshot_id": snapshot_id, "path": rel, "same_as_current": same,
        "total": total, "tiers": tiers, "by_layer": by_layer,
        "islands": islands, "written": written, "pruned": pruned,
        "elapsed_ms": int((time.time() - t0) * 1000), "log": MAINTAIN_LOG,
        "note": ("dry-run：未写盘" if not apply else
                 (f"断面与 current 相同，跳过重写（id={snapshot_id}）" if same
                  else f"已写断面 {rel}（{written} 行）")),
    }


# 生效条件：cg 与 keep 必填；keep<=0 时不删除任何断面返回 []；否则删除除最近 keep 个 .jsonl 外的旧断面。
def _prune(cg, keep):
    """只保留最近 keep 个断面文件（按文件名时间前缀排序）。"""
    d = longterm_dir(cg)
    try:
        files = sorted(x for x in os.listdir(d) if x.endswith(".jsonl"))
    except OSError:
        return []
    removed = []
    for x in files[:-int(keep)] if int(keep) > 0 else []:
        try:
            os.remove(os.path.join(d, x))
            removed.append(x)
        except OSError:
            pass
    return removed


# 生效条件：cg 必填，limit 默认 20；目录不可读返回 []；否则新的在前逐个 append，因先 append 后判 len(out)>=limit，limit=0 时仍返回 1 条快照。
def longterm_list(cg, limit=20):
    """列出历史断面（新的在前）：{snapshot_id, path, ts, total, tiers}。"""
    d = longterm_dir(cg)
    out = []
    try:
        for x in sorted(os.listdir(d), reverse=True):
            if not x.endswith(".jsonl"):
                continue
            p = os.path.join(d, x)
            out.append({"file": x, "path": f"{LONGTERM_DIR}/{x}",
                        "bytes": os.path.getsize(p)})
            if len(out) >= int(limit):
                break
    except OSError:
        return []
    cur = None
    try:
        with open(current_path(cg), encoding="utf-8") as f:
            cur = json.load(f)
    except (OSError, ValueError):
        cur = None
    return {"current": cur, "snapshots": out}


# 生效条件：longterm_dir(cg) 不可列出（OSError）时返回 {"ok":False,"error":"no_snapshot"}；否则在倒序文件名中取首个满足 snapshot_id 为 None 或为其子串的 .jsonl（snapshot_id="" 与任意文件名匹配），无匹配返回 {"ok":False,"error":"snapshot_not_found"}；命中则逐行聚合该文件（空行与 json.loads 抛 ValueError 的行跳过），返回 file/total/tiers/by_layer/islands。
def longterm_show(cg, snapshot_id=None):
    """读取某个断面的分层统计（不载全量行，只聚合）。"""
    d = longterm_dir(cg)
    target = None
    try:
        files = sorted(x for x in os.listdir(d) if x.endswith(".jsonl"))
    except OSError:
        return {"ok": False, "error": "no_snapshot"}
    for x in reversed(files):
        if snapshot_id is None or snapshot_id in x:
            target = x
            break
    if not target:
        return {"ok": False, "error": "snapshot_not_found", "snapshot_id": snapshot_id}
    tiers, by_layer, islands, n = {}, {}, 0, 0
    with open(os.path.join(d, target), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            n += 1
            t = r.get("tier") or "?"
            tiers[t] = tiers.get(t, 0) + 1
            lay = r.get("layer") or "?"
            by_layer.setdefault(lay, {k: 0 for k in TIERS})
            by_layer[lay][t] = by_layer[lay].get(t, 0) + 1
            if r.get("island"):
                islands += 1
    return {"ok": True, "file": target, "total": n, "tiers": tiers,
            "by_layer": by_layer, "islands": islands}


# ==========================================================================
# 海马体前馈（maintain.prefeed）
# ==========================================================================
#
# 写入**之前**的新奇检测：重复项并入既有（MERGE），而非新增；无关噪音丢弃；
# 有歧义的半重复留痕待复核。这是「写入侧前置」的落库动作，比夜间整理更早一步。

# 生效条件：cg 与 content 必填；恒经 assess 得四态并映射 decision（ACCEPT→write 等），落留痕后返回 ok=True，不写任何节点。
def prefeed(cg, content, layer="contextual", role=None, verification_basis=None,
            importance_hint=None, node_id=None):
    """前馈裁决（不写盘）：返回四态 + 判据，并留痕 `_forgetting.jsonl`。

    落库由调用方按 verdict 执行（ACCEPT 新增 / MERGE 强化 / DROP|DEFER 不写），
    使「裁决」与「落库」解耦——便于 dry-run 预演与单测。
    """
    vd = assess(cg, content, layer=layer, role=role,
                verification_basis=verification_basis,
                importance_hint=importance_hint, node_id=node_id)
    decision = {"ACCEPT": "write", "MERGE": "reinforce",
                "DROP": "discard", "DEFER": "defer"}.get(vd["verdict"], "defer")
    rec = {"kind": "prefeed", "layer": layer,
           "node_id": node_id or _prefeed_id(content),
           "verdict": vd["verdict"], "decision": decision,
           "reason": vd["reason"], "duplicate_with": vd["redundancy"]["with"],
           "duplicate_ratio": vd["redundancy"]["max"],
           "novelty": vd["entropy"]["novelty"],
           "self_information_bits": vd["entropy"]["self_information_bits"],
           "actor": getattr(cg, "actor", "unknown"), "t": time.time()}
    log(cg, rec)
    return {"ok": True, "action": "prefeed", **rec}


# 生效条件：content 为 None 或假值时按 "" 计算，恒返回 "pre_"+sha1(content).hexdigest()[:12]。
def _prefeed_id(content):
    return "pre_" + hashlib.sha1((content or "").encode("utf-8")).hexdigest()[:12]


# 生效条件：cg 必填，limit 默认 100；action 为假值（None/空串）时不过滤，真值只留该 action；返回 recs[-int(limit):]，limit=0 时退化为全量。
def maintain_history(cg, limit=100, action=None):
    """维护留痕（`_maintain.jsonl` 最近 limit 条），可按 action 过滤。"""
    recs = list(read_jsonl(os.path.join(cg.root, MAINTAIN_LOG)))
    if action:
        recs = [r for r in recs if r.get("action") == action]
    return recs[-int(limit):]