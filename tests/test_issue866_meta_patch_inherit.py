# -*- coding: utf-8 -*-
"""#866 守卫：正文逐字未变的元数据补丁，前序 frontmatter 必须保住。

issue #866：`cg(op=maintain, action=retag, apply=True)` 对 doc 节点只改 tags，
正文与召回名次逐字不变，但 frontmatter 丢了 `doc_ref` / `importance_components`，
`sensitivity` 从 internal 变 null（**安全降级**）。

根因：`add()` 正文未变时只按白名单 `INHERIT_ON_OVERWRITE_BODY_SAME` 继承 → 漏一个丢一个。
修法：继承面改为「白名单 ∪（前序全部 − 必须重算的键）」。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg.mdcos import MdCGOS  # noqa: E402

CCG = ('# 功能名：{n}\n# 生效条件：c\n# 子功能：s\n# 执行：e\n'
       '# 验证方式：test\n# 不适用条件：无\n\n{body}\n')
FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:180])
        FAILS.append(name)


def main():
    print("=" * 70)
    print("#866 元数据补丁不得丢字段")
    print("=" * 70)
    root = tempfile.mkdtemp(prefix="i866_")
    cg = MdCGOS(root, actor="test")
    nid = "doc_probe"
    cg.add(nid, CCG.format(n="诊断", s="w", e="1", body="日记正文，逐字不变"),
           layer="knowledge", tags=["domain:diary_2026-10-09_deadbeef"],
           importance=0.6, sensitivity="internal",
           doc_ref={"src": "diary.md", "lineno": 12, "end": 30},
           # 注意：这些必须是**顶层 kwarg**（extra= 会嵌到 fm["extra"] 下，不是顶层）。
           # 真实 doc 摄取路径（index_doc）也是走 kwarg。
           importance_components={"base": 0.5, "boost": 0.1})
    before = cg.get(nid)["frontmatter"]
    ok("doc_ref" in before, "P1 前置：doc_ref 已写入", sorted(before))
    ok("importance_components" in before, "P1b 前置：importance_components 已写入")
    ok(before.get("sensitivity") == "internal", "P2 前置：sensitivity=internal")

    out = cg.retag(nid, tags_remove=["domain:diary_2026-10-09_deadbeef"],
                   tags_add=["domain:diary"], dry_run=False)
    ok(bool(out.get("committed")), "P3 retag 已提交", out)
    after = cg.get(nid)["frontmatter"]

    ok("doc_ref" in after, "P4 doc_ref 保住（provenance）", sorted(after))
    ok(after.get("doc_ref") == before.get("doc_ref"), "P5 doc_ref 内容逐位不变",
       (before.get("doc_ref"), after.get("doc_ref")))
    ok("importance_components" in after, "P6 importance_components 保住")
    ok(after.get("sensitivity") == "internal",
       "P7 sensitivity 不被重置（安全降级）", after.get("sensitivity"))
    ok("domain:diary" in (after.get("tags") or []), "P8 新标签生效")
    ok("domain:diary_2026-10-09_deadbeef" not in (after.get("tags") or []), "P9 旧标签移除")
    ok(cg.get(nid)["content"].strip() == CCG.format(
        n="诊断", s="w", e="1", body="日记正文，逐字不变").strip(), "P10 正文逐字不变")

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())