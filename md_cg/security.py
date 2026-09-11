# -*- coding: utf-8 -*-
"""md_cg · 进程/权限模型（记忆 OS #2）

关键动机：**灵枢是开源仓库，而记忆很大一部分是私有内容**。因此权限模型必须
支持「公开知识」与「私有记忆」的物理与逻辑隔离：

  ① 物理隔离：租户（tenant）各自一个根目录。public 租户的根可落在开源仓库内，
     private 租户的根必须落在仓库外（如 ~/.mdcg/private/）。
  ② 逻辑隔离：每个节点带 sensitivity（public < internal < private < secret）；
     每个调用方（Principal）带 clearance，只能读写 ≤ clearance 的节点。
  ③ 硬规则：secret 节点对 clearance < secret 的调用方**写入即拒**（对齐 noema
     「secret 候选自动拒绝」）；写入高于自身 clearance 的敏感度 → 拒绝。

零第三方依赖。
"""
from __future__ import annotations

import json
import os
import time
import uuid

SENSITIVITY_ORDER = ("public", "internal", "private", "secret")
DEFAULT_SENSITIVITY = "internal"


class AccessDenied(Exception):
    """权限拒绝（读/写/管理）。"""


def _rank(level: str) -> int:
    try:
        return SENSITIVITY_ORDER.index(level)
    except ValueError:
        raise AccessDenied(f"未知敏感度/密级：{level}") from None


class Principal:
    """调用方身份（一次会话一个）。

    tenant        —— 租户（决定根目录）
    actor         —— 调用者标识（写入审计）
    clearance     —— 最高可读/可写敏感度
    can_write     —— 是否允许写
    can_admin     —— 是否允许管理操作（forget/restore/review_decide）
    session       —— 会话 id（进程/会话模型：每次连接一个）
    harness       —— 承载端标识（dsh/zcode/codebuddy…；仅归因，不参与授权）
    unit          —— 单元分工（record/reflect/verify/output/sustain；仅归因）
                     注：MCP 请求级参数 `as_unit` 会经 `tokens.narrowed_principal`
                     产出一次性 Principal——其 role/layers/ops 取自该单元 spec、unit
                     记为执行单元。那是**单次调用的临时身份**，不改变本字段的归因
                     定位（见 `mcp_server.call_tool`）。

    令牌扩展（由 `tokens.verify_token` 填充；直接构造时为 None = 不限制）：
    role          —— 角色（designer/reflection/verifier/recorder/output/sustain/guest）
    token_id      —— 令牌 id（可追溯到签发记录）
    parent        —— 派生来源令牌 id（权职分离的委派链）
    expires_at    —— 过期时间戳（None = 不过期）
    layers_allow  —— 可写层白名单（None = 不限制；"*" = 全部）
    ops_allow     —— 可执行 op 白名单（同上）
    auth_mode     —— direct（直接构造）/ token / legacy_env / anonymous

    版本层扩展（蜂群互联层0，由 `theory.check` 填充）：
    theory_ok      —— 版本声明是否合法；False 时**全部写/管理操作被拒**（只读降级）
    theory_version —— 当前声明的协议版本（审计与 whoami 用）
    """

    def __init__(self, tenant: str = "default", actor: str = "system",
                 clearance: str = DEFAULT_SENSITIVITY, can_write: bool = True,
                 can_admin: bool = False, session: str = None,
                 harness: str = None, unit: str = None,
                 role: str = None, token_id: str = None, parent: str = None,
                 expires_at: float = None, layers_allow=None, ops_allow=None,
                 auth_mode: str = "direct", theory_ok: bool = True,
                 theory_version: str = None):
        _rank(clearance)                      # 校验
        self.tenant = tenant
        self.actor = actor
        self.clearance = clearance
        self.can_write = can_write
        self.can_admin = can_admin
        self.session = session or ("sess_" + uuid.uuid4().hex[:12])
        # 归因维度（嵌套身份）：只入审计（_audit/_recent），不参与权限判定。
        # 权限域仍由令牌记录决定（tokens.ROLE_SPECS），与 harness/unit 无关。
        # 受控例外：MCP 请求级 `as_unit` 收窄（tokens.narrowed_principal）产出的是
        # 一次性 Principal，其 role/allow 取自单元 spec——**只做减法**（与 owner
        # 求交 + 管理权恒 False），故不构成本字段「参与授权」的先例。
        self.harness = harness
        self.unit = unit
        self.role = (role or "system")
        self.token_id = token_id
        self.parent = parent
        self.expires_at = float(expires_at) if expires_at else None
        self.layers_allow = None if layers_allow is None else tuple(layers_allow)
        self.ops_allow = None if ops_allow is None else tuple(ops_allow)
        self.auth_mode = auth_mode
        self.theory_ok = bool(theory_ok)
        self.theory_version = theory_version

    # ---------- 基础判定 ----------

    def allows(self, sensitivity: str) -> bool:
        """clearance 是否覆盖该敏感度（可读/可写）。"""
        return _rank(sensitivity) <= _rank(self.clearance)

    def expired(self) -> bool:
        return self.expires_at is not None and time.time() > self.expires_at

    @staticmethod
    def _in_scope(allow, name: str) -> bool:
        if allow is None:                     # 未声明 = 不限制（兼容直接构造）
            return True
        return "*" in allow or name in allow

    def allows_layer(self, layer: str) -> bool:
        return self._in_scope(self.layers_allow, layer or "knowledge")

    def allows_op(self, op: str) -> bool:
        return self._in_scope(self.ops_allow, (op or "").strip().lower())

    # ---------- 强制校验（越权即 AccessDenied） ----------

    def _require_live(self):
        if self.expired():
            raise AccessDenied(f"actor={self.actor} 令牌已过期")

    def require_op(self, op: str):
        self._require_live()
        if not self.allows_op(op):
            raise AccessDenied(
                f"角色 {self.role} 无权执行 op={op}（作用域 "
                f"{list(self.ops_allow) if self.ops_allow is not None else '不限'}）")

    def require_write(self, sensitivity: str):
        self._require_live()
        if not self.theory_ok:
            raise AccessDenied(
                "版本层校验未通过（theory_ok=False）：全部写操作被拒，"
                "仅保留 theory 修复入口")
        if not self.can_write:
            raise AccessDenied(f"actor={self.actor} 无写权限")
        if not self.allows(sensitivity):
            raise AccessDenied(
                f"写入敏感度 {sensitivity} 超出 clearance {self.clearance}")

    def require_layer_write(self, layer: str, sensitivity: str):
        """写层校验：密级 + 层白名单双闸门（核心私有内容不可越权修改）。"""
        self.require_write(sensitivity)
        layer = layer or "knowledge"
        if not self.allows_layer(layer):
            raise AccessDenied(
                f"角色 {self.role} 无权写入 {layer} 层"
                f"（可写层 {list(self.layers_allow) if self.layers_allow is not None else '不限'}）")

    def require_admin(self, op: str):
        self._require_live()
        if not self.theory_ok:
            raise AccessDenied(
                f"版本层校验未通过（theory_ok=False）：管理操作 {op} 被拒")
        if not self.can_admin:
            raise AccessDenied(f"actor={self.actor} 无管理权限（{op}）")

    def as_dict(self):
        return {"tenant": self.tenant, "actor": self.actor,
                "clearance": self.clearance, "can_write": self.can_write,
                "can_admin": self.can_admin, "session": self.session,
                "harness": self.harness, "unit": self.unit,
                "role": self.role, "token_id": self.token_id,
                "parent": self.parent, "auth_mode": self.auth_mode,
                "expires_at": self.expires_at,
                "theory_ok": self.theory_ok,
                "theory_version": self.theory_version,
                "layers_allow": (None if self.layers_allow is None
                                 else list(self.layers_allow)),
                "ops_allow": (None if self.ops_allow is None
                              else list(self.ops_allow))}

    def __repr__(self):
        return (f"Principal(tenant={self.tenant!r}, actor={self.actor!r}, "
                f"role={self.role!r}, clearance={self.clearance!r}, "
                f"write={self.can_write}, admin={self.can_admin})")


