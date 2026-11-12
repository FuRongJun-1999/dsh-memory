# -*- coding: utf-8 -*-
"""#842 / #843 守卫：桶召回的「截断前含时间序」与「validity 透传」。"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import bucketindex as bi  # noqa: E402
from md_cg import bucketscope as bs  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

CCG = ('# 功能名：{n}\n# 生效条件：c\n# 子功能：s\n# 执行：e\n'
       '# 验证方式：test\n# 不适用条件：无\n\n{body}\n')
FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:160])
        FAILS.append(name)


def main():
    print("=" * 66)
    print("#842 截断前含时间序 / #843 validity 透传")
    print("=" * 66)
    base = time.mktime(time.strptime("2026-11-09 09:00:00", "%Y-%m-%d %H:%M:%S"))
    for count in (8, 9):
        root = tempfile.mkdtemp(prefix="g842_")
        g = MdCGOS(root, actor="test")
        for i in range(count):
            g.add("a%02d" % i, CCG.format(n="节点%d" % i, s="w", e=str(i), body="索引"),
                  created_at=base + i, session="s")
        bi.build(g, write=True)
        picked = bs.session_scope(g, "索引", "s", cap=8)
        ids = [n.get("id") for n, _s, _q, _p in (picked or [])]
        newest = "a%02d" % (count - 1)
        ok(newest in ids, "#842 count=%d 时最新条 %s 仍在桶召回里" % (count, newest), ids)
        ok(len(ids) == min(8, count), "#842 count=%d 条数=%d" % (count, len(ids)), ids)

    # #843：validity=True 时桶补召回不得装回过期节点
    root = tempfile.mkdtemp(prefix="g843_")
    g = MdCGOS(root, actor="test")
    now = time.time()
    g.add("active", CCG.format(n="现行", s="w", e="1", body="阀门 合成规格 现行"),
          created_at=now, session="s")
    g.add("expired", CCG.format(n="过期", s="w", e="2", body="阀门 合成规格 旧版"),
          created_at=now - 10, session="s", valid_until="2000-01-01")
    bi.build(g, write=True)
    pack = g.recall("阀门 合成规格", budget_tokens=4000, k=10, validity=True)
    items = pack.get("items") or pack.get("pack") or []
    ids = [it.get("id") for it in items]
    ok("expired" not in ids, "#843 validity=True 不装回过期节点", ids)
    ok("active" in ids, "#843 现行节点仍在", ids)
    os.environ["MDCG_BUCKET_SCOPE"] = "0"
    pack2 = g.recall("阀门 合成规格", budget_tokens=4000, k=10, validity=True)
    ids2 = [it.get("id") for it in (pack2.get("items") or pack2.get("pack") or [])]
    ok("expired" not in ids2, "#843 关闭桶召回时同样不含过期（对照）", ids2)
    os.environ.pop("MDCG_BUCKET_SCOPE", None)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())