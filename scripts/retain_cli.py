# -*- coding: utf-8 -*-
"""retain_cli —— `md_cg.retain` 的命令行入口（T14 保留面的可操作面）

## 为什么有这个脚本（病灶 E，2026-10-21）

`md_cg/retain.py`（605 行）是 T14「被反复引用的要留住」的实现，含判定面
（`retain_verdict` / `retain_scan`）与写面（`promote` / `rollback`，三闸取与、
记账与回滚齐备）。但在本脚本之前：**生产链上零调用**——全仓只有 3 个测试
import 它（`test_t14a_acceptance.py:95`、`test_t14a_retain_promote.py:60`、
`test_t14a_retain_verdict.py:58`），没有任何 CLI、定时任务或服务调它。

后果不是「少一个功能」，而是这条 ✅ 目标的兑现方式只有测试：`目标清单.md:80`
记 T14「✅ 2026-10-13 已交付」，而运行时没人能触发它，运维只能照模块 docstring
里那句「运行：python -c \"from md_cg import retain, mdcg; ...\"」手抄命令——正是
「记忆里的人肉步骤」。本脚本把那句手抄命令变成登记入口。

## 判据面的接线（不是重写）

本脚本**不含判据**：判定与写盘全部委托 `md_cg.retain`，自己不解释阈值、不复制
层清单、不碰 frontmatter。这样「留不留」只有一个事实源，避免第二条实现漂移
（本仓既有教训：同一语义两处实现必然漂移）。

写盘仍要三闸取与（`有 --apply` ∧ `有 --writable` ∧ `retain.promote` 内部的
`e_gate()` ALLOW）；缺一即只预演并如实回 `blocked_by`——本脚本不给任何闸开后门。

## 用法

    python scripts/retain_cli.py scan  --root <库根>
    python scripts/retain_cli.py promote --root <库根>            # 预演
    python scripts/retain_cli.py promote --root <库根> --apply --writable
    python scripts/retain_cli.py rollback --root <库根> --batch <批次>

退出码：0 成功（含预演）；2 参数/库根不可用；3 写盘被闸拦下（预演结果仍打印）。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cg(root):
    from md_cg import mdcg
    return mdcg.MdCG(root)


def _dump(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def main(argv=None):
    ap = argparse.ArgumentParser(prog='retain_cli', description='T14 保留面：盘点 / 提升 / 回滚')
    ap.add_argument('action', choices=['scan', 'promote', 'rollback'])
    ap.add_argument('--root', required=True, help='md_cg 库根（含 knowledge/ 等层目录）')
    ap.add_argument('--id', action='append', dest='ids', help='显式候选节点 id（可重复）')
    ap.add_argument('--apply', action='store_true', help='写盘意图（第一闸）')
    ap.add_argument('--writable', action='store_true', help='主库写窗口（第二闸）')
    ap.add_argument('--batch', help='rollback 的批次号（缺省最近一批）')
    ap.add_argument('--json', action='store_true', help='只打 JSON')
    a = ap.parse_args(argv)

    if not os.path.isdir(a.root):
        print(f'库根不存在：{a.root}', file=sys.stderr)
        return 2
    try:
        cg = _cg(a.root)
    except Exception as e:
        print(f'库根打不开：{type(e).__name__}: {e}', file=sys.stderr)
        return 2

    from md_cg import retain

    if a.action == 'scan':
        out = retain.retain_scan(cg)
        _dump(out)
        return 0

    if a.action == 'promote':
        out = retain.promote(cg, ids=a.ids or None, apply=a.apply, writable=a.writable,
                             actor='retain_cli')
        _dump(out)
        return 0 if not out.get('blocked_by') else 3

    out = retain.rollback(cg, batch=a.batch, entry_ids=a.ids or None, actor='retain_cli')
    _dump(out)
    return 0 if out.get('ok') else 3


if __name__ == '__main__':
    sys.exit(main())
