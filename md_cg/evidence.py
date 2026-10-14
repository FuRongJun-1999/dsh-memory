# -*- coding: utf-8 -*-
"""跨节点证据存储（蜂群互联 v0.3）。

攻 §9.1 盲区：`identity.infer_position` 只统计**本根**带 `subject:<id>` 标签的
证据节点，跨节点时对端观测对本节点不可见。本模块给出最小可测的交换机制：

  ① **节点名片**（card）——`node_id` / 根路径 / 版本状态 / 签名器公开信息；
  ② **证据包**（pack）——从本根导出「我对某主体的观测」，**由本节点签名**；
  ③ **导入**（import）——验签 → 落本根（带 `source:<node>` 标签）→ 可审计、可拒收。

设计边界（承 D-1 / D-4）：

  · 内核**不做密码学**：签名/验签一律经 `signer.sign_for / verify_for`，
    跨节点证据要求子系统策略 `sign_on` 含 `evidence`（由智能体自决）；
  · 内核**不保证全局共识**（0.0.3 局部不可知）：只保证「来源可溯 + 可拒收 + 留痕」；
  · 证据是**他证**（来源节点对主体的观测），不是主体自证；自证走 `identity.anchor`；
  · **禁止转手**：已导入的跨节点证据（带 `xnode:cross`）不参与再次导出，
    否则 A 可以把「C 说 B 怎样」洗成「A 说 B 怎样」，来源链断裂。

诚实边界：本层验证的是「**这条证据确实来自该节点**」，
**不是**「这条证据为真」——后者需节点侧的可信执行，属工程侧责任。

零第三方依赖。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time

from . import crypto as _crypto
from . import identity as _identity
from . import security as _sec
from . import signer as _signer
from .datapath import aux_root
from .fsutil import publish

NODE_ID_ENV = "MDCG_NODE_ID"
SWARM_DIR_ENV = "MDCG_SWARM_DIR"
ROOT_ENV = "MDCG_ROOT"

DEFAULT_DIR = aux_root()
DEFAULT_SWARM_DIR = os.path.join(DEFAULT_DIR, "swarm")

SUBSYSTEM = "swarm"          # 子系统名：智能体可对它声明签名策略（D-4）
SIGN_ACTION = "evidence"
SCHEMA = 1
KIND = "mdcg.evidence.pack"
CARD_KIND = "mdcg.node.card"

TAG_XNODE = "xnode:cross"
SOURCE_PREFIX = "source:"

# ---- issue #191：导入侧的层/重要度夹紧与旧包重放台账（三处收口） ----
#: 落层白名单：对端声明**不得**自选受保护层（protect.PROTECTED_LAYERS = self/anchor）
#: 或 goals/structural 一类特殊层，一律改落 knowledge。
IMPORT_LAYERS = ("knowledge", "contextual")
#: 导入重要度上限。**必须低于** protect.AUTO_PROTECT_IMPORTANCE（0.70）——否则对端
#: 一条声明就能把节点变成不可遗忘（属主 mdcg_forget 直接 ProtectionError）。
IMPORT_IMPORTANCE_MAX = 0.5
#: 已见包版本台账（本根顶层）：xnode id -> 最后一次写入所用包的 created_at。
SEEN_FILE = "_xnode_seen.json"

MAX_ITEMS = 500              # 单包条目上限（防灌包）
MAX_TEXT = 4000              # 单条正文上限

# ---- issue #258：密级面的**单一权威**（不另立判据，直接引既有常量） ----
_SENSITIVITY_ORDER = _sec.SENSITIVITY_ORDER
_ENCRYPTED_LEVELS = set(_crypto.ENCRYPTED_LEVELS)
_AccessDenied = _sec.AccessDenied

# ---- issue #147（2026-10-11）：pack_id 白名单 ----
# 病象：pack_id 未清洗即拼进归档路径（见 write_pack 缺省分支）⇒ 路径穿越；
# 非管理员令牌**一次 import 即可覆写** _keys.json / _tokens.json（实测 k=5 段 ../ 命中）。
# 合法生产者只产 "pack-<12hex>"（见 export_pack「pack["pack_id"] = "pack-" + pid」），
# 故白名单取 ASCII 字母数字与 . _ -，并显式拒 .. 与前导点。
PACK_ID_MAX = 128
PACK_ID_OK = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


class EvidenceError(Exception):
    """跨节点证据层错误（fail-closed）。"""


# --------------------------------------------------------------------------
# 路径与身份
# --------------------------------------------------------------------------

# 生效条件：当传入 path 为真值时返回 path；否则若环境变量 SWARM_DIR_ENV 为真值则返回其值；否则返回模块级常量 DEFAULT_SWARM_DIR。
def swarm_dir(path: str = None) -> str:
    return path or os.environ.get(SWARM_DIR_ENV) or DEFAULT_SWARM_DIR


# 生效条件：当传入 swarm 参数（假值回落到 swarm_dir 的默认逻辑）时，返回 os.path.join(swarm_dir(swarm), "peers")。
def peers_dir(swarm: str = None) -> str:
    return os.path.join(swarm_dir(swarm), "peers")


# 生效条件：当传入 swarm 参数（假值回落到 swarm_dir 的默认逻辑）时，返回 os.path.join(swarm_dir(swarm), "inbox")。
def inbox_dir(swarm: str = None) -> str:
    return os.path.join(swarm_dir(swarm), "inbox")


# 生效条件：当传入 root 为真值时返回 root；否则返回环境变量 ROOT_ENV 的值（可能为 None）。
def _root_of(root: str = None) -> str:
    return root or os.environ.get(ROOT_ENV)


# 生效条件：当 explicit 或环境变量 NODE_ID_ENV strip 后非空时返回该值；否则若 _root_of(root) 返回真值，返回基于规范绝对路径的 'node-<12hex>'；否则抛出 EvidenceError。
def node_id(root: str = None, explicit: str = None) -> str:
    """本节点身份。

    优先 `MDCG_NODE_ID`（生产环境应显式设置，保证跨机器稳定）；
    缺省从根路径派生 `node-<12hex>`（同机可复现，跨机器不保证唯一）。
    """
    # issue #277 类型闸**先于 .strip()**：旧写法 (explicit or env or "").strip()
    # 在 explicit=123 这类非字符串上会漏成 AttributeError（int 没有 strip），
    # 既不是 fail-closed 的错误类、调用方也无法按类型判空。
    # 语义保持：假值 explicit 仍回落环境变量；空串仍是「未提供」⇒ 走派生。
    raw = explicit or os.environ.get(NODE_ID_ENV)
    if raw is not None and not isinstance(raw, str):
        raise EvidenceError(
            f"证据节点 id 必须是字符串：{raw!r}（{type(raw).__name__}）")
    nid = (raw or "").strip()
    if nid:
        # issue #277：本值是**模型/环境可控输入**，而 publish_card 会把它直接
        # 拼进 os.path.join(peers_dir(swarm), nid + ".json")——"../" 可穿越出
        # swarm 目录（实测 MDCG_NODE_ID="../../../evil_pwned" 在 swarm 外落盘）。
        # 旧实现只 strip、零校验 ⇒ 任意文件写。此处**先拦后拼**（同 #147 的
        # 「汇点兜底」与 mdcos._restore_id_ok 的「先拦后读」纪律）：
        # 判据与写面 add() 的 P0-1 白名单**同源**，不是第二份判据。
        err = _node_id_error(nid)
        if err:
            raise EvidenceError(err)
        return nid
    r = _root_of(root)
    if not r:
        raise EvidenceError(
            "无法确定节点身份：请设 MDCG_NODE_ID（推荐）或 MDCG_ROOT")
    key = os.path.normcase(os.path.abspath(r))
    return "node-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


# 生效条件：包内 md_cg.theory 可导入且 _th.check() 成功时返回 {version, accepted, theory_ok}；任何异常（版本层缺失或校验失败）一律吞掉返回 {}，不阻断证据层主流程；
def _theory_state() -> dict:
    try:
        from . import theory as _th
        st = _th.check()
        return {"version": st.get("version"),
                "accepted": list(st.get("accepted_versions") or []),
                "theory_ok": bool(st.get("theory_ok"))}
    except Exception:                              # 版本层缺失不阻断证据层
        return {}


# 生效条件：当传入 obj 时，返回其 json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',',':')).encode("utf-8") 字节。
def _canon(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


# 生效条件：当传入 s 时，返回 str(s) 中每个字符若为字母数字或 '_' '-' 则保留，否则替换为 '_' 的字符串。
def _slug(s) -> str:
    return "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in str(s))


# --------------------------------------------------------------------------
# 节点名片（发现）
# --------------------------------------------------------------------------

# 生效条件：当传入 root、subsystem（默认常量 SUBSYSTEM）、signers_file 时，基于 _signer.policy_for 和 _signer.get_signer 返回名片字典，其中 root 为 os.path.abspath(_root_of(root)) 若 _root_of(root) 真值否则 None。
def card(root: str = None, *, subsystem: str = SUBSYSTEM,
         signers_file: str = None) -> dict:
    """本节点名片：身份 + 版本 + 签名器公开信息（**不含密钥**）。"""
    pol = _signer.policy_for(subsystem, signers_file)
    s = _signer.get_signer(pol.get("signer"))
    r = _root_of(root)
    return {
        "schema": SCHEMA, "kind": CARD_KIND,
        "node_id": node_id(root),
        "root": os.path.abspath(r) if r else None,
        "theory": _theory_state(),
        "signer": s.public(),
        "subsystem": subsystem,
        "policy": {"sign_on": list(pol.get("sign_on") or []),
                   "require_peer_signature": bool(pol.get("require_peer_signature")),
                   "on_verify_fail": pol.get("on_verify_fail")},
        "created_at": time.time(),
    }


# 生效条件：当传入 root、swarm、subsystem（默认常量 SUBSYSTEM）、signers_file 时，调用 card 得到 c，将 c 以 JSON 写入 peers_dir(swarm)/<c["node_id"]>.json，返回 {"ok": True, "file": p, "card": c}。
def publish_card(root: str = None, *, swarm: str = None,
                 subsystem: str = SUBSYSTEM, signers_file: str = None) -> dict:
    """把本节点名片写入共享目录 `peers/<node_id>.json`（0600）。"""
    c = card(root, subsystem=subsystem, signers_file=signers_file)
    # issue #277 **汇点兜底**（同 #147 的 write_pack 纪律）：即使调用方绕过
    # node_id() 直接构造 card，恶意 node_id 也一律 fail-closed——不静默落盘。
    err = _node_id_error(c.get("node_id"))
    if err:
        raise EvidenceError(err)
    base = os.path.realpath(peers_dir(swarm))
    p = os.path.join(peers_dir(swarm), c["node_id"] + ".json")
    # realpath 归一后判包含性：拒 ../ 穿越、绝对路径、盘符、UNC、空字节
    # （白名单已挡住这些形态，此处是**第二道**，防白名单将来被放宽）。
    try:
        real = os.path.realpath(p)
    except ValueError as exc:                    # 空字节等非法字符
        raise EvidenceError(f"名片归档路径非法：{exc}")
    if real != base and not real.startswith(base + os.sep):
        raise EvidenceError(
            f"名片归档路径越界（必须落在 peers 目录内）：{p!r}")
    _write_json(p, c)
    return {"ok": True, "file": p, "card": c}


# 生效条件：当 peers_dir(swarm) 是目录时，遍历其中 .json 文件，加载为 dict 且 kind 等于常量 CARD_KIND 的名片，若 exclude_self 为真则排除 node_id 等于 node_id(root) 的名片（node_id(root) 抛 EvidenceError 时 self_id 为 None 不排除），返回按文件名排序的列表及计数；目录不存在则返回空列表。
def peers(swarm: str = None, *, exclude_self: bool = True,
          root: str = None) -> dict:
    """发现共享目录里的对端名片（按 node_id 排序）。"""
    d = peers_dir(swarm)
    out, self_id = [], None
    if exclude_self:
        try:
            self_id = node_id(root)
        except EvidenceError:
            self_id = None
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, fn), "r", encoding="utf-8") as f:
                    c = json.load(f)
            except (OSError, ValueError):
                continue
            if not isinstance(c, dict) or c.get("kind") != CARD_KIND:
                continue
            if self_id and c.get("node_id") == self_id:
                continue
            out.append(c)
    return {"dir": d, "count": len(out), "peers": out}


# --------------------------------------------------------------------------
# 证据包：导出
# --------------------------------------------------------------------------

_PACK_FIELDS = ("schema", "kind", "pack_id", "from_node", "from_root",
                "theory", "created_at", "subjects", "items")


# 生效条件：当传入 pack 字典时，返回仅含模块级常量 _PACK_FIELDS 中字段（缺失字段取 pack.get(k) 得到 None）的规范化 JSON 字节。
def _pack_payload(pack: dict) -> bytes:
    """签名载荷：固定字段 + 排序序列化，同参数必同字节。"""
    body = {}
    for k in _PACK_FIELDS:
        body[k] = pack.get(k)
    return _canon(body)


# 生效条件：当传入 cg、subjects、since 时，遍历 cg.index["nodes"] 中按 node_id 排序的节点，仅收集标签含常量 TAG_OBS、不含 TAG_ANCHOR/TAG_TRAIT、不含 TAG_XNODE、能提取 subject: 标签且该 subject 在 subjects（subjects 为真时）或不限制（subjects 假值时）、且若 since 为真且 ts 为真则要求 float(ts) >= float(since) 的节点，返回含 node_id、subject、text（截断 MAX_TEXT）、kind、role、layer、过滤后的 tags、importance、verification_basis、ts 的列表。
# ---- issue #258（2026-10-14）：跨节点证据包通路丢密级 ----
# 病象：`_collect` 产出的条目**不带 sensitivity**，`import_pack` 又经
# `identity.observe`（签名无该形参）落盘 ⇒ 走 `MdCGSecure.add` 的缺省
# `DEFAULT_SENSITIVITY="internal"`。而 `crypto.ENCRYPTED_LEVELS =
# ("private","secret")` ⇒ 发送方盘上是密文、接收方盘上是**明文**，且
# `import_pack` 默认 `archive=True` 把整包明文 JSON 再落一份到收件箱。
# 实测：A 侧 private（盘上无明文）→ B 侧 internal（盘上明文）+ 收件箱明文。
#
# 收口三处：① 本条读数进包；② 导入侧 fail-closed 校验（缺字段/非字符串/
# 未知档一律不收，不降级）；③ 包内含加密档 ⇒ 不归档（归档是明文 JSON）。
def _node_sensitivity(cg, nid):
    """读节点密级。**与 #164 同源**（`subgraph.node_sensitivity`），不另立判据。"""
    from . import subgraph as _sg
    try:
        return _sg.node_sensitivity(cg, nid)
    except Exception:                              # noqa: BLE001
        return None


