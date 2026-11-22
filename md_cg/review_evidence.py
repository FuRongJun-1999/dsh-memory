# -*- coding: utf-8 -*-
# 功能名：复核单元的**代码化证据**判定（reviewed_by 声明 -> 可核验证据）
# 生效条件：MdCGOS.add() 收到 reviewed_by 且该层落在写闸 tier >= 1（knowledge/structural/self/anchor）时
# 子功能：①台账证据（decisions.jsonl，另一 actor、窗口内、带 record_hash）②进程内代码授权（_dual_review_verdict 的 ok 结论）③human 无证据源一律不认
# 执行：add() -> _verified_reviewers() -> verify_claims() -> require_layer_write(reviewers=已核验单元)
# 验证方式：md_cg/test_issue1009_reviewer_evidence.py
# 不适用条件：tier 0 层（闸不看复核单元）；MDCG_WRITE_GATE=off（闸完全不介入，声明原样下传）
"""使用者裁定（2026-11-22）：「算，但只算带明确证据的。依赖人去复核是不可能去做到的。
只能是确定性规则，和代码化的结果。」

=> reviewed_by 是**声明**，不是证据。声明要变成证据，只有两条码化来源：

**① 台账证据**（跨调用可复核）
   本仓的裁决台账 hippocampus/decisions.jsonl 里，存在一条满足下列全部条件的记录：
     · 时间在窗口内（缺省 7 天，MDCG_REVIEW_EVIDENCE_WINDOW_S 可调）；
     · actor **不是**本次写入者（自证不算复核，与 self_review_forbidden 同源）；
     · record_hash 非空（该记录本身可被 _record_hash 重算复核）；
   再按单元取**该记录实际做了什么**：
     · reflect —— redteam_verdict == "pass"，或 decision 属 {accept, edit} 且 issues 为空；
     · verify  —— verify_hash 非空（判据指纹算过 = 校验器真跑过）。

**② 代码授权**（进程内、不可伪造）
   review_decide 里 _dual_review_verdict 判 ok 之后，由代码把「本次裁决确实过了
   反思 + 验证」登记成 grant（键=目标节点 id，300 秒内有效，用一次即作废）。
   它来自代码判定而非入参，故可直接作为证据。

**③ human —— 无证据源，一律不认。**
   实测：台账 797 条记录的 actor 取值只有 designer-cli(458) / zcode(181) / codebuddy(141) /
   designer(10) / system(3) / mcp-client(3)——全是**客户端身份**，没有一条是「人」的可验证签名。
   既然如此，human 不能由入参声明换任何东西出来；tier 3（self/anchor）在 enforce 下因此
   缺少可满足路径，这是**已知且有意为之**的 fail-closed 状态（见 issue #1009 记录），
   要放开得先设计一个码化的替代判据。
"""
import json
import os
import time

#: 台账证据的时间窗（秒）。缺省 7 天：一次复核不能给一年后的写入背书。
DEFAULT_WINDOW_S = 7 * 86400
#: 窗口的环境开关。
WINDOW_ENV = "MDCG_REVIEW_EVIDENCE_WINDOW_S"
#: 代码授权的有效期（秒）：只在一次 review_decide -> add 的直连链上有效。
GRANT_TTL_S = 300

#: 单元别名（与 mdcos._norm_review_unit 同口径，此处独立维护以便单独测试）
ALIASES = {
    "reflect": ("reflect", "reflection", "反思", "反思单元", "反思者"),
    "verify": ("verify", "verification", "验证", "验证单元", "验证者"),
    "human": ("human", "man", "人工", "人工裁定", "human_review"),
}


def norm_unit(name):
    """别名 -> reflect / verify / human；不认识返回 None（不猜）。"""
    if isinstance(name, dict):
        name = name.get("unit") or name.get("role") or name.get("name") or ""
    s = str(name or "").strip().lower()
    if not s:
        return None
    for canon, names in ALIASES.items():
        if s in names:
            return canon
    return None


