# -*- coding: utf-8 -*-
"""work_done **形式完备闸**（condaccept）——只判形式完备，不判语义真值。

【正名，2026-10-24】本模块原名「验收器」，名不副实。核对自身实现可见：

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

理论依据（统一架构 v1.1 §2.4 / §9.1）：
    理论只承认可认知信息。故验收不看文件是否存在、行数够不够，
    只看这条**断言**本身是否成立：条件空间声明了吗？证据可回溯吗？同槽冲突吗？

判据分层（重要）：
    阻断判据（决定 ACCEPT/REJECT/DEFER）
        V1 条件空间四维齐全          缺 → DEFER
        V2 证据可回溯（evidence_ref/出处）  不可回溯 → REJECT
        V4 与已固化同槽信息冲突        冲突 → REJECT（负路由优先）
    只读旁证（只记录，不阻断——写时检索代价与自指风险未解）
        V3 同一信息的多份投影是否一致
        V5 冗余投影是否已合并

灰度（与 condgate 同一纪律）：
    MDCG_WORKDONE_ACCEPT = observe（默认）| enforce
    observe：**恒返回 DEFER**，与「未注入验收器」的现状逐位一致；
             真实判定写进 evidence/detail，只为积累读数，绝不改变现网行为。
    enforce：返回真实判定——此时才真正放行或拦截。
    这一取舍的理由：若 observe 就返回 ACCEPT，等于一夜之间让全部 work_done
    绕过审核直接落盘，比不注入更激进。

注入方式：
    模块提供 register(audit_module)，由 audit.load_external_verifiers 回调；
    环境变量 MDCG_VERIFIER_MODULES=md_cg.condaccept 声明本模块。
"""

import os
import re

__all__ = ["register", "verify_work_done", "evaluate", "mode",
           "FOUR_DIMS", "last_judgement", "reset_last"]

ENV_MODE = "MDCG_WORKDONE_ACCEPT"
MODES = ("observe", "enforce")

FOUR_DIMS = ("observation_position", "observation_tool",
             "time_window", "existence_constraint")

#: 证据可回溯的形态：显式 evidence_ref/evidence 字段，或正文里的可定位出处
#: 证据可回溯的形态。首版正则过窄，把「第9.1节」这类带小数点的节号判成无证据
#: （实测：一条完全合规的样本被 V2 假拒绝）——判据过严与过松同样有害，故：
#:   ① 行首出处标记允许不带井号（正文里常写「依据：…」而非「# 依据：…」）
#:   ② 节号允许小数点（第9.1节 / 第 3.2.1 节）
_EVIDENCE_PATTERNS = (
    re.compile(r"^\s*(?:#\s*)?(?:位置|出处|依据|来源)\s*[：:]\s*\S", re.M),
    re.compile(r"(?:node_id|mem_|doc_|\bT\d+\b|第\s*[\d.]+\s*节|L\d+[-–]L?\d*|##)", re.M),
    re.compile(r"(?:实测|读数|日志|job_id|h_dsh)", re.M),
)

_LAST = {}


def mode():
    """当前档位。缺省 **enforce**（2026-10-24 使用者裁定「开」）。

    历史：首版缺省 observe（恒返回 DEFER、只记读数），是为了不动现网。
    使用者裁定"写入方填、验证者复核、不合格打回"后，缺省改为 enforce——
    不合规的写入当场打回给作者，而不是静默堆进审核队列。
    可用 MDCG_WORKDONE_ACCEPT=observe 临时退回观察档（回滚开关）。
    """
    raw = (os.environ.get(ENV_MODE) or "").strip().lower()
    return raw if raw in MODES else "enforce"


def reset_last():
    _LAST.clear()


def last_judgement():
    return dict(_LAST)


def _v(state, evidence, detail=None, kind="work_done"):
    """构造裁决。

    响应体恒带两层解耦的语义（2026-10-24）：
        acceptance          形式层结论：formal_pass / formal_reject
        verification_state  真值层结论：本模块恒给 unverified（它无权判真）
    两者刻意**不合并**——合并会让「形式过了」被读成「内容对了」。
    诚实边界：节点 frontmatter 尚未落这两个字段（需改 mdcos.add 的 fm 构造，
    属跨模块改动），当前只在写入响应面提供；这是已知缺口，不假装已完成。
    """
    d = dict(detail or {})
    d.setdefault("acceptance", "formal_pass" if state == "ACCEPT" else "formal_reject")
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

    只用**只读**检索，且排除本节点自身（自指防护：本次正在写的 nid 不参与比对）。
    检索失败一律视为「无法判定」而非「无冲突」——不猜。
    """
    from . import condgate
    text = str(payload.get("content") or "")
    key = condgate.slot_key(text)
    if key is None:
        return None, "无槽位（未按 CCG 三要素写注释），V4 跳过"
    cg = ctx.get("cg")
    if cg is None:
        return None, "无 cg，V4 无法判定"
    try:
        raw = cg.search(text[:120], k=3)
    except Exception as exc:
        return None, "检索失败（%s），V4 无法判定" % type(exc).__name__
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
            return nid, "同槽异值：与 %s 槽位相同但内容不同" % (nid or "未知节点")
    return None, "未发现同槽冲突"


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

    # V1 未过 = **打回写入方**，不是入队等裁决者（2026-10-24 使用者裁定）。
    # 区分依据：缺条件空间是写入方的责任，不是裁决者的责任——DEFER 会把
    # 「该由作者补齐的东西」转嫁给裁决队列，这正是 957 条积压的成因。
    if missing:
        return _v("REJECT",
                  "V1 未过：条件空间缺 %s；请补齐后重新提交（本条不入审核队列）"
                  % ",".join(missing),
                  {"criterion": "V1", "missing": missing,
                   "return_to": "author", "action": "resubmit_with_condition_space"})

    if not _has_evidence(payload):
        # 措辞按实际能力写（2026-10-24）：本判据只认**出处标记的存在**，
        # 不判该出处在语义上是否真能支撑本条断言——后者需要验证单元。
        return _v("REJECT",
                  "V2 未过：未见出处标记（无 evidence_ref，正文亦无「依据/出处/来源」、"
                  "节号、node_id、实测读数等可定位标记）。注意：V2 只认标记存在，"
                  "不判该出处是否真能支撑本条断言。",
                  {"criterion": "V2", "checks": "marker_presence_only"})

    conflict_nid, why = _slot_conflict(payload, ctx)
    if conflict_nid is not None:
        return _v("REJECT", "V4 未过：%s" % why,
                  {"criterion": "V4", "conflict_with": conflict_nid})

    return _v("ACCEPT",
              "形式完备：V1 条件空间齐全、V2 见出处标记、V4 无字面同槽冲突；"
              "V3/V5 为只读旁证未阻断。**本结论不判内容真值**"
              "（acceptance=formal_pass, verification_state=unverified）",
              {"criterion": "V1/V2/V4", "slot_conflict": why,
               "semantic_judgement": "not_attempted"})


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
