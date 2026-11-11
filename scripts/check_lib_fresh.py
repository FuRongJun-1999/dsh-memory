#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""`lib/` 新鲜度守卫：构建产物不得落后于 `src/`（src↔lib mtime 单调）。

===== 为什么需要这条 =====

本包的发布契约是 `main → lib/index.js`（package.json），而 `lib/` 被
`.gitignore` 忽略——它**只存在于构建机/安装态**，不进 git。于是有两条独立
的失效路径，任何一条都让「装到的包」与「仓里的源码」不是同一个东西：

① **`lib/` 陈旧**：`src/` 改了 54 次提交，`lib/` 还停在旧构建（实测本地
   2026-10-14 vs 源码 2026-11-11）。跑 `node lib/…` 得到的是老代码，而
   `npm test` 会先 build 再测 ⇒ **测试永远对着新代码**，陈旧面测不出来。
② **`lib/` 缺失**：干净克隆/`--omit=dev` 安装下根本没有 `lib/`，包入口悬空
   而无人察觉（issue #161 的同族现场）。

本守卫只做**单调性**判断（产物时间 ≥ 源码时间），不重新构建、不装依赖——
因此能在不装 devDependencies 的环境（含 CI 的轻量 job）里跑，也不会与
`npm run build` 抢同一份 `lib/`。

===== 判据（三条，各自可红）=====

G1 **存在性**：`lib/index.js` 与 `lib/index.d.ts` 必须在（包入口 + 类型入口）。
G2 **单调性**：`lib/` 下每个构建产物，其 mtime 不得**早于**其来源 `src/`
   文件。产物→来源的映射是 `tsc` 的目录结构（`src/x.ts` → `lib/x.js`、
   `src/lib/x.ts` → `lib/lib/x.js`），故按同名去 `.js`/`.d.ts` 后缀反查。
G3 **覆盖性**：`src/` 下每个 `.ts` 都必须有对应的 `.js` 产物。缺产物说明
   构建没跑完或 `tsconfig` 的 `outDir/include` 漂了——这比陈旧更难发现
   （旧的产物还在，只是少了一部分新模块）。

===== 退出码 =====
0 = 合规；1 = 违规；2 = **判据不可用**（`src/` 不存在 = 安装态/子包视角，
拒绝以「没东西可查」冒充通过——同 `run_tests.py` 的零选中 fail-closed 口径）。

===== 用法 =====

    python scripts/check_lib_fresh.py            # 检查
    python scripts/check_lib_fresh.py --quiet    # 只报违规（CI 日志更短）
    python scripts/check_lib_fresh.py --allow-missing
                                                 # lib/ 整目录缺失时只警告（本地首次 clone）

