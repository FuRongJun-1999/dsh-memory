#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_registry_tarball.py — check_registry_tarball.py 的回放断言（脚本式）。

覆盖：①旧版本 tarball 必红（本次事故形态）②版本一致必绿 ③不声明 tarball 必绿
④无版本号文件名必红 ⑤真实条目必绿（修复后）⑥条目缺失默认跳过、--require-entry 报错。
命令一律走 argv 列表 + 显式 UTF-8（工作纪律第 15 条）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_CHECK = os.path.join(_HERE, "check_registry_tarball.py")
_REAL_ENTRY = os.path.join(
    _REPO, "awesome-dsh-plugin", "data", "plugins", "FuRongJun-1999__dsh-memory.yml"
)


def run(args):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, _CHECK] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=_REPO,
    )


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def entry_text(tarball_url):
    head = "url: https://github.com/FuRongJun-1999/dsh-memory\nname: FuRongJun-1999/dsh-memory\ncategory: agi\n"
    if tarball_url is None:
        return head + "description:\n  en: placeholder\n"
    return head + "tarball: %s\n" % tarball_url + "description:\n  en: placeholder\n"


def main():
    base = "https://github.com/FuRongJun-1999/dsh-memory/releases/download"
    with tempfile.TemporaryDirectory() as tmp:
        pkg = os.path.join(tmp, "package.json")
        write(pkg, '{"name": "@furongjun1999/dsh-memory", "version": "0.4.8"}\n')

        # ① 旧版本 tarball 必红 —— 本次事故形态
        stale = os.path.join(tmp, "stale.yml")
        write(stale, entry_text(base + "/v0.3.0/furongjun1999-dsh-memory-0.3.0.tgz"))
        got = run(["--entry", stale, "--package", pkg])
        assert got.returncode == 1, got.stdout + got.stderr
        assert "0.3.0" in got.stdout and "0.4.8" in got.stdout, got.stdout

        # ② 版本一致必绿
        ok = os.path.join(tmp, "ok.yml")
        write(ok, entry_text(base + "/v0.4.8/furongjun1999-dsh-memory-0.4.8.tgz"))
        got = run(["--entry", ok, "--package", pkg])
        assert got.returncode == 0, got.stdout + got.stderr

        # ③ 不声明 tarball 必绿
        none = os.path.join(tmp, "none.yml")
        write(none, entry_text(None))
        got = run(["--entry", none, "--package", pkg])
        assert got.returncode == 0, got.stdout + got.stderr
        assert "未声明 tarball" in got.stdout, got.stdout

        # ④ 文件名不含版本号必红
        unver = os.path.join(tmp, "unver.yml")
        write(unver, entry_text(base + "/latest/download/your-plugin.tgz"))
        got = run(["--entry", unver, "--package", pkg])
        assert got.returncode == 1, got.stdout + got.stderr

        # ⑤ 条目缺失默认跳过 / --require-entry 报错
        missing = os.path.join(tmp, "missing.yml")
        got = run(["--entry", missing, "--package", pkg])
        assert got.returncode == 0 and "SKIPPED" in got.stdout, got.stdout
        got = run(["--entry", missing, "--package", pkg, "--require-entry"])
        assert got.returncode == 2, got.stdout + got.stderr

        # ⑥ 真实条目必绿（修复前此处为红，即本测试的负例证据）
        if os.path.isfile(_REAL_ENTRY):
            got = run(["--entry", _REAL_ENTRY, "--package", os.path.join(_REPO, "package.json")])
            assert got.returncode == 0, "真实条目未通过：" + got.stdout + got.stderr
        else:
            print("SKIP 真实条目不在本地")

    print("ALL PASS test_registry_tarball")
    return 0


if __name__ == "__main__":
    sys.exit(main())
