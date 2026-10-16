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
import sys

import os
import time

from . import chain
from . import forgetting as _forgetting
from . import fsutil
from . import nodefile
from . import protect
from . import subgraph as _subgraph
from . import trust

__all__ = [
    "RollbackError", "PreimageError",
    "command_for", "preimage", "collect_impact", "read_preimage",
    "strip_aggregate_lines", "rollback_mutation",
    "node_fingerprint", "preimage_fingerprint",
]

#: 影响面「索引条目」对拍键（`collect_impact` 采集、残留核对比对，同一份口径）。
_INDEX_KEYS = ("present", "path", "layer", "importance", "merge_count",
               "protected", "tags")
#: 需要前像/可回滚的动作类（设计 §一：B 合并 / C 改写 / D 删除）。
_ROLLBACK_ACTIONS = ("B", "C", "D")
#: 盘面指纹取样的 frontmatter 键（**执行后像 / 前像 / 现盘面三侧同口径**）——
#: 只取判据相关的稳定键：内容哈希之外，「执行之后又被标保护 / 换层 / 重判验证态」
#: 同样属于「目标被动过」。刻意**不含** updated_at 之类每次落盘都变的键（否则
#: 「内容没变、只重写了一遍」会大面积误判成漂移，把合法回滚一并拒掉）。
_FINGERPRINT_FM_KEYS = ("immutable", "protection_reason", "layer", "sensitivity",
                        "verification_state", "lifecycle_state", "self_state",
                        "protected")
#: 回滚留痕的审计 op（`_audit.jsonl` 一行）——常量单点，守卫按同名常量取用。
ROLLBACK_AUDIT_OP = "rollback"


# 生效条件：node 为 cg.get 返回形态（None/非 dict/假值＝目标不在盘）时返回 {"present": False}；否则返回 {"present": True, "content_hash": nodefile.content_hash(content), "fm": {k: fm.get(k) for k in _FINGERPRINT_FM_KEYS}}（正文与 frontmatter 都取不到时按空串/空 dict 计，不抛）；
def node_fingerprint(node):
    """盘面指纹（正文内容哈希 + 判据相关 fm 键）——**唯一实现**。

    执行桥（`mdcos._mutation_execute`，执行落盘**之后**采「后像」）与回滚入口
    （回滚**之前**采「现盘面」）共用同一份口径——两侧各写一份哈希/键表，
    漂移就会让闸门永远「匹配成功」而静默失效（同 `nodefile.content_hash`
    的纪律：全仓唯一实现）。
    """
    if not isinstance(node, dict) or not node:
        return {"present": False}
    fm = node.get("frontmatter") or {}
    content = node.get("content") or ""
    return {"present": True,
            "content_hash": nodefile.content_hash(content),
            "fm": {k: fm.get(k) for k in _FINGERPRINT_FM_KEYS}}


# 生效条件：fm/content 传入（缺省按空 dict/空串）时返回与 node_fingerprint 同形态的前像盘面指纹（present 恒 True、fm 只取 _FINGERPRINT_FM_KEYS 键）；
def preimage_fingerprint(fm, content):
    """前像盘面指纹——用于「现盘面是否**已经**等于前像」的幂等重放判定。"""
    fm = fm or {}
    return {"present": True,
            "content_hash": nodefile.content_hash(content or ""),
            "fm": {k: fm.get(k) for k in _FINGERPRINT_FM_KEYS}}


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


# 生效条件：rel 指向的文件不存在时抛 RollbackError(code="preimage_missing")；存在则读取并以 cg._open_content(node_id, fm, raw) 对称解封，返回 (fm, content)——content 为 None（无密钥/身份不符）时抛 RollbackError(code="preimage_unreadable")；文件含坏字节（非 UTF-8）无法解析时同样抛 RollbackError(code="preimage_unreadable")（fail-closed，不裸抛 UnicodeDecodeError）；
def read_preimage(cg, node_id, rel):
    """读执行时点前像文件（**与 snapshot_preimage 对称**：写走 _write_node 封装、
    读走 _open_content 解封）——返回 (fm, content)。

    注意：快照文件以节点文件同款 nodefile 序列化落盘；加密库中其内容为密封
    形态，必须经解封钩子读，直接 nodefile.loads 会把密文当明文再次封装
    （双重封装）。非加密库两钩子恒等（探针实测逐字节一致）。

    文件含坏字节（非 UTF-8）无法解析时抛 RollbackError(code="preimage_unreadable")
    ——fail-closed，不裸抛 UnicodeDecodeError。
    """
    p = os.path.join(cg.root, str(rel).replace("/", os.sep))
    if not os.path.isfile(p):
        raise RollbackError("preimage_missing",
                            "前像文件不存在：%s——变更单可能未执行（无前像）"
                            "或快照被移走；fail-closed 不猜一个前像。" % rel)
    try:
        with open(p, encoding="utf-8") as f:
            fm, raw = nodefile.loads(f.read())
    except UnicodeDecodeError as exc:
        # 坏字节/非 UTF-8：fail-closed——绝不让 UnicodeDecodeError 裸抛逃逸
        raise RollbackError("preimage_unreadable",
                            "前像文件坏字节 / 非 UTF-8 无法解析：%s（%s）——"
                            "fail-closed 不回滚。" % (rel, exc))
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