`--allow-missing` 是给**本地开发**用的：干净克隆后还没 build 时不该被判红。
CI 与 `npm run gate` **不得**用它（发布契约必须真的成立）。
"""
from __future__ import annotations

import argparse
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO, "src")
_LIB = os.path.join(_REPO, "lib")

#: 构建产物的后缀（`tsc` 对每个 .ts 出 .js + .d.ts；`.map` 可选）
_ARTIFACT_SUFFIXES = (".js", ".d.ts")


def _iter_ts(root):
    """递归列出 root 下的 .ts（跳过 node_modules / __pycache__）。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("node_modules", "__pycache__", ".git")]
        for fn in filenames:
            if fn.endswith(".ts") and not fn.endswith(".d.ts"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def _rel(path, base):
    return os.path.relpath(path, base).replace(os.sep, "/")


def _source_for(artifact, lib_root):
    """产物路径 → 期望的来源 .ts 路径（`tsc` 保持目录结构，只换后缀）。"""
    rel = _rel(artifact, lib_root)
    for suf in _ARTIFACT_SUFFIXES:
        if rel.endswith(suf):
            rel = rel[: -len(suf)] + ".ts"
            return os.path.join(_SRC, rel.replace("/", os.sep))
    if rel.endswith(".js.map"):
        return os.path.join(_SRC, rel[:-len(".js.map")].replace("/", os.sep) + ".ts")
    return None


def _iter_artifacts(lib_root):
    out = []
    for dirpath, dirnames, filenames in os.walk(lib_root):
        dirnames[:] = [d for d in dirnames if d != "node_modules"]
        for fn in filenames:
            out.append(os.path.join(dirpath, fn))
    return sorted(out)


def check(quiet=False, allow_missing=False):
    """执行三条判据，返回 (exit_code, 违规列表, 统计 dict)。"""
    def say(msg):
        if not quiet:
            print(msg)

    if not os.path.isdir(_SRC):
        print("判据不可用：%s 不存在（安装态/子包视角，无从判断 src↔lib 新鲜度）"
              % _rel(_SRC, _REPO), file=sys.stderr)
        return 2, [], {}

    ts_files = _iter_ts(_SRC)
    stats = {"src_ts": len(ts_files)}

    entry = os.path.join(_LIB, "index.js")
    entry_dts = os.path.join(_LIB, "index.d.ts")
    if not os.path.isdir(_LIB):
        msg = "lib/ 不存在（未构建：干净克隆或 --omit=dev 安装）"
        if allow_missing:
            say("WARN " + msg + " —— --allow-missing 放行（本地首次 clone）")
            return 0, [], stats
        return 1, [msg], stats

    bad = []
    # ---- G1 存在性：包入口与类型入口 ----
    for path, label in ((entry, "lib/index.js（package.json main）"),
                        (entry_dts, "lib/index.d.ts（package.json types）")):
        if not os.path.isfile(path):
            bad.append("G1 缺构建入口：%s" % label)
    say("G1 构建入口：%s"
        % ("缺" if bad else "齐（lib/index.js + lib/index.d.ts）"))

    # ---- G2 单调性 ----
    artifacts = _iter_artifacts(_LIB)
    stats["lib_files"] = len(artifacts)
    stale = []
    for art in artifacts:
        src = _source_for(art, _LIB)
        if src is None or not os.path.isfile(src):
            continue                    # 无对应来源（如 lib/ 下的 .json）不判
        if os.path.getmtime(art) < os.path.getmtime(src):
            stale.append((_rel(art, _REPO), _rel(src, _REPO)))
    for art, src in stale[:20]:
        bad.append("G2 产物陈旧：%s 早于 %s" % (art, src))
    if len(stale) > 20:
        bad.append("G2 另有 %d 个陈旧产物（只列前 20 条）" % (len(stale) - 20))
    stats["stale"] = len(stale)
    say("G2 单调性：%d 个产物中 %d 个陈旧"
        % (len(artifacts), len(stale)))

    # ---- G3 覆盖性：每个 src/*.ts 都要有 .js 产物 ----
    missing = []
    for src in ts_files:
        want = os.path.join(_LIB, _rel(src, _SRC)).replace(".ts", ".js")
        if not os.path.isfile(want):
            missing.append((_rel(src, _REPO), _rel(want, _REPO)))
    for src, want in missing[:20]:
        bad.append("G3 缺产物：%s → 应有 %s" % (src, want))
    if len(missing) > 20:
        bad.append("G3 另有 %d 个 src 文件无产物（只列前 20 条）" % (len(missing) - 20))
    stats["missing"] = len(missing)
    say("G3 覆盖性：%d 个 src/*.ts 中 %d 个无产物"
        % (len(ts_files), len(missing)))

    return (1 if bad else 0), bad, stats


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python scripts/check_lib_fresh.py",
        description="lib/ 新鲜度守卫（src↔lib mtime 单调 + 产物覆盖）")
    ap.add_argument("--quiet", action="store_true", help="只报违规")
    ap.add_argument("--allow-missing", action="store_true",
                    help="lib/ 整目录缺失时只警告（本地首次 clone；CI 不得用）")
    args = ap.parse_args(argv)

    rc, bad, stats = check(quiet=args.quiet, allow_missing=args.allow_missing)
    if rc == 2:
        return 2
    if bad:
        print("")
        print("lib/ 新鲜度：FAIL（%d 条）" % len(bad))
        for line in bad:
            print("  - " + line)
        print("")
        print("修法：在仓根跑 `npm run build`（需 devDependencies："
              "`npm ci --include=dev`）后重新检查。")
        return 1
    if not args.quiet:
        print("")
        print("lib/ 新鲜度：OK（src %d 个 .ts，lib %d 个文件，陈旧 0，缺产物 0）"
              % (stats.get("src_ts", 0), stats.get("lib_files", 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
