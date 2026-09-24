# -*- coding: utf-8 -*-
"""test_migrate_restricted —— private→restricted 迁移字段保全守卫（V22）

背景：migrate_restricted.py --apply 曾只传 content/layer/sensitivity/
override 调 cg.add(override=True)——add 是**全量重建 frontmatter**
（mdcg.py add docstring 自认），存量节点的 tags/condition_space/
importance/confidence/edges/non_applicable_conditions/created_at/
protected/protection_reason 全部被清空或重置（数据丢失；protect 的
override 快照仅覆盖受保护节点且需人工找回）。本守卫把「迁移只改
sensitivity，其余字段逐项保全」固化为断言。

运行：python -X utf8 scripts/test_migrate_restricted.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:200])


def main():
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal

    root = tempfile.mkdtemp(prefix="mdcg_migrate_guard_")
    try:
        pri = dict(actor="migrate-restricted", clearance="secret",
                   can_write=True, can_admin=True, role="designer",
                   auth_mode="test")
        cg = MdCGSecure(root, principal=Principal(**pri))
        nid = "guard_private_node"
        cg.add(nid, "存量 private 节点正文（迁移守卫）",
               layer="knowledge", sensitivity="private",
               tags=["incident", "rollback"],
               condition_space={"env": "prod", "region": "cn"},
               importance=0.9, confidence=0.8,
               edges=[["node_x", "ref"]],
               non_applicable_conditions=["演练环境"],
               protected=True, protection_reason="复现保护标记")
        cg.flush()
        before = cg.get(nid)
        check("BEFORE: 源 private 节点可读（信封可解）", bool(before))
        if not before:
            return 1
        bfm = before["frontmatter"]

        spec = importlib.util.spec_from_file_location(
            "migrate_restricted",
            os.path.join(HERE, "scripts", "migrate_restricted.py"))
        mr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mr)
        rc = mr.main(["--root", root, "--apply", "--ids", nid])
        check("迁移脚本退出码 0", rc == 0, rc)

        cg2 = MdCGSecure(root, principal=Principal(**pri))
        after = cg2.get(nid)
        check("AFTER: 迁移后节点可读", bool(after))
        if not after:
            return 1
        afm = after["frontmatter"]

        print("[1] 迁移目的达成（保全不得破坏迁移本身）")
        check("sensitivity: private → restricted",
              afm.get("sensitivity") == "restricted", afm.get("sensitivity"))
        # 注：nodefile 覆写落盘会给正文补尾换行（既有口径，与本缺陷无关），
        # 故按 rstrip('\n') 归一后比较。
        check("content 原文保全",
              (after.get("content") or "").rstrip("\n")
              == (before.get("content") or "").rstrip("\n"),
              repr(after.get("content")))
        check("layer 不变", afm.get("layer") == bfm.get("layer"),
              (bfm.get("layer"), afm.get("layer")))

        print("[2] V22 主诉：frontmatter 字段逐项保全（旧代码全数丢失）")
        check("tags 保全", afm.get("tags") == ["incident", "rollback"],
              afm.get("tags"))
        check("importance 保全", afm.get("importance") == 0.9,
              afm.get("importance"))
        check("confidence 保全", afm.get("confidence") == 0.8,
              afm.get("confidence"))
        _acs = afm.get("condition_space") or {}
        check("condition_space 自定义键保全（env/region，非只剩 time_window）",
              _acs.get("env") == "prod" and _acs.get("region") == "cn",
              afm.get("condition_space"))
        check("non_applicable_conditions 保全",
              afm.get("non_applicable_conditions") == ["演练环境"],
              afm.get("non_applicable_conditions"))
        check("edges 保全", afm.get("edges") == [["node_x", "ref"]],
              afm.get("edges"))
        check("protected 保全", afm.get("protected") is True,
              afm.get("protected"))
        check("protection_reason 保全",
              afm.get("protection_reason") == "复现保护标记",
              afm.get("protection_reason"))
        check("created_at 不重置",
              afm.get("created_at") == bfm.get("created_at"),
              (bfm.get("created_at"), afm.get("created_at")))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\nmigrate_restricted 守卫: {passed} 通过 / {failed} 失败")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
