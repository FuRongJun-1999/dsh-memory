# -*- coding: utf-8 -*-
# 功能名：复核单元的**代码化证据**判定（reviewed_by 声明 -> 可核验证据）
# 生效条件：MdCGSecure.add() 收到 reviewed_by 且该层落在写闸 tier >= 1（knowledge/structural/self/anchor）时
# 子功能：①签名凭据 proof（验签通过的 reflect/verify 令牌或非 NullSigner 的 sign_review_attestation 签章，含 Tier-3 human）②台账证据（decisions.jsonl，另一 actor、窗口内、带 record_hash）③进程内代码授权 grant（review_decide 过门后发的 300s 绑目标一次性授权，仅 reflect/verify）
# 执行：add() -> _resolve_write_reviewers() -> verify_claims(..., proof=...) -> require_layer_write(reviewers=已核验单元)
# 验证方式：md_cg/test_issue1009_reviewer_evidence.py + md_cg/test_issue1009_dual_review_auth.py
# 不适用条件：tier 0 层（闸不看复核单元）；MDCG_WRITE_GATE=off（闸完全不介入，声明原样下传）
"""使用者裁定（2026-11-22）：「算，但只算带明确证据的。依赖人去复核是不可能去做到的。
只能是确定性规则，和代码化的结果。」

=> reviewed_by 是**声明**，不是证据。统一口径（三源并集，皆要求 actor != 写入者）：

  accepted_units = 签名凭据(proof) ∪ 台账证据(ledger) ∪ 代码授权(grant)

**① 签名凭据**（`proof=`，密码学可验证、跨进程可复核）
   经服务端 `tokens.verify_token` 验签通过的 reflect/verify 令牌，或经非 `NullSigner`
   签名器绑定 `(pid, node_id, unit, actor)` 的 `sign_review_attestation` 签章（含 `human`）。
   已核验的 `proof` 可直接满足对应单元，无需再落台账；由此把 Tier-3（self/anchor）
   从「无证据源死口」救回为「有密码学人工签章才可满足」的可验证路径。

**② 台账证据**（跨调用可复核）
   本仓的裁决台账 hippocampus/decisions.jsonl 里，存在一条满足下列全部条件的记录：
     · 时间在窗口内（缺省 7 天，MDCG_REVIEW_EVIDENCE_WINDOW_S 可调）；
     · actor 经 `norm_actor` 归一非空且**不是**本次写入者（防大小写/空白/括号注记自证）；
     · record_hash 非空（该记录本身可被 _record_hash 重算复核）；
   再按单元取**该记录实际做了什么**：
     · reflect —— redteam_verdict == "pass"，或 decision 属 {accept, edit} 且 issues 为空；
     · verify  —— verify_hash 非空（判据指纹算过 = 校验器真跑过）。

**③ 代码授权**（进程内、不可伪造）
   受信任直调路径 `review_decide` 过完全部前置门后，由代码把本次裁决登记成 grant
   （键=目标节点 id，300 秒内有效，用一次即作废，仅覆盖 reflect/verify）。
   未信任 MCP/令牌面的裸声明在进入 grant 前即被剥离，不得借此提权。

**human 纪律**：台账与代码授权一律不授 `human`（台账 actor 全是客户端身份）；
未带有效 `proof` 签章的 `human` 声明仍一律拒（保持 fail-closed）。
"""
import json
import os
import re
import time

#: 台账证据的时间窗（秒）。缺省 7 天：一次复核不能给一年后的写入背书。
DEFAULT_WINDOW_S = 7 * 86400
#: 窗口的环境开关。
WINDOW_ENV = "MDCG_REVIEW_EVIDENCE_WINDOW_S"
#: 代码授权的有效期（秒）：只在一次 review_decide -> add 的直连链上有效。
GRANT_TTL_S = 300

#: 单元别名（与 mdcos._norm_review_unit 同口径，独立维护以便单独测试）
ALIASES = {
    "reflect": ("reflect", "reflection", "reflect_unit", "反思", "反思单元", "反思者"),
    "verify": ("verify", "verifier", "verification", "verify_unit", "验证", "验证单元", "验证者"),
    "human": ("human", "man", "user", "使用者", "人工", "人工裁定", "human_review"),
}


# 生效条件：name 为字符串或含 unit/role/name 键的 dict；返回 reflect/verify/human 或 None。
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


# 生效条件：name 经 strip、剥离尾部中英文括号注记、去除全部空白并 casefold 后返回；空值返回 ""。
def norm_actor(name) -> str:
    """复核主体名归一（与 ccgc._same_subject 同口径，防大小写/空白/括号注记绕过自证检查）。"""
    s = str(name or "").strip()
    if not s:
        return ""
    s = re.sub(r"[（(][^（）()]*[)）]\s*$", "", s)
    return re.sub(r"\s+", "", s).casefold()


