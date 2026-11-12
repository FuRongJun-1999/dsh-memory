# -*- coding: utf-8 -*-
"""三类病因并联修复守卫（外测 2026-11-11 #858 判别结果）。

① 名额：锚点在池内排第 5、日名额只有 4   → 早段意图会话配额 4→2（日桶得 6）
② 桶内闸：该日词表与 query 无交集 ⇒ 不补足 → 早段/两端/证据选入的桶也算「有理由」
③ 池生成：均匀采样漏掉有强证据的那天     → 证据前置到池生成（_early_candidates）
"""
from __future__ import annotations

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
    print("三类病因：名额 / 桶内闸 / 池生成")
    print("=" * 66)
    root = tempfile.mkdtemp(prefix="three_")
    g = MdCGOS(root, actor="test")
    base = time.mktime(time.strptime("2026-04-12 10:00:00", "%Y-%m-%d %H:%M:%S"))
    N = 31
    docs = []
    for i in range(N):
        ts = base + i * 86400
        if i in (18, 28):
            body = "江北回声 陪爸开药 替班 交换架"
        elif i == 30:
            body = "orphan 用户 又 到 这 个 点 了"
        else:
            body = "日常 闲聊 记录"
        for j in range(3):
            g.add("d%02d_%d" % (i, j), CCG.format(n="x", s="w", e=str(j), body=body),
                  created_at=ts, session="s%02d" % i)
        docs.append(time.strftime("%Y-%m-%d", time.localtime(ts)))
    bi.build(g, write=True, with_content=True)
    now = time.mktime(time.strptime("2026-06-10 12:00:00", "%Y-%m-%d %H:%M:%S"))
    q = "我最早陪爸开药是哪天"
    terms = bs._terms(q)

    pool = bs._early_candidates(g, sorted(bi.all_days(g)), terms)
    ok(docs[18] in pool, "E1 ①③ 池生成含「均匀采样会漏掉但有强证据」的那天", pool[:4])
    ok(pool[0] == docs[28] or pool[0] == docs[18],
       "E2 证据最强的那天排池首", pool[:3])
    ok(docs[30] in pool, "E3 无证据的末日仍靠两端兜底在池里", pool[:5])

    ok(bs.SESSION_QUOTA_EARLY < bs.SESSION_QUOTA, "E4 早段意图会话配额更小（名额让给日桶）",
       (bs.SESSION_QUOTA_EARLY, bs.SESSION_QUOTA))

    picked = bs.scope_recall(g, q, session="s30", now=now, cap=8)
    buckets = [str(qq.get("bucket")) for _n, _s, qq, _p in picked]
    sess_n = len([b for b in buckets if b == "session"])
    ok(sess_n <= bs.SESSION_QUOTA_EARLY, "E5 早段意图会话桶 ≤ SESSION_QUOTA_EARLY", buckets)
    ok(any(b.endswith(docs[18]) for b in buckets), "E6 04-30 强证据日进 pack", buckets)
    ok(any(b.endswith(docs[28]) for b in buckets), "E7 倒数第三（强证据）进 pack", buckets)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())