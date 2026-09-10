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
import os
import sys
import time

from . import identity as _identity
from . import signer as _signer

NODE_ID_ENV = "MDCG_NODE_ID"
SWARM_DIR_ENV = "MDCG_SWARM_DIR"
ROOT_ENV = "MDCG_ROOT"

DEFAULT_DIR = os.path.join(os.path.expanduser("~"), ".mdcg")
DEFAULT_SWARM_DIR = os.path.join(DEFAULT_DIR, "swarm")

SUBSYSTEM = "swarm"          # 子系统名：智能体可对它声明签名策略（D-4）
SIGN_ACTION = "evidence"
SCHEMA = 1
KIND = "mdcg.evidence.pack"
CARD_KIND = "mdcg.node.card"

TAG_XNODE = "xnode:cross"
SOURCE_PREFIX = "source:"

MAX_ITEMS = 500              # 单包条目上限（防灌包）
MAX_TEXT = 4000              # 单条正文上限


class EvidenceError(Exception):
    """跨节点证据层错误（fail-closed）。"""


# --------------------------------------------------------------------------
# 路径与身份
# --------------------------------------------------------------------------

def swarm_dir(path: str = None) -> str:
    return path or os.environ.get(SWARM_DIR_ENV) or DEFAULT_SWARM_DIR


def peers_dir(swarm: str = None) -> str:
    return os.path.join(swarm_dir(swarm), "peers")


def inbox_dir(swarm: str = None) -> str:
    return os.path.join(swarm_dir(swarm), "inbox")


def _root_of(root: str = None) -> str:
    return root or os.environ.get(ROOT_ENV)


def node_id(root: str = None, explicit: str = None) -> str:
    """本节点身份。

    优先 `MDCG_NODE_ID`（生产环境应显式设置，保证跨机器稳定）；
    缺省从根路径派生 `node-<12hex>`（同机可复现，跨机器不保证唯一）。
    """
    nid = (explicit or os.environ.get(NODE_ID_ENV) or "").strip()
    if nid:
        return nid
    r = _root_of(root)
    if not r:
        raise EvidenceError(
            "无法确定节点身份：请设 MDCG_NODE_ID（推荐）或 MDCG_ROOT")
    key = os.path.normcase(os.path.abspath(r))
    return "node-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _theory_state() -> dict:
    try:
        from . import theory as _th
        st = _th.check()
        return {"version": st.get("version"),
                "accepted": list(st.get("accepted_versions") or []),
                "theory_ok": bool(st.get("theory_ok"))}
    except Exception:                              # 版本层缺失不阻断证据层
        return {}


def _canon(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _slug(s) -> str:
    return "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in str(s))


# --------------------------------------------------------------------------
# 节点名片（发现）
# --------------------------------------------------------------------------

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


def publish_card(root: str = None, *, swarm: str = None,
                 subsystem: str = SUBSYSTEM, signers_file: str = None) -> dict:
    """把本节点名片写入共享目录 `peers/<node_id>.json`（0600）。"""
    c = card(root, subsystem=subsystem, signers_file=signers_file)
    p = os.path.join(peers_dir(swarm), c["node_id"] + ".json")
    _write_json(p, c)
    return {"ok": True, "file": p, "card": c}


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


def _pack_payload(pack: dict) -> bytes:
    """签名载荷：固定字段 + 排序序列化，同参数必同字节。"""
    body = {}
    for k in _PACK_FIELDS:
        body[k] = pack.get(k)
    return _canon(body)


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
            "ts": ts,
        })
    return items


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


def write_pack(pack: dict, path: str = None, swarm: str = None) -> dict:
    """把证据包落盘到收件箱（或指定路径）。"""
    if not path:
        path = os.path.join(inbox_dir(swarm),
                            f"{_slug(pack.get('from_node'))}__{pack.get('pack_id')}.json")
    _write_json(path, pack)
    return {"ok": True, "file": path}


# --------------------------------------------------------------------------
# 证据包：导入
# --------------------------------------------------------------------------

def _read_pack(src) -> dict:
    if isinstance(src, dict):
        return src
    with open(src, "r", encoding="utf-8") as f:
        return json.load(f)


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
    return ""


def _xnode_id(from_node: str, orig: str) -> str:
    return f"xnode_{_slug(from_node)}_{_slug(orig)}"


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

    items = pack["items"][:MAX_ITEMS]
    written, skipped = [], 0
    for it in items:
        if not isinstance(it, dict):
            skipped += 1
            continue
        subj = (it.get("subject") or "").strip()
        text = (it.get("text") or "").strip()
        if not subj or not text:
            skipped += 1
            continue
        tags = [TAG_XNODE, f"{SOURCE_PREFIX}{from_node}"]
        tags += [t for t in (it.get("tags") or [])
                 if isinstance(t, str) and t
                 and not t.startswith("subject:")
                 and not t.startswith(SOURCE_PREFIX)
                 and t not in (TAG_XNODE, _identity.TAG_ANCHOR, _identity.TAG_TRAIT)]
        imp = it.get("importance")
        _identity.observe(
            cg, subj, text,
            kind=it.get("kind"), role=it.get("role"),
            layer=it.get("layer") or "knowledge",
            tags=tags,
            importance=0.5 if imp is None else imp,
            verification_basis=it.get("verification_basis") or "data",
            node_id=_xnode_id(from_node, it.get("node_id") or subj),
            override=True)
        written.append(_xnode_id(from_node, it.get("node_id") or subj))

    archived = ""
    if archive:
        try:
            archived = write_pack(pack, swarm=swarm)["file"]
        except OSError:
            archived = ""
    return {"ok": True, "from_node": from_node, "pack_id": pack.get("pack_id"),
            "imported": len(written), "skipped": skipped,
            "truncated": len(pack["items"]) > MAX_ITEMS,
            "node_ids": written, "archived": archived}


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------

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

def _write_json(path: str, obj) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    return path


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
    return MdCGSecure(r, principal=p)


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


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
