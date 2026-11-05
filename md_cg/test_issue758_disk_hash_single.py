# -*- coding: utf-8 -*-
"""issue #758：reconcile 的盘面指纹收单值（#741 后二元组第二元素不可达）。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import nodefile, reconcile   # noqa: E402
from md_cg.mdcg import MdCG   # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


BODY = ("# 功能名：x\n# 生效条件：y\n# 子功能：z\n# 执行：e\n"
        "# 验证方式：test\n# 不适用条件：无\n\n正文")


def main():
    print("=" * 68)
    print("issue #758 · _disk_hash 单值（含端到端收紧证明）")
    print("=" * 68)
    ok(callable(getattr(reconcile, "_disk_hash", None)), "A1 存在 _disk_hash")
    h1 = reconcile._disk_hash(BODY + "\n")
    ok(isinstance(h1, str), "A2 返回单值 str", type(h1).__name__)
    ok(h1 == nodefile.content_hash(BODY), "A2b 与索引同源（常盘 1 尾换行 == 正文本体）")
    ok(reconcile._disk_hash(BODY + "\n\n") != h1,
       "A3 ≥2 尾换行与 1 尾换行**不同值**（旧二元组会用它蒙混）")
    # A4（复核要求：端到端）——索引是「剥尽形态」× 盘面多尾换行 ⇒ 必须判 drift，且 apply 后幂等
    tmp = tempfile.mkdtemp(prefix="iss758_")
    try:
        cg = MdCG(os.path.join(tmp, "r"), autoflush=1)
        cg.add("n758", BODY, layer="knowledge")
        rel = cg.index["nodes"]["n758"].get("path")
        fp = os.path.join(cg.root, rel)
        with open(fp, "a", encoding="utf-8", newline="") as f:
            f.write("\n")                      # 盘面变 2 尾换行
        cg.index["nodes"]["n758"]["content_hash"] = nodefile.content_hash(BODY)   # 剥尽形态（旧口径）
        r1 = cg.reconcile_state(apply=False)
        ok("n758" in (r1.get("hash_drift") or []),
           "A4 索引剥尽 × 盘面多尾换行 ⇒ 判 drift（收紧生效）", r1.get("hash_drift"))
        cg.reconcile_state(apply=True)
        r2 = cg.reconcile_state(apply=False)
        ok(not (r2.get("hash_drift") or []), "A4b apply 后幂等（二次扫描不再 drift）", r2.get("hash_drift"))
        cg.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("issue #758：%d 项失败" % len(FAILS) if FAILS else "issue #758：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())