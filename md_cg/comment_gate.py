# -*- coding: utf-8 -*-
"""comment_gate · 代码符号「条件化注释」抽样闸门（计划四环之环二入口）。

**换对象不换机制**：复用 refine.py 的闸门范式（分层抽样 → 只读工单 → 人工裁决留痕 →
通过率放行），把处理对象从「node_ 前缀的记忆节点 CCG 字段缺口」换成
「code_ 前缀的代码符号注释缺口」。

候选判据（唯一、机械、不做语义猜测）：**代码节点且正文缺『生效条件』**。
依 Phase 0 契约，代码节点的生效条件只能来自源码人工声明——缺它即 BLINDSPOT
（缺证据），正是本闸门要治理的对象。落点按使用者裁决 q-0：写进源码、定义行紧邻的
井号注释（**两个窗口**，见 docs/mdcg/代码评审与条件化注释_契约_v0.1.md §三.2）。

本模块只做**候选池 / 工单 / 留痕 / 闸门**：不生成注释、不改任何节点。
生成与评审方式按 q-2（LLM 生成 + 人工抽检，复用 0.90 闸门）。

诚实边界（honest_limits 已随 SPEC 一并输出）：
· 分层抽样的**分配**沿用 refine.sample_ids 对 code_ 节点的口径（家族=大域），
  而非对候选池重新分配——故 sample_adequacy 会如实报出样本里的候选产出率；
  若产出率不足，应先扩大 n 或改用候选池重分配（已知待办，不在本片）。
"""
from __future__ import annotations

import json
import os
import time

from . import codeindex, nodefile, refine

#: 放行阈值**唯一真源在 refine**（不在此处再定义一份，防口径漂移）
GATE_MIN_PASS_RATE = refine.GATE_MIN_PASS_RATE
SAMPLE_N = refine.SAMPLE_N
#: 本闸门自己的抽样种子（与 refine 的 g6-sample-v1 分离，样本可各自复算）
SAMPLE_SEED = "comment-gate-v1"
#: 代码节点 id 前缀（见 codeindex.node_id = code_ + sha1 前 12 位）
PREFIX = "code_"
LOG_NAME = "_comment_gate.jsonl"

#: 人工核对清单（与工单逐项对应；对照 refine.SPEC.review_items 的同构位置）
REVIEW_ITEMS = (
    "生效条件是否为**功能前置条件**（何种输入/状态下正确），而非索引元条件",
    "条件可否被机械复核（有输入/状态判据；不是「常用条件默认省略」）",
    "落点是否为源码定义行紧邻的井号注释（两窗口之一），且不覆盖既有实现说明",
    "公开仓合规：过第 14 条「内容政策 + 隐私」双清单（补写内容随源码公开）",
)

SPEC = {
    "goal": "为代码符号补写功能级生效条件注释，使其在检索侧可判（不再因缺证据恒 BLINDSPOT）",
    "target": "code_ 前缀节点中正文缺『生效条件』者",
    "landing": "源码定义行紧邻的井号注释（leading/body 两窗口，物理序合并）",
    "review_items": list(REVIEW_ITEMS),
    "gate": {"min_pass_rate": GATE_MIN_PASS_RATE, "basis": "人工核对忠实比例",
             "rule": "低于阈值不得扩批"},
    "honest_limits": [
        "本闸门只覆盖已索引的代码节点；未索引的源码不在面内（先跑 index_code）",
        "分层分配沿用 code_ 节点口径而非候选池，样本候选产出率由 sample_adequacy 如实上报",
        "不生成注释、不改节点：生成与评审属另一环节（LLM 生成 + 人工抽检）",
    ],
}


# 生效条件：cg 传入后返回 os.path.join(cg.root, LOG_NAME)，即以 cg.root 与模块级常量 LOG_NAME 拼接的日志路径（cg 缺 root 属性时抛 AttributeError）。
def _log_path(cg) -> str:
    return os.path.join(cg.root, LOG_NAME)


# 生效条件：cg 与 nid 传入后，先看 str(nid) 是否以模块级常量 PREFIX 开头（不以则返回 False）；以 PREFIX 开头时取 cg.get(nid)（缺节点按空字典）的 content（假值按空串）经 nodefile.ccg_completeness 判断，若 "生效条件" 不在其 required_present 中则返回 True，否则 False。
def is_candidate(cg, nid) -> bool:
    """候选判据：代码节点且正文缺『生效条件』（机械判据，唯一）。"""
    if not str(nid).startswith(PREFIX):
        return False
    node = cg.get(nid) or {}
    comp = nodefile.ccg_completeness(node.get("content") or "")
    return "生效条件" not in comp["required_present"]


