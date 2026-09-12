# -*- coding: utf-8 -*-
"""真实库对齐（P32）：CCG 回填 + 能力标签注入。

为什么是「回填」而不是「重写」
------------------------------
迁移入库的历史节点里，条件信息**往往已经在 frontmatter 里**：
`condition_space`（四槽）、`non_applicable_conditions`、`verification_basis`、
`state_attributes.comment.*`。缺的只是把它们渲染成 CCG 正文行（`# 生效条件：…`
等）。缺了正文行，`judge_qualification` 一律判 BLINDSPOT——节点从「可检索」
掉到「不可判定」。

回填 = 把**已声明的证据**渲染成 CCG 行。它不发明条件，只搬运已有声明。

生效条件的来源链（本轮口径修正：观测位置 ≠ 生效条件）
----------------------------------------------------
生效条件**只能**来自两处，且优先成文声明：
  ① `state_attributes.comment.生效条件`（人/流程写下的成文声明）
  ② `nodefile.condition_space_text(frontmatter.condition_space)`（四槽合成）
旧版曾回退到 `condition_space.observation_position` **单槽**，加前缀「观测位置：」
冒充生效条件——那是把坐标的一维当成整条生效条件，真实库因此落了 109 条弱等价行。
该回退**已删除**；四槽不齐 → 不写（部分槽不构成完整条件空间声明），转待补台账。
`fix_conditions_*` 三个函数用于清洗存量：把已落库的单槽冒充行**重渲染**为合规
合成声明，或**删除并登记待补**——全程留痕、可回滚、幂等。

纪律（对齐 consolidate 的固化纪律）
----------------------------------
· 不猜测：字段只在**有来源**时才写；来源写进留痕 `basis`；无来源 → 跳过并计入
  `unfillable`，绝不编造。
· 可预演：`plan()` 只出报表、不改盘；`apply()` 才写。默认只回填「补完即可判定」
  的节点，`partial`（补完仍不全）默认不写，除非显式 `include_partial=True`。
· 可留痕：每次写入记一条 `_backfill.jsonl`（字段 / 写入值 / 依据 / 批次 / 操作者）。
· 可回滚：`rollback()` 按留痕反向应用，且**只在当前值仍等于写入值**时撤销
  （防覆盖后续人工修改），否则计入 `conflict` 跳过。
· fail-closed：密文节点一律跳过，**绝不解密回写**。

能力标签注入
------------
`cap:<op>` 标签让路由能返回建议能力名（`mcp_server` 读 frontmatter.tags 的
`cap:` 前缀）。匹配是**关键词启发式**（对标 `tokens.ALL_OPS` 工具名清单），
不是语义推断：结果带 `matched_by`（命中的关键词）与 `confidence`，调用方据此
判断可信度。只改 frontmatter.tags，不动正文。
"""
from __future__ import annotations

import hashlib
import os
import time
from collections import OrderedDict

from . import crypto, nodefile, tokens
from .consolidate import _has_ccg_line, _upsert_ccg_line
from .fsutil import append_jsonl, read_jsonl
from .mdcos import MdCGOS, _ccg_field

# ---- 常量 ----------------------------------------------------------------

BACKFILL_LOG = "_backfill.jsonl"

# 负记忆层是「故意无条件」的（覆盖标记），派生脚手架不该再被回填成事实
SKIP_LAYERS = ("rejected", "unresolved", "goals")
# 推断脚手架 / 概念层不得回填：否则会污染锚点解析（见 predict.anchor_from_description）
SKIP_TAGS = ("gap_hint", "scene", "reconstructed", "concept", "insight")
# 记忆系统**内部脚手架层**（锚点解析 anchor / 自模型修订 self）：不是用户知识，永不可回填；
# 被回填成事实会污染锚点解析与自模型（与 SKIP_LAYERS 同源理由）。crosscheck 亦复用之。
INTERNAL_LAYERS = ("anchor", "self")

# 验证基底枚举 → 可读声明（人/流程声明，不靠模型生成）
BASIS_TEXT = OrderedDict((
    ("compiler", "编译器/静态检查通过"),
    ("test", "单元测试/回归测试通过"),
    ("measurement", "实测数据（benchmark / 采样）"),
    ("formal_proof", "形式化证明"),
    ("data", "数据/语料统计"),
    # 来源一致性档（文科）：文科知识非可复现的物理事实，以来源表述一致为足够基底
    ("textbook", "依人教版教材表述一致（文科·来源一致性）"),
    ("public_kb", "公开知识库条目一致（文科·来源一致性）"),
    ("other", "人工评审或离线工序声明"),
))
BASIS_ENUM_DEFAULT = "other"

BATCH_DEFAULT = "backfill"

#: 生效条件的**唯一结构化来源**：condition_space 四槽合成（见 nodefile）
BASIS_CONDITION_SYNTH = "frontmatter.condition_space(四槽合成)"
#: 旧口径残留标记：把单槽 observation_position 冒充成生效条件的留痕 basis
LEGACY_CONDITION_BASIS = "frontmatter.condition_space.observation_position"
#: 存量清洗批次的默认批次名
FIX_BATCH_DEFAULT = "cond_fix"

#: 槽名 → 人读标签（台账/报告用；与 nodefile.CONDITION_SLOTS 同源）
_SLOT_LABEL = dict(nodefile.CONDITION_SLOTS)

# 能力标签规则：cap → 关键词（小写，中文原样）。仅保留 ALL_OPS 里真实存在的 op。
_CAP_RULES_RAW = OrderedDict((
    ("route",       ("路由", "召回", "检索", "rank", "rrf", "route")),
    ("export",      ("导出", "灾备", "备份", "搬运", "export", "evidence_pack")),
    ("ingest",      ("摄取", "导入", "摄入", "ingest", "分派")),
    ("session",     ("会话", "续接", "上下文压缩", "session", "compact")),
    ("maintain",    ("维护", "重要性", "重算", "快照", "前馈", "模式分离", "recalc")),
    ("consolidate", ("固化", "提升", "归纳", "聚类", "升格", "promote", "induce")),
    ("insight",     ("洞察", "情景重构", "盲区", "归因", "reconstruct", "outlook")),
    ("whitebox",    ("白箱", "资格判定", "裁决", "四态", "whitebox")),
    ("verify",      ("验证", "核验", "verdict")),
    ("predict",     ("预测", "趋势", "外推", "predict")),
    ("causal",      ("因果", "causal")),
    ("metacognition", ("元认知", "metacognition")),
    ("self_state",  ("自我状态", "状态卡", "self_state")),
    ("evolution",   ("演化", "evolution", "账本")),
    ("sustain",     ("维生", "自愈", "心跳", "sustain")),
    ("scrub",       ("擦除", "去污", "scrub")),
    ("protect",     ("保护", "私有内容", "protect")),
    ("forget",      ("遗忘", "失效", "forget")),
    ("link",        ("蜂群", "对等", "信任", "link")),
    ("identity",    ("身份", "主体", "identity")),
    ("goal",        ("目标", "goal")),
    ("recent",      ("近期事件", "recent")),
    ("theory",      ("协议版本", "theory")),
    ("consistency", ("一致性", "自洽", "consistency")),
    ("ref",         ("回读", "漂移", "悬空", "code_ref", "doc_ref")),
    ("index_code",  ("代码索引", "index_code")),
    ("index_doc",   ("文档索引", "章节索引", "index_doc")),
))
# 只保留真实 op，未知 op 静默丢弃（避免注入无效能力名）
CAP_RULES = OrderedDict(
    (cap, kws) for cap, kws in _CAP_RULES_RAW.items() if cap in tokens.ALL_OPS)


