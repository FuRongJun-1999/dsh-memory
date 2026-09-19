# -*- coding: utf-8 -*-
"""蜂巢 worker：按域重索引 code_ref 节点（确定性执行，零 LLM）。

链路（与 mcp_server 的 op=index_code 同源）：
    refindex.index_dir(root, kind='code_ref', ledger=Ledger(cg.root))
    refindex.add_items(cg, items, kind='code_ref', root=root)
    refindex.prune_orphans(cg, kind='code_ref', root=root, items=items)
    refindex.prune_dangling(cg, only_roots=[root])
    cg.close()

incremental=1 时以 _refindex.json 水位跳过未变文件——只补齐缺口文件，
已索引且未变的节点零触碰（缩小不可逆面）。

为什么 Principal 必须 can_admin=True：`forget` 在 MdCGSecure 上受
`require_admin` 闸门保护（mdcos.py 第 3289 行）。本 worker 是**库维护通道**
（重建派生索引），清退过期代/悬空节点是重建的必要环节——无 admin 则
`prune_orphans` 计划全部被拒、`count=0` 而脚本仍报 ok，验收判据
（meta_indep == total、old_synth == 0）永远达不到。该身份不进检索面、
不参与授权收窄，语义上与 MCP 侧持 admin 令牌的维护调用同档。

用法：
  python -X utf8 scripts/_mdcg_reindex_code.py \
      --root <库根> --repo <仓根> --domain md_cg \
      [--incremental 1] [--max-files 2000] [--max-items 50000] \
      [--prune 1] [--dangling 1] [--max-check 20000]
"""
import os
import sys
import json
import time
import argparse

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True, help="认知图库根")
ap.add_argument("--repo", required=True, help="dsh-memory 仓根（md_cg 包所在）")
ap.add_argument("--domain", required=True, help="仓内相对目录名，或绝对路径")
ap.add_argument("--incremental", type=int, default=1)
ap.add_argument("--max-files", type=int, default=2000)
ap.add_argument("--max-items", type=int, default=50000)
ap.add_argument("--prune", default="1",
                help="索引后清退同 root 同 path 的过期代节点：1=实做 0=跳过 dry=只列")
ap.add_argument("--dangling", default="1",
                help="索引后清退本 root 下源文件已删除的悬空节点：1=实做 0=跳过 dry=只列")
ap.add_argument("--max-check", type=int, default=20000,
                help="prune_dangling 巡检上限（MAX_CHECK=2000 会截断，全量对账须抬高）")
a = ap.parse_args()

repo = os.path.abspath(a.repo)
sys.path.insert(0, repo)
from md_cg import refindex                      # noqa: E402
from md_cg.mdcos import MdCGSecure              # noqa: E402
from md_cg.security import Principal            # noqa: E402

src = a.domain if os.path.isabs(a.domain) else os.path.join(repo, a.domain)
if not os.path.isdir(src):
    print(json.dumps({"ok": False, "error": "目录不存在：%s" % src},
                     ensure_ascii=False))
    sys.exit(2)

principal = Principal(actor="hive_reindex", session="sess_hive_reindex",
                      harness="hive", can_write=True, can_admin=True)
cg = MdCGSecure(a.root, principal=principal, autoflush=64)

t0 = time.time()
items, errors, stats = refindex.index_dir(
    src, kind="code_ref",
    max_files=a.max_files, max_items=a.max_items,
    incremental=bool(a.incremental), ledger=refindex.Ledger(cg.root))
ids, sens = refindex.add_items(cg, items, kind="code_ref", root=src)

# 与 mcp_server._prune_after_index 同源：add_items 只做同 id 幂等 upsert，
# 源侧符号改名/删除留下的过期代节点不会自动消失（须显式清退）。
# 截断时一律跳过——没扫完不等于剩下的都过期。
pv = str(a.prune).strip().lower()
prune = {"mode": pv, "skipped": None, "dry_run": None, "count": None,
         "blocked": None, "head": []}
if pv in ("0", "false", "no", "off", ""):
    prune["skipped"] = "prune=0"
elif stats.get("truncated"):
    prune["skipped"] = "索引被截断，对账不成立"
else:
    dry = pv in ("dry", "dry_run", "dry-run")
    prune["dry_run"] = dry
    try:
        res = refindex.prune_orphans(cg, kind="code_ref", root=src, items=items,
                                     dry_run=dry)
        prune["count"] = res.get("count")
        blocked = res.get("skipped_protected") or []
        prune["blocked"] = len(blocked)
        # 被拒原因必须透出：上一轮「blocked=15 / count=0 但 ok=true」静默无归因，
        # 是本次排障多耗一轮的直接原因（与 op 必填防呆同源的教训）。
        prune["blocked_reason"] = (blocked[0].get("error")
                                   if blocked and isinstance(blocked[0], dict)
                                   else None)
        prune["head"] = (res.get("pruned") or [])[:10]
    except Exception as exc:                 # 权限/保护等 → 如实记录，不假装成功
        prune["error"] = str(exc)[:200]

# 悬空清退（`op=ref action=prune` 的等价面）：源文件已删除的节点回读必然失败，
# 靠 prune_orphans 够不着——其计划按「同 root 同 path 且不在新代中」立项，
# 而悬空节点的源 path 根本不在本轮 items 里（keep is None → 直接跳过）。
dg = str(a.dangling).strip().lower()
prune["dangling"] = {"mode": dg, "skipped": None, "dry_run": None, "count": None,
                     "candidates": None, "truncated": None, "blocked": None,
                     "head": []}
if dg in ("0", "false", "no", "off", ""):
    prune["dangling"]["skipped"] = "dangling=0"
elif stats.get("truncated"):
    prune["dangling"]["skipped"] = "索引被截断，对账不成立"
else:
    dry2 = dg in ("dry", "dry_run", "dry-run")
    prune["dangling"]["dry_run"] = dry2
    try:
        res2 = refindex.prune_dangling(cg, only_roots=[src], dry_run=dry2,
                                       max_nodes=a.max_check)
        prune["dangling"]["count"] = res2.get("count")
        prune["dangling"]["candidates"] = res2.get("candidates")
        prune["dangling"]["truncated"] = res2.get("truncated")
        b2 = res2.get("skipped_protected") or []
        prune["dangling"]["blocked"] = len(b2)
        prune["dangling"]["blocked_reason"] = (b2[0].get("error")
                                              if b2 and isinstance(b2[0], dict)
                                              else None)
        prune["dangling"]["head"] = (res2.get("pruned") or [])[:10]
    except Exception as exc:
        prune["dangling"]["error"] = str(exc)[:200]

cg.close()

print(json.dumps({
    "ok": True,
    "domain": a.domain,
    "src": src,
    "incremental": bool(a.incremental),
    "items": len(items),
    "written_ids": len(ids),
    "errors": len(errors),
    "truncated": stats.get("truncated"),
    "truncated_reason": stats.get("truncated_reason"),
    "skipped_unchanged": stats.get("skipped_unchanged"),
    "files_scanned": stats.get("files"),
    "prune": prune,
    "sens": sens,
    "elapsed_s": round(time.time() - t0, 1),
    "errors_head": errors[:5],
}, ensure_ascii=False))
sys.exit(0)
