#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""存量 private 节点 → restricted（错误处置标记）迁移工具（批次 28）。

private 分型后：错误处置标记用 restricted（链路必读、不加密），private
回归纯隐私/会话绑定语义。存量 private 节点按「错误相关被标记」的体系
语义应迁为 restricted——是否迁移、迁移哪些由使用者逐批裁定（private
节点中可能混有真隐私内容，脚本不做语义猜测）。

用法：
  python scripts/migrate_restricted.py --dry-run
  python scripts/migrate_restricted.py --apply
  python scripts/migrate_restricted.py --apply --ids id1,id2
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def main(argv=None):
    ap = argparse.ArgumentParser(description="private → restricted 迁移")
    ap.add_argument("--root", default=os.environ.get("MDCG_ROOT"),
                    help="认知图库根（缺省 MDCG_ROOT env）")
    ap.add_argument("--ids", default=None,
                    help="逗号分隔的节点 id 清单（缺省=全部 private）")
    ap.add_argument("--apply", action="store_true",
                    help="执行迁移（缺省 dry-run 只出清单）")
    ap.add_argument("--limit", type=int, default=50,
                    help="dry-run 清单最多显示条数（默认 50）")
    a = ap.parse_args(argv)
    if not a.root:
        print("需要 --root 或 MDCG_ROOT 环境变量")
        return 2

    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal

    # autoflush=1（P1b，2026-09-26，与 mcp_server.py:3695-3702 同款）：短命迁移
    # 工具进程无显式 close，被 kill 时 atexit 兜底不执行，缺省 64 会让覆写停在
    # 内存 _dirty、分片日志从未落——逐条落日志保任意退出形态跨进程可见。
    cg = MdCGSecure(a.root, principal=Principal(
        actor="migrate-restricted", clearance="secret", can_write=True,
        can_admin=True, role="designer", auth_mode="test"), autoflush=1)
    targets = (a.ids.split(",") if a.ids
               else [nid for nid, e in cg.index["nodes"].items()
                     if e.get("sensitivity") == "private"])
    print("扫描到 private 节点 %d 个（%s）" % (
        len(targets), "APPLY 迁移" if a.apply else "DRY-RUN 清单"))
    ok = skipped = 0
    for nid in targets:
        node = cg.get(nid)
        if not node:
            print("  SKIP（designer 不可读——写者会话绑定/信封缺失）: " + nid)
            skipped += 1
            continue
        if not a.apply:
            if ok < a.limit:
                print("  将迁移: %s  %r" % (nid, node.get("content", "")[:40]))
            ok += 1
            continue
        full = cg.get(nid) or {}
        fm_old = full.get("frontmatter") or {}
        # V22 修复：add 是**全量重建 frontmatter**（mdcg.py add docstring
        # 自认），只传 content/layer/sensitivity 会把存量 tags/condition_
        # space/importance/confidence/edges/non_applicable_conditions/
        # created_at/protected 等全部清空重置（数据丢失）。迁移只应改
        # sensitivity——其余字段一律从旧 frontmatter 透传。排除键：
        # · id/layer/sensitivity：本调用显式给值（sensitivity=重复传参即
        #   TypeError）；
        # · state/lifecycle_state/verification_state：add 覆写既有节点时
        #   **默认继承**旧值（mdcg.py :1268/:1291），显式传相同值反而要走
        #   迁移裁决，白担非法迁移风险；
        # · bucket/bucket_zh：路由按 tags/condition_space 重算（与
        #   _scan_nodes 重建口径一致）；
        # · writer：语义=最后写入者（_attribution），迁移即刷新为迁移者。
        passthrough = {k: v for k, v in fm_old.items()
                       if k not in ("id", "layer", "sensitivity", "state",
                                    "lifecycle_state", "verification_state",
                                    "bucket", "bucket_zh", "writer")}
        cg.add(nid, full.get("content", ""),
               layer=(fm_old.get("layer") or "knowledge"),
               sensitivity="restricted", override=True, **passthrough)
        ok += 1
    print("%s: %d  跳过: %d" % ("迁移" if a.apply else "清单", ok, skipped))
    if not a.apply:
        print("dry-run 未改动任何节点；确认清单后加 --apply 执行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