# ---- 通用工具 ------------------------------------------------------------

def _as_cg(x):
    """接受 root 路径或已构造的 cg 实例——保持密级隔离与密钥上下文。"""
    return MdCGOS(x) if isinstance(x, str) else x


def _as_text(v) -> str:
    if isinstance(v, (list, tuple)):
        return "；".join(str(x).strip() for x in v if str(x).strip())
    if v in (None, ""):
        return ""
    return str(v).strip()


def _comment(fm: dict) -> dict:
    st = (fm or {}).get("state_attributes")
    c = st.get("comment") if isinstance(st, dict) else None
    return c if isinstance(c, dict) else {}


def _ensure_comment(fm: dict) -> dict:
    st = fm.get("state_attributes")
    if not isinstance(st, dict):
        st = {}
        fm["state_attributes"] = st
    c = st.get("comment")
    if not isinstance(c, dict):
        c = {}
        st["comment"] = c
    return c


def _node_id(e: dict) -> str:
    return e.get("id") or os.path.basename(e.get("path") or "")[:-3]


def _condition_text(fm: dict) -> str:
    """→ 条件空间四槽合成的生效条件声明；四槽不齐 → ""（不冒充）。

    **唯一**的 condition_space → 生效条件 路径。旧版在此回退到
    `observation_position` **单槽**加「观测位置：」前缀——那正是
    「观测位置 ≠ 生效条件」的污染源（真实库 109 条），已删除。
    """
    return nodefile.condition_space_text((fm or {}).get("condition_space"))


def _sha(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:12]


def _entry_id(batch: str, nid: str) -> str:
    return hashlib.sha1(f"{batch}|{nid}".encode("utf-8")).hexdigest()[:12]


def _remove_ccg_line(content: str, field: str) -> str:
    """删掉 `# <字段>：…` 整行（回滚用）。"""
    keep = []
    for ln in (content or "").split("\n"):
        s = ln.strip().lstrip("#").strip()
        name = s.split("：")[0].split(":")[0].strip()
        if ln.strip().startswith("#") and name == field:
            continue
        keep.append(ln)
    return "\n".join(keep)


def _log_path(cg) -> str:
    return os.path.join(cg.root, BACKFILL_LOG)


# ---- 字段推导（唯一入口：只搬运已声明的证据） -----------------------------

def derive_fields(fm: dict, content: str, basis_text: str = None,
                  placeholder_out: list = None) -> dict:
    """按**已有声明**推导可回填字段 → `{field: (value, basis)}`。

    无来源的字段不出现在结果里（不猜测）。
    **占位标记（`骨架锚点`/`内容待填充`）同样不出现**——它不是已声明的事实；
    被丢弃的字段名记入 `placeholder_out`（可选出参），供报表区分
    「无来源」与「待填充」两种缺口。
    """
    c = _comment(fm)
    st = fm.get("state_attributes")
    st = st if isinstance(st, dict) else {}
    ph = placeholder_out if placeholder_out is not None else []
    out = {}

    def _put(field, value, basis):
        """有值且非占位标记才写出；占位值只记名，绝不渲染成事实。"""
        if not value:
            return
        if nodefile.is_placeholder_text(value):
            ph.append(field)
            return
        out[field] = (value, basis)

    if not _has_ccg_line(content, "功能名"):
        # 优先 state_attributes.name（迁移入库写入的规范功能名），回退 frontmatter.title
        raw_name = st.get("name")
        v = _as_text(raw_name) if isinstance(raw_name, (str, list, tuple)) else ""
        src = "state_attributes.name"
        if not v:
            v, src = _as_text(fm.get("title")), "frontmatter.title"
        _put("功能名", v, src)

    if not _has_ccg_line(content, "生效条件"):
        v = _as_text(c.get("生效条件") or c.get("适用条件"))
        src = "state_attributes.comment.生效条件"
        if not v:
            # 结构化来源：整条条件空间声明的合成，**不是** observation_position 单槽
            v, src = _condition_text(fm), BASIS_CONDITION_SYNTH
        _put("生效条件", v, src)

    if not _has_ccg_line(content, "子功能"):
        _put("子功能", _as_text(c.get("子功能") or c.get("子内容")),
             "state_attributes.comment.子功能")

    if not _has_ccg_line(content, "执行"):
        _put("执行", _as_text(c.get("执行") or c.get("执行方式")),
             "state_attributes.comment.执行")

    if not _has_ccg_line(content, "验证方式"):
        v = _as_text(c.get("验证方式"))
        src = "state_attributes.comment.验证方式"
        if not v and nodefile.verification_basis_valid(fm):
            vb = fm.get("verification_basis")
            v, src = BASIS_TEXT.get(vb, ""), f"frontmatter.verification_basis={vb}"
        if not v and basis_text:
            v, src = basis_text, "declared.basis_text"
        _put("验证方式", v, src)

    if not _has_ccg_line(content, "不适用条件"):
        _put("不适用条件",
             _as_text(c.get("不适用条件") or fm.get("non_applicable_conditions")),
             "state_attributes.comment/frontmatter.non_applicable_conditions")

    return out


# ---- 节点筛选 ------------------------------------------------------------

def _readable_guard(cg, e) -> bool:
    fn = getattr(cg, "_readable", None)
    if not callable(fn):
        return True
    try:
        return bool(fn(e))
    except Exception:                              # noqa: BLE001
        return False