# 生效条件：落盘前先过保护闸——protect.is_immutable(cg, node_id) 为真且 preimage_fm 未带同一保护位（immutable is True 或 layer ∈ PROTECTED_LAYERS）时，force 为假即返回拒绝体 dict（不写盘）；随后尝试 protect.snapshot(cg, node_id) 把将被覆盖的当前版本留档（失败不阻断），再经 cg._write_node 落盘、按 _node_entry 重算索引条目写入 index["nodes"] 与 _dirty 并失效 subgraph/chain/trust 三个反查缓存，返回 None（落盘完成）；本函数只被本模块的回滚分支调用；
def _land(cg, node_id, path, fm, content, preimage_fm=None, force=False,
          actor=None):
    """回滚的**唯一落盘口**：保护闸 + 前像快照 + 写盘 + 索引重算 + 缓存失效。

    与 `mdcos.review_decide` merge 分支的定向 upsert 同款（`_node_entry`
    与 `_scan_nodes` 同源，字段集零漂移）；走 `_dirty`（**不走 `_stage`**
    ——它会虚增 bucket 计数，目标已在索引）。

    #352-A（2026-10-15）：本口此前**三闸全无**——直接 `cg._write_node`，
    不走 `protect.guard_overwrite` / `guard_write`，不留 `protect.snapshot`
    前像副本，不写 `_audit`。后果：目标在执行之后被标 immutable 时，回滚
    照样覆写并把 immutable 标记一并清掉，且事后无从知道被覆盖的是哪一版。

    保护判据（**避免过度收紧**）：只在「现盘面受保护 **而** 执行时点前像不带
    同一保护位」时拒绝——保护位是本变更**之后**加的，覆写会把它抹掉。若前像
    本身就带保护位（原节点本就 immutable / 在保护层），回滚只是把该保护位
    如实还原，属正常回滚，**不拦**（否则 D 删除回滚永远回不来受保护节点）。

    返回 None＝落盘完成；返回 dict＝拒绝体（`ok: False` + `error`），调用方
    据此 fail-closed 返回，绝不静默覆写。
    """
    try:
        prot, why = protect.is_immutable(cg, node_id)
    except Exception:                      # noqa: BLE001 —— 判定失败按不拦（读面异常不升级成拒服务）
        prot, why = False, ""
    if prot and not force:
        _pre = preimage_fm or {}
        _pre_prot = (_pre.get("immutable") is True
                     or str(_pre.get("layer") or "") in protect.PROTECTED_LAYERS)
        if not _pre_prot:
            return {"ok": False, "error": "protected_target",
                    "protection": why,
                    "detail": "回滚目标 %s 现受写保护（%s），而执行时点前像不带"
                              "该保护位——保护位是本变更**之后**加的，覆写会把它"
                              "一并清掉；fail-closed 未覆写（确认后加 --force）。"
                              % (node_id, why),
                    "hint": "如确需回滚：先解除保护（mdcg_protect 面）或对本单"
                            "显式 --force；二者都会留痕。"}
    # 落盘前把**将被覆盖的当前版本**留档（protect 面既有单点，不另写第二套）。
    try:
        protect.snapshot(cg, node_id)
    except Exception:                      # noqa: BLE001 —— 留档失败不阻断回滚本身
        pass
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


