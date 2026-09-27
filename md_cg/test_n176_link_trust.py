# -*- coding: utf-8 -*-
"""N176 守卫：无令牌签章（self-reported）不得经 link 落 knowledge 层。

病灶（N176，high，2026-09-27）：attest 无 verifier_token 时验证方身份是
**纯自报字符串**，AttestResult.verifier_identity="self-reported" 只是如实
标注——但 link（:709-798）/link_pending（:984-1000）与全仓对该字段**零消费**，
docstring「下游策略可据此拒绝」是未兑现空防线。record 角色（can_write=True、
ops_allow 含 ccg，md_cg/tokens.py:126-141）单 agent 即可：
    compile → attest(verdict=ACCEPT, verifier=任意编造名, 无令牌) → link(apply=true)
编造名与 compiled_by 不同源（E041 只拦同源变体），未经验证的内容带「已签章」
状态直写 knowledge 层（_cg._write_node）并进入检索传播，绕过 review 编外复核
与裁定 A（LLM 不得自己验证自己）。

修复契约（N176 最小修，兑现下游消费）：
  link(apply=true) 对 verifier_identity != "token"（含历史 pending 缺字段）
  一律 E052 拒绝写入；dry-run 不拦（附 E052 预告 warning）；
  有令牌路径与同源 E041 不动；link_pending 经委托同闸，拒绝后 pending 保留
  （暂存非存档，待令牌验证方复核）。全量验证方信任协议留档不扩。

运行：python -m md_cg.test_n176_link_trust
环境纪律：全程哑令牌（临时 MDCG_TOKEN_FILE）+ 临时记忆根，不触真实令牌库。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import ccgc, nodefile, tokens
from md_cg.mdcos import MdCGOS
from md_cg.readcache import direct_read

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + detail)


DIALOG = ("文件摄取分派：按扩展名把文件路由到对应摄取器"
          "。该方法使用扩展名映射表进行路由"
          "。此功能在本地文件系统中生效"
          "。仅对本地可读文件生效"
          "。2026-09-16"
          "。通过回放测试验证"
          "。二进制文件不适用")

SLOTS = {
    "observation_position": {"value": "此功能在本地文件系统中生效"},
    "observation_tool": {"value": "该方法使用扩展名映射表进行路由"},
    "time_window": {"value": [0.0, 9999999999.0]},
    "existence_constraint": {"value": "仅对本地可读文件生效"},
}

MARKS = {
    "功能名": {"value": "文件摄取分派：按扩展名把文件路由到对应摄取器"},
    "子功能": {"value": "按扩展名把文件路由到对应摄取器"},
    "执行": {"value": "使用扩展名映射表进行路由"},
    "验证方式": {"value": "回放测试", "basis": "test"},
    "不适用条件": {"value": "二进制文件不适用"},
}

MARK_LINE = "功能名：文件摄取分派：按扩展名把文件路由到对应摄取器"


def _seed(root, node):
    cg = MdCGOS(root)
    cg.add(node, "# 功能名：待编译节点\n\n占位正文。\n", layer="knowledge")
    cg.flush()
    cg.rebuild_index()
    return cg


def _disk(cg, node):
    entry = (cg.index.get("nodes") or {}).get(node)
    return direct_read(cg, entry)


def main():
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="mdcg_n176_")
    tok_env = os.path.join(tmp, "tokens.json")
    old_tf = os.environ.get(tokens.TOKEN_FILE_ENV)
    os.environ[tokens.TOKEN_FILE_ENV] = tok_env
    try:
        # ---------- X1 攻击前提：record 权限面（tokens.py:126-141） ----------
        print("== X1 record 角色权限面（哑令牌临时库）==")
        rec = tokens.issue("record", actor="worker-a", path=tok_env)
        check("X1a record 令牌可签发（哑临时令牌文件）", bool(rec.get("token")))
        spec = tokens.ROLE_SPECS.get("record") or {}
        check("X1b record can_write=True", spec.get("can_write") is True)
        check("X1c record ops_allow 含 ccg", "ccg" in (spec.get("ops_allow") or []))
        pr = tokens.verify_token(rec["token"])
        check("X1d 令牌主体=worker-a", getattr(pr, "actor", "") == "worker-a")

        root = os.path.join(tmp, "root")
        cg = _seed(root, "tgt")

        # ---------- X2 攻击复现：编造名无令牌 → link(apply=true) 必须拒 ----------
        print("== X2 攻击复现：编造名无令牌签章 → link(apply=true) 必须拒 ==")
        r = ccgc.compile_dialog(DIALOG, "tgt", "worker-a",
                                slots=SLOTS, marks=MARKS, cg=cg)
        check("X2a compile success（攻击面成立）", r.success,
              "errors=" + "; ".join(r.errors[:2]))
        at = ccgc.attest("tgt", ccgc.ACCEPT, "hive:reflect:fake-unit", "worker-a",
                         evidence="编外复核（伪造）", cg=cg)
        check("X2b 编造名过 attest（E041 只拦同源，病灶如实留证）",
              at.ok and at.verifier_identity == "self-reported",
              "ok=%s id=%s err=%s" % (at.ok, at.verifier_identity, at.error[:60]))
        l = ccgc.link(r, at, cg=cg, apply=True)
        check("X2c link(apply=true) 拒绝且 written==0（E052）",
              (not l.ok) and l.written == 0
              and any(str(e).startswith("E052") for e in l.errors),
              "ok=%s written=%s errors=%s" % (l.ok, l.written, l.errors[:2]))
        _fm1, c1 = _disk(cg, "tgt")
        check("X2d knowledge 层未被写入（六要素仍不全）",
              not nodefile.ccg_completeness(c1)["complete"],
              "complete=" + str(nodefile.ccg_completeness(c1)))
        check("X2e 未进入检索传播（盘上正文无六行）", MARK_LINE not in (c1 or ""))

        # ---------- X3 link_pending 同闸（委托面，:984-1000） ----------
        print("== X3 link_pending 同闸 ==")
        sv = ccgc.save_pending(cg, r, at)
        lp = ccgc.link_pending(cg, "tgt", apply=True, actor="worker-a")
        check("X3a link_pending(apply=true) 拒绝（E052）",
              (not lp.ok) and lp.written == 0
              and any(str(e).startswith("E052") for e in lp.errors),
              "ok=%s errors=%s" % (lp.ok, lp.errors[:2]))
        check("X3b pending 保留（暂存非存档，可待令牌复核）",
              os.path.isfile(sv.get("path") or ""))

        # ---------- X4 MCP 工具面同闸（compile→attest→link 全程） ----------
        print("== X4 MCP 工具面同闸 ==")
        cg2 = _seed(root, "tgt2")
        from md_cg import mcp_server as mcp
        c2 = mcp._ccg_call(cg2, {"ccg": {"action": "compile", "node_id": "tgt2",
                                         "actor": "worker-a", "dialog": DIALOG,
                                         "marks": MARKS, "slots": SLOTS}})
        check("X4a MCP compile 成功并落 pending",
              c2.get("ok") and (c2.get("pending") or {}).get("ok"))
        c3 = mcp._ccg_call(cg2, {"ccg": {"action": "attest", "node_id": "tgt2",
                                         "verdict": "ACCEPT",
                                         "verifier": "hive:reflect:fake-unit2",
                                         "compiled_by": "worker-a",
                                         "evidence": "伪造复核"}})
        check("X4b MCP attest 自报签章通过（病灶如实留证）",
              c3.get("ok") and (c3.get("attest") or {}).get("verifier_identity")
              == "self-reported",
              json.dumps(c3.get("attest") or {}, ensure_ascii=False)[:120])
        c4 = mcp._ccg_call(cg2, {"ccg": {"action": "link", "node_id": "tgt2",
                                         "apply": True}})
        check("X4c MCP link(apply=true) 拒绝（E052）",
              (not c4.get("ok")) and "E052" in json.dumps(c4, ensure_ascii=False),
              json.dumps(c4, ensure_ascii=False)[:160])

        # ---------- X5 对照面：有令牌路径不误伤 ----------
        print("== X5 对照面：有令牌签章正常落库 ==")
        tk = tokens.issue("verify", actor="external-reviewer", path=tok_env)["token"]
        at2 = ccgc.attest("tgt", ccgc.ACCEPT, "随意自报字符串会被覆盖", "worker-a",
                          evidence="真实编外验证方", cg=cg, verifier_token=tk)
        check("X5a 令牌签章 identity=token 且覆盖自报",
              at2.ok and at2.verifier == "external-reviewer"
              and at2.verifier_identity == "token",
              "ok=%s id=%s" % (at2.ok, at2.verifier_identity))
        l2 = ccgc.link(r, at2, cg=cg, apply=True)
        check("X5b 有令牌签章 link 落库六行", l2.ok and l2.written == 6,
              "ok=%s written=%s errors=%s" % (l2.ok, l2.written, l2.errors[:2]))
        _fm2, c2d = _disk(cg, "tgt")
        check("X5c 六要素齐备（正常通路不受影响）",
              nodefile.ccg_completeness(c2d)["complete"])

        # ---------- X6 对照面：同源 E041 不动 ----------
        print("== X6 对照面：同源 E041 不动 ==")
        at3 = ccgc.attest("tgt", ccgc.ACCEPT, "Worker-A", "worker-a", cg=cg)
        check("X6a 同源变体仍 E041", (not at3.ok) and at3.error.startswith("E041"),
              "err=" + at3.error[:60])

        # ---------- X7 dry-run 不拦（附 E052 预告） ----------
        print("== X7 dry-run 不拦 ==")
        cg3 = _seed(root, "tgt3")
        r3 = ccgc.compile_dialog(DIALOG, "tgt3", "worker-a",
                                 slots=SLOTS, marks=MARKS, cg=cg3)
        at4 = ccgc.attest("tgt3", ccgc.ACCEPT, "hive:reflect:fake-unit3", "worker-a",
                          cg=cg3)
        ld = ccgc.link(r3, at4, cg=cg3, apply=False)
        check("X7a dry-run ok=True 且附 E052 预告 warning",
              ld.ok and ld.dry_run and ld.written == 0
              and any("E052" in w for w in ld.warnings),
              "ok=%s warnings=%s" % (ld.ok, ld.warnings[:2]))
        _fm3, c3d = _disk(cg3, "tgt3")
        check("X7b dry-run 确未写入", MARK_LINE not in (c3d or ""))
    finally:
        if old_tf is None:
            os.environ.pop(tokens.TOKEN_FILE_ENV, None)
        else:
            os.environ[tokens.TOKEN_FILE_ENV] = old_tf
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print("FAILED: %d 项 → %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("ALL OK: %d 项（N176 无令牌签章不落 knowledge 层守卫全绿）" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
