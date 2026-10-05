#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_registry_tarball.py — check_registry_tarball.py 的回放断言（脚本式）。

覆盖：①旧版本 tarball 必红（本次事故形态）②版本一致必绿 ③不声明 tarball 必绿
④无版本号文件名必红 ⑤真实条目必绿（修复后）⑥条目缺失默认跳过、--require-entry 报错
⑦N256：YAML 合法别写法（缩进/行内注释/冒号前空格/列表项/内联映射）不得失明——
旧的行锚正则在这五形态下全部静默放行（rc 与真·未声明逐字相同）；另断言形态非法
（`tarball: [a,b]`）fail-closed 为 rc=2，不得降级为「未声明」。
命令一律走 argv 列表 + 显式 UTF-8（工作纪律第 15 条）。

用法：
  python -X utf8 scripts/test_registry_tarball.py               # 测工作树版
  python -X utf8 scripts/test_registry_tarball.py --impl head   # 红基线：HEAD 版（⑦ 组转红即证据；
                                                                # 该改动入库后 HEAD 含修复，红基线不再复现）
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_CHECK = os.path.join(_HERE, "check_registry_tarball.py")
_REAL_ENTRY = os.path.join(
    _REPO, "awesome-dsh-plugin", "data", "plugins", "FuRongJun-1999__dsh-memory.yml"
)


_IMPL = _CHECK          # 被测实现（main 依 --impl 覆写；红基线 = HEAD 版）


def materialize_head(tmp):
    """物化 HEAD 版实现（红基线取证）；失败返回 None。"""
    p = subprocess.run(
        ["git", "show", "HEAD:scripts/check_registry_tarball.py"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=_REPO)
    if p.returncode != 0 or not p.stdout:
        return None
    out = os.path.join(tmp, "check_registry_tarball_head.py")
    write(out, p.stdout)
    return out


def run(args):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, _IMPL] + args,
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


def _run_all():
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

        # ⑦ N256：YAML 合法别写法不得失明（旧行锚正则五形态全盲 ⇒ 静默放行）
        stale_url = base + "/v0.3.0/furongjun1999-dsh-memory-0.3.0.tgz"
        ok_url = base + "/v0.4.8/furongjun1999-dsh-memory-0.4.8.tgz"

        def _doc(variant, url):
            head = ("url: https://github.com/FuRongJun-1999/dsh-memory\n"
                    "name: FuRongJun-1999/dsh-memory\ncategory: agi\n")
            tail = "description:\n  en: placeholder\n"
            if variant == "缩进":
                return "".join("  " + ln + "\n"
                               for ln in (head + "tarball: %s\n" % url).splitlines())
            if variant == "行内注释":
                return head + "tarball: %s  # pinned\n" % url + tail
            if variant == "冒号前空格":
                return head + "tarball : %s\n" % url + tail
            if variant == "列表项":
                return "- name: x\n  tarball: %s\n- name: y\n" % url
            if variant == "内联映射":
                return "{name: x, tarball: '%s'}\n" % url
            raise AssertionError(variant)

        for variant in ("缩进", "行内注释", "冒号前空格", "列表项", "内联映射"):
            f = os.path.join(tmp, "v_%s.yml" % variant)
            write(f, _doc(variant, stale_url))
            got = run(["--entry", f, "--package", pkg])
            assert got.returncode == 1, "形态「%s」失明（rc=%s）：%s" % (
                variant, got.returncode, got.stdout + got.stderr)
            assert "0.3.0" in got.stdout and "0.4.8" in got.stdout, got.stdout
        # 对照：同形态携当前版本必绿
        f = os.path.join(tmp, "v_ok.yml")
        write(f, _doc("行内注释", ok_url))
        got = run(["--entry", f, "--package", pkg])
        assert got.returncode == 0, got.stdout + got.stderr
        # 形态非法（非字符串）→ fail-closed rc=2（不得降级为「未声明」）
        f = os.path.join(tmp, "v_bad.yml")
        write(f, "tarball: [a, b]\n")
        got = run(["--entry", f, "--package", pkg])
        assert got.returncode == 2, got.stdout + got.stderr

    print("ALL PASS test_registry_tarball")
    return 0


def main(argv=None):
    global _IMPL
    ap = argparse.ArgumentParser(description="check_registry_tarball 回放断言")
    ap.add_argument("--impl", default=None,
                    help="被测实现：缺省=工作树版；head=HEAD 版（红基线）；或 .py 路径")
    ns = ap.parse_args(argv)
    impl_dir = None
    if ns.impl == "head":
        impl_dir = tempfile.mkdtemp(prefix="registry_tarball_head_")
        impl = materialize_head(impl_dir)
        if impl is None:
            print("无法物化 HEAD 版（git show 失败）——红基线取证不可用")
            return 2
        _IMPL = impl
    elif ns.impl:
        _IMPL = os.path.abspath(ns.impl)
    try:
        return _run_all()
    finally:
        if impl_dir:
            shutil.rmtree(impl_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
