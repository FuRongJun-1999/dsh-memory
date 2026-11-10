# -*- coding: utf-8 -*-
"""#835 守卫：cogmap check 不得依赖本机 git remote 的 owner。

issue #835：`_repo_base()` 早先只认本机 `git remote get-url origin`，
⇒ fork（或任何 remote 指向别处的机器）里 check 必红，4 处差异全是 URL 里的 owner 字符串。
本守卫钉住三条：
  G1 COGMAP_REPO_BASE 可显式钉住基址；
  G2 `_norm_repo_base` 把任意 GitHub 仓库基址归一为占位符（owner/repo 不同不算漂移）；
  G3 在「另一个 owner」的基址下跑 check 仍然通过（同一份工作树、同一份文档）。
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import cogmap_sync as cs  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def main():
    print("=" * 66)
    print("#835 cogmap check 与 remote owner 解耦")
    print("=" * 66)

    old = os.environ.get("COGMAP_REPO_BASE")
    try:
        os.environ["COGMAP_REPO_BASE"] = "https://github.com/SomeFork/dsh-memory"
        base = cs._repo_base()
        ok(base == "https://github.com/SomeFork/dsh-memory", "G1 COGMAP_REPO_BASE 优先于 git origin", base)

        a = "https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L796"
        b = "https://github.com/SomeFork/dsh-memory/blob/main/md_cg/mcp_server.py#L796"
        ok(cs._norm_repo_base(a) == cs._norm_repo_base(b), "G2 不同 owner 归一后相等",
           (cs._norm_repo_base(a), cs._norm_repo_base(b)))
        c = "https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L797"
        ok(cs._norm_repo_base(a) != cs._norm_repo_base(c), "G2b 行号不同仍能判红（归一不掩盖漂移）")

        env = dict(os.environ)
        env["COGMAP_REPO_BASE"] = "https://github.com/SomeFork/dsh-memory"
        r = subprocess.run([sys.executable, "-X", "utf8", "scripts/cogmap_sync.py", "check"],
                           cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env, timeout=300)
        out = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        ok(r.returncode == 0, "G3 换 owner 的基址下 check 仍通过",
           (r.returncode, out[-1] if out else ""))
    finally:
        if old is None:
            os.environ.pop("COGMAP_REPO_BASE", None)
        else:
            os.environ["COGMAP_REPO_BASE"] = old

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())