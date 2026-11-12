# -*- coding: utf-8 -*-
"""issue #672 守卫：validity 语义与 meta 口径透出（不改变过滤行为）。"""
from __future__ import annotations

import tempfile

from .mdcos import MdCGOS


def main():
    ok = bad = 0

    def chk(cond, label):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  PASS", label)
        else:
            bad += 1
            print("  FAIL", label)

    cg = MdCGOS(tempfile.mkdtemp(prefix="f672_"))
    cg.add("expired", "# 功能名：甲过期\n# 执行：乙", layer="knowledge", importance=0.6,
           verification_basis="test", valid_until="2000-01-01")
    cg.add("live", "# 功能名：甲在效\n# 执行：乙", layer="knowledge", importance=0.6,
           verification_basis="test", valid_from="2000-01-01", valid_until="2099-01-01")
    cg.add("future", "# 功能名：甲未生效\n# 执行：乙", layer="knowledge", importance=0.6,
           verification_basis="test", valid_from="2099-01-01")
    cg.flush()

    res_off, meta_off = cg.search_rrf("甲", paths=("bm25",), k=10)
    res_on, meta_on = cg.search_rrf("甲", paths=("bm25",), k=10, validity=True)
    ids_off = sorted(r[0].get("id") for r in res_off)
    ids_on = sorted(r[0].get("id") for r in res_on)

    chk(meta_off.get("validity_scope") == "off", "默认（不启用）meta.validity_scope=off")
    chk(meta_on.get("validity_scope") == "expired_only", "启用时 meta.validity_scope=expired_only")
    chk("expired" in ids_off, "未启用：过期节点仍可见（默认不过滤）")
    chk("expired" not in ids_on, "启用：过期节点被排除")
    chk("future" in ids_on, "启用：**未生效节点仍保留**（名字易误读，本守卫钉住语义）")
    chk("live" in ids_on, "启用：生效中节点保留")

    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
