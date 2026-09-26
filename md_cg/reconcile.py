# -*- coding: utf-8 -*-
"""启动对账 reconcile v0（v0.3 T9 自稳定定理落地，落地清单 P0-3）。

**定位（与 twophase 的分工）**：`twophase.reconcile` 是**写账本清账**——只回答
「有 intent 无 outcome 的那笔写入到底落盘没有」；本模块是它之上的**全量 diff
对账**：索引（派生态）vs 盘面真源（节点 .md）逐条比对，把「索引与盘面背离」
收敛回自稳定合法态（T9：任意瞬态扰动后仅凭真源与协议在有限步内回到合法态）。

**三类 diff（v0 判据面）**：
  1. **多索引条目**（幽灵）：索引有条目、盘面无其文件（或该文件已归属他 id）
     → 摘除条目（tombstone，与 `_unstage` 同口径）；
  2. **缺索引条目**：盘面有节点文件、索引无条目（非合作写者/日志丢失）
     → 以 `_node_entry` 重建条目补入（与 rebuild_index 逐字段同源）；
  3. **内容漂移**：条目 path 与盘面落点不符、或 content_hash 与盘面重算不符
     → 以盘面为真源重建条目（**增量 upsert**，不触发全量 rebuild）。

**T9 边界（结构合法 ≠ 内容正确）**：真源自身损坏——读失败（OSError，含
Windows 上 Defender/索引器持句柄的瞬态形态）、解码失败（非 UTF-8 字节）、
frontmatter 结构非法（`---` 无闭合）——**一律不自动改写**：既不据损坏文件
建条目，也不因「读不出」摘除既有条目（瞬态读失败若被当「文件没了」就会把
一次性抖动放大成索引面永久损伤，与 N134 同型——宁可漏修，不可误伤），只
stderr 告警 + `_reconcile.jsonl` 留痕，是否处置交人工/上层裁决。

**耗时可控**：清单 diff 是 O(n) 索引操作（os.walk 计数级）；哈希核验对每个
盘面 .md 恰一次顺序读 + 轻量 frontmatter 切分（`nodefile.loads` 是纯字符串
切分，无 YAML/全文解析、无检索打分/嵌入）——不是 `rebuild_index` 式全量重扫，
修复只对漂移条目做定向 upsert。整体 O(n)；`MDCG_RECONCILE=0` 一键关闭
（缺省开）。**告警口径**：diff 非空才写 stderr 与留痕，干净库零输出零写盘。

**诚实边界（v0 不覆盖面）**：
  · frontmatter **字段值**漂移（如盘上 importance 被直改、索引仍旧值）不在
    v0 判据面——索引没有 fm 指纹可比（content_hash 刻意不含 frontmatter，见
    nodefile.content_hash 文档串），该面仍由 rebuild_index 全量兜底（v1 候选）；
  · 对账是**增益**不是服务前提：本模块任何异常都不得阻塞启动（调用方
    mcp_server.main 以 try/except 包裹，与两段式对账同风格）。
"""
import os
import time

from . import nodefile
from .fsutil import append_jsonl

#: 关闭开关：仅当 `MDCG_RECONCILE` 的 strip 后取值**恰好为 "0"** 时关闭
#: （缺省开；其它取值一律视为开——开关只回答「关没关」，不承担配置语义）。
ENV_SWITCH = "MDCG_RECONCILE"

#: 留痕文件（root 下，append-only，与 `_write_2pc.jsonl` / `_protected_audit.jsonl`
#: 同一「独立审计文件」惯例；**仅在 diff 非空时写入**，干净库零写盘）。
TRACE_FILE = "_reconcile.jsonl"

#: 留痕/告警里每类异常的采样上限（防大库首轮修复把日志/告警撑成洪水）。
SAMPLE_CAP = 20


# 生效条件：读 MDCG_RECONCILE 环境变量（未设按空串），strip 后等于 "0" 返回 False，其余（含未设）返回 True。
def enabled() -> bool:
    """对账开关（缺省开；`MDCG_RECONCILE=0` 关闭）。"""
    return os.environ.get(ENV_SWITCH, "").strip() != "0"


# 生效条件：给定 cg 且其 root 属性可参与 os.path.join 时，恒返回 os.path.join(cg.root, TRACE_FILE)，无分支与早退。
def trace_path(cg) -> str:
    return os.path.join(cg.root, TRACE_FILE)


# 生效条件：text 为假值（None/""）时按空串处理，返回去尾换行后的字符串（仅剥 "\n"）。
def _norm(text: str) -> str:
    return (text or "").rstrip("\n")


