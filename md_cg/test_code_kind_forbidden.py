# -*- coding: utf-8 -*-
"""code 类型不得绕过 forbidden 禁表（2026-10-19 外部实测，dsh-bounty #1103）。

运行：python -X utf8 -m md_cg.test_code_kind_forbidden

病态（修前实测）：
  `_rule_check` 的契约写着「forbidden 是内容政策，对所有 content_kind 恒生效」，
  `data/policy.json` 的 `_note` 也这么写；但全仓只有 `_verify_text` /
  `_verify_work_wip` 两个验证器调用它，`_verify_code` 只做 `ast.parse`。
  于是「代码里夹带凭据」判 ACCEPT 并明文落盘（`knowledge/orphan/*.md`），
  且无令牌 guest 经 `cg(op=read)` 可读回。README 恰恰推荐用 code 立刻落盘。

本守卫钉住四件事（缺一即红）：
  K1 行为面：code 正文含 sk-/AKIA/PEM 三种禁表形态 ⇒ 必须 REJECT（修前三条全 ACCEPT）
  K2 不误伤：干净代码 ⇒ 必须 ACCEPT（防「一律拒绝」式假修复）
  K3 不回退：空内容/语法错误仍 REJECT，且语法错误优先报语法（不比修前更差）
  K4 静态面：`_verify_code` 分支体内**确实调用** `_rule_check`（防被改回只做 AST）

判别力自证：删掉 K4 所指的那次调用，K1 必红、K4 必红（见 --mutate）。
哑值 `sk-live-FAKE...` / `AKIA...` / PEM 均为**合成串**，非真凭据。
"""
from __future__ import annotations

import inspect
import json
import re
import sys

from . import audit

_ok = 0
_bad = []

FAKE = "sk-live-FAKE0123456789abcdef0123"
DIRTY_SK = "TOKEN = '%s'\ndef get():\n    return TOKEN\n" % FAKE
DIRTY_AKIA = "AWS = 'AKIAABCDEFGHIJKLMNOP'\n"
DIRTY_PEM = ("K = '''-----BEGIN RSA PRIVATE KEY-----\n"
             "MIIEowIBAAKCAQEA1234567890abcdef\n"
             "-----END RSA PRIVATE KEY-----'''\n")
CLEAN = "def add(a, b):\n    return a + b\n"


def ok(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("  ok   %s" % name)
    else:
        _bad.append("%s %s" % (name, detail))
        print("  FAIL %s %s" % (name, detail))


def state_of(kind, content):
    rules = audit.load_rulebook()
    v = audit.audit(kind, {"content": content}, {"rules": rules})
    return v.get("state"), str(v.get("evidence") or "")


def main():
    print("== K1 行为面：code 正文命中禁表必须 REJECT ==")
    for label, body in (("sk-", DIRTY_SK), ("AKIA", DIRTY_AKIA), ("PEM", DIRTY_PEM)):
        st, ev = state_of("code", body)
        ok("K1 %s 形态判 REJECT" % label, st == audit.REJECT,
           "实得 state=%s evidence=%s" % (st, ev[:80]))

    print("== K2 不误伤：干净代码仍 ACCEPT ==")
    st, ev = state_of("code", CLEAN)
    ok("K2 干净代码 ACCEPT", st == audit.ACCEPT,
       "实得 state=%s evidence=%s" % (st, ev[:80]))

    print("== K3 不回退：原有拒绝理由不被削弱 ==")
    st, ev = state_of("code", "")
    ok("K3a 空内容仍 REJECT", st == audit.REJECT, "实得 %s" % st)
    st, ev = state_of("code", "def f(:\n")
    ok("K3b 语法错误仍 REJECT 且证据含「语法」",
       st == audit.REJECT and "语法" in ev, "实得 state=%s ev=%s" % (st, ev[:60]))

    print("== K4 静态面：_verify_code 确实调用 _rule_check ==")
    src = inspect.getsource(audit._verify_code)
    ok("K4 _verify_code 分支体内出现 _rule_check 调用",
       bool(re.search(r"_rule_check\(", src)),
       "分支体内未找到 _rule_check( —— 只做 AST 即本缺陷原形")

    print("== 对照腿：text/work_wip 未被本次改动影响 ==")
    st, _ = state_of("text", "值班记录：令牌 %s。" % FAKE)
    ok("K5 text 仍 REJECT", st == audit.REJECT, "实得 %s" % st)
    st, _ = state_of("work_wip", "值班记录：令牌 %s。" % FAKE)
    ok("K6 work_wip 仍 REJECT", st == audit.REJECT, "实得 %s" % st)

    print("")
    if _bad:
        print("code 禁表守卫：%d 通过，%d 失败" % (_ok, len(_bad)))
        for b in _bad:
            print("  红：%s" % b)
        return 1
    print("code 禁表守卫：%d 通过，0 失败" % _ok)
    return 0


if __name__ == "__main__":
    sys.exit(main())
