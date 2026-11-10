# -*- coding: utf-8 -*-
"""#856 / #857 守卫：time 导入（validity 生效）与多轮轮转（cap 补满）。

#856：`bucketscope` 用了 `time.*` 却没导入 ⇒ `validity=True` 时 `_is_expired` 抛 NameError，
      被 mdcos 的桶召回外层 except 吞掉 ⇒ **桶补召回整体静默失效**。
      （旧守卫 `test_bucket_recency_guards` 为何没抓到：它只断言「expired 不在 pack」，
       而失效后 pack 里本来就没有 —— 假绿。）
#857：跨日桶轮转只跑一轮；某些日桶只出 0–1 条时永远补不满（9 条匹配 + cap=8 只回 6 条）。
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
    print("#856 time 导入 / #857 多轮轮转")
    print("=" * 66)
    now = time.mktime(time.strptime("2026-07-10 12:00:00", "%Y-%m-%d %H:%M:%S"))

    # ---- #856 ----
    expired = {"frontmatter": {"valid_until": "2000-01-01"}}
    active = {"frontmatter": {"created_at": now}}
    ok(bs._is_expired(expired, now) is True, "T1 expired 判定可用（不抛 NameError）")
    ok(bs._is_expired(active, now) is False, "T2 无 valid_until 不算过期")

    root = tempfile.mkdtemp(prefix="g856_")
    g = MdCGOS(root, actor="test")
    g.add("a_live", CCG.format(n="活", s="w", e="1", body="阀门 规格 现行"),
          created_at=now, session="s")
    g.add("a_dead", CCG.format(n="死", s="w", e="2", body="阀门 规格 旧版"),
          created_at=now - 10, session="s", valid_until="2000-01-01")
    bi.build(g, write=True, with_content=True)
    # 关键：`_pick` 内部要真的调用 `_is_expired`（#856 的 NameError 就是在这里被外层吞掉的）。
    # 用「词面无命中 + fill_rest」触发按时间兜底，同时开 validity ⇒ 必须只有活节点、且不抛异常。
    ids = [n.get("id") for n, _s, _q, _p in bs._pick(
        g, ["a_live", "a_dead"], bs._terms("完全无关词"), 4,
        validity=True, now=now, fill_rest=True)]
    ok(len(ids) > 0, "T3 validity=True 时 _pick 仍能返回候选（不抛 NameError）", ids)
    ok("a_dead" not in ids, "T4 expired 不进入桶召回结果", ids)

    # ---- #857 ----
    root2 = tempfile.mkdtemp(prefix="g857_")
    g2 = MdCGOS(root2, actor="test")
    base = time.mktime(time.strptime("2026-04-01 10:00:00", "%Y-%m-%d %H:%M:%S"))
    # 3 个日桶，共 9 条命中；cap=8 ⇒ 必须补满 8 条
    k = 0
    for d in range(3):
        for j in range(3):
            g2.add("m%d" % k, CCG.format(n="x", s="w", e=str(j), body="阀门 规格 记录"),
                   created_at=base + d * 86400, session="s%d" % d)
            k += 1
    bi.build(g2, write=True, with_content=True)
    picked2 = bs.scope_recall(g2, "阀门 规格", session=None, now=now, cap=8)
    ok(len(picked2) == 8, "T5 9 条匹配 + cap=8 ⇒ 必须补满 8 条（旧版只回 6）", len(picked2))
    buckets = {q.get("bucket") for _n, _s, q, _p in picked2}
    ok(len(buckets) == 3, "T6 补满的同时仍覆盖全部 3 个日桶", buckets)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())