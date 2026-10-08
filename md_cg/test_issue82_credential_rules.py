# -*- coding: utf-8 -*-
r"""守卫 · #82.1 写入门禁禁表扩边界（2026-10-09 裁定 + DSH 端实施）。

背景（修订前）：
  · 第 7 条 (?i)\b(password|passwd|pwd|密码|口令)\s*[:=：]\s*\S{6,} 有**双向**问题——
    漏：汉字之间无词边界，「我的密码：abc123456」判不中；
    伤：行首/空白后的「密码：三联体密码子…」（生物学知识）判中。
  修后：英文侧保留 \b、中文侧不加，并把值侧收紧为「含数字的连续凭据形态 token」。
  · 新增第 12 条覆盖「是/为/等于/is」形态。

判据（真跑判定层）：
  G1 三形态（是 / is / =）一律 REJECT
  G2 原漏的两个形态（句中冒号、= 中文前缀）现能 REJECT
  G3 误伤对照：生物学句「密码：三联体密码子…」**不得**命中（修前会命中）
  G4 已知边界如实保留：纯字母值、纯空格形态仍 ACCEPT（宁漏勿伤取向）
  G5 禁表条数=12 且可加载
运行：python -X utf8 -m md_cg.test_issue82_credential_rules
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
SIX = ("# 功能名：t\n# 生效条件：t\n# 子功能：t\n# 执行：t\n"
       "# 验证方式：t\n# 不适用条件：t\n")


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
    pol = os.path.join(REPO, "data", "policy.json")
    rules = audit.load_rulebook(pol)
    check("G5 禁表可加载且条数=12", len(rules.get("forbidden") or []) == 12,
          "n=%d" % len(rules.get("forbidden") or []))

    def verdict(tail):
        return audit.VERIFIERS["text"]({"content": SIX + tail}, {"rules": rules}).get("state")

    for name, tail in (("是形态·中文", "我的密码是abc123456"),
                       ("is形态·英文", "the password is abc123456"),
                       ("=形态·中文前缀", "我的密码=abc123456")):
        check("G1 %s ⇒ REJECT" % name, verdict(tail) == "REJECT", str(verdict(tail)))

    for name, tail in (("句中冒号（原漏）", "我的密码：abc123456"),
                       ("= 中文前缀（原漏）", "我的密码=abc123456")):
        check("G2 %s ⇒ REJECT" % name, verdict(tail) == "REJECT", str(verdict(tail)))

    bio = "密码：三联体密码子、简并性、通用性。起始密码子AUG、终止密码子。"
    check("G3 误伤对照·生物学句 ⇒ ACCEPT（修前会命中）",
          verdict(bio) == "ACCEPT", str(verdict(bio)))

    check("G4a 纯字母值 ⇒ ACCEPT（宁漏勿伤，已知边界）",
          verdict("我的密码：abcdefgh") == "ACCEPT", "")
    check("G4b 纯空格形态 ⇒ ACCEPT（已知残留漏面，按裁决暂不加）",
          verdict("我的密码 abc123456") == "ACCEPT", "")

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
