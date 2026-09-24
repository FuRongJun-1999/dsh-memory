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
  scripts/    test_*.py（脚本式，非包无 __init__）→ 直跑 python scripts/<name>.py
  hive/       test_*.py（包内，脚本式）→ python -m hive.<name>

用法（任意 cwd 均可，内部以仓库根为 subprocess cwd）：
  python scripts/run_tests.py                  # 全量
  python scripts/run_tests.py md_cg            # 只跑一组：md_cg | compiler | swarm | scripts | hive
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


# 生效条件：以模块级常量 _REPO 为根，返回全量套件实际执行的测试文件路径列表（相对 _REPO 的正斜杠路径）——md_cg/test_*.py、compiler 与 swarm 下 tests/*.py（basename 以 "_" 开头者跳过）、scripts/test_*.py、hive/test_*.py，按组序拼接。
def _discovered_files():
    """全量套件实际执行的测试文件（判据面覆盖完备性核对的单一切面）。

    「跑什么」的唯一真源：judgment_manifest 的覆盖守卫从这里取执行清单，
    与判据面清单比对——两套清单各自维护必然漂移（issue #36 的根因形态）。
    """
    import glob
    files = []
    files += sorted(glob.glob(os.path.join(_REPO, "md_cg", "test_*.py")))
    for pkg in ("compiler", "swarm"):
        for f in sorted(glob.glob(os.path.join(_REPO, pkg, "tests", "*.py"))):
            if os.path.basename(f).startswith("_"):
                continue
            files.append(f)
    files += sorted(glob.glob(os.path.join(_REPO, "scripts", "test_*.py")))
    files += sorted(glob.glob(os.path.join(_REPO, "hive", "test_*.py")))
    return [os.path.relpath(f, _REPO).replace("\\", "/") for f in files]


# 生效条件：基于 _discovered_files() 的文件列表按目录前缀分派命令形态（md_cg/ 与 hive/ 是包 -m 优先、compiler|swarm/tests/ 双候选、scripts/ 非包只直跑），返回 (组名, 显示名, argv 候选列表) 列表。
def _discover():
    """返回 [(组名, 显示名, argv)]；argv 为候选列表（依次尝试直到成功启动）。"""
    out = []
    for rel in _discovered_files():
        f = os.path.join(_REPO, rel)
        parts = rel.split("/")
        stem = os.path.splitext(parts[-1])[0]
        if rel.startswith("md_cg/"):
            out.append(("md_cg", f"md_cg.{stem}",
                        [[sys.executable, "-X", "utf8", "-m", f"md_cg.{stem}"]]))
        elif rel.startswith(("compiler/", "swarm/")):
            pkg = parts[0]
            out.append((pkg, f"{pkg}.tests.{stem}",
                        [[sys.executable, "-X", "utf8", "-m",
                          f"{pkg}.tests.{stem}"],
                         [sys.executable, "-X", "utf8", f]]))
        elif rel.startswith("scripts/"):
            # scripts/ 不是包（无 __init__.py）→ 只能直跑；脚本内自带 sys.path 注入
            out.append(("scripts", f"scripts.{stem}",
                        [[sys.executable, "-X", "utf8", f]]))
        else:
            # hive/ 是包（有 __init__.py，与 md_cg 同形）→ -m 优先；测试内用
            # importlib 直载 exec.py/wm.py，-m 下 __file__ 正常，直跑同样可用。
            out.append(("hive", f"hive.{stem}",
                        [[sys.executable, "-X", "utf8", "-m", f"hive.{stem}"],
                         [sys.executable, "-X", "utf8", f]]))
    return out


# 生效条件：给定 name、候选命令列表 argvs、超时秒数 timeout，逐个 subprocess.run（cwd 为模块级常量 _REPO，env 在 os.environ 基础上覆盖 PYTHONUTF8=1/PYTHONIOENCODING=utf-8，shell=False，encoding="utf-8"/errors="replace"）：抛 TimeoutExpired 即返回 (name, False, f"超时（>{timeout}s）")；若 returncode!=0 且 stderr 含 "No module named" 且 len(argvs)>1 则记下该 stderr 末 300 字符继续下一候选，否则返回 (name, returncode==0, stdout+stderr 拼接后末 800 字符)；所有候选都命中回退条件时返回 (name, False, 最后记下的片段)；
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


# 生效条件：当模块级常量 _REPO 下 md_cg/whitebox_kb/wisdom/wisdom-book-cloud.db 存在时返回 None，不存在时返回依赖缺失说明字符串；
def _dep_db():
    p = os.path.join(_REPO, "md_cg", "whitebox_kb", "wisdom",
                     "wisdom-book-cloud.db")
    return (None if os.path.exists(p)
            else "依赖白箱库 whitebox_kb/wisdom/wisdom-book-cloud.db"
                 "（.gitignore 忽略，需本地生成）")


