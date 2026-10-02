# -*- coding: utf-8 -*-
"""三档自治 · 回滚原语通用化（设计 v0.2 §四/§十一 · 批次③）。

设计 §四「回滚原语（已有，需通用化）」四条在本文档与实现中的落点：

  1. **受保护快照面推广为一切 C/D/B 动作**：`_protected_history/<id>/<时间戳>.md`
     ＋ `_protected_audit.jsonl`（protect.py 面）**面复用、语义泛化**——执行桥
     经 `preimage()` 在**执行时点**调 `protect.snapshot_preimage()` 拍前像；
     `protect.py` 的既有 `snapshot()` / `guard_*` 行为**一字不改**（守卫钉死）。
  2. **软删（D）**：`trash/` ＋ 删除清单的既有 `restore` 接进统一口径——
     `rollback_mutation` 的 D 分支调 `cg.restore(force=True)`；restore 走 add
     全量重建，探针实测与原件有字节差（多 `sensitivity: null` 键），故其后按
     前像**校准**（`calibrated` 读数如实返回，不假装 restore 本身逐字节）。
  3. **合并（B）**：聚合行 `- 【聚合 …】`（`forgetting.AGG_MARK`）**定向剥离**
     （`strip_aggregate_lines`）回退到合并前正文；fm 全量取前像——
     merge_count/last_merge_at/importance/merge_sources/protected 等**不可逆**
     （`-0.05` 会被 `min(1.0,…)` 截断、last_merge_at 旧值无从得知），前像快照
     是唯一诚实来源。
  4. **分数类（E）**：不属本批（设计 §四 明文「分数类：各模块既有 rollback」）。

统一回滚入口 `rollback_mutation(cg, mutation, ...)`：输入＝变更单的**执行时点
载荷**（执行桥补全后的 `mutation_executed` 形态；CLI 从 decisions.jsonl 的
`rec["mutation"]` 读回），按动作类分派 C/B/D 三条原语，回滚后做**残留核对**
（边/索引条目/聚合行三面与前像时点影响面逐位对拍）与**逐字节比对前像**读数。

边界（如实登记）：
  · 前像=执行时点快照——提议时点**不拍**（设计 §四：从提议到 accept 之间目标
    可能被第三方改动，回滚必须撤销本变更本身）；执行记录里的 `before` 引用由
    执行桥补全，故对**未执行**（reject/fail-closed/pending）的变更单，本模块
    fail-closed 拒绝回滚（`rollback_gap`，不允许凭空猜一个前像）。
  · 加密库（覆写 `_seal_content` 的实例）密文层不保证逐字节可复现（每次封装
    熵不同）——`bytes_equal_preimage` 在非加密库上成立（探针实测）；
    加密库语义为「明文内容 + 结构可恢复」，读数如实返回。
  · `restore` 的 tombstone 检查保留语义：回滚是「确认该删除属于本变更」的
    处置，故显式 `force=True` 且 `reason` 写入返回体，不静默绕过。
"""
from __future__ import annotations

import os

from . import chain
from . import forgetting as _forgetting
from . import nodefile
from . import protect
from . import subgraph as _subgraph
from . import trust

__all__ = [
    "RollbackError", "PreimageError",
    "command_for", "preimage", "collect_impact", "read_preimage",
    "strip_aggregate_lines", "rollback_mutation",
]

#: 影响面「索引条目」对拍键（`collect_impact` 采集、残留核对比对，同一份口径）。
_INDEX_KEYS = ("present", "path", "layer", "importance", "merge_count",
               "protected", "tags")
#: 需要前像/可回滚的动作类（设计 §一：B 合并 / C 改写 / D 删除）。
_ROLLBACK_ACTIONS = ("B", "C", "D")


class RollbackError(RuntimeError):
    """回滚无法执行（前像缺失/不可读、动作类未知等）——fail-closed。"""

    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code = code
        self.extra = extra


class PreimageError(RuntimeError):
    """执行时点前像拍摄失败——执行桥据此 fail-closed（一切破坏性动作先留前像）。"""