# 生效条件：cg 与 nid 传入后，从 cg.get(nid)（缺节点按空字典）的 frontmatter（假值按空字典）的 code_ref（假值按空字典）中按 path/name/kind/lineno/end/lang/precise 各键取 ref.get(k)（缺键为 None），返回含 code_ref 与固定 landing_rule、landing_note 字段的落点字典。
def _landing(cg, nid) -> dict:
    """工单条目 → 源码落点（坐标 + 落点规则），供补写者直接定位。"""
    node = cg.get(nid) or {}
    fm = node.get("frontmatter") or {}
    ref = fm.get("code_ref") or {}
    return {
        "code_ref": {k: ref.get(k) for k in
                     ("path", "name", "kind", "lineno", "end", "lang", "precise")},
        "landing_rule": "定义行紧邻上方连续井号注释（leading）或定义行紧邻下方、体首语句之前（body）",
        "landing_note": "两窗口按源码物理行序合并；靠前者胜出（契约 §三.2）",
    }


# 生效条件：cg 与 nid 传入后，取 cg.get(nid)（缺节点按空字典）的 content（假值按空串）算长度与 refine._sha(content)[:16] 作为 source_sha，并结合 refine._entry(cg, nid) 的 layer/tags（tags 假值按空列表）与 nodefile.CCG_MARKS 得出 ccg_missing，最后合并 _landing(cg, nid) 的返回构成工单条目字典。
def _item(cg, nid) -> dict:
    node = cg.get(nid) or {}
    content = node.get("content") or ""
    comp = nodefile.ccg_completeness(content)
    e = refine._entry(cg, nid)
    it = {
        "id": nid, "family": refine._family(cg, nid),
        "layer": e.get("layer"), "tags": list(e.get("tags") or []),
        "ccg_present": comp["present"],
        "ccg_missing": [m for m in nodefile.CCG_MARKS if m not in comp["present"]],
        "body_len": len(content),
        "source_sha": refine._sha(content)[:16],
    }
    it.update(_landing(cg, nid))
    return it


# 生效条件：ids 非空时返回经 is_candidate(cg, i) 过滤后的显式候选与 meta.source='explicit_ids'；ids 为空时经 refine._pool(cg, PREFIX) 扫描返回候选与 meta.source='scan'（含 skipped_protected）。
def candidates(cg, ids=None):
    """候选池（只读）→ (ids, meta)。"""
    if ids:
        pool = sorted({str(i) for i in ids if is_candidate(cg, i)})
        return pool, {"source": "explicit_ids", "pool": len(pool),
                      "requested": len(pool), "candidates": len(pool)}
    all_ids, protected = refine._pool(cg, PREFIX)
    cands = sorted(i for i in all_ids if is_candidate(cg, i))
    return cands, {"source": "scan", "prefix": PREFIX, "pool": len(all_ids),
                   "skipped_protected": protected, "candidates": len(cands)}


# 生效条件：seed 为假值（None/空串）时回落模块常量 SAMPLE_SEED，n 仅当为 None 时取 SAMPLE_N、否则 int(n)（n=0 保留 0）；ids 为真值时样本取全部候选，为假值（含空列表）时经 refine.sample_ids 抽样后按 is_candidate 过滤。
def plan(x, ids=None, n=None, seed=None) -> dict:
    """抽检工单（只读）：确定性样本 + 源码落点 + 口径声明 + 样本充分性。"""
    cg = refine._as_cg(x)
    seed = seed or SAMPLE_SEED
    n = SAMPLE_N if n is None else int(n)
    cands, cmeta = candidates(cg, ids=ids)
    if ids:
        sample = sorted(cands)
        smeta = {"pool": len(cands), "sampled": len(cands), "families": 0, "strata": {}}
    else:
        picked, smeta = refine.sample_ids(cg, n=n, seed=seed, prefix=PREFIX)
        sample = sorted(i for i in picked if is_candidate(cg, i))
    items = [_item(cg, nid) for nid in sample]
    strata = {}
    for it in items:
        s = strata.setdefault(it["family"], {"picked": 0, "missing_fields": {}})
        s["picked"] += 1
        for m in it["ccg_missing"]:
            s["missing_fields"][m] = s["missing_fields"].get(m, 0) + 1
    adequacy = {
        "sample_of_code_nodes": smeta.get("sampled", len(sample)),
        "candidates_in_sample": len(sample),
        "candidate_yield": round(len(sample) / float(smeta.get("sampled") or 1), 4),
        "note": "分配沿用 code_ 节点口径；产出率不足时应扩大 n 或改候选池重分配",
    }
    return {
        "root": cg.root, "dry_run": True, "readonly": True,
        "action": "comment_gate", "op": "maintain",
        "prefix": PREFIX, "seed": seed, "requested": n,
        "pool": cmeta, "sampled": len(items), "families": len(strata),
        "sample": sample, "sample_sha": refine._sha(*sample)[:16] if sample else "",
        "strata": strata, "items": items, "worklist": items,
        "spec": SPEC, "gate_rule": SPEC["gate"], "sample_adequacy": adequacy,
        "note": ("代码注释补写工单（只读）：供人工核对补写口径；"
                 "核对通过率未达阈值前不得扩批。本动作不改任何节点。"),
    }


