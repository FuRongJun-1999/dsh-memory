# -*- coding: utf-8 -*-
# 功能名：#450 写面层闸 _resolve_target 对「既有节点缺 sensitivity 键」的**登记形态**（保持 internal 回落）
# 生效条件：python -X utf8 -m md_cg.test_issue450_writegate_unknown_sens [--mutate]
# 子功能：A 组=缺键节点的判定形态（internal 回落 ⇒ internal 身份可改写，**已知 fail-open 代价**）·
#         K 组=非恒真对照（显式密级仍拒 / 缺省档放行 / 新节点放行 / 高权身份放行）·
#         F 组=索引回填面（MdCGSecure._scan_nodes 把缺键擦成 internal 之后的读数）·
#         E 组=结构锚（回落值/缺键回读/裁定注释在位）· R 组=裁定可分辨性（若改回 fail-closed，A1 必转红）
# 执行：直接跑；--mutate 时跑 R 组的判别力自证（不修改仓库文件）
# 验证方式：断言全过 + 退出码 0；--mutate 下 R 组必须证明「resolve 出 secret ⇒ 同一断言转红」
# 不适用条件：① 不覆盖读面 recent_events（属 #447）；② 不做「真实密级应为高密级」的业务裁定；
#   ③ 不覆盖加密且无密钥导致盘面读不出的节点（此时无法确认缺键，保留索引值，见 _resolve_target 注释）。
"""issue #450 守卫：钉「缺键 ⇒ internal 回落」这一裁定，以及它的代价与改判条件。

裁定（2026-10-18，全量链实测后）：
  首版曾按 fail-closed（缺键 ⇒ secret）落地，理由是「真实密级可能是
  restricted/private/secret ⇒ 回落 internal 会放行 ⇒ 越权」。全量链随即暴露
  blast radius：本仓写面的**常态**是不声明 sensitivity（缺省即 internal），
  fail-closed 等于把全库 legacy 节点对非 secret 身份变成只读——实测
  `test_p31_insight` / `test_p30_maintain` / `test_p29_session_ingest_export`
  三个用例当场转红（内部身份改写既有无键节点被 AccessDenied）。
  ⇒ 按「成本>收益取小」**保持 internal 回落**；本守卫把该形态钉住，
  并把「何时改判」写进 `protect._resolve_target` 的注释③。

所以本守卫断言的是**已裁定的形态**，不是「缺陷已修」：
  A1 = internal 身份 × legacy 无键节点 ⇒ **放行**（代价：这一放行就是 fail-open 面）
  A2 = `_resolve_target` 的密级 = `internal`（不是 secret）
  R 组证明这条断言不是恒真：若把回落值改成 secret，同一身份会被拒。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

FAILS = []
PASSED = []


def _check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  PASS " + name)
    else:
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:200])


def _run(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return "PASS"
    except Exception as exc:                     # noqa: BLE001
        return "DENY(%s)" % type(exc).__name__


def _env():
    tmp = tempfile.mkdtemp(prefix="iss450_")
    os.environ["MDCG_ROOT"] = os.path.join(tmp, "brain")
    os.environ["MDCG_STATE_ROOT"] = os.path.join(tmp, "state")
    os.environ["MDCG_AUX_ROOT"] = os.path.join(tmp, "auxroot")
    os.environ["MDCG_DATA_ROOT"] = os.path.join(tmp, "data")
    os.environ["MDCG_EXPORT_ROOT"] = os.path.join(tmp, "export")
    os.environ["MDCG_TOKEN_FILE"] = os.path.join(tmp, "auxroot", "tokens.json")
    os.environ["MDCG_MASTER_KEY"] = "cd" * 32
    for k in ("MDCG_TOKEN", "MDCG_VERIFY_KEY", "MDCG_TENANT", "MDCG_CLEARANCE",
              "MDCG_SESSION"):
        os.environ.pop(k, None)
    return tmp


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    tmp = _env()
    from md_cg import protect
    from md_cg.mdcg import MdCG
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal

    try:
        root = os.environ["MDCG_ROOT"]
        # legacy 形态：基类 MdCG 直写（fm 无 sensitivity 键）
        base = MdCG(root)
        base.add("legacy_nokey", "升级前旧节点正文（无 sensitivity 键）",
                 layer="knowledge", importance=0.3)
        base.close()
        owner = Principal(tenant="default", actor="owner", clearance="secret",
                          can_write=True, can_admin=True, role="designer",
                          auth_mode="test")
        w = MdCGSecure(root, principal=owner)
        w.add("restricted_node", "显式受限正文", layer="knowledge",
              importance=0.3, sensitivity="restricted")
        w.add("internal_node", "显式内部正文", layer="knowledge",
              importance=0.3, sensitivity="internal")
        w.close()

        p = Principal(tenant="default", actor="internal-reader",
                      clearance="internal", can_write=True, can_admin=False,
                      role="record", auth_mode="test")
        cg = MdCGSecure(root, principal=p)

        print("== A 组：缺键节点的**已裁定形态**（internal 回落） ==")
        # 预热到真实运行态：索引条目的 sensitivity 由 `_scan_nodes` 回填（缺键 → internal）
        protect._resolve_target(cg, "legacy_nokey")
        _warm = (cg.index.get("nodes") or {}).get("legacy_nokey") or {}
        _check("A0 预热：索引条目已被回填为 'internal'（缺键被擦成缺省档）",
               _warm.get("sensitivity") == "internal", _warm.get("sensitivity"))
        _check("A1 internal 身份 × legacy 无键节点 => 放行（**已知 fail-open 代价**，"
               "改判条件见 protect 注释③）",
               _run(protect.guard_overwrite, cg, "legacy_nokey",
                    layer="knowledge") == "PASS",
               _run(protect.guard_overwrite, cg, "legacy_nokey",
                    layer="knowledge"))
        _check("A2 _resolve_target(legacy_nokey) 的密级 = internal（不是 secret）",
               protect._resolve_target(cg, "legacy_nokey")[1] == "internal",
               protect._resolve_target(cg, "legacy_nokey"))
        _check("A3 层位仍正确解析（knowledge）",
               protect._resolve_target(cg, "legacy_nokey")[0] == "knowledge",
               protect._resolve_target(cg, "legacy_nokey"))

        print("== K 组：非恒真对照（层闸本身没被整体拆掉） ==")
        _check("K1 显式 restricted => 仍拒（对照锚定）",
               _run(protect.guard_overwrite, cg, "restricted_node",
                    layer="knowledge") == "DENY(AccessDenied)",
               _run(protect.guard_overwrite, cg, "restricted_node",
                    layer="knowledge"))
        _check("K2 显式 internal => 放行",
               _run(protect.guard_overwrite, cg, "internal_node",
                    layer="knowledge") == "PASS",
               _run(protect.guard_overwrite, cg, "internal_node",
                    layer="knowledge"))
        _check("K3 节点不存在（新写入面）=> 放行",
               _run(protect.guard_overwrite, cg, "brand_new",
                    layer="knowledge") == "PASS",
               _run(protect.guard_overwrite, cg, "brand_new",
                    layer="knowledge"))
        hi = Principal(tenant="default", actor="secret-reader",
                       clearance="secret", can_write=True, can_admin=False,
                       role="designer", auth_mode="test")
        cg_hi = MdCGSecure(root, principal=hi)
        _check("K4 secret 身份 × 无键节点 => 放行",
               _run(protect.guard_overwrite, cg_hi, "legacy_nokey",
                    layer="knowledge") == "PASS",
               _run(protect.guard_overwrite, cg_hi, "legacy_nokey",
                    layer="knowledge"))
        cg_hi.close()

        print("== F 组：索引回填面 ==")
        protect._resolve_target(cg, "legacy_nokey")
        e = (cg.index.get("nodes") or {}).get("legacy_nokey") or {}
        fm = (cg.get("legacy_nokey") or {}).get("frontmatter") or {}
        _check("F1 前置成立：索引条目 sensitivity == 'internal' 而 fm 无该键",
               e.get("sensitivity") == "internal" and not fm.get("sensitivity"),
               (e.get("sensitivity"), fm.get("sensitivity")))
        _check("F2 索引回填后仍按 internal 判定（缺键信号已被回填擦掉——这正是"
               "「未知」不可区分的来源）",
               _run(protect.guard_overwrite, cg, "legacy_nokey",
                    layer="knowledge") == "PASS",
               _run(protect.guard_overwrite, cg, "legacy_nokey",
                    layer="knowledge"))

        print("== E 组：结构锚（裁定形态在位） ==")
        src = open(os.path.join(_REPO, "md_cg", "protect.py"),
                   encoding="utf-8").read()
        i = src.find("def _resolve_target(")
        j = src.find("\ndef ", i + 10)
        body = src[i:j if j > 0 else len(src)]
        _check("E1 单点内的回落值是 DEFAULT_SENSITIVITY（不是 fail-closed 的 secret）",
               "_sens or DEFAULT_SENSITIVITY" in body
               or 'return _layer or "knowledge", DEFAULT_SENSITIVITY' in body)
        _check("E2 缺键回读仍在位（=将来改判时的接线点）",
               'if not _fm.get("sensitivity"):' in body)
        _check("E3 裁定注释在位：写明代价与改判条件",
               "成本" in body and "何时改判" in body)

        print("== R 组：裁定可分辨性（这条断言不是恒真） ==")
        _check("R1 internal 身份对 internal 档放行、对 secret 档拒绝",
               _run(p.require_layer_write, "knowledge", "internal") == "PASS"
               and _run(p.require_layer_write, "knowledge", "secret").startswith("DENY"),
               (_run(p.require_layer_write, "knowledge", "internal"),
                _run(p.require_layer_write, "knowledge", "secret")))
        _check("R2 ⇒ 若 _resolve_target 改回 secret，A1 必转红（判别力成立）",
               _run(protect.guard_overwrite, cg, "legacy_nokey",
                    layer="knowledge", sensitivity="secret") == "DENY(AccessDenied)",
               _run(protect.guard_overwrite, cg, "legacy_nokey",
                    layer="knowledge", sensitivity="secret"))
        cg.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 60)
    print("#450 守卫：%d 通过，%d 失败" % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print("  红项：" + f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
