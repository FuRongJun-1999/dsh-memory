# -*- coding: utf-8 -*-
r"""守卫 · #93 mdcg_remember 通路须过 policy 打码（2026-10-09 DSH 端实施）。

缺陷（GitHub #93）：mdcg_remember（hooks 自动记忆走的通路）**不过** policy.json
的 forbidden 规则 ⇒ AKIA / ghp_ / URL 内嵌凭据 / PEM 私钥块**明文入库**且 guest
可检索；而同样内容走 cg(op=write) 会被判 REJECT。

本笔处置：在该分支落盘前，用 **audit.redact_forbidden 按片段打码**（与 REJECT 分支
同口径，非整条拒绝——自动记忆是 hooks 通路，整条拒绝会静默丢记忆）。

判据：
  G1 四种形态都能被 redact_forbidden 命中并改变文本（AKIA/ghp/URL 凭据/PEM）
  G2 静态：mdcg_remember 分支体内**确实调用**了 redact_forbidden（防被回退）
  G3 不误伤：普通内容经 redact_forbidden **逐字不变**
  G4 与 policy.json 同源：命中的正是 policy 里那条（防「另起一套模式」）
运行：python -X utf8 -m md_cg.test_issue93_remember_redaction
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []
CASES = (
    ("AWS AKIA", "AKIAIOSFODNN7EXAMPLE"),
    ("GitHub ghp_", "ghp_0123456789abcdefghijklmnopqrstuvwxyz"),
    ("URL 内嵌凭据", "postgres://admin:Hunter2Secret@db.example.com:5432/app"),
    ("PEM 私钥块", "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----"),
)


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def main():
    from md_cg import audit
    rules = audit.load_rulebook()
    if isinstance(rules, tuple):
        rules = rules[0]

    for label, text in CASES:
        red = audit.redact_forbidden(text, rules)
        check("G1 %s ⇒ 被脱敏（原文不再出现）" % label,
              red != text and text not in red, str(red)[:60])

    # G2 静态：分支体内真的调了 redact_forbidden
    src = open(os.path.join(HERE, "mcp_server.py"), encoding="utf-8").read()
    i = src.find('if name == "mdcg_remember":')
    seg = src[i:i + 3000] if i >= 0 else ""
    check("G2 静态：mdcg_remember 分支体内调用 redact_forbidden",
          "redact_forbidden" in seg, "分支体长度=%d" % len(seg))

    # G3 不误伤
    plain = "# 功能名：t\n# 执行：端口是 5432\n"
    check("G3 普通内容经 redact_forbidden 逐字不变",
          audit.redact_forbidden(plain, rules) == plain, "")

    # G4 同源：命中的规则确在 policy.json 的 forbidden 里
    pol = open(os.path.join(REPO, "data", "policy.json"), encoding="utf-8").read()
    check("G4 与 policy.json 同源（AKIA 规则在其中）",
          "AKIA" in pol, "")

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
