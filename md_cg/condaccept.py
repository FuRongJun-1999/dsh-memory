# -*- coding: utf-8 -*-
"""work_done **形式完备闸**（condaccept）——只判形式完备，不判语义真值。

【正名，2026-10-18】本模块原名「验收器」，名不副实。核对自身实现可见：

    V1 条件空间齐全   结构检查（四个键非空）
    V2 证据可回溯     **正则匹配**（正文出现「依据：」「第X节」「实测」等标记）
    V4 同槽冲突       CCG 三要素指纹相同 + 前 200 字**字面**不同

三者全是**可判定的结构/词法/字符比较**，没有一个能做语义判定：它判不出
「换种说法还是同一条」（语义等价），也判不出「字面不像但意思冲突」（语义矛盾），
更判不出「这个出处在语义上真能支撑本条断言」。零 LLM 的正确边界就在这里。

故本模块对外语义**降级为形式完备闸**：
    ACCEPT  = 形式完备（字段齐、有出处标记、无字面同槽冲突）
    REJECT  = 形式不完备（并说明缺什么）
    ⇒ **ACCEPT 不等于内容为真**。内容真值由验证单元／外部基底裁决
      （架构 P3 的 verify，不由本模块承担）。

语义判定为什么不该塞进零 LLM：那是把「能不能判」与「判得对不对」混为一谈，
一旦下游把形式通过读成内容可信，造成的损害比不做校验更大。

理论依据（统一架构 v1.2 §2.4 / §10.1）：
    理论只承认可认知信息。形式完备闸不看文件是否存在、行数够不够，
    只看这条**断言**的形式是否齐备：条件空间声明了吗？有出处标记吗？字面同槽冲突吗？

判据分层（重要，与实现逐条对齐）：
    阻断判据（决定 ACCEPT/REJECT/BLINDSPOT）
        V1 条件空间四维齐全              缺 → REJECT（打回作者，非 DEFER）
        V2 见出处标记（evidence_ref/出处） 无标记 → REJECT
        V4 与已固化同槽信息冲突            冲突 → REJECT（负路由优先）
                                          判不了（检索失败/无 cg）→ **BLINDSPOT**
                                          不适用（无 CCG 槽位）→ 不阻断，标 na
    只读旁证（只记录，不阻断——写时检索代价与自指风险未解）
        V3 同一信息的多份投影是否一致
        V5 冗余投影是否已合并
        （注：V3/V5 仅对带 CCG 三要素的内容可执行；对普通文档/群聊/台账行不适用）

灰度（**缺省 enforce**）：
    MDCG_WORKDONE_ACCEPT = observe | enforce（缺省 enforce，非法值亦回落 enforce）
    observe：**恒返回 DEFER**（回到「未注入验收器」的旧行为），真实判定写进
             evidence/detail，只记读数不改变现网。
    enforce：返回真实判定——此时才真正放行或拦截。

注入方式（**内建注册，不依赖环境变量**，2026-10-18 修订）：
    由 md_cg/audit.py 尾部 register_verifier("work_done", verify_work_done, override=True)
    直接内建。此前依赖 MDCG_VERIFIER_MODULES，实测该 env 写入注册表后运行中的宿主
    及其子进程读不到，外部注入形同虚设。register() 仍保留，供需要显式注入的场景。
"""

import os
import re

__all__ = ["register", "verify_work_done", "evaluate", "mode",
           "FOUR_DIMS", "last_judgement", "reset_last"]

ENV_MODE = "MDCG_WORKDONE_ACCEPT"
MODES = ("observe", "enforce")
_WARNED_MODES = set()

FOUR_DIMS = ("observation_position", "observation_tool",
             "time_window", "existence_constraint")

#: 证据可回溯的形态：显式 evidence_ref/evidence 字段，或正文里的可定位出处
#: 证据可回溯的形态。首版正则过窄，把「第10.1节」这类带小数点的节号判成无证据
#: （实测：一条完全合规的样本被 V2 假拒绝）——判据过严与过松同样有害，故：
#:   ① 行首出处标记允许不带井号（正文里常写「依据：…」而非「# 依据：…」）
#:   ② 节号允许小数点（第10.1节 / 第 3.2.1 节）
_EVIDENCE_PATTERNS = (
    re.compile(r"^\s*(?:#\s*)?(?:位置|出处|依据|来源)\s*[：:]\s*\S", re.M),
    re.compile(r"(?:node_id|mem_|doc_|\bT\d+\b|第\s*[\d.]+\s*节|L\d+[-–]L?\d*|##)", re.M),
    re.compile(r"(?:实测|读数|日志|job_id|h_dsh)", re.M),
)