# 生效条件：verdicts（None 按 []）中可哈希且属于 okv 字面集合（True/"1"/"true"/"True"/"pass"/"PASS"/"faithful"/"忠实"/"accept"/"ACCEPT"）的项计 passed，dict 项在 `v in okv` 处不可哈希先抛 TypeError，故源码里 v.get("verdict") 的计数分支不可达；reviewed 为 0 时 rate=0.0、expand_allowed=False、reason="no_review"，否则按 rate 与模块常量 GATE_MIN_PASS_RATE 比较给出 expand_allowed 与 reason。
def _stats(verdicts) -> dict:
    """通过率（只认忠实/pass/True），阈值取 refine 唯一真源。"""
    vs = list(verdicts or [])
    okv = {True, "1", "true", "True", "pass", "PASS", "faithful", "忠实",
           "accept", "ACCEPT"}
    passed = 0
    for v in vs:
        if v in okv:
            passed += 1
        elif isinstance(v, dict) and v.get("verdict") in okv:
            passed += 1
    reviewed = len(vs)
    rate = (passed / float(reviewed)) if reviewed else 0.0
    allowed = reviewed > 0 and rate >= GATE_MIN_PASS_RATE
    return {"reviewed": reviewed, "passed": passed, "pass_rate": round(rate, 4),
            "min_pass_rate": GATE_MIN_PASS_RATE, "expand_allowed": allowed,
            "reason": ("" if allowed else
                       ("no_review" if reviewed == 0 else
                        "rate %.4f < %.2f" % (rate, GATE_MIN_PASS_RATE)))}


