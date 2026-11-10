# -*- coding: utf-8 -*-
"""时间线（`recall.timeline`）守卫：「日期 | 事件首句」必须由算法给出，不靠模型归纳。

背景（2026-11-11 外测，Ornn8 B 类 19 题）：模型面对 20–30 条按检索分排的片段时，
**没有确定性的时序依据**去选「最早那次」——同一题两次跑给出不同锚点（P20-037：6-22 vs 5-22）。
提示词让它「按日期排序再取最早」，它排的是自己回忆的顺序，不是材料里的日期序。
故时间线必须作为一等公民由算法产出：`(date, id, head)`，按日期升序。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import bucketindex as bi  # noqa: E402
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
    print("recall.timeline：日期 | 事件首句（按日期升序）")
    print("=" * 66)
    root = tempfile.mkdtemp(prefix="tl_")
    g = MdCGOS(root, actor="test")
    d1 = time.mktime(time.strptime("2026-04-01 10:00:00", "%Y-%m-%d %H:%M:%S"))
    d2 = time.mktime(time.strptime("2026-04-02 10:00:00", "%Y-%m-%d %H:%M:%S"))
    d3 = time.mktime(time.strptime("2026-07-20 10:00:00", "%Y-%m-%d %H:%M:%S"))
    # 故意**乱序写入**，验证输出按日期升序而不是写入序
    g.add("n3", CCG.format(n="回忆", s="w", e="3", body="回忆：那次排了四十分钟"),
          created_at=d3, session="s")
    g.add("n1", CCG.format(n="首次", s="w", e="1", body="首次提及：明天陪爸去社区医院开药"),
          created_at=d1, session="s")
    g.add("n2", CCG.format(n="当日", s="w", e="2", body="当日：排队快一个钟头"),
          created_at=d2, session="s")
    bi.build(g, write=True, with_content=True)
    pack = g.recall("陪爸开药 排队", budget_tokens=4000, k=10)
    tl = pack.get("timeline")
    n_pack = len(pack.get("pack") or [])
    ok(isinstance(tl, list) and len(tl) == n_pack and n_pack >= 2,
       "T1 timeline 与 pack 逐条对齐（%d 条）" % n_pack, (type(tl).__name__, len(tl) if isinstance(tl, list) else "-"))
    dates = [x.get("date") for x in tl]
    ok(dates == sorted(dates), "T2 按日期升序（与写入序无关）", dates)
    ok(all(x.get("id") for x in tl), "T3 每条带 id（可回溯原文）", [x.get("id") for x in tl][:3])
    heads = [x.get("head") or "" for x in tl]
    ok(all(h and not h.startswith("#") for h in heads), "T4 事件首句非空且跳过 CCG 头", heads[:2])
    ok(any("陪爸" in h or "排队" in h for h in heads), "T5 首句确实是事件内容", heads[:3])

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())