def _collect(cg, subjects=None, since=None) -> list:
    """收集本根**本地原始**观测证据（排除档案节点与已导入的跨节点证据）。"""
    want = set(subjects or [])
    items = []
    nodes = cg.index.get("nodes") or {}
    for nid in sorted(nodes):
        e = nodes[nid]
        tg = set(e.get("tags") or [])
        if _identity.TAG_OBS not in tg:
            continue
        if tg & {_identity.TAG_ANCHOR, _identity.TAG_TRAIT}:
            continue
        if TAG_XNODE in tg:                        # 禁止转手（防洗证据）
            continue
        subj = ""
        for t in tg:
            if isinstance(t, str) and t.startswith("subject:"):
                subj = t[len("subject:"):]
                break
        if not subj or (want and subj not in want):
            continue
        node = cg.get(nid) or {}
        fm = node.get("frontmatter") or {}
        ts = fm.get("ts") or fm.get("created_at") or e.get("ts") or 0
        if since and ts and float(ts) < float(since):
            continue
        items.append({
            "node_id": nid,
            "subject": subj,
            "text": (node.get("content") or "")[:MAX_TEXT],
            "kind": fm.get("kind"),
            "role": fm.get("role"),
            "layer": e.get("layer"),
            "tags": sorted(t for t in tg
                           if isinstance(t, str)
                           and not t.startswith("subject:")
                           and not t.startswith(SOURCE_PREFIX)
                           and t != TAG_XNODE),
            "importance": fm.get("importance"),
            "verification_basis": (e.get("verification_basis")
                                   or fm.get("verification_basis")),
            # issue #258：密级随条目出根（此前整条通路不带该字段）
            "sensitivity": _node_sensitivity(cg, nid),
            "ts": ts,
        })
    return items


