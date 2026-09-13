# -*- coding: utf-8 -*-
"""run_tests.py · 全仓测试一键入口（固化 `python -m` 运行约定）。

背景（2026-09-13 全面分析报告建议 #3）：md_cg 包内测试普遍使用**相对导入**，
必须以模块方式从仓库根运行——`python -m md_cg.test_xxx`；直接
`python md_cg/test_xxx.py` 会因相对导入 ImportError（59/61 踩坑实测）。
本脚本把该约定固化为唯一入口，杜绝逐文件手敲与跑法漂移。

测试面（与仓库实际保持同步）：
  md_cg/      test_*.py → python -m md_cg.<name>
  compiler/   tests/*.py（脚本式 assert+sys.exit）→ -m compiler.tests.<name>
  swarm/      tests/*.py（脚本式 assert+sys.exit）→ -m swarm.tests.<name>

用法（任意 cwd 均可，内部以仓库根为 subprocess cwd）：
  python scripts/run_tests.py                  # 全量
  python scripts/run_tests.py md_cg            # 只跑一组：md_cg | compiler | swarm
  python scripts/run_tests.py -k p44           # 按关键字过滤模块名
  python scripts/run_tests.py --jobs 1         # 串行（默认并发 4）
  python scripts/run_tests.py --list           # 只列出目标不执行

退出码：全部通过 0，存在失败 1（可直接接 CI / 提交前门禁）。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import subprocess
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _discover():
    """返回 [(组名, 显示名, argv)]；argv 为候选列表（依次尝试直到成功启动）。"""
    import glob

    out = []
    for f in sorted(glob.glob(os.path.join(_REPO, "md_cg", "test_*.py"))):
        stem = os.path.splitext(os.path.basename(f))[0]
        out.append(("md_cg", f"md_cg.{stem}",
                    [[sys.executable, "-X", "utf8", "-m", f"md_cg.{stem}"]]))
    for pkg in ("compiler", "swarm"):
        for f in sorted(glob.glob(os.path.join(_REPO, pkg, "tests", "*.py"))):
            if os.path.basename(f).startswith("_"):
                continue
            stem = os.path.splitext(os.path.basename(f))[0]
            out.append((pkg, f"{pkg}.tests.{stem}",
                        [[sys.executable, "-X", "utf8", "-m",
                          f"{pkg}.tests.{stem}"],
                         [sys.executable, "-X", "utf8", f]]))
    return out


def _run_one(name, argvs, timeout):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    last = ""
    for argv in argvs:                    # -m 优先；No module named 时回退直跑
        try:
            r = subprocess.run(argv, cwd=_REPO, capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               env=env, shell=False, timeout=timeout)
        except subprocess.TimeoutExpired:
            return name, False, f"超时（>{timeout}s）"
        if not (r.returncode != 0 and "No module named" in (r.stderr or "")
                and len(argvs) > 1):
            tail = ((r.stdout or "") + (r.stderr or ""))[-800:]
            return name, r.returncode == 0, tail
        last = (r.stderr or "")[-300:]
    return name, False, last


def main():
    ap = argparse.ArgumentParser(description="灵枢全仓测试入口（python -m 约定）")
    # 注：不用 argparse choices——部分 Python 版本对 nargs="*" 无值时
    # 以空列表过 choices 校验会误报 invalid choice（bpo-27227 老行为）。
    ap.add_argument("group", nargs="*", default=None,
                    help="只跑指定组，可多选：md_cg compiler swarm（缺省全量）")
    ap.add_argument("-k", default="", help="按关键字过滤模块名")
    ap.add_argument("--jobs", type=int, default=4, help="并发数（默认 4）")
    ap.add_argument("--timeout", type=int, default=900, help="单测超时秒数")
    ap.add_argument("--list", action="store_true", help="只列出目标不执行")
    args = ap.parse_args()

    _known = ("md_cg", "compiler", "swarm")
    _bad = [g for g in (args.group or ()) if g not in _known]
    if _bad:
        ap.error(f"invalid group: {', '.join(_bad)}（可选：{'/'.join(_known)}）")
    groups = set(args.group or ()) or set(_known)
    targets = [(g, n, a) for g, n, a in _discover()
               if g in groups and (not args.k or args.k in n)]
    if args.list:
        for g, n, _a in targets:
            print(f"{g:<9}{n}")
        print(f"共 {len(targets)} 个")
        return 0

    bad = []
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, args.jobs)) as ex:
        futs = {ex.submit(_run_one, n, a, args.timeout): (g, n)
                for g, n, a in targets}
        for fu in concurrent.futures.as_completed(futs):
            name, ok, tail = fu.result()
            print(("PASS  " if ok else "FAIL  ") + name, flush=True)
            if not ok:
                bad.append(name)
                for ln in tail.splitlines()[-6:]:
                    print("      " + ln, flush=True)

    print(f"\n===== SUMMARY {len(targets) - len(bad)}/{len(targets)} 通过 =====")
    if bad:
        print("失败：" + ", ".join(bad))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