# 生效条件：pid 非空时返回 `python -X utf8 -m md_cg.rollback_cli --root "<root>" --pid <pid>` 形态的命令串（唯一构造点）；pid 为空时抛 ValueError；
def command_for(root, pid) -> str:
    """回滚命令串（**唯一构造点**，可执行——守卫实测演练同一条串）。

    形态自定为 `md_cg.rollback_cli`：CLI 从 decisions.jsonl 读回该 pid 的
    执行记录（`rec["mutation"]`，含执行时点前像/影响面/回滚命令），按动作类
    分派统一回滚入口。root 用双引号包裹（路径可含空格）。
    """
    if not pid:
        raise ValueError("回滚命令缺 pid：无 pid 即无法定位执行记录——"
                         "fail-closed 不构造命令串。")
    return ('python -X utf8 -m md_cg.rollback_cli --root "%s" --pid %s'
            % (root, pid))


# 生效条件：action 归一后属 _ROLLBACK_ACTIONS 时——forgetting.prior_node 判目标不存在则返回 None（动作不会发生，由调用方走既有 target_missing/not_found 路径）；目标在位于执行时点拍前像（protect.snapshot_preimage）并采集影响面与回滚命令，返回 {"before","impact","rollback"}；拍摄失败（目标在位而快照未落）抛 PreimageError（fail-closed）；action 不属 _ROLLBACK_ACTIONS 时返回 None；
def preimage(cg, action, target, pid=None, reason=""):
    """执行时点前像（快照引用 + 影响面 + 回滚命令）——**唯一采集点**。

    由执行桥（`mdcos._mutation_execute`）在动作原语落盘**之前**调用：
    拍到的快照即「执行前一刻」的盘面（含提议之后、执行之前的第三方改动），
    回滚据此撤销本变更本身（设计 §四：前像=执行时点，不是提议时点）。

    返回 None 的两条路径（都＝动作不会发生，无需留前像）：
      · 动作类不属 B/C/D（未知动作类由执行桥的既有分支 fail-closed）；
      · 目标节点不存在（既有原语会走 target_missing/not_found，执行桥的
        C 分支另有显式 target_missing 检查——本函数不抢它的错误形态）。
    """
    act = str(action or "").strip().upper()
    if act not in _ROLLBACK_ACTIONS:
        return None
    if _forgetting.prior_node(cg, target) is None:
        return None
    rel = protect.snapshot_preimage(cg, target, action=act, pid=pid,
                                    reason=reason)
    if rel is None:
        raise PreimageError(
            "执行时点前像拍摄失败（目标 %s 在位但快照未落盘）——"
            "一切破坏性动作先留前像（设计 §四/§六），本次 fail-closed 未执行。"
            % target)
    return {"before": rel,
            "impact": collect_impact(cg, target),
            "rollback": command_for(cg.root, pid)}


# 生效条件：对任意 cg、node_id 均返回影响面读数 dict——{"edges": {"declared","children","parents"}, "index": {"present","path","layer","importance","merge_count","protected","tags"}, "agg_lines": [...]}（节点不可读时各面取空值/None，不抛）；本函数只读，不产生副作用；
def collect_impact(cg, node_id):
    """执行时点影响面读数（设计 §四：边 / 索引条目 / 聚合行）。

    三个面都是**执行时点**（动作落盘前）的读数——回滚后由
    `rollback_mutation` 重采一次逐位对拍（残留核对：回滚后不得残留本变更
    在任一面的痕迹）。采集走既有单点：`subgraph.children/parents_index`
    （声明式 ∪ 边式）、索引条目直读、聚合行按 `forgetting.AGG_MARK` 字面判。
    """
    try:
        node = cg.get(node_id)
    except Exception:                      # noqa: BLE001 —— 读面失败按空读数采
        node = None
    fm = (node or {}).get("frontmatter") or {}
    content = (node or {}).get("content") or ""
    entry = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(node_id) \
        or {}
    return {
        "edges": {
            "declared": list(fm.get("edges") or []),
            "children": _subgraph.children(cg, node_id),
            "parents": list(_subgraph.parents_index(cg).get(node_id) or []),
        },
        "index": {
            "present": bool(entry),
            "path": entry.get("path"),
            "layer": entry.get("layer"),
            "importance": entry.get("importance"),
            "merge_count": entry.get("merge_count"),
            "protected": bool(entry.get("protected")),
            "tags": list(entry.get("tags") or []),
        },
        # 聚合行行号（1 起）：正文里字面含 AGG_MARK 的行——forgetting.aggregate_line
        # 生成的形态是 `- 【聚合 月-日 时:分】…`；宽判据（含标记即计）与回滚核对同源。
        "agg_lines": [i + 1 for i, l in enumerate(content.splitlines())
                      if _forgetting.AGG_MARK in l],
    }


