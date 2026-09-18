# -*- coding: utf-8 -*-
"""linkref 存量回填（R-L1b 配套，2026-09-17）。

背景：全库 62 个节点「正文已引用他节点、但 edges 为空」——零语法成本可回收
的存量差距。使用者裁决（2026-09-17）：**存量只进审核队列**，不直接写事实层。

三态（默认 dry-run，永不自动写库）：
    （无开关）         扫描 → 输出候选清单 JSON（只读）
    --propose          扫描 → 把「批次提案」写入海马体 inbox，返回 pid
    --apply --pid P    仅当提案 P 已被裁决为 accept 才落边（fail-closed）

为什么是「批次提案」而非「逐边提案」：灵枢审核队列的裁决单元是**节点**
（review_decide → add），逐边提案被 accept 时落成的是「记录节点」而非一条边，
不闭环。批次提案 + 清单文件 + accept 后 --apply 是**零核心改动**（不碰
review_decide 的安全语义）的闭环形态；人工审核粒度=批次，逐条明细可查清单。

用法（第 15 条：argv 列表 + 显式 UTF-8，不经 Windows shell）：
    set PYTHONUTF8=1
    python scripts/linkref_backfill.py --root <认知图根> --out cand.json
    python scripts/linkref_backfill.py --root <根> --propose
    python scripts/linkref_backfill.py --root <根> --apply --pid <已accept的pid>

边界：--apply 默认**重新扫描**（保证落边依据=当前真源）；传 --in 则用审核时
那份清单（可复现），两者都会经 append_edge 幂等去重。

读隔离（20260917 取证）：候选面随扫描身份密级变化——白名单 = **当前身份
可读**节点（口径同 `backfill._readable_guard`：不可见即不存在），读隔离区
节点既不作源（读不出）也不作目标（免生悬空边）。故 `--clearance` 缺省取
最保守的 internal，调高是运维显式决策（会加宽边面）。

读隔离的判据有**两个面**，扫描面与候选目标各受一道：
  ①**密级面**（`known_ids` → `_readable`，读索引里的 sensitivity 字段，纯内存）
    ——决定哪些节点进扫描面；
  ②**密钥面**（`live_targets` → 实读 `get`）——`private`/`secret` 正文是密文，
    解封需 (tenant, actor) 信封里的 DEK，无 DEK 时 `get` 返回 None。
  只在①上筛目标是**不够**的（密级够 ≠ 密钥够）：真实库 secret 下实测有
  459 条这样的节点，若不过②，候选清单会含 15 条指向死目标的悬空边。
统计键：`skipped_unreadable` = 白名单内实读失败的**源**节点数（clearance=
internal 下 0——白名单已按密级剔除；secret 下 459）；`skipped_dead_target` =
实读失败的**目标**候选数（悬空边拦截）。
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import linkref                       # noqa: E402
from md_cg.mdcos import MdCGSecure              # noqa: E402
from md_cg.security import DEFAULT_SENSITIVITY, Principal    # noqa: E402


# 生效条件：传入 cg 与 nid 后，cg._edge_node(nid) 不抛异常时返回其读值（fm, content, path），抛任意 Exception 时返回 None。
def _edge_node(cg, nid):
    """读 (fm, content, path)；失败返回 None（口径同 append_edge）。"""
    try:
        return cg._edge_node(nid)
    except Exception:                                # noqa: BLE001
        return None


# 生效条件：传入 cg 后遍历 sorted(known_ids(cg))，仅当 nid 通过 is_linkable_id、_edge_node(cg,nid) 返回真值、is_linkable_source(nid, fm.get("layer")) 为真、extract_refs(content or "", known, exclude=nid) 非空、其中存在不在 fm.get("edges") target 集内的 gap、且 live_targets(cg, gaps, cache=live_cache) 非空时，该节点计入 nodes_with_gap 并为每个存活 gap 追加 {node,target,layer,relation_type} 候选项（其余情况仅累加对应 skipped_* 后跳过），最终返回 (cands, stats)；verbose（默认 True）只在 nodes_scanned 每满 2000 时向 stderr 打印进度。
def scan(cg, verbose=True):
    """扫描全库：返回 (候选列表, 统计)。只读。

    目标侧**双道过滤**：白名单 = 当前身份可读节点（`known_ids`，密级面）→
    候选目标再过 `live_targets` 实读校验（密钥面）——`private`/`secret` 正文
    是密文，解封需本身份的 DEK，无 DEK 时建边会产出指向死目标的悬空边
    （真实库 secret clearance 下实测 459 条此类节点 / 15 条悬空候选）。
    """
    known = linkref.known_ids(cg)
    cands, stats = [], {"nodes_total": len(known), "nodes_scanned": 0,
                        "nodes_with_gap": 0, "pairs": 0, "skipped_audit": 0,
                        "skipped_bad_id": 0, "skipped_unreadable": 0,
                        "skipped_dead_target": 0,
                        "clearance": getattr(getattr(cg, "principal", None),
                                             "clearance", None)}
    live_cache = {}
    for i, nid in enumerate(sorted(known)):
        if not linkref.is_linkable_id(nid):
            stats["skipped_bad_id"] += 1   # 脏键（None / 中文标题式键）不作源
            continue
        got = _edge_node(cg, nid)
        if not got:
            stats["skipped_unreadable"] += 1   # 读隔离（不可见即不存在）
            continue
        fm, content, path = got
        stats["nodes_scanned"] += 1
        if verbose and stats["nodes_scanned"] % 2000 == 0:
            print("  ... 已扫 %d/%d" % (stats["nodes_scanned"], len(known)),
                  file=sys.stderr)
        if not linkref.is_linkable_source(nid, fm.get("layer")):
            stats["skipped_audit"] += 1        # 审计留痕层（self）不作源
            continue
        refs = linkref.extract_refs(content or "", known=known, exclude=nid)
        if not refs:
            continue
        have = {str(e.get("target")) for e in (fm.get("edges") or [])
                if isinstance(e, dict) and e.get("target")}
        gaps = [t for t in refs if t not in have]
        if not gaps:
            continue
        live = linkref.live_targets(cg, gaps, cache=live_cache)
        stats["skipped_dead_target"] += len(gaps) - len(live)
        if not live:
            continue
        gaps = live
        stats["nodes_with_gap"] += 1
        layer = fm.get("layer") or ""
        for t in gaps:
            cands.append({"node": nid, "target": t, "layer": layer,
                          "relation_type": linkref.RELATION})
    stats["pairs"] = len(cands)
    return cands, stats


# 生效条件：传入 cg、cands、stats、out_path 即用 stats["nodes_with_gap"]、stats["pairs"]、stats["nodes_total"] 与 out_path or "(未落盘)" 组装提案文本，调用 cg.propose(node_id="mem_%d" % int(time.time()*1000)、layer="contextual"、tags 含 linkref/backfill/edge-proposal、linkref_batch 取自 stats 与 out_path) 并返回 pid，无其他返回分支。
def do_propose(cg, cands, stats, out_path):
    content = (
        "【linkref 存量回填提案】扫描到 %d 个源节点存在「正文已引用他节点、"
        "但未建 reference 边」的差距，共 %d 条候选边（全库 %d 节点）。\n"
        "候选清单：%s\n"
        "复现扫描：python scripts/linkref_backfill.py --root <root> --out <file>\n"
        "裁决 accept 后落边：python scripts/linkref_backfill.py --root <root> "
        "--apply --pid <本pid>\n"
        "说明：本次不直接写事实层（使用者裁决 2026-09-17：存量只进审核队列）；"
        "落边经 append_edge 幂等，边类型 reference、verified=False。"
        % (stats["nodes_with_gap"], stats["pairs"], stats["nodes_total"],
           out_path or "(未落盘)"))
    pid = cg.propose(node_id="mem_%d" % int(time.time() * 1000),
                     content=content, layer="contextual",
                     tags=["linkref", "backfill", "edge-proposal"],
                     linkref_batch={"count": stats["pairs"],
                                    "nodes": stats["nodes_with_gap"],
                                    "file": out_path})
    return pid


# 生效条件：传入 cg、pid、cands 后，若 cg._pid_status() 取出的 st.get(pid) or {} 中 status 不等于 "accepted"（含 pid 不在 st 中），打印拒绝并返回 2；否则逐条处理 cands——live_targets(cg,[c["target"]]) 为空计入 dead 跳过，cg.append_edge(c["node"], linkref.make_edge(...)) 为真计入 added、为假计入 skipped、抛 Exception 计入 failed，最后返回 1（failed 非 0）或 0。
def do_apply(cg, pid, cands):
    st = cg._pid_status()
    rec = st.get(pid) or {}
    if rec.get("status") != "accepted":
        print("拒绝：pid %s 未经 accept 裁决（状态=%s）——fail-closed。"
              % (pid, rec.get("status") or "未入队"))
        return 2
    added = skipped = failed = dead = 0
    live_cache = {}
    for c in cands:
        # 落边时刻再校一次目标可得性（清单可能来自另一密级/另一身份的扫描，
        # 或节点在审核期间被加密/删除）——不可读即不建边，不留悬空边。
        if not linkref.live_targets(cg, [c["target"]], cache=live_cache):
            dead += 1
            continue
        try:
            if cg.append_edge(c["node"],
                              linkref.make_edge(c["target"],
                                                source="backfill:linkref")):
                added += 1
            else:
                skipped += 1
        except Exception as e:                       # noqa: BLE001
            failed += 1
            print("  落边失败 %s→%s：%r" % (c["node"], c["target"], e))
    print("落边完成：新增 %d / 幂等跳过 %d / 目标不可读 %d / 失败 %d（候选 %d）"
          % (added, skipped, dead, failed, len(cands)))
    return 1 if failed else 0


# 生效条件：a.root（--root 缺省取 os.environ.get("MDCG_ROOT")）为假值时返回 3；否则以 clearance=--clearance（缺省读 os.environ.get("MDCG_CLEARANCE")，未设或为空串则回落模块常量 DEFAULT_SENSITIVITY）建 Principal 与 MdCGSecure——给了 --in 则读该 JSON 的 "candidates"/"stats"（缺键或假值回落 []/{}），未给则 scan(cg, verbose=not a.quiet)；--out 非空时写出清单文件；随后 --apply 且给了 --pid 时返回 do_apply(cg, a.pid, cands)，--apply 缺 --pid 返回 3，否则 --propose 时返回 0，两者皆无按 dry-run 返回 0。
def main():
    ap = argparse.ArgumentParser(description="linkref 存量回填（默认 dry-run）")
    ap.add_argument("--root", default=os.environ.get("MDCG_ROOT"),
                    help="认知图根目录（缺省读 MDCG_ROOT）")
    ap.add_argument("--out", default=None, help="候选清单输出路径（JSON）")
    ap.add_argument("--in", dest="inp", default=None,
                    help="--apply 时改用既有清单（缺省重新扫描）")
    ap.add_argument("--propose", action="store_true", help="写入审核队列（批次提案）")
    ap.add_argument("--apply", action="store_true", help="落边（须 --pid 已 accept）")
    ap.add_argument("--pid", default=None, help="--apply 所需的已裁决提案 pid")
    ap.add_argument("--clearance", default=os.environ.get("MDCG_CLEARANCE")
                    or DEFAULT_SENSITIVITY,
                    help="扫描身份密级（缺省读 MDCG_CLEARANCE，否则 internal"
                         "=最保守；可读面与边面随密级变化）")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    if not a.root:
        print("缺少 --root（或设 MDCG_ROOT）"); return 3
    p = Principal(tenant="default", actor="linkref_backfill", role="designer",
                  clearance=a.clearance, can_write=True, can_admin=True)
    cg = MdCGSecure(a.root, principal=p)

    if a.inp:
        with open(a.inp, encoding="utf-8") as f:
            data = json.load(f)
        cands = data.get("candidates") or []
        stats = data.get("stats") or {}
        print("载入清单：%d 条候选" % len(cands))
    else:
        print("扫描中（clearance=%s，可读 %d 节点）..."
              % (a.clearance, len(linkref.known_ids(cg))), file=sys.stderr)
        cands, stats = scan(cg, verbose=not a.quiet)

    print(json.dumps(stats, ensure_ascii=False))
    if a.out:
        parent = os.path.dirname(os.path.abspath(a.out))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"stats": stats, "candidates": cands}, f,
                      ensure_ascii=False, indent=1)
        print("候选清单已写出：%s" % a.out)

    if a.apply:
        if not a.pid:
            print("--apply 必须配 --pid（已 accept 的提案）"); return 3
        return do_apply(cg, a.pid, cands)
    if a.propose:
        pid = do_propose(cg, cands, stats, a.out)
        print("已入审核队列：pid=%s（待 review_cli accept 后方可 --apply）" % pid)
        return 0
    print("dry-run 结束（未写库）。加 --propose 入队，或 --apply --pid 落边。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
