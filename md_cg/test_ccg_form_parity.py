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

本套的七组断言：
 ① 两形态都判齐（形态不改变「齐不齐」）
 ② 缺要素仍判不全（放宽的是标点，不是要求——判别力自证，两种形态各测）
 ③ 写入闸门与检索面**结论一致**（读真源 data/policy.json 复算，直接钉住分叉）
 ④ 取值面同源：无冒号的「值」= 标题后首个非空非标题行
 ⑤ 四个副本函数与单点结论一致（防未来再长出第五、第六套口径）
 ⑥ 写读闭环：无冒号节点经 upsert 后取得到新值（不出现「写进去读不出」）
 ⑦ 「不适用条件」两函数（`has_non_applicable` / `positive_body`）× 两形态同权：
   无冒号形态同样算「已声明」（旧码只认冒号写法），且 positive_body 连**值行**
   一并剥净（旧码只剥标题行 ⇒ 同一条正文写不写冒号会给出两种召回面）；
   并含**红基线自证**——`git show HEAD:md_cg/nodefile.py` 物化后跑同一批断言，
   HEAD 版对无冒号形态必须失手（否则本节断言空转；本改动入库后该腿 SKIP）。
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import types

from . import ccgc, consistency, consolidate, nodefile, tasks
from .mdcg import MdCG
from .mdcos import _ccg_field

PASS = FAIL = SKIPPED = 0
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


def skip(label, why):
    """不适用/前提缺失的腿：只报不判——不计入 FAIL（如红基线随 HEAD 前移而不可复现）。"""
    global SKIPPED
    SKIPPED += 1
    print("  [SKIP] %s（%s）" % (label, why))


def _load_head_nodefile():
    """物化 HEAD 版 `md_cg/nodefile.py` 并 exec 成模块（红基线自证用）。

    nodefile 只依赖 stdlib、顶层无副作用（无包内相对导入、无模块级 I/O），故
    HEAD 字节可独立 exec 进一个空模块命名空间。取不到（无 git / 无提交 / 路径
    不在仓内）时返回 (None, 原因)——由调用方 SKIP，不静默当成功。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run(["git", "-c", "core.quotepath=false", "show",
                        "HEAD:md_cg/nodefile.py"],
                       cwd=root, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None, ("git show 失败 rc=%s %s"
                      % (r.returncode, (r.stderr or "").strip()[:200]))
    mod = types.ModuleType("_head_nodefile_legacy")
    mod.__file__ = os.path.join(root, "md_cg", "nodefile.py")
    exec(compile(r.stdout, "HEAD:md_cg/nodefile.py", "exec"), mod.__dict__)
    return mod, ""


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

    print("== ⑦ 「不适用条件」两函数 × 两形态同权（A3：N238 同族残面收口）==")
    # 被测：`has_non_applicable`（判「有没有声明」）与 `positive_body`（剥声明段后再作召回键）。
    # 判据全部在单点（`ccg_mark_present` / `_ccg_heading_rest` / `ccg_field_value`，①-⑤ 已验收）
    # ——两函数都不得自带一套「冒号可有可无」的本地口径。
    NEG = "不适用条件"
    COLON_NEG = "# 功能名：p\n# 不适用条件：ZXQ7\n正文第一行\n"
    BARE_NEG = "# 功能名：p\n# 不适用条件\nZXQ7\n正文第一行\n"
    for name, body in (("带冒号", COLON), ("无冒号", NONCOLON), ("混形态", MIXED)):
        ok(nodefile.has_non_applicable(body) == nodefile.ccg_mark_present(body, NEG),
           "⑦%s：has_non_applicable 与单点同判（%s）"
           % (name, nodefile.has_non_applicable(body)))
    ok(nodefile.has_non_applicable(BARE_NEG) is True,
       "⑦无冒号形态：通体判 True（旧码 False——真声明被判成没声明）")
    ok(nodefile.has_non_applicable(COLON_NEG) is True
       and nodefile.has_non_applicable("") is False
       and nodefile.has_non_applicable("正文提到不适用条件，但不是 CCG 行\n") is False,
       "⑦带冒号 True / 空正文 False / 行内提及 False（放宽的是标点，不是判据）")

    pb_bare = nodefile.positive_body(BARE_NEG)
    pb_colon = nodefile.positive_body(COLON_NEG)
    ok(pb_bare == pb_colon,
       "⑦positive_body 两形态剥除结论一致（无冒号得到 %r）" % pb_bare)
    ok("ZXQ7" not in pb_bare and "正文第一行" in pb_bare,
       "⑦无冒号形态：值行一并剥净、正文保留（旧码残留值行 ZXQ7）")
    ok(nodefile.positive_body("# 不适用条件\n# 执行：x\n后文\n") == "# 执行：x\n后文\n",
       "⑦裸标题后紧跟另一标题：不吞下一要素（取值口径同 ccg_field_value）")
    plain_line = "正文提到不适用条件这个词，但不是 CCG 行。\n"
    ok(nodefile.positive_body(plain_line) == plain_line,
       "⑦普通句子不误伤（只剥 CCG 行）")
    only_neg = "# 不适用条件\nZXQ7\n正文第一行\n"
    ok(consistency._body_text(only_neg) == nodefile.positive_body(only_neg),
       "⑦只声明该要素时：positive_body 与 consistency._body_text 同口径（同一剥除算法单点）")
    # 消费点用中文反例词面（不做大小写归一——`_like` 只小写 body/tags，
    # 拿大写词面测会因边被消而空转，测不出「值行残留 ⇒ 反例被召回」）
    BARE_NEG_CN = "# 功能名：p\n# 不适用条件\n不得把甲当作乙\n正文第一行\n"
    ok(MdCG._like(BARE_NEG_CN, {}, ["不得把甲当作乙"]) is False,
       "⑦消费点 _like：无冒号形态的反例词不作召回键（旧码残留值行 ⇒ 会被召回）")
    ok(MdCG._like(BARE_NEG_CN, {}, ["正文第一行"]) is True,
       "⑦消费点 _like：正条件行照常命中（判别力未削弱）")

    print("-- ⑦红基线自证：HEAD 版 nodefile 对无冒号形态必须失手 --")
    head, why = _load_head_nodefile()
    if head is None:
        skip("⑦红基线自证", "取不到 HEAD 版：%s" % why)
    else:
        h_present = head.has_non_applicable(BARE_NEG)
        h_leak = "ZXQ7" in head.positive_body(BARE_NEG)
        if h_present is True and not h_leak:
            skip("⑦红基线自证",
                 "HEAD 版已含修复（本改动已入库）——红基线只在其提交前可复现")
        else:
            ok(h_present is False and h_leak,
               "⑦红基线可复现：HEAD 版判 has_non_applicable=%s、positive_body 残留值行=%s"
               % (h_present, h_leak))

    print()
    print("ccg_form_parity: PASS=%d FAIL=%d SKIP=%d" % (PASS, FAIL, SKIPPED))
    if FAILS:
        print("FAILS: " + "; ".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
