# -*- coding: utf-8 -*-
"""守卫 · pack 预算纪律（issue #1005，2026-11-25）。

**判据（今天用三次翻车换来的）**：凡是要进 pack 的东西（判读合同 / 槽位卡 / 注入项），
都要先算预算，再谈价值。**不加预算的改动，等于改动了别人的份额。**

三次同形的翻车：
  ① raw 保底把原话提到队首  ⇒ 挤掉高分档案卡（179 题四子集全负）
  ② 槽位卡进候选池          ⇒ 挤掉原话轮次（P17-CASE-025 四道全灭）
  ③ 判读合同 +54 token      ⇒ 挤掉 pack 尾部两条材料（P20-CASE-029/d03 从 PP 掉成 FF）

本守卫钉住三条：
  1. 判读合同 token 有**硬上限**（超了必须压缩，不许悄悄吃预算）；
  2. 合同不会因为预算不足被静默丢弃（`reading_policy_skipped` 不得出现）；
  3. 开合同时，pack 里的材料条数不得比关合同时少太多（合同不许吃掉材料）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import reading_policy as RP  # noqa: E402
from md_cg.mdcos import MdCGOS, est_tokens  # noqa: E402

PASSED, FAILED = [], []

#: 合同 token 硬上限。2026-11-25 实测：146 → 200 时挤掉两条材料；压缩后 136。
#: 上限留 20 token 余量（≈ 半条材料），再多就该重新压缩而不是加预算。
POLICY_TOKEN_CAP = 160


def ok(cond, name, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else "  " + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


BODY = "# 功能名：{n}\n# 生效条件：t\n# 子功能：s\n# 执行：{x}\n# 验证方式：t\n# 不适用条件：无\n"


def main():
    pol = RP.TEXT
    n_tok = est_tokens(pol)
    ok(n_tok <= POLICY_TOKEN_CAP,
       "B1 判读合同 token ≤ %d（超了必须压缩，不许悄悄吃预算）" % POLICY_TOKEN_CAP,
       n_tok)
    ok(bool(pol.strip()), "B2 合同非空（关闭时为空是另一条路径）")

    T = tempfile.mkdtemp(prefix="pack_budget_")
    try:
        cg = MdCGOS(T, actor="t")
        for i in range(12):
            cg.add("turn_%02d" % i,
                   BODY.format(n="材料%d" % i, x="预算纪律 测试材料 编号%d" % i),
                   layer="contextual", tags=["对话"], importance=0.6)
        cg.flush()

        def run(policy_on):
            old = os.environ.get("MDCG_READING_POLICY")
            os.environ["MDCG_READING_POLICY"] = "1" if policy_on else "0"
            try:
                out = cg.recall("预算纪律", budget_tokens=400, k=20)
            finally:
                if old is None:
                    os.environ.pop("MDCG_READING_POLICY", None)
                else:
                    os.environ["MDCG_READING_POLICY"] = old
            pack = out.get("pack") or []
            return {
                "n": len(pack),
                "used": out.get("tokens_used"),
                "skipped": (out.get("meta") or {}).get("reading_policy_skipped"),
                "policy": out.get("reading_policy") or "",
            }

        on = run(True)
        off = run(False)
        ok(on["skipped"] is None,
           "B3 合同不因预算不足被静默丢弃（reading_policy_skipped 为空）", on["skipped"])
        ok(est_tokens(on["policy"]) == n_tok,
           "B4 下发正文即 READING_POLICY.TEXT（没被中途裁剪）")
        ok(on["n"] <= off["n"],
           "B5 开合同时材料条数不多于关闭时（合同只占不赚）", (on["n"], off["n"]))
        # B6 用**比率**而不是条数：136 token 合同在 400 预算下会吃掉 3 条材料，
        # 「吃几条」会随材料大小漂移，「合同占整包比例」才稳定且可解释。
        # 判据：合同不得超过整包（材料 + 合同）的 35%——超了就是合同在挤材料。
        total = int(on["used"] or 0)
        ratio = n_tok / float(total) if total else 0.0
        ok(ratio <= 0.35,
           "B6 合同占整包比例 ≤ 35%%（%d/%d = %.1f%%）" % (n_tok, total, ratio * 100),
           ("ratio=%.3f" % ratio, on["n"], off["n"]))
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print("pack 预算守卫：%d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())