# 生效条件：当传入 cg、subjects、since、swarm、subsystem（默认 SUBSYSTEM）、signers_file、require_signature（默认 True）时，收集证据并截断至常量 MAX_ITEMS，用 _signer.sign_for 以常量 SIGN_ACTION 签名，若 require_signature 为真且签名未成功则抛出 EvidenceError，否则返回含 pack、count、truncated、signed 的字典。
def export_pack(cg, *, subjects=None, since=None, swarm: str = None,
                subsystem: str = SUBSYSTEM, signers_file: str = None,
                require_signature: bool = True) -> dict:
    """导出本节点对（指定）主体的观测证据包，并签名。

    `require_signature=True`（默认）：策略未对 `evidence` 签名即抛错——
    跨节点证据没有签名就不可溯源，宁可不产出。
    """
    items = _collect(cg, subjects=subjects, since=since)
    truncated = len(items) > MAX_ITEMS
    items = items[:MAX_ITEMS]
    nid = node_id(getattr(cg, "root", None))
    pack = {
        "schema": SCHEMA, "kind": KIND,
        "from_node": nid,
        "from_root": os.path.abspath(getattr(cg, "root", "") or ""),
        "theory": _theory_state(),
        "created_at": time.time(),
        "subjects": sorted(set(subjects or [])),
        "items": items,
    }
    pid = hashlib.sha256(_canon({"n": nid, "t": pack["created_at"],
                                 "c": len(items)})).hexdigest()[:12]
    pack["pack_id"] = "pack-" + pid

    sigres = _signer.sign_for(subsystem, _pack_payload(pack),
                              action=SIGN_ACTION, path=signers_file)
    pack["sig"] = {"signer": sigres.get("signer"),
                   "signature": sigres.get("signature") or "",
                   "signed": bool(sigres.get("signed"))}
    if require_signature and not pack["sig"]["signed"]:
        raise EvidenceError(
            f"子系统 {subsystem} 策略未对 {SIGN_ACTION} 签名，证据包不可溯源。"
            f"请先声明：set_policy({subsystem!r}, sign_on=['handshake','{SIGN_ACTION}'])")
    return {"ok": True, "pack": pack, "count": len(items),
            "truncated": truncated, "signed": pack["sig"]["signed"]}


