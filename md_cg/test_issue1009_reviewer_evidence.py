# -*- coding: utf-8 -*-
"""复核单元的代码化证据判定（issue #1009 第 5 项 · 2026-11-22 使用者裁定）。

裁定：「算，但只算带明确证据的。依赖人去复核是不可能去做到的。只能是确定性规则，
和代码化的结果。」

本文件只测**判定函数本身**（md_cg/review_evidence.verify_claims，纯函数 + 临时台账）；
写入路径的集成面（直写被拒 / 台账证据放行 / 自证不放行）由
md_cg/test_issue709_review_chain_enforce.py 的 E1–E4 覆盖。

运行：python -X utf8 -m md_cg.test_issue1009_reviewer_evidence
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import review_evidence as re_mod  # noqa: E402

_OK = 0
_BAD = []


def ok(cond, name, extra=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s %s" % (name, extra))
    else:
        _BAD.append(name)
        print("  FAIL %s %s" % (name, extra))


def _write_ledger(path, recs):
    with open(path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    print("=== issue #1009 第 5 项：复核单元的代码化证据 ===")
    now = time.time()
    d = tempfile.mkdtemp()
    ledger = os.path.join(d, "decisions.jsonl")

    # V1 无台账：全部拒绝
    r = re_mod.verify_claims(["反思单元", "验证单元"], ledger_path=ledger, actor="writer", now=now)
    ok(r["accepted"] == [] and len(r["rejected"]) == 2, "V1 无台账 ⇒ 声明全拒")

    # V2 另一 actor 的红队 pass 记录 ⇒ reflect 有证据、verify 无（没 verify_hash）
    _write_ledger(ledger, [{"t": now - 60, "actor": "codebuddy", "decision": "accept",
                            "redteam_verdict": "pass", "issues": [], "record_hash": "h1",
                            "pid": "p1", "record_node_id": "rev_p1_r1"}])
    r = re_mod.verify_claims(["reflect", "verify"], ledger_path=ledger, actor="writer", now=now)
    ok(r["accepted"] == ["reflect"], "V2 红队 pass ⇒ 只认 reflect", str(r["accepted"]))
    ok(any(x["unit"] == "verify" for x in r["rejected"]), "V3 verify 因缺 verify_hash 被拒")
    ok("verify_hash" in r["rejected"][0]["why"], "V4 拒绝理由指名缺 verify_hash")

    # V5 同一记录补 verify_hash ⇒ verify 也成立
    _write_ledger(ledger, [{"t": now - 60, "actor": "codebuddy", "decision": "accept",
                            "redteam_verdict": "pass", "issues": [], "record_hash": "h1",
                            "verify_hash": "vh1", "pid": "p1"}])
    r = re_mod.verify_claims(["reflect", "verify"], ledger_path=ledger, actor="writer", now=now)
    ok(sorted(r["accepted"]) == ["reflect", "verify"], "V5 带 verify_hash ⇒ 两个单元都成立")
    ok(r["evidence"]["verify"]["source"] == "ledger"
       and r["evidence"]["verify"]["record_hash"] == "h1", "V6 记录来源与指纹入证据体")

    # V7 自证：记录 actor 就是写入者 ⇒ 不算
    r = re_mod.verify_claims(["reflect"], ledger_path=ledger, actor="codebuddy", now=now)
    ok(r["accepted"] == [], "V7 同 actor 的记录不算证据（自证）")

    # V8 超窗口 ⇒ 不算
    r = re_mod.verify_claims(["reflect"], ledger_path=ledger, actor="writer",
                             now=now + 8 * 86400)
    ok(r["accepted"] == [], "V8 超 7 天窗口 ⇒ 不算证据")

    # V9 缺 record_hash ⇒ 不可复核，不算
    _write_ledger(ledger, [{"t": now - 60, "actor": "codebuddy", "decision": "accept",
                            "redteam_verdict": "pass", "issues": []}])
    r = re_mod.verify_claims(["reflect"], ledger_path=ledger, actor="writer", now=now)
    ok(r["accepted"] == [], "V9 缺 record_hash ⇒ 不算证据")

    # V10 human 永远不认（无证据源），且拒绝理由说清楚
    _write_ledger(ledger, [{"t": now - 60, "actor": "codebuddy", "decision": "accept",
                            "redteam_verdict": "pass", "issues": [], "record_hash": "h1",
                            "verify_hash": "vh"}])
    r = re_mod.verify_claims(["human", "reflect", "verify"], ledger_path=ledger,
                             actor="writer", now=now)
    ok("human" not in r["accepted"], "V10 human 不出现在 accepted")
    hw = [x["why"] for x in r["rejected"] if x["unit"] == "human"]
    ok(bool(hw) and "无代码化证据源" in hw[0], "V11 human 的拒绝理由指明无证据源")

    # V12 别名归一 + 未知单元拒绝
    ok(re_mod.norm_unit("反思单元") == "reflect"
       and re_mod.norm_unit("验证者") == "verify"
       and re_mod.norm_unit("human_review") == "human"
       and re_mod.norm_unit("随便什么") is None, "V12 别名归一 / 未知返回 None")
    r = re_mod.verify_claims(["玄学单元"], ledger_path=ledger, actor="writer", now=now)
    ok(r["accepted"] == [] and "未知复核单元" in r["rejected"][0]["why"],
       "V13 未知单元按声明无效拒绝")

    # V14 代码授权：时效内 + 绑目标 ⇒ 接受；过期 / 目标不符 ⇒ 拒
    grant = {"units": ("reflect", "verify"), "pid": "p1", "target": "node_x", "t": now - 5}
    r = re_mod.verify_claims(["reflect", "verify"], node_id="node_x", actor="w",
                             grant=grant, now=now)
    ok(sorted(r["accepted"]) == ["reflect", "verify"] and r["grant_used"],
       "V14 代码授权（时效内、目标相符）⇒ 接受")
    ok(r["evidence"]["reflect"]["source"] == "code_grant", "V15 证据来源标为 code_grant")
    r = re_mod.verify_claims(["reflect"], node_id="node_x", actor="w",
                             grant=dict(grant, t=now - 10 ** 5), now=now)
    ok(r["accepted"] == [], "V16 授权过期 ⇒ 不再算证据")
    r = re_mod.verify_claims(["reflect"], node_id="node_y", actor="w", grant=grant, now=now)
    ok(r["accepted"] == [], "V17 授权绑定的目标不符 ⇒ 不算证据")

    # V18 空声明 / None 不炸
    r = re_mod.verify_claims([], ledger_path=ledger, actor="w", now=now)
    ok(r == {"accepted": [], "rejected": [], "evidence": {}, "grant_used": False},
       "V18 空声明返回空结果")

    print()
    print("复核证据判定：%d 通过，%d 失败" % (_OK, len(_BAD)))
    if _BAD:
        print("失败项：" + " / ".join(_BAD))
    return 1 if _BAD else 0


if __name__ == "__main__":
    sys.exit(main())