# 生效条件：C 改写回滚——索引中节点在位（不在位返回 ok False error target_missing）时把前像 (fm0,c0) 落到节点盘面 path（_land；保护闸拒绝即原样返回该拒绝体）+ flush，返回读数 dict；
def _rollback_rewrite(cg, tgt, fm0, c0, force=False, actor=None):
    path = _disk_path(cg, tgt)
    if path is None or _forgetting.prior_node(cg, tgt) is None:
        return {"ok": False, "error": "target_missing",
                "detail": "C 回滚：目标 %s 不在索引中——本变更之外还有变化，"
                          "fail-closed 不猜落点（如属误删可先 restore）。" % tgt}
    refuse = _land(cg, tgt, path, fm0, c0, preimage_fm=fm0, force=force,
                   actor=actor)
    if refuse is not None:
        return refuse
    cg.flush()
    return {"ok": True, "restored_path": os.path.relpath(path, cg.root)
                                 .replace("\\", "/"), "method": "preimage"}


# 生效条件：B 合并回滚——目标在位（不在位返回 ok False error target_missing）时先按 strip_aggregate_lines 剥离追加的聚合行，剥离结果与前像正文逐字节相等则正文取剥离结果、否则取前像正文（stripped_ok 如实记录），fm 全量取前像 (fm0)，经 _land 落盘 + flush；返回读数 dict（removed_lines/stripped_ok/method）；
def _rollback_merge(cg, tgt, fm0, c0, force=False, actor=None):
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
    refuse = _land(cg, tgt, path, fm0, stripped if stripped_ok else c0,
                   preimage_fm=fm0, force=force, actor=actor)
    if refuse is not None:
        return refuse
    cg.flush()
    return {"ok": True, "restored_path": os.path.relpath(path, cg.root)
                                 .replace("\\", "/"),
            "method": "strip_aggregate_lines" if stripped_ok else "preimage",
            "stripped_ok": stripped_ok, "removed_lines": removed}


# 生效条件：D 删除回滚——先调既有 cg.restore(tgt, force=True)（trash + 删除清单口径）；restore 失败且（错误非 not_in_trash 或节点仍不在库）时返回 ok False（detail 带 restore 原返回体）；restore 成功、或 not_in_trash 而节点已在库（此前已回滚过＝幂等重放）时继续：按前像做逐字节校准（盘面与快照字节不等时经 _land 以 (fm0,c0) 重写，calibrated=True 如实记录——探针实测 restore 重建会多 sensitivity:null 键），返回读数 dict（replayed 标注重放）；
def _rollback_delete(cg, tgt, fm0, c0, rel, force=False, actor=None):
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
        refuse = _land(cg, tgt, path, fm0, c0, preimage_fm=fm0, force=force,
                       actor=actor)
        if refuse is not None:
            return refuse
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


# 生效条件：cg 为 None 或 cg.get 抛异常/返回假值时返回 None，否则返回 cg.get(node_id) 的结果（读面失败一律按「目标不可读」计，不抛）；
def _node_of(cg, node_id):
    if cg is None:
        return None
    try:
        return cg.get(node_id)
    except Exception:                      # noqa: BLE001
        return None


# 生效条件：pid 为真且 cg.decisions() 可读时，返回本 pid 最后一条 decision=="accept" 记录**之后**、decision=="accept" 且 rec["mutation"]["target"] 等于 tgt 的记录 pid 列表（顺序同盘面）；**取不到顺序（pid 为空 / 无该 pid / decisions 不可读）时返回 None**（＝判据不可用，调用方据此不拦——不把「取不到证据」升级成拒绝）；
def _later_executions(cg, tgt, pid):
    """本单执行之后、同目标的 accept 执行记录（旧执行记录无 after_hash 时的兜底判据）。

    decisions.jsonl 是 append-only，故「盘面顺序」即「时间顺序」——同一 pid 的
    最后一条 accept 之后出现的、target 相同的 accept 执行记录，就是「本单之后
    目标又被执行过一次」的证据面。
    """
    if not pid or cg is None:
        return None
    try:
        rows = list(cg.decisions())
    except Exception:                      # noqa: BLE001
        return None
    idx = None
    for i, r in enumerate(rows):
        if r.get("pid") == pid and r.get("decision") == "accept":
            idx = i
    if idx is None:
        return None
    out = []
    for r in rows[idx + 1:]:
        if r.get("decision") != "accept":
            continue
        mu = r.get("mutation")
        if isinstance(mu, dict) and str(mu.get("target") or "") == tgt:
            out.append(r.get("pid"))
    return out