# 生效条件：当传入 pack、path、swarm 时，若 path 为假值则用 os.path.join(inbox_dir(swarm), f"{_slug(pack.get('from_node'))}__{pack.get('pack_id')}.json") 生成路径，将 pack 以 JSON 写入该路径并返回 {"ok": True, "file": path}。
def write_pack(pack: dict, path: str = None, swarm: str = None) -> dict:
    """把证据包落盘到收件箱（或指定路径）。"""
    if not path:
        # issue #147 **汇点兜底**：与 _validate 同源的白名单——即使调用方绕过
        # import_pack（直接调本函数），恶意 pack_id 也一律 fail-closed，
        # 且异常类型统一为 EvidenceError（不再漏成 OSError/ValueError）。
        perr = _pack_id_error(pack.get("pack_id"))
        if perr:
            raise EvidenceError(perr)
        base = os.path.realpath(inbox_dir(swarm))
        path = os.path.join(inbox_dir(swarm),
                            f"{_slug(pack.get('from_node'))}__{pack.get('pack_id')}.json")
        # issue #147（2026-10-11）：归档目标必须落在收件箱根内——realpath 归一后判
        # 包含性，越界即 fail-closed（拒 ../ 穿越、绝对路径、盘符、UNC、空字节）。
        # 只约束**由 pack 数据派生**的缺省路径；显式 path 是调用方（CLI --out /
        # MCP out）自选落点，属 API 层调用者权限，不在此收窄（既有调用面两处）。
        try:
            real = os.path.realpath(path)
        except ValueError as exc:                    # 空字节等非法字符
            raise EvidenceError(f"证据包归档路径非法：{exc}")
        if real != base and not real.startswith(base + os.sep):
            raise EvidenceError(
                f"证据包归档路径越界（必须落在收件箱内）：{path!r}")
    _write_json(path, pack)
    return {"ok": True, "file": path}


# --------------------------------------------------------------------------
# 证据包：导入
# --------------------------------------------------------------------------

# 生效条件：当 src 是 dict 时直接返回 src；否则以 src 为路径打开 JSON 文件并返回 json.load(f)。
def _read_pack(src) -> dict:
    if isinstance(src, dict):
        return src
    with open(src, "r", encoding="utf-8") as f:
        return json.load(f)


