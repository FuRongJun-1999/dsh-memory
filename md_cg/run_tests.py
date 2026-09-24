# -*- coding: utf-8 -*-
"""run_tests.py · 测试一键入口（固化 `python -m` 运行约定）。

背景（2026-09-13 全面分析报告建议 #3）：md_cg 包内测试普遍使用**相对导入**，
必须以模块方式从仓库根运行——`python -m md_cg.test_xxx`；直接
`python md_cg/test_xxx.py` 会因相对导入 ImportError（59/61 踩坑实测）。
本脚本把该约定固化为唯一入口，杜绝逐文件手敲与跑法漂移。

**本模块是包内入口**（2026-09-24 修复）：原入口只在 `scripts/run_tests.py`，
而出货包 `files` 不含 `scripts/` —— README 写的门禁命令在安装态不存在。
现在 `python -m md_cg.run_tests` 恒可用；源码树里 `scripts/run_tests.py`
可继续作为薄封装（同一约定）。

与 scripts/ 版的两点差异（都是为了在受限宿主里可跑）：
  ① 子进程输出**重定向到文件**，不用 capture_output（管道）：DSH 文件沙箱
     禁 CreatePipe（WinError 5），旧写法在受限环境里每个用例都 PermissionError
     ——表现为「全部失败」，与代码无关。日志落在 `<testlogs>/` 便于事后查。
  ② 组集合按**存在性**发现：compiler / swarm / scripts / hive 不在（安装态）
     就自然没有目标，不报错。

用法（任意 cwd 均可，内部以本包所在仓根为 subprocess cwd）：
  python -m md_cg.run_tests                  # 全量（存在的组）
  python -m md_cg.run_tests md_cg            # 只跑一组：md_cg | compiler | swarm | scripts | hive
  python -m md_cg.run_tests -k p44           # 按关键字过滤模块名
  python -m md_cg.run_tests --jobs 1         # 串行（默认并发 4）
  python -m md_cg.run_tests --list           # 只列出目标不执行

退出码：全部通过 0，存在失败 1（可直接接 CI / 提交前门禁）。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import glob
import os
import subprocess
import sys
import tempfile
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: 逐用例日志目录（重定向目标；默认临时目录，避免污染仓）
_LOG_DIR = os.environ.get("MDCG_TESTLOG_DIR") or os.path.join(
    tempfile.gettempdir(), "md_cg_testlogs")


def _discover():
    """返回 [(组名, 显示名, argv 候选列表)]；argv 依次尝试直到成功启动。"""
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
    # scripts/ 不是包（无 __init__.py）→ 只能直跑；脚本内自带 sys.path 注入
    for f in sorted(glob.glob(os.path.join(_REPO, "scripts", "test_*.py"))):
        stem = os.path.splitext(os.path.basename(f))[0]
        out.append(("scripts", f"scripts.{stem}",
                    [[sys.executable, "-X", "utf8", f]]))
    # hive/ 是包 → -m 优先；测试内用 importlib 直载，故回退直跑同样可用。
    for f in sorted(glob.glob(os.path.join(_REPO, "hive", "test_*.py"))):
        stem = os.path.splitext(os.path.basename(f))[0]
        out.append(("hive", f"hive.{stem}",
                    [[sys.executable, "-X", "utf8", "-m", f"hive.{stem}"],
                     [sys.executable, "-X", "utf8", f]]))
    return out


# 生效条件：name/argvs/timeout 就绪时逐个 argv 尝试运行（cwd=_REPO，stdout+stderr 重定向到 _LOG_DIR/<name>.log，无管道），返回 (name, 是否通过, 日志尾部最多 800 字符)；超时返回 (name, False, "超时(>Ns)")；首个成功启动（非「No module named」回退）的尝试决定结果。
def _run_one(name, argvs, timeout):
    """跑一个用例；输出**重定向到文件**（不用管道——沙箱禁 CreatePipe）。"""
    os.makedirs(_LOG_DIR, exist_ok=True)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    last = ""
    for argv in argvs:                    # -m 优先；No module named 时回退直跑
        log = os.path.join(_LOG_DIR, name.replace(".", "_") + ".log")
        t0 = time.time()
        try:
            with open(log, "wb") as fh:
                p = subprocess.run(argv, cwd=_REPO, stdout=fh,
                                   stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, env=env,
                                   shell=False, timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            return name, False, f"超时（>{timeout}s）—— 日志 {log}"
        except OSError as exc:
            return name, False, f"无法启动子进程：{exc!r}（日志 {log}）"
        try:
            with open(log, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            text = ""
        if rc != 0 and "No module named" in text and len(argvs) > 1:
            last = text[-300:]
            continue
        tail = text[-800:]
        return name, rc == 0, f"[{time.time() - t0:.1f}s] " + tail
    return name, False, last


def _dep_db():
    p = os.path.join(_REPO, "md_cg", "whitebox_kb", "wisdom",
                     "wisdom-book-cloud.db")
    return (None if os.path.exists(p)
            else "依赖白箱库 whitebox_kb/wisdom/wisdom-book-cloud.db"
                 "（.gitignore 忽略，需本地生成）")


def _dep_mdroot():
    """md 语料真源依赖：目录存在**且含 .md** 才算就绪。

    空壳目录不算（v14 缺陷 F：旁路执行造出的空 `_md_cg_wisdom_graph/` 曾把
    runner 从 SKIP 翻成 FAIL）——判据必须与 test_md_access_parity 同口径。
    """
    p = os.path.join(_REPO, "_md_cg_wisdom_graph")
    if not os.path.isdir(p):
        return ("依赖 md 语料真源 _md_cg_wisdom_graph/（.gitignore 忽略，"
                "组 D 需本地真源）")
    for _dirpath, _dirs, names in os.walk(p):
        if any(n.endswith(".md") for n in names):
            return None
    return ("依赖 md 语料真源 _md_cg_wisdom_graph/（目录在但零 .md："
            "空壳目录不算依赖就绪）")


# 裸 clone 环境 SKIP 探测（2026-09-14 外部复核建议 #3）：
# 依赖 gitignored 本地数据或特定平台的测试，依赖缺失时标 SKIP（附原因）
# 不计入失败——避免裸 clone 用户第一眼看到虚假 FAIL（复核实测 83/87 根因）。
_SKIPS = {
    "md_cg.test_p44_md_whitebox": _dep_db,
    "md_cg.test_md_access_parity": _dep_db,
    "md_cg.test_wisdom_md_store": _dep_mdroot,
    "swarm.tests.test_swarm_fault": (
        lambda: None if os.name == "nt"
        else "Windows 专用（powershell/taskkill）"),
}


# 生效条件：argv 就绪时解析组/-k/--jobs/--timeout/--list 参数，按 _discover() 与 _SKIPS 过滤后并发执行，打印 PASS/FAIL/SKIP 与汇总；全部通过返回 0、有失败返回 1、--list 恒返回 0。
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m md_cg.run_tests",
        description="灵枢测试入口（python -m 约定；输出重定向，沙箱安全）")
    # 注：不用 argparse choices——部分 Python 版本对 nargs="*" 无值时
    # 以空列表过 choices 校验会误报 invalid choice（bpo-27227 老行为）。
    ap.add_argument("group", nargs="*", default=None,
                    help="只跑指定组，可多选：md_cg compiler swarm scripts hive"
                         "（缺省全量）")
    ap.add_argument("-k", default="", help="按关键字过滤模块名")
    ap.add_argument("--jobs", type=int, default=4, help="并发数（默认 4）")
    ap.add_argument("--timeout", type=int, default=900, help="单测超时秒数")
    ap.add_argument("--list", action="store_true", help="只列出目标不执行")
    args = ap.parse_args(argv)

    _known = ("md_cg", "compiler", "swarm", "scripts", "hive")
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

    # SKIP 探测：依赖缺失/平台不符的测试不执行（外部复核建议 #3，裸 clone 友好）
    skipped, runnable = [], []
    for g, n, a in targets:
        probe = _SKIPS.get(n)
        reason = probe() if probe else None
        if reason:
            skipped.append((n, reason))
            print(f"SKIP  {n}  （{reason}）", flush=True)
        else:
            runnable.append((g, n, a))

    bad = []
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, args.jobs)) as ex:
        futs = {ex.submit(_run_one, n, a, args.timeout): (g, n)
                for g, n, a in runnable}
        for fu in concurrent.futures.as_completed(futs):
            name, ok, tail = fu.result()
            print(("PASS  " if ok else "FAIL  ") + name, flush=True)
            if not ok:
                bad.append(name)
                for ln in tail.splitlines()[-6:]:
                    print("      " + ln, flush=True)

    print(f"\n===== SUMMARY {len(runnable) - len(bad)}/{len(runnable)} 通过，"
          f"{len(skipped)} 跳过（依赖缺失/平台不符） =====")
    print(f"逐用例日志：{_LOG_DIR}")
    if bad:
        print("失败：" + ", ".join(bad))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