class TenantRegistry:
    """租户注册表：tenant → {root, clearance_cap, description}。

    默认位置：<registry_dir>/_tenants.json（默认 ~/.mdcg/）。
    设计意图：私有租户的 root 指向仓库外目录，开源仓库里只放 public 租户的根。
    """

    def __init__(self, path: str = None):
        if path is None:
            path = os.path.join(os.path.expanduser("~"), ".mdcg", "_tenants.json")
        self.path = path
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    return d
            except (ValueError, OSError):
                pass
        return {"schema": 1, "tenants": {}}

    def _save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def register(self, tenant: str, root: str, clearance_cap: str = DEFAULT_SENSITIVITY,
                 description: str = ""):
        _rank(clearance_cap)
        self.data["tenants"][tenant] = {
            "root": os.path.abspath(root),
            "clearance_cap": clearance_cap,
            "description": description,
            "registered_at": time.time(),
        }
        self._save()
        return self.data["tenants"][tenant]

    def get(self, tenant: str):
        return self.data["tenants"].get(tenant)

    def root_of(self, tenant: str):
        t = self.get(tenant)
        return t["root"] if t else None

    def cap_of(self, tenant: str):
        t = self.get(tenant)
        return t["clearance_cap"] if t else DEFAULT_SENSITIVITY

    def all(self):
        return dict(self.data["tenants"])

    def principal_for(self, tenant: str, actor: str = None, clearance: str = None,
                      can_write: bool = True, can_admin: bool = False,
                      session: str = None) -> Principal:
        """按租户上限夹紧 clearance（调用方不能超过租户上限）。"""
        cap = self.cap_of(tenant)
        want = clearance or cap
        if _rank(want) > _rank(cap):
            want = cap
        return Principal(tenant=tenant, actor=actor or tenant, clearance=want,
                         can_write=can_write, can_admin=can_admin, session=session)