# 生效条件：rel 指向的文件不存在时抛 RollbackError(code="preimage_missing")；存在则读取并以 cg._open_content(node_id, fm, raw) 对称解封，返回 (fm, content)——content 为 None（无密钥/身份不符）时抛 RollbackError(code="preimage_unreadable")；
def read_preimage(cg, node_id, rel):
    """读执行时点前像文件（**与 snapshot_preimage 对称**：写走 _write_node 封装、
    读走 _open_content 解封）——返回 (fm, content)。

    注意：快照文件以节点文件同款 nodefile 序列化落盘；加密库中其内容为密封
    形态，必须经解封钩子读，直接 nodefile.loads 会把密文当明文再次封装
    （双重封装）。非加密库两钩子恒等（探针实测逐字节一致）。
    """
    p = os.path.join(cg.root, str(rel).replace("/", os.sep))
    if not os.path.isfile(p):
        raise RollbackError("preimage_missing",
                            "前像文件不存在：%s——变更单可能未执行（无前像）"
                            "或快照被移走；fail-closed 不猜一个前像。" % rel)
    with open(p, encoding="utf-8") as f:
        fm, raw = nodefile.loads(f.read())
    content = cg._open_content(node_id, fm, raw)
    if content is None:
        raise RollbackError("preimage_unreadable",
                            "前像不可解封（无密钥/身份不符）：%s。" % rel)
    return fm, content


# 生效条件：content 以 reference 为前缀且其后追加段逐段为「\n + 含 AGG_MARK 的非空行」时，逐段剥掉该追加段返回 (reference + 剩余段, 被剥行列表)；不以 reference 为前缀、追加段形态不符、或 reference 为空时原样返回 (content, [])——不猜、不做字符串手术；
def strip_aggregate_lines(content, reference):
    """定向剥离（设计 §四：合并回滚）——把**合并追加的聚合行**从正文里剥掉。

    为什么是「前缀 + 追加段」判据而不是全局扫行：合并原语（`forgetting.
    reinforce` / `writelimit.converge_into`）对正文是**追加式**的
    （`aggregate_line`：`new_body = body + "\\n" + line`），回滚的目标是回到
    前像正文——精确、可判、不误伤正文里历史遗留的聚合行（它们在前像里就已
    存在，属「合并前正文」的一部分，不该动）。非追加式形态（第三方改写等）
    一律不手术：返回原 content 与空剥离表，由调用方按读数决策。

    返回 `(new_content, removed)`；追加段完全剥净时 `new_content == reference`
    （正常回滚场景，逐字节）。判据与 `forgetting.aggregate_line` 同款字面
    （`AGG_MARK` 常量单点在 forgetting.py，不另写第二份）。
    """
    text = content or ""
    ref = reference or ""
    if not ref or not text.startswith(ref):
        return text, []
    tail = text[len(ref):]
    removed = []
    while tail.startswith("\n"):
        nl = tail.find("\n", 1)
        line = tail[1:] if nl < 0 else tail[1:nl]
        if not line.strip() or _forgetting.AGG_MARK not in line:
            break                          # 空行/非聚合行：停止（不越界手术）
        removed.append(line)
        tail = "" if nl < 0 else tail[nl:]
    # 收尾：追加段的**纯换行尾**（`nodefile.dumps:313` 给不以换行结尾的正文
    # 补过一个尾换行，读回时即多出——探针实测：合并后读回形态为
    # `前像 + "\n" + 聚合行 + "\n"`）在已剥过行时一并剥净，使正常场景逐字节
    # 回到前像；未剥过行（removed 为空）不动分毫。
    if removed and not tail.strip("\n"):
        tail = ""
    return ref + tail, removed


