# -*- coding: utf-8 -*-
"""连接层（蜂群互联层1）。

职责：管理**跨节点信任状态**——「我信你多少」。落盘 `~/.mdcg/_links.json`（0600）。

本层**不做密码学**（设计裁决 D-4）：签名一律经 `signer.sign_for / verify_for`
按子系统策略调用，内核只保证「策略被读取并执行」。

四条不可动摇的性质（文档 §3.2 / §4.3）：

1. **P_trust 是概率估计，不是承诺**——可上调、可下调、**可被反例击穿**；
2. **有上限 `p_trust_cap`**——受版本对齐度与节点完整度约束，不能靠高频交互刷高；
3. **有衰减**——长时间无观测向初值回归，避免「一次建立信任后永久有效」；
4. **全程留痕**——`audit` 记录每次变更的证据与依据条款（宪章第二十四条）。

诚实边界：`UP_STEP` / `DOWN_STEP` / `DECAY_DAYS` / `PROBATION_SECONDS`
**均为未标定占位值**（文档 §4.3：「v0.1 只声明结构，不宣称权重数值」）。
标定属路线图 v0.3，本模块只保证结构、方向与不可自放大。

零第三方依赖。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

from . import signer as _signer

LINKS_FILE_ENV = "MDCG_LINKS_FILE"
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), ".mdcg")
DEFAULT_LINKS_FILE = os.path.join(DEFAULT_DIR, "_links.json")
SCHEMA = 1

STATUS = ("probation", "normal", "degraded", "isolated", "withdrawn")
IN_TRUST = ("probation", "normal", "degraded")

# ---- 信任数值（未标定占位；方向性约束由宪章第七条确定：降快于升）----------
P_TRUST_INIT = 0.8            # 宪章第五条：蜂群成员初值
CAP_ALIGNED = 0.8
CAP_INCOMPLETE = 0.6          # 未声明单元映射（子智能体级）
CAP_MISALIGNED = 0.3          # 版本不在认可集合
CAP_ISOLATED = 0.0
UP_STEP = 0.05
DOWN_STEP = 0.20              # 降快于升：可被反例击穿
DEGRADE_BELOW = 0.50
DECAY_DAYS = 30.0             # 无观测半衰期（向初值回归）
PROBATION_SECONDS = 7 * 24 * 3600     # 观察期；未声明宪章则翻倍


class LinkError(Exception):
    """连接层错误（fail-closed）。"""


# --------------------------------------------------------------------------
# 存储
# --------------------------------------------------------------------------

# 生效条件：path 为真值（非 None/非空串）时直接返回 path；否则取 `os.environ.get(LINKS_FILE_ENV)`，其为真值时返回之；环境变量缺失或为空串（假值）时回落 DEFAULT_LINKS_FILE。
def links_file(path: str = None) -> str:
    return path or os.environ.get(LINKS_FILE_ENV) or DEFAULT_LINKS_FILE


# 生效条件：p=links_file(path)，仅当 `os.path.exists(p)` 为真且 json.load 得到 dict 且 `d.get("links")` 为 dict 时，`d.setdefault("schema", SCHEMA)`（已有 schema 键则保留原值）并返回 d；路径不存在、抛 OSError/ValueError、或 links 非 dict 时返回 `{"schema": SCHEMA, "links": {}, "updated_at": None}`。
def load(path: str = None) -> dict:
    p = links_file(path)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("links"), dict):
                d.setdefault("schema", SCHEMA)
                return d
        except (OSError, ValueError):
            pass
    return {"schema": SCHEMA, "links": {}, "updated_at": None}


# 生效条件：传入 data（dict）与可选 path 时，p=links_file(path)，以 `dict(data)` 浅拷贝并强制覆盖 schema=SCHEMA、updated_at=time.time()，写入 p+".tmp"（目录名为空时 makedirs(".")），chmod 0o600 的 OSError 被吞，`os.replace(tmp, p)` 后返回 p。
def save(data: dict, path: str = None) -> str:
    p = links_file(path)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    data = dict(data)
    data["schema"] = SCHEMA
    data["updated_at"] = time.time()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, p)
    return p


# 生效条件：传入 peer 时，对 f"{peer}|{time.time()}|{os.getpid()}" 做 utf-8 编码的 sha256，返回 "lk_" 拼接 `hexdigest()` 的前 12 个十六进制字符（peer 为 None 时按 "None" 参与哈希）。
def _new_id(peer: str) -> str:
    h = hashlib.sha256(f"{peer}|{time.time()}|{os.getpid()}".encode("utf-8"))
    return "lk_" + h.hexdigest()[:12]


# 生效条件：传入 link（dict）与 action，构造含 at/action 的 rec 并并入 kw 中值非 None 的项；link 缺 "audit" 键时由 setdefault 建空列表后 append，link 已有 "audit" 列表则直接 append 一条记录（已有值为 None 等非列表时 append 会失败，源码未兜）。
def _audit(link: dict, action: str, **kw):
    rec = {"at": time.time(), "action": action}
    rec.update({k: v for k, v in kw.items() if v is not None})
    link.setdefault("audit", []).append(rec)


# 生效条件：peer 为 None 或 strip 后为空串时返回空串 p；strip 后以 "agent:" 开头时原样返回 p；否则返回 "agent:" + p。
def _norm_peer(peer: str) -> str:
    p = (peer or "").strip()
    return p if (not p or p.startswith("agent:")) else "agent:" + p


# 生效条件：data.get("links") 为真 dict 时，peer 直接是键则返回 (peer, links[peer])；否则在 {peer, _norm_peer(peer)} 中匹配任一 link_id 或 link 的 peer_node_id 并返回首个 (lid, lk)；均不匹配返回 (None, None)。
def _find(data: dict, peer: str):
    """按 link_id 或 peer_node_id 定位（容忍省略 `agent:` 前缀）。"""
    links = data.get("links") or {}
    if peer in links:
        return peer, links[peer]
    cands = {peer, _norm_peer(peer)}
    for lid, lk in links.items():
        if lid in cands or lk.get("peer_node_id") in cands:
            return lid, lk
    return None, None


# 生效条件：调用方传入 data（须含 "links" 映射）、lid、link 时，执行 `data["links"][lid] = link` 并 save(data, path)，返回 link（data 无 "links" 键时该赋值抛 KeyError，源码未兜）。
def _commit(data: dict, lid: str, link: dict, path: str = None):
    data["links"][lid] = link
    save(data, path)
    return link


# --------------------------------------------------------------------------
# 版本对齐度 → 信任上限
# --------------------------------------------------------------------------

# 生效条件：以 `peer_theory or {}` 取 t，pv=`t.get("version") or t.get("theory_version")`；pv 为假值（None/空串）返回 aligned False、cap CAP_MISALIGNED、reason 为「对端未声明版本」；pv 在本地 theory.check() 的 accepted_versions（缺失时按 []）内返回 aligned True、cap CAP_ALIGNED；否则返回 aligned False、cap CAP_MISALIGNED 并附对端版本与本地集合。
def version_alignment(peer_theory: dict = None) -> dict:
    """对端版本 vs 本地认可集合 → `{aligned, cap, reason}`。"""
    from .theory import check as _theory_check
    st = _theory_check()
    accepted = list(st.get("accepted_versions") or [])
    t = peer_theory or {}
    pv = t.get("version") or t.get("theory_version")
    if not pv:
        return {"aligned": False, "cap": CAP_MISALIGNED,
                "reason": "对端未声明版本（层0 派生律）",
                "local_accepted": accepted, "peer_version": None}
    if pv in accepted:
        return {"aligned": True, "cap": CAP_ALIGNED, "reason": "版本在认可集合内",
                "local_accepted": accepted, "peer_version": pv}
    return {"aligned": False, "cap": CAP_MISALIGNED,
            "reason": f"对端版本 {pv} 不在本地认可集合 {accepted}",
            "local_accepted": accepted, "peer_version": pv}


# 生效条件：cap 初始为 CAP_ALIGNED；`alignment.get("aligned")` 为假时 cap=min(cap, CAP_MISALIGNED)；position_map 为假值（None 或空 dict）时 cap=min(cap, CAP_INCOMPLETE)；返回该 cap（数值大小关系由常量定义，源码未在本段校验）。
def _cap_for(alignment: dict, position_map: dict = None) -> float:
    cap = CAP_ALIGNED
    if not alignment.get("aligned"):
        cap = min(cap, CAP_MISALIGNED)
    if not position_map:
        cap = min(cap, CAP_INCOMPLETE)
    return cap


# 生效条件：传入 position 时返回含 position、委派 `md_cg.weights` 得到的 dominant/secondary/excluded/order，以及 class（`_w.is_viewpoint(position)` 真取 VIEWPOINT，否则取 FUNCTIONAL）的字典，不修改任何状态。
def position_preference(position: str) -> dict:
    """该位置的分量偏好序（委派 `md_cg.weights`，纯结构、无数值）。

    仅作查询/自描述，**不改动** `_cap_for` 的既有默认行为——对齐「先声明
    结构、数值标定 DEFER」的纪律（文档 §4.3）。
    """
    from . import weights as _w
    return {"position": position, "dominant": _w.dominant(position),
            "secondary": _w.secondary(position), "excluded": _w.excluded(position),
            "class": (VIEWPOINT if _w.is_viewpoint(position) else FUNCTIONAL),
            "order": _w.order(position)}


#: 位置类别（与 `md_cg.weights` 同名常量保持一致，供连接层自描述引用）
VIEWPOINT = "viewpoint"
FUNCTIONAL = "functional"


# --------------------------------------------------------------------------
# 签名载荷（确定性：同参数必同字节）
# --------------------------------------------------------------------------

# 生效条件：传入 body 时返回 `json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` 的 utf-8 编码字节。
def _canon(body: dict) -> bytes:
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


# 生效条件：传入 peer_node_id 与可选 peer_theory/position_map 时，t=`peer_theory or {}`，返回 _canon 字节串，其中 theory_version 取 `t.get("version") or t.get("theory_version")`、theory_hash 取 `t.get("hash") or t.get("theory_hash")`、position_map 为 `(position_map or {})` 各项按 key 排序后值经 str() 的映射。
def handshake_payload(peer_node_id: str, peer_theory: dict = None,
                      position_map: dict = None) -> bytes:
    t = peer_theory or {}
    return _canon({
        "peer_node_id": peer_node_id,
        "theory_version": t.get("version") or t.get("theory_version"),
        "theory_hash": t.get("hash") or t.get("theory_hash"),
        "position_map": {k: str(v) for k, v in
                         sorted((position_map or {}).items())},
    })


# 生效条件：传入 peer_node_id、evidence、positive 时返回 _canon 字节串，evidence 经 str()（None 得 "None"）、positive 经 bool()（0/""/None 得 False）。
def evidence_payload(peer_node_id: str, evidence: str, positive: bool) -> bytes:
    return _canon({"peer_node_id": peer_node_id, "evidence": str(evidence),
                   "positive": bool(positive)})


# --------------------------------------------------------------------------
# 握手（文档 §5.1 五步：① 声明 → ② 校验 → ③ 建档 → ④ 观察期；⑤ 转正见 promote）
# --------------------------------------------------------------------------

def handshake(peer_node_id: str, *, peer_theory: dict = None,
              position_map: dict = None, declared_charter: bool = True,
              subsystem: str = None, peer_signature: str = None,
              path: str = None, signers_file: str = None,
              actor: str = "system") -> dict:
    """建立连接记录。验签失败**不静默**：按子系统策略处置并留痕。"""
    if not peer_node_id:
        raise LinkError("peer_node_id 不能为空")
    if not peer_node_id.startswith("agent:"):
        peer_node_id = "agent:" + peer_node_id      # §4.2 全局唯一主体 id

    align = version_alignment(peer_theory)
    payload = handshake_payload(peer_node_id, peer_theory, position_map)
    ctx = {"peer": peer_node_id, "action": "handshake"}
    ver = _signer.verify_for(subsystem, payload, peer_signature or "", ctx=ctx,
                             action="handshake", path=signers_file)

    if not ver.get("ok"):
        on_fail = ver.get("on_fail") or "degrade"
        if on_fail == "reject":
            raise LinkError(
                f"对端签名校验失败（策略={on_fail}）：{ver.get('reason')}")

    cap = _cap_for(align, position_map)
    now = time.time()
    probation = PROBATION_SECONDS * (1.0 if declared_charter else 2.0)
    t = peer_theory or {}

    link = {
        "link_id": _new_id(peer_node_id),
        "peer_node_id": peer_node_id,
        "peer_theory_version": t.get("version") or t.get("theory_version"),
        "peer_theory_hash": t.get("hash") or t.get("theory_hash"),
        "p_trust": min(P_TRUST_INIT, cap),
        "p_trust_cap": cap,
        "status": "probation",
        "position_map": dict(position_map or {}),
        "declared_charter": bool(declared_charter),
        "subsystem": subsystem or "",
        "version_aligned": bool(align.get("aligned")),
        "evidence_count": 0,
        "last_observed": None,
        "decay": 0.0,
        "created_at": now,
        "probation_until": now + probation,
        "promoted_at": None,
        "signatures": {},
        "audit": [],
    }

    ours = _signer.sign_for(subsystem, payload, ctx=ctx, action="handshake",
                            path=signers_file)
    if ours.get("signed"):
        link["signatures"]["self"] = {"signer": ours.get("signer"),
                                      "signature": ours.get("signature"),
                                      "at": now}
    if ver.get("required"):
        link["signatures"]["peer"] = {"signer": ver.get("signer"),
                                      "signature": peer_signature or "",
                                      "verified": bool(ver.get("ok")),
                                      "at": now}

    _audit(link, "handshake", by=actor, peer=peer_node_id,
           clause="宪章第二十八条（接入声明）",
           peer_version=link["peer_theory_version"],
           version_aligned=align.get("aligned"), cap=cap,
           signature_required=bool(ver.get("required")),
           signature_ok=bool(ver.get("ok")) if ver.get("required") else None,
           probation_seconds=probation)

    if not ver.get("ok"):
        on_fail = ver.get("on_fail") or "degrade"
        if on_fail == "isolate":
            _set_status(link, "isolated", actor=actor,
                        clause="宪章第七条（信任降级）",
                        reason=ver.get("reason"))
        else:
            _set_status(link, "degraded", actor=actor,
                        clause="宪章第七条（信任降级）",
                        reason=ver.get("reason"))
    elif not align.get("aligned"):
        _audit(link, "version_misaligned", by=actor,
               clause="层0 派生律（版本不符降级观察期）",
               reason=align.get("reason"))

    data = load(path)
    _commit(data, link["link_id"], link, path)
    return {"ok": True, "link": link, "alignment": align,
            "signature": {"required": bool(ver.get("required")),
                          "ok": bool(ver.get("ok")) if ver.get("required") else None,
                          "on_fail": (ver.get("on_fail")
                                      if ver.get("required") else None)}}


# --------------------------------------------------------------------------
# 观测（P_trust 更新 / 反例击穿）
# --------------------------------------------------------------------------

# 生效条件：peer 经 load(path)/_find 命中连接（未命中或 status 为 "withdrawn" 时抛 LinkError）；`_signer.verify_for(...)` 返回值中 ok 非真时按 `ver.get("on_fail") or "degrade"` 处置——"reject" 抛 LinkError，其余置 isolated/degraded 后返回 ok False；验签通过则 delta=UP_STEP if positive else -DOWN_STEP，P_trust 置 `round(max(0.0, min(cap, before + delta)), 6)`（cap 取 `link.get("p_trust_cap") or 0.0`），负证据且新 P_trust<DEGRADE_BELOW 且原状态在 IN_TRUST 时降级，返回 ok True、link、delta。
def observe(peer: str, *, evidence: str, positive: bool = True,
            subsystem: str = None, peer_signature: str = None,
            path: str = None, signers_file: str = None,
            actor: str = "system") -> dict:
    """记录一条跨节点观测证据并调整 P_trust。

    · 正证据 `+UP_STEP`；负证据 `-DOWN_STEP`，跌破 `DEGRADE_BELOW` 自动降级；
    · 策略要求签名而验签失败 → 按 `on_verify_fail` 处置（宪章第七条）。
    """
    data = load(path)
    lid, link = _find(data, peer)
    if not link:
        raise LinkError(f"连接不存在：{peer}（需先 handshake）")
    if link["status"] == "withdrawn":
        raise LinkError(f"连接已退出：{peer}")

    payload = evidence_payload(link["peer_node_id"], evidence, positive)
    ver = _signer.verify_for(subsystem or link.get("subsystem") or None, payload,
                             peer_signature or "",
                             ctx={"peer": link["peer_node_id"],
                                  "action": "evidence"},
                             action="evidence", path=signers_file)
    if not ver.get("ok"):
        on_fail = ver.get("on_fail") or "degrade"
        if on_fail == "reject":
            raise LinkError(
                f"证据签名校验失败（策略={on_fail}）：{ver.get('reason')}")
        _set_status(link, "isolated" if on_fail == "isolate" else "degraded",
                    actor=actor, clause="宪章第七条", reason=ver.get("reason"))
        _commit(data, lid, link, path)
        return {"ok": False, "link": link, "on_fail": on_fail,
                "reason": ver.get("reason")}

    delta = UP_STEP if positive else -DOWN_STEP
    cap = float(link.get("p_trust_cap") or 0.0)
    before = float(link.get("p_trust") or 0.0)
    link["p_trust"] = round(max(0.0, min(cap, before + delta)), 6)
    link["evidence_count"] = int(link.get("evidence_count") or 0) + 1
    link["last_observed"] = time.time()
    link["decay"] = 0.0
    if ver.get("required"):
        link.setdefault("signatures", {})["peer_evidence"] = {
            "signer": ver.get("signer"), "signature": peer_signature or "",
            "verified": True, "at": time.time()}

    _audit(link, "observe", by=actor, clause="宪章第二十四条（留痕）",
           evidence=str(evidence)[:200], positive=bool(positive),
           delta=delta, p_trust=link["p_trust"])

    # 反例击穿：不因历史高分豁免（宪章第七条）
    if not positive and link["p_trust"] < DEGRADE_BELOW \
            and link["status"] in IN_TRUST:
        _set_status(link, "degraded", actor=actor,
                    clause="宪章第七条（一次异常即降级）",
                    reason=f"负证据使 P_trust={link['p_trust']} < {DEGRADE_BELOW}")

    _commit(data, lid, link, path)
    return {"ok": True, "link": link, "delta": delta}


# --------------------------------------------------------------------------
# 状态迁移（宪章第二十二条响应阶梯）
# --------------------------------------------------------------------------

# 生效条件：status 不在 STATUS 中抛 LinkError；否则写入 link["status"]=status，status 为 "isolated" 时同时置 p_trust_cap=CAP_ISOLATED、p_trust=0.0，并写留痕（clause 为假值含 None/空串时回落「宪章第二十二条（响应阶梯）」），返回 link。
def _set_status(link: dict, status: str, *, actor: str = "system",
                clause: str = None, reason: str = None):
    if status not in STATUS:
        raise LinkError(f"未知状态：{status}")
    old = link.get("status")
    link["status"] = status
    if status == "isolated":
        link["p_trust_cap"] = CAP_ISOLATED
        link["p_trust"] = 0.0
    _audit(link, f"status:{old}->{status}", by=actor,
           clause=clause or "宪章第二十二条（响应阶梯）", reason=reason)
    return link


# 生效条件：传入 peer 与 status 时，先 load(path)/_find 定位（未命中抛 LinkError），再 `_set_status(link, status, actor=actor, reason=reason)` 并 `_commit(data, lid, link, path)`，返回 `{"ok": True, "link": link}`。
def _transition(peer, status, *, reason=None, path=None, actor="system"):
    data = load(path)
    lid, link = _find(data, peer)
    if not link:
        raise LinkError(f"连接不存在：{peer}")
    _set_status(link, status, actor=actor, reason=reason)
    _commit(data, lid, link, path)
    return {"ok": True, "link": link}


# 生效条件：连接存在且 link["status"]=="probation" 且 float(link.get("probation_until") or 0) - time.time() <= 0 时置 normal、promoted_at，提交并返回 {'ok': True, 'link'}；连接不存在、非 probation 或观察期未满均抛 LinkError。
def promote(peer: str, *, path: str = None, actor: str = "system") -> dict:
    """观察期满且无异常 → normal。"""
    data = load(path)
    lid, link = _find(data, peer)
    if not link:
        raise LinkError(f"连接不存在：{peer}")
    if link["status"] != "probation":
        raise LinkError(f"仅 probation 可转正，当前 {link['status']}")
    left = float(link.get("probation_until") or 0) - time.time()
    if left > 0:
        raise LinkError(f"观察期未满（剩余 {int(left)}s）")
    _set_status(link, "normal", actor=actor,
                clause="宪章第七条反面（观察期满无异常）")
    link["promoted_at"] = time.time()
    _commit(data, lid, link, path)
    return {"ok": True, "link": link}


# 生效条件：传入 peer 时无条件返回 `_transition(peer, "degraded", reason=reason, path=path, actor=actor)`，reason/path/actor 原样透传。
def degrade(peer: str, *, reason: str = None, path: str = None,
            actor: str = "system") -> dict:
    return _transition(peer, "degraded", reason=reason, path=path, actor=actor)


# 生效条件：传入 peer 时无条件返回 `_transition(peer, "isolated", reason=reason, path=path, actor=actor)`，reason/path/actor 原样透传。
def isolate(peer: str, *, reason: str = None, path: str = None,
            actor: str = "system") -> dict:
    return _transition(peer, "isolated", reason=reason, path=path, actor=actor)


# 生效条件：传入 peer 时无条件返回 `_transition(peer, "withdrawn", reason=reason, path=path, actor=actor)`，reason/path/actor 原样透传（30 天冷静期不在本函数内校验）。
def withdraw(peer: str, *, reason: str = None, path: str = None,
             actor: str = "system") -> dict:
    """声明退出（宪章第二十一条附 3：30 天冷静期由上层流程保证）。"""
    return _transition(peer, "withdrawn", reason=reason, path=path, actor=actor)


# --------------------------------------------------------------------------
# 衰减（无观测向初值回归）
# --------------------------------------------------------------------------

def decay_all(*, path: str = None, now: float = None,
              actor: str = "system") -> dict:
    data = load(path)
    now = now or time.time()
    changed = []
    for lid, link in (data.get("links") or {}).items():
        if link.get("status") not in IN_TRUST:
            continue
        last = link.get("last_observed") or link.get("created_at") or now
        days = max(0.0, (now - float(last)) / 86400.0)
        if days <= 0:
            continue
        factor = 0.5 ** (days / DECAY_DAYS)
        before = float(link.get("p_trust") or 0.0)
        cap = float(link.get("p_trust_cap") or 0.0)
        after = max(0.0, min(cap, round(
            P_TRUST_INIT + (before - P_TRUST_INIT) * factor, 6)))
        link["decay"] = round(before - after, 6)
        if abs(link["decay"]) > 1e-9:
            link["p_trust"] = after
            _audit(link, "decay", by=actor, clause="§3.2（无观测向初值回归）",
                   days=round(days, 3), p_trust=after)
            changed.append({"link_id": lid, "peer_node_id": link["peer_node_id"],
                            "from": before, "to": after, "decay": link["decay"]})
    if changed:
        save(data, path)
    return {"ok": True, "changed": changed, "count": len(changed)}


# --------------------------------------------------------------------------
# 查询 / 自描述 / CLI
# --------------------------------------------------------------------------

# 生效条件：`_find(load(path), peer)` 命中时返回该 link；未命中时抛 LinkError。
def get(peer: str, *, path: str = None) -> dict:
    lid, link = _find(load(path), peer)
    if not link:
        raise LinkError(f"连接不存在：{peer}")
    return link


# 生效条件：status 为真值时过滤掉 `link.get("status") != status` 的连接，subsystem 为真值时过滤掉 `link.get("subsystem") != subsystem` 的连接（两者为 None/空串则不过滤）；返回 `{"file": links_file(path), "count": len(out), "links": out}`，out 按 (status, peer_node_id) 排序。
def ls(*, path: str = None, status: str = None, subsystem: str = None) -> dict:
    data = load(path)
    out = []
    for lid, link in (data.get("links") or {}).items():
        if status and link.get("status") != status:
            continue
        if subsystem and link.get("subsystem") != subsystem:
            continue
        row = {k: link.get(k) for k in
               ("peer_node_id", "status", "p_trust", "p_trust_cap",
                "peer_theory_version", "version_aligned",
                "evidence_count", "subsystem")}
        row["link_id"] = lid
        out.append(row)
    out.sort(key=lambda x: (x.get("status") or "", x.get("peer_node_id") or ""))
    return {"file": links_file(path), "count": len(out), "links": out}


# 生效条件：无 required 形参，调用即返回自描述 dict，其中 "file" 由无参 `links_file()` 决定（随 LINKS_FILE_ENV 环境变量与 DEFAULT_LINKS_FILE 回落变化），其余字段由 STATUS 列表与模块级常量（P_TRUST_INIT/UP_STEP/DOWN_STEP/DEGRADE_BELOW/DECAY_DAYS/PROBATION_SECONDS/CAP_*）拼成。
def catalog() -> dict:
    return {
        "layer": "连接层（蜂群互联层1）",
        "question": "跨节点：我信你多少",
        "file": links_file(),
        "status": list(STATUS),
        "p_trust": {"init": P_TRUST_INIT, "up_step": UP_STEP,
                    "down_step": DOWN_STEP, "degrade_below": DEGRADE_BELOW,
                    "decay_days": DECAY_DAYS,
                    "probation_seconds": PROBATION_SECONDS,
                    "note": "数值未标定（占位）；方向性约束：降快于升"},
        "caps": {"aligned": CAP_ALIGNED, "incomplete": CAP_INCOMPLETE,
                 "misaligned": CAP_MISALIGNED, "isolated": CAP_ISOLATED},
        "signature": {"delegated_to": "md_cg.signer",
                      "decision": "D-4：内核只定义契约，子系统自决用法"},
        "clauses": {"handshake": "宪章第二十八条", "degrade": "宪章第七条",
                    "ladder": "宪章第二十二条", "audit": "宪章第二十四条"},
        "position_weights": {
            "module": "md_cg.weights",
            "formula": "P_trust = f(一致性, 位置可预测性, 版本对齐度)",
            "note": "位置偏好序已标定；数值未标定（占位）",
            "classes": {VIEWPOINT: "认知视角（3 项都涉及，不设零）",
                        FUNCTIONAL: "功能单元（身份即排除）"},
            "daily_eval": "设计者为元参照系，不参与日常评估",
        },
    }


# 生效条件：传入 obj 时执行 `print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))`，无返回值（不可序列化对象经 default=str 转字符串）。
def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


# 生效条件：argv 为 None 时 argparse 取 sys.argv，子命令为 required；a.cmd 为 catalog/ls/handshake/observe/promote|degrade|isolate|withdraw/show/decay 时分别以 a.links_file（──links-file）、a.status、peer、a.evidence、`positive=not a.negative`、a.reason、a.signers_file 等分派执行；捕获 LinkError 打印到 stderr 并返回 2，否则返回 0（argparse 自身错误退出不在本段返回值内）。
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m md_cg.links",
        description="连接层：跨节点信任状态（P_trust / 状态机 / 留痕）")
    ap.add_argument("--links-file", default=None,
                    help="连接文件（默认 ~/.mdcg/_links.json）")
    ap.add_argument("--signers-file", default=None, help="子系统签名策略文件")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("catalog", help="连接层自描述")
    p_ls = sub.add_parser("ls", help="列出连接")
    p_ls.add_argument("--status", default=None, choices=list(STATUS))

    p_h = sub.add_parser("handshake", help="握手建档")
    p_h.add_argument("peer")
    p_h.add_argument("--peer-version", default=None)
    p_h.add_argument("--position-map", default=None, help="如 record=record,verify=verify")
    p_h.add_argument("--no-charter", action="store_true", default=False)
    p_h.add_argument("--subsystem", default=None)
    p_h.add_argument("--peer-signature", default=None)

    p_o = sub.add_parser("observe", help="记录观测证据")
    p_o.add_argument("peer")
    p_o.add_argument("--evidence", required=True)
    p_o.add_argument("--negative", action="store_true", default=False)
    p_o.add_argument("--peer-signature", default=None)

    for nm in ("promote", "degrade", "isolate", "withdraw"):
        pp = sub.add_parser(nm, help=f"状态迁移：{nm}")
        pp.add_argument("peer")
        pp.add_argument("--reason", default=None)

    p_s = sub.add_parser("show", help="查看单个连接")
    p_s.add_argument("peer")
    sub.add_parser("decay", help="按无观测时长执行衰减")

    a = ap.parse_args(argv)
    try:
        if a.cmd == "catalog":
            _print(catalog())
        elif a.cmd == "ls":
            _print(ls(path=a.links_file, status=a.status))
        elif a.cmd == "handshake":
            pm = None
            if a.position_map:
                pm = dict(x.split("=", 1) for x in a.position_map.split(",")
                          if "=" in x)
            th = {"version": a.peer_version} if a.peer_version else None
            _print(handshake(a.peer, peer_theory=th, position_map=pm,
                             declared_charter=not a.no_charter,
                             subsystem=a.subsystem,
                             peer_signature=a.peer_signature,
                             path=a.links_file, signers_file=a.signers_file))
        elif a.cmd == "observe":
            _print(observe(a.peer, evidence=a.evidence, positive=not a.negative,
                           peer_signature=a.peer_signature,
                           path=a.links_file, signers_file=a.signers_file))
        elif a.cmd in ("promote", "degrade", "isolate", "withdraw"):
            _print(globals()[a.cmd](a.peer, reason=a.reason, path=a.links_file))
        elif a.cmd == "show":
            _print(get(a.peer, path=a.links_file))
        elif a.cmd == "decay":
            _print(decay_all(path=a.links_file))
    except LinkError as e:
        print(f"[md_cg.links] {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())