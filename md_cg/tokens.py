# -*- coding: utf-8 -*-
"""md_cg · 令牌与角色权职分离（记忆 OS #3）

动机：管理权限原先来自环境变量 `MDCG_CAN_ADMIN` —— 任何能设置该进程环境的
调用方都能自授权限，且无法表达「谁可以做什么」。本模块把权限收敛为三层：

  ① 令牌（token）—— 身份与权限的唯一凭据。明文只在签发时返回一次，落盘只存
     sha256 摘要；校验失败即 fail-closed（MCP 侧拒绝启动，不降级为可用）。
  ② 角色（role）—— 职责矩阵：设计者 / 反思单元 / 验证单元 / 记录单元 /
     输出单元 / 维生系统。每个角色有各自的可写层、可执行 op、密级上限。
  ③ 派生（derive）—— 设计者令牌可派生**受限子令牌**，权限只能收窄不能放大，
     子令牌默认不可再派生。单智能体环境下用它把子代理隔离成不同单元：
     验证单元拿不到事实层写权，记录单元无法自我验证，输出单元只读。

核心私有内容保护（对应「其他单元不应越权修改」）：
  · 密级 private / secret 的内容，只有 clearance 达标的角色可写；
  · 非设计者角色的密级上限一律 internal，因此**天然无法写入核心私有内容**；
  · anchor / self 保护层只对 layers_allow 含对应层（或 "*"）的角色开放。

存储：默认 `~/.mdcg/_tokens.json`（仓库外，0600），可用 `MDCG_TOKEN_FILE`
或 `--token-file` 覆盖。与 `_tenants.json` / `master.key` 同目录约定。

零第三方依赖。
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from collections import OrderedDict

from .security import Principal, _rank

TOKEN_ENV = "MDCG_TOKEN"
TOKEN_FILE_ENV = "MDCG_TOKEN_FILE"
DEFAULT_TOKEN_DIR = os.path.join(os.path.expanduser("~"), ".mdcg")
DEFAULT_TOKEN_FILE = os.path.join(DEFAULT_TOKEN_DIR, "_tokens.json")
PREFIX = "mdcg1"
SCHEMA = 1

# 核心私有内容：这些密级的内容不允许非设计者角色越权修改
CORE_PRIVATE_SENSITIVITIES = ("private", "secret")
# 保护层：身份锚点与自我层，只有显式授权的角色可写
CORE_LAYERS = ("anchor", "self")

# 全部可写层（与 mdcg.LAYERS 对齐）
ALL_LAYERS = ("anchor", "structural", "knowledge", "contextual", "self",
              "rejected", "unresolved", "goals")

# 认知图 op 全集（与 mcp_server._cg_call 对齐，供 ops_allow 收窄）
ALL_OPS = ("info", "route", "read", "write", "goal", "recent", "verify",
           "review", "forget", "protect", "identity", "consistency",
           "metacognition", "self_state", "evolution", "sustain", "scrub",
           "predict", "causal", "whitebox", "index_code", "ref", "theory", "link")


class TokenError(Exception):
    """令牌无效 / 过期 / 越权派生。"""


# --------------------------------------------------------------------------
# 角色职责矩阵
# --------------------------------------------------------------------------

# 五大单元（record/reflect/verify/output/sustain）的 unit/effect/duty 与
# `identity.POSITIONS`（智能论 v3.4 §十三）同源；test_p21 有断言防漂移。
# designer / guest 是**权限角色**而非位置效应，故不参与位置推断。
ROLE_SPECS = OrderedDict([
    ("designer", {
        "label": "设计者权限载体", "unit": "设计者", "effect": "主",
        "duty": "外部用户指定的唯一主智能体：全局观测 + 管理操作 + 派生受限子令牌",
        "can_write": True, "can_admin": True, "clearance_cap": "secret",
        "layers_allow": ["*"], "ops_allow": ["*"], "delegable": True,
        "forbidden": ["无（唯一可管理与可派生角色）"],
    }),
    ("record", {
        "label": "记录单元", "unit": "记录单元", "effect": "全",
        "duty": "保存观测、过程、结果和误差；不得自证、不得改保护层",
        "can_write": True, "can_admin": False, "clearance_cap": "internal",
        "layers_allow": ["knowledge", "contextual", "structural", "unresolved",
                         "rejected", "goals"],
        "ops_allow": ["info", "route", "read", "write", "goal", "recent"],
        "delegable": False,
        "forbidden": ["self/anchor 层", "private/secret 密级", "裁决与删除"],
    }),
    ("reflect", {
        "label": "反思单元", "unit": "反思单元", "effect": "新",
        "duty": "发现差异、遗漏条件和新的路径；只写反思/情境层",
        "can_write": True, "can_admin": False, "clearance_cap": "internal",
        "layers_allow": ["contextual"],
        "ops_allow": ["info", "route", "read", "write", "recent", "metacognition"],
        "delegable": False,
        "forbidden": ["knowledge/self/anchor 层", "private/secret 密级", "裁决与删除"],
    }),
    ("verify", {
        "label": "验证单元", "unit": "验证单元", "effect": "稳",
        "duty": "判断规则、执行结果和结构是否有效；只写验证证据与负记忆",
        "can_write": True, "can_admin": False, "clearance_cap": "internal",
        "layers_allow": ["rejected", "contextual"],
        "ops_allow": ["info", "route", "read", "write", "verify"],
        "delegable": False,
        "forbidden": ["knowledge/self/anchor 层（不得改被验证内容）",
                      "private/secret 密级", "裁决与删除"],
    }),
    ("output", {
        "label": "输出单元", "unit": "输出单元", "effect": "通",
        "duty": "与外部系统协作并表达边界；只读呈现，任何写入一律拒绝",
        "can_write": False, "can_admin": False, "clearance_cap": "internal",
        "layers_allow": [],
        "ops_allow": ["info", "route", "read", "recent", "whitebox"],
        "delegable": False,
        "forbidden": ["全部写入", "private/secret 密级", "管理操作"],
    }),
    ("sustain", {
        "label": "维生系统", "unit": "维生系统", "effect": "存",
        "duty": "维护存在、预算、回滚和整体结构；只写 self 层运维域",
        "can_write": True, "can_admin": False, "clearance_cap": "internal",
        "layers_allow": ["self"],
        "ops_allow": ["info", "read", "write", "sustain", "scrub", "evolution",
                      "self_state", "metacognition", "link"],
        "delegable": False,
        "forbidden": ["knowledge/anchor 层", "private/secret 密级", "裁决与删除"],
    }),
    ("guest", {
        "label": "未认证访客", "unit": "访客", "effect": "—",
        "duty": "无令牌时的降级身份：只读、最低密级",
        "can_write": False, "can_admin": False, "clearance_cap": "internal",
        "layers_allow": [],
        "ops_allow": ["info", "route", "read", "recent", "whitebox"],
        "delegable": False,
        "forbidden": ["全部写入", "private/secret 密级", "管理操作"],
    }),
])

# 别名：兼容旧写法与自然语言（verifier→verify / recorder→record …）
ROLE_ALIASES = {"recorder": "record", "reflection": "reflect",
                "verifier": "verify", "viewer": "output", "admin": "designer",
                "root": "designer", "anon": "guest", "anonymous": "guest"}

# 与 identity.POSITIONS 对齐的五个位置效应角色
POSITION_ROLES = ("record", "reflect", "verify", "output", "sustain")

DELEGABLE_ROLES = tuple(r for r, s in ROLE_SPECS.items() if s["delegable"])


def normalize_role(role: str) -> str:
    r = (role or "").strip().lower()
    return ROLE_ALIASES.get(r, r)


def role_spec(role: str):
    r = normalize_role(role)
    if r not in ROLE_SPECS:
        raise TokenError(f"未知角色：{role!r}（可选 {sorted(ROLE_SPECS)}）")
    return dict(ROLE_SPECS[r])


def catalog():
    """角色职责矩阵（供 whoami / service_info / 文档自描述）。"""
    return {"schema": SCHEMA, "token_file": token_file(),
            "core_private_sensitivities": list(CORE_PRIVATE_SENSITIVITIES),
            "core_layers": list(CORE_LAYERS), "all_layers": list(ALL_LAYERS),
            "position_roles": list(POSITION_ROLES),
            "delegable_roles": list(DELEGABLE_ROLES),
            "aliases": dict(ROLE_ALIASES),
            "roles": {r: dict(s) for r, s in ROLE_SPECS.items()}}


# --------------------------------------------------------------------------
# 存储（仓库外，0600）
# --------------------------------------------------------------------------

def token_file(path: str = None) -> str:
    return path or os.environ.get(TOKEN_FILE_ENV) or DEFAULT_TOKEN_FILE


def _load(path: str = None) -> dict:
    p = token_file(path)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                d.setdefault("tokens", {})
                return d
        except (OSError, ValueError):
            pass
    return {"schema": SCHEMA, "tokens": {}}


def _save(data: dict, path: str = None):
    p = token_file(path)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)          # 令牌摘要文件不可被其他用户读
    except OSError:
        pass


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _clamp_level(want: str, cap: str) -> str:
    return want if _rank(want) <= _rank(cap) else cap


def _narrow(allow, parent_allow):
    """求交：子权限只能收窄。父为 None（不限制）时取子；子为 None 时取父。"""
    if allow is None:
        return None if parent_allow is None else list(parent_allow)
    if parent_allow is None or "*" in parent_allow:
        return list(allow)
    if "*" in allow:
        return list(parent_allow)
    return [x for x in allow if x in parent_allow]


def make_token(role: str, token_id: str, secret: str) -> str:
    return f"{PREFIX}.{role}.{token_id}.{secret}"


def parse_token(token: str):
    parts = (token or "").strip().split(".")
    if len(parts) != 4 or parts[0] != PREFIX:
        raise TokenError("令牌格式非法（应为 mdcg1.<role>.<token_id>.<secret>）")
    _, role, token_id, secret = parts
    if not role or not token_id or not secret:
        raise TokenError("令牌字段缺失")
    return role.lower(), token_id, secret


# --------------------------------------------------------------------------
# 签发 / 校验 / 派生 / 吊销
# --------------------------------------------------------------------------

def issue(role: str, actor: str = None, clearance: str = None,
          tenant: str = "default", ttl: float = None, label: str = "",
          issued_by: str = "root", parent: str = None, delegable: bool = None,
          layers_allow=None, ops_allow=None, path: str = None):
    """签发一枚令牌。明文 token 只在返回值里出现一次，不落盘。"""
    role = normalize_role(role)
    spec = role_spec(role)
    clearance = _clamp_level(clearance or spec["clearance_cap"],
                             spec["clearance_cap"])
    layers = _narrow(layers_allow, spec["layers_allow"])
    ops = _narrow(ops_allow, spec["ops_allow"])
    token_id, secret = "tk_" + secrets.token_hex(6), secrets.token_urlsafe(32)
    now = time.time()
    rec = {
        "role": role, "actor": actor or role, "tenant": tenant,
        "clearance": clearance,
        "can_write": bool(spec["can_write"]),
        "can_admin": bool(spec["can_admin"]),
        "layers_allow": layers, "ops_allow": ops,
        "delegable": bool(spec["delegable"] if delegable is None else delegable),
        "parent": parent, "issued_by": issued_by, "issued_at": now,
        "expires_at": (now + float(ttl)) if ttl else None,
        "revoked_at": None, "label": label, "hash": _hash(secret),
    }
    data = _load(path)
    data["tokens"][token_id] = rec
    data["schema"] = SCHEMA
    _save(data, path)
    return {"ok": True, "token": make_token(role, token_id, secret),
            "token_id": token_id, "role": role, "actor": rec["actor"],
            "clearance": clearance, "layers_allow": layers, "ops_allow": ops,
            "expires_at": rec["expires_at"], "token_file": token_file(path)}


def verify_token(token: str, tenant: str = None, path: str = None) -> Principal:
    """校验令牌 → Principal。任何异常都抛 TokenError（fail-closed）。"""
    role, token_id, secret = parse_token(token)
    rec = (_load(path).get("tokens") or {}).get(token_id)
    if not rec:
        raise TokenError("令牌不存在（可能已吊销或来自其他令牌文件）")
    if rec.get("role") != role:
        raise TokenError("令牌角色与记录不一致（可能被篡改）")
    if rec.get("revoked_at"):
        raise TokenError("令牌已吊销")
    if not hmac.compare_digest(str(rec.get("hash") or ""), _hash(secret)):
        raise TokenError("令牌密钥不匹配")
    exp = rec.get("expires_at")
    if exp and time.time() > float(exp):
        raise TokenError("令牌已过期")
    return Principal(
        tenant=tenant or rec.get("tenant") or "default",
        actor=rec.get("actor") or role,
        clearance=rec.get("clearance") or "internal",
        can_write=bool(rec.get("can_write")),
        can_admin=bool(rec.get("can_admin")),
        role=role, token_id=token_id, parent=rec.get("parent"),
        expires_at=exp, layers_allow=rec.get("layers_allow"),
        ops_allow=rec.get("ops_allow"), auth_mode="token")


def derive(parent_token: str, role: str, actor: str = None, ttl: float = None,
           label: str = "", path: str = None, clearance: str = None,
           layers_allow=None, ops_allow=None):
    """设计者令牌派生受限子令牌：权限只能收窄，子令牌默认不可再派生。"""
    parent = verify_token(parent_token, path=path)
    data = _load(path)
    prec = (data.get("tokens") or {}).get(parent.token_id) or {}
    if not prec.get("delegable"):
        raise TokenError(f"令牌 {parent.token_id} 不可派生（role={parent.role}）")
    role = normalize_role(role)
    spec = role_spec(role)
    clamped = []
    want_clear = clearance or spec["clearance_cap"]
    final_clear = _clamp_level(want_clear, spec["clearance_cap"])
    if _rank(parent.clearance) < _rank(final_clear):
        final_clear = parent.clearance
        clamped.append("clearance")
    layers = _narrow(_narrow(layers_allow, spec["layers_allow"]),
                     prec.get("layers_allow"))
    ops = _narrow(_narrow(ops_allow, spec["ops_allow"]), prec.get("ops_allow"))
    can_write = bool(spec["can_write"]) and bool(parent.can_write)
    can_admin = bool(spec["can_admin"]) and bool(parent.can_admin)
    token_id, secret = "tk_" + secrets.token_hex(6), secrets.token_urlsafe(32)
    now = time.time()
    rec = {
        "role": role, "actor": actor or role, "tenant": parent.tenant,
        "clearance": final_clear, "can_write": can_write, "can_admin": can_admin,
        "layers_allow": layers, "ops_allow": ops,
        "delegable": False, "parent": parent.token_id,
        "issued_by": parent.token_id, "issued_at": now,
        "expires_at": (now + float(ttl)) if ttl else prec.get("expires_at"),
        "revoked_at": None, "label": label, "hash": _hash(secret),
    }
    data["tokens"][token_id] = rec
    _save(data, path)
    return {"ok": True, "token": make_token(role, token_id, secret),
            "token_id": token_id, "role": role, "actor": rec["actor"],
            "clearance": final_clear, "layers_allow": layers, "ops_allow": ops,
            "can_write": can_write, "can_admin": can_admin,
            "parent": parent.token_id, "clamped": clamped,
            "expires_at": rec["expires_at"]}


def revoke(token_id: str, path: str = None):
    data = _load(path)
    rec = (data.get("tokens") or {}).get(token_id)
    if not rec:
        raise TokenError(f"令牌不存在：{token_id}")
    rec["revoked_at"] = time.time()
    _save(data, path)
    # 级联吊销派生链
    children = [t for t, r in data["tokens"].items() if r.get("parent") == token_id]
    for c in children:
        revoke(c, path)
    return {"ok": True, "token_id": token_id, "revoked_children": children}


def list_tokens(path: str = None, include_revoked: bool = False):
    """令牌清单（不含密钥材料与摘要）。"""
    out = []
    for tid, r in (_load(path).get("tokens") or {}).items():
        if r.get("revoked_at") and not include_revoked:
            continue
        out.append({"token_id": tid, "role": r.get("role"),
                    "actor": r.get("actor"), "tenant": r.get("tenant"),
                    "clearance": r.get("clearance"),
                    "can_write": r.get("can_write"),
                    "can_admin": r.get("can_admin"),
                    "layers_allow": r.get("layers_allow"),
                    "ops_allow": r.get("ops_allow"),
                    "delegable": r.get("delegable"), "parent": r.get("parent"),
                    "label": r.get("label"), "issued_at": r.get("issued_at"),
                    "expires_at": r.get("expires_at"),
                    "revoked_at": r.get("revoked_at")})
    return sorted(out, key=lambda x: x.get("issued_at") or 0)


# --------------------------------------------------------------------------
# CLI：签发 / 派生 / 清单 / 吊销 / 角色矩阵
# --------------------------------------------------------------------------

def _print(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m md_cg.tokens",
        description="灵枢令牌管理：角色权职分离的凭据签发与校验")
    ap.add_argument("--token-file", default=None, help="令牌文件路径（默认 ~/.mdcg/_tokens.json）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_i = sub.add_parser("issue", help="签发令牌（外部用户为设计者载体签发）")
    p_i.add_argument("--role", required=True, help="designer|reflection|verifier|recorder|output|sustain")
    p_i.add_argument("--actor", default=None)
    p_i.add_argument("--tenant", default="default")
    p_i.add_argument("--clearance", default=None)
    p_i.add_argument("--ttl", type=float, default=None, help="有效期（秒）")
    p_i.add_argument("--label", default="")

    p_d = sub.add_parser("derive", help="设计者令牌派生子令牌（权限只能收窄）")
    p_d.add_argument("--token", default=None, help="父令牌明文")
    p_d.add_argument("--token-file-in", dest="token_file_in", default=None, help="从文件读父令牌")
    p_d.add_argument("--role", required=True)
    p_d.add_argument("--actor", default=None)
    p_d.add_argument("--ttl", type=float, default=None)
    p_d.add_argument("--label", default="")

    p_v = sub.add_parser("verify", help="校验令牌并打印身份")
    p_v.add_argument("--token", default=None)
    p_v.add_argument("--token-file-in", dest="token_file_in", default=None)

    p_r = sub.add_parser("revoke", help="吊销令牌（级联吊销派生链）")
    p_r.add_argument("--token-id", required=True)

    sub.add_parser("list", help="列出令牌（不含密钥材料）")
    sub.add_parser("roles", help="打印角色职责矩阵")

    a = ap.parse_args(argv)
    try:
        if a.cmd == "issue":
            _print(issue(a.role, actor=a.actor, clearance=a.clearance,
                         tenant=a.tenant, ttl=a.ttl, label=a.label,
                         path=a.token_file))
        elif a.cmd == "derive":
            tok = a.token
            if a.token_file_in:
                with open(a.token_file_in, encoding="utf-8") as f:
                    tok = f.read().strip()
            _print(derive(tok, a.role, actor=a.actor, ttl=a.ttl,
                          label=a.label, path=a.token_file))
        elif a.cmd == "verify":
            tok = a.token
            if a.token_file_in:
                with open(a.token_file_in, encoding="utf-8") as f:
                    tok = f.read().strip()
            p = verify_token(tok, path=a.token_file)
            _print({"ok": True, "principal": p.as_dict(),
                    "role_label": role_spec(p.role)["label"]})
        elif a.cmd == "revoke":
            _print(revoke(a.token_id, path=a.token_file))
        elif a.cmd == "list":
            _print({"tokens": list_tokens(path=a.token_file),
                    "token_file": token_file(a.token_file)})
        elif a.cmd == "roles":
            _print(catalog())
    except TokenError as e:
        sys.stderr.write(f"[tokens] {e}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