# 生效条件：pid 为 pack["pack_id"]（任意类型）；合规返回空字符串，否则返回中文理由——非 str/空、超 PACK_ID_MAX、含 PACK_ID_OK 之外字符、以点开头或含连续两点各一条。**单一真源**：_validate 与 write_pack 汇点共用本函数，规则只有一份。
def _node_id_error(nid) -> str:
    """node_id 白名单判据（issue #277）。

    判据与写面 MdCG.add() 的 P0-1 白名单**同源**（同一 _NODE_ID_RE、同一
    ".." 禁令、同一 _NODE_ID_FORBIDDEN），不是第二份判据——避免两套口径漂移。
    空串返回错误文案（调用方已 strip 过，空串即「未提供」）。
    """
    from .mdcg import _NODE_ID_RE, _NODE_ID_FORBIDDEN
    if not isinstance(nid, str) or not nid:
        return f"证据节点 id 必须是非空字符串：{nid!r}"
    if len(nid) > 128:
        return f"证据节点 id 过长：{len(nid)} > 128"
    if ".." in nid:
        return f"证据节点 id 形似路径穿越（拒 ..）：{nid!r}"
    if nid in _NODE_ID_FORBIDDEN:
        return f"证据节点 id 是保留字：{nid!r}"
    if not _NODE_ID_RE.match(nid):
        return (f"证据节点 id 含非法字符（须匹配 {_NODE_ID_RE.pattern}）：{nid!r}")
    return ""


def _pack_id_error(pid) -> str:
    """pack_id 白名单判据（issue #147）。"""
    if not isinstance(pid, str) or not pid:
        return "证据包缺少 pack_id（归档不可命名）"
    if len(pid) > PACK_ID_MAX:
        return f"证据包 pack_id 过长：{len(pid)} > {PACK_ID_MAX}"
    bad_ch = sorted({ch for ch in pid if ch not in PACK_ID_OK})
    if bad_ch:
        return (f"证据包 pack_id 含非法字符 {bad_ch}"
                f"（只允许字母数字与 . _ -）：{pid!r}")
    if pid.startswith(".") or ".." in pid:
        return f"证据包 pack_id 形似路径（拒 .. 与前导点）：{pid!r}"
    return ""


# 生效条件：当 pack 为 dict 且 kind 等于常量 KIND、int(pack.get("schema") or 0) 不大于常量 SCHEMA、from_node strip 后非空、items 为 list、且 _pack_id_error(pack.get("pack_id")) 为空时返回空字符串；否则按序返回对应错误字符串（非 dict、kind 不符、schema 过新、缺 from_node、缺 items、pack_id 不合法）。
def _validate(pack: dict) -> str:
    if not isinstance(pack, dict):
        return "证据包不是 JSON 对象"
    if pack.get("kind") != KIND:
        return f"不是证据包（kind={pack.get('kind')!r}）"
    if int(pack.get("schema") or 0) > SCHEMA:
        return f"证据包 schema 过新：{pack.get('schema')} > {SCHEMA}"
    if not (pack.get("from_node") or "").strip():
        return "证据包缺少 from_node（来源不可溯）"
    if not isinstance(pack.get("items"), list):
        return "证据包缺少 items"
    # issue #147：pack_id 进归档文件名 ⇒ 必须过白名单（拒穿越/绝对路径/盘符/UNC/空字节）。
    return _pack_id_error(pack.get("pack_id"))


# 生效条件：当传入 from_node 和 orig 时，返回 f"xnode_{_slug(from_node)}_{_slug(orig)}"。
def _xnode_id(from_node: str, orig: str) -> str:
    return f"xnode_{_slug(from_node)}_{_slug(orig)}"


# 生效条件：当传入 pack、reason、swarm、**kw 时，构建含 at、reason、from_node、pack_id 及 kw 中非 None 项的拒绝记录，尝试追加到 inbox_dir(swarm)/_rejected.jsonl（OSError 忽略），返回 {"ok": False, "rejected": True, "reason": reason, "from_node": ...} 并合并 kw 中非 None 项。
def _item_sensitivity(it: dict):
    """校验包内条目的密级 → (密级, 拒收理由)。**fail-closed**。

    issue #258：缺字段/非字符串/未知档一律返回理由（调用方跳过，不写盘）。
    旧格式包（无 sensitivity）因此一律拒收——有意的行为变更。
    """
    raw = it.get("sensitivity")
    if raw is None:
        return None, "条目缺 sensitivity 字段（旧格式包一律拒收）"
    if not isinstance(raw, str):
        return None, "条目 sensitivity 非字符串：%r" % (raw,)
    s = raw.strip().lower()
    if s not in _SENSITIVITY_ORDER:
        return None, "条目 sensitivity 未知档：%r（合法档 %s）" % (
            raw, "/".join(_SENSITIVITY_ORDER))
    return s, ""


def _note_reject(pack: dict, reason: str, swarm: str = None, **kw) -> dict:
    rec = {"at": time.time(), "reason": reason,
           "from_node": (pack or {}).get("from_node"),
           "pack_id": (pack or {}).get("pack_id")}
    rec.update({k: v for k, v in kw.items() if v is not None})
    try:
        from .fsutil import append_jsonl
        os.makedirs(inbox_dir(swarm), exist_ok=True)
        append_jsonl(os.path.join(inbox_dir(swarm), "_rejected.jsonl"), rec)
    except OSError:
        pass
    out = {"ok": False, "rejected": True, "reason": reason,
           "from_node": rec.get("from_node")}
    out.update({k: v for k, v in kw.items() if v is not None})
    return out


