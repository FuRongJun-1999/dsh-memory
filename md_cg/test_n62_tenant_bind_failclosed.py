# -*- coding: utf-8 -*-
"""N62 守卫（第 5 轮，2026-09-27）：令牌路径租户上限夹紧 + 租户绑定覆盖 fail-closed。

留档复测（v8 N62 首报 → v9/v15/v16 历轮成立 → 本轮第 5 次，medium 维持）：

病灶①（cap 夹紧从未接线）：verify_token 令牌路径返回 Principal 时
clearance=rec["clearance"] 原样透出（tokens.py:450）——TenantRegistry.cap_of /
principal_for 现成（security.py:323/332）但令牌路径零调用；tenantC 登记上限
internal 时 designer(secret) 令牌仍以 secret 运行（可读含 private/secret）。

病灶②（绑定覆盖 warn-only）：verify_token 形参 tenant（MCP 侧来自
MDCG_TENANT）与令牌记录 rec["tenant"] 不同时仅 stderr 告警（tokens.py:441-446），
形参值照常顶替（:448 tenant=tenant or ...）——tenantA 令牌在 MDCG_TENANT=
tenantB 下以原权限对 tenantB 运行。

红守卫（哑临时登记表 + 哑令牌库 + 临时根，确定性、零真实状态；登记表经
MDCG_TENANT_REGISTRY 注入——与 _resolve_root 同源，无新形参，旧代码红为
功能红而非 TypeError）：
  R1 ② 覆盖被拒：tenantA designer 令牌 + tenant="tenantB" → TokenError
      （fail-closed），消息含两侧租户与校正指引；
  R2 ① cap 夹紧：tenantC（登记 cap=internal）designer 令牌（角色默认 secret）
      无覆盖 → clearance 夹紧为 internal，allows("private"/"secret") 均 False；
  R3 未登记租户零闸变：tenantD（不在登记表）令牌 clearance 原样；
  R4 无冲突零误伤：tenant=None/""/同值 → 原令牌租户、零异常；
  R5 MCP 进程面：_build_principal 同面复现（env 注入 MDCG_TOKEN + MDCG_TENANT
      + MDCG_TENANT_REGISTRY）——② 拒绝、① 夹紧、同值零误伤。

同面搭车（N174，low，见 deferred，本轮不修）：mcp_server.py:3522-3528 legacy
env 路径 clearance 夹紧另行 deferred。

运行：python -m md_cg.test_n62_tenant_bind_failclosed
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile

from . import tokens
from .security import TenantRegistry

PASS = FAIL = 0
FAILS = []
MARK = "租户绑定被入参覆盖"          # fail-closed 拒绝消息稳定锚点


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:110])


def _verify(token, tenant=None, path=None):
    """verify_token 捕获异常，返回 (principal|None, exc|None)。"""
    try:
        return tokens.verify_token(token, tenant=tenant, path=path), None
    except tokens.TokenError as e:
        return None, e


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tmp = tempfile.mkdtemp(prefix="mdcg_n62_")
    tf = os.path.join(tmp, "_tokens.json")
    reg_path = os.path.join(tmp, "_tenants.json")
    old_reg = os.environ.get("MDCG_TENANT_REGISTRY")
    try:
        # 哑临时登记表：确定性上限（tenantA=secret 不夹、tenantB/tenantC=internal）
        reg = TenantRegistry(reg_path)
        reg.register("tenantA", os.path.join(tmp, "rootA"), clearance_cap="secret",
                     description="N62 守卫哑登记 tenantA")
        reg.register("tenantB", os.path.join(tmp, "rootB"),
                     clearance_cap="internal", description="N62 哑登记 tenantB")
        reg.register("tenantC", os.path.join(tmp, "rootC"),
                     clearance_cap="internal", description="N62 哑登记 tenantC")
        os.environ["MDCG_TENANT_REGISTRY"] = reg_path
        d_a = tokens.issue("designer", actor="dummy-designer-a", tenant="tenantA",
                           path=tf)          # 角色默认 clearance=secret
        d_c = tokens.issue("designer", actor="dummy-designer-c", tenant="tenantC",
                           path=tf)          # 登记 cap=internal < secret
        d_d = tokens.issue("designer", actor="dummy-designer-d", tenant="tenantD",
                           path=tf)          # tenantD 未登记

        # ---------- R1 ② 覆盖 fail-closed ----------
        print("== R1 租户绑定被入参覆盖 → 拒绝（fail-closed）==")
        p1, e1 = _verify(d_a["token"], tenant="tenantB", path=tf)
        check("R1a 覆盖被拒（TokenError 且含锚点）",
              p1 is None and e1 is not None and MARK in str(e1),
              f"p={p1} exc={type(e1).__name__}: {str(e1)[:80]}")
        check("R1b 拒绝消息含两侧租户与校正指引",
              e1 is not None and "tenantA" in str(e1) and "tenantB" in str(e1)
              and "MDCG_TENANT" in str(e1), str(e1)[:100])

        # ---------- R2 ① cap 夹紧（登记租户，纯收紧） ----------
        print("== R2 登记租户上限夹紧（cap=internal < 令牌 secret）==")
        p2, e2 = _verify(d_c["token"], path=tf)
        check("R2a clearance 夹紧为 internal",
              e2 is None and p2 is not None and p2.clearance == "internal",
              f"clearance={getattr(p2, 'clearance', None)} err={e2}")
        check("R2b 可读不含 private/secret",
              p2 is not None and not p2.allows("private")
              and not p2.allows("secret"),
              f"private={p2.allows('private') if p2 else None} "
              f"secret={p2.allows('secret') if p2 else None}")
        check("R2c internal 本级仍可读（收紧不误伤）",
              p2 is not None and p2.allows("internal"),
              f"internal={p2.allows('internal') if p2 else None}")

        # ---------- R3 未登记租户零闸变 ----------
        print("== R3 未登记租户零闸变（fresh install 行为不变）==")
        p3, e3 = _verify(d_d["token"], path=tf)
        check("R3 未登记 tenantD clearance 原样（不夹紧）",
              e3 is None and p3 is not None and p3.clearance == "secret"
              and p3.tenant == "tenantD" and p3.allows("secret"),
              f"clearance={getattr(p3, 'clearance', None)} "
              f"tenant={getattr(p3, 'tenant', None)} err={e3}")

        # ---------- R4 无冲突零误伤 ----------
        print("== R4 无冲突路径零误伤 ==")
        for label, arg in (("None", None), ("空串", ""), ("同值", "tenantA")):
            p4, e4 = _verify(d_a["token"], tenant=arg, path=tf)
            check(f"R4 tenant={label}：零异常且回落令牌租户 tenantA",
                  e4 is None and p4 is not None and p4.tenant == "tenantA"
                  and p4.clearance == "secret",
                  f"tenant={getattr(p4, 'tenant', None)} "
                  f"clearance={getattr(p4, 'clearance', None)} err={e4}")

        # ---------- R5 MCP 进程面（_build_principal 同面） ----------
        print("== R5 MCP 进程级：MDCG_TOKEN + MDCG_TENANT + MDCG_TENANT_REGISTRY ==")
        from .mcp_server import _build_principal
        saved = {k: os.environ.get(k) for k in
                 ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_TOKEN_FILE", "MDCG_ROOT",
                  "MDCG_TENANT_REGISTRY", "MDCG_LEGACY_ENV_AUTH",
                  "MDCG_LEGACY_ENV_ADMIN", "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE",
                  "MDCG_CLEARANCE", "MDCG_ACTOR")}
        try:
            os.environ["MDCG_TOKEN"] = d_a["token"]
            os.environ["MDCG_TOKEN_FILE"] = tf
            os.environ["MDCG_ROOT"] = os.path.join(tmp, "mcp")
            os.environ["MDCG_TENANT_REGISTRY"] = reg_path
            os.environ["MDCG_TENANT"] = "tenantB"
            for k in ("MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
                      "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_CLEARANCE",
                      "MDCG_ACTOR"):
                os.environ.pop(k, None)
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                mp, merr = _build_principal()
            check("R5a MCP 面覆盖被拒（err 含锚点，principal=None）",
                  mp is None and merr is not None and MARK in merr,
                  f"err={str(merr)[:90]}")
            # ① 经 MCP 面：tenantC（登记 cap=internal）夹紧
            os.environ["MDCG_TOKEN"] = d_c["token"]
            os.environ["MDCG_TENANT"] = "tenantC"
            mp2, merr2 = _build_principal()
            check("R5b MCP 面 cap 夹紧（tenantC designer → internal）",
                  merr2 is None and mp2 is not None
                  and getattr(mp2, "clearance", None) == "internal",
                  f"clearance={getattr(mp2, 'clearance', None)} err={merr2}")
            # 同值零误伤
            os.environ["MDCG_TOKEN"] = d_a["token"]
            os.environ["MDCG_TENANT"] = "tenantA"
            mp3, merr3 = _build_principal()
            check("R5c MDCG_TENANT 同值：零误伤正常通过",
                  merr3 is None and mp3 is not None
                  and getattr(mp3, "tenant", None) == "tenantA"
                  and getattr(mp3, "clearance", None) == "secret",
                  f"err={merr3} tenant={getattr(mp3, 'tenant', None)} "
                  f"clearance={getattr(mp3, 'clearance', None)}")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    finally:
        if old_reg is None:
            os.environ.pop("MDCG_TENANT_REGISTRY", None)
        else:
            os.environ["MDCG_TENANT_REGISTRY"] = old_reg
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print("FAILED: %d 项 → %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("ALL OK: %d 项（N62 令牌路径 cap 夹紧 + 租户覆盖 fail-closed 守卫全绿）" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
