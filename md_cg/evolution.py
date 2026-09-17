# -*- coding: utf-8 -*-
"""md_cg · 演化账本：用 md 文档记录「每一次修改 = 对一条缺失条件的补充」。

为什么用 md 而不是 jsonl
------------------------
演化记录的价值不在于机器回放，而在于**认知规律可读**。人读账本时应该看到
「哪一类条件反复缺失、补上之后状态怎么变」，而不是一串字段增量。所以：

    账本正文 = 人类可读的「规律 + 状态」
    回滚快照 = 同一条目下内嵌的 fenced json 块

md 是单一真相源，不再引入第二种日志格式。

记录的是「规律 / 状态」，不是实现
--------------------------------
    pattern  规律    —— 一句话认知规律（例：缺时间窗口的条件在跨季度查询里被误召回）
    missing  缺失条件 —— 补的是哪一维条件（对应结构维四要素）
    state    before/after —— confidence / layer / importance / 负条件 / 验证基底
    evidence 证据    —— 触发本次演化的验证依据（replay / 测试 / 人工）

不记录代码、函数名、调用栈——那些属于 git，不属于认知账本。

回滚
----
每条条目都带 before/after 状态。`rollback` 把 after 撤回 before，并且**自己也记
一条 rollback 条目**——撤销不可静默，撤销本身也是演化。支持 dry_run 预演。

账本只追加，不原地改写（append-only md），追加受跨进程锁保护。
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid

from .fsutil import FileLock, atomic_write

EVOLUTION_DIR = "_evolution"
LEDGER_NAME = "ledger.md"
SCHEMA_VERSION = 1

KIND_CONDITION_GAP = "condition_gap"   # 补缺失条件（默认）
KIND_LAYER_SHIFT = "layer_shift"       # 层间迁移
KIND_GENERAL = "general"               # 其他结构变更
KIND_ROLLBACK = "rollback"             # 回滚
KINDS = (KIND_CONDITION_GAP, KIND_LAYER_SHIFT, KIND_GENERAL, KIND_ROLLBACK)

# 参与演化的「认知状态」字段（不是实现细节）。回滚按这些字段原样写回 frontmatter。
STATE_FIELDS = ("confidence", "importance", "layer", "verification_basis",
                "condition_space", "non_applicable_conditions", "edges",
                "valid_until")

# 缺失条件可归到哪一维（对应结构维四要素；patterns() 按此聚类出规律）
CONDITION_DIMS = ("conditions", "conditions.time_window",
                  "conditions.observation_position", "conditions.tool",
                  "conditions.existence", "non_applicable_conditions",
                  "execution")

# 中文标签 ↔ 字段名（账本正文用中文，解析时映射回字段）
_LABELS = {"规律": "pattern", "缺失条件": "missing", "动作": "action",
           "状态": "state_text", "证据": "evidence", "来源": "source",
           "时间": "time", "回滚自": "rollback_of"}
_REV = {v: k for k, v in _LABELS.items()}
_BULLET_ORDER = ("pattern", "missing", "action", "state_text", "evidence",
                 "source", "time", "rollback_of")

_HEADER = """# 演化账本 · md_cg

> 每一次修改 = 对一条缺失条件的补充。
> 记录的是**认知规律**与**状态**，不是实现细节（实现属于 git）。
> 回滚：`cg(op=evolution, action=rollback, entry_id=evo-...)`