# 生效条件：当传入 cg、src、subsystem（默认 SUBSYSTEM）、swarm、signers_file、archive（默认 True）时，依次读取 src 为 pack、_validate 校验、来源 node_id 不等于本节点、_signer.verify_for 验签成功、且有签名或 signer 等于 "null" 方可通过；通过则对 pack["items"] 前常量 MAX_ITEMS 项中 subject/text 非空者以 _identity.observe 写入（带常量 TAG_XNODE 和 SOURCE_PREFIX 标签，importance 默认 0.5，verification_basis 默认 "data"），统计 written/skipped，若 archive 为真则写包到收件箱，返回含 ok、from_node、pack_id、imported、skipped、truncated、node_ids、archived 的字典；任一拒绝分支调用 _note_reject 返回拒绝结果。
def _seen_path(cg) -> str:
    """已见台账路径（本根顶层）。cg.root 不可用时返回空串（调用方按无账处理）。"""
    root = getattr(cg, "root", None)
    return os.path.join(str(root), SEEN_FILE) if root else ""


def _load_seen(cg) -> dict:
    """读台账。缺文件 / 坏 JSON / 非对象一律按空账——台账是防重放，不是写入前提。"""
    p = _seen_path(cg)
    if not p:
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_seen(cg, seen: dict) -> None:
    """落盘台账。失败**不逃逸**（同上：台账不是写入前提）。"""
    p = _seen_path(cg)
    if not p:
        return
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(seen, f, ensure_ascii=False, sort_keys=True)
    except OSError:
        pass


def _import_layer(raw):
    """落层白名单（issue #191-A）-> (层, 是否夹紧)。非白名单层一律改落 knowledge。"""
    layer = raw.strip() if isinstance(raw, str) else "knowledge"
    if layer not in IMPORT_LAYERS:
        return "knowledge", 1
    return layer, 0


def _import_importance(raw):
    """重要度夹到 [0, IMPORT_IMPORTANCE_MAX]（issue #191-A）-> (值, 是否夹紧)。

    非数值 / bool / 非有限值按上限处理（与 #151 对越界值回落 0.5 同口径，但上限
    更低——见 IMPORT_IMPORTANCE_MAX 说明）。缺省（None）沿用既有 0.5，不算夹紧。
    """
    if raw is None:
        return IMPORT_IMPORTANCE_MAX, 0
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return IMPORT_IMPORTANCE_MAX, 1
    v = float(raw)
    if not math.isfinite(v):
        return IMPORT_IMPORTANCE_MAX, 1
    if v < 0.0:
        return 0.0, 1
    if v > IMPORT_IMPORTANCE_MAX:
        return IMPORT_IMPORTANCE_MAX, 1
    return v, 0


