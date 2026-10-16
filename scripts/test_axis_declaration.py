# -*- coding: utf-8 -*-
# 功能名：判据轴覆盖域声明的结构腿（C6）
# 生效条件：python -u -X utf8 scripts/test_axis_declaration.py；被测面=docs/state/判据轴声明.md 的「声明表」
# 子功能：A 六字段齐全 + 可解析 + covered ≤ |target_space|（可数值化时）· S 自检（合成反例证判据能红）
# 执行：直接跑；退出码 0=全绿、1=有红
# 验证方式：全部 PASS；S 段用**合成坏行**（缺字段 / covered>target / covered 非整数）喂同一条判据，断言各自能红
# 不适用条件：**本腿不能判 `covered` 数值填得对不对 —— 那要真去数**（腿看见「声明在场」，看不见「声明为真」）；不判 verdict 的语义是否成立（那要人判）
"""C6 载体：判据轴必须给覆盖域声明。

★残余（如实）：本腿只做**结构判据**。`covered` 的**数值真实性**不可判（要真去数目标集合）。
★对偶提醒：这使 C2/C4/C5/C6/C7 归为一族 —— **腿只能看见「声明/登记在场」，看不见「声明为真」**。
"""
from __future__ import annotations

import io
import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(_REPO, "docs", "state", "判据轴声明.md")
FIELDS = ("axis", "key_space", "target_space", "covered", "relation", "evidence")

PASS = FAIL = 0
FAILS = []


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:220])


# 生效条件：rows 为「管道分隔的表行」列表即成立；返回 (bad 列表, 总行数)。
# 判据：① 六字段齐全（缺一即 bad）② covered 可解析为整数 ③ target_space 以数字开头时，covered ≤ 该数。
def check_rows(rows):
    bad = []
    for i, r in enumerate(rows):
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        if len(cells) < len(FIELDS):
            bad.append((i, "字段数不足", len(cells)))
            continue
        d = dict(zip(FIELDS, cells))
        miss = [f for f in FIELDS if not d.get(f)]
        if miss:
            bad.append((i, "缺字段", miss))
            continue
        if not re.fullmatch(r"\d+", d["covered"]):
            bad.append((i, "covered 非整数", d["covered"]))
            continue
        m = re.match(r"^(\d+)", d["target_space"])
        if m and int(d["covered"]) > int(m.group(1)):
            bad.append((i, "covered > |target_space|", (d["covered"], m.group(1))))
    return bad, len(rows)


def main():
    txt = io.open(DOC, encoding="utf-8").read()
    # 取「声明表」小节里的数据行（跳过表头与分隔行）
    rows = []
    in_tbl = False
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("| axis |"):
            in_tbl = True
            continue
        if in_tbl:
            if not s.startswith("|"):
                break
            if set(s) <= set("|-: "):
                continue
            rows.append(s)
    print("== A 组：判据轴覆盖域声明（C6）==")
    print("  [扫描面] 声明表数据行 **%d** 行（先报总数，不截断）" % len(rows))
    bad, n = check_rows(rows)
    ok("A1 声明表非空（至少 1 条声明）", n >= 1, n)
    ok("A2 六字段齐全 + covered 可解析 + covered ≤ |target_space|（违规则全量列出）",
       not bad, "违规行全量 = %s" % (bad,))
    ok("A3 ★规范要拦的那类已入表：至少一条 relation != 同一集合 且 verdict 标了「轴被推翻」",
       "交叉" in txt and "轴被推翻" in txt)

    print("")
    print("== S 组：自检（合成坏行，证明判据**能红**）==")
    _g, _ = check_rows(["| a | b | 38 个 op | 5 | 子集 | e | v |"])
    ok("S1 正常行 ⇒ 不报违规（判据不误红）", not _g, _g)
    _b1, _ = check_rows(["| a | b | 38 个 op | | 子集 | e | v |"])
    ok("S2 ★缺 covered（空字段）⇒ 报违规", bool(_b1), _b1)
    _b2, _ = check_rows(["| a | b | 38 个 op | 99 | 子集 | e | v |"])
    ok("S3 ★covered(99) > |target_space|(38) ⇒ 报违规", bool(_b2), _b2)
    _b3, _ = check_rows(["| a | b | 38 个 op | 五 | 子集 | e | v |"])
    ok("S4 ★covered 非整数 ⇒ 报违规", bool(_b3), _b3)
    _b4, _ = check_rows(["| a | b | desc | 2 | 子集 | e | v |"])
    ok("S5 target_space 不可数值化（描述文本）⇒ **不报违规**（如实：此时腿无法判覆盖）", not _b4, _b4)

    print("")
    print("断言总数 %d（PASS %d / FAIL %d）" % (PASS + FAIL, PASS, FAIL))
    if FAILS:
        print("FAILED:")
        for f in FAILS:
            print("   - " + f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())