def window_seconds(environ=None):
    env = os.environ if environ is None else environ
    raw = str(env.get(WINDOW_ENV) or "").strip()
    if not raw:
        return DEFAULT_WINDOW_S
    try:
        v = float(raw)
    except ValueError:
        return DEFAULT_WINDOW_S
    return v if v > 0 else DEFAULT_WINDOW_S


def _iter_records(path):
    """逐行读台账；坏行跳过（一行坏掉不该让整个写入路径失去证据能力）。"""
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    yield rec
    except OSError:
        return


def _same_actor(a, b):
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def _reflect_ok(rec):
    if str(rec.get("redteam_verdict") or "") == "pass":
        return True
    return (str(rec.get("decision") or "") in ("accept", "edit")
            and not (rec.get("issues") or []))


def _verify_ok(rec):
    return bool(rec.get("verify_hash"))


_CHECKS = {"reflect": _reflect_ok, "verify": _verify_ok}


def verify_claims(claims, *, ledger_path=None, actor="", node_id=None,
                  window_s=None, now=None, grant=None):
    """把 reviewed_by 的声明核成证据。

    返回 {"accepted": [单元...], "rejected": [{"unit","why"}...],
          "evidence": {单元: {...}}, "grant_used": bool}
    accepted 里只有 reflect/verify；human 永不出现在 accepted（无证据源）。
    """
    now = time.time() if now is None else float(now)
    win = window_seconds() if window_s is None else float(window_s)
    out = {"accepted": [], "rejected": [], "evidence": {}, "grant_used": False}

    seen = []
    for raw in (claims or ()):
        u = norm_unit(raw)
        if u is None:
            out["rejected"].append({"unit": str(raw), "why": "未知复核单元（只认 reflect/verify/human）"})
            continue
        if u not in seen:
            seen.append(u)
    if not seen:
        return out

    # ② 代码授权：本次进程内 _dual_review_verdict 判过 ok（含 reflect+verify）
    g_ok = False
    if isinstance(grant, dict):
        g_units = set(grant.get("units") or ())
        g_target = grant.get("target")
        fresh = (now - float(grant.get("t") or 0)) <= GRANT_TTL_S
        bound = (g_target is None or node_id is None
                 or str(g_target) == str(node_id))
        g_ok = bool(fresh and bound and {"reflect", "verify"} <= g_units)

    records = None
    for u in seen:
        if u == "human":
            out["rejected"].append({
                "unit": "human",
                "why": ("人工裁定无代码化证据源（台账 actor 全是客户端身份，人签不可验证）；"
                        "tier 3 因此缺少可满足路径，见 issue #1009")})
            continue
        if g_ok:
            out["accepted"].append(u)
            out["evidence"][u] = {"source": "code_grant",
                                  "pid": grant.get("pid"), "t": grant.get("t")}
            out["grant_used"] = True
            continue
        if records is None:
            records = list(_iter_records(ledger_path))
        hit = None
        for rec in reversed(records):
            try:
                t = float(rec.get("t") or 0)
            except (TypeError, ValueError):
                continue
            if now - t > win:
                continue
            if _same_actor(rec.get("actor"), actor):
                continue
            if not str(rec.get("record_hash") or "").strip():
                continue
            if _CHECKS[u](rec):
                hit = rec
                break
        if hit is None:
            out["rejected"].append({
                "unit": u,
                "why": ("台账里没有可作为证据的记录（需：另一 actor、%d 天内、带 record_hash，"
                        "且 %s）" % (int(win // 86400) or 1,
                                    "红队 pass 或 accept/edit 无 issues" if u == "reflect"
                                    else "verify_hash 非空（校验器实跑）"))})
            continue
        out["accepted"].append(u)
        out["evidence"][u] = {"source": "ledger", "actor": hit.get("actor"),
                              "pid": hit.get("pid"), "t": hit.get("t"),
                              "record_node_id": hit.get("record_node_id"),
                              "record_hash": hit.get("record_hash")}
    return out