# 生效条件：a/b 经 norm_actor 归一后均非空且相等时返回 True，否则返回 False。
def same_actor(a, b) -> bool:
    na, nb = norm_actor(a), norm_actor(b)
    return bool(na) and na == nb


_same_actor = same_actor


def _safe_claim_label(raw) -> str:
    """未知声明脱敏标签：若入参为含凭据字段的 dict，绝不把 token/sig 明文回显到审计/日志。"""
    if isinstance(raw, dict):
        label = raw.get("unit") or raw.get("role") or raw.get("name")
        if label is not None and str(label).strip():
            return str(label).strip()[:120]
        if raw.get("token") or raw.get("sig"):
            return "<credential>"
        return str({k: str(v)[:40] for k, v in raw.items()
                    if k not in ("token", "sig", "secret")})[:120]
    return str(raw)[:120]


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


def _reflect_ok(rec):
    if str(rec.get("redteam_verdict") or "") == "pass":
        return True
    return (str(rec.get("decision") or "") in ("accept", "edit")
            and not (rec.get("issues") or []))


def _verify_ok(rec):
    return bool(rec.get("verify_hash"))


_CHECKS = {"reflect": _reflect_ok, "verify": _verify_ok}


def _normalize_proof(proof, actor: str = "") -> dict:
    """把已验签的 proof 归一为 {canon_unit: evidence_dict}；含 actor 时复核 actor != 写入者。"""
    proof_map = {}
    if not proof:
        return proof_map
    if isinstance(proof, dict):
        for k, meta in proof.items():
            u = norm_unit(k)
            if u not in ("reflect", "verify", "human") or not meta:
                continue
            entry = {"source": "proof"}
            if isinstance(meta, dict):
                p_actor = meta.get("actor")
                if p_actor and actor and same_actor(p_actor, actor):
                    continue
                for mk in ("via", "actor", "signer", "token_id", "pid", "node_id"):
                    mv = meta.get(mk)
                    if mv is not None and str(mv).strip():
                        entry[mk] = mv
            proof_map[u] = entry
    else:
        items = [proof] if isinstance(proof, (str, bytes)) else proof
        for raw_p in items:
            u = norm_unit(raw_p)
            if u in ("reflect", "verify", "human"):
                proof_map.setdefault(u, {"source": "proof"})
    return proof_map


# 生效条件：claims 为复核单元声明序列（支持单值或可迭代）；按「签名凭据 proof ∪ 代码授权 grant ∪ 台账证据 ledger」三源核验，均要求 actor != 写入者；返回 {accepted, rejected, evidence, grant_used}。
def verify_claims(claims, *, ledger_path=None, actor="", node_id=None,
                  window_s=None, now=None, grant=None, proof=None):
    """把 reviewed_by 的声明核成证据（统一公式：proof ∪ ledger ∪ grant，皆要求 actor != 写入者）。

    返回 {"accepted": [单元...], "rejected": [{"unit","why"}...],
          "evidence": {单元: {...}}, "grant_used": bool}
    human 仅在提供已验签的 `proof`（非 NullSigner 签章凭据）时可进入 accepted，
    裸声明 / 台账 / 代码授权一律不授予 human。
    """
    now = time.time() if now is None else float(now)
    win = window_seconds() if window_s is None else float(window_s)
    out = {"accepted": [], "rejected": [], "evidence": {}, "grant_used": False}

    if claims is None:
        claim_items = ()
    elif isinstance(claims, (str, bytes, dict)):
        claim_items = (claims,)
    else:
        claim_items = claims

    seen = []
    for raw in claim_items:
        u = norm_unit(raw)
        if u is None:
            out["rejected"].append({"unit": _safe_claim_label(raw),
                                    "why": "未知复核单元（只认 reflect/verify/human）"})
            continue
        if u not in seen:
            seen.append(u)
    if not seen:
        return out

    # ① 签名凭据：已通过令牌验签或非 NullSigner 签章验证的单元（含 human）
    proof_map = _normalize_proof(proof, actor=actor)

    # ② 代码授权：本次进程内受信任裁决路径登记的一次性授权（仅 reflect/verify）
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
        if u in proof_map:
            out["accepted"].append(u)
            out["evidence"][u] = dict(proof_map[u])
            continue
        if u == "human":
            out["rejected"].append({
                "unit": "human",
                "why": ("人工裁定无代码化证据源（台账 actor 全是客户端身份，人签不可验证；"
                        "需经非 NullSigner 的 sign_review_attestation 签章凭据），见 issue #1009")})
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
            rec_actor = rec.get("actor")
            if not norm_actor(rec_actor) or not norm_actor(actor) or same_actor(rec_actor, actor):
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
