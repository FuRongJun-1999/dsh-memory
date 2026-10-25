# -*- coding: utf-8 -*-
"""判据面清单生成器（批次8b，互验定稿 §7.6「机器可读清单未定义」缺口收口）。

**本模块是 `scripts/judgment_manifest.py` 的包内等价实现**（2026-09-24 修复）：
出货包 `files` 不含 `scripts/`，而 `md_cg/interop.py` 原先以子进程调用该脚本
——安装态必抛 FileNotFoundError，且受限宿主（DSH 文件沙箱）禁子进程管道
（CreatePipe → WinError 5）。判据面是**运行时依赖**，故搬进包内。

⚠ **判据面构成必须与源码树逐条同源**（A3 的硬约束）：验证器侧（hive runner /
hive serve 心跳）用的是 `scripts/judgment_manifest.py`，两侧 PATTERNS 一旦
不同，digest 必不相等 → A3 红。因此：
  ① 本文件的 PATTERNS / 排序 / digest 算法与 `scripts/` 版**逐字同步**
     （含 issue #36 的组构成；组数以 `PATTERNS` 长度为准，当前 **10 组**
     = 7 组通配 + `test/` 三条精确名。C37/2026-10-25：此处原写作「7 组」的
     中文数字形式，与 `len(PATTERNS)==10` 相悖，已按实测改正）；
  ② `md_cg/interop.py` **优先加载源码树的 `scripts/judgment_manifest.py`**，
     只有它不在（安装态）才回落到本模块。

判据面 = 验证实例 A3 断言（判据面文件集合 hash==冻结值）的覆盖对象。
候选面 = hive/src/**（被验证的源码）。
物理分离成立后：候选弱化判据面任一文件 → 判据面 hash 不变、候选面变化被
判据面覆盖 → 弱化必红（zcode 外评 break#3 的结构性收口）。

用法（包内入口）：
  python -m md_cg.judgment_manifest                    # 输出 JSON（清单+sha256+分组计数）
  python -m md_cg.judgment_manifest --digest           # 仅输出组合指纹（纯值，A3 输入）
  python -m md_cg.judgment_manifest --check-coverage   # 覆盖完备性守卫（issue #36）
  python -m md_cg.judgment_manifest --verify <冻结的manifest.json>

清单组成（§7.6 定稿；issue #36 补齐「跑什么=冻结什么」同源）：
  hive/tests/*.rs         Rust 侧承重断言（judgment_surface.rs）
  hive/test_*.py          hive Python 测试套件
  scripts/run_tests.py    全量测试入口
  scripts/test_*.py       scripts 侧测试
  md_cg/test_*.py         Python 侧测试套件
  compiler/tests/*.py     compiler 测试
  swarm/tests/*.py        swarm 测试
  test/{hive_exec,hive_wm}_test.py   test/ 侧逐文件裁决可收件（A6；精确名冻结）
  test/chaos_injection/run_all.py   chaos 套件入口（批次99 补收；精确名冻结）

安装态（出货包）只有 `md_cg/test_*.py` 一组可得——其余组命中数为 0，
`missing_patterns` 显式随清单与冻结凭证落盘（不静默少算）；A3 两侧必须在
同一种布局下取值，否则 digest 天然不等（见 `md_cg/interop.py` 的说明）。
"""
import hashlib
import json
import os
import sys

# 包内位置 = <插件根>/md_cg/judgment_manifest.py → 上溯两级回到插件根
# （与 scripts/ 版的 os.path.dirname(dirname(__file__)) 同值）。
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATTERNS = [
    ("hive/tests", "*.rs"),
    ("hive", "test_*.py"),
    ("scripts", "run_tests.py"),
    ("scripts", "test_*.py"),
    ("md_cg", "test_*.py"),
    ("compiler/tests", "*.py"),
    ("swarm/tests", "*.py"),
    # test/（A6，2026-10-05）：与 scripts/ 版逐字同步——test/ 侧逐文件裁决可收件的
    # 精确名冻结（未过裁决的件不进判据面）。批次99 补收：chaos 套件的陈旧登记已
    # 同步（FI-M04 读码代理断言改 AST 语义判据 + 去锁定点变异自证）。
    ("test", "hive_exec_test.py"),
    ("test", "hive_wm_test.py"),
    ("test/chaos_injection", "run_all.py"),
]


# 生效条件：无必需形参；遍历 PATTERNS 逐组取 HERE 下子目录中匹配的文件（目录不存在或零命中则 groups 计数为 0 且该组进 missing_patterns），按相对路径排序后返回 {"algorithm","groups","files","missing_patterns"}。
def collect() -> dict:
    """收集判据面清单（分组计数 + 缺失组显式上报）。"""
    files = []
    groups = {}
    for sub, pat in PATTERNS:
        base = os.path.join(HERE, sub)
        n = 0
        if os.path.isdir(base):
            import fnmatch
            for name in sorted(os.listdir(base)):
                full = os.path.join(base, name)
                if not os.path.isfile(full):
                    continue
                if fnmatch.fnmatch(name, pat):
                    rel = os.path.relpath(full, HERE).replace("\\", "/")
                    files.append(rel)
                    n += 1
        groups[f"{sub}/{pat}"] = n
    files.sort()
    out = {"algorithm": "sha256", "groups": groups, "files": [],
           # 零命中组（目录不存在、或目录在但空）：安装态/裸 clone 的判据面不完整，
           # 必须随清单可见——否则「少算」会被当成「判据面完好」。
           "missing_patterns": sorted(k for k, v in groups.items() if not v)}
    for rel in files:
        with open(os.path.join(HERE, rel), "rb") as fh:
            h = hashlib.sha256(fh.read()).hexdigest()
        out["files"].append({"path": rel, "sha256": h})
    return out