"""

_ENTRY_RE = re.compile(
    r"^##\s+(evo-[0-9]{8}-[0-9]{6}-[0-9a-f]{4})\s+·\s+`?([^`\n]*)`?\s*$", re.M)
_BULLET_RE = re.compile(r"^-\s+\*\*(.+?)\*\*：\s*(.*)$", re.M)
_STATE_RE = re.compile(r"```json state\s*\n(.*?)\n```", re.S)


# --------------------------------------------------------------------------
# 路径 / 追加
# --------------------------------------------------------------------------

# 生效条件：cg 可解析出 root 时，返回 os.path.join(cg.root, 模块常量 EVOLUTION_DIR)，无守卫分支。
def evolution_dir(cg) -> str:
    return os.path.join(cg.root, EVOLUTION_DIR)


# 生效条件：cg 可解析出 root 时，返回 evolution_dir(cg) 与模块常量 LEDGER_NAME 的 os.path.join 结果。
def ledger_path(cg) -> str:
    return os.path.join(evolution_dir(cg), LEDGER_NAME)


# 生效条件：无入参，任何一次调用都返回 "evo-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex 的前 4 位。
def new_entry_id() -> str:
    return "evo-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


# 生效条件：cg 与 text 给定时，在 FileLock(ledger_path(cg)) 内取旧内容（读不到或空则回退 _HEADER，不以换行结尾则补一个换行）并 atomic_write 写入 old + text，无需 text 非空。
def _append(cg, text: str):
    """向账本追加一条（读-改-写 + 跨进程锁，崩溃不留半截文件）。"""
    p = ledger_path(cg)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with FileLock(p):
        old = ""
        if os.path.exists(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                old = f.read()
        if not old:
            old = _HEADER
        if old and not old.endswith("\n"):
            old += "\n"
        atomic_write(p, old + text)


# 生效条件：ledger_path(cg) 对应路径不存在时返回 ""，否则以 encoding="utf-8"、errors="replace" 打开并返回 f.read() 的全部内容。
def read_ledger(cg) -> str:
    p = ledger_path(cg)
    if not os.path.exists(p):
        return ""
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


# --------------------------------------------------------------------------
# 渲染 / 解析
# --------------------------------------------------------------------------

# 生效条件：field、before、after 任意取值下都返回 f"{field} {_short(before)}→{_short(after)}"。
def _fmt_change(field, before, after) -> str:
# 生效条件：v 为 list/tuple 返回 f"{len(v)}条"，为 dict 返回 f"{len(v)}键"，为 None 返回 "—"，为 float 返回 f"{v:g}"，其余类型返回 str(v)。
    def _short(v):
        if isinstance(v, (list, tuple)):
            return f"{len(v)}条"
        if isinstance(v, dict):
            return f"{len(v)}键"
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:g}"
        return str(v)
    return f"{field} {_short(before)}→{_short(after)}"


# 生效条件：before 与 after 中任一为假值（None、{} 等）时该侧按 {} 参与比较，返回 STATE_FIELDS 中 b.get(k) != a.get(k) 的字段对应的 _fmt_change(k, b.get(k), a.get(k)) 列表。
def diff(before, after):
    """状态差异 → 人类可读列表（只比认知状态字段）。"""
    b, a = before or {}, after or {}
    return [_fmt_change(k, b.get(k), a.get(k))
            for k in STATE_FIELDS if b.get(k) != a.get(k)]


# 生效条件：entry 含键 'entry_id'（缺失即 KeyError）时，按 _BULLET_ORDER 输出值不属 None/""/[]/{} 的字段行（node_id 假值显示 '—'），并在 entry.get("state") 为真值时追加 json 状态块，返回以 "\n" 连接的文本。
def _fmt(entry: dict) -> str:
    lines = [f"## {entry['entry_id']} · `{entry.get('node_id') or '—'}`", ""]
    for k in _BULLET_ORDER:
        v = entry.get(k)
        if v in (None, "", [], {}):
            continue
        lines.append(f"- **{_REV[k]}**：{v}")
    state = entry.get("state")
    if state:
        lines.append("")
        lines.append("```json state")
        lines.append(json.dumps(state, ensure_ascii=False, sort_keys=True))
        lines.append("```")
    lines.append("")
    return "\n".join(lines)


# 生效条件：text 中 _ENTRY_RE 匹配到 0 个条目时返回 []，匹配到则按各匹配区间解析为字典列表（node 为空或 "—" 时 node_id 置 None，state 段 json.loads 抛 ValueError 时 state 置 None，kind 缺省回落模块常量 KIND_CONDITION_GAP）。
def _parse(text: str):
    out = []
    marks = list(_ENTRY_RE.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        block = text[m.end():end]
        node = (m.group(2) or "").strip()
        e = {"entry_id": m.group(1), "node_id": node if node and node != "—" else None}
        for bm in _BULLET_RE.finditer(block):
            key = _LABELS.get(bm.group(1).strip())
            if key:
                e[key] = bm.group(2).strip()
        sm = _STATE_RE.search(block)
        if sm:
            try:
                e["state"] = json.loads(sm.group(1))
            except ValueError:
                e["state"] = None
        st = e.get("state") or {}
        e["kind"] = st.get("kind") or KIND_CONDITION_GAP
        out.append(e)
    return out


# --------------------------------------------------------------------------
# 认知状态
# --------------------------------------------------------------------------

# 生效条件：cg.get(node_id) 为假值（含 None）时返回 None，否则返回 frontmatter 中属于 STATE_FIELDS 且值不为 None 的字段（"layer" 缺失时用 node.get("path") 首段补上），保留 []/{}/"" 等显式空值。
def state_of(cg, node_id):
    """抽取节点的认知状态（可回滚字段），节点不存在返回 None。

    保留 `[]`/`{}` 等「显式为空」的值——回滚要能区分「原来就没有」与「原来是空」。
    """
    node = cg.get(node_id)
    if not node:
        return None
    fm = node.get("frontmatter") or {}
    st = {k: fm[k] for k in STATE_FIELDS if k in fm and fm[k] is not None}
    if "layer" not in st:
        st["layer"] = (node.get("path") or "").split("/")[0]
    return st


# --------------------------------------------------------------------------
# 记录
# --------------------------------------------------------------------------

# 生效条件：pattern.strip() 非空且 kind 属于模块常量 KINDS 时追加并返回条目 e（pattern 为空白或 kind 未知抛 ValueError；action 去空白后为空且 extra 为真时取 extra.pop("change", "") 作 action；before/after 任一 non-None 时 state 记入二者 or {}；extra 中值不属 None/""/[]/{} 的键并入 e）。
def record(cg, node_id=None, pattern="", missing="", action="", evidence="",
           source="", kind=KIND_CONDITION_GAP, before=None, after=None,
           extra=None):
    """追加一条演化条目。

    `pattern`（规律）必填——没有规律就没有可复用的认知，只是一次性改动。
    before/after 给状态快照（用于回滚）；缺省则不生成回滚能力。
    """
    if not (pattern or "").strip():
        raise ValueError("演化条目必须写清「规律」（pattern）")
    if kind not in KINDS:
        raise ValueError(f"未知演化类型：{kind}")
    if not (action or "").strip() and extra:
        action = extra.pop("change", "")      # change 是 action 的入口别名
    state = {"kind": kind}
    if before is not None or after is not None:
        state["before"] = before or {}
        state["after"] = after or {}
    changes = diff(before, after)
    e = {
        "entry_id": new_entry_id(), "node_id": node_id,
        "pattern": pattern.strip(), "missing": (missing or "").strip(),
        "action": (action or "").strip(),
        "state_text": " · ".join(changes),
        "evidence": (evidence or "").strip(), "source": (source or "").strip(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "kind": kind, "state": state,
    }
    if extra:
        for k, v in extra.items():
            if v not in (None, "", [], {}):
                e[k] = v
    _append(cg, _fmt(e))
    return e


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------

# 生效条件：cg 给定时返回 _parse(read_ledger(cg)) 的列表——node_id 为真值则只留该节点记录、kind 为真值则只留该类型记录、newest_first 为真值则 reverse、limit 为真值时截断为前 int(limit) 条（limit 为 0/None 等假值时不截断）。
def entries(cg, limit=None, node_id=None, kind=None, newest_first=True):
    recs = _parse(read_ledger(cg))
    if node_id:
        recs = [r for r in recs if r.get("node_id") == node_id]
    if kind:
        recs = [r for r in recs if r.get("kind") == kind]
    if newest_first:
        recs.reverse()
    if limit:
        recs = recs[:int(limit)]
    return recs


# 生效条件：遍历 entries(cg, limit=0)（limit=0 为假值故不截断，覆盖全部记录），命中 r.get("entry_id") == entry_id 时返回该记录，否则返回 None。
def show(cg, entry_id):
    for r in entries(cg, limit=0):
        if r.get("entry_id") == entry_id:
            return r
    return None


# 生效条件：cg 与 node_id 给定时返回 {"node_id": node_id, "entries": entries(cg, limit=limit, node_id=node_id)}——node_id 为假值时 entries 不按节点过滤，limit 默认 50 为真值故截断，传 0 等假值则不截断。
def history(cg, node_id, limit=50):
    return {"node_id": node_id, "entries": entries(cg, limit=limit, node_id=node_id)}


# 生效条件：cg 给定时返回统计字典，其中 recs 取 entries(cg, limit=0) 全量、real 剔除 kind == 模块常量 KIND_ROLLBACK（missing 为空的条目不计入 by_missing、kind 缺省回落 KIND_CONDITION_GAP、source 缺省回落 "unknown"），top_patterns 取按 count 降序 pattern 升序排序后的前 int(limit) 项（limit 为 0 时切片为空列表）。
def patterns(cg, limit=10):
    """规律统计：哪一维条件反复缺失、由谁触发、哪些规律重复出现。

    这是「认知功能记录规律」的落点——不是统计改了多少次，而是看清缺什么。
    """
    recs = entries(cg, limit=0)
    real = [r for r in recs if r.get("kind") != KIND_ROLLBACK]
    by_missing, by_kind, by_source, seen = {}, {}, {}, {}
    for r in real:
        m = (r.get("missing") or "").strip()
        if m:
            by_missing[m] = by_missing.get(m, 0) + 1
        k = r.get("kind") or KIND_CONDITION_GAP
        by_kind[k] = by_kind.get(k, 0) + 1
        s = r.get("source") or "unknown"
        by_source[s] = by_source.get(s, 0) + 1
        p = (r.get("pattern") or "").strip()
        if p:
            d = seen.setdefault(p, {"pattern": p, "count": 0, "last_at": ""})
            d["count"] += 1
            d["last_at"] = r.get("time") or d["last_at"]
    top = sorted(seen.values(), key=lambda d: (-d["count"], d["pattern"]))
    return {"total": len(recs), "evolutions": len(real),
            "rollbacks": len(recs) - len(real),
            "by_missing": by_missing, "by_kind": by_kind,
            "by_source": by_source, "top_patterns": top[:int(limit)]}


# 生效条件：cg 给定时返回固定结构字典——missing_top 取 patterns(cg) 的 by_missing 中计数最大项的键（by_missing 为空则 "（暂无）"），top_pattern 取 top_patterns[0]["pattern"]（为空则 "（暂无）"），recent 取 entries(cg, limit=5)。
def summary(cg):
    p = patterns(cg)
    missing_top = (max(p["by_missing"].items(), key=lambda kv: kv[1])[0]
                   if p["by_missing"] else "（暂无）")
    top_pattern = (p["top_patterns"][0]["pattern"]
                   if p["top_patterns"] else "（暂无）")
    return {
        "ok": True, "ledger": f"{EVOLUTION_DIR}/{LEDGER_NAME}",
        "evolutions": p["evolutions"], "rollbacks": p["rollbacks"],
        "most_missing": missing_top, "top_pattern": top_pattern,
        "by_missing": p["by_missing"],
        "recent": entries(cg, limit=5),
        "text": (f"演化 {p['evolutions']} 次 / 回滚 {p['rollbacks']} 次；"
                 f"最常缺：{missing_top}"),
    }


# --------------------------------------------------------------------------
# 回滚
# --------------------------------------------------------------------------

# 生效条件：cg.get(node_id) 为假时返回 ([], [{"field": "*", "reason": "节点不存在"}])，否则先处理 target 中的 "layer"（为真且不同于当前 path 首段时经 cg._move_layer 迁移并 appended "layer"，抛异常则记入 skipped，相同/为假时直接 appended "layer"），再按 STATE_FIELDS 处理：k 在 remove 中且存在于 frontmatter 则 pop 并 appended "-k"，k 在 target 中且值相同则 appended k、不同则改写并在 changed 时经 cg._write_node 回写，最终返回 (applied, skipped)（若层迁移后 node 取不回则提前返回）。
def _apply_state(cg, node_id, target, remove=()):
    """把目标状态写回节点。返回 (applied, skipped)。

    target 中的字段写回原值；remove 中的字段是「改动后才出现」的，回滚需删除，
    这样「补一条缺失条件」的回滚才是真的撤回补充，而不是留个空壳。
    """
    applied, skipped = [], []
    node = cg.get(node_id)
    if not node:
        return applied, [{"field": "*", "reason": "节点不存在"}]

    # 层迁移单独走 _move_layer（搬文件 + 写保护校验）
    if "layer" in target:
        to = target.get("layer")
        cur = (node.get("path") or "").split("/")[0]
        if to and to != cur:
            try:
                cg._move_layer(node_id, to, reason="evolution rollback")
                applied.append("layer")
                node = cg.get(node_id)          # 路径已变，重新取
            except Exception as exc:            # noqa: BLE001 —— 受保护节点拒绝降级
                skipped.append({"field": "layer",
                                "reason": f"{type(exc).__name__}: {exc}"})
        else:
            applied.append("layer")

    if not node:
        return applied, skipped
    fm = dict(node["frontmatter"])
    changed = False
    for k in STATE_FIELDS:
        if k == "layer":
            continue
        if k in remove:
            if k in fm:
                fm.pop(k, None)
                changed = True
                applied.append(f"-{k}")
            continue
        if k not in target:
            continue
        if fm.get(k) == target[k]:
            applied.append(k)
            continue
        fm[k] = target[k]
        changed = True
        applied.append(k)
    if changed:
        cg._write_node(node_id, os.path.join(cg.root, node["path"]),
                       fm, node["content"])
    return applied, skipped


# 生效条件：cg 与 entry_id 定位 show(cg, entry_id) 后逐项判定——条目不存在返回未找到错误、kind == 模块常量 KIND_ROLLBACK 返回拒回滚错误、state 的 before 为假值返回无回滚状态错误、node_id 为假值返回未绑定节点错误、state_of 为 None 返回节点不可读错误；dry_run 为真值时返回含 current/target/would_remove/would_change 的预览；否则经 _apply_state(target, remove=after 中不属 before 且非 "layer" 的字段) 回写、尝试 cg.rebuild_index()（异常静默）并 record 一条 KIND_ROLLBACK 条目后返回 ok=True 结果。
def rollback(cg, entry_id, dry_run=False, note=""):
    """把某条演化撤回其 before 状态，并记一条 rollback 条目（撤销不可静默）。"""
    src = show(cg, entry_id)
    if not src:
        return {"ok": False, "error": f"未找到条目：{entry_id}"}
    if src.get("kind") == KIND_ROLLBACK:
        return {"ok": False, "error": "不能回滚一条回滚记录；请指定被回滚的原条目"}
    st = src.get("state") or {}
    before = st.get("before")
    if not before:
        return {"ok": False, "error": "该条目未记录可回滚状态（before 缺失）"}
    after = st.get("after") or {}
    node_id = src.get("node_id")
    if not node_id:
        return {"ok": False, "error": "该条目未绑定节点"}
    cur = state_of(cg, node_id)
    if cur is None:
        return {"ok": False, "error": f"节点不存在或不可读：{node_id}"}

    target = {k: before[k] for k in STATE_FIELDS if k in before}
    # 改动后才出现的字段 = 本次补充的条件 → 回滚要删掉，而不是留个空壳
    remove = [k for k in after if k != "layer" and k not in before]
    if dry_run:
        return {"ok": True, "dry_run": True, "entry_id": entry_id,
                "node_id": node_id, "current": cur, "target": target,
                "would_remove": remove, "would_change": diff(cur, target)}

    applied, skipped = _apply_state(cg, node_id, target, remove=remove)
    try:
        cg.rebuild_index()
    except Exception:                           # noqa: BLE001 —— 索引可重建，不阻断回滚
        pass
    after = state_of(cg, node_id) or {}
    rb = record(cg, node_id=node_id,
                pattern=note or f"撤销 {entry_id} 的结构变更，回到补充前的状态",
                action=f"回滚 {entry_id}",
                evidence="manual rollback", source="rollback",
                kind=KIND_ROLLBACK, before=cur, after=after,
                extra={"rollback_of": entry_id})
    return {"ok": True, "entry_id": entry_id, "node_id": node_id,
            "applied": applied, "skipped": skipped,
            "state": after, "rollback_entry": rb}


# --------------------------------------------------------------------------
# 自描述
# --------------------------------------------------------------------------

# 生效条件：无入参，任何调用都返回含 module/schema/ledger/carrier/principles/fields/kinds/state_fields/condition_dims/rollback/actions 的固定字典（kinds、state_fields、condition_dims 分别来自模块常量 KINDS、STATE_FIELDS、CONDITION_DIMS）。
def catalog():
    return {
        "module": "evolution",
        "schema": SCHEMA_VERSION,
        "ledger": f"{EVOLUTION_DIR}/{LEDGER_NAME}",
        "carrier": "md（人类可读账本 = 单一真相源，不引入第二种日志格式）",
        "principles": [
            "每一次修改 = 对一条缺失条件的补充",
            "记录的是认知规律与状态，不是实现细节（实现属于 git）",
            "回滚本身也记一条演化条目：撤销不可静默",
            "账本只追加，不原地改写（append-only md）",
            "规律按「缺失条件维度」聚类，看清反复缺什么",
        ],
        "fields": {
            "pattern": "规律（必填）：一句话认知规律",
            "missing": "缺失条件：补的是哪一维条件",
            "action": "动作：这次具体改了什么",
            "state_text": "状态：before→after 的人类可读差异",
            "evidence": "证据：触发本次演化的验证依据",
            "source": "来源：consolidate|verify|manual|...",
        },
        "kinds": list(KINDS),
        "state_fields": list(STATE_FIELDS),
        "condition_dims": list(CONDITION_DIMS),
        "rollback": {
            "scope": "frontmatter 认知状态字段 + layer 迁移",
            "not_covered": "正文 CCG 行文本、边权重、加密内容",
            "safety": "受保护节点降级被 protect.guard_move 拒绝时记入 skipped",
            "preview": "dry_run=true 只列 would_change，不落盘",
        },
        "actions": ["record", "entries", "show", "history", "patterns",
                    "summary", "rollback", "catalog"],
    }