#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_pkg_version_sync.py — package.json / package-lock.json 版本一致性门禁。

病灶：`package.json` 手改版本时忘了同步 `package-lock.json`，两份版本号就会长期漂移
（本仓实测：package.json=0.11.1，package-lock.json=0.9.23，**漂了 8 个版本没人发现**）。
npm 侧不会报错，但 `npm ci` / 发包 / 依赖审计都会读到那份旧版本号。

判据（三处必须逐字相等）：
  ① package.json            .version
  ② package-lock.json       .version
  ③ package-lock.json       .packages[""].version

退出码：0 一致｜1 不一致｜2 读取/用法错误
--selftest 跑内置正负例（不读真实文件），失败同样非零退出。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile


def _read_version(path, dotted_key):
    """按路径读版本号；读不到返回 None（调用方判为 error）。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    node = data
    for part in dotted_key:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return str(node or "").strip() or None


def check(root):
    """返回 (code, message, detail)。"""
    pj = os.path.join(root, "package.json")
    pl = os.path.join(root, "package-lock.json")
    if not os.path.isfile(pj) or not os.path.isfile(pl):
        return 2, "缺少 package.json 或 package-lock.json", {}
    got = {
        "package.json": _read_version(pj, ("version",)),
        "package-lock.json": _read_version(pl, ("version",)),
        "package-lock.packages[root]": _read_version(pl, ("packages", "", "version")),
    }
    missing = [k for k, v in got.items() if not v]
    if missing:
        return 2, "版本号缺失：%s" % ", ".join(missing), got
    uniq = set(got.values())
    if len(uniq) == 1:
        return 0, "版本一致：%s" % got["package.json"], got
    return 1, "版本不一致：%s" % json.dumps(got, ensure_ascii=False), got


def _selftest():
    """正负例：一致必绿、lock 漂移必红、缺键必红、缺文件必红。"""
    cases = []
    tmp = tempfile.mkdtemp(prefix="pkgver_")
    try:
        def write(ver_pj, ver_pl, ver_root, with_lock=True):
            with open(os.path.join(tmp, "package.json"), "w", encoding="utf-8") as f:
                json.dump({"name": "x", "version": ver_pj}, f)
            if with_lock:
                lock = {"name": "x", "version": ver_pl, "lockfileVersion": 3,
                        "packages": {"": {"name": "x", "version": ver_root}}}
                with open(os.path.join(tmp, "package-lock.json"), "w", encoding="utf-8") as f:
                    json.dump(lock, f)

        write("0.11.2", "0.11.2", "0.11.2")
        cases.append(("一致 ⇒ 0", check(tmp)[0], 0))
        write("0.11.2", "0.9.23", "0.9.23")
        cases.append(("lock 漂移 ⇒ 1", check(tmp)[0], 1))
        write("0.11.2", "0.11.2", "0.9.23")
        cases.append(("packages[root] 漂移 ⇒ 1", check(tmp)[0], 1))
        with open(os.path.join(tmp, "package-lock.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "x", "version": "0.11.2", "lockfileVersion": 3, "packages": {}}, f)
        cases.append(("缺 packages[root].version ⇒ 2", check(tmp)[0], 2))
        with open(os.path.join(tmp, "package.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "x"}, f)
        cases.append(("缺 version ⇒ 2", check(tmp)[0], 2))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    bad = 0
    for name, got, want in cases:
        ok = got == want
        print(("  PASS " if ok else "  FAIL ") + "%s（得到 %s）" % (name, got))
        bad += 0 if ok else 1
    print("自检：%d 通过 / %d 失败" % (len(cases) - bad, bad))
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="package.json / package-lock.json 版本一致性门禁")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    code, msg, detail = check(args.root)
    print(("PASS " if code == 0 else "FAIL ") + msg)
    if detail and code != 0:
        for k, v in detail.items():
            print("  %-30s %s" % (k + ":", v))
        print("修复：`npm version <x.y.z> --no-git-tag-version` 会同时更新两处；手改 package.json 后务必重生成 lock。")
    return code


if __name__ == "__main__":
    sys.exit(main())