def _classify(cg, e, nid, basis_text=None):
    """→ (skip_reason, item)；skip_reason 非空表示不参与回填。"""
    fm, content = cg._read(e)
    if fm is None:
        return "unreadable", None
    if crypto.is_encrypted(content):
        return "locked", None
    tags = fm.get("tags") or []
    if e.get("layer") in SKIP_LAYERS or any(t in SKIP_TAGS for t in tags):
        return "derived", None
    cpl = nodefile.ccg_completeness(content)
    if cpl["complete"]:
        return "present", None
    ph_fields = []
    der = derive_fields(fm, content, basis_text=basis_text,
                        placeholder_out=ph_fields)
    fill = {f: der[f] for f in der if not _has_ccg_line(content, f)}
    required_missing = [f for f in nodefile.CCG_REQUIRED
                        if not _has_ccg_line(content, f)]
    undeducible = [f for f in required_missing if f not in der]
    if not fill:
        # 无可写字段：区分「无来源」（unfillable）与「字段值全是待填充标记」
        # （placeholder）——后者是空壳节点，须转待填充工单，而非静默计入无来源。
        return ("placeholder" if ph_fields else "unfillable"), None
    cls = "backfillable" if not undeducible else "partial"
    # 待补台账：生效条件既不在正文、也推不出（四槽不全）→ 记缺失槽名。
    # 这不是「无来源」而是**缺证据**：补不动者按裁定判 BLINDSPOT，绝不静默 ACCEPT。
    cond_pending = []
    if not _has_ccg_line(content, "生效条件") and "生效条件" not in der:
        cond_pending = nodefile.condition_space_missing(fm.get("condition_space"))
    return "", {
        "id": nid, "layer": e.get("layer"), "class": cls,
        "fill": {f: {"value": v, "basis": b} for f, (v, b) in fill.items()},
        "missing_undeducible": undeducible,
        "placeholder_fields": ph_fields,
        "conditions_pending": cond_pending,
        "before_ratio": cpl["ratio"],
    }


def plan(x, layer=None, limit=None, ids=None, include_partial=False,
         basis_text=None, prefix=None) -> dict:
    """预演：产出可回填清单，不写盘。

    `prefix`：按 id 前缀收窄范围（真实库用 `kp_`，与核对工单同一边界）；
    内部 `anchor`/`self` 层一律出局（计入 `skipped_internal`）。
    """
    cg = _as_cg(x)
    rep = {"root": cg.root, "dry_run": True, "action": "backfill",
           "prefix": prefix, "nodes_scanned": 0, "skipped_locked": 0,
           "skipped_derived": 0, "skipped_internal": 0,
           "skipped_present": 0, "skipped_denied": 0, "unfillable": 0,
           "skipped_placeholder": 0, "nodes_with_placeholder": 0,
           "skipped_partial": 0, "targeted": 0,
           # 待写节点中生效条件仍缺声明的数量（全库台账见 conditions_pending）
           "targeted_missing_conditions": 0, "items": []}
    want = set(ids) if ids else None
    for nid, e in list((cg.index.get("nodes") or {}).items()):
        if want is not None and nid not in want:
            continue
        if prefix and not str(nid).startswith(prefix):
            continue
        if layer and e.get("layer") != layer:
            continue
        if e.get("layer") in INTERNAL_LAYERS:
            rep["skipped_internal"] += 1
            continue
        if not _readable_guard(cg, e):
            rep["skipped_denied"] += 1
            continue
        rep["nodes_scanned"] += 1
        reason, item = _classify(cg, e, nid, basis_text=basis_text)
        if reason == "locked":
            rep["skipped_locked"] += 1
            continue
        if reason == "derived":
            rep["skipped_derived"] += 1
            continue
        if reason == "present":
            rep["skipped_present"] += 1
            continue
        if reason == "unfillable":
            rep["unfillable"] += 1
            continue
        if reason == "placeholder":
            rep["skipped_placeholder"] += 1
            continue
        if item.get("placeholder_fields"):
            rep["nodes_with_placeholder"] += 1
        if item.get("conditions_pending"):
            rep["targeted_missing_conditions"] += 1
        if item["class"] == "partial" and not include_partial:
            rep["skipped_partial"] += 1
            continue
        item["entry_id"] = _entry_id("backfill", nid)
        rep["targeted"] += 1
        if limit is None or len(rep["items"]) < limit:
            rep["items"].append(item)
    rep["planned_ids"] = [i["id"] for i in rep["items"]]
    return rep


# ---- 回填写入 / 回滚 / 留痕 ----------------------------------------------

def apply(x, ids=None, entry_ids=None, layer=None, limit=None,
          batch=BATCH_DEFAULT, include_partial=False, basis_text=None,
          actor=None, prefix=None) -> dict:
    """执行回填：逐节点改写 md，写 `_backfill.jsonl` 留痕。"""
    cg = _as_cg(x)
    batch = batch or BATCH_DEFAULT
    p = plan(cg, layer=layer, limit=None, ids=ids, prefix=prefix,
             include_partial=include_partial, basis_text=basis_text)
    items = p["items"]
    if entry_ids:
        want = set(entry_ids)
        items = [i for i in items if i["entry_id"] in want]
    rep = {"root": cg.root, "dry_run": False, "action": "backfill",
           "batch": batch, "actor": actor, "planned": len(items),
           "written": 0, "skipped_drift": 0, "skipped_locked": 0,
           "entry_ids": [], "by_field": {}}
    for it in items:
        if limit is not None and rep["written"] >= limit:
            break
        nid = it["id"]
        e = cg.index["nodes"].get(nid)
        if not e:
            rep["skipped_drift"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None or crypto.is_encrypted(content):
            rep["skipped_locked"] += 1
            continue
        # 预演到执行之间节点可能被改动：只写仍缺失的字段
        todo = {f: d for f, d in it["fill"].items()
                if not _has_ccg_line(content, f)}
        if not todo:
            rep["skipped_drift"] += 1
            continue
        comment0 = _comment(fm)
        # 记录改写前的真相：rollback 必须「还原」而非「删除」——否则 comment
        # 里原有的声明会被误删，导致回填不可重复（回滚不是真逆操作）。
        prev_c = {f: comment0[f] for f in todo if f in comment0}
        fm_before = {}
        if "不适用条件" in todo:
            fm_before["non_applicable_conditions"] = {
                "had": "non_applicable_conditions" in fm,
                "value": fm.get("non_applicable_conditions")}
        if "验证方式" in todo and not nodefile.verification_basis_valid(fm):
            fm_before["verification_basis"] = {
                "had": "verification_basis" in fm,
                "value": fm.get("verification_basis")}
        comment = _ensure_comment(fm)
        wid = _sha(f"{nid}|{batch}|{time.time()}")
        applied = {}
        for f, d in todo.items():
            content = _upsert_ccg_line(content, f, d["value"])
            comment[f] = d["value"]
            if f == "不适用条件":
                fm["non_applicable_conditions"] = [
                    s.strip() for s in d["value"].split("；") if s.strip()]
            if f == "验证方式" and not nodefile.verification_basis_valid(fm):
                fm["verification_basis"] = BASIS_ENUM_DEFAULT
            applied[f] = {"after": d["value"], "basis": d["basis"],
                          "before": prev_c.get(f)}
            rep["by_field"][f] = rep["by_field"].get(f, 0) + 1
        cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                       durable=True)
        append_jsonl(_log_path(cg), {
            "action": "backfill", "ts": time.time(), "batch": batch,
            "actor": actor, "entry_id": it["entry_id"], "write_id": wid,
            "node": nid, "layer": e.get("layer"), "fields": applied,
            "fm_before": fm_before,
            "content_hash_after": _sha(content)})
        rep["written"] += 1
        rep["entry_ids"].append(it["entry_id"])
    if rep["written"]:
        cg.rebuild_index()
    rep["plan_remaining"] = max(0, p["targeted"] - len(items))
    return rep


