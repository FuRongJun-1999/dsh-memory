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
from . import fsutil
from .fsutil import append_jsonl

#: 关闭开关：仅当 `MDCG_RECONCILE` 的 strip 后取值**恰好为 "0"** 时关闭
#: （缺省开；其它取值一律视为开——开关只回答「关没关」，不承担配置语义）。
ENV_SWITCH = "MDCG_RECONCILE"

#: 留痕文件（root 下，append-only，与 `_write_2pc.jsonl` / `_protected_audit.jsonl`
#: 同一「独立审计文件」惯例；**仅在 diff 非空时写入**，干净库零写盘）。
TRACE_FILE = "_reconcile.jsonl"

#: 留痕/告警里每类异常的采样上限（防大库首轮修复把日志/告警撑成洪水）。
SAMPLE_CAP = 20

#: 三态戳名（R-544）：落在 `sustain.net_dir()`（aux 目录，**不在库根**）。
#: 为什么不在库根写：`test_reconcile_v0` 1e 钉着「干净库零写盘（无留痕文件）」这条
#: 设计性质，库根不许因为「我跑过」而多出文件；而 aux 目录本就是运行时状态位，
#: 戳是单文件原子覆写、不增长。
STAMP_NAME = "reconcile"

#: `status()` 的读数集合（判据是「三种情况读数不同」）：
#:   never_run  从来没有对账跑过（无戳）
#:   disabled   跑了但被 `MDCG_RECONCILE=0` 关掉（戳里 state=disabled）
#:   clean      跑了、开着、diff 全零
#:   dirty      跑了、开着、有 diff（附三类计数与是否已修）
STATES = ("never_run", "disabled", "clean", "dirty")


# 生效条件：写三态戳（best-effort：任何异常吞掉返回 None，观测面不得反过来炸启动序列）；state 取 STATES 之一，extra 的 None 值丢弃。
def _stamp(state: str, **extra):
    """把「这次对账是什么态」写成 aux 目录下的单文件戳（原子覆写，不增长）。"""
    try:
        from . import sustain as _s        # 延迟导入：避免 mdcg↔reconcile↔sustain 环
        return _s.write_stamp(STAMP_NAME, state=state, **extra)
    except Exception:                      # noqa: BLE001 —— 观测面增益，不得炸调用方
        return None


# 生效条件：无入参必需项；读 aux 目录的三态戳并返回 {"state","age","ts","applied","ghost","missing","drift","raw","detail"}——无戳或戳损坏时 state="never_run"，戳内 state 不在 STATES 时按 never_run 记并保留 raw。
def status(cg=None) -> dict:
    """对账三态读数（R-544）：`never_run` / `disabled` / `clean` / `dirty`。

    修前三种情况在盘面**完全不可区分**：干净库不写留痕、被 `MDCG_RECONCILE=0`
    关掉也什么都不写、从来没跑过同样什么都没有——于是「对账到底有没有在工作」
    只能靠读代码猜。修后每次进入 `reconcile_state` 都落一枚 aux 戳。
    """
    try:
        from . import sustain as _s
        rec = _s.read_stamp(STAMP_NAME)
    except Exception as e:                 # noqa: BLE001
        return {"state": "never_run", "age": None, "ts": None, "raw": None,
                "detail": "读戳失败：%s: %s" % (type(e).__name__, e)}
    if not rec:
        return {"state": "never_run", "age": None, "ts": None, "raw": None,
                "detail": "从未对账（aux 目录无 reconcile 戳）"}
    st = rec.get("state")
    if st not in STATES:
        return {"state": "never_run", "age": rec.get("age"), "ts": rec.get("ts"),
                "raw": rec, "detail": "戳内 state 非法（%r）" % (st,)}
    out = {"state": st, "age": rec.get("age"), "ts": rec.get("ts"),
           "applied": rec.get("applied"), "ghost": rec.get("ghost"),
           "missing": rec.get("missing"), "drift": rec.get("drift"),
           "raw": rec, "detail": None}
    if st == "disabled":
        out["detail"] = "被 MDCG_RECONCILE=0 关闭（对账没执行）"
    elif st == "clean":
        out["detail"] = "已执行，diff 全零（干净）"
    elif st == "dirty":
        out["detail"] = ("已执行且有 diff：幽灵 %s / 缺失 %s / 漂移 %s（%s）"
                         % (rec.get("ghost"), rec.get("missing"), rec.get("drift"),
                            "已按盘面修复" if rec.get("applied") else "dry-run 未修"))
    return out