# 生效条件：content（nodefile.loads 切出的盘面正文，含尾换行）非 None 时返回 (content_hash(content), content_hash(_norm(content))) 二元组——**双形态接受集**：add 写路径入索引的指纹按封存原文（mdcg.py `_stage` 面，正文不带尾换行时等于 norm 形态），rebuild 重建路径按 loads 读回原文（带尾换行）——两 producers 各自稳定，diff 两侧都认，否则无尾换行节点会在每次启动被误报漂移（假阳性洪水，twophase._norm 文档串同款教训）。
def _disk_hashes(content: str) -> tuple:
    raw = nodefile.content_hash(content or "")
    return raw, nodefile.content_hash(_norm(content))


# 生效条件：遍历 mdcg.LAYERS 各层目录树（os.walk，与 _scan_nodes 同序同口径），逐个 .md 读取并 nodefile.loads 切分；成功解析的以 nid（fm.get("id") 或文件名去 .md）登入 by_nid（同 nid 后到覆盖，与 _scan_nodes dict 覆盖语义一致）并登记 path_owner[relpath]=nid；读失败（OSError）/解码失败（UnicodeDecodeError）/frontmatter 无闭合（fm 为空且原文以 "---\n" 开头）的登入 problems（kind=read_error/decode_error/frontmatter_unterminated，附 relpath），不进 by_nid 与 path_owner；返回 (by_nid, path_owner, problems)。
def _scan_disk(cg):
    by_nid = {}
    path_owner = {}
    problems = []
    for layer in _layers():
        base = os.path.join(cg.root, layer)
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, cg.root).replace("\\", "/")
                try:
                    with open(p, encoding="utf-8") as f:
                        text = f.read()
                except OSError as exc:          # 瞬态/持久读失败：不猜测
                    problems.append({"path": rel, "kind": "read_error",
                                     "detail": str(exc)[:120]})
                    continue
                except UnicodeDecodeError as exc:   # 非 UTF-8 字节：真源损坏
                    problems.append({"path": rel, "kind": "decode_error",
                                     "detail": str(exc)[:120]})
                    continue
                fm, content = nodefile.loads(text)
                if not fm and text.startswith("---\n"):
                    # 结构非法：有 frontmatter 起始符但无闭合——loads 无法切出
                    # 字段（正常节点必有 frontmatter；无 frontmatter 的裸文件
                    # 按 _scan_nodes 旧例仍以文件名登入，不判损坏）。
                    problems.append({"path": rel,
                                     "kind": "frontmatter_unterminated",
                                     "detail": "--- 无闭合"})
                    continue
                nid = fm.get("id") or fn[:-3]
                by_nid[nid] = {"path": rel, "abs": p, "layer": layer,
                               "fm": fm, "content": content}
                path_owner[rel] = nid
    return by_nid, path_owner, problems


# 生效条件：延迟导入 mdcg 取模块级 LAYERS 并返回（与 _scan_nodes 的遍历集合同一真源；函数内导入避免 mdcg ↔ reconcile 模块环）。
def _layers():
    from .mdcg import LAYERS
    return LAYERS


# 生效条件：把单条异常以 JSONL 追加进 trace_path(cg)（best-effort：OSError 吞掉不抛——留痕是增益，不得反过来炸启动序列），无返回值。
def _trace(cg, record: dict) -> None:
    try:
        append_jsonl(trace_path(cg), record)
    except OSError:
        pass


# 生效条件：向 stderr 写一行告警（try/except 全包——stderr 为 None/closed/断管时静默放弃，N136 教训：告警通道失效不得伪装成新异常炸穿调用方），无返回值。
def _warn(msg: str) -> None:
    try:
        import sys
        sys.stderr.write("[mdcg-reconcile] %s\n" % msg)
    except Exception:                       # noqa: BLE001 —— 告警失效不追责
        pass


