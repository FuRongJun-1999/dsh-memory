# -*- coding: utf-8 -*-
r"""守卫 · #89② 0 分条目不得装进检索结果（2026-10-09 DSH 端实施）。

缺陷（GitHub #89）：无关查询（如「红烧肉怎么做」）会返回 k 条**分数全为 0.0** 的
条目——它们没有质量信号，对调用方无价值且有误导（LLM 会当成相关内容）。

判据（真跑真库）：
  G1 无关查询 ⇒ **不返回任何 0 分条目**（修前返回 5 条 0 分）
  G2 精确命中 ⇒ 仍正常返回（score > 0 者不受影响）
  G3 混合 ⇒ 结果集内**不存在** score == 0 的条目
运行：python -X utf8 -m md_cg.test_issue89_zero_score
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []
SIX = lambda s: ("# 功能名：t\n# 生效条件：t\n# 子功能：t\n# 执行：" + s
                 + "\n# 验证方式：t\n# 不适用条件：t\n")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def main():
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    root = tempfile.mkdtemp(prefix="p89g_")
    p = Principal(actor="guard", clearance="secret", can_write=True, can_admin=True,
                  role="designer", auth_mode="local-cli", session="guard")
    cg = MdCGSecure(root, principal=p, autoflush=0)
    for i in range(120):
        cg.add("k%04d" % i, SIX("主题%d 关键词 KW%04d 说明 %d" % (i % 10, i, i)))
    cg.flush()

    def rows(q):
        docs, _stat = cg.search(q, k=5)
        out_ = []
        for it in docs:
            if isinstance(it, tuple):
                _id = (it[0] or {}).get("id") if isinstance(it[0], dict) else None
                out_.append((_id, it[1] if len(it) > 1 else None))
        return out_

    irr = rows("红烧肉怎么做")
    zero = [x for x in irr if float(x[1] or 0) == 0.0]
    check("G1 无关查询 ⇒ 不返回 0 分条目（修前返回 5 条 0 分）",
          len(zero) == 0, "返回 %d 条，其中 0 分 %d 条" % (len(irr), len(zero)))

    hit = rows("KW0007")
    check("G2 精确命中 ⇒ 仍正常返回", len(hit) >= 1 and any(float(s or 0) > 0 for _, s in hit),
          "hit=%r" % (hit[:3],))

    check("G3 结果集内不存在 score == 0 的条目",
          all(float(s or 0) > 0 for _, s in irr), "irr=%r" % (irr[:5],))

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