# 生效条件：读 MDCG_RECONCILE 环境变量（未设按空串），strip 后等于 "0" 返回 False，其余（含未设）返回 True。
def enabled() -> bool:
    """对账开关（缺省开；`MDCG_RECONCILE=0` 关闭）。"""
    return os.environ.get(ENV_SWITCH, "").strip() != "0"


# 生效条件：给定 cg 且其 root 属性可参与 os.path.join 时，恒返回 os.path.join(cg.root, TRACE_FILE)，无分支与早退。
def trace_path(cg) -> str:
    return os.path.join(cg.root, TRACE_FILE)


# 生效条件：content（nodefile.loads 切出的盘面正文，含尾换行）为 str 时返回 nodefile.content_hash(content)（单值）。
def _disk_hash(content: str) -> str:
    # issue #758（在 #741 之后收单值）：content_hash 内部已先 normalize_body（补一个尾换行）再哈希，
    # 与索引条目口径**同源** ⇒ 「双形态接受集」的第二元素（对去尽尾换行的正文再哈希）在常盘形态下
    # 恒等、仅在「≥2 个尾换行」时不等——而**索引侧**已无写点产出该形态（normalize_body 只补不剥） ⇒ 第二元素不可达，收成单值。
    # 副作用（既定意图）：收紧了旧容忍面——仅在「索引与盘面形态不一致」（手改/外部写者/#741 前 legacy 条目）时判 drift；经写路径落盘的 ≥2 尾换行两侧一致，不误报，旧行为靠第二元素蒙混。
    return nodefile.content_hash(content or "")


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
                # R-202b：判据消费单点——BOM 剥离与「以分隔行开头」的行语义只在
                # nodefile.starts_with_delim 里写一次（R-202 的口径）；此处再要求
                # 「完整起始分隔行」（--- + 行尾），避免把 `---abc` 这类正文误判成
                # 无闭合残头。不剥 BOM 的旧判据会让 BOM 残头在此判假、被当「缺失
                # 条目」重新 _stage 回索引，与 _scan_nodes 的隔离结论互相打脸
                # （实测 before index=[] → after index=['broken']）。
                if not fm and nodefile.starts_with_delim(text) and (
                        text.lstrip("\ufeff").startswith("---\n")
                        or text.lstrip("\ufeff").startswith("---\r\n")):
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
# #326-④：append_jsonl 不再上抛、以 False 报写失败——本处**仍容忍**（best-effort
# 簿记），但失败不再静默：源头已记 fsutil.APPEND_FAILURES + 有界 stderr 告警
# （B 面单点）。显式消费返回值：不留裸调用（守卫 AST 钉子会抓）。
        _ok = append_jsonl(trace_path(cg), record)
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
        # R-544：被关掉也要落戳——否则「从没跑过」与「被关」在盘面上一模一样。
        _stamp("disabled", applied=False)
        return {"skipped": True, "applied": False}
    index_nodes = cg.index.get("nodes") or {}
    by_nid, path_owner, problems = _scan_disk(cg)

    problem_paths = {p["path"] for p in problems}
    ghost, missing, drift = [], [], []
    kept_unreadable = []                    # 条目在、真源暂不可读——保留只告警

    # ①③ 以索引为基准走一遍：多索引条目 + 内容漂移
    for nid, entry in list(index_nodes.items()):
        if nid not in by_nid:
            ep = entry.get("path") or ""
            if ep in problem_paths:
                kept_unreadable.append(nid)     # 真源读不出 ≠ 文件没了：不摘条目
            else:
                ghost.append(nid)               # 盘面无其文件（或已归属他 id）
            continue
        d = by_nid[nid]
        h_disk = _disk_hash(d["content"])
        if entry.get("path") != d["path"] \
                or entry.get("content_hash") != h_disk:
            drift.append(nid)

    # ② 以盘面为基准走一遍：缺索引条目（仅成功解析的真源参与）
    for nid in by_nid:
        if nid not in index_nodes:
            missing.append(nid)

    from . import protect as _prot          # #463：同 refindex，闸放「静默摘除点」
    repaired = {"unstaged": 0, "staged": 0, "skipped_protected": []}
    if apply:
        # R-543（2026-11-10）：**修复动作必须在锁内、且锁内复核**。
        # 修前：diff 在锁外算完就逐个 `_unstage` / `_stage`，不持任何锁 —— 启动对账
        # 跑在后台线程里（`mcp_server._reconcile_bg`），同一进程的 stdin 请求线程
        # 同时在写节点；两个写者共用 `cg.index` / `cg._dirty` 却没有任何互斥，
        # 「并发 reconcile + write 索引错乱」因此可复现：对账拿锁外快照把**刚写进来
        # 的节点**当幽灵摘掉，或把已被并发写者以新内容装上的条目用旧哈希覆盖回去。
        # 修后：逐节点取 `node_write_lock`（与写路径同一把 OS 级锁、同 id 同锁），
        # 并在锁内**重新确认**一次盘面/索引现状，只对仍然成立的那部分动手。
        # 为什么不是一把根级大锁：那会把对账（实测 2.92 秒 / 31,688 节点）压到
        # 写路径前面，等于给启动期加一次全库停顿；按节点锁既精确又不阻塞别的 id。
        for nid in ghost:
            # #463（SEC·P0）：受保护节点不得被启动对账静默摘索引（跳过并记账，不新增形状）。
            try:
                _prot.guard_forget(cg, nid)
            except _prot.ProtectionError:
                repaired["skipped_protected"].append(nid)
                continue
            with fsutil.node_write_lock(cg, nid):
                # 锁内复核：条目可能已被并发写者摘掉；文件也可能刚被写回盘面
                # （旧路径见 by_nid 时它不在，锁内再 stat 一次才算数）。
                entry = (cg.index.get("nodes") or {}).get(nid)
                if not entry:
                    continue
                ep = entry.get("path") or ""
                if ep and os.path.isfile(os.path.join(cg.root, ep)):
                    continue
                cg._unstage(nid)            # tombstone + 立即持久化
                repaired["unstaged"] += 1
        for nid in missing + drift:
            d = by_nid[nid]
            h_disk = _disk_hash(d["content"])
            with fsutil.node_write_lock(cg, nid):
                # 锁内复核：并发写者若已把该 id 以**同一份盘面内容**装好，就不再重复装；
                # 若已装成别的版本（哈希不同），仍以盘面为真源（对账的既定口径）。
                cur = (cg.index.get("nodes") or {}).get(nid)
                if cur is not None and cur.get("content_hash") == h_disk \
                        and cur.get("path") == d["path"]:
                    continue
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

    # R-544：三态戳（disabled / clean / dirty）。**不进库根**，故「干净库零写盘」
    # 那条性质不受影响；戳是单文件原子覆写，不随运行次数增长。
    _stamp("dirty" if (ghost or missing or drift or problems) else "clean",
           applied=bool(apply), ghost=len(ghost), missing=len(missing),
           drift=len(drift), problems=len(problems),
           repaired_unstaged=repaired["unstaged"],
           repaired_staged=repaired["staged"])

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
