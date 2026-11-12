# -*- coding: utf-8 -*-
"""外测 2026-11-11 两个卡点守卫。

卡点 1：`_pick` 部分命中抑制——只要有一条命中就把同桶其余节点全丢（锚点在桶里也消失）。
卡点 2：`recall` 没有 `now` 入口——生产装包按真实时钟算，宿主/外部复测丢逻辑时钟。
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def main():
    print("=" * 66)
    print("卡点 1（命中抑制）/ 卡点 2（recall 时钟）/ 跨桶轮转")
    print("=" * 66)
    root = tempfile.mkdtemp(prefix="card_")
    g = MdCGOS(root, actor="test")
    now = time.mktime(time.strptime("2026-07-10 12:00:00", "%Y-%m-%d %H:%M:%S"))
    day = time.mktime(time.strptime("2026-05-03 10:00:00", "%Y-%m-%d %H:%M:%S"))
    # 同一天三条：只有 114 命中 query 词，锚点 116 不命中
    g.add("114", CCG.format(n="命中的", s="w", e="1", body="陪爸 开药 相关"),
          created_at=day, session="other")
    g.add("115", CCG.format(n="中间", s="w", e="2", body="别的 内容"),
          created_at=day + 60, session="other")
    g.add("116", CCG.format(n="锚点", s="w", e="3", body="完全 无关 措辞"),
          created_at=day + 120, session="other")
    bi.build(g, write=True, with_content=True)

    # 直接测 _pick 的补足行为：需显式 fill_rest（缺省关，以保持「最近 N 天」兜底不塞无关条目）
    picked = bs._pick(g, ["114", "115", "116"], bs._terms("陪爸 开药"), 8, fill_rest=True)
    ids = [n.get("id") for n, _s, _q, _p in picked]
    ok("114" in ids, "K1a 命中节点在", ids)
    ok("116" in ids, "K1b **锚点（零命中）也按时间补足进来**", ids)
    ok(len(ids) == 3, "K1c 同桶补足到桶内全部（cap 允许）", ids)

    # 跨桶轮转：8 个桶各 3 条，cap=4 → 至少覆盖 4 个不同桶
    root2 = tempfile.mkdtemp(prefix="rr_")
    g2 = MdCGOS(root2, actor="test")
    base = time.mktime(time.strptime("2026-04-01 10:00:00", "%Y-%m-%d %H:%M:%S"))
    for i in range(8):
        for j in range(3):
            g2.add("d%d_%d" % (i, j), CCG.format(n="n", s="w", e=str(j), body="陪爸 开药 记录"),
                   created_at=base + i * 86400, session="s%d" % i)
    bi.build(g2, write=True, with_content=True)
    now2 = time.mktime(time.strptime("2026-07-10 12:00:00", "%Y-%m-%d %H:%M:%S"))
    picked2 = bs.scope_recall(g2, "我最早陪爸开药", session=None, now=now2, cap=4)
    buckets = {q.get("bucket") for _n, _s, q, _p in picked2}
    ok(len(buckets) >= 3, "K2 跨桶轮转：4 个名额覆盖 ≥3 个不同日桶", buckets)

    ok("now" in inspect.signature(MdCGOS.recall).parameters, "K3a recall 签名含 now")
    pack = g.recall("陪爸 开药", budget_tokens=4000, k=10, now=now)
    metas = [it.get("metadata") or {} for it in (pack.get("items") or pack.get("pack") or [])]
    rd = [m.get("resolved_dates") for m in metas if m.get("resolved_dates")]
    ok(True, "K3b recall(now=) 可调用且不炸", (len(metas), rd[:2]))

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())