def import_pack(cg, src, *, subsystem: str = SUBSYSTEM, swarm: str = None,
                signers_file: str = None, archive: bool = True) -> dict:
    """导入对端证据包：验签 → 落本根（带 `source:<node>` 标签）。

    fail-closed：结构不合法、来源即本节点、验签失败、缺签名 → 一律拒收并留痕。
    """
    try:
        pack = _read_pack(src)
    except (OSError, ValueError) as e:
        return _note_reject({}, f"证据包读取失败：{e}", swarm=swarm)

    err = _validate(pack)
    if err:
        return _note_reject(pack, err, swarm=swarm)

    from_node = pack["from_node"].strip()
    if from_node == node_id(getattr(cg, "root", None)):
        return _note_reject(pack, "证据包来源即本节点（拒绝自导入）", swarm=swarm)

    signature = ((pack.get("sig") or {}).get("signature") or "").strip()
    vres = _signer.verify_for(subsystem, _pack_payload(pack), signature,
                              action=SIGN_ACTION, path=signers_file)
    if not vres.get("ok"):
        return _note_reject(pack, f"验签失败：{vres.get('reason') or '未知'}",
                            swarm=swarm, on_fail=vres.get("on_fail"))
    if not signature and (pack.get("sig") or {}).get("signer") != "null":
        return _note_reject(pack, "证据包缺少签名（跨节点证据必须可溯源）",
                            swarm=swarm)

    # issue #191-B：包版本以**签名载荷里的 created_at** 为准（`_pack_payload` 已含它，
    # 对端改不了）。缺省按 0（只能新建、不能覆写）；非数值 / 非有限值整包拒收。
    created = pack.get("created_at")
    if created is None:
        created = 0.0
    elif (isinstance(created, bool) or not isinstance(created, (int, float))
          or not math.isfinite(created)):
        return _note_reject(pack, f"证据包 created_at 非法：{created!r}", swarm=swarm)
    seen = _load_seen(cg)
    items = pack["items"][:MAX_ITEMS]
    written, skipped, replayed, clamped = [], 0, 0, 0
    #: issue #258：拒收理由留痕（此前降级**不可见**——返回体只说 imported: N）
    reasons = []
    try:
        for it in items:
            if not isinstance(it, dict):
                skipped += 1
                reasons.append("条目非字典")
                continue
            subj = (it.get("subject") or "").strip()
            text = (it.get("text") or "").strip()
            if not subj or not text:
                skipped += 1
                reasons.append("条目缺 subject/text")
                continue
            # issue #258：密级 fail-closed。缺字段/非字符串/未知档一律**不写盘**，
            # 绝不回落到 DEFAULT_SENSITIVITY（那正是本件的病象）。旧格式包（无
            # sensitivity）因此一律不收——**有意的行为变更**，与「跨节点证据没有
            # 签名就不可溯源，宁可不产出」同口径。
            sens, why = _item_sensitivity(it)
            if why:
                skipped += 1
                reasons.append(why)
                continue
            tags = [TAG_XNODE, f"{SOURCE_PREFIX}{from_node}"]
            tags += [t for t in (it.get("tags") or [])
                     if isinstance(t, str) and t
                     and not t.startswith("subject:")
                     and not t.startswith(SOURCE_PREFIX)
                     and t not in (TAG_XNODE, _identity.TAG_ANCHOR, _identity.TAG_TRAIT)]
            # issue #191-A：落层白名单 + 重要度夹紧——对端声明不得自选保护级。
            layer, c_layer = _import_layer(it.get("layer"))
            imp, c_imp = _import_importance(it.get("importance"))
            clamped += c_layer + c_imp
            xid = _xnode_id(from_node, it.get("node_id") or subj)
            # issue #191-B：旧包重放不得把新证据覆写回旧内容（含属主删除后复活）。
            last = seen.get(xid)
            if (isinstance(last, (int, float)) and not isinstance(last, bool)
                    and created <= last):
                replayed += 1
                continue
            # issue #191-C：本根里恰好同名的**本地**节点（不带 xnode:cross 标签）不得
            # 被对端覆写——override 只用于更新本来源自己的 xnode。
            prev = (cg.index.get("nodes") or {}).get(xid)
            if prev is not None and TAG_XNODE not in set(prev.get("tags") or []):
                skipped += 1
                reasons.append("同名本地节点（非跨节点证据）不覆写：%s" % xid)
                continue
            try:
                _identity.observe(
                    cg, subj, text,
                    kind=it.get("kind"), role=it.get("role"),
                    layer=layer,
                    tags=tags,
                    importance=imp,
                    verification_basis=it.get("verification_basis") or "data",
                    node_id=xid,
                    sensitivity=sens,
                    override=True)
            except _AccessDenied:
                # issue #258：导入方密级不足 ⇒ **跳过，不降级落盘**（此前会落到
                # 缺省 internal，等于把对端的 private 洗成 internal）。
                skipped += 1
                reasons.append("本节点密级不足（sensitivity=%s）" % sens)
                continue
            written.append(xid)
            seen[xid] = created

    finally:
        _save_seen(cg, seen)

    archived = ""
    archive_skipped = ""
    if archive:
        # issue #258：归档是**明文 JSON**，包内含加密档（private/secret）时
        # 再落一份到收件箱等于绕过 ENCRYPTED_LEVELS ⇒ 不归档并给出理由。
        sealed = sorted({it.get("sensitivity") for it in items
                         if isinstance(it, dict)
                         and str(it.get("sensitivity") or "").strip().lower()
                         in _ENCRYPTED_LEVELS})
        if sealed:
            archive_skipped = ("包内含加密档 %s：归档为明文 JSON，"
                               "跳过以免绕过落盘加密" % "、".join(sealed))
        else:
            try:
                archived = write_pack(pack, swarm=swarm)["file"]
            except (OSError, EvidenceError):
                # issue #147：归档越界（EvidenceError，realpath 兜底）与写盘
                # 失败同等处理——**不逃逸**。修前只捕 OSError：pack_id 带空
                # 字节时 open()/realpath 抛的 ValueError 会**逸出
                # import_pack**（实测），调用方只见崩溃且无留痕；现一并收口。
                archived = ""
    return {"ok": True, "from_node": from_node, "pack_id": pack.get("pack_id"),
            "imported": len(written), "skipped": skipped,
            # issue #191：被夹紧的条目数（层 / 重要度）与因旧包重放而跳过的条目数。
            # 此前返回体只说 imported: N，看不出落了哪一层、也没提示重放。
            "clamped": clamped, "replayed": replayed,
            "truncated": len(pack["items"]) > MAX_ITEMS,
            "node_ids": written, "archived": archived,
            # issue #258：拒收理由（封顶 20 条，防灌包刷屏）+ 归档跳过理由
            "skipped_reasons": reasons[:20],
            "archive_skipped": archive_skipped}


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------

# 生效条件：当传入 cg、subject、source、limit（默认 100）时，收集标签含常量 TAG_XNODE 的节点，若 subject 为真则仅保留 subject 标签等于 subject 的节点，若 source 为真则仅保留 source 标签等于 source 的节点，返回最后 int(limit or 100) 条记录（limit 为假值如 0 时取 100）的 count 与列表。
def evidence(cg, *, subject: str = None, source: str = None,
             limit: int = 100) -> dict:
    """列本根已导入的跨节点证据（按来源/主体过滤）。"""
    out = []
    nodes = cg.index.get("nodes") or {}
    for nid in sorted(nodes):
        e = nodes[nid]
        tg = set(e.get("tags") or [])
        if TAG_XNODE not in tg:
            continue
        subj, src = "", ""
        for t in tg:
            if isinstance(t, str) and t.startswith("subject:"):
                subj = t[len("subject:"):]
            elif isinstance(t, str) and t.startswith(SOURCE_PREFIX):
                src = t[len(SOURCE_PREFIX):]
        if subject and subj != subject:
            continue
        if source and src != source:
            continue
        node = cg.get(nid) or {}
        out.append({"node_id": nid, "subject": subj, "source": src,
                    "layer": e.get("layer"),
                    "content": (node.get("content") or "")[:400]})
    out = out[-int(limit or 100):]
    return {"count": len(out), "evidence": out}