# 生效条件：cg.index 须含 "nodes" 映射；enabled() 为 False 时直接返回 {"skipped": True, "applied": False} 不触盘；否则 _scan_disk 后做三类 diff：①nid 不在盘面且其 entry.path 既非问题文件也非无主——判幽灵（apply 时逐条 _unstage）；②盘面 nid 不在索引——判缺失（apply 时以 cg._node_entry 构条目 _stage）；③两上面向交的 nid 中 entry.path 与盘面落点不符或 content_hash 不在盘面双形态接受集——判漂移（apply 时以盘面重建条目 _stage）；apply 为真时收尾 cg.flush() 持久化；diff 非空时写 stderr 告警并 _trace 留痕（各类采样 ≤SAMPLE_CAP）；返回含 skipped/applied/scanned/entries/ghost_entries/missing_entries/hash_drift/unwritable_source/repaired 的报告 dict，applied=bool(apply)。
def reconcile_state(cg, apply: bool = True) -> dict:
    """索引（派生态）vs 盘面真源的三类 diff 对账（reconcile v0 主入口）。

    `apply=False` 为 dry-run（只 diff 报告，不修复、不写盘）。返回报告：
    `{"skipped","applied","scanned","entries","ghost_entries",
      "missing_entries","hash_drift","unwritable_source","repaired"}`。
    幂等：修复后的索引面与盘面一致，二次扫描 diff 为空、零输出零写盘。
    """
    if not enabled():
        return {"skipped": True, "applied": False}
    index_nodes = cg.index.get("nodes") or {}
    by_nid, path_owner, problems = _scan_disk(cg)

    problem_paths = {p["path"] for p in problems}
    ghost, missing, drift = [], [], []
    kept_unreadable = []                    # 条目在、真源暂不可读——保留只告警

    # ①③ 以索引为基准走一遍：多索引条目 + 内容漂移
    for nid, entry in index_nodes.items():
        if nid not in by_nid:
            ep = entry.get("path") or ""
            if ep in problem_paths:
                kept_unreadable.append(nid)     # 真源读不出 ≠ 文件没了：不摘条目
            else:
                ghost.append(nid)               # 盘面无其文件（或已归属他 id）
            continue
        d = by_nid[nid]
        h_raw, h_norm = _disk_hashes(d["content"])
        if entry.get("path") != d["path"] \
                or entry.get("content_hash") not in (h_raw, h_norm):
            drift.append(nid)

    # ② 以盘面为基准走一遍：缺索引条目（仅成功解析的真源参与）
    for nid in by_nid:
        if nid not in index_nodes:
            missing.append(nid)

    repaired = {"unstaged": 0, "staged": 0}
    if apply:
        for nid in ghost:
            cg._unstage(nid)                # tombstone + 立即持久化
            repaired["unstaged"] += 1
        for nid in missing + drift:
            d = by_nid[nid]
            cg._stage(nid, cg._node_entry(d["abs"], d["layer"],
                                          d["fm"], d["content"]))
            repaired["staged"] += 1
        if repaired["unstaged"] or repaired["staged"]:
            cg.flush()                      # 启动期一次收尾落账（不赖 autoflush）

    rep = {
        "skipped": False,
        "applied": bool(apply),
        "scanned": len(by_nid) + len(problems),
        "entries": len(index_nodes),
        "ghost_entries": ghost,
        "missing_entries": missing,
        "hash_drift": drift,
        "unwritable_source": problems,
        "repaired": repaired,
    }
    if kept_unreadable:
        rep["kept_unreadable"] = kept_unreadable

    # 告警 + 留痕（diff 非空才发声；干净库零输出零写盘）
    if ghost or missing or drift or problems or kept_unreadable:
        _warn("启动对账 v0: 幽灵条目=%s 缺失条目=%s 哈希漂移=%s "
              "真源损坏/不可读=%s（%s）"
              % (len(ghost), len(missing), len(drift), len(problems),
                 "已按盘面增量修复索引面" if apply else "dry-run 未修复"))
        for nid in ghost[:SAMPLE_CAP]:
            _warn("  幽灵条目（盘面无文件→摘除）: %s" % (nid,))
        for nid in kept_unreadable[:SAMPLE_CAP]:
            _warn("  条目保留（真源暂不可读，不猜测不摘除）: %s" % (nid,))
        for pr in problems[:SAMPLE_CAP]:
            _warn("  真源损坏/不可读（只告警不改写——T9 边界）: %s [%s]"
                  % (pr["path"], pr["kind"]))
        _trace(cg, {
            "t": time.time(), "op": "reconcile_v0", "apply": bool(apply),
            "scanned": rep["scanned"], "entries": rep["entries"],
            "ghost": ghost[:SAMPLE_CAP], "ghost_n": len(ghost),
            "missing": missing[:SAMPLE_CAP], "missing_n": len(missing),
            "drift": drift[:SAMPLE_CAP], "drift_n": len(drift),
            "problems": problems[:SAMPLE_CAP], "problems_n": len(problems),
            "kept_unreadable": kept_unreadable[:SAMPLE_CAP],
            "repaired": repaired,
        })
    return rep