# 生效条件：当模块级常量 _REPO 下 _md_cg_wisdom_graph 为目录、且其下（递归）至少有一个 .md 文件时返回 None；目录缺失或为无 .md 的空壳目录时返回依赖缺失说明字符串；
def _dep_mdroot():
    p = os.path.join(_REPO, "_md_cg_wisdom_graph")
    if not os.path.isdir(p):
        return ("依赖 md 语料真源 _md_cg_wisdom_graph/（.gitignore 忽略，"
                "组 D 需本地真源）")
    for _dp, _dn, fs in os.walk(p):
        if any(str(f).endswith(".md") for f in fs):
            return None
    # **空壳不算就绪**（2026-09-20 v14 缺陷 F）：兄弟测试一旦经
    # `MdCGOS(root)`（内部 makedirs）走一遭，就在仓根留下空目录——只判
    # `isdir` 会把「本该 SKIP」的目标变成 FAIL，且失败形态随机（取决于谁先跑）。
    return ("依赖 md 语料真源 _md_cg_wisdom_graph/ 为**空壳**（目录在但无 .md）"
            "——需本地生成；空壳多为兄弟测试残留，不算就绪")


# 生效条件：_dep_db() 与 _dep_mdroot() 均返回 None 时返回 None，否则返回二者中首个非空说明（两依赖都需在位）；
def _dep_db_and_mdroot():
    """同时依赖白箱库与 md 语料的测试（如 P44 / P45 对拍）用组合探测。"""
    return _dep_db() or _dep_mdroot()


# 裸 clone 环境 SKIP 探测（2026-09-14 外部复核建议 #3）：
# 依赖 gitignored 本地数据或特定平台的测试，依赖缺失时标 SKIP（附原因）
# 不计入失败——避免裸 clone 用户第一眼看到虚假 FAIL（复核实测 83/87 根因）。
_SKIPS = {
    "md_cg.test_p44_md_whitebox": _dep_db_and_mdroot,
    "md_cg.test_md_access_parity": _dep_db_and_mdroot,
    "md_cg.test_wisdom_md_store": _dep_mdroot,
    "swarm.tests.test_swarm_fault": (
        lambda: None if os.name == "nt"
        else "Windows 专用（powershell/taskkill）"),
}

# 仅串行（批次 20，issue #30①）：负载敏感的性能阈值断言在并行争抢下会
# 假红（bench_swarm_scale 的吞吐>500/摊薄<3× 在 --jobs 4 实测随机失败）
# ——并行跑自动 SKIP（附原因），串行（--jobs 1）正常执行。性能基准照旧
# 有跑（串行全量含它），只是不与其它测试抢 CPU。
_SERIAL_ONLY = {
    "swarm.tests.bench_swarm_scale",
    # 同形态（2026-09-25 全量实测）：加速比 > 2 宽松下限在 --jobs 4 争抢下
    # 1.91× 假红（单跑 2.96×），与 bench_swarm_scale 同为负载敏感吞吐断言。
    "swarm.tests.bench_swarm_parallel",
}


# 生效条件：解析命令行（位置参数 group 为 nargs="*"、default=None，-k 默认 ""，--jobs 默认 4，--timeout 默认 900，--list 为 store_true）后，若 args.group 里有不在 ("md_cg","compiler","swarm","scripts","hive") 中的组名则 ap.error 报错退出（args.group 为 None 或空列表时该检查不触发）；groups 取 set(args.group) 或（其为假值时）全部五组；targets 由 _discover() 按 groups 过滤且 args.k 为假值或出现在显示名中；args.list 为真时打印组名与显示名及总数并返回 0；否则先按 _SKIPS 探测跳过有原因的目标，再以 max(1, args.jobs) 个线程跑 _run_one(name, a, args.timeout)，无失败打印汇总返回 0，有失败打印失败名单返回 1；
def main():
    ap = argparse.ArgumentParser(description="灵枢全仓测试入口（python -m 约定）")
    # 注：不用 argparse choices——部分 Python 版本对 nargs="*" 无值时
    # 以空列表过 choices 校验会误报 invalid choice（bpo-27227 老行为）。
    ap.add_argument("group", nargs="*", default=None,
                    help="只跑指定组，可多选：md_cg compiler swarm scripts hive"
                         "（缺省全量）")
    ap.add_argument("-k", default="", help="按关键字过滤模块名")
    ap.add_argument("--jobs", type=int, default=4, help="并发数（默认 4）")
    ap.add_argument("--timeout", type=int, default=900, help="单测超时秒数")
    ap.add_argument("--list", action="store_true", help="只列出目标不执行")
    args = ap.parse_args()

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
        if n in _SERIAL_ONLY and max(1, args.jobs) > 1:
            reason = "负载敏感（性能阈值断言），并行争抢会假红——仅串行执行"
            skipped.append((n, reason))
            print(f"SKIP  {n}  （{reason}）", flush=True)
            continue
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
    if bad:
        print("失败：" + ", ".join(bad))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