def rollback(x, batch=None, entry_ids=None, actor=None) -> dict:
    """按留痕反向应用：撤销本批次回填（当前值 ≠ 写入值时跳过，防覆盖）。"""
    cg = _as_cg(x)
    want = set(entry_ids) if entry_ids else None
    rep = {"root": cg.root, "action": "backfill_rollback", "actor": actor,
           "batch": batch, "reverted": 0, "conflict": 0, "missing": 0,
           "fields_reverted": 0, "skipped_done": 0}
    log = list(read_jsonl(_log_path(cg)) or [])
    done = {r.get("write_id") for r in log
            if r.get("action") == "backfill_rollback" and r.get("write_id")}
    for rec in log:
        if rec.get("action") != "backfill":
            continue
        if rec.get("write_id") and rec.get("write_id") in done:
            rep["skipped_done"] += 1
            continue
        if batch and rec.get("batch") != batch:
            continue
        if want is not None and rec.get("entry_id") not in want:
            continue
        nid = rec.get("node")
        e = cg.index["nodes"].get(nid)
        if not e:
            rep["missing"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None:
            rep["missing"] += 1
            continue
        comment = _comment(fm)
        reverted, conflicted = {}, []
        for f, d in (rec.get("fields") or {}).items():
            if _ccg_field(content, f) != d.get("after"):
                conflicted.append(f)          # 已被后续修改 → 不撤销
                continue
            content = _remove_ccg_line(content, f)
            b = d.get("before")
            if b is None:
                comment.pop(f, None)          # 原本就没有 → 删回「无」
            else:
                comment[f] = b                # 原本有 → 还原原值（非删除）
            reverted[f] = d.get("after")
        if not reverted:
            rep["conflict"] += 1
            continue
        for k, box in (rec.get("fm_before") or {}).items():
            if box.get("had"):
                fm[k] = box.get("value")
            else:
                fm.pop(k, None)
        st = fm.get("state_attributes")
        if isinstance(st, dict) and isinstance(st.get("comment"), dict) \
                and not st["comment"]:
            st.pop("comment", None)
        cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                       durable=True)
        append_jsonl(_log_path(cg), {
            "action": "backfill_rollback", "ts": time.time(), "actor": actor,
            "batch": rec.get("batch"), "entry_id": rec.get("entry_id"),
            "write_id": rec.get("write_id"), "node": nid,
            "reverted": list(reverted), "conflict": conflicted})
        rep["reverted"] += 1
        rep["fields_reverted"] += len(reverted)
        if conflicted:
            rep["conflict"] += 1
    if rep["reverted"]:
        cg.rebuild_index()
    return rep


def history(x, limit=100, action=None, batch=None) -> dict:
    cg = _as_cg(x)
    recs = []
    for rec in read_jsonl(_log_path(cg)) or []:
        if action and rec.get("action") != action:
            continue
        if batch and rec.get("batch") != batch:
            continue
        recs.append(rec)
    total = len(recs)
    if limit is not None and limit >= 0:
        recs = recs[-limit:]
    return {"root": cg.root, "total": total, "returned": len(recs),
            "records": recs}


# ---- 能力标签注入（关键词启发式） ----------------------------------------

# 候选匹配不得吃进两类「自产词」，否则候选再生、plan 永不收敛：
#   ① `fm.tags`：`cap:<op>` 是**注入结果**，回流后 `cap:route` 自匹配关键词
#      "route"、`cap:self_state` 自匹配 "self_state"…… 已注入节点会重新成为候选；
#   ② `# 验证方式：` 模板行：它是 CCG 五要素的必备行，展开后**几乎全库**命中
#      「验证」，`cap:verify` 遂从能力判断退化为正文模板的副产品
#      （evolution 账本实测：预演命中 1630/1813）。
_CAP_TEMPLATE_LINES = ("验证方式",)


def _cap_body(content: str) -> str:
    """正文（供关键词匹配）——剔除 CCG 模板行，防模板词污染候选。"""
    keep = []
    for line in (content or "").splitlines():
        head = line.strip().lstrip("#").strip()
        head = head.split("：", 1)[0].split(":", 1)[0].strip()
        if head in _CAP_TEMPLATE_LINES:
            continue
        keep.append(line)
    return "\n".join(keep)


def _cap_text(e, fm, content) -> str:
    """候选匹配文本：节点标识 + CCG 字段 + 正文（**不含 `fm.tags`**）。"""
    parts = [_as_text(fm.get("title")), e.get("id") or ""]
    for f in ("功能名", "生效条件", "子功能"):
        v = _ccg_field(content, f)
        if v:
            parts.append(v)
    parts.append(_cap_body(content)[:300])
    return " ".join(parts).lower()


def cap_matches(text: str) -> list:
    hits = []
    for cap, kws in CAP_RULES.items():
        m = [k for k in kws if k in text]
        if m:
            hits.append({"cap": cap, "matched_by": m,
                         "confidence": round(min(1.0, 0.4 + 0.2 * len(m)), 3)})
    hits.sort(key=lambda h: (-h["confidence"], h["cap"]))
    return hits


