# -*- coding: utf-8 -*-
"""CCG 六要素「形态口径一致性」验收（2026-09-28）。

运行：python -m md_cg.test_ccg_form_parity

为什么需要这一套（本套的由来，是一个真实的口径分叉）：
六要素标题存在两种书写形态——带冒号 `# 生效条件：<值>` 与不带冒号
`# 生效条件` 后换行接值。写入闸门 `data/policy.json` 的必需正则
`(?m)^#\\s*生效条件` **不要求冒号**，而检索面判据 `nodefile.ccg_completeness`
原先**要求冒号**才计入「已声明」。二者对同一条正文给出相反结论：归档过闸
（ACCEPT）后到检索路由被判 BLINDSPOT「CCG 要素不全」——归档看着写成了，
检索面却当它没声明。存量实测 6905 件含六要素节点中 88 件处于该状态。

判据收敛在**单点** `nodefile.ccg_mark_present` / `nodefile.ccg_field_value`
（冒号可有可无），`mdcos._ccg_field`、`ccgc._has_ccg_line`、
`consolidate._has_ccg_line`、`tasks._field_line` 一律委托该单点。

本套的六组断言：
 ① 两形态都判齐（形态不改变「齐不齐」）
 ② 缺要素仍判不全（放宽的是标点，不是要求——判别力自证，两种形态各测）
 ③ 写入闸门与检索面**结论一致**（读真源 data/policy.json 复算，直接钉住分叉）
 ④ 取值面同源：无冒号的「值」= 标题后首个非空非标题行
 ⑤ 四个副本函数与单点结论一致（防未来再长出第五、第六套口径）
 ⑥ 写读闭环：无冒号节点经 upsert 后取得到新值（不出现「写进去读不出」）
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

from . import ccgc, consolidate, nodefile, tasks
from .mdcos import _ccg_field

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % label)
    else:
        FAIL += 1
        FAILS.append(label)
        print("  [FAIL] %s" % label)


MARKS = ("功能名", "生效条件", "子功能", "执行", "验证方式", "不适用条件")

# ① 带冒号形态（既有惯例形态）
COLON = "".join("# %s：值_%s\n" % (m, m) for m in MARKS)
# ① 不带冒号形态（policy 正则接受，标题行 + 换行接值）
NONCOLON = "".join("# %s\n值_%s\n" % (m, m) for m in MARKS)
# ① 混形态（一半带冒号一半不带）
MIXED = "".join(("# %s：值_%s\n" if i % 2 == 0 else "# %s\n值_%s\n") % (m, m)
                for i, m in enumerate(MARKS))


def _drop(body: str, mark: str) -> str:
    """删掉某要素的标题行（连带其值行）——用于②的判别力自证。"""
    out = []
    skip_next = False
    for ln in body.splitlines(True):
        if skip_next:
            skip_next = False
            continue
        if re.match(r"^#\s*%s\s*[:：]?\s*$" % re.escape(mark), ln.rstrip("\n")):
            skip_next = True
            continue
        if ln.startswith("# %s：" % mark) or ln.startswith("# %s:" % mark):
            continue
        out.append(ln)
    return "".join(out)


def _policy_required() -> list:
    """读**真源**策略文件的必需正则（相对本模块定位，不依赖 cwd）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "data", "policy.json")
    with io.open(path, encoding="utf-8") as fh:
        return [re.compile(p) for p in json.load(fh)["required"]]