_LAST = {}


def mode():
    """当前档位。缺省 **enforce**（2026-10-18 使用者裁定「开」）。

    历史：首版缺省 observe（恒返回 DEFER、只记读数），是为了不动现网。
    使用者裁定"写入方填、验证者复核、不合格打回"后，缺省改为 enforce——
    不合规的写入当场打回给作者，而不是静默堆进审核队列。
    可用 MDCG_WORKDONE_ACCEPT=observe 临时退回观察档（回滚开关）。
    """
    raw = (os.environ.get(ENV_MODE) or "").strip().lower()
    if raw and raw not in MODES:
        if raw not in _WARNED_MODES:
            _WARNED_MODES.add(raw)
            import sys as _sys
            _sys.stderr.write(
                "[condaccept] 非法档位 %r（可选 %s），回落文档缺省 enforce\n"
                % (raw, "|".join(MODES)))
        return "enforce"
    return raw or "enforce"


def reset_last():
    _LAST.clear()


def last_judgement():
    return dict(_LAST)


def _v(state, evidence, detail=None, kind="work_done"):
    """构造裁决。

    响应体恒带两层解耦的语义（2026-10-18）：
        acceptance          形式层结论：formal_pass / formal_reject
        verification_state  真值层结论：本模块恒给 unverified（它无权判真）
    两者刻意**不合并**——合并会让「形式过了」被读成「内容对了」。
    诚实边界：节点 frontmatter 尚未落这两个字段（需改 mdcos.add 的 fm 构造，
    属跨模块改动），当前只在写入响应面提供；这是已知缺口，不假装已完成。
    """
    d = dict(detail or {})
    _acc = {"ACCEPT": "formal_pass", "REJECT": "formal_reject",
            "BLINDSPOT": "undetermined", "DEFER": "undetermined"}
    d.setdefault("acceptance", _acc.get(state, "undetermined"))
    d.setdefault("verification_state", "unverified")
    return {"state": state, "kind": kind, "basis": None,
            "evidence": evidence, "detail": d}


def _has_evidence(payload):
    refs = payload.get("evidence_ref") or payload.get("evidence")
    if isinstance(refs, (list, tuple)) and any(str(x).strip() for x in refs):
        return True
    if isinstance(refs, str) and refs.strip():
        return True
    text = str(payload.get("content") or "")
    return any(p.search(text) for p in _EVIDENCE_PATTERNS)


def _slot_conflict(payload, ctx):
    """V4：与已固化同槽信息是否冲突。

    返回 (status, nid, why)，status ∈ {"conflict","clear","unknown","na"}：

        conflict  同槽异值 → 上游 REJECT
        clear     查到且无同槽冲突 → 放行
        unknown    **判不了**（检索失败／无 cg）→ 上游 BLINDSPOT
        na         不适用（无 CCG 三要素槽位）→ 不阻断，标不适用

    为什么必须分四态（2026-10-18，外部评审 P0-1）：此前「判不了」返回 (None, why)，
    上游一律落到 ACCEPT——这违反本架构自己的 I5（无证据只能 DEFER/BLINDSPOT）。
    「无法判定」的下一步**不是 ACCEPT**，是 BLINDSPOT；但「不适用」也不等于判不了，
    故单列 na，避免把所有非 CCG 内容一并挡在门外。

    只用**只读**检索，且排除本节点自身（自指防护：本次正在写的 nid 不参与比对）。
    """
    from . import condgate
    text = str(payload.get("content") or "")
    key = condgate.slot_key(text)
    if key is None:
        return "na", None, "无 CCG 三要素槽位，V4 不适用（不阻断）"
    cg = ctx.get("cg")
    if cg is None:
        return "unknown", None, "无 cg，V4 无法判定"
    try:
        raw = cg.search(text[:120], k=3)
    except Exception as exc:
        return "unknown", None, "检索失败（%s），V4 无法判定" % type(exc).__name__
    # 返回形态兼容：cg.search 正常是 (res, meta) 且 res 元素为 (node, score, qual)；
    # 但测试替身/其它实现可能直接给 res 或 [{...}]。显式分辨，不猜、不静默跳过。
    hits = raw
    if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[0], (list, tuple)):
        hits = raw[0]
    me = str(ctx.get("nid") or "")
    for item in (hits or []):
        if isinstance(item, (list, tuple)) and item:
            node = item[0]
        elif isinstance(item, dict):
            node = item
        else:
            continue
        nid = str((node or {}).get("id") or "")
        if me and nid == me:
            continue
        other = (node or {}).get("content") or ""
        other_key = condgate.slot_key(other)
        if other_key == key and other.strip()[:200] != text.strip()[:200]:
            return "conflict", nid, "同槽异值：与 %s 槽位相同但内容不同" % (nid or "未知节点")
    return "clear", None, "未发现同槽冲突"