# 生效条件：对任意 cg/tgt/act/rel/res 都无条件返回布尔——先尝试 cg._audit("rollback", tgt, **meta)（MdCGOS 面，带 tenant/session/clearance 归因），失败或 cg 无 _audit 时退化为向 cg.root/_audit.jsonl 追加一行 {"t","op":"rollback","id","actor","action","pid","preimage","reason","method","bytes_equal_preimage"}；两种情况都不抛（留痕失败不阻断已完成的回滚）；
def _audit_rollback(cg, tgt, act, rel, res, actor=None, pid=None, reason=""):
    """回滚留痕（`_audit.jsonl` 一行 op="rollback"）——#352-A。

    改前本模块的 docstring 写「审计由各分支的落盘 / restore 留痕承担」，而
    `_land` 这一支（C/B 以及 D 的校准路径）**一行审计都不写**：回滚是唯一
    不写台账的破坏性写口（步骤④准入读数第 3 条即为「R3 破坏可逆读数缺失」）。
    本函数是回滚留痕的**唯一落点**（op 常量集中在 `ROLLBACK_AUDIT_OP`）。
    """
    meta = {"action": act, "pid": pid, "preimage": rel,
            "reason": str(reason or ""), "method": res.get("method"),
            "bytes_equal_preimage": res.get("bytes_equal_preimage")}
    fn = getattr(cg, "_audit", None)
    if callable(fn):
        try:
            fn(ROLLBACK_AUDIT_OP, tgt, **meta)
            return True
        except Exception as e:             # noqa: BLE001 —— 退化为直写
            # #472 站点 2：**退化不再静默**（原为 `pass`）——写 stderr 留痕，并把本行标记为
            # 「链外（已知退化）」，使 mdcos._audit_chain_verify 判为 known_degraded（**软信号**），
            # **而非** unknown_foreign（后者是「有人插入」，安全要报）——**两者不得同一信号**。
            try:
                from .mdcos import AUDIT_KNOWN_DEGRADED as _KD
            except Exception:              # 循环导入等：退化为字面量
                # ⚠️ **已登记的已知偏差**（issue #472，Lead 裁定「允许但必须登记」）：
                #   1) **这是回落副本、不是真源** —— 真源是 `mdcos.AUDIT_KNOWN_DEGRADED`；
                #   2) **回落触发条件**：`from .mdcos import ...` 失败（循环导入等）；
                #   3) **已知漂移风险**：若有人只改 mdcos 侧的值，**回落到字面量的这条路径会静默
                #      地用旧值** —— 这是「两份副本必然漂」在语言机制层的又一次落地。
                #   ⇒ 该偏差**已被腿钉住**：`md_cg/test_issue472_audit_chain.py` 的 C2 腿断言
                #      「本回落字面量 == mdcos.AUDIT_KNOWN_DEGRADED 的真值」（AST 静态比对，
                #      不需构造循环导入 ⇒ 可行）。
                _KD = "AUDIT_KNOWN_DEGRADED"
            sys.stderr.write("[rollback] cg._audit 不可用，退化直写（链外·已知退化）：%s: %s"
                             % (type(e).__name__, e) + chr(10))
            _degraded_mark = _KD
    else:
        _degraded_mark = None
    rec = {"t": time.time(), "op": ROLLBACK_AUDIT_OP, "id": tgt,
           "actor": actor}
    if _degraded_mark:
        rec["chain"] = _degraded_mark
    rec.update(meta)
    try:
        fsutil.append_jsonl(os.path.join(cg.root, "_audit.jsonl"), rec)
        return True
    except Exception:                      # noqa: BLE001
        return False


