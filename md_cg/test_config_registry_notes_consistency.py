# -*- coding: utf-8 -*-
"""守卫 · 配置登记表的 notes 不得与同一行的 value 说反话（issue #1004，与 #1000 同型）。

起因：_TABLE_ROWS 的 notes 是**自由文本**，config_registry_guard 只机械复核
value / semantic / domain 那几列（缺省逐位相等、值域、样本名），**不校验 notes 与
value 是否自相矛盾**。于是 ("sleep","scrub_apply","1","on","…（缺省关：只盘点不落盘）")
这种「值说开、注释说关」在结构上不可能被守卫发现——而它恰好是**安全预期与行为相反**
的那一类（去污染到底真落盘还是 dry-run）。

判据刻意只做「同一行内自洽」，不猜语义：
  N1 凡 notes 出现「缺省开/默认开」⇒ 同行 value 必须为真值
  N2 凡 notes 出现「缺省关/默认关」⇒ 同行 value 必须为假值
  N3 至少能判出若干条（防空过）

运行：python -m md_cg.test_config_registry_notes_consistency
"""
from __future__ import annotations

import sys

from .config_registry import _TABLE_ROWS

ON_WORDS = ("缺省开", "默认开")
OFF_WORDS = ("缺省关", "默认关")
FALSY = (None, False, 0, "", "0", "off", "false", "False", "no")


def _truthy(value) -> bool:
    return value not in FALSY


def check(name, cond, detail=""):
    assert cond, "[FAIL] %s %s" % (name, detail)
    print("[ok] %s" % name)


def main():
    on_claims, off_claims, bad = 0, 0, []
    for row in _TABLE_ROWS:
        area, key, value = row[0], row[1], row[2]
        notes = " ".join(str(x) for x in row[3:] if isinstance(x, str))
        if any(w in notes for w in ON_WORDS):
            on_claims += 1
            if not _truthy(value):
                bad.append((area, key, "notes 称缺省开", value))
        if any(w in notes for w in OFF_WORDS):
            off_claims += 1
            if _truthy(value):
                bad.append((area, key, "notes 称缺省关", value))
    check("N1/N2 notes 的缺省声称与同行 value 一致", not bad, bad[:3])

    # N3 防空过：_TABLE_ROWS 之外，ENV_CATEGORY_ROWS 里也有同类声称（无法机械核对 value，
    #    只用来证明这一类文本在仓库里确实存在，避免上面的判据在数据搬走后变成空转）。
    from .config_registry_bulk import ENV_CATEGORY_ROWS
    bulk_claims = sum(1 for r in ENV_CATEGORY_ROWS
                      if any(w in " ".join(str(x) for x in r if isinstance(x, str))
                             for w in ON_WORDS + OFF_WORDS))
    check("N3 至少判出 3 条缺省声称（防空过）",
          on_claims + off_claims + bulk_claims >= 3,
          (on_claims, off_claims, bulk_claims))

    # N4 #1004 定点回归：scrub_apply 缺省是「开」（真落盘）——三处表述必须同口径。
    import io
    import os
    _src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sleep.py"),
                   encoding="utf-8").read()
    _rows = {(r[0], r[1]): r for r in _TABLE_ROWS}
    _note = " ".join(str(x) for x in _rows[("sleep", "scrub_apply")][3:] if isinstance(x, str))
    check("N4a 登记表 notes 说 scrub_apply 缺省开", "缺省开" in _note, _note[:60])
    check('N4b sleep.py 生效条件头写 scrub_apply 缺省 "1"',
          '缺省 "1"' in _src, "未找到")
    check("N4c sleep.py 的默认值字面量仍是 \"1\"",
          '"scrub_apply": "1",' in _src, "未找到")
    print()
    print("配置登记表 notes 自洽守卫：全部通过（开 %d 条 / 关 %d 条）" % (on_claims, off_claims))

if __name__ == "__main__":
    sys.exit(main())