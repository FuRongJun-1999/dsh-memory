# -*- coding: utf-8 -*-
"""记忆评审流水线 · 级 4：M4 落库治理（确定性部分 · rule 驱动 · 永不删除）。

真源：`docs/记忆评审系统_立项设计与施工交接_20260915.md` §3 第 4 级 + §6 验收 + §7 负面清单。
本模块只做**机械可裁决**的治理动作（回填等）；LLM 语义类（合并 / 降权）不在其列——
那属 M2 建议 + designer 终裁，本轮不落地。

**规则驱动，引擎不写死**：回填哪个字段、作用于哪些层，不写在本文件里，从 M1 规则库
（`rules/*.json`，数据真源）读——`R-ROLE-MISSING` 的 `matcher.layer` 定作用域、
`mechanical[check=field_absent].field` 定字段。改靶子 = 改数据，引擎冻结。

**来源链（只搬运已声明证据）**：

① `tags`          `role:<值>` 标签——显式成文声明；
② `map`           `frontmatter.writer` → role 的**声明映射表**（`WRITER_ROLE_MAP`）。
                  当前**故意为空**：库内无任何成文映射能把 writer（`MDCG_ACTOR`：
                  dsh-memory / codebuddy / zcode / designer-cli…）落到
                  `mdcos.ALL_ROLES`；`scripts/review_cli.py` 的
                  `Principal(role="designer")` 属**权限角色**（`tokens.ROLE_SPECS`），
                  与节点 role 是两套词汇，混填即污染域。故留空 + 通道保留，待终裁补表；
③ `layer_default` 层默认投影——真源 = `mdcos.MdCGOS.add` 成文语义「默认 role=None
                  （知识）」，即缺省来源 = knowledge。该档是「隐含默认的显式化」，
                  断言强度高于 ①②，故单独分档上报（`by_source`）；只认显式成文声明时
                  用 `sources=("tags","map")` 关掉它。

**域封闭**：写入值必须 ∈ `mdcos.ALL_ROLES`；域外值一律不写，记 `*_out_of_domain` 且
**停止降级**（显式声明了域外值 ≠ 无声明，回退到默认档会把待裁决冲突悄悄抹平）。
`tool-output/command/edit` 属工作角色（`WORK_ROLES`，默认不参与正排，见
`mdcos._candidates`）。故 ② `map` 档**显式拒绝**工作角色（命中即
`map_role_is_work_role`，不降级）——映射表是本引擎的推断，把知识节点推成工作角色
等于亲手把它从默认召回里摘掉；① `tags` 档是**写入者成文声明**，予以尊重（治理层
不替作者改主意）。

**五纪律**（对齐 `backfill`）：不猜测（无来源 → `unfillable` + 原因分布，绝不编造）／
可预演（`role_plan` 只出报表，`role_apply` 写前重查，已有值计 `skipped_drift`）／
可留痕（`_govern.jsonl`：前后值 / 依据 / 来源档 / 批次 / 操作者 / 规则 id）／
可回滚（只在当前值 == 写入值时撤销，否则 `conflict`；原本无键 → 删键还原）／
fail-closed（密文与不可读节点跳过，绝不解密回写；靶规则缺失抛错）。
§7 负面清单：只写 frontmatter 一个字段，不动正文、永不删除。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from .. import crypto
from ..backfill import _as_cg, _entry_id, _readable_guard, _sha
from ..fsutil import append_jsonl, read_jsonl
from ..mdcos import ALL_ROLES, WORK_ROLES
from .ruleset import _as_rules, _blank

#: 留痕文件名（与 `backfill._backfill.jsonl` 分立：治理动作须能独立审计）
GOVERN_LOG = "_govern.jsonl"

#: 默认靶规则；`field_absent` 检查名（与 `ruleset.MECH_CHECKS` 同名）
RULE_ROLE = "R-ROLE-MISSING"
CHECK_FIELD_ABSENT = "field_absent"

#: 来源档
SOURCE_TAGS = "tags"
SOURCE_MAP = "map"
SOURCE_LAYER = "layer_default"
ALL_SOURCES = (SOURCE_TAGS, SOURCE_MAP, SOURCE_LAYER)
#: 默认只开「成文声明」两档；③ `layer_default` **必须显式开启**。
#: 依据（2026-09-16 真实库实测）：writer/tags 面无任何成文声明，故默认档在真实库上
#: 产出 `targeted=0 / unfillable=11120`（原因逐一列出）——这是**诚实结论**，而不是
#: 用 ③ 把指标刷绿：role"覆盖≥90%"若由常量填满即失去判据意义，且 ③ 会关掉 M1 的
#: `field_absent`，使 M2 的 `role_inferable` 语义判定**永不发生**——「字段有值」冒充
#: 「来源已知」。终裁开启前请先读 `LAYER_DEFAULT_WARNING`。
DEFAULT_SOURCES = (SOURCE_TAGS, SOURCE_MAP)

#: 开启 ③ `layer_default` 前**必读**的终裁提示（`role_plan`/CLI 在 `sources` 含 ③ 时透出）。
#: 它填的是**常量**而非**来源**：`role_ratio_kn` 会立刻跳到 100%（层内几乎全是 knowledge），
#: 但 ① M1 的 `R-ROLE-MISSING`（`field_absent`）随之永不命中——规则失去发现能力；
#: ② M2 的 `role_inferable` 语义判定（LLM 从 writer/tags/正文判 role）永无输入——
#: 即以「字段有值」冒充「来源已知」。③ 若 writer 有声明而库内无法映射（当前真实库
#: 全部如此），本档会把该冲突抹平成「已治理」，掩盖待裁决项。
LAYER_DEFAULT_WARNING = (
    "开启 layer_default 是把『来源未知』填成常量 knowledge：role 覆盖率立刻达标，"
    "但 M1 field_absent 与 M2 role_inferable 同时失效（字段有值冒充来源已知），"
    "并以层默认抹平 writer→role 待裁决冲突。须 designer 终裁、显式传 "
    "sources=tags,map,layer_default、留痕署名后方可使用。")

#: 标签前缀：`role:<值>` 为成文 role 声明
ROLE_TAG_PREFIX = "role:"

#: `writer` → role 的**声明映射表**（见模块 docstring ②：当前故意为空）
WRITER_ROLE_MAP: dict = {}

#: 层默认投影表：真源 = `mdcos.MdCGOS.add` docstring「默认 role=None（知识）」。
#: 只有层名本身就在 `ALL_ROLES` 里时才投影（knowledge 是唯一的一个）。
LAYER_DEFAULT_ROLE = {"knowledge": "knowledge"}

BASIS_TAG = "frontmatter.tags(role:<值> 显式声明)"
BASIS_LAYER = "mdcos.MdCGOS.add 默认语义(role=None ⇒ knowledge)"

REASON_NO_SOURCE = "no_source_declared"
REASON_TAG_OOD = "tag_role_out_of_domain"
REASON_MAP_OOD = "map_role_out_of_domain"
REASON_MAP_WORK = "map_role_is_work_role"
REASON_WRITER_NO_MAP = "writer_no_mapping"

ACTION_ROLE = "role"
ACTION_ROLE_ROLLBACK = "role_rollback"
BATCH_DEFAULT = "m4-role"

ACTIONS = ("role", "role_rollback", "role_history", "role_stats")


# ---- 通用工具 ------------------------------------------------------------

def _log_path(cg) -> str:
    return os.path.join(cg.root, GOVERN_LOG)


def _tags(fm: dict) -> list:
    return [t for t in ((fm or {}).get("tags") or []) if isinstance(t, str)]


def _reason_key(kind: str, detail: str = None) -> str:
    return kind if not detail else "%s:%s" % (kind, detail)


def _bump(box: dict, key: str) -> None:
    box[key] = box.get(key, 0) + 1


# ---- 靶子定位（rule 驱动）------------------------------------------------

def role_rule(*, rules=None, rules_dir=None, rule_id: str = RULE_ROLE) -> dict:
    """从 M1 规则库取「role 回填」靶规则 → `{field, layers, remedy, …}`。

    规则库是靶子的**唯一真源**：缺规则 / 缺 `matcher.layer` / 缺
    `field_absent.field` 一律抛 ValueError（fail-closed）——规则消失不是
    「没有要治理的东西」，而是治理靶子失效，必须显式红灯而非静默空跑。
    """
    rl = _as_rules(rules, rules_dir)
    hit = next((r for r in rl if r.get("id") == rule_id), None)
    if hit is None:
        raise ValueError("规则库无 %s（可用：%s）"
                         % (rule_id, [r.get("id") for r in rl]))
    layers = list((hit.get("matcher") or {}).get("layer") or [])
    field = None
    for spec in hit.get("mechanical") or []:
        if spec.get("check") == CHECK_FIELD_ABSENT and spec.get("field"):
            field = spec["field"]
            break
    if not layers or not field:
        raise ValueError("规则 %s 未声明 matcher.layer / %s.field——无法定位回填靶"
                         % (rule_id, CHECK_FIELD_ABSENT))
    return {"rule_id": rule_id, "title": hit.get("title"), "field": field,
            "layers": layers, "severity": hit.get("severity"),
            "remedy": hit.get("remedy"), "llm": list(hit.get("llm") or [])}


# ---- 取值推导（唯一入口：只搬运已声明的证据）------------------------------

def _candidate_role(e, fm, *, sources, role_map) -> tuple:
    """→ `(role, basis, source, reason)`：有来源则 reason=None；无来源则 role=None。

    按声明强度优先：`tags`（成文）> `map`（声明表）> `layer_default`（隐含默认显式化）。
    命中**域外值**时立即返回且**不降级**：显式声明了域外值 ≠ 无声明——继续回退到更弱的
    来源会把一个待 designer 裁决的冲突悄悄抹平。
    """
    if SOURCE_TAGS in sources:
        for t in _tags(fm):
            if t.startswith(ROLE_TAG_PREFIX):
                v = t[len(ROLE_TAG_PREFIX):].strip().lower()
                if v in ALL_ROLES:
                    return v, BASIS_TAG, SOURCE_TAGS, None
                return None, None, None, _reason_key(REASON_TAG_OOD, v or "空")
    if SOURCE_MAP in sources:
        w = str(fm.get("writer") or "").strip().lower()
        v = str((role_map or {}).get(w) or "").strip().lower() if w else ""
        if v:
            if v in WORK_ROLES:
                # 映射表是**我们的推断**：把 knowledge 层节点推成工作角色会让它在默认
                # 召回中被剔除（`_candidates` 默认排除 WORK_ROLES）——故意不做，红灯。
                return None, None, None, _reason_key(REASON_MAP_WORK, v)
            if v in ALL_ROLES:
                return v, "WRITER_ROLE_MAP[%s]" % w, SOURCE_MAP, None
            return None, None, None, _reason_key(REASON_MAP_OOD, v)
    if SOURCE_LAYER in sources:
        v = LAYER_DEFAULT_ROLE.get(str(e.get("layer") or ""))
        if v:
            return v, BASIS_LAYER, SOURCE_LAYER, None
    w = str(fm.get("writer") or "").strip()
    return None, None, None, (_reason_key(REASON_WRITER_NO_MAP, w) if w
                              else REASON_NO_SOURCE)


def _classify(cg, e, nid, *, sources, role_map) -> tuple:
    """单条裁决 → `(skip_reason, item|gap)`；skip_reason 为空串表示可回填。"""
    if not _readable_guard(cg, e):
        return "denied", None
    fm, content = cg._read(e)
    if fm is None:
        return "unreadable", None
    if crypto.is_encrypted(content):
        return "locked", None
    if not _blank(fm.get("role")):
        return "present", None
    role, basis, src, reason = _candidate_role(e, fm, sources=sources,
                                               role_map=role_map)
    if not role:
        return "unfillable", {"id": nid, "layer": e.get("layer"),
                              "reason": reason, "writer": fm.get("writer")}
    return "", {"id": nid, "layer": e.get("layer"), "role": role, "source": src,
                "basis": basis, "before": fm.get("role"),
                "had_key": "role" in fm, "writer": fm.get("writer")}


def _iter_scope(cg, *, layers, layer=None, prefix=None, ids=None) -> list:
    """按规则作用域遍历索引条目 → `[(nid, entry)]`（只读、nid 稳定序）。

    `layer` 收窄只能收窄到规则已声明的层内——跨层即抛错（同 `ruleset` 的
    「执行时按同一条件过滤，绝不跨层套用」）。
    """
    want = set(layers)
    if layer:
        if layer not in want:
            raise ValueError("layer=%s 不在靶规则作用域 %s 内（绝不跨层套用）"
                             % (layer, sorted(want)))
        want = {layer}
    idw = set(ids) if ids else None
    out = []
    for nid in sorted((cg.index.get("nodes") or {})):
        if idw is not None and nid not in idw:
            continue
        if prefix and not nid.startswith(prefix):
            continue
        e = cg.index["nodes"][nid]
        if str(e.get("layer")) not in want:
            continue
        out.append((nid, e))
    return out


# ---- 预演 -----------------------------------------------------------------

def role_plan(x, layer=None, limit=None, ids=None, prefix=None, *,
              sources=DEFAULT_SOURCES, role_map=None, rule_id=RULE_ROLE,
              rules=None, rules_dir=None, sample=0) -> dict:
    """预演：产出可回填清单 + 不可回填原因分布，**不写盘**。

    `sources` 见模块 docstring 的三档来源；`role_map` 覆盖 `WRITER_ROLE_MAP`
    （designer 终裁补声明表的入口，不改库）。
    """
    cg = _as_cg(x)
    rule = role_rule(rules=rules, rules_dir=rules_dir, rule_id=rule_id)
    rm = dict(WRITER_ROLE_MAP)
    rm.update({str(k).strip().lower(): v for k, v in (role_map or {}).items()})
    rep = {"root": cg.root, "dry_run": True, "action": ACTION_ROLE,
           "rule": rule, "sources": list(sources), "role_map": rm,
           "layer": layer, "prefix": prefix,
           "nodes_scanned": 0, "skipped_out_of_scope": 0,
           "skipped_locked": 0, "skipped_denied": 0, "skipped_unreadable": 0,
           "skipped_present": 0, "unfillable": 0, "unfillable_by_reason": {},
           "targeted": 0, "by_source": {}, "items": []}
    scope_layers = set(rule["layers"])
    idw = set(ids) if ids else None
    for nid in sorted((cg.index.get("nodes") or {})):
        if idw is not None and nid not in idw:
            continue
        if prefix and not str(nid).startswith(prefix):
            continue
        e = cg.index["nodes"][nid]
        if str(e.get("layer")) not in scope_layers:
            rep["skipped_out_of_scope"] += 1
    for nid, e in _iter_scope(cg, layers=rule["layers"], layer=layer,
                              prefix=prefix, ids=ids):
        rep["nodes_scanned"] += 1
        skip, item = _classify(cg, e, nid, sources=sources, role_map=rm)
        if skip == "unfillable":
            rep["unfillable"] += 1
            # 原因键带明细（如 writer_no_mapping:dsh-memory）——聚合即得逐来源分布
            _bump(rep["unfillable_by_reason"], str(item["reason"]))
            continue
        if skip:
            rep["skipped_%s" % skip] = rep.get("skipped_%s" % skip, 0) + 1
            continue
        item["entry_id"] = _entry_id(ACTION_ROLE, nid)
        item["ref"] = e.get("ref")
        rep["targeted"] += 1
        _bump(rep["by_source"], item["source"])
        if limit is None or len(rep["items"]) < limit:
            rep["items"].append(item)
    rep["planned_ids"] = [i["id"] for i in rep["items"]]
    if sample and rep["planned_ids"]:
        step = max(1, len(rep["planned_ids"]) // int(sample))
        rep["sample"] = rep["planned_ids"][::step][:int(sample)]
    rep["rule_layers"] = sorted(scope_layers)
    return rep


# ---- 执行 / 回滚 / 留痕 / 对照 -------------------------------------------

def role_apply(x, ids=None, entry_ids=None, layer=None, limit=None,
               batch=BATCH_DEFAULT, sources=DEFAULT_SOURCES, role_map=None,
               rule_id=RULE_ROLE, rules=None, rules_dir=None, actor=None,
               prefix=None) -> dict:
    """执行回填：逐节点改写 md 的 role 字段，写 `_govern.jsonl` 留痕。

    写前**重查**一次（预演 → 执行之间节点可能被改动）：已有 role 值 → `skipped_drift`
    一律不动；密文 / 不可读 → `skipped_locked` / `skipped_missing`，**绝不解密回写**。
    `ids` / `prefix` / `entry_ids` 三重收窄，`entry_ids` 优先（工单式精确执行）。
    """
    cg = _as_cg(x)
    batch = batch or BATCH_DEFAULT
    p = role_plan(cg, layer=layer, limit=limit, ids=ids, prefix=prefix,
                  sources=sources, role_map=role_map, rule_id=rule_id,
                  rules=rules, rules_dir=rules_dir)
    items = p["items"]
    if entry_ids:
        want = set(entry_ids)
        items = [i for i in items if i["entry_id"] in want]
    rep = {"root": cg.root, "dry_run": False, "action": ACTION_ROLE,
           "batch": batch, "actor": actor, "rule_id": rule_id,
           "field": p["rule"]["field"], "sources": list(sources),
           "planned": len(items), "written": 0, "by_source": {},
           "skipped_drift": 0, "skipped_locked": 0, "skipped_missing": 0,
           "skipped_denied": 0, "entry_ids": [],
           "unfillable": p["unfillable"],
           "unfillable_by_reason": p["unfillable_by_reason"]}
    for it in items:
        nid = it["id"]
        e = (cg.index.get("nodes") or {}).get(nid)
        if e is None:
            rep["skipped_missing"] += 1
            continue
        if not _readable_guard(cg, e):
            rep["skipped_denied"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None:
            rep["skipped_missing"] += 1
            continue
        if crypto.is_encrypted(content):
            rep["skipped_locked"] += 1
            continue
        if not _blank(fm.get("role")):
            rep["skipped_drift"] += 1
            continue
        fm_before = {"role": fm.get("role"), "had_key": "role" in fm}
        fm["role"] = it["role"]
        ts = time.time()
        cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                       durable=True)
        wid = _sha("%s|%s|%.6f" % (nid, batch, ts))
        append_jsonl(_log_path(cg), {
            "action": ACTION_ROLE, "ts": ts, "batch": batch, "actor": actor,
            "entry_id": it["entry_id"], "write_id": wid, "node": nid,
            "layer": e.get("layer"), "rule_id": rule_id, "field": "role",
            "value": it["role"], "source": it["source"], "basis": it["basis"],
            "writer": it.get("writer"), "fm_before": fm_before,
            "content_hash_after": _sha(content)})
        rep["written"] += 1
        _bump(rep["by_source"], it["source"])
        rep["entry_ids"].append(it["entry_id"])
    if rep["written"]:
        cg.rebuild_index()
    rep["plan_remaining"] = max(0, p["targeted"] - len(items))
    return rep


def role_rollback(x, batch=None, entry_ids=None, actor=None) -> dict:
    """按留痕反向应用：撤销 role 回填。

    **只在当前值仍等于当初写入值时**撤销；否则计 `conflict` 不覆盖（此后可能已有
    人工修正 / 后续批次写入）。原本无该键 → 删键还原（不是写空串）。
    """
    cg = _as_cg(x)
    want = set(entry_ids) if entry_ids else None
    rep = {"root": cg.root, "action": ACTION_ROLE_ROLLBACK, "actor": actor,
           "batch": batch, "reverted": 0, "conflict": 0, "missing": 0,
           "skipped_done": 0, "entry_ids": []}
    log = list(read_jsonl(_log_path(cg)) or [])
    done = {r.get("write_id") for r in log
            if r.get("action") == ACTION_ROLE_ROLLBACK and r.get("write_id")}
    for rec in log:
        if rec.get("action") != ACTION_ROLE:
            continue
        if batch and rec.get("batch") != batch:
            continue
        if want is not None and rec.get("entry_id") not in want:
            continue
        wid = rec.get("write_id")
        if wid and wid in done:
            rep["skipped_done"] += 1
            continue
        nid = rec.get("node")
        e = (cg.index.get("nodes") or {}).get(nid)
        if e is None:
            rep["missing"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None or crypto.is_encrypted(content):
            rep["missing"] += 1
            continue
        if _blank(fm.get("role")) or str(fm.get("role")) != str(rec.get("value")):
            rep["conflict"] += 1
            continue
        before = rec.get("fm_before") or {}
        if before.get("had_key"):
            fm["role"] = before.get("role")
        else:
            fm.pop("role", None)
        cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                       durable=True)
        append_jsonl(_log_path(cg), {
            "action": ACTION_ROLE_ROLLBACK, "ts": time.time(), "actor": actor,
            "batch": rec.get("batch"), "entry_id": rec.get("entry_id"),
            "write_id": wid, "node": nid, "field": "role",
            "restored": before.get("role"),
            "had_key": bool(before.get("had_key")), "reason": "rollback"})
        rep["reverted"] += 1
        rep["entry_ids"].append(rec.get("entry_id"))
    if rep["reverted"]:
        cg.rebuild_index()
    return rep


def history(x, limit=100, action=None, batch=None) -> dict:
    """读 `_govern.jsonl` 留痕（治理动作的可审计面）。"""
    cg = _as_cg(x)
    recs = [r for r in (read_jsonl(_log_path(cg)) or [])
            if (not action or r.get("action") == action)
            and (not batch or r.get("batch") == batch)]
    tail = recs[-int(limit):] if limit else recs
    by_action = {}
    for r in recs:
        _bump(by_action, str(r.get("action")))
    return {"root": cg.root, "action": "role_history", "total": len(recs),
            "by_action": by_action, "records": tail}


def role_stats(x, *, rule_id=RULE_ROLE, rules=None, rules_dir=None) -> dict:
    """只读对照：role 覆盖率 + 取值分布（治理前后量化用）。

    判据**不复刻**——直接复用 `conformance`（真源：`_coverage_metrics` 的
    knowledge 层口径 `role_ratio_kn` 与 `THRESHOLDS["role_coverage_min"]`），
    本函数只补「逐层 / 逐值」分布，供 M4 复跑报告引用。
    """
    from .. import conformance as CONF          # 延迟导入：读侧判据真源，按需加载
    cg = _as_cg(x)
    rule = role_rule(rules=rules, rules_dir=rules_dir, rule_id=rule_id)
    nodes = CONF.load_index(cg.root)
    cov = CONF._coverage_metrics(nodes)
    thr = float(CONF.THRESHOLDS["role_coverage_min"])
    by_layer, by_value = {}, {}
    for e in nodes.values():
        _bump(by_layer, str(e.get("layer")))
        if not _blank(e.get("role")):
            _bump(by_value, str(e.get("role")))
    kn = float(cov.get("role_ratio_kn") or 0.0)
    return {"root": cg.root, "action": "role_stats", "rule_id": rule_id,
            "layers": rule["layers"], "nodes": cov.get("nodes"),
            "knowledge": cov.get("knowledge"), "role_ratio": cov.get("role_ratio"),
            "role_ratio_kn": cov.get("role_ratio_kn"), "threshold": thr,
            "target_met": kn >= thr, "gap_to_target": max(0.0, thr - kn),
            "by_layer": by_layer, "by_value": by_value}


# ---- 统一入口 ------------------------------------------------------------

def run(x, action, **kw) -> dict:
    """`role`（`apply=True` 则执行）/ `role_rollback` / `role_history` / `role_stats`。"""
    if action not in ACTIONS:
        raise ValueError("未知 action=%s（可用：%s）" % (action, list(ACTIONS)))
    if action == ACTION_ROLE:
        if kw.pop("apply", False):
            return role_apply(x, **kw)
        return role_plan(x, **kw)
    fn = {ACTION_ROLE_ROLLBACK: role_rollback, "role_history": history,
          "role_stats": role_stats}[action]
    return fn(x, **kw)


# ---- 命令行 --------------------------------------------------------------
#
# 形态约定：`--root` / `--rules-dir` / `--json` 均为**子命令参数**（`parents=[common]`），
# 须写在子命令**之后**：`govern plan --root <root>`。写在子命令之前会被顶层解析器
# 当作位置参数吃掉（`scripts/review_cli.py` 的同型坑，2026-09-15 实测更正）。

def _parse_sources(s) -> tuple:
    """CLI 侧来源档解析：逗号分隔，值域封闭（非法即抛，不静默降级）。"""
    if not s:
        return DEFAULT_SOURCES
    vals = tuple(v.strip() for v in str(s).split(",") if v.strip())
    bad = [v for v in vals if v not in ALL_SOURCES]
    if bad:
        raise ValueError("未知来源档 %s（可用：%s）" % (bad, list(ALL_SOURCES)))
    if not vals:
        raise ValueError("sources 为空（缺省即 %s）" % ",".join(DEFAULT_SOURCES))
    return vals


def _common_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--root", default=None, help="真源根（缺省读环境变量 MDCG_ROOT）")
    ap.add_argument("--rules-dir", default=None, help="规则库目录（缺省 mreview/rules）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（缺省人读摘要）")
    return ap


def _add_scope_args(p) -> None:
    p.add_argument("--layer", help="收窄到该层（须在规则 matcher 层之内）")
    p.add_argument("--prefix", help="只处理该 id 前缀")
    p.add_argument("--ids", help="逗号分隔的节点 id 白名单")
    p.add_argument("--limit", type=int, help="本次最多处理条数")
    p.add_argument("--sources",
                   help="来源档逗号分隔：tags,map[,layer_default]（缺省 %s）"
                        % ",".join(DEFAULT_SOURCES))


def _scope_kw(a) -> dict:
    return {"layer": a.layer, "prefix": a.prefix, "limit": a.limit,
            "ids": [i.strip() for i in (a.ids or "").split(",") if i.strip()] or None,
            "sources": _parse_sources(a.sources), "rules_dir": a.rules_dir}


def _warn_layer_default(sources) -> None:
    if SOURCE_LAYER in sources:
        print("警告：" + LAYER_DEFAULT_WARNING, file=sys.stderr)


def _die(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m md_cg.mreview.govern",
        description="记忆评审 M4 · 落库治理（确定性部分：rule 驱动 · 永不删除）")
    sub = ap.add_subparsers(dest="cmd")
    common = _common_parser()

    p = sub.add_parser("plan", parents=[common], help="预演（只出报表，不写盘）")
    _add_scope_args(p)
    p.add_argument("--sample", type=int, default=0, help="抽样条数（人工核对样板）")

    p = sub.add_parser("apply", parents=[common], help="执行回填（写盘 + 留痕 + 可回滚）")
    _add_scope_args(p)
    p.add_argument("--batch", default=BATCH_DEFAULT, help="批次名（留痕 / 回滚锚点）")
    p.add_argument("--actor", default=None, help="执行者署名（留痕）")
    p.add_argument("--entry-id", action="append", default=[],
                   help="只执行该条目（可多次；工单式精确执行）")
    p.add_argument("--yes", action="store_true", help="显式确认写盘（缺省拒绝）")

    p = sub.add_parser("rollback", parents=[common], help="按留痕回滚")
    p.add_argument("--batch", default=None, help="只回滚该批次")
    p.add_argument("--entry-id", action="append", default=[], help="只回滚该条目（可多次）")
    p.add_argument("--actor", default=None, help="执行者署名（留痕）")

    p = sub.add_parser("history", parents=[common], help="读 `_govern.jsonl` 留痕")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--batch", default=None)
    p.add_argument("--action", default=None)

    sub.add_parser("stats", parents=[common],
                   help="覆盖率对照（复用 conformance 判据）")

    a = ap.parse_args(argv)
    if not a.cmd:
        # `--root` 是**子命令**参数（`parents=[common]`）：无子命令时顶层 Namespace
        # 根本没有该属性——须先判 cmd 再取 root，否则 `govern` 裸跑即 AttributeError。
        ap.print_help()
        return 2
    root = a.root or os.environ.get("MDCG_ROOT")
    if not root:
        return _die("需要 --root 或环境变量 MDCG_ROOT（fail-closed）")

    if a.cmd == "plan":
        try:
            kw = _scope_kw(a)
        except ValueError as ex:
            return _die(str(ex))
        _warn_layer_default(kw["sources"])
        try:
            rep = role_plan(root, sample=a.sample, **kw)
        except ValueError as ex:
            return _die("预演失败：%s" % ex)
        if a.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
            return 0
        print("[M4 预演·只读] root=%s" % rep["root"])
        print("  靶规则 %s｜层 %s｜字段 %s｜来源档 %s"
              % (rep["rule"]["rule_id"], ",".join(rep["rule_layers"]),
                 rep["rule"]["field"], ",".join(rep["sources"])))
        print("  扫描 %d｜可回填 %d｜不可回填 %d｜域外 %d｜已锁 %d｜已有值 %d｜无权限 %d"
              % (rep["nodes_scanned"], rep["targeted"], rep["unfillable"],
                 rep["skipped_out_of_scope"], rep["skipped_locked"],
                 rep["skipped_present"], rep["skipped_denied"]))
        for k, v in sorted(rep["by_source"].items()):
            print("  来源 %-16s %d" % (k, v))
        for k, v in sorted(rep["unfillable_by_reason"].items(), key=lambda kv: -kv[1]):
            print("  挡下 %-32s %d" % (k, v))
        if rep.get("sample"):
            print("  抽样：%s" % ", ".join(rep["sample"]))
        return 0

    if a.cmd == "apply":
        if not a.yes:
            return _die("apply 会写盘：先跑 plan 核对清单，再以 --yes 显式确认（fail-closed）")
        try:
            kw = _scope_kw(a)
        except ValueError as ex:
            return _die(str(ex))
        _warn_layer_default(kw["sources"])
        try:
            rep = role_apply(root, batch=a.batch, actor=a.actor,
                             entry_ids=list(a.entry_id) or None, **kw)
        except ValueError as ex:
            return _die("执行失败：%s" % ex)
        if a.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
            return 0
        print("[M4 执行] batch=%s actor=%s" % (rep["batch"], rep["actor"]))
        print("  写入 %d｜漂移跳过 %d｜密文跳过 %d｜缺失 %d｜无权限 %d｜余量 %d"
              % (rep["written"], rep["skipped_drift"], rep["skipped_locked"],
                 rep["skipped_missing"], rep["skipped_denied"], rep["plan_remaining"]))
        for k, v in sorted(rep["by_source"].items()):
            print("  来源 %-16s %d" % (k, v))
        return 0

    if a.cmd == "rollback":
        if not a.batch and not a.entry_id:
            return _die("rollback 需要 --batch 或 --entry-id（防全量误回滚）")
        rep = role_rollback(root, batch=a.batch, actor=a.actor,
                            entry_ids=list(a.entry_id) or None)
        if a.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
            return 0
        print("[M4 回滚] batch=%s｜还原 %d｜冲突跳过 %d｜缺失 %d｜已回滚 %d"
              % (rep["batch"], rep["reverted"], rep["conflict"], rep["missing"],
                 rep["skipped_done"]))
        return 0

    if a.cmd == "history":
        rep = history(root, limit=a.limit, action=a.action, batch=a.batch)
        if a.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
            return 0
        print("[M4 留痕] 命中 %d 条｜分布 %s" % (rep["total"], rep["by_action"]))
        for r in rep["records"]:
            print("  %-14s %-10s %-22s %s=%s"
                  % (time.strftime("%m-%d %H:%M:%S", time.localtime(r.get("ts") or 0)),
                     r.get("action"), str(r.get("node")), r.get("field"),
                     r.get("value", r.get("restored"))))
        return 0

    try:
        rep = role_stats(root)
    except ValueError as ex:
        return _die("对照失败：%s" % ex)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0
    print("[M4 对照] root=%s 判据源=conformance" % rep["root"])
    print("  节点 %s｜knowledge %s｜role 覆盖 %s｜knowledge 层覆盖 %s（阈值 %.2f，%s）"
          % (rep["nodes"], rep["knowledge"], rep["role_ratio"],
             rep["role_ratio_kn"], rep["threshold"],
             "达标" if rep["target_met"] else "未达标，缺口 %.4f" % rep["gap_to_target"]))
    print("  逐层 %s" % rep["by_layer"])
    print("  逐值 %s" % rep["by_value"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