# 生效条件：x 传入后经 refine._as_cg 得到 cg，若 cg.principal 非 None 则调用其 require_admin("maintain_comment_gate")；随后调用 plan(cg, ids=ids, n=n, seed=seed) 取工单、调用 _stats(verdicts) 取闸门统计，batch 假值回落 time.strftime("%Y%m%d-%H%M%S")，os.makedirs(cg.root, exist_ok=True) 后把含 batch/actor/seed/pool/sample/verdicts/gate 等字段的记录以追加方式写入 _log_path(cg)，并返回 ok=True 的留痕结果。
def apply(x, ids=None, n=None, seed=None, verdicts=None, actor=None, note=None,
          batch=None) -> dict:
    """落抽检批次 + 人工裁决到 _comment_gate.jsonl。**不改写任何节点**。

    权限**自持在模块内**（与 refine 同档）：apply 虽只落留痕，但它决定后续是否放行
    **扩批**，故按管理面处理。放在此处而非分发层，是为避免「分发面漏挂一道闸」
    这类易失同步的权限缺口。
    """
    cg = refine._as_cg(x)
    _principal = getattr(cg, "principal", None)
    if _principal is not None:
        _principal.require_admin("maintain_comment_gate")
    p = plan(cg, ids=ids, n=n, seed=seed)
    batch = batch or time.strftime("%Y%m%d-%H%M%S")
    stats = _stats(verdicts)
    rec = {"t": time.time(), "action": "comment_gate", "batch": batch, "actor": actor,
           "seed": p["seed"], "requested": p["requested"], "pool": p["pool"],
           "sampled": p["sampled"], "sample": p["sample"], "sample_sha": p["sample_sha"],
           "sample_adequacy": p["sample_adequacy"], "verdicts": list(verdicts or []),
           "gate": stats, "note": note}
    os.makedirs(cg.root, exist_ok=True)
    with open(_log_path(cg), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    return {"ok": True, "action": "comment_gate", "op": "maintain", "batch": batch,
            "root": cg.root, "sampled": p["sampled"], "gate": stats, "log": LOG_NAME,
            "note": ("抽检留痕已落盘（未改任何节点）；" +
                     ("闸门放行扩批" if stats["expand_allowed"] else
                      "闸门未放行：" + stats["reason"]))}


# 生效条件：x 传入后经 refine._as_cg 得到 cg，读取 _log_path(cg) 且仅当 os.path.exists 为真时逐行解析（空行跳过、json.loads 抛 ValueError 的行跳过），batch 为真时仅保留 batch 字段匹配的记录；recs 为空时返回 expand_allowed=False、reason="no_batch"，否则取 recs[-1] 的 verdicts 经 _stats 复算并返回。
def gate(x, batch=None) -> dict:
    """扩批闸门：读留痕复算通过率（不写盘）。"""
    cg = refine._as_cg(x)
    recs = []
    path = _log_path(cg)
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    continue
    if batch:
        recs = [r for r in recs if r.get("batch") == batch]
    if not recs:
        return {"ok": True, "action": "comment_gate_gate", "op": "maintain",
                "root": cg.root, "batch": batch, "batches": 0,
                "expand_allowed": False, "reason": "no_batch"}
    rec = recs[-1]
    stats = _stats(rec.get("verdicts"))
    return {"ok": True, "action": "comment_gate_gate", "op": "maintain",
            "root": cg.root, "batch": rec.get("batch"),
            "batches": len({r.get("batch") for r in recs}), **stats}


# 生效条件：root 传入后调用 codeindex.index_dir 扫描（max_files 假值回落 500，max_items 假值回落 2000），对返回 items 的每条 comments（假值按空列表）逐条先 str(c).lstrip("#").strip() 再判断是否以 "生效条件" 开头，全部不以该串开头的项进入候选并返回含 items/errors/stats/examined/candidates 的字典。
def candidates_from_sources(root, patterns=None, max_files=None, max_items=None,
                            skip_dirs=None):
    """**源级**候选枚举（不依赖认知图）：扫源码树，筛出注释里缺『生效条件』的符号。

    为什么需要它（2026-09-17 实测）：真实库 2934 条 code_ 节点的生效条件 **100% 是旧 render
    的合成值**，故**图内候选池为 0**；而「源码里哪些符号缺条件注释」是**源侧事实**，
    无须先重索引（重索引会让 2934 条同时失去条件、判 BLINDSPOT）。本入口绕开该一次性代价。

    判据唯一且机械：符号的 **井号注释窗口**（leading + body，见 codeindex）中不存在以
    『生效条件』开头的行；只认井号注释、不认 docstring——落点按 q-0 裁决。
    """
    items, errors, stats = codeindex.index_dir(
        root, patterns=patterns, max_files=int(max_files or 500),
        max_items=int(max_items or 2000), skip_dirs=skip_dirs)
    cands = []
    for it in items:
        has = any(str(c).lstrip("#").strip().startswith("生效条件")
                  for c in (it.get("comments") or []))
        if not has:
            cands.append(it)
    return {"root": root, "items": cands, "errors": errors, "stats": stats,
            "examined": len(items), "candidates": len(cands),
            "note": ("源级枚举：判据=井号注释窗口内无『生效条件』行；"
                     "不含图内节点状态，故不受存量渲染影响")}


# 生效条件：it 传入后取 it.get("path")（假值按空串）按 "/" 分割首段作为 family（首段为空则 family="."），并返回含 id=codeindex.node_id(it)、name/kind、code_ref（path/lineno/end/lang/precise 各缺省 None）、comments（假值按空列表逐项 str）、以及固定 landing_rule 与 landing_note 的字典。
def _landing_src(it) -> dict:
    return {"id": codeindex.node_id(it), "name": it.get("name"),
            "kind": it.get("kind"),
            "family": (it.get("path") or "").split("/")[0] or ".",
            "code_ref": {"path": it.get("path"), "lineno": it.get("lineno"),
                         "end": it.get("end"), "lang": it.get("lang"),
                         "precise": it.get("precise")},
            "comments": [str(c) for c in (it.get("comments") or [])],
            "landing_rule": ("定义行紧邻上方连续井号注释（leading）或定义行紧邻下方、"
                             "体首语句之前（body）"),
            "landing_note": "两窗口按源码物理行序合并；靠前者胜出（契约 §三.2）"}


# 生效条件：root 传入后调用 candidates_from_sources(root, patterns=patterns, skip_dirs=skip_dirs, max_files=max_files, max_items=max_items) 得候选，seed 假值回落 SAMPLE_SEED，n 为 None 时取 SAMPLE_N 否则 int(n)（0 保持 0），按 path 首段（空则 "."）分族与 sha(seed, node_id) 排序后做族间确定性轮转取至多 n 项，返回只读源级工单。
def plan_sources(root, n=None, seed=None, patterns=None, skip_dirs=None,
                 max_files=None, max_items=None) -> dict:
    """**源级**工单（只读）：确定性抽样 + 源码落点；不依赖认知图、不改任何节点。

    抽样口径：按大域（顶层目录）**确定性轮转**（族内按 sha(seed,id) 排序）。
    刻意**不复制** refine 的浮点最大余数分配——那是第二份实现，会引入漂移；
    源级候选列表是精确的（无「先抽样再过滤」的口径损失），轮转已给出跨族覆盖。
    """
    seed = seed or SAMPLE_SEED
    n = SAMPLE_N if n is None else int(n)
    got = candidates_from_sources(root, patterns=patterns, skip_dirs=skip_dirs,
                                 max_files=max_files, max_items=max_items)
    fams = {}
    for it in got["items"]:
        top = (it.get("path") or "").split("/")[0] or "."
        fams.setdefault(top, []).append(it)
    pools = {f: len(v) for f, v in fams.items()}
    names = sorted(fams)
    for f in names:
        fams[f].sort(key=lambda it: refine._sha(seed, codeindex.node_id(it)))
    picked = []
    while len(picked) < n and any(fams[f] for f in names):
        for f in names:
            if fams[f] and len(picked) < n:
                picked.append(fams[f].pop(0))
    work = [_landing_src(it) for it in picked]
    return {"root": root, "dry_run": True, "readonly": True, "mode": "source_level",
            "action": "comment_gate_sources", "op": "maintain",
            "seed": seed, "requested": n, "examined": got["examined"],
            "candidates": got["candidates"], "sampled": len(work),
            "families": len(pools), "strata": pools,
            "items": work, "worklist": work, "spec": SPEC,
            "scan_errors": list(got["errors"])[:10], "scan_stats": got["stats"],
            "gate_rule": SPEC["gate"],
            "note": ("源级工单（只读）：不依赖认知图、不改任何节点；"
                     "抽样为按大域的确定性轮转。")}


# 生效条件：x 与 action 传入后，action=="comment_gate" 时若 kw.get("apply") 为真则转 apply(x, ids,n,seed,verdicts,actor,note,batch)，否则转 plan(x, ids,n,seed)；action=="comment_gate_verdict" 时转 gate(x, batch)；action 为 "comment_gate_sources" 或 "comment_gate_source_plan" 时以 root=kw.get("root") or getattr(x,"root",None) or str(x) 转 plan_sources(...)；其余 action 抛 ValueError。
def run(x, action, **kw) -> dict:
    """maintain op 分派入口（与 backfill.run 同形，便于 mcp_server 侧并列分派）。"""
    if action == "comment_gate":
        if kw.get("apply"):
            return apply(x, ids=kw.get("ids"), n=kw.get("n"), seed=kw.get("seed"),
                         verdicts=kw.get("verdicts"), actor=kw.get("actor"),
                         note=kw.get("note"), batch=kw.get("batch"))
        return plan(x, ids=kw.get("ids"), n=kw.get("n"), seed=kw.get("seed"))
    if action == "comment_gate_verdict":
        return gate(x, batch=kw.get("batch"))
    if action in ("comment_gate_sources", "comment_gate_source_plan"):
        root = kw.get("root") or getattr(x, "root", None) or str(x)
        return plan_sources(root, n=kw.get("n"), seed=kw.get("seed"),
                            patterns=kw.get("patterns"), skip_dirs=kw.get("skip_dirs"))
    raise ValueError("未知 comment_gate action：%s（允许 comment_gate / "
                     "comment_gate_verdict）" % action)