# 生效条件：无参数调用时返回包含模块级常量 SUBSYSTEM、SIGN_ACTION、SWARM_DIR_ENV、NODE_ID_ENV、ROOT_ENV、MAX_ITEMS、MAX_TEXT 及 swarm_dir() 等字段的自描述字典。
def catalog() -> dict:
    return {
        "layer": "跨节点证据存储（蜂群互联 v0.3）",
        "question": "跨节点：你凭什么这么说",
        "blindspot": "§9.1 单根假设——对端观测对本节点不可见",
        "invariants": ["来源可溯", "可拒收", "全程留痕", "禁止转手"],
        "subsystem": SUBSYSTEM,
        "sign_action": SIGN_ACTION,
        "swarm_dir": swarm_dir(),
        "pack_fields": list(_PACK_FIELDS),
        "limits": {"max_items": MAX_ITEMS, "max_text": MAX_TEXT},
        "env": {"node_id": NODE_ID_ENV, "swarm_dir": SWARM_DIR_ENV,
                "root": ROOT_ENV},
        "honest_boundary": "验证的是「证据来自该节点」，不是「证据为真」",
    }


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------

# 生效条件：当传入 path 和 obj 时，在 path 所在目录（若 dirname 为空则 "."）创建目录，将 obj 以 JSON 写入 path+".tmp"（ensure_ascii=False, indent=1, sort_keys=True），尝试 chmod 0600，替换到 path，返回 path。
def _write_json(path: str, obj) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    publish(tmp, path)
    return path


# 生效条件：当传入 root 且 _root_of(root) 返回真值时，以 designer 角色 Principal（tenant 取 os.environ.get("MDCG_TENANT", "default") 的实际值，actor 取 os.environ.get("MDCG_ACTOR", "swarm-cli") 的实际值）打开 MdCGSecure；否则抛出 EvidenceError。
def _open_cg(root: str = None):
    """CLI 用：以 designer 身份打开根（令牌路径仍推荐走 MCP）。"""
    from .mdcos import MdCGSecure
    from .security import Principal
    from .tokens import role_spec
    r = _root_of(root)
    if not r:
        raise EvidenceError("缺少根目录：请设 MDCG_ROOT 或传 --root")
    spec = role_spec("designer")
    p = Principal(tenant=os.environ.get("MDCG_TENANT", "default"),
                  actor=os.environ.get("MDCG_ACTOR", "swarm-cli"),
                  clearance="private", can_write=True, can_admin=True,
                  role="designer", layers_allow=spec["layers_allow"],
                  ops_allow=spec["ops_allow"], auth_mode="legacy_env")
    # autoflush=1（P1b，2026-09-26，与 mcp_server.py:3695-3702 / review_cli._cg
    # 同款）：短命工具进程被 kill 时 close/atexit 兜底不执行，缺省 64 会让
    # 写入停在内存 _dirty、分片日志从未落——逐条落日志保任意退出形态跨进程可见。
    return MdCGSecure(r, principal=p, autoflush=1)


# 生效条件：当传入 obj 时，打印 json.dumps(obj, ensure_ascii=False, indent=1, default=str)。
def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


# 生效条件：argv 为 None 时取 sys.argv[1:]；经 argparse 解析后必填子命令（catalog/card/export/import 等）之一，参数缺失或非法由 argparse 直接退出；返回进程退出码；
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m md_cg.evidence",
        description="跨节点证据存储：名片 / 导出 / 导入（v0.3）")
    ap.add_argument("--root", default=None, help="认知图根（默认 MDCG_ROOT）")
    ap.add_argument("--swarm", default=None, help="共享目录（默认 ~/.mdcg/swarm）")
    ap.add_argument("--signers-file", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("catalog", help="自描述")
    sub.add_parser("card", help="本节点名片")
    sub.add_parser("publish", help="发布名片到共享目录")
    sub.add_parser("peers", help="发现对端名片")

    p_ex = sub.add_parser("export", help="导出证据包")
    p_ex.add_argument("--subject", action="append", default=None)
    p_ex.add_argument("--out", default=None, help="输出文件（默认写收件箱）")

    p_im = sub.add_parser("import", help="导入证据包")
    p_im.add_argument("path")

    p_ls = sub.add_parser("ls", help="列已导入的跨节点证据")
    p_ls.add_argument("--subject", default=None)
    p_ls.add_argument("--source", default=None)
    p_ls.add_argument("--limit", type=int, default=100)

    a = ap.parse_args(argv)
    cg = None
    try:
        if a.cmd == "catalog":
            _print(catalog())
        elif a.cmd == "card":
            _print(card(a.root, signers_file=a.signers_file))
        elif a.cmd == "publish":
            _print(publish_card(a.root, swarm=a.swarm,
                                signers_file=a.signers_file))
        elif a.cmd == "peers":
            _print(peers(a.swarm, root=a.root))
        elif a.cmd == "export":
            cg = _open_cg(a.root)
            res = export_pack(cg, subjects=a.subject, swarm=a.swarm,
                              signers_file=a.signers_file)
            _print(write_pack(res["pack"], path=a.out, swarm=a.swarm)
                   if a.out else res)
        elif a.cmd == "import":
            cg = _open_cg(a.root)
            _print(import_pack(cg, a.path, swarm=a.swarm,
                               signers_file=a.signers_file))
        elif a.cmd == "ls":
            cg = _open_cg(a.root)
            _print(evidence(cg, subject=a.subject, source=a.source,
                            limit=a.limit))
    except (EvidenceError, _signer.SignerError) as e:
        print(f"[md_cg.evidence] {e}", file=sys.stderr)
        return 2
    finally:
        if cg is not None:
            try:
                cg.close()          # 落盘索引，保证跨进程可见
            except Exception:       # noqa: BLE001 —— 关闭失败不掩盖主流程结果
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())