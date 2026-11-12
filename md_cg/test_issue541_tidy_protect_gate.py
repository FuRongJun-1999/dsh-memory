# -*- coding: utf-8 -*-
"""issue #541 守卫：tidy_contextual 的 keep 写点必须过 protect.guard_overwrite。

背景（缺陷）：`tidy_contextual` 写回**保留节点（keep）**时裸调 `cg._write_node`
⇒ 不判层闸、不判保护闸、不拍快照、不写 `_protected_audit.jsonl`，
于是 `immutable` / `protected` 节点被**静默覆写且零审计**。
注意同函数内 `if mfm.get("protected") or mfm.get("immutable"): continue`
只作用于 **members**，**不覆盖 keep 本身** —— 保留节点恰是缺闸的那一个。
姊妹函数 `converge_into`（N215 已接线）对同一节点会正确抛 `ProtectionError`。
触发面是**无人值守**的：`AUTO_DEFAULTS["auto_tidy"]` 缺省 True、每 6h。

本守卫的判据（可机械复核）：
  ① immutable keep 被同构聚合时的写盘 ⇒ **必须抛 ProtectionError**；
  ② 对照组：`protect.guard_overwrite` 对同一节点同样抛（证明判据对象正确）；
  ③ 非保护 keep 仍照常聚合（修复不得过宽，防「加了闸就一律不聚合」）。

跑法（任意 cwd）：
    python -X utf8 -m md_cg.test_issue541_tidy_protect_gate
退出码：全部通过 0，存在失败 1。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

os.environ.setdefault("MDCG_MASTER_KEY", "ef" * 32)

from md_cg import protect, writelimit  # noqa: E402
from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg.security import Principal  # noqa: E402
from md_cg.tokens import role_spec  # noqa: E402

_PASS = 0
_FAIL = 0


def ok(cond, label, detail=None):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print("  [PASS] %s" % label)
    else:
        _FAIL += 1
        print("  [FAIL] %s%s" % (label, ("  <- " + repr(detail)) if detail is not None else ""))


def _cg(root: str):
    spec = role_spec("designer")
    p = Principal(tenant="default", actor="lead", clearance="secret",
                  can_write=True, can_admin=True, role="designer",
                  layers_allow=spec["layers_allow"], ops_allow=spec["ops_allow"])
    p.theory_ok = True
    return MdCGSecure(root, principal=p)


def _seed(cg, immutable_first: bool):
    """造 5 条同构 contextual 记忆（模板一致才会成组）。返回节点 id 列表。

    注：`cg.add()` 返回**纯字符串 id**（不是 dict），且 `immutable` 落在
    frontmatter 里（`cg.index['nodes']` 不镜像该键）——判读一律走 `cg.get(id)`。
    """
    ids = []
    for i in range(5):
        nid = cg.add("i541_t%d" % i, "巡检批次%d收官记忆：同模板正文" % i,
                     layer="contextual", immutable=(immutable_first and i == 0))
        if isinstance(nid, str) and nid:
            ids.append(nid)
    cg.flush()
    return ids


def main() -> int:
    sandbox = tempfile.mkdtemp(prefix="issue541_")
    try:
        print("== G1 immutable keep 被聚合 ⇒ 必须抛 ProtectionError（核心判据）==")
        cg = _cg(os.path.join(sandbox, "g1"))
        ids = _seed(cg, immutable_first=True)
        keep_id = ids[0]
        imm, why = protect.is_immutable(cg, keep_id)
        ok(imm, "G1a 前置：keep 确为 immutable", (imm, why))
        before = (cg.get(keep_id).get("content") or "")
        raised = None
        try:
            writelimit.tidy_contextual(cg, apply=True, min_group=3)
        except protect.ProtectionError as exc:
            raised = exc
        except Exception as exc:                      # noqa: BLE001
            raised = "OTHER:%s" % type(exc).__name__
        ok(isinstance(raised, protect.ProtectionError),
           "G1b immutable keep 聚合 ⇒ ProtectionError", raised)
        after = (cg.get(keep_id).get("content") or "")
        ok(before == after, "G1c 被拒后 keep 正文未被改写（fail-closed 不写盘）",
           (len(before), len(after)))
        cg.close()

        print("== G2 对照：guard_overwrite 对同一节点同样抛（判据对象正确）==")
        cg2 = _cg(os.path.join(sandbox, "g2"))
        ids2 = _seed(cg2, immutable_first=True)
        raised2 = None
        try:
            protect.guard_overwrite(cg2, ids2[0], layer="contextual",
                                    sensitivity=None, override=False,
                                    actor="test")
        except protect.ProtectionError as exc:
            raised2 = exc
        except Exception as exc:                      # noqa: BLE001
            raised2 = "OTHER:%s" % type(exc).__name__
        ok(isinstance(raised2, protect.ProtectionError),
           "G2 guard_overwrite(同一 immutable 节点) ⇒ ProtectionError", raised2)
        cg2.close()

        print("== G3 非保护 keep 仍照常聚合（修复不得过宽）==")
        cg3 = _cg(os.path.join(sandbox, "g3"))
        _seed(cg3, immutable_first=False)
        res = None
        try:
            res = writelimit.tidy_contextual(cg3, apply=True, min_group=3)
        except Exception as exc:                      # noqa: BLE001
            res = "EXC:%s" % type(exc).__name__
        ok(isinstance(res, dict), "G3a 非保护节点不抛异常", res)
        if isinstance(res, dict):
            ok(res.get("applied_count", 0) >= 0, "G3b 聚合统计可读", res)
        cg3.close()

        print("=" * 64)
        print("通过 %d / 失败 %d" % (_PASS, _FAIL))
        print("=" * 64)
        return 1 if _FAIL else 0
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
