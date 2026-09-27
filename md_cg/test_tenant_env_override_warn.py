# -*- coding: utf-8 -*-
"""租户绑定 env 覆盖守卫（v8 N62 止血告警 → 本轮 N62 第 5 轮 fail-closed）。

攻击面：控制 MCP 进程 env 的部署面（宿主配置 / 启动器 / 同机多会话）——
tenantA 签发的 designer(secret, can_admin) 令牌在 MDCG_TENANT=tenantB 下经
mcp_server._build_principal → verify_token(tok, tenant=env) 以 tenantB 身份
运行（tenant=tenant or rec.get("tenant") 形参优先）。

契约演进（N62 五轮留档）：
  v8/v9/第15轮：仅 stderr 告警零闸变（止血口径——先开口，强校验 deferred）；
  本轮（2026-09-27 第 5 次，medium 维持）：告警改 fail-closed 拒绝
  （tokens.verify_token 抛 TokenError，消息含两侧租户与校正指引），并接线
  登记租户 clearance_cap 夹紧（MDCG_TENANT_REGISTRY，与 mcp_server.
  _resolve_root 同源；未登记租户零闸变）。

运行：python -m md_cg.test_tenant_env_override_warn
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile

from . import tokens

PASS = FAIL = 0
FAILS = []
MARK = "租户绑定被入参覆盖"          # fail-closed 拒绝消息稳定锚点


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _verify_capture(token, tenant, path):
    """verify_token 捕获异常与 stderr，返回 (principal|None, stderr_text, exc|None)。"""
    buf = io.StringIO()
    p = exc = None
    try:
        with contextlib.redirect_stderr(buf):
            p = tokens.verify_token(token, tenant=tenant, path=path)
    except tokens.TokenError as e:
        exc = e
    return p, buf.getvalue(), exc


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = tempfile.mkdtemp(prefix="mdcg_tenant_warn_")
    tf = os.path.join(root, "_tokens.json")
    # 登记表钉在临时不存在路径：守卫全程不触真实 ~/.mdcg/_tenants.json，
    # 且「未登记 → 零夹紧」确定性（冲突拒绝发生在登记表访问之前）。
    reg_path = os.path.join(root, "_tenants_absent.json")
    old_reg = os.environ.get("MDCG_TENANT_REGISTRY")
    os.environ["MDCG_TENANT_REGISTRY"] = reg_path
    try:
        # ---------------- ① 攻击复现（单元级，fail-closed） ----------------
        print("\n[1] 攻击复现：tenantA 令牌被 tenantB 形参覆盖 → 拒绝")
        d = tokens.issue("designer", actor="dummy-designer", tenant="tenantA",
                         path=tf)
        p, err, exc = _verify_capture(d["token"], "tenantB", tf)
        check("冲突覆盖被拒（TokenError 且含锚点）",
              p is None and exc is not None and MARK in str(exc),
              f"p={p} exc={type(exc).__name__}: {str(exc)[:80]}")
        check("拒绝消息含两侧租户与校正指引",
              exc is not None and "tenantA" in str(exc) and "tenantB" in str(exc)
              and "MDCG_TENANT" in str(exc), str(exc)[:100])

        # ---------------- ② fail-closed（覆盖零放行） ----------------
        print("\n[2] fail-closed（冲突路径零 Principal 放行）")
        check("冲突路径不返回 Principal", p is None, f"p={p}")

        # ---------------- ③ 无冲突路径零误伤 ----------------
        print("\n[3] 无冲突路径零误伤")
        p0, err0, exc0 = _verify_capture(d["token"], None, tf)
        check("tenant=None：零异常且回退令牌租户",
              exc0 is None and MARK not in err0 and p0.tenant == "tenantA",
              f"tenant={p0.tenant} err={exc0}")
        p1, err1, exc1 = _verify_capture(d["token"], "", tf)
        check("tenant=''（env 未设/空串）：零异常且回退令牌租户",
              exc1 is None and MARK not in err1 and p1.tenant == "tenantA",
              f"tenant={p1.tenant} err={exc1}")
        p2, err2, exc2 = _verify_capture(d["token"], "tenantA", tf)
        check("tenant 同值：零异常零告警",
              exc2 is None and MARK not in err2 and p2.tenant == "tenantA",
              f"tenant={p2.tenant} err={exc2}")

        # ---------------- ④ MCP 进程级入口（_build_principal 直调先例 b26） ----------------
        print("\n[4] MCP 进程级：MDCG_TOKEN(tenantA) + MDCG_TENANT=tenantB")
        from .mcp_server import _build_principal
        saved = {k: os.environ.get(k) for k in
                 ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_TOKEN_FILE", "MDCG_ROOT",
                  "MDCG_TENANT_REGISTRY", "MDCG_LEGACY_ENV_AUTH",
                  "MDCG_LEGACY_ENV_ADMIN", "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE",
                  "MDCG_CLEARANCE", "MDCG_ACTOR")}
        try:
            os.environ["MDCG_TOKEN"] = d["token"]
            os.environ["MDCG_TOKEN_FILE"] = tf
            os.environ["MDCG_ROOT"] = os.path.join(root, "mcp")
            os.environ["MDCG_TENANT_REGISTRY"] = reg_path
            os.environ["MDCG_TENANT"] = "tenantB"
            for k in ("MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
                      "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_CLEARANCE",
                      "MDCG_ACTOR"):
                os.environ.pop(k, None)
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                mp, merr = _build_principal()
            mout = buf.getvalue()
            check("MCP 入口覆盖被拒（err 含锚点，principal=None）",
                  mp is None and merr is not None and MARK in merr,
                  f"err={str(merr)[:90]}")
            # 无冲突对照：MDCG_TENANT 与令牌租户一致 → 零异常正常通过
            os.environ["MDCG_TENANT"] = "tenantA"
            buf2 = io.StringIO()
            with contextlib.redirect_stderr(buf2):
                mp2, merr2 = _build_principal()
            check("MDCG_TENANT 同值：零异常零告警",
                  merr2 is None and MARK not in buf2.getvalue()
                  and getattr(mp2, "tenant", None) == "tenantA",
                  buf2.getvalue().strip()[:90])
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
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