def main() -> int:
    print("== ① 两形态都判齐 ==")
    for name, body in (("带冒号", COLON), ("无冒号", NONCOLON), ("混形态", MIXED)):
        comp = nodefile.ccg_completeness(body)
        ok(comp["complete"] and sorted(comp["required_present"]) == sorted(MARKS),
           "①%s：六要素判齐（present=%d/%d）" % (name, len(comp["required_present"]), len(MARKS)))
        ok(abs(comp["ratio"] - 1.0) < 1e-9, "①%s：ratio=1.0（%s）" % (name, comp["ratio"]))

    print("== ② 缺要素仍判不全（放宽的是标点，不是要求）==")
    for name, body in (("带冒号", COLON), ("无冒号", NONCOLON)):
        for mark in MARKS:
            broken = _drop(body, mark)
            comp = nodefile.ccg_completeness(broken)
            ok(not comp["complete"] and mark not in comp["required_present"],
               "②%s 缺「%s」→ 判不全" % (name, mark))
    ok(not nodefile.ccg_completeness("")["complete"], "②空正文 → 判不全")
    ok(not nodefile.ccg_completeness("# 生效条件\n只要这一条\n")["complete"],
       "②只声明一条 → 判不全（不冒充齐全）")

    print("== ③ 写入闸门与检索面结论一致（读真源 policy 复算）==")
    pats = _policy_required()
    for name, body in (("带冒号", COLON), ("无冒号", NONCOLON), ("混形态", MIXED),
                       ("空正文", ""), ("只一条", "# 生效条件：x\n")):
        gate = all(p.search(body) for p in pats)
        retr = nodefile.ccg_completeness(body)["complete"]
        ok(gate == retr, "③%s：闸门=%s 检索面=%s（必须相等）" % (name, gate, retr))
    for mark in MARKS:
        for name, body in (("带冒号", COLON), ("无冒号", NONCOLON)):
            broken = _drop(body, mark)
            gate = all(p.search(broken) for p in pats)
            retr = nodefile.ccg_completeness(broken)["complete"]
            ok(gate == retr and not retr,
               "③%s 缺「%s」：两侧同判不全" % (name, mark))
    # 边界形态：二级标题 / 缩进标题 / 无空格 —— 两侧必须同判（宽松方向也要一致）。
    # 注意按**该要素自身**的那条必需正则比对（拿「全六条」的结论比「单条」判据
    # 是错的口径——空正文与二级标题会因两侧同假而蒙对，暴露不出真差异）。
    for name, line in (("二级标题", "## 生效条件：x\n"),
                       ("缩进标题", "  # 生效条件：x\n"),
                       ("无空格", "#生效条件：x\n"),
                       ("制表符", "#\t生效条件：x\n")):
        pat = next(p for p in pats if "生效条件" in p.pattern)
        gate = bool(pat.search(line))
        present = nodefile.ccg_mark_present(line, "生效条件")
        ok(gate == present,
           "③%s（%r）：闸门=%s 判据=%s（必须相等）" % (name, line.strip(), gate, present))
    # 全形态 × 全要素的逐条一致性（比「整体 complete」更细，能定位到具体要素）
    for name, body in (("带冒号", COLON), ("无冒号", NONCOLON), ("混形态", MIXED)):
        for mark in MARKS:
            pat = next(p for p in pats if mark in p.pattern)
            ok(bool(pat.search(body)) == nodefile.ccg_mark_present(body, mark),
               "③%s 逐要素一致：「%s」" % (name, mark))

    print("== ④ 取值面：无冒号的值 = 标题后首个非空非标题行 ==")
    ok(nodefile.ccg_field_value(COLON, "功能名") == "值_功能名",
       "④带冒号：取行内值")
    ok(nodefile.ccg_field_value(NONCOLON, "功能名") == "值_功能名",
       "④无冒号：取下一行值")
    ok(nodefile.ccg_field_value("# 执行\n\n真实值行\n后文\n", "执行") == "真实值行",
       "④无冒号：跳过空行取首个非空行")
    ok(nodefile.ccg_field_value("# 功能名\n# 生效条件：x\n", "功能名") == "",
       "④无冒号且下一行又是标题：取空串而非吞掉下一个要素")
    ok(nodefile.ccg_field_value(COLON, "不存在的字段") is None,
       "④无该字段行 → None")

    print("== ⑤ 四个副本与单点结论一致（防再长出口径分叉）==")
    for name, body in (("带冒号", COLON), ("无冒号", NONCOLON)):
        for mark in ("功能名", "生效条件", "执行"):
            single = nodefile.ccg_mark_present(body, mark)
            ok(ccgc._has_ccg_line(body, mark) == single,
               "⑤ccgc._has_ccg_line(%s,%s) 与单点一致" % (name, mark))
            ok(consolidate._has_ccg_line(body, mark) == single,
               "⑤consolidate._has_ccg_line(%s,%s) 与单点一致" % (name, mark))
            ok(bool(_ccg_field(body, mark)) == single or not single,
               "⑤mdcos._ccg_field(%s,%s) 与单点一致" % (name, mark))
            ok(tasks._field_line(body, mark) == (nodefile.ccg_field_value(body, mark) or ""),
               "⑤tasks._field_line(%s,%s) 与单点同值" % (name, mark))

    print("== ⑥ 写读闭环：无冒号节点 upsert 后取得到新值 ==")
    for enc, upsert in (("ccgc", ccgc._upsert_ccg_line), ("consolidate", consolidate._upsert_ccg_line)):
        after = upsert(NONCOLON, "生效条件", "新条件")
        ok(_ccg_field(after, "生效条件") == "新条件",
           "⑥%s：无冒号节点 upsert 后 mdcos 读出「新条件」" % enc)
        ok(nodefile.ccg_field_value(after, "生效条件") == "新条件",
           "⑥%s：同一次写单点读出「新条件」" % enc)
        ok(nodefile.ccg_completeness(after)["complete"],
           "⑥%s：upsert 后仍判齐" % enc)
        try:
            upsert(NONCOLON, "生效条件", "多行\n注入")
            ok(False, "⑥%s：值含换行应被拒（N208）" % enc)
        except ValueError:
            ok(True, "⑥%s：值含换行被拒（N208 fail-closed）" % enc)

    print()
    print("ccg_form_parity: PASS=%d FAIL=%d" % (PASS, FAIL))
    if FAILS:
        print("FAILS: " + "; ".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
