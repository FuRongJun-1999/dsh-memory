# -*- coding: utf-8 -*-
"""判据面清单生成器（批次8b，互验定稿 §7.6「机器可读清单未定义」缺口收口）。

判据面 = 验证实例 A3 断言（判据面文件集合 hash==冻结值）的覆盖对象。
候选面 = hive/src/**（被验证的源码）。
物理分离成立后：候选弱化判据面任一文件 → 判据面 hash 不变、候选面变化被
判据面覆盖 → 弱化必红（zcode 外评 break#3 的结构性收口）。

用法：
  python scripts/judgment_manifest.py            # 输出 JSON（清单+sha256）
  python scripts/judgment_manifest.py --verify <冻结的manifest.json>
                                                 # 比对当前盘面与冻结值，输出 PASS/FAIL

清单组成（§7.6 示例的机器可读定稿）：
  hive/tests/**            集成测试（判据面主体，批次8b 起）
  scripts/run_tests.py     全量测试入口
  md_cg/test_*.py          Python 侧测试套件
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATTERNS = [
    ("hive/tests", "*.rs"),
    ("scripts", "run_tests.py"),
    ("md_cg", "test_*.py"),
]


def collect():
    files = []
    for sub, pat in PATTERNS:
        base = os.path.join(HERE, sub)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            if not os.path.isfile(full):
                continue
            import fnmatch
            if fnmatch.fnmatch(name, pat):
                rel = os.path.relpath(full, HERE).replace("\\", "/")
                files.append(rel)
    files.sort()
    out = {"algorithm": "sha256", "files": []}
    for rel in files:
        h = hashlib.sha256(open(os.path.join(HERE, rel), "rb").read()).hexdigest()
        out["files"].append({"path": rel, "sha256": h})
    return out


def main():
    manifest = collect()
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