# 生效条件：mutation 为 dict 且含非空 target 与 before（否则返回 ok False error mutation_missing/rollback_gap 带 hint）；before 文件不可读按 RollbackError(code) 返回 ok False；现盘面与执行后像不等且未显式 force 时返回 ok False error drifted_since_execute（现盘面已等于前像＝幂等重放，放行）；dry_run 为真时只返回读数不落盘；动作类属 C/B/D 时按对应分支回滚，成功再重采影响面做残留对拍、做逐字节比对并向 _audit.jsonl 写一行 op="rollback"，返回 {"ok": True, "action","target","preimage","restored_path","bytes_equal_preimage","residual","method",...}；动作类不属 C/B/D 时返回 ok False error rollback_action_unknown；本函数不抛（可预期错误一律返回体）；
def rollback_mutation(cg, mutation, reason="", actor=None, force=False,
                      pid=None, dry_run=False):
    """统一回滚入口（设计 §四 四条：C/B/D 分派 + 残留核对 + 逐字节比对）。

    输入＝**执行时点载荷**（`autonomy_modes.mutation_executed` 形态，含
    action/target/before/impact/rollback[/after_hash]）；CLI 从 decisions.jsonl
    的 `rec["mutation"]` 读回。`reason`/`actor`/`pid` 进返回体与回滚留痕。

    #352-A（2026-10-15）**漂移闸**（`drifted_since_execute`）：回滚的语义是
    「撤销**本变更本身**、不抹第三方改动」（`autonomy_modes.mutation_payload`
    :551-555 明文），而改前只处理了「提议→执行之间」的第三方改动（前像取执行
    时点），**没处理「执行→回滚之间」的改动**——回滚用执行时点前像**整体覆写**，
    执行之后写进去的正文（含另一张合并单追加的聚合行、删除后同 id 的重建、
    新增的 immutable 标记）一并消失，回执还报 `ok:True`。本闸的比较面：

      · `after_hash`（执行桥在执行落盘**之后**采的「后像」指纹，
        `md_cg/mdcos.py` 的 `_mutation_execute` 处补全）与现盘面指纹不等 ⇒ 拒；
      · 旧执行记录（无 `after_hash`）⇒ 退化为扫 decisions.jsonl 同目标、本单
        **之后**的 accept 执行记录，有则拒；顺序取不到（pid 未知）时不拦
        （不把「取不到证据」升级成拒绝）。

    **幂等重放豁免**：现盘面**已经等于前像**时直接放行——回滚本身已做过（或
    节点已处于前像状态），此时「覆写」是无操作，抹不掉任何东西。这条是既有
    守卫 Q/R/S 组的「回滚命令串二次演练（幂等重放，rc=0）」得以保持的判据。

    `force=True` 跳过漂移闸与 `_land` 的保护闸（`rollback_cli --force`）；
    `dry_run=True` 只回报将被覆写的差异、不落盘。
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
    # ---- 漂移闸（#352-A）：执行之后目标又被写过 ⇒ fail-closed，不整体覆写 ----
    cur_fp = node_fingerprint(_node_of(cg, tgt))
    pre_fp = preimage_fingerprint(fm0, c0)
    drift = None
    if cur_fp != pre_fp and not force:     # 相等＝幂等重放，放行（见 docstring）
        want = mutation.get("after_hash")
        if isinstance(want, dict):
            if cur_fp != want:
                drift = {"ok": False, "error": "drifted_since_execute",
                         "action": act, "target": tgt, "preimage": rel,
                         "current": cur_fp, "expected_after_execute": want,
                         "hint": "本单**执行之后**目标又被写过——回滚会用执行时点"
                                 "前像整体覆写，把这些写入一并抹掉（设计 §四："
                                 "回滚只撤销本变更本身、不抹第三方改动）。"
                                 "已 fail-closed 未覆写：先核对上面的 current / "
                                 "expected_after_execute 差异，确需回滚加 --force。",
                         "reason": str(reason or ""), "actor": actor}
        else:
            later = _later_executions(cg, tgt, pid)
            if later:
                drift = {"ok": False, "error": "drifted_since_execute",
                         "action": act, "target": tgt, "preimage": rel,
                         "current": cur_fp, "later_executions": later,
                         "hint": "该执行记录无 after_hash（改前落盘）——按"
                                 "decisions.jsonl 判据：本单之后同目标还有 accept "
                                 "执行记录 %s，回滚会抹掉它们的写入；fail-closed "
                                 "未覆写（确需回滚加 --force）。" % (later,),
                         "reason": str(reason or ""), "actor": actor}
    if drift is not None:
        if dry_run:
            out = dict(drift, dry_run=True, would_apply=False)
            return out
        return drift
    if dry_run:
        return {"ok": True, "dry_run": True, "would_apply": True,
                "action": act, "target": tgt, "preimage": rel,
                "current": cur_fp, "preimage_state": pre_fp,
                "expected_after_execute": mutation.get("after_hash"),
                "reason": str(reason or ""), "actor": actor}
    if act == "C":
        res = _rollback_rewrite(cg, tgt, fm0, c0, force=force, actor=actor)
    elif act == "B":
        res = _rollback_merge(cg, tgt, fm0, c0, force=force, actor=actor)
    else:                                  # "D"
        res = _rollback_delete(cg, tgt, fm0, c0, rel, force=force, actor=actor)
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
           "reason": str(reason or ""), "actor": actor, "pid": pid,
           "bytes_equal_preimage": _bytes_equal(disk_p, pre_p),
           "residual": residual, "impact_after": after}
    out.update(res)
    # 回滚留痕（#352-A）：唯一不变更 _audit 的破坏性写口就此收口。
    out["audited"] = _audit_rollback(cg, tgt, act, rel, out, actor=actor,
                                     pid=pid, reason=reason)
    return out
