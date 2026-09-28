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
  python scripts/migrate_restricted.py --apply --ids id1 --force

N220（2026-09-28）三条收紧：
  · 目标复查：`--ids`（或全量扫描）的每个目标都须在索引中**密级为 private**、
    且 layer 不在不可篡改层（`md_cg/protect.PROTECTED_LAYERS` = self/anchor）
    ——不满足者显式 SKIP 并报出原因。旧实现直取清单不看目标，一次
    `--ids anchor_node,internal_node --apply` 即把保护层节点与共享档节点
    一并改写为 restricted（层保护闸被恒定 override=True 绕开，误操作不可逆）。
  · override 置位条件：仅当「目标确为 private 档」且用户**显式 `--force`**
    时才传 override=True；受写保护（immutable 标记）节点默认拒改并报出，
    工具不再默认代持该权限（引擎级 `protect.guard_write` 正常生效）。
  · dry-run 只报元数据（layer/密级/正文字数），**不回显正文**——旧实现按
    `content[:40]` 回显私有档正文到终端/CI 日志，且把 `--ids` 指定节点一律
    计成「扫描到 private 节点」，计数与来源不符。
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
    ap.add_argument("--force", action="store_true",
                    help="受写保护（immutable 标记）的 private 节点也覆写"
                         "（缺省拒改；N220：override 仅在显式 --force 时置位）")
    a = ap.parse_args(argv)
    if not a.root:
        print("需要 --root 或 MDCG_ROOT 环境变量")
        return 2

    from md_cg import protect
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import AccessDenied, Principal

    # autoflush=1（P1b，2026-09-26，与 mcp_server.py:3695-3702 同款）：短命迁移
    # 工具进程无显式 close，被 kill 时 atexit 兜底不执行，缺省 64 会让覆写停在
    # 内存 _dirty、分片日志从未落——逐条落日志保任意退出形态跨进程可见。
    cg = MdCGSecure(a.root, principal=Principal(
        actor="migrate-restricted", clearance="secret", can_write=True,
        can_admin=True, role="designer", auth_mode="test"), autoflush=1)
    entries = cg.index.get("nodes") or {}
    mode_label = "APPLY 迁移" if a.apply else "DRY-RUN 清单"
    if a.ids:
        targets = [x.strip() for x in a.ids.split(",") if x.strip()]
        print("指定 --ids 节点 %d 个（%s）" % (len(targets), mode_label))
    else:
        targets = sorted(nid for nid, e in entries.items()
                         if (e or {}).get("sensitivity") == "private")
        print("扫描到 private 节点 %d 个（%s）" % (len(targets), mode_label))
    ok = skipped = 0
    for nid in targets:
        # N220：逐目标复查——清单来源（--ids 由运维/外部工具生成）不构成判据，
        # 真判据是节点当下的密级与层（直取清单曾把 anchor 保护层与共享档节点
        # 一并改写为 restricted，且 override=True 恒定置位绕开层保护闸）。
        entry = entries.get(nid)
        if entry is None:
            print("  SKIP（索引中无此节点——id 拼写或库代不同）: " + nid)
            skipped += 1
            continue
        layer = str(entry.get("layer") or "")
        sens = str(entry.get("sensitivity") or "")
        if layer in protect.PROTECTED_LAYERS:
            print("  SKIP（%s 为保护层（不可篡改）——迁移即越权改写，"
                  "本工具不代持该权限）: %s" % (layer, nid))
            skipped += 1
            continue
        if sens != "private":
            print("  SKIP（目标密级=%s，非 private——本工具只处置 private 档）: %s"
                  % (sens or "未标注", nid))
            skipped += 1
            continue
        node = cg.get(nid)
        if not node:
            print("  SKIP（designer 不可读——写者会话绑定/信封缺失）: " + nid)
            skipped += 1
            continue
        # 写保护预检（与引擎级 protect.guard_write 同判据）：让 dry-run 清单与
        # apply 实际动作一致——否则 dry-run 会把「将被 guard_write 拒绝」的节点
        # 也列成「将迁移」（清单不可信）。--force 时跳过本预检（显式承认覆写）。
        _prot, _why = protect.is_immutable(cg, nid)
        if _prot and not a.force:
            print("  SKIP（节点受写保护：%s；需显式 --force 才可覆写）: %s"
                  % (_why, nid))
            skipped += 1
            continue
        if not a.apply:
            if ok < a.limit:
                # 只报元数据：私有档正文不回显（旧实现 content[:40] 把正文
                # 倒进终端/CI 日志），计数按「可通过复查的目标」计。
                print("  将迁移: %s（layer=%s sensitivity=%s→restricted 正文 %d 字）"
                      % (nid, layer, sens, len(node.get("content") or "")))
            ok += 1
            continue
        full = node
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
        # N220：override 只在「目标确为 private 档」（上面已复查）且用户显式
        # --force 时置位——否则引擎级写保护闸（protect.guard_write）正常生效，
        # 受保护（immutable）节点须显式 --force，工具不默认代持覆写权限。
        override = bool(a.force) and sens == "private"
        try:
            cg.add(nid, full.get("content", ""),
                   layer=(fm_old.get("layer") or "knowledge"),
                   sensitivity="restricted", override=override, **passthrough)
        except (protect.ProtectionError, AccessDenied) as exc:
            print("  SKIP（受写保护/无写权，需 --force 复核后重试）: %s — %s"
                  % (nid, exc))
            skipped += 1
            continue
        ok += 1
    print("%s: %d  跳过: %d" % ("迁移" if a.apply else "清单", ok, skipped))
    if not a.apply:
        print("dry-run 未改动任何节点；确认清单后加 --apply 执行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
