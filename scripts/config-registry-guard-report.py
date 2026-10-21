#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config-registry-guard-report.py · 跑 registry 守卫并把输出落文件。

为什么需要它：DSH 沙箱下 node 的 spawn 不能接管道（EPERM），而
`python -m md_cg.config_registry_guard` 的判据要读 stdout。本脚本在 Python 内部
用 subprocess 拿输出（没有跨进程管道限制），写到 `--out=` 指定的文件。
退出码沿用守卫的退出码，方便门直接判。
"""
import os
import subprocess
import sys


def main(argv):
    out = None
    for a in argv:
        if a.startswith("--out="):
            out = a.split("=", 1)[1]
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, "-m", "md_cg.config_registry_guard"],
                       cwd=repo, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    text = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    sys.stdout.write(text)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