# 生效条件：把 fm/content 以 _write_node 落盘到既有 path，随后按 _node_entry（与 _scan_nodes 同源）重算索引条目写入 index["nodes"] 与 _dirty（索引持久化靠 _dirty→flush→_index_log 重放），并失效 subgraph/chain/trust 三个反查缓存；本函数只被本模块的回滚分支调用；
def _land(cg, node_id, path, fm, content):
    """回滚的**唯一落盘口**：写盘 + 索引重算 + 缓存失效（三步同口径）。

    与 `mdcos.review_decide` merge 分支的定向 upsert 同款（`_node_entry`
    与 `_scan_nodes` 同源，字段集零漂移）；走 `_dirty`（**不走 `_stage`**
    ——它会虚增 bucket 计数，目标已在索引）。
    """
    cg._write_node(node_id, path, fm, content)
    layer = str(fm.get("layer") or "knowledge")
    try:
        e = cg._node_entry(path, layer, fm, content)
    except Exception:                      # noqa: BLE001 —— 重算失败不阻断回滚落盘
        e = None
    if e is not None:
        cg.index["nodes"][node_id] = e
        cg._dirty[node_id] = e
    _subgraph.invalidate_cache(cg)
    chain.invalidate_cache(cg)
    trust.invalidate_cache(cg)


# 生效条件：node_id 的索引条目存在时返回其盘面绝对路径；不存在或条目无 path 时返回 None；
def _disk_path(cg, node_id):
    e = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(node_id) or {}
    p = e.get("path")
    return os.path.join(cg.root, p) if p else None


# 生效条件：对任意路径返回 bytes（不存在/不可读时返回 None——比对判据按 None 处理，不抛）；
def _bytes_of(path):
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


# 生效条件：path 与 rel 都取到字节时返回两者逐字节相等的布尔；任一侧字节取不到时返回 False（不可证即不认——比对判据 fail-closed）；
def _bytes_equal(path, rel_path):
    a, b = _bytes_of(path), _bytes_of(rel_path)
    return a is not None and b is not None and a == b


# 生效条件：C 改写回滚——索引中节点在位（不在位返回 ok False error target_missing）时把前像 (fm0,c0) 落到节点盘面 path（_land）+ flush，返回读数 dict；
def _rollback_rewrite(cg, tgt, fm0, c0):
    path = _disk_path(cg, tgt)
    if path is None or _forgetting.prior_node(cg, tgt) is None:
        return {"ok": False, "error": "target_missing",
                "detail": "C 回滚：目标 %s 不在索引中——本变更之外还有变化，"
                          "fail-closed 不猜落点（如属误删可先 restore）。" % tgt}
    _land(cg, tgt, path, fm0, c0)
    cg.flush()
    return {"ok": True, "restored_path": os.path.relpath(path, cg.root)
                                 .replace("\\", "/"), "method": "preimage"}


