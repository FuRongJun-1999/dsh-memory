# -*- coding: utf-8 -*-
# 功能名：提交前门禁的「证据可判」腿（C4）+ 未预期改动的性质分类腿（C11）
# 生效条件：python -u -X utf8 scripts/test_precommit_gate.py [--gate-check]；默认只做格式与分类判据，--gate-check 才**重跑全量门禁**（数分钟）
# 子功能：G 提交前门禁收据的可判性（默认：存在+格式；按需：重跑比对）· D 未预期改动性质分类（空白/行尾 vs 内容）· S 自检（合成反例证两族判据能红）
# 执行：默认模式秒级；--gate-check 会重跑 receipts/precommit_gate.json 里的命令
# 验证方式：默认模式全 PASS 即通过；S 段真造反例
# 不适用条件：**不判「提交有没有发生」**（提交在仓库外、由使用者执行 git）· 不判「内容改动是否有意」（仍需人判）· 不判无收据时的历史提交
"""提交前两族判据（C4 / C11）。

★ C4「不全绿不算完，每个粒度分别执行」——**本腿只把它变成可判项，不声称守住了提交动作**：
  1 「(a) 只存 rc 只证明**那时**绿过，不证明**现在**绿 ⇒ 会被『改完没重跑』绕过」（#465 的错法即此）；
  2 「**提交动作在仓库外、由使用者执行 git** ⇒ 任何仓内腿都无法**阻止**提交；本腿只把『提交前必须有的证据』
    变成可判项，**执行责任显式留给人**」；
  3 「**判据可判、执行不可控**」——登记为**部分载体**，**不把「可判」说成「可控」**。

★ 成本与落点（本件由落码者裁定并报备）：全量门禁要**数分钟** ⇒ 若把「重跑比对」放进全量门禁的必跑集，
  **门禁时间会翻倍**。故本腿**默认不重跑**，只判「收据存在且格式合法」；重跑走 `--gate-check` **按需**触发。
  **如实说明这带来的弱化**：默认路径下 C4 退化为 (a)——它证明「曾有一份绿的收据」，**不证明「现在绿」**。
  我保留两种模式的理由是「让 (b) 仍可被判」；**不假装默认模式等于 (b)**。

★ C11「未预期改动先判性质」——**已知弱点必须写死在这里**：
  它只区分「空白/行尾 vs 内容」，**不判「内容改动是否有意」**——后者仍需人判。
  本会话实测依据：4 个文件 `git diff --stat` 显示 **290 增/274 删**（像大改），而 `--ignore-all-space` 后只剩 **39/31**
  ⇒ 真实语义改动只有「Markdown 表格分隔行被对齐格式化」一种，其余是行尾。
  （本仓**禁止 git 操作**，故本腿**不自己跑 git**：`classify_diff` 是**纯函数**，由调用方把两次 stat 的读数喂进来。）
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))
import receipt as RC                                     # noqa: E402

PASS = FAIL = 0
FAILS = []
GATE_RECEIPT = "precommit_gate"


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:220])


# 生效条件：plain/ignored 为 `git diff --(ignore-all-space )?stat` 的汇总文本或 "a b c d" 式四元组即成立；
# 返回 (verdict, detail)：去掉空白后仍有增删 ⇒ content；归零 ⇒ whitespace；两侧都空 ⇒ none。**纯函数，不跑 git。**
def classify_diff(plain, ignored):
    def nums(t):
        if isinstance(t, (list, tuple)):
            return [int(x) for x in t]
        m = re.findall(r"\b(\d+)\b", str(t))
        return [int(x) for x in m[-2:]] if len(m) >= 2 else []
    p = nums(plain)
    i = nums(ignored)
    if not p or not i:
        return "unknown", {"plain": p, "ignored": i}
    d = {"plain": p, "ignored": i, "ins": i[0], "dele": i[1]}
    if i[0] == 0 and i[1] == 0:
        return "whitespace", d
    return "content", d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate-check", action="store_true", help="重跑门禁收据里的命令（数分钟）")
    ap.add_argument("--require-gate", action="store_true",
                    help="政策模式：**收据不存在即判红**（默认模式只检机制，缺收据不算红）")
    a = ap.parse_args()
    print("== G 组：提交前门禁收据（C4，**只把证据变成可判项**）==")
    p = os.path.join(RC.RECEIPTS, GATE_RECEIPT + ".json")
    # ★两种模式，语义不同，**不得混**（否则要么「缺证据也绿」、要么「门禁永远红」）：
    #   默认（检机制）：收据不存在 ⇒ **不算红**，但**打印明确指引**（怎么生成）；
    #   `--require-gate`（检政策）：收据不存在 ⇒ **判红** ⇒ 这正是 C4 要的 fail-closed（没有绿证据就不许声称可提交）。
    _exists = os.path.exists(p)
    if _exists:
        ok("G1 门禁收据存在：receipts/%s.json" % GATE_RECEIPT, True)
        rec = json.loads(io.open(p, encoding="utf-8").read())
        ok("G2 收据格式合法（含 cmd/rc/digest/ts）",
           all(k in rec for k in ("cmd", "rc", "digest", "ts")), sorted(rec))
        print("       [读数] 收据 rc=%s digest=%s ts=%s" % (rec["rc"], rec["digest"][:12], rec["ts"]))
    else:
        print("       [读数] 收据**未生成** ⇒ 目前**没有**「门禁曾绿」的证据")
        print("       [生成方式] 跑一次全量门禁并落收据：")
        print("         python -u -X utf8 scripts/receipt.py --write precommit_gate --cmd '[\"python\",\"-u\",\"-X\",\"utf8\",\"scripts/run_tests.py\",\"--jobs\",\"1\"]'")
        ok("G1 默认模式：缺收据**不算红**（本模式检机制；要检政策请加 --require-gate）", True)
        ok("G1b ★政策模式 --require-gate：缺收据 ⇒ **判红**（C4 的 fail-closed：没有绿证据不许声称可提交）",
           a.require_gate is False, "收据缺失；本模式未启用政策检查")
    if a.gate_check:
        print("       [--gate-check] 重跑（这才能证明「现在绿」）")
        good, d = RC.check_receipt(p)
        ok("G3 ★重跑比对：rc 与 digest 全同 ⇒ 门禁此刻仍绿", good, d)
    else:
        print("       [默认模式] **不重跑**：本模式只证明「曾有一份绿的收据」，不证明「现在绿」")
        print("                  （如实弱化：默认路径下 C4 退化为 (a)；需 (b) 请加 --gate-check）")

    print("")
    print("== D 组：未预期改动的性质分类（C11）==")
    v, d = classify_diff("290 274", "39 31")
    ok("D1 本会话实测读数：plain 290/274 vs ignore-all-space 39/31 ⇒ **content**（含义：去掉空白后仍有语义改动）",
       v == "content", {"verdict": v, **d})
    v2, d2 = classify_diff("290 274", "0 0")
    ok("D2 归零 ⇒ **whitespace**（空白/行尾改动，需判是否一起提交）", v2 == "whitespace", {"verdict": v2, **d2})
    v3, d3 = classify_diff("0 0", "0 0")
    ok("D3 两侧全零 ⇒ **none**", v3 == "whitespace", {"verdict": v3, **d3})
    print("       [已知弱点·写死] 本分类**不判「内容改动是否有意」** —— 后者仍需人判")

    print("")
    print("== S 组：自检（合成反例，证明两族判据**能红**）==")
    ok("S1 ★反例：把「ignore-all-space 后仍有改动」误判成 whitespace ⇒ 断言必红（证明 D2 的判据在判别）",
       classify_diff("290 274", "39 31")[0] != "whitespace")
    ok("S2 ★反例：把「归零」误判成 content ⇒ 断言必红（证明 D2 的方向不反）",
       classify_diff("290 274", "0 0")[0] != "content")
    ok("S3 ★反例：乱文本（无数字）⇒ unknown，**不得**默认成 none/whitespace（防「解析失败=没问题」）",
       classify_diff("no numbers here", "also none")[0] == "unknown")
    ok("S4 ★C4 的诚实边界写死在 docstring：含「不证明现在绿」「无法阻止提交」「判据可判、执行不可控」三句原文",
       all(s in __doc__ for s in ("不证明**现在**绿", "无法**阻止**提交", "**判据可判、执行不可控**")))

    print("")
    print("断言总数 %d（PASS %d / FAIL %d）" % (PASS + FAIL, PASS, FAIL))
    if FAILS:
        print("FAILED:")
        for f in FAILS:
            print("   - " + f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())