def evaluate(payload, ctx):
    """纯判定（不含灰度）。返回 verdict dict。"""
    from . import condgate as _cg_gate
    # 复用 condgate 的别名归一与 time_window 自动补，判据口径只此一处（不另立第二份）。
    cs = _cg_gate.autofill_time_window(_cg_gate._canon_keys(payload.get("condition_space")))
    normalized = {}
    missing = list(FOUR_DIMS)
    if isinstance(cs, dict):
        for k in FOUR_DIMS:
            v = cs.get(k)
            if isinstance(v, str):
                v = v.strip()
            if v not in (None, "", [], {}):
                normalized[k] = v
        missing = [k for k in FOUR_DIMS if k not in normalized]

    # V1 未过 = **打回写入方**，不是入队等裁决者（2026-10-18 使用者裁定）。
    # 区分依据：缺条件空间是写入方的责任，不是裁决者的责任——DEFER 会把
    # 「该由作者补齐的东西」转嫁给裁决队列，这正是 957 条积压的成因。
    if missing:
        return _v("REJECT",
                  "V1 未过：条件空间缺 %s；请补齐后重新提交（本条不入审核队列）"
                  % ",".join(missing),
                  {"criterion": "V1", "missing": missing,
                   "return_to": "author", "action": "resubmit_with_condition_space"})

    if not _has_evidence(payload):
        # 措辞按实际能力写（2026-10-18）：本判据只认**出处标记的存在**，
        # 不判该出处在语义上是否真能支撑本条断言——后者需要验证单元。
        return _v("REJECT",
                  "V2 未过：未见出处标记（无 evidence_ref，正文亦无「依据/出处/来源」、"
                  "节号、node_id、实测读数等可定位标记）。注意：V2 只认标记存在，"
                  "不判该出处是否真能支撑本条断言。",
                  {"criterion": "V2", "checks": "marker_presence_only"})

    v4_status, conflict_nid, why = _slot_conflict(payload, ctx)
    if v4_status == "conflict":
        return _v("REJECT", "V4 未过：%s" % why,
                  {"criterion": "V4", "conflict_with": conflict_nid})
    if v4_status == "unknown":
        # 判不了 ≠ 没问题。按 I5/I6 只能给 BLINDSPOT，不得落到 ACCEPT。
        return _v("BLINDSPOT", "V4 无法判定：%s；按 I5/I6 不得判通过" % why,
                  {"criterion": "V4", "v4_status": "unknown"})

    base = {"criterion": "V1/V2/V4", "slot_conflict": why,
            "v4_status": v4_status, "semantic_judgement": "not_attempted"}
    if v4_status == "na":
        base["v4_note"] = "无 CCG 槽位 → V4 不适用（不是判不了）"
    return _v("ACCEPT",
              ("形式完备：V1 条件空间齐全、V2 见出处标记、V4 未发现字面同槽冲突%s；"
               "V3/V5 为只读旁证未阻断。**本结论不判内容真值**"
               "（acceptance=formal_pass, verification_state=unverified）")
              % ("（V4 不适用：无 CCG 槽位）" if v4_status == "na" else ""),
              base)


def verify_work_done(payload, ctx):
    """验收器入口（签名同 audit 内建验证器）。"""
    real = evaluate(payload, ctx)
    m = mode()
    prior = ctx.get("nid") or ""
    _LAST.clear()
    _LAST.update({"mode": m, "real_state": real["state"],
                  "real_evidence": real["evidence"], "nid": prior})
    if m == "enforce":
        return real
    # observe：与「未注入」逐位一致地返回 DEFER，真实判定只入 evidence
    return _v("DEFER",
              "observe 档：真实判定=%s（%s）；此档不放行，仅为积累读数"
              % (real["state"], real["evidence"]),
              {"observe": True, "real": real})


def register(audit_module):
    """注入点：由 audit.load_external_verifiers 回调。"""
    audit_module.register_verifier("work_done", verify_work_done, override=True)
    return True
