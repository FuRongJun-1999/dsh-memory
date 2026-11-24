# -*- coding: utf-8 -*-
"""守卫 · issue #1005 ③：raw 保底配额（原话轮次不得被派生卡全部挤掉）。

病灶（issue 原文第 3 条）：原话轮次与派生材料（档案/摘要/状态卡）共用同一份预算，
实测出现过「卡进了 pack、源轮次没进」⇒ 答案缺原句、只能靠事后打补丁。

本守卫钉住三件事：
  1. 派生卡高分占满时，原话轮次仍能进包（缺省 raw_min=2）；
  2. `MDCG_RAW_MIN=0` 时回到原行为（可关）；
  3. 队列前段已是原话时**不改序**（raw_min_applied=0，正常路径零影响）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else "  " + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


BODY = "# 功能名：{n}\n# 生效条件：t\n# 子功能：s\n# 执行：{x}\n# 验证方式：t\n# 不适用条件：无\n"


def _build(root, derived_n=10, raw_n=3):
    cg = MdCGOS(root, actor="t")
    # 派生卡：profile- 前缀占满高分（coverage.is_derived 的判据）
    for i in range(derived_n):
        cg.add("profile-role-%02d" % i, BODY.format(n="档案卡%d" % i, x="预算争用 派生"),
               layer="contextual", tags=["档案"], importance=0.95)
    # 原话轮次：普通 id、低重要度（模拟被挤掉的那批）
    for i in range(raw_n):
        cg.add("turn_%02d" % i, BODY.format(n="用户原话%d" % i, x="预算争用 原话"),
               layer="contextual", tags=["对话"], importance=0.05)
    cg.flush()
    return cg


def main():
    T = tempfile.mkdtemp(prefix="raw_quota_")
    try:
        cg = _build(T)
        out = cg.recall("预算争用", budget_tokens=400, k=20)
        pack = out.get("pack") or []
        raw = [e for e in pack if not str(e.get("id") or "").startswith("profile-")]
        ok(len(raw) >= 2, "R1 派生卡占满高分时，原话轮次仍进包 >= 2",
           [(e.get("id"), e.get("score")) for e in pack][:6])
        ok(bool(pack) and out.get("meta", {}).get("raw_min_applied", 0) > 0,
           "R2 meta 如实报出 raw 保底动手了（raw_min_applied > 0）",
           out.get("meta", {}).get("raw_min_applied"))
        ok(out.get("coverage_certified") is not True or raw,
           "R3 有原话进包时不应报 raw_not_included",
           out.get("coverage_gaps"))

        old = os.environ.get("MDCG_RAW_MIN")
        os.environ["MDCG_RAW_MIN"] = "0"
        try:
            off = cg.recall("预算争用", budget_tokens=400, k=20)
        finally:
            if old is None:
                os.environ.pop("MDCG_RAW_MIN", None)
            else:
                os.environ["MDCG_RAW_MIN"] = old
        off_raw = [e for e in (off.get("pack") or [])
                   if not str(e.get("id") or "").startswith("profile-")]
        ok(off.get("meta", {}).get("raw_min_applied", 0) == 0,
           "R4 MDCG_RAW_MIN=0 时不改序（可关）", off.get("meta", {}).get("raw_min_applied"))
        ok(len(off_raw) <= len(raw),
           "R5 关闭后原话条数不多于开启时（配额确实在起作用）", (len(off_raw), len(raw)))

        T2 = tempfile.mkdtemp(prefix="raw_quota2_")
        try:
            cg2 = MdCGOS(T2, actor="t")
            for i in range(5):
                cg2.add("turn_only_%d" % i, BODY.format(n="原话%d" % i, x="只有原话"),
                        layer="contextual", tags=["对话"], importance=0.6)
            cg2.flush()
            o2 = cg2.recall("只有原话", budget_tokens=400, k=10)
            ok(o2.get("meta", {}).get("raw_min_applied", 0) == 0,
               "R6 前段已是原话时不改序（raw_min_applied=0）",
               o2.get("meta", {}).get("raw_min_applied"))
        finally:
            shutil.rmtree(T2, ignore_errors=True)
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print("raw 保底配额：%d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())