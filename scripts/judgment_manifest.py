# -*- coding: utf-8 -*-
"""判据面清单生成器（批次8b，互验定稿 §7.6「机器可读清单未定义」缺口收口）。

判据面 = 验证实例 A3 断言（判据面文件集合 hash==冻结值）的覆盖对象。
候选面 = hive/src/**（被验证的源码）。
物理分离成立后：候选弱化判据面任一文件 → 判据面 hash 不变、候选面变化被
判据面覆盖 → 弱化必红（zcode 外评 break#3 的结构性收口）。

用法：
  python scripts/judgment_manifest.py            # 输出 JSON（清单+sha256+分组计数）
  python scripts/judgment_manifest.py --digest   # 仅输出组合指纹（纯值，A3 输入）
  python scripts/judgment_manifest.py --check-coverage
                                                 # 覆盖完备性守卫（issue #36）：
                                                 # run_tests 实际执行的每个测试
                                                 # 文件必须在判据面内，缺谁报谁
  python scripts/judgment_manifest.py --verify <冻结的manifest.json>
                                                 # 比对当前盘面与冻结值，输出 PASS/FAIL

清单组成（§7.6 示例的机器可读定稿；issue #36 补齐「跑什么=冻结什么」同源）：
  hive/tests/*.rs         Rust 侧承重断言（judgment_surface.rs）
  hive/test_*.py          hive Python 测试套件（6 文件/88KB，#36 前漏冻）
  scripts/run_tests.py    全量测试入口
  scripts/test_*.py       scripts 侧测试（#36 前漏冻）
  md_cg/test_*.py         Python 侧测试套件
  compiler/tests/*.py     compiler 测试（#36 前漏冻）
  swarm/tests/*.py        swarm 测试（#36 前漏冻）
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATTERNS = [
    ("hive/tests", "*.rs"),
    ("hive", "test_*.py"),
    ("scripts", "run_tests.py"),
    ("scripts", "test_*.py"),
    ("md_cg", "test_*.py"),
    ("compiler/tests", "*.py"),
    ("swarm/tests", "*.py"),
]


def collect():
    files = []
    groups = {}
    for sub, pat in PATTERNS:
        base = os.path.join(HERE, sub)
        n = 0
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                full = os.path.join(base, name)
                if not os.path.isfile(full):
                    continue
                import fnmatch
                if fnmatch.fnmatch(name, pat):
                    rel = os.path.relpath(full, HERE).replace("\\", "/")
                    files.append(rel)
                    n += 1
        groups[f"{sub}/{pat}"] = n
    files.sort()
    out = {"algorithm": "sha256", "groups": groups, "files": [],
           # 零命中组（目录不存在、或目录在但空）：安装态/裸 clone 的判据面不完整，
           # 必须随清单可见——否则「少算」会被当成「判据面完好」。
           # （与包内 md_cg/judgment_manifest.py 同形；digest 只用 files，加键不改指纹。）
           "missing_patterns": sorted(k for k, v in groups.items() if not v)}
    for rel in files:
        h = hashlib.sha256(open(os.path.join(HERE, rel), "rb").read()).hexdigest()
        out["files"].append({"path": rel, "sha256": h})
    return out


def coverage_gap(discovered_files, patterns=None) -> list:
    """覆盖完备性守卫（issue #36；v20 D-36-1 重构）：「跑什么」⊆「冻结什么」。

    准确语义 = 每个 run_tests **会跑的文件**是否落在冻结 PATTERNS 的
    **覆盖域**内——域外文件 collect 永不收它 → 不进判据指纹 → 漏冻。

    v20 D-36-1 旧实现缺陷：frozen 用**现算清单**与 discovered 做集合差——
    collect 的 PATTERNS 是发现规则的超集，差集结构上恒空（守卫永远 PASS，
    对「发现规则与 PATTERNS 漂移」失效）。新实现直接对发现规则域判定：
    run_tests 新增发现目录/模式而 PATTERNS 未跟 → 必报；域内新增文件
    （collect 现算会收、digest 自动含它）正确地不报。
    """
    import fnmatch
    pats = patterns if patterns is not None else PATTERNS
    gap = []
    for rel in discovered_files:
        rel = str(rel).replace("\\", "/")
        if not any(fnmatch.fnmatch(rel, f"{sub}/{pat}") for sub, pat in pats):
            gap.append(rel)
    return sorted(gap)


def digest(manifest: dict) -> str:
    """判据面组合指纹（批次10，A3/A2 的输入）：sha256("path:hash\n" 按清单序拼接)。

    服务端（hive serve 心跳 fingerprint）与验证器共用同一算法——清单变更
    （新增/删除/任一文件改动）必改 digest，缺一不可。
    """
    lines = "".join(f"{f['path']}:{f['sha256']}\n" for f in manifest["files"])
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def main():
    manifest = collect()
    if len(sys.argv) >= 2 and sys.argv[1] == "--digest":
        print(digest(manifest))
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "--check-coverage":
        # 「跑什么」真源现场加载（批次 23 D-36-1：不再把现算 manifest 喂给
        # coverage_gap——旧接线差集恒空，守卫永远 PASS）
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "run_tests", os.path.join(HERE, "scripts", "run_tests.py"))
        rt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rt)
        gap = coverage_gap(rt._discovered_files())
        print(json.dumps({
            "verdict": "PASS" if not gap else "FAIL",
            "missing": gap,
            "coverage_domain": [f"{sub}/{pat}" for sub, pat in PATTERNS],
            "groups": manifest["groups"],
            "file_count": len(manifest["files"]),
        }, ensure_ascii=False, indent=2))
        return 0 if not gap else 1
    if len(sys.argv) >= 3 and sys.argv[1] == "--verify":
        frozen = json.load(open(sys.argv[2], encoding="utf-8"))
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