# 生效条件：B 合并回滚——目标在位（不在位返回 ok False error target_missing）时先按 strip_aggregate_lines 剥离追加的聚合行，剥离结果与前像正文逐字节相等则正文取剥离结果、否则取前像正文（stripped_ok 如实记录），fm 全量取前像 (fm0)，经 _land 落盘 + flush；返回读数 dict（removed_lines/stripped_ok/method）；
def _rollback_merge(cg, tgt, fm0, c0):
    cur = None
    try:
        cur = cg.get(tgt)
    except Exception:                      # noqa: BLE001
        cur = None
    if not cur:
        return {"ok": False, "error": "target_missing",
                "detail": "B 回滚：目标 %s 不可读——本变更之外还有变化，"
                          "fail-closed 不猜落点。" % tgt}
    path = _disk_path(cg, tgt)
    if path is None:
        return {"ok": False, "error": "target_missing",
                "detail": "B 回滚：目标 %s 索引条目缺 path。" % tgt}
    c1 = cur.get("content") or ""
    stripped, removed = strip_aggregate_lines(c1, c0)
    stripped_ok = stripped == c0
    # 正文取剥离结果（正常场景逐字节==前像）；剥离不精确（追加段含非聚合行等）
    # 时以快照正文为准——回滚的判据是「回到前像」，stripped_ok 如实记录。
    # fm 全量取前像：merge_count/last_merge_at/importance（+0.05 可被 1.0 截断）/
    # merge_sources/protected/lifecycle_state 等均不可逆，前像是唯一诚实来源。
    _land(cg, tgt, path, fm0, stripped if stripped_ok else c0)
    cg.flush()
    return {"ok": True, "restored_path": os.path.relpath(path, cg.root)
                                 .replace("\\", "/"),
            "method": "strip_aggregate_lines" if stripped_ok else "preimage",
            "stripped_ok": stripped_ok, "removed_lines": removed}


# 生效条件：D 删除回滚——先调既有 cg.restore(tgt, force=True)（trash + 删除清单口径）；restore 失败且（错误非 not_in_trash 或节点仍不在库）时返回 ok False（detail 带 restore 原返回体）；restore 成功、或 not_in_trash 而节点已在库（此前已回滚过＝幂等重放）时继续：按前像做逐字节校准（盘面与快照字节不等时经 _land 以 (fm0,c0) 重写，calibrated=True 如实记录——探针实测 restore 重建会多 sensitivity:null 键），返回读数 dict（replayed 标注重放）；
def _rollback_delete(cg, tgt, fm0, c0, rel):
    res = cg.restore(tgt, force=True)
    replayed = (not res.get("ok")) and res.get("error") == "not_in_trash" \
        and _forgetting.prior_node(cg, tgt) is not None
    if not res.get("ok") and not replayed:
        return {"ok": False, "error": res.get("error") or "restore_failed",
                "detail": {"restore": res},
                "hint": "D 回滚走既有 restore（trash + 删除清单）——失败即"
                        "未恢复；如 trash 缺失可核对前像目录。"}
    path = _disk_path(cg, tgt)
    if path is None:
        return {"ok": False, "error": "target_missing",
                "detail": "D 回滚：restore 返回 ok 但索引无条目。"}
    pre_p = os.path.join(cg.root, str(rel).replace("/", os.sep))
    restore_bytes_equal = _bytes_equal(path, pre_p)
    calibrated = False
    if not restore_bytes_equal:
        # 校准（如实）：restore 的 add 全量重建与快照存在字节差（实测 =
        # 多 `sensitivity: null` 键）——回滚的判据是「回到前像」，故以快照
        # 重写一次；`restore_bytes_equal=False` 读数保留，不假装 restore
        # 本身逐字节。
        _land(cg, tgt, path, fm0, c0)
        calibrated = True
    cg.flush()
    return {"ok": True, "restored_path": os.path.relpath(path, cg.root)
                                 .replace("\\", "/"),
            "method": "restore+preimage_calibration" if calibrated
                      else "restore",
            "replayed": replayed,
            "calibrated": calibrated,
            "restore_bytes_equal": restore_bytes_equal}


# 生效条件：before_impact 与 after 两个影响面 dict（缺面按空 dict）逐面返回对拍布尔——{"agg_lines_restored","edges_restored","index_restored"}；
def _residual(before_impact, after):
    bi = before_impact if isinstance(before_impact, dict) else {}
    return {
        "agg_lines_restored": (after.get("agg_lines") or [])
                              == (bi.get("agg_lines") or []),
        "edges_restored": (after.get("edges") or {}) == (bi.get("edges") or {}),
        "index_restored": {k: (after.get("index") or {}).get(k)
                           for k in _INDEX_KEYS}
                          == {k: (bi.get("index") or {}).get(k)
                              for k in _INDEX_KEYS},
    }


