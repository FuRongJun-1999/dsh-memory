# -*- coding: utf-8 -*-
"""守卫 · #81 swarm 密钥 fail-closed（2026-10-09 设计者裁定 A，DSH 端实施）。

背景：修前 make_swarm_config 的 shared_secret 缺省回落**源码内公开常量**
「蜂群默认密钥」，main.rs 亦 unwrap_or 同一常量 ⇒ 任何读过源码者可自签伪造
WAL 行并通过验签（实测 all_valid=true，FI-R08 记于混沌注入 case）。

修后（裁定 A：fail-closed）：Python 入口缺/空一律 raise ValueError；Rust 入口
缺/空一律 eprintln + ExitCode(2) 拒启动；DEFAULT_SECRET 常量保留供显式引用与
历史对照，但不再作缺省。

判据：
  G1 Python：不传 shared_secret ⇒ ValueError（修前：静默使用公开常量）
  G2 Python：显式传入 ⇒ 正常，且 cfg 里就是传入值
  G3 Python：空串 ⇒ ValueError（N143 既有口径保持）
  G4 源码：rust_swarm.py / main.rs 均不再把公开常量作缺省回落
  G5 常量：DEFAULT_SECRET 仍在（供显式引用/历史对照），不是被删
运行：python -X utf8 -m swarm.tests.test_issue81_secret_fail_closed
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for _p in (REPO,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

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
    from swarm.rust_swarm import make_swarm_config, DEFAULT_SECRET

    try:
        make_swarm_config([{"id": "a"}], [])
        check("G1 不传 shared_secret ⇒ ValueError（修前=静默用公开常量）", False,
              "未抛异常（fail-open 回归！）")
    except ValueError as exc:
        check("G1 不传 shared_secret ⇒ ValueError（修前=静默用公开常量）", True,
              str(exc)[:70])

    try:
        cfg = make_swarm_config([{"id": "a"}], [], shared_secret="guard-explicit-key")
        check("G2 显式传入 ⇒ 正常且 cfg 采用该值",
              cfg.get("shared_secret") == "guard-explicit-key", str(cfg.get("shared_secret")))
    except Exception as exc:
        check("G2 显式传入 ⇒ 正常且 cfg 采用该值", False, repr(exc)[:80])

    try:
        make_swarm_config([{"id": "a"}], [], shared_secret="")
        check("G3 空串 ⇒ ValueError（N143 口径保持）", False, "未抛异常")
    except ValueError:
        check("G3 空串 ⇒ ValueError（N143 口径保持）", True, "")

    rs = open(os.path.join(REPO, "swarm", "rust_swarm.py"), encoding="utf-8").read()
    check("G4a rust_swarm.py 不再把 DEFAULT_SECRET 作参数缺省",
          "shared_secret: str = DEFAULT_SECRET" not in rs, "")
    mr = open(os.path.join(REPO, "swarm", "rust_runtime", "src", "main.rs"),
              encoding="utf-8").read()
    # 只在**非注释行**里找：注释中引用旧行为（修前 unwrap_or(...)）是说明性的，
    # 不构成缺省回落；判据要打在代码面上。
    mr_code = "\n".join(l for l in mr.splitlines() if not l.strip().startswith("//"))
    check("G4b main.rs 代码面不再 unwrap_or 公开常量",
          'unwrap_or("' + "蜂群默认密钥" + '")' not in mr_code, "")
    check("G4c main.rs 含拒绝分支（ExitCode::from(2) 且提到 shared_secret）",
          ("ExitCode::from(2)" in mr) and ("shared_secret" in mr), "")

    check("G5 DEFAULT_SECRET 常量保留（供显式引用/历史对照）",
          DEFAULT_SECRET == "蜂群默认密钥", repr(DEFAULT_SECRET))

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
