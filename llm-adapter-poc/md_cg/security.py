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

    tenant     —— 租户（决定根目录）
    actor      —— 调用者标识（写入审计）
    clearance  —— 最高可读/可写敏感度
    can_write  —— 是否允许写
    can_admin  —— 是否允许管理操作（forget/restore/review_decide）
    session    —— 会话 id（进程/会话模型：每次连接一个）
    """

    def __init__(self, tenant: str = "default", actor: str = "system",
                 clearance: str = DEFAULT_SENSITIVITY, can_write: bool = True,
                 can_admin: bool = False, session: str = None):
        _rank(clearance)                      # 校验
        self.tenant = tenant
        self.actor = actor
        self.clearance = clearance
        self.can_write = can_write
        self.can_admin = can_admin
        self.session = session or ("sess_" + uuid.uuid4().hex[:12])

    def allows(self, sensitivity: str) -> bool:
        """clearance 是否覆盖该敏感度（可读/可写）。"""
        return _rank(sensitivity) <= _rank(self.clearance)

    def require_write(self, sensitivity: str):
        if not self.can_write:
            raise AccessDenied(f"actor={self.actor} 无写权限")
        if not self.allows(sensitivity):
            raise AccessDenied(
                f"写入敏感度 {sensitivity} 超出 clearance {self.clearance}")

    def require_admin(self, op: str):
        if not self.can_admin:
            raise AccessDenied(f"actor={self.actor} 无管理权限（{op}）")

    def as_dict(self):
        return {"tenant": self.tenant, "actor": self.actor,
                "clearance": self.clearance, "can_write": self.can_write,
                "can_admin": self.can_admin, "session": self.session}

    def __repr__(self):
        return (f"Principal(tenant={self.tenant!r}, actor={self.actor!r}, "
                f"clearance={self.clearance!r}, write={self.can_write}, "
                f"admin={self.can_admin})")


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