# 生效条件：mutation 为 dict 且含非空 target 与 before（否则返回 ok False error mutation_missing/rollback_gap 带 hint）；before 文件不可读按 RollbackError(code) 返回 ok False；动作类属 C/B/D 时按对应分支回滚，成功再重采影响面做残留对拍并做逐字节比对，返回 {"ok": True, "action","target","preimage","restored_path","bytes_equal_preimage","residual","method",...}；动作类不属 C/B/D 时返回 ok False error rollback_action_unknown；本函数不抛（可预期错误一律返回体）；
def rollback_mutation(cg, mutation, reason="", actor=None):
    """统一回滚入口（设计 §四 四条：C/B/D 分派 + 残留核对 + 逐字节比对）。

    输入＝**执行时点载荷**（`autonomy_modes.mutation_executed` 形态，含
    action/target/before/impact/rollback）；CLI 从 decisions.jsonl 的
    `rec["mutation"]` 读回。`reason`/`actor` 进返回体（审计由各分支的
    落盘/restore 留痕承担，本模块不另写第二套台账）。
    """
    if not isinstance(mutation, dict):
        return {"ok": False, "error": "mutation_missing",
                "hint": "回滚入口需要变更单的执行时点载荷（dict）——"
                        "decisions.jsonl 的 rec[\"mutation\"]。"}
    act = str(mutation.get("action") or "").strip().upper()
    tgt = str(mutation.get("target") or "").strip()
    rel = mutation.get("before")
    if not tgt:
        return {"ok": False, "error": "mutation_missing",
                "hint": "载荷缺 target——无法定位回滚对象。"}
    if not rel:
        return {"ok": False, "error": "rollback_gap",
                "hint": "载荷缺 before（执行时点前像引用）：该变更单**未执行**"
                        "（reject / fail-closed / pending）或执行记录不完整——"
                        "fail-closed 不猜一个前像（前像必须来自执行时点）。"}
    if act not in _ROLLBACK_ACTIONS:
        return {"ok": False, "error": "rollback_action_unknown",
                "action": act or None,
                "hint": "回滚只覆盖 C 改写 / B 合并 / D 删除（设计 §四）；"
                        "动作类 %r 未定义回滚——fail-closed。" % (act or None)}
    try:
        fm0, c0 = read_preimage(cg, tgt, rel)
    except RollbackError as exc:
        return {"ok": False, "error": exc.code, "detail": str(exc),
                "action": act, "target": tgt, "preimage": rel}
    if act == "C":
        res = _rollback_rewrite(cg, tgt, fm0, c0)
    elif act == "B":
        res = _rollback_merge(cg, tgt, fm0, c0)
    else:                                  # "D"
        res = _rollback_delete(cg, tgt, fm0, c0, rel)
    if not res.get("ok"):
        out = dict(res)
        out.update({"action": act, "target": tgt, "preimage": rel})
        return out
    # 残留核对（设计 §十一 红项面）：重采影响面，与前像时点记录逐面对拍。
    after = collect_impact(cg, tgt)
    residual = _residual(mutation.get("impact"), after)
    # 逐字节比对前像（设计 §十一）：盘面 vs 快照文件。
    pre_p = os.path.join(cg.root, str(rel).replace("/", os.sep))
    disk_p = _disk_path(cg, tgt)
    out = {"ok": True, "action": act, "target": tgt, "preimage": rel,
           "rollback_command": mutation.get("rollback") or "",
           "reason": str(reason or ""), "actor": actor,
           "bytes_equal_preimage": _bytes_equal(disk_p, pre_p),
           "residual": residual, "impact_after": after}
    out.update(res)
    return out
