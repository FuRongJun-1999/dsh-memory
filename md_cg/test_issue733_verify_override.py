# -*- coding: utf-8 -*-
"""issue #733 守卫：`verify(override=True)` 必须能推进受保护节点的验证态。

## 病象
对**受保护节点**（self/anchor 层、protected 位、importance>=0.70 按分保护）
发起 `verify(..., "weakened", override=True)`：

- 回执 `verification.ok == False`、`error == "protected"`；
- `verification_state` 停在原值（如 unverified）；
- 而 `confidence` / `evidence_count` / `evidence_log` **已按 weakened 扣减并落盘**
  ⇒ 「证据记了、结论没落地」的盘面不自洽态。

拒绝提示语写的是「确需降级请显式 override=True」——**调用方照做却仍被拒**。

## 根因
`MdCG.verify` 的 `override` 只透传给了 falsified 分支的
`protect.guard_forget`；两条正常裁决分支（confirmed / weakened）调
`set_verification` 时整段没带 `override`，于是下游 `trust.set_state` →
`stamp` 看到的恒为缺省 `False`，受保护节点的降级迁移被无条件拒绝。

## 断言面（每条＝一个可定点变异的判据）
- **O1 override=True 生效**：受保护节点的 weakened 裁决真正落到 doubted。
- **O2 override=False 仍拒**（保护语义**未放宽**）：不传/传 False 时照旧
  `ok=False`、状态不变——这是与 O1 配对的反向判据，防止「一律放行」的假修复。
- **O3 非保护节点不受影响**：缺省调用（不传 override）照常落到 doubted，
  既有调用方行为逐位不变。
- **O4 confirmed 分支同源透传**：受保护节点 confirmed（升格方向）不因保护被拒。

运行：python -X utf8 -m md_cg.test_issue733_verify_override
退出码（fail-closed）：0 = 全绿；1 = 有断言失败。
沙箱纪律：库根落守卫临时目录，绝不碰在役库与 ~/.mdcg。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from md_cg.mdcg import MdCG                      # noqa: E402

_FAILED = []


def ok(cond, msg):
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        _FAILED.append(msg)


_BODY = (
    "# 功能名：override 透传守卫节点\n"
    "# 生效条件：守卫自检时\n"
    "# 子功能：构造受保护 / 非保护两类节点\n"
    "# 执行：verify 后比对 verification_state\n"
    "# 验证方式：本条测试\n"
    "# 不适用条件：无\n"
)


def _fresh_root(tag: str) -> str:
    return tempfile.mkdtemp(prefix="mdcg733-" + tag + "-")


def _mk_protected(cg, nid):
    """构造受保护节点：importance>=0.70 触发按分保护。"""
    cg.add(nid, _BODY, layer="knowledge", tags=["t"], importance=0.9)
    fm = (cg.get(nid) or {}).get("frontmatter") or {}
    return fm


def _mk_normal(cg, nid):
    cg.add(nid, _BODY, layer="knowledge", tags=["t"], importance=0.2)
    return (cg.get(nid) or {}).get("frontmatter") or {}


def o1_override_true_lands():
    """O1：受保护节点 weakened + override=True → 真的落到 doubted。"""
    print("== O1 override=True 生效 ==")
    root = _fresh_root("o1")
    try:
        cg = MdCG(root)
        fm = _mk_protected(cg, "o1")
        ok(bool(fm.get("protected")) is True,
           "O1 前置：节点确为受保护（protected=%r importance=%r）"
           % (fm.get("protected"), fm.get("importance")))
        res = cg.verify("o1", "外部证据：overridden", "weakened", override=True)
        ver = res.get("verification") or {}
        after = (cg.get("o1") or {}).get("frontmatter") or {}
        ok(ver.get("ok") is True,
           "O1 verification.ok 为真（实际 %r error=%r）"
           % (ver.get("ok"), ver.get("error")))
        ok(after.get("verification_state") == "doubted",
           "O1 verification_state 落到 doubted（实际 %r）"
           % (after.get("verification_state"),))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def o2_override_false_still_denies():
    """O2：不传 override 时**仍然拒绝**（保护语义不得放宽）。"""
    print("== O2 override 缺省仍拒 ==")
    root = _fresh_root("o2")
    try:
        cg = MdCG(root)
        fm = _mk_protected(cg, "o2")
        before = fm.get("verification_state")
        res = cg.verify("o2", "外部证据：无 override", "weakened")
        ver = res.get("verification") or {}
        after = (cg.get("o2") or {}).get("frontmatter") or {}
        ok(ver.get("ok") is False,
           "O2 缺省 override 时 verification.ok 为假（实际 %r）" % (ver.get("ok"),))
        ok(ver.get("error") == "protected",
           "O2 拒绝码为 protected（实际 %r）" % (ver.get("error"),))
        # review ①：`after == before` 在 before 为 None 时会退化成「仍是 None」，
        # 分不出 unverified -> None 这种破坏。改成**显式等值对**：
        # 先钉死 before 属于合法初态集合，再断言 after 与之逐位相等。
        ok(before in (None, "unverified"),
           "O2 前置：初态属于合法集合 {None, unverified}（实际 %r）" % (before,))
        ok(after.get("verification_state") == before,
           "O2 受保护节点状态未被改动（前=%r 后=%r）"
           % (before, after.get("verification_state")))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def o3_normal_unaffected():
    """O3：非保护节点缺省调用行为不变。"""
    print("== O3 非保护节点不受影响 ==")
    root = _fresh_root("o3")
    try:
        cg = MdCG(root)
        _mk_normal(cg, "o3")
        res = cg.verify("o3", "外部证据：常规", "weakened")
        ver = res.get("verification") or {}
        after = (cg.get("o3") or {}).get("frontmatter") or {}
        ok(ver.get("ok") is True,
           "O3 非保护节点缺省 verify 成功（实际 ok=%r）" % (ver.get("ok"),))
        ok(after.get("verification_state") == "doubted",
           "O3 非保护节点落到 doubted（实际 %r）"
           % (after.get("verification_state"),))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def o4_confirmed_branch_carries_override():
    """O4：confirmed 分支同样透传 override（升格方向不被保护误拦）。"""
    print("== O4 confirmed 分支同源 ==")
    root = _fresh_root("o4")
    try:
        cg = MdCG(root)
        _mk_protected(cg, "o4")
        # review ②：原写法是恒真测试——confirmed 是升格方向（verified rank 全局
        # 最小），旧码此处本就 ok=True，回退补丁也不变红。改为 monkeypatch
        # 捕获 set_verification 实际收到的 override 实参：回退 ⇒ False ⇒ 红。
        seen = {}
        orig = cg.set_verification

        def spy(node_id, state, **kw):
            seen["override"] = kw.get("override")
            return orig(node_id, state, **kw)

        cg.set_verification = spy
        cg.verify("o4", "外部证据：确认", "confirmed", override=True)
        ok(seen.get("override") is True,
           "O4 set_verification 实际收到 override=True（实收 %r）"
           % (seen.get("override"),))
    finally:
        shutil.rmtree(root, ignore_errors=True)


_GROUPS = (o1_override_true_lands, o2_override_false_still_denies,
           o3_normal_unaffected, o4_confirmed_branch_carries_override)


def main():
    for fn in _GROUPS:
        fn()
    print("=" * 68)
    if _FAILED:
        print("verify override 透传守卫：%d 条失败" % len(_FAILED))
        for m in _FAILED:
            print("  - " + m)
        return 1
    print("verify override 透传守卫：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())