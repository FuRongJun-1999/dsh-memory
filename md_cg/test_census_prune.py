# -*- coding: utf-8 -*-
"""PR #15 census 归档区剪枝探针（脚本式，exit code 定成败）。

用法：python -X utf8 -m md_cg.test_census_prune
覆盖：
- ARCHIVE_DIRS 五个目录整体剪枝（含 _protected_history/<id>/<ts>.md 两层下钻）
- _protected_history_* 前缀目录剪枝
- 普通子目录不误伤
- 无 frontmatter 的散落 md 仍被跳过（既有语义保持）
- 真实库（data/mdcg）上活跃数不再被墓碑/快照稀释
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import census  # noqa: E402

FM = "---\nid: {nid}\nlayer: knowledge\n---\n正文\n"
passed = 0


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        print("  [FAIL] " + name + "  " + detail)


def main():
    root = tempfile.mkdtemp(prefix="census_prune_")
    nodes = {
        # (相对路径, 是否活跃)
        ("act_root.md", True),
        ("sub", "act_sub.md", True),          # 普通子目录不误伤
        ("trash", "t1.md", False),
        ("_protected_history", "n1", "20260101_000000.md", False),  # 两层下钻
        ("_protected", "p1.md", False),
        ("_index_log", "i1.md", False),
        ("hippocampus", "h1.md", False),
        ("_protected_history_extra", "x.md", False),  # 前缀分支
        ("note.md", None),                    # 无 frontmatter 散落文档 → 跳过
    }
    for n in nodes:
        parts = [p for p in n if p is not True and p is not False and p is not None]
        active = n[-1] is True
        rel = os.path.join(*parts) if parts else "note.md"
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("" if n[-1] is None else FM.format(nid=os.path.splitext(parts[-1])[0]))
    rows = census.load(root)
    ids = sorted(r[0] for r in rows)
    check("仅活跃节点入普查（2 个）", ids == ["act_root", "act_sub"], str(ids))
    for bad in ("t1", "p1", "i1", "h1", "x", "20260101_000000"):
        check(f"归档区 {bad} 被剪枝", bad not in ids, str(ids))

    # 真实库对比：PR 版活跃数 vs 全遍历数（含归档区）
    real = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "mdcg")
    if os.path.isdir(real):
        n_active = len(census.load(real))
        n_all = sum(1 for dp, _ds, fs in os.walk(real) for f in fs
                    if f.endswith(".md"))
        print(f"\n  真实库 {real}")
        print(f"  PR 版活跃节点 {n_active} / 全遍历 {n_all}"
              f"（归档区剪掉 {n_all - n_active}）")
        check("真实库剪枝后不再被墓碑稀释", n_active < n_all,
              f"{n_active} vs {n_all}")

    print(f"\ntest_census_prune: {passed} 断言通过")
    return 0 if passed >= 7 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
