# -*- coding: utf-8 -*-
r"""守卫 · #66 两条口径（子项一 甲=维持幂等口径；子项二 乙=seed 可注入默认 0）。

zcode 端 2026-10-09 裁定「一甲二乙」：
  · 子项一（_handled 幂等名单）：甲 —— 维持「只认改过的单条记录」，**零代码改动**，只补文档。
  · 子项二（sample 的 seed）：乙 —— seed 可注入、**默认仍 0**；不传时行为逐字不变。

判据（真跑真库）：
  G1 seed 不传 ≡ seed=0（默认路径逐字不变，回归）
  G2 seed 显式注入 ⇒ 抽样结果随之改变（可注入确实生效）
  G3 _handled 只认 op==decontaminate 且 ok 的单条记录（口径断言，防被"放宽为认汇总"）
运行：python -X utf8 -m md_cg.test_issue66_scrub_semantics
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []
N = 40
SIX = ("# 功能名：t\n# 生效条件：t\n# 子功能：t\n# 执行：t\n"
       "# 验证方式：t\n# 不适用条件：t\n")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def _cg(root):
    from md_cg import tokens as TK
    from md_cg.mdcos import MdCGSecure
    prof = os.environ.get("MDCG_DSH_PROFILE") or ""
    tok = None
    if prof:
        try:
            m = re.search("MDCG_TOKEN:[ ]*'([^']+)'",
                          open(prof, encoding="utf-8", errors="replace").read())
            tok = m.group(1) if m else None
        except OSError:
            tok = None
    return MdCGSecure(root, principal=TK.verify_token(tok) if tok else None)


def main():
    from md_cg import scrub
    root = tempfile.mkdtemp(prefix="p66_")
    cg = _cg(root)
    for i in range(N):
        cg.add("q_%03d" % i, SIX + "body %d\n" % i)

    ids = lambda s: [x[0] for x in (s.get("picked") or s.get("items") or [])]
    a = scrub.sample(cg, 8, strategy="risk")
    b = scrub.sample(cg, 8, strategy="risk", seed=0)
    out_a, out_b = ids(a), ids(b)
    if not out_a:                      # 兜底取法（结构不同则按返回体键探测）
        out_a = [str(x) for x in (a.get("sample") or [])]
        out_b = [str(x) for x in (b.get("sample") or [])]
    check("G1 seed 不传 ≡ seed=0（默认路径逐字不变）",
          out_a == out_b and len(out_a) > 0, "n=%d" % len(out_a))

    c = scrub.sample(cg, 8, strategy="risk", seed=20261009)
    out_c = ids(c) or [str(x) for x in (c.get("sample") or [])]
    check("G2 seed 显式注入 ⇒ 抽样结果随之改变（可注入生效）",
          out_c != out_a, "seed=None n=%d 与 seed=20261009 n=%d 是否相同=%r"
          % (len(out_a), len(out_c), out_c == out_a))

    # G3 _handled 口径：只认单条 decontaminate 且 ok
    log = os.path.join(root, scrub.SCRUB_LOG)
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "w", encoding="utf-8") as f:
        f.write(json.dumps({"op": "decontaminate", "ok": True, "node_id": "X1", "kind": "k1"}) + "\n")
        f.write(json.dumps({"op": "decontaminate", "ok": False, "node_id": "X2", "kind": "k2"}) + "\n")
        f.write(json.dumps({"op": "sweep_summary", "ok": True, "node_id": "X3", "kind": "k3"}) + "\n")
    h = scrub._handled(cg)
    check("G3 _handled 只认单条 decontaminate 且 ok（口径未被放宽）",
          (("X1", "k1") in h) and (("X2", "k2") not in h) and (("X3", "k3") not in h),
          "handled=%r" % (sorted(h),))

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
