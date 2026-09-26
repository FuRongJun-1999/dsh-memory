# -*- coding: utf-8 -*-
"""租户绑定 env 覆盖告警守卫（v8 N62 / v9 / 第15轮三次成立，止血验收）。

攻击面：控制 MCP 进程 env 的部署面（宿主配置 / 启动器 / 同机多会话）——
tenantA 签发的 designer(secret, can_admin) 令牌在 MDCG_TENANT=tenantB 下经
mcp_server._build_principal → verify_token(tok, tenant=env) 静默以 tenantB
身份运行（tenant=tenant or rec.get("tenant") 形参优先），全程零告警。

止血口径（本轮）：仅加 stderr 告警，零闸变——冲突时 Principal 判定结果与
修复前完全一致（形参/env 值仍优先），但必须开口。对照 MDCG_CLEARANCE 先例
（mcp_server._build_principal 密级冲突告警）。clearance_cap 夹紧接线与租户
绑定强校验不在本项范围（另行 deferred）。

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
MARK = "租户绑定被入参覆盖"          # 告警稳定锚点（tokens.verify_token）


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
    """verify_token 并捕获 stderr，返回 (principal, stderr_text)。"""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        p = tokens.verify_token(token, tenant=tenant, path=path)
    return p, buf.getvalue()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = tempfile.mkdtemp(prefix="mdcg_tenant_warn_")
    tf = os.path.join(root, "_tokens.json")
    try:
        # ---------------- ① 攻击复现（单元级） ----------------
        print("\n[1] 攻击复现：tenantA 令牌被 tenantB 形参覆盖必须告警")
        d = tokens.issue("designer", actor="dummy-designer", tenant="tenantA",
                         path=tf)
        p, err = _verify_capture(d["token"], "tenantB", tf)
        check("冲突覆盖发 stderr 告警", MARK in err,
              (err.strip().splitlines() or ["（零 stderr 输出——静默覆盖成立）"])[-1][:90])
        check("告警含两侧租户名", "tenantA" in err and "tenantB" in err,
              err.strip()[:100])

        # ---------------- ② 零闸变（止血不改判定） ----------------
        print("\n[2] 零闸变（判停结果与修复前一致，只加告警）")
        check("形参/env 租户仍优先生效", p.tenant == "tenantB",
              f"principal.tenant={p.tenant}")
        check("权限面不受影响（designer/can_admin 原样）",
              p.role == "designer" and p.can_admin is True,
              f"role={p.role} admin={p.can_admin}")

        # ---------------- ③ 无冲突路径零误伤 ----------------
        print("\n[3] 无冲突路径零误伤")
        p0, err0 = _verify_capture(d["token"], None, tf)
        check("tenant=None：零告警且回退令牌租户",
              MARK not in err0 and p0.tenant == "tenantA",
              f"tenant={p0.tenant}")
        p1, err1 = _verify_capture(d["token"], "", tf)
        check("tenant=''（env 未设/空串）：零告警且回退令牌租户",
              MARK not in err1 and p1.tenant == "tenantA",
              f"tenant={p1.tenant}")
        p2, err2 = _verify_capture(d["token"], "tenantA", tf)
        check("tenant 同值：零告警", MARK not in err2 and p2.tenant == "tenantA",
              f"tenant={p2.tenant}")

        # ---------------- ④ MCP 进程级入口（_build_principal 直调先例 b26） ----------------
        print("\n[4] MCP 进程级：MDCG_TOKEN(tenantA) + MDCG_TENANT=tenantB")
        from .mcp_server import _build_principal
        saved = {k: os.environ.get(k) for k in
                 ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_TOKEN_FILE", "MDCG_ROOT",
                  "MDCG_LEGACY_ENV_AUTH", "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE",
                  "MDCG_CLEARANCE", "MDCG_ACTOR")}
        try:
            os.environ["MDCG_TOKEN"] = d["token"]
            os.environ["MDCG_TOKEN_FILE"] = tf
            os.environ["MDCG_ROOT"] = os.path.join(root, "mcp")
            os.environ["MDCG_TENANT"] = "tenantB"
            for k in ("MDCG_LEGACY_ENV_AUTH", "MDCG_CAN_ADMIN",
                      "MDCG_CAN_WRITE", "MDCG_CLEARANCE", "MDCG_ACTOR"):
                os.environ.pop(k, None)
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                mp, merr = _build_principal()
            mout = buf.getvalue()
            check("MCP 入口构建成功（攻击原样可达）", merr is None and mp is not None,
                  f"err={merr}")
            check("MCP 入口租户被覆盖为 tenantB（攻击面成立）",
                  getattr(mp, "tenant", None) == "tenantB",
                  f"tenant={getattr(mp, 'tenant', None)}")
            check("MCP 入口 stderr 含覆盖告警", MARK in mout,
                  (mout.strip().splitlines() or ["（零 stderr）"])[-1][:90])
            # 无冲突对照：MDCG_TENANT 与令牌租户一致 → 零告警
            os.environ["MDCG_TENANT"] = "tenantA"
            buf2 = io.StringIO()
            with contextlib.redirect_stderr(buf2):
                mp2, merr2 = _build_principal()
            check("MDCG_TENANT 同值：零告警",
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
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
