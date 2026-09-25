# -*- coding: utf-8 -*-
"""租户登记表损坏静默回落守卫（N124：v15 留档②+引擎域/检索域复测三度成立）。

缺陷形态：mcp_server._resolve_root 的 except 分支（原 :3551-3552 裸 except
静默置 t_root=None）+ security.TenantRegistry._load 吞 ValueError/OSError
返回空表（security.py:274-283，合法 JSON 但顶层非对象时甚至不进 except）——
登记表损坏/不可读时租户根物理隔离绑定**无声消失**：写入本应落到 acme_root
的节点落到 MDCG_ROOT（跨租户可见），且「登记根×显式 MDCG_ROOT 冲突
fail-closed」检测（:3565-3567）连带失效，全程零痕迹。

攻击面：能影响 MDCG_TENANT_REGISTRY 指向文件（损坏/截断/替换为目录/权限
回收）的本地攻击面 + MDCG_ROOT 已设。

止血口径（本轮，对照 MDCG_CLEARANCE 覆盖告警先例）：仅加 stderr 告警，零
闸变——损坏时 _resolve_root 返回值与修复前完全一致（回落 MDCG_ROOT），但
必须开口；完好表下「租户已登记」「租户未登记（文档化零变更路径）」「冲突
fail-closed」三路径零误伤。

红项 = R1-R3（坏 JSON / 登记表为目录 / JSON 顶层非对象 → 零 stderr）；
G 项 = 完好表三路径零误伤 + fail-closed 防线仍在 + 返回值零闸变。
运行：python -m md_cg.test_tenant_registry_corrupt_warn
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

PASS = FAIL = 0
FAILS = []
MARK = "租户登记表"                     # 告警稳定锚点（mcp_server._resolve_root）


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _resolve_capture(env):
    """_resolve_root 并捕获 stderr，返回 ((root, err), stderr_text)。"""
    from .mcp_server import _resolve_root
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        out = _resolve_root(env)
    return out, buf.getvalue()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = tempfile.mkdtemp(prefix="mdcg_tenant_reg_")
    try:
        fallback = os.path.join(root, "fallback_root")
        reg_root = os.path.join(root, "acme_root")
        env = {"MDCG_ROOT": fallback, "MDCG_TENANT": "acme",
               "MDCG_TENANT_REGISTRY": os.path.join(root, "_tenants.json")}

        # ---------------- ① 攻击复现：登记表损坏必须开口 ----------------
        print("\n[1] 攻击复现：登记表损坏 → 静默回落 MDCG_ROOT")
        with open(env["MDCG_TENANT_REGISTRY"], "w", encoding="utf-8") as f:
            f.write("{corrupted!!!")               # 坏 JSON（v15 复测原样）
        (r1, e1), err1 = _resolve_capture(env)
        check("R1a 坏 JSON：stderr 含登记表告警", MARK in err1,
              (err1.strip().splitlines() or ["（零 stderr——静默回落成立）"])[-1][:90])
        check("R1b 零闸变：返回值仍回落 MDCG_ROOT",
              r1 == fallback and e1 is None, f"root={r1}")
        check("R1c 告警含租户名与回退根", "acme" in err1 and fallback in err1,
              err1.strip()[:100])

        # 登记表为目录（OSError 路径）
        os.remove(env["MDCG_TENANT_REGISTRY"])
        os.mkdir(env["MDCG_TENANT_REGISTRY"])
        (r2, e2), err2 = _resolve_capture(env)
        check("R2 登记表为目录：stderr 含告警且零闸变",
              MARK in err2 and r2 == fallback and e2 is None,
              (err2.strip().splitlines() or ["（零 stderr）"])[-1][:90])
        os.rmdir(env["MDCG_TENANT_REGISTRY"])

        # JSON 顶层非对象（合法 JSON 但 _load 不进 except 分支的路径）
        with open(env["MDCG_TENANT_REGISTRY"], "w", encoding="utf-8") as f:
            f.write('["not","a","table"]')
        (r3, e3), err3 = _resolve_capture(env)
        check("R3 JSON 顶层非对象：stderr 含告警且零闸变",
              MARK in err3 and r3 == fallback and e3 is None,
              (err3.strip().splitlines() or ["（零 stderr）"])[-1][:90])

        # ---------------- ② 完好表三路径零误伤 ----------------
        print("\n[2] 完好登记表：已登记/未登记/冲突 三路径零误伤")
        os.remove(env["MDCG_TENANT_REGISTRY"])
        from .security import TenantRegistry
        TenantRegistry(env["MDCG_TENANT_REGISTRY"]).register("acme", reg_root)
        # 已登记 happy path：不设 MDCG_ROOT（设了且不同值即冲突 fail-closed）
        env_nr = {k: v for k, v in env.items() if k != "MDCG_ROOT"}
        (r4, e4), err4 = _resolve_capture(env_nr)
        check("G1 已登记：返回登记根且零告警",
              r4 and os.path.abspath(r4) == os.path.abspath(reg_root)
              and e4 is None and MARK not in err4, f"root={r4}")

        env5 = dict(env, MDCG_TENANT="nobody")
        (r5, e5), err5 = _resolve_capture(env5)
        check("G2 未登记租户：文档化回落 MDCG_ROOT 且零告警",
              r5 == fallback and e5 is None and MARK not in err5, f"root={r5}")

        env6 = dict(env)
        (r6, e6), err6 = _resolve_capture(dict(env6, MDCG_TENANT_REGISTRY=""))
        # 空串 registry 路径 → 缺省 ~/.mdcg/_tenants.json（不在断言面，仅保不崩）
        check("G3 缺省登记表路径不误伤告警锚",
              isinstance(err6, str), f"root={r6}")

        # 冲突 fail-closed 防线（损坏时连带失效的那道）必须仍在
        (r7, e7), err7 = _resolve_capture(dict(env, MDCG_ROOT=reg_root + "_x"))
        check("G4 登记根×显式根冲突仍 fail-closed",
              r7 is None and e7 and "fail-closed" in e7, f"err={e7}")

        # ---------------- ③ TenantRegistry.load_error 单元面 ----------------
        print("\n[3] TenantRegistry.load_error 单元面")
        bad = os.path.join(root, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{corrupted!!!")
        t1 = TenantRegistry(bad)
        check("G5 坏 JSON：load_error 非空", bool(t1.load_error),
              f"load_error={t1.load_error}")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "tenants": {
                "acme": {"root": reg_root}}}, f, ensure_ascii=False)
        t2 = TenantRegistry(bad)
        check("G6 完好表：load_error 为空", not t2.load_error,
              f"load_error={t2.load_error}")
        t3 = TenantRegistry(os.path.join(root, "absent.json"))
        check("G7 缺文件：load_error 为空（正常首启不算损坏）",
              not t3.load_error, f"load_error={t3.load_error}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
