# -*- coding: utf-8 -*-
r"""守卫 · #95 context_files 通道的敏感路径黑名单补面（2026-10-09 DSH 端实施）。

缺陷（GitHub #95）：context_files 走**黑名单**，而黑名单天生会漏——漏掉的恰好是
本项目自己落盘的管理员明文令牌（~/.mdcg/token），以及 .pgpass / .my.cnf /
*.bash_history 这些实测「原文进入消息」的形态。

本笔处置（**建议 2 与 3**，均为纯增量、不动白名单语义）：
  · _SENSITIVE_DIR_SEGMENTS 增 .mdcg / keyrings
  · _SENSITIVE_FILE_NAMES 增 token / .pgpass / .my.cnf / keyring 系 / 浏览器密码库
  · 族匹配增 *_history 与 .history
  · _PII_PATTERNS 增灵枢令牌形态 mdcg1.<...>（与 data/policy.json 第 11 条同源）
**未做**：#95 建议 1（context_files 复用白名单语义）—— 它会改变既有调用方
（含本端自己传绝对路径的用法）的可达面，属**行为变更**，另出稿待裁。

判据（真跑 _sensitive_read / PII 脱敏）：
  G1 ~/.mdcg/token ⇒ 命中（designer 明文令牌，本仓自己签发的那个）
  G2 .pgpass / .my.cnf ⇒ 命中
  G3 *.bash_history / .history ⇒ 命中
  G4 mdcg1.<...> 令牌文本 ⇒ PII 脱敏命中
  G5 不误伤：普通文件（notes.md / data.txt）⇒ 不命中
运行：python -X utf8 -m hive.test_issue95_context_files_creds
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

PASS = 0
FAIL = 0
FAILS = []


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
    import exec as E   # noqa: E402 —— hive/exec.py（与本文件同目录）

    def hit(p):
        r = E._sensitive_read(os.path.realpath(p))
        return r is not None

    home = os.path.expanduser("~")
    g1 = [os.path.join(home, ".mdcg", "token"),
          os.path.join(home, ".mdcg", "_tokens.json")]
    for p in g1:
        check("G1 命中 %s（#95 的核心形态）" % os.path.basename(p), hit(p), p)
    for p in (os.path.join(home, ".pgpass"), os.path.join(home, ".my.cnf")):
        check("G2 命中 %s" % os.path.basename(p), hit(p), p)
    for p in (os.path.join(home, ".bash_history"), os.path.join(home, ".zsh_history")):
        check("G3 命中 %s（命令历史）" % os.path.basename(p), hit(p), p)

    # G4 PII：令牌文本须被脱敏
    token = "mdcg1.designer.tk_0123456789abcdef.SECRETSECRETSECRET"
    red = E._redact_deep(token) if hasattr(E, "_redact_deep") else None
    if red is None:
        # 退路：用模式表直接验证
        matched = any(rx.search(token) for _n, rx in E._PII_PATTERNS)
        check("G4 mdcg1. 令牌被 PII 模式命中", matched, "")
    else:
        check("G4 mdcg1. 令牌被脱敏（原文不再出现）",
              token not in str(red), str(red)[:60])

    # G5 不误伤
    for p in (os.path.join(REPO, "README.md"), os.path.join(REPO, "hive", "exec.py")):
        check("G5 不误伤 %s" % os.path.basename(p), not hit(p), p)

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