class _Unverifiable:
    """「无法核对」的显式哨兵（E43/2026-10-25）。

    此前安装态 `coverage_gap()` 返回 `None`：它是假值，`if gap:` / `if not gap:`
    这类写法会把「没核对」读成「没有缺口 = 通过」——正是本模块自己在
    docstring 里禁止的事（「不得当作通过」）。哨兵把这句纪律变成机械约束：
    对它做布尔求值直接抛 TypeError，调用方只能 `is UNVERIFIABLE` 显式分支。
    """

    __slots__ = ()

    def __bool__(self):
        raise TypeError(
            "coverage_gap() 返回 UNVERIFIABLE（安装态无法核对）：它既不是通过也"
            "不是失败，不能参与布尔判断——请用 `gap is UNVERIFIABLE` 显式分支")

    def __repr__(self):
        return "UNVERIFIABLE"


UNVERIFIABLE = _Unverifiable()


# 生效条件：scripts/run_tests.py 在（源码树）时以 _discovered_files() 为唯一执行清单真源，逐文件判定是否落在冻结 PATTERNS 覆盖域内（域外=collect 永不收=漏冻）返回缺失列表（空列表=通过）；rt 不在（安装态）时返回 UNVERIFIABLE 哨兵——它不可布尔求值，调用方须显式 `is UNVERIFIABLE` 分支并如实说明「无法核对」。批次 23 域覆盖语义（与 scripts 版同口径，v20 D-36-1：集合差形式在 collect 超集下恒空=假牙）。
def coverage_gap(manifest: dict):
    """覆盖完备性守卫（issue #36）：「跑什么」⊆「冻结什么」。

    批次 23 起与 `scripts/` 版同口径——**域覆盖判定**：每个 run_tests
    会跑的文件必须落在冻结 PATTERNS 的覆盖域内（域外 = collect 永不收
    → 不进判据指纹 → 漏冻）。v20 D-36-1：集合差形式在 collect 超集下
    恒空（假牙）。安装态（run_tests 不在）返回 UNVERIFIABLE 哨兵（不是
    None、不是 []）——调用方须如实说明「无法核对」，不得当作通过。
    """
    import fnmatch
    import importlib.util
    rt_path = os.path.join(HERE, "scripts", "run_tests.py")
    if not os.path.isfile(rt_path):
        return UNVERIFIABLE
    spec = importlib.util.spec_from_file_location("run_tests", rt_path)
    rt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rt)
    gap = []
    for rel in rt._discovered_files():
        rel = str(rel).replace("\\", "/")
        if not any(fnmatch.fnmatch(rel, f"{sub}/{pat}")
                   for sub, pat in PATTERNS):
            gap.append(rel)
    return sorted(gap)


# 生效条件：manifest 含 "files"（每项 path/sha256）时返回 sha256("path:hash\n" 按清单序拼接)；files 为空时返回空串拼接结果（sha256 of ""）。
def digest(manifest: dict) -> str:
    """判据面组合指纹（批次10，A3/A2 的输入）：sha256("path:hash\\n" 按清单序拼接)。

    服务端（hive serve 心跳 fingerprint）与验证器共用同一算法——清单变更
    （新增/删除/任一文件改动）必改 digest，缺一不可。
    """
    lines = "".join(f"{f['path']}:{f['sha256']}\n" for f in manifest["files"])
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


# 生效条件：argv 为空时打印全量清单 JSON 并返回 0；--digest 打印指纹返回 0；--check-coverage 在源码树缺 run_tests.py 时打印 UNVERIFIABLE 返回 2、否则按缺口 PASS/FAIL 返回 0/1；--verify <path> 比对冻结清单 PASS/FAIL 返回 0/1。
def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    manifest = collect()
    if argv[:1] == ["--digest"]:
        print(digest(manifest))
        return 0
    if argv[:1] == ["--check-coverage"]:
        gap = coverage_gap(manifest)
        if gap is UNVERIFIABLE:
            print(json.dumps({
                "verdict": "UNVERIFIABLE",
                "reason": "scripts/run_tests.py 不在（安装态）——覆盖完备性守卫"
                          "属源码树门禁，本环境无法核对（不冒充通过）",
                "groups": manifest["groups"],
                "file_count": len(manifest["files"]),
            }, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps({
            "verdict": "PASS" if not gap else "FAIL",
            "missing": gap,
            "groups": manifest["groups"],
            "file_count": len(manifest["files"]),
        }, ensure_ascii=False, indent=2))
        return 0 if not gap else 1
    if argv[:1] == ["--verify"]:
        if len(argv) < 2:
            print("用法：--verify <冻结的manifest.json>", file=sys.stderr)
            return 2
        with open(argv[1], encoding="utf-8") as fh:
            frozen = json.load(fh)
        cur = {f["path"]: f["sha256"] for f in manifest["files"]}
        froz = {f["path"]: f["sha256"] for f in frozen["files"]}
        added = sorted(set(cur) - set(froz))
        removed = sorted(set(froz) - set(cur))
        changed = sorted(p for p in set(cur) & set(froz) if cur[p] != froz[p])
        ok = not (added or removed or changed)
        print(json.dumps({
            "verdict": "PASS" if ok else "FAIL",
            "added": added, "removed": removed, "changed": changed,
        }, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