def cap_plan(x, layer=None, limit=None, ids=None, min_conf=0.5) -> dict:
    """预演：按关键词启发式给出 `cap:<op>` 标签建议（含依据与置信度），不写盘。"""
    cg = _as_cg(x)
    rep = {"root": cg.root, "dry_run": True, "action": "cap",
           "min_conf": min_conf, "nodes_scanned": 0, "skipped_locked": 0,
           "skipped_present": 0, "skipped_denied": 0, "targeted": 0,
           "items": []}
    want = set(ids) if ids else None
    for nid, e in list((cg.index.get("nodes") or {}).items()):
        if want is not None and nid not in want:
            continue
        if layer and e.get("layer") != layer:
            continue
        if not _readable_guard(cg, e):
            rep["skipped_denied"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None or crypto.is_encrypted(content):
            rep["skipped_locked"] += 1
            continue
        rep["nodes_scanned"] += 1
        have = set(t for t in (fm.get("tags") or []) if isinstance(t, str))
        hits = [h for h in cap_matches(_cap_text(e, fm, content))
                if h["confidence"] >= min_conf
                and f"cap:{h['cap']}" not in have]
        if not hits:
            rep["skipped_present"] += 1
            continue
        item = {"id": nid, "layer": e.get("layer"), "caps": hits,
                "entry_id": _entry_id("cap", nid)}
        rep["targeted"] += 1
        if limit is None or len(rep["items"]) < limit:
            rep["items"].append(item)
    rep["planned_ids"] = [i["id"] for i in rep["items"]]
    return rep


def cap_apply(x, ids=None, entry_ids=None, layer=None, limit=None,
              batch=BATCH_DEFAULT, min_conf=0.5, actor=None) -> dict:
    """注入 `cap:<op>` 标签：只改 frontmatter.tags，不动正文。"""
    cg = _as_cg(x)
    batch = batch or BATCH_DEFAULT
    p = cap_plan(cg, layer=layer, limit=None, ids=ids, min_conf=min_conf)
    items = p["items"]
    if entry_ids:
        want = set(entry_ids)
        items = [i for i in items if i["entry_id"] in want]
    rep = {"root": cg.root, "dry_run": False, "action": "cap", "batch": batch,
           "actor": actor, "min_conf": min_conf, "planned": len(items),
           "written": 0, "skipped_locked": 0, "skipped_drift": 0,
           "tags_added": 0, "entry_ids": []}
    for it in items:
        if limit is not None and rep["written"] >= limit:
            break
        nid = it["id"]
        e = cg.index["nodes"].get(nid)
        if not e:
            rep["skipped_drift"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None or crypto.is_encrypted(content):
            rep["skipped_locked"] += 1
            continue
        tags = list(fm.get("tags") or [])
        added = [f"cap:{h['cap']}" for h in it["caps"] if f"cap:{h['cap']}" not in tags]
        if not added:
            rep["skipped_drift"] += 1
            continue
        fm["tags"] = tags + added
        cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                       durable=True)
        append_jsonl(_log_path(cg), {
            "action": "cap", "ts": time.time(), "batch": batch, "actor": actor,
            "entry_id": it["entry_id"], "write_id": _sha(f"cap|{nid}|{time.time()}"),
            "node": nid, "layer": e.get("layer"),
            "tags_added": added,
            "evidence": {h["cap"]: h["matched_by"] for h in it["caps"]},
            "confidence": {h["cap"]: h["confidence"] for h in it["caps"]}})
        rep["written"] += 1
        rep["tags_added"] += len(added)
        rep["entry_ids"].append(it["entry_id"])
    if rep["written"]:
        cg.rebuild_index()
    rep["plan_remaining"] = max(0, p["targeted"] - len(items))
    return rep


def cap_rollback(x, batch=None, entry_ids=None, actor=None) -> dict:
    """撤销 cap 注入：仅移除**仍在 tags 里**的 `cap:` 标签（防覆盖后续修改）。"""
    cg = _as_cg(x)
    want = set(entry_ids) if entry_ids else None
    rep = {"root": cg.root, "action": "cap_rollback", "actor": actor,
           "batch": batch, "reverted": 0, "conflict": 0, "missing": 0,
           "tags_removed": 0, "skipped_done": 0}
    log = list(read_jsonl(_log_path(cg)) or [])
    done = {r.get("write_id") for r in log
            if r.get("action") == "cap_rollback" and r.get("write_id")}
    for rec in log:
        if rec.get("action") != "cap":
            continue
        if rec.get("write_id") and rec.get("write_id") in done:
            rep["skipped_done"] += 1
            continue
        if batch and rec.get("batch") != batch:
            continue
        if want is not None and rec.get("entry_id") not in want:
            continue
        nid, added = rec.get("node"), rec.get("tags_added") or []
        e = cg.index["nodes"].get(nid)
        if not e:
            rep["missing"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None:
            rep["missing"] += 1
            continue
        tags = list(fm.get("tags") or [])
        removed = [t for t in added if t in tags]
        if not removed:
            rep["conflict"] += 1
            continue
        fm["tags"] = [t for t in tags if t not in set(removed)]
        cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                       durable=True)
        append_jsonl(_log_path(cg), {
            "action": "cap_rollback", "ts": time.time(), "actor": actor,
            "batch": rec.get("batch"), "entry_id": rec.get("entry_id"),
            "write_id": rec.get("write_id"), "node": nid,
            "tags_removed": removed})
        rep["reverted"] += 1
        rep["tags_removed"] += len(removed)
    if rep["reverted"]:
        cg.rebuild_index()
    return rep


# ---- 豁免解除（ccg_exempt 分批摘除） --------------------------------------

EXEMPT_FLAG = "ccg_exempt"


def _exempt_ready(fm: dict, content: str):
    """摘豁免前置条件 → `(ready, missing)`。

    硬约束（顺序依赖）：证据未补齐就摘豁免，节点会从 DEFER **退化为 BLINDSPOT**，
    比现状更差。故要求「合法 `verification_basis`」+「5 要素齐备（含验证方式行）」
    同时成立才允许摘除。
    """
    miss = []
    if not nodefile.verification_basis_valid(fm):
        miss.append("verification_basis")
    if not nodefile.ccg_completeness(content).get("complete"):
        miss.append("ccg5")
    return (not miss), miss


def exempt_plan(x, layer=None, limit=None, ids=None, require_ready=True,
                sample=0, prefix=None) -> dict:
    """预演：列出可摘 `ccg_exempt` 的节点（默认要求证据就绪），不写盘。

    `sample=N` 时按 id 序等距抽取 N 个作为验收样本（确定性，重跑同一样本）。
    `prefix`：按 id 前缀收窄范围（真实库用 `kp_`）；内部 `anchor`/`self` 层出局。
    """
    cg = _as_cg(x)
    rep = {"root": cg.root, "dry_run": True, "action": "exempt",
           "require_ready": require_ready, "prefix": prefix, "nodes_scanned": 0,
           "skipped_locked": 0, "skipped_denied": 0, "skipped_not_exempt": 0,
           "skipped_internal": 0, "skipped_unready": 0, "unready_reasons": {},
           "targeted": 0, "items": [], "sample": []}
    want = set(ids) if ids else None
    for nid, e in list((cg.index.get("nodes") or {}).items()):
        if want is not None and nid not in want:
            continue
        if prefix and not str(nid).startswith(prefix):
            continue
        if layer and e.get("layer") != layer:
            continue
        if e.get("layer") in INTERNAL_LAYERS:
            rep["skipped_internal"] += 1
            continue
        if not _readable_guard(cg, e):
            rep["skipped_denied"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None or crypto.is_encrypted(content):
            rep["skipped_locked"] += 1
            continue
        rep["nodes_scanned"] += 1
        if not fm.get(EXEMPT_FLAG):
            rep["skipped_not_exempt"] += 1
            continue
        ready, miss = _exempt_ready(fm, content)
        if require_ready and not ready:
            rep["skipped_unready"] += 1
            for m in miss:
                rep["unready_reasons"][m] = rep["unready_reasons"].get(m, 0) + 1
            # 批量：直接过滤（报表已计数）；显式点名：入列交由 apply 判定并留
            # `exempt_skip` 记录——被点名的节点绝不静默丢弃。
            if want is None:
                continue
        item = {"id": nid, "layer": e.get("layer"), "ready": ready,
                "missing": miss, "basis": fm.get("verification_basis"),
                "entry_id": _entry_id("exempt", nid)}
        rep["targeted"] += 1
        if limit is None or len(rep["items"]) < limit:
            rep["items"].append(item)
    rep["planned_ids"] = [i["id"] for i in rep["items"]]
    if sample and rep["items"]:
        ids_all = [i["id"] for i in rep["items"]]
        k = min(int(sample), len(ids_all))
        stride = max(1, len(ids_all) // k)
        rep["sample"] = ids_all[::stride][:k]
    return rep


def exempt_apply(x, ids=None, entry_ids=None, layer=None, limit=None,
                 batch=BATCH_DEFAULT, require_ready=True, actor=None,
                 prefix=None) -> dict:
    """分批摘除 `ccg_exempt`（置 False 而非删键，便于反向还原）。

    就绪校验在**写入前**再查一次（plan 与 apply 之间可能被改动）；
    不满足则计 `skipped_unready` 并留 `exempt_skip` 记录，绝不硬摘。
    """
    cg = _as_cg(x)
    batch = batch or BATCH_DEFAULT
    p = exempt_plan(cg, layer=layer, ids=ids, require_ready=require_ready,
                    prefix=prefix)
    items = p["items"]
    if entry_ids:
        want = set(entry_ids)
        items = [i for i in items if i["entry_id"] in want]
    rep = {"root": cg.root, "dry_run": False, "action": "exempt", "batch": batch,
           "actor": actor, "require_ready": require_ready, "planned": len(items),
           "written": 0, "skipped_unready": 0, "skipped_locked": 0,
           "skipped_drift": 0, "entry_ids": []}
    for it in items:
        if limit is not None and rep["written"] >= limit:
            break
        nid = it["id"]
        e = cg.index["nodes"].get(nid)
        if not e:
            rep["skipped_drift"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None or crypto.is_encrypted(content):
            rep["skipped_locked"] += 1
            continue
        if not fm.get(EXEMPT_FLAG):
            rep["skipped_drift"] += 1
            continue
        ready, miss = _exempt_ready(fm, content)
        if require_ready and not ready:
            rep["skipped_unready"] += 1
            append_jsonl(_log_path(cg), {
                "action": "exempt_skip", "ts": time.time(), "batch": batch,
                "actor": actor, "node": nid, "missing": miss})
            continue
        before = fm.get(EXEMPT_FLAG)
        fm[EXEMPT_FLAG] = False
        wid = _sha(f"exempt|{nid}|{time.time()}")
        cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                       durable=True)
        append_jsonl(_log_path(cg), {
            "action": "exempt", "ts": time.time(), "batch": batch, "actor": actor,
            "entry_id": it["entry_id"], "write_id": wid, "node": nid,
            "layer": e.get("layer"), "exempt_before": before,
            "basis": fm.get("verification_basis")})
        rep["written"] += 1
        rep["entry_ids"].append(it["entry_id"])
    if rep["written"]:
        cg.rebuild_index()
    rep["plan_remaining"] = max(0, p["targeted"] - len(items))
    return rep


def exempt_rollback(x, batch=None, entry_ids=None, actor=None) -> dict:
    """反向还原 `ccg_exempt`：仅当当前仍为「已摘」状态时还原，否则计 conflict。"""
    cg = _as_cg(x)
    want = set(entry_ids) if entry_ids else None
    rep = {"root": cg.root, "action": "exempt_rollback", "actor": actor,
           "batch": batch, "reverted": 0, "conflict": 0, "missing": 0,
           "skipped_done": 0}
    log = list(read_jsonl(_log_path(cg)) or [])
    done = {r.get("write_id") for r in log
            if r.get("action") == "exempt_rollback" and r.get("write_id")}
    for rec in log:
        if rec.get("action") != "exempt":
            continue
        if rec.get("write_id") and rec.get("write_id") in done:
            rep["skipped_done"] += 1
            continue
        if batch and rec.get("batch") != batch:
            continue
        if want is not None and rec.get("entry_id") not in want:
            continue
        nid = rec.get("node")
        e = cg.index["nodes"].get(nid)
        if not e:
            rep["missing"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None:
            rep["missing"] += 1
            continue
        if fm.get(EXEMPT_FLAG):
            rep["conflict"] += 1
            continue
        fm[EXEMPT_FLAG] = rec.get("exempt_before", True)
        cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                       durable=True)
        append_jsonl(_log_path(cg), {
            "action": "exempt_rollback", "ts": time.time(), "actor": actor,
            "batch": rec.get("batch"), "entry_id": rec.get("entry_id"),
            "write_id": rec.get("write_id"), "node": nid,
            "exempt_restored": fm.get(EXEMPT_FLAG)})
        rep["reverted"] += 1
    if rep["reverted"]:
        cg.rebuild_index()
    return rep


# ---- 待补台账 / 存量清洗（生效条件口径修正） ------------------------------
#
# 背景：旧口径把 `condition_space.observation_position` 单槽加前缀「观测位置：」
# 当作生效条件写入（真实库 109 条）。观测位置 ≠ 生效条件——生效条件是**整条**
# 条件空间声明的合成。本段负责三件事：
#   ① conditions_pending   只读台账：未声明且四槽推不出的节点
#   ② fix_conditions_*     清洗：冒充行重渲染为合规声明，或删除并登记待补
#   ③ verify_conditions    只读复算：验收指标 legacy_position == 0


def conditions_pending(x, prefix=None, layer=None, limit=None) -> dict:
    """只读台账：列出「未声明生效条件、且四槽推不出」的节点及其缺失槽。

    生效条件已成为必填项（`CCG_REQUIRED`），但存量节点未必有足够声明可补。
    这类节点**不能静默判 ACCEPT**：进本台账等待后续补充；确实补不动者由资格
    判定落 BLINDSPOT（而不是被「常用条件默认省略」掩盖）。本函数不写盘。
    """
    cg = _as_cg(x)
    rep = {"root": cg.root, "dry_run": True, "action": "conditions_pending",
           "prefix": prefix, "nodes_scanned": 0, "skipped_locked": 0,
           "skipped_denied": 0, "skipped_internal": 0, "skipped_derived": 0,
           "declared": 0, "derivable": 0, "pending": 0,
           "by_missing": {}, "items": []}
    for nid, e in list((cg.index.get("nodes") or {}).items()):
        if prefix and not str(nid).startswith(prefix):
            continue
        if layer and e.get("layer") != layer:
            continue
        if e.get("layer") in INTERNAL_LAYERS:
            rep["skipped_internal"] += 1
            continue
        if not _readable_guard(cg, e):
            rep["skipped_denied"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None or crypto.is_encrypted(content):
            rep["skipped_locked"] += 1
            continue
        if (e.get("layer") in SKIP_LAYERS
                or any(t in SKIP_TAGS for t in (fm.get("tags") or []))):
            rep["skipped_derived"] += 1
            continue
        rep["nodes_scanned"] += 1
        if _has_ccg_line(content, "生效条件"):
            rep["declared"] += 1
            continue
        if "生效条件" in derive_fields(fm, content):
            # 有来源、只是还没接线 → 属于「待回填」，不是缺证据
            rep["derivable"] += 1
            continue
        cs = fm.get("condition_space")
        miss = nodefile.condition_space_missing(cs)
        if not isinstance(cs, dict) or len(miss) == len(nodefile.CONDITION_SLOTS):
            key = "无条件空间声明"
        else:
            key = "缺" + "+".join(_SLOT_LABEL.get(k, k) for k in miss)
        rep["by_missing"][key] = rep["by_missing"].get(key, 0) + 1
        rep["pending"] += 1
        if limit is None or len(rep["items"]) < limit:
            rep["items"].append({
                "id": nid, "layer": e.get("layer"), "missing_slots": miss,
                "missing_text": key,
                "fallback": "补写生效条件；确实补不动 → 判 BLINDSPOT"})
    if limit is not None:
        rep["items"] = rep["items"][:limit]
    return rep


def _legacy_condition_records(cg) -> dict:
    """→ {node: {after, original, …}}：我们**自己写下的**单槽冒充行（真源 = 留痕）。

    只有留痕里 `basis == LEGACY_CONDITION_BASIS` 的行才敢自动改——人写下的
    「观测位置：…」声明不在其列（宁可漏改，不可误改）。已被回滚的写入剔除；
    同一节点多次写入时以最后一次为准。
    """
    log = list(read_jsonl(_log_path(cg)) or [])
    undone = {r.get("write_id") for r in log
              if r.get("action") == "backfill_rollback" and r.get("write_id")}
    out = {}
    for rec in log:
        if rec.get("action") != "backfill":
            continue
        if rec.get("write_id") and rec.get("write_id") in undone:
            continue
        f = (rec.get("fields") or {}).get("生效条件")
        if not isinstance(f, dict) or f.get("basis") != LEGACY_CONDITION_BASIS:
            continue
        nid = rec.get("node")
        if not nid:
            continue
        out[nid] = {"after": f.get("after"), "original": f.get("before"),
                    "write_id": rec.get("write_id"), "batch": rec.get("batch")}
    return out


def fix_conditions_plan(x, prefix=None, limit=None) -> dict:
    """预演：清洗存量单槽冒充行。不写盘。

    逐条判定（都要求「当前值仍等于我们当初写入的值」，否则计 `conflict`、不碰）：
      · 四槽齐备 → `rewrite`：改写为 `condition_space_text(cs)` 合成声明；
      · 四槽不全 → `drop`：删掉冒充行并登记待补。补不全的行留着比删掉更危险——
        它会被当成生效条件读，等于把坐标的一维当成整条声明。
    """
    cg = _as_cg(x)
    rep = {"root": cg.root, "dry_run": True, "action": "fix_conditions",
           "prefix": prefix, "legacy": 0, "targeted": 0, "rewrite": 0,
           "drop": 0, "conflict": 0, "missing": 0, "skipped_locked": 0,
           "skipped_denied": 0, "items": []}
    for nid, rec in _legacy_condition_records(cg).items():
        if prefix and not str(nid).startswith(prefix):
            continue
        e = cg.index["nodes"].get(nid)
        if not e:
            rep["missing"] += 1
            continue
        if not _readable_guard(cg, e):
            rep["skipped_denied"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None or crypto.is_encrypted(content):
            rep["skipped_locked"] += 1
            continue
        rep["legacy"] += 1
        cur = _ccg_field(content, "生效条件") or ""
        if cur != (rec.get("after") or ""):
            rep["conflict"] += 1                 # 已被后续改动 → 不碰
            continue
        new = _condition_text(fm)
        act = "rewrite" if new else "drop"
        rep["targeted"] += 1
        rep[act] += 1
        if limit is None or len(rep["items"]) < limit:
            rep["items"].append({
                "id": nid, "layer": e.get("layer"), "action": act,
                "before": cur, "after": new,
                "missing_slots": nodefile.condition_space_missing(
                    fm.get("condition_space")),
                "comment_before": (_comment(fm) or {}).get("生效条件"),
                "comment_original": rec.get("original"),
                "entry_id": _entry_id(FIX_BATCH_DEFAULT, nid)})
    rep["planned_ids"] = [i["id"] for i in rep["items"]]
    return rep


def fix_conditions_apply(x, ids=None, entry_ids=None, prefix=None, limit=None,
                         batch=FIX_BATCH_DEFAULT, actor=None) -> dict:
    """执行清洗：`rewrite` 改写为四槽合成声明；`drop` 删行并登记待补。

    写盘与留痕同 `apply`：`_backfill.jsonl` 记 `condition_fix`；`drop` 另记
    `condition_pending`（待补台账的可追溯副本）。幂等：清洗后不再有候选行。
    """
    cg = _as_cg(x)
    batch = batch or FIX_BATCH_DEFAULT
    p = fix_conditions_plan(cg, prefix=prefix, limit=None)
    items = p["items"]
    if ids:
        want = set(ids)
        items = [i for i in items if i["id"] in want]
    if entry_ids:
        want = set(entry_ids)
        items = [i for i in items if i["entry_id"] in want]
    rep = {"root": cg.root, "dry_run": False, "action": "fix_conditions",
           "batch": batch, "actor": actor, "planned": len(items),
           "rewritten": 0, "dropped": 0, "pending_logged": 0,
           "skipped_drift": 0, "skipped_locked": 0, "skipped_denied": 0,
           "entry_ids": []}
    for it in items:
        if limit is not None and (rep["rewritten"] + rep["dropped"]) >= limit:
            break
        nid = it["id"]
        e = cg.index["nodes"].get(nid)
        if not e:
            rep["skipped_drift"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None or crypto.is_encrypted(content):
            rep["skipped_locked"] += 1
            continue
        # 预演 → 执行之间可能被改动：当前值必须仍等于我们当初写入的值
        cur = _ccg_field(content, "生效条件")
        comment_before = (_comment(fm) or {}).get("生效条件")
        if (cur or "") != (it["before"] or "") \
                or comment_before != it["comment_before"]:
            rep["skipped_drift"] += 1
            continue
        comment = _ensure_comment(fm)
        if it["action"] == "rewrite":
            content = _upsert_ccg_line(content, "生效条件", it["after"])
            comment["生效条件"] = it["after"]
        else:
            content = _remove_ccg_line(content, "生效条件")
            # comment 里那份是同一污染的副本 → 还原为**写入前**的原值（真逆操作）
            orig = it["comment_original"]
            if orig in (None, ""):
                comment.pop("生效条件", None)
            else:
                comment["生效条件"] = orig
        st = fm.get("state_attributes")
        if isinstance(st, dict) and isinstance(st.get("comment"), dict) \
                and not st["comment"]:
            st.pop("comment", None)
        cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                       durable=True)
        append_jsonl(_log_path(cg), {
            "action": "condition_fix", "ts": time.time(), "batch": batch,
            "actor": actor, "entry_id": it["entry_id"],
            "write_id": _sha(f"cond_fix|{nid}|{time.time()}"),
            "node": nid, "layer": e.get("layer"), "fix": it["action"],
            "fields": {"生效条件": {
                "before": it["before"], "after": it["after"],
                "basis": BASIS_CONDITION_SYNTH if it["action"] == "rewrite"
                         else "dropped:legacy_position"}},
            "comment_before": comment_before,
            "comment_original": it["comment_original"],
            "missing_slots": it["missing_slots"],
            "content_hash_after": _sha(content)})
        if it["action"] == "rewrite":
            rep["rewritten"] += 1
        else:
            rep["dropped"] += 1
            append_jsonl(_log_path(cg), {
                "action": "condition_pending", "ts": time.time(),
                "batch": batch, "actor": actor, "node": nid,
                "layer": e.get("layer"), "missing_slots": it["missing_slots"],
                "reason": "四槽不可合成：单槽冒充行已删除，等待后续补充；"
                          "确实补不动则判 BLINDSPOT"})
            rep["pending_logged"] += 1
        rep["entry_ids"].append(it["entry_id"])
    if rep["rewritten"] or rep["dropped"]:
        cg.rebuild_index()
    rep["plan_remaining"] = max(0, p["targeted"] - len(items))
    return rep


def fix_conditions_rollback(x, batch=None, entry_ids=None, actor=None) -> dict:
    """按留痕反向应用：恢复被改写的旧值 / 重建被删除的冒充行。

    与 `rollback` 同一条纪律：**只在当前值仍等于写入值**时撤销，
    否则计 `conflict` 跳过（防覆盖后续人工修改）。
    """
    cg = _as_cg(x)
    want = set(entry_ids) if entry_ids else None
    rep = {"root": cg.root, "action": "fix_conditions_rollback", "actor": actor,
           "batch": batch, "reverted": 0, "conflict": 0, "missing": 0,
           "skipped_done": 0}
    log = list(read_jsonl(_log_path(cg)) or [])
    done = {r.get("write_id") for r in log
            if r.get("action") == "fix_conditions_rollback" and r.get("write_id")}
    for rec in log:
        if rec.get("action") != "condition_fix":
            continue
        if rec.get("write_id") and rec.get("write_id") in done:
            rep["skipped_done"] += 1
            continue
        if batch and rec.get("batch") != batch:
            continue
        if want is not None and rec.get("entry_id") not in want:
            continue
        nid = rec.get("node")
        e = cg.index["nodes"].get(nid)
        if not e:
            rep["missing"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None:
            rep["missing"] += 1
            continue
        d = (rec.get("fields") or {}).get("生效条件") or {}
        cur = _ccg_field(content, "生效条件") or ""
        if cur != (d.get("after") or ""):
            rep["conflict"] += 1                 # 已被后续改动 → 不撤销
            continue
        before = d.get("before")
        if before in (None, ""):
            content = _remove_ccg_line(content, "生效条件")
        else:
            content = _upsert_ccg_line(content, "生效条件", before)
        comment = _ensure_comment(fm)
        cb = rec.get("comment_before")
        if cb in (None, ""):
            comment.pop("生效条件", None)
        else:
            comment["生效条件"] = cb
        st = fm.get("state_attributes")
        if isinstance(st, dict) and isinstance(st.get("comment"), dict) \
                and not st["comment"]:
            st.pop("comment", None)
        cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                       durable=True)
        append_jsonl(_log_path(cg), {
            "action": "fix_conditions_rollback", "ts": time.time(),
            "actor": actor, "batch": rec.get("batch"),
            "entry_id": rec.get("entry_id"), "write_id": rec.get("write_id"),
            "node": nid, "restored": before})
        rep["reverted"] += 1
    if rep["reverted"]:
        cg.rebuild_index()
    return rep


def verify_conditions(x, prefix=None, limit=None) -> dict:
    """复算核对（只读）：生效条件行的来源分布 + 弱等价残留计数。

    `legacy_position` 必须为 **0**——这是本轮口径修正的验收指标：
    「观测位置：X」单槽冒充行不得再出现在任何节点里。
    """
    cg = _as_cg(x)
    rep = {"root": cg.root, "dry_run": True, "action": "verify_conditions",
           "prefix": prefix, "nodes_scanned": 0, "absent": 0, "declared": 0,
           "from_synthesis": 0, "from_comment": 0, "legacy_position": 0,
           "other": 0, "by_prefix": {}, "legacy_ids": []}
    for nid, e in list((cg.index.get("nodes") or {}).items()):
        if prefix and not str(nid).startswith(prefix):
            continue
        if e.get("layer") in INTERNAL_LAYERS:
            continue
        fm, content = cg._read(e)
        if fm is None or crypto.is_encrypted(content):
            continue
        rep["nodes_scanned"] += 1
        cur = _ccg_field(content, "生效条件")
        if not cur:
            rep["absent"] += 1
            kind = "absent"
        else:
            rep["declared"] += 1
            synth = _condition_text(fm)
            cmt = _as_text(_comment(fm).get("生效条件"))
            if nodefile.is_legacy_position_condition(cur):
                rep["legacy_position"] += 1
                kind = "legacy_position"
                if limit is None or len(rep["legacy_ids"]) < limit:
                    rep["legacy_ids"].append(nid)
            elif synth and cur == synth:
                rep["from_synthesis"] += 1
                kind = "from_synthesis"
            elif cmt and cur == cmt:
                rep["from_comment"] += 1
                kind = "from_comment"
            else:
                rep["other"] += 1
                kind = "other"
        box = rep["by_prefix"].setdefault(str(nid).split("_")[0], {})
        box[kind] = box.get(kind, 0) + 1
    return rep


# ---- 统一入口 ------------------------------------------------------------

ACTIONS = ("backfill", "backfill_rollback", "backfill_history",
           "cap", "cap_rollback", "cap_history",
           "exempt", "exempt_rollback", "exempt_history")


def run(x, action, **kw) -> dict:
    """`maintain` op 的分派入口：action ∈ ACTIONS。"""
    if action == "backfill":
        if kw.get("apply"):
            return apply(x, **{k: v for k, v in kw.items() if k != "apply"})
        return plan(x, **{k: v for k, v in kw.items() if k != "apply"})
    if action == "backfill_rollback":
        return rollback(x, **kw)
    if action == "backfill_history":
        return history(x, **kw)
    if action == "cap":
        if kw.get("apply"):
            return cap_apply(x, **{k: v for k, v in kw.items() if k != "apply"})
        return cap_plan(x, **{k: v for k, v in kw.items() if k != "apply"})
    if action == "cap_rollback":
        return cap_rollback(x, **kw)
    if action == "cap_history":
        return history(x, action="cap", **kw)
    if action == "exempt":
        if kw.get("apply"):
            return exempt_apply(x, **{k: v for k, v in kw.items() if k != "apply"})
        return exempt_plan(x, **{k: v for k, v in kw.items() if k != "apply"})
    if action == "exempt_rollback":
        return exempt_rollback(x, **kw)
    if action == "exempt_history":
        return history(x, action="exempt", **kw)
    raise ValueError(f"未知 backfill action：{action}（允许：{ACTIONS}）")
