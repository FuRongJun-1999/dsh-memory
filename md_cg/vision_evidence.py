# -*- coding: utf-8 -*-
"""G5 · 视觉证据回填（守卫式 / 零 LLM / 不读图像 / 不重跑视觉）。

裁定依据
--------
`docs/mdcg/认知图_G4-G8缺口裁定单_v0.1.md` §三（四态 = ACCEPT，条件 = 脱敏 + 只读 AEIS）。
缺口根因（库外只读观测）：产出侧 `vision_pipeline.cg_ingest` 只取
`p.get("model_evidence")`，白箱 `geometry_parts` 部件不带该键 → 部件节点证据面
恒为 `{}`。即「证据口径未定义」，不是「没有证据」。

证据源（**主证据源**，只读、不落图、不落敏感语义文本）
------------------------------------------------------
· `AEIS/data/vision/<图集>/parts_*.json`（如 `parts_0.json`）
· `AEIS/data/vision/<图集>/vision_*.json`（同 schema：parts 带全部判定字段）
· 权威口径文档：`AEIS/data/vision/VISION_PIPELINE_已验证_v1.md`
关键：**库内节点正文本身**也是同一白箱管线的持久化产物（部件行含
`bbox / cond_hash / verdict / reason / fg`），可与归档逐部件结构化结果互证。

三档映射（裁定单 §三，逐字段必得有源，缺一不落）
------------------------------------------------
· tier 1 模型证据：源数据含 `model_evidence` → `{model, kpts_used, min_conf}`。
  本库归档与节点均无该键 → 本轮恒不适用。
· tier 2 白箱证据：无模型键但判定要素齐 → 落
  `{algo, confidence, cond_hash, fg_ratio, occluded, verdict_reason}`。
· tier 3 盲区：两者皆无 → `evidence` 保持为空，标 `evidence_status=BLINDSPOT`
  （附 `evidence_blindspot_reason`），**不编造**。

归因纪律（白箱优先、模型次之、缺失不编造）
------------------------------------------
· 节点正文已记录者优先取节点实测（`cond_hash / fg_ratio / verdict_reason`）；
  节点未记录者（`algo / confidence / occluded`）由归档补全。
· 连接键可验证：imgpart 家族用 `cond_hash` 精确连接；vpipe 家族用
  （家族根 `cond_hash` → 归档 `identity.cond_hash`）+ `type` 连接。
· 连接后必须校验 `verdict` 一致；不一致 → 判 BLINDSPOT（`verdict_mismatch`），
  不落半可信证据。
· 6 字段任一取不到源 → BLINDSPOT（`missing_field:<name>`）。
· 根节点（`部件树根`）不承载四态裁定 → 恒 BLINDSPOT（`root_no_verdict`）。

脱敏
----
· 不读取任何图像文件；不重跑视觉；证据内只落结构化字段。
· 图集目录名不进库：一律以编号引用（`图集_0`…`图集_9`，取自目录尾部 `_<N>`）。
· `verdict_reason` 为算法产出的结构化判定理由（非敏感语义文本），且节点正文
  原本已含该字段，故不构成新增泄露面。

纪律（对齐 backfill / consolidate）
-----------------------------------
· 不猜测：字段只在有源时写，来源写进 `evidence_source` / `evidence_joined_by`。
· 可预演：`plan()` 只出报表；`apply()` 才写。
· 可留痕：每次写入记一条 `_vision_evidence.jsonl`（批次 / 节点 / 档位 / 来源 /
  连接键 / 写入字段）。
· 可回滚：`rollback()` 按留痕反向删除本批次写入的证据键（幂等，防覆盖）。
· fail-closed：密文节点一律跳过，绝不解密回写。
· 只落 frontmatter 证据面：不动正文（含正文内联 `evidence={}` 槽），
  避免改 `content_hash` 破坏上游去重——列为未闭合项。
"""
from __future__ import annotations

import glob
import json
import os
import re
import time

from . import crypto, evolution
from .fsutil import append_jsonl, read_jsonl
from .mdcos import MdCGOS

# ---- 常量 -----------------------------------------------------------------

EVIDENCE_LOG = "_vision_evidence.jsonl"

#: 视觉节点 id 前缀（G4 归位后位于 contextual 层）
VISION_PREFIXES = ("imgpart_", "vpipe_")

#: 视觉证据归档根（**本仓** data/vision，随大脑自带；只读）。
#: 可用环境变量覆盖；`MDCG_AEIS_ROOT` 为三层拆分前的遗留名，仍兼容。
VISION_ROOT_ENV = "MDCG_VISION_ROOT"
LEGACY_VISION_ROOT_ENV = "MDCG_AEIS_ROOT"
_HERE = os.path.dirname(os.path.abspath(__file__))
#: 默认 = 本仓根 → 证据落在 <repo>/data/vision（拆分子项 B7：不再指向外部 AEIS 仓）
DEFAULT_VISION_ROOT = os.path.dirname(_HERE)

#: 权威口径文档（只读引用，写进报表供核对；相对证据归档根）
AUTHORITY_DOC = "data/vision/VISION_PIPELINE_已验证_v1.md"

#: 裁定单 §三 tier-2 六字段：逐字段必得有源，缺一即不落（→ BLINDSPOT）
TIER2_FIELDS = ("algo", "confidence", "cond_hash", "fg_ratio", "occluded",
                "verdict_reason")

STATUS_MODEL = "MODEL"
STATUS_WHITEBOX = "WHITEBOX"
STATUS_BLINDSPOT = "BLINDSPOT"

#: 本轮写入的全部 frontmatter 证据键（回滚据此删除）
EVIDENCE_KEYS = ("evidence", "evidence_status", "evidence_tier",
                 "evidence_source", "evidence_joined_by", "evidence_doc",
                 "evidence_blindspot_reason", "evidence_batch", "evidence_at")

BATCH_DEFAULT = "visevid"

ROOT_MARK = "部件树根"

# 部件行：`<head> 部件 <type>: bbox=[..] <rest>`
_RE_PART = re.compile(
    r"^(?P<head>.+?)\s+部件\s+(?P<type>[^:：]+)\s*[:：]\s*"
    r"bbox=\[(?P<bbox>[^\]]*)\]\s*(?P<rest>.*)$")
_RE_COND = re.compile(r"cond_hash=([0-9a-fA-F]{6,})")
_RE_VERDICT = re.compile(r"(?:^|\s)verdict=([A-Za-z]+)")
_RE_REASON = re.compile(r"(?:^|\s)reason=(.*?)(?:\s+fg=|\s+evidence=|$)")
_RE_FG = re.compile(r"(?:^|\s)fg=([0-9]*\.?[0-9]+)")
_RE_NPARTS = re.compile(r"(\d+)\s*部件")
_RE_IMG_TAG = re.compile(r"^img(\d+)$")
_RE_DIR_N = re.compile(r"_(\d+)$")


# ---- 通用工具 -------------------------------------------------------------

# 生效条件：x 为 str 时返回 MdCGOS(x) 新实例，否则原样返回 x。
def _as_cg(x):
    """接受 root 路径或已构造 cg 实例——保持密级隔离与密钥上下文。"""
    return MdCGOS(x) if isinstance(x, str) else x


# 生效条件：无必需形参，调用即返回 time.strftime("%Y%m%d-%H%M%S") 的当前批次串。
def _now_batch() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


# 生效条件：base 为字符串批号，先读 _log_path(cg) 的 jsonl 收集 batch 字段中以 base 开头的已有值，base 未被占用则原样返回 base，已占用则返回首个未占用的 f"{base}.{i}"（i 从 2 递增）。
def _unique_batch(cg, base: str) -> str:
    """同秒重复调用时批号去重（后缀 .2/.3…），保证按批次回滚不打偏。"""
    seen = set()
    for rec in read_jsonl(_log_path(cg)) or []:
        b = rec.get("batch")
        if isinstance(b, str) and b.startswith(base):
            seen.add(b)
    if base not in seen:
        return base
    i = 2
    while f"{base}.{i}" in seen:
        i += 1
    return f"{base}.{i}"


# 生效条件：cg 具 root 属性时取 cg.root、否则取 str(cg) 作为 root，返回 os.path.join(root, EVIDENCE_LOG)。
def _log_path(cg) -> str:
    root = cg.root if hasattr(cg, "root") else str(cg)
    return os.path.join(root, EVIDENCE_LOG)


# 生效条件：batch 与 nid 恒以 "%s|%s" 拼接成条目号，不做空值或类型校验。
def _entry_id(batch: str, nid: str) -> str:
    return "%s|%s" % (batch, nid)


# 生效条件：v 为 list/tuple 时返回各元素 str(x).strip() 后非空项以「；」连接；否则 v 为 None 返回空串，其余值返回 str(v).strip()。
def _as_text(v) -> str:
    if isinstance(v, (list, tuple)):
        return "；".join(str(x).strip() for x in v if str(x).strip())
    return "" if v is None else str(v).strip()


# 生效条件：path 经 abspath→dirname→basename 取名后匹配 _RE_DIR_N，命中则返回 int(m.group(1))，未命中返回 None。
def _gallery_no(path: str):
    """图集编号：目录名尾部 `_<N>`；缺省 None（脱敏引用用）。"""
    name = os.path.basename(os.path.dirname(os.path.abspath(path)))
    m = _RE_DIR_N.search(name)
    return int(m.group(1)) if m else None


# 生效条件：gal 非 None 时返回 "图集_%s" % gal，gal 为 None 时返回 "图集_?"。
def _gallery_ref(gal) -> str:
    return "图集_%s" % (gal if gal is not None else "?")


# 生效条件：无必需形参，按 os.environ.get(VISION_ROOT_ENV) or os.environ.get(LEGACY_VISION_ROOT_ENV) or DEFAULT_VISION_ROOT 取值——某环境变量为空串时视为假值继续回落下一项。
def vision_root() -> str:
    """视觉证据归档根：env 覆盖 > 遗留 env > 本仓 data/vision 的父目录。"""
    return (os.environ.get(VISION_ROOT_ENV)
            or os.environ.get(LEGACY_VISION_ROOT_ENV)
            or DEFAULT_VISION_ROOT)


#: 遗留别名（拆分前命名）；新代码请用 vision_root()。
aeis_root = vision_root


# ---- 证据源（只读归档） ---------------------------------------------------

# 生效条件：root 下 data/vision/*/*.json 逐文件读；文件 OSError/ValueError、JSON 顶层非 dict、parts 非非空 list、或过滤后（type 与 cond_hash 皆真值的 dict）无记录时跳过该文件，否则收入含 path/gallery/image_id/algo/identity_cond_hash/by_type/by_cond 的 src 并最终返回 out 列表。
def load_sources(root: str) -> list:
    """扫描 `AEIS/data/vision/*/*.json`，取逐部件结构化结果（主证据源）。"""
    base = os.path.join(root, "data", "vision")
    out = []
    for p in sorted(glob.glob(os.path.join(base, "*", "*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        parts = d.get("parts")
        if not isinstance(parts, list) or not parts:
            continue
        recs = [x for x in parts
                if isinstance(x, dict) and x.get("type") and x.get("cond_hash")]
        if not recs:
            continue
        ident = d.get("identity") if isinstance(d.get("identity"), dict) else {}
        src = {
            "path": p, "gallery": _gallery_no(p),
            "image_id": "" if d.get("image_id") is None else str(d.get("image_id")),
            "algo": d.get("algo"),
            "identity_cond_hash": ident.get("cond_hash"),
            "by_type": {}, "by_cond": {},
        }
        for r in recs:
            src["by_type"].setdefault(str(r["type"]), r)
            src["by_cond"].setdefault(str(r["cond_hash"]), []).append(r)
        out.append(src)
    return out


# ---- 节点正文解析 ---------------------------------------------------------

# 生效条件：content 为 None 或空串时按 "" 处理；逐行 strip 后跳过空行与以 # 开头的行，返回首个含 ROOT_MARK 或匹配 _RE_PART 的行，全部无命中返回 ""。
def _find_body_line(content: str) -> str:
    for ln in (content or "").split("\n"):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if ROOT_MARK in s or _RE_PART.match(s):
            return s
    return ""


# 生效条件：rest 为 None/假值时按 "" 处理，分别用 _RE_COND/_RE_VERDICT/_RE_REASON/_RE_FG 捕获；fg 命中则转 float、ValueError 时置 None；reason 命中并 strip 后为空则置 None；返回含 cond_hash/verdict/reason/fg_ratio 四键的 dict（未命中键值为 None）。
def _fields(rest: str) -> dict:
    m = _RE_COND.search(rest or "")
    v = _RE_VERDICT.search(rest or "")
    r = _RE_REASON.search(rest or "")
    f = _RE_FG.search(rest or "")
    fg = f.group(1) if f else None
    try:
        fg = float(fg) if fg is not None else None
    except ValueError:
        fg = None
    reason = r.group(1).strip() if r else None
    return {"cond_hash": m.group(1) if m else None,
            "verdict": v.group(1) if v else None,
            "reason": reason or None,
            "fg_ratio": fg}


# 生效条件：content 无正文行（空串、全为注释/空行、或无 ROOT_MARK 且不匹配 _RE_PART）返回 None；首行含 ROOT_MARK 返回 kind="root" 记录（n_parts 由 _RE_NPARTS 转 int、未命中为 None，cond_hash 取自 _fields）；否则须匹配 _RE_PART，不匹配返回 None，匹配后 bbox 按逗号切分对非空项做 int(float(x))（ValueError 则 bbox=None）并返回 kind="part" 记录。
def parse_node(content: str):
    """视觉节点正文 → 结构化记录；非视觉节点 → None。"""
    line = _find_body_line(content)
    if not line:
        return None
    if ROOT_MARK in line:
        d = _fields(line)
        n = _RE_NPARTS.search(line)
        return {"kind": "root", "type": None, "bbox": None,
                "n_parts": int(n.group(1)) if n else None,
                "cond_hash": d["cond_hash"], "verdict": None,
                "reason": None, "fg_ratio": None}
    m = _RE_PART.match(line)
    if not m:
        return None
    try:
        bbox = [int(float(x)) for x in m.group("bbox").split(",") if x.strip()]
    except ValueError:
        bbox = None
    d = _fields(m.group("rest"))
    d.update({"kind": "part", "type": m.group("type").strip(), "bbox": bbox})
    return d


# ---- 节点集合 -------------------------------------------------------------

# 生效条件：layer 透传给 cg._candidates，nid 取 e["id"] 或 path 去 .md 后须以 prefixes 中任一开头且 cg._read 返回非 None 的 fm 才被计数；加密内容记录 locked=True/parsed=None 且不触发 limit 检查，非加密内容 parse_node 后若 limit 非 None 且节点数已达 limit 即 break（因此最多多计该条）。
def _vision_nodes(cg, layer=None, prefixes=VISION_PREFIXES, limit=None) -> list:
    """收集视觉节点（只读 index）。

    `layer=None` → 全层扫描（按前缀识别）；不静默漏节点——G4 阶段被 fail-closed
    跳过、仍留在原层的密文视觉节点也必须被计入 `skipped_locked` 而非被忽略。
    """
    nodes = []
    for e in cg._candidates(layer=layer) or []:
        nid = e.get("id") or os.path.basename(e.get("path") or "")[:-3]
        if not any(nid.startswith(p) for p in prefixes):
            continue
        fm, content = cg._read(e)
        if fm is None:
            continue
        if crypto.is_encrypted(content):
            nodes.append({"id": nid, "path": e["path"], "layer": e.get("layer"),
                          "tags": list(fm.get("tags") or []), "fm": fm,
                          "locked": True, "parsed": None})
            continue
        nodes.append({"id": nid, "path": e["path"], "layer": e.get("layer"),
                      "tags": list(fm.get("tags") or []), "fm": fm,
                      "locked": False, "parsed": parse_node(content)})
        if limit is not None and len(nodes) >= limit:
            break
    return nodes


# 生效条件：nodes 中 parsed 为 dict、kind=="root" 且 cond_hash 为真值的节点，以其 tags[-1]（无 tags 时为空串）为标签 setdefault 记录首个 cond_hash，返回标签→cond_hash 的 out。
def _family_root_cond(nodes) -> dict:
    """家族标签(image_id) → 根节点 cond_hash。"""
    out = {}
    for n in nodes:
        p = n.get("parsed")
        if p and p.get("kind") == "root" and p.get("cond_hash"):
            label = n["tags"][-1] if n["tags"] else ""
            out.setdefault(label, p["cond_hash"])
    return out


# 生效条件：n["id"] 以 "vpipe_" 开头时先以 roots.get(tags[-1] 或 "") 取 cond——cond 为假返回 (None,"no_family_root")，cond 为真则在 sources 中匹配 identity_cond_hash 成功返回 (s,"identity_cond_hash")、未命中再按该标签匹配 image_id 成功返回 (s,"image_id")、仍失败返回 (None,"no_source_archive")；非 vpipe_ 时取 tags 中首个匹配 _RE_IMG_TAG 的 img<N>（未取到则不匹配）按 image_id 命中返回 (s,"image_tag")，否则返回 (None,"no_source_archive")。
def _pick_source(n, sources, roots) -> tuple:
    """→ (source, joined_by)；无法定位图集 → (None, 原因)。"""
    nid = n["id"]
    tags = n["tags"]
    if nid.startswith("vpipe_"):
        cond = roots.get(tags[-1] if tags else "")
        if cond:
            for s in sources:
                if s.get("identity_cond_hash") == cond:
                    return s, "identity_cond_hash"
        else:
            return None, "no_family_root"
        label = tags[-1] if tags else ""
        for s in sources:
            if label and s.get("image_id") == label:
                return s, "image_id"
        return None, "no_source_archive"
    # imgpart：标签 `img<N>` ↔ 归档 image_id == N
    img = None
    for t in tags:
        m = _RE_IMG_TAG.match(str(t))
        if m:
            img = m.group(1)
            break
    if img is not None:
        for s in sources:
            if s.get("image_id") == img:
                return s, "image_tag"
    return None, "no_source_archive"


# ---- 三档映射 -------------------------------------------------------------

# 生效条件：parsed.cond_hash 为真值时按 str(cond_hash) 从 src["by_cond"] 取候选——其中 type 与 parsed["type"] 相同者直接返回 (r,"cond_hash")，否则候选仅 1 条返回 (cands[0],"cond_hash")、多于 1 条返回 (None,None)；候选为空或 cond_hash 为假时若 parsed.type 为真则按 src["by_type"].get(type) 命中返回 (r,"type")，否则返回 (None,None)。
def _match_record(src, parsed, joined_by):
    """在归档里定位对应部件记录（imgpart 优先 cond_hash 精确，vpipe 按 type）。"""
    if parsed.get("cond_hash"):
        cands = list(src["by_cond"].get(str(parsed["cond_hash"])) or [])
        if cands:
            for r in cands:
                if parsed.get("type") and str(r.get("type")) == parsed["type"]:
                    return r, "cond_hash"
            return (cands[0], "cond_hash") if len(cands) == 1 else (None, None)
    if parsed.get("type"):
        r = src["by_type"].get(parsed["type"])
        if r:
            return r, "type"
    return None, None


# 生效条件：n["locked"] 为真→BLINDSPOT(reason="locked")；否则 parsed 缺失→"unparsed"、kind 非 "part"→"root_no_verdict"；否则 _pick_source(n,sources,roots) 无源→以 why 为 reason；否则 _match_record 无记录→"no_matching_part"；否则 parsed 与 rec 的 verdict 均为真且不等→"verdict_mismatch"；否则 TIER2_FIELDS 中任一字段为 None→"missing_field:…"；全部通过才返回 STATUS_WHITEBOX 与 ev（未用到的形参 aeis_root_used 不参与判定）。
def build_evidence(n, sources, roots, aeis_root_used):
    """单节点 → (status, evidence, meta)；严格三档，缺源即 BLINDSPOT。"""
    parsed = n.get("parsed")
    if n.get("locked"):
        return STATUS_BLINDSPOT, None, {"reason": "locked",
                                        "source": None, "joined_by": None}
    if not parsed or parsed.get("kind") != "part":
        return STATUS_BLINDSPOT, None, {"reason": "root_no_verdict"
                                        if parsed else "unparsed",
                                        "source": None, "joined_by": None}
    src, why = _pick_source(n, sources, roots)
    if src is None:
        return STATUS_BLINDSPOT, None, {"reason": why, "source": None,
                                        "joined_by": None}
    rec, joined_by = _match_record(src, parsed, why)
    if rec is None:
        return STATUS_BLINDSPOT, None, {"reason": "no_matching_part",
                                        "source": src, "joined_by": why}
    # 白箱优先、条件一致校验：verdict 不一致即不落半可信证据
    if parsed.get("verdict") and rec.get("verdict") \
            and parsed["verdict"] != rec["verdict"]:
        return STATUS_BLINDSPOT, None, {"reason": "verdict_mismatch",
                                        "source": src, "joined_by": joined_by}
    ev = {
        "algo": rec.get("algo") or src.get("algo"),
        "confidence": rec.get("confidence"),
        "cond_hash": parsed.get("cond_hash") or rec.get("cond_hash"),
        "fg_ratio": parsed.get("fg_ratio")
        if parsed.get("fg_ratio") is not None else rec.get("fg_ratio"),
        "occluded": rec.get("occluded"),
        "verdict_reason": parsed.get("reason") or rec.get("verdict_reason"),
    }
    gaps = [k for k in TIER2_FIELDS if ev.get(k) is None]
    if gaps:
        return STATUS_BLINDSPOT, None, {"reason": "missing_field:" + ",".join(gaps),
                                        "source": src, "joined_by": joined_by}
    return STATUS_WHITEBOX, ev, {"reason": None, "source": src,
                                 "joined_by": joined_by}


# ---- 预演 / 执行 / 回滚 / 留痕 --------------------------------------------

# 生效条件：x 经 _as_cg 转换；prefixes 为假值回落 VISION_PREFIXES、aeis_root_ 为假值回落 aeis_root()；ids 为真值时才按 set(ids) 过滤 nodes；对 nodes 调 build_evidence，locked 节点只累加 skipped_locked，白箱项入 items、其余入 blindspot_items，全程不写盘并返回含 aeis_root/sources/nodes_scanned/targeted/blindspot/by_reason 的报表。
def plan(x, layer=None, prefixes=None, limit=None,
         aeis_root_=None, ids=None) -> dict:
    """预演：产出证据回填清单，不写盘。"""
    cg = _as_cg(x)
    prefixes = tuple(prefixes) if prefixes else VISION_PREFIXES
    root_used = aeis_root_ or aeis_root()
    sources = load_sources(root_used)
    nodes = _vision_nodes(cg, layer=layer, prefixes=prefixes, limit=limit)
    if ids:
        want = set(ids)
        nodes = [n for n in nodes if n["id"] in want]
    roots = _family_root_cond(_vision_nodes(cg, layer=layer,
                                            prefixes=prefixes))
    items, blind, locked = [], [], 0
    for n in nodes:
        status, ev, meta = build_evidence(n, sources, roots, root_used)
        if n.get("locked"):
            locked += 1
            continue
        row = {"id": n["id"], "layer": n.get("layer"), "status": status,
               "type": (n.get("parsed") or {}).get("type"),
               "reason": meta.get("reason"),
               "joined_by": meta.get("joined_by"),
               "source": _gallery_ref(meta["source"]["gallery"])
               if meta.get("source") else None,
               "already": n["fm"].get("evidence_status")}
        if status == STATUS_WHITEBOX:
            row["evidence"] = ev
            items.append(row)
        else:
            blind.append(row)
    by_reason = {}
    for r in blind:
        k = r.get("reason") or "?"
        by_reason[k] = by_reason.get(k, 0) + 1
    return {
        "root": cg.root, "dry_run": True, "action": "vision_evidence",
        "aeis_root": root_used, "authority_doc": AUTHORITY_DOC,
        "sources": [{"gallery": _gallery_ref(s["gallery"]),
                     "image_id": s["image_id"],
                     "parts": len(s["by_type"])} for s in sources],
        "nodes_scanned": len(nodes), "skipped_locked": locked,
        "targeted": len(items), "blindspot": len(blind),
        "blindspot_by_reason": by_reason,
        "items": items, "blindspot_items": blind,
    }


# 生效条件：x 经 _as_cg，batch 为假值回落 BATCH_DEFAULT 并交给 _unique_batch(cg, …) 去重；ids 为真值才按 id 过滤、entry_ids 为真值才按 _entry_id(batch,id) 过滤；循环中节点不在 cg.index["nodes"] 记 skipped_drift，fm 为 None 或内容加密记 skipped_locked，fm 已有同 status（白箱还要求 evidence 相同）记 skipped_already，否则改写 fm 并落盘、追加 jsonl、收集 entry_id；written 非 0 时 cg.rebuild_index() 并尝试 evolution.record（异常被吞）后返回 rep。
def apply(x, ids=None, entry_ids=None, layer=None, prefixes=None,
          limit=None, batch=None, aeis_root_=None, actor=None) -> dict:
    """执行回填：逐节点改写 frontmatter 证据面，写 `_vision_evidence.jsonl`。"""
    cg = _as_cg(x)
    p = plan(cg, layer=layer, prefixes=prefixes, limit=limit,
             aeis_root_=aeis_root_)
    batch = _unique_batch(cg, batch or BATCH_DEFAULT)
    want_ids = set(ids) if ids else None
    want_eids = set(entry_ids) if entry_ids else None
    rows = list(p["items"]) + list(p["blindspot_items"])
    if want_ids is not None:
        rows = [r for r in rows if r["id"] in want_ids]
    if want_eids is not None:
        rows = [r for r in rows
                if _entry_id(batch, r["id"]) in want_eids]
    rep = {"root": cg.root, "dry_run": False, "action": "vision_evidence",
           "batch": batch, "actor": actor, "aeis_root": p["aeis_root"],
           "authority_doc": AUTHORITY_DOC,
           "planned": len(rows), "written": 0, "blindspot_written": 0,
           "skipped_locked": p["skipped_locked"],
           "skipped_already": 0, "skipped_drift": 0, "entry_ids": []}
    for r in rows:
        nid = r["id"]
        e = cg.index["nodes"].get(nid)
        if not e:
            rep["skipped_drift"] += 1
            continue
        fm, content = cg._read(e)
        if fm is None or crypto.is_encrypted(content):
            rep["skipped_locked"] += 1
            continue
        status = r["status"]
        ev = r.get("evidence")
        if fm.get("evidence_status") == status and \
                (status == STATUS_BLINDSPOT or fm.get("evidence") == ev):
            rep["skipped_already"] += 1
            continue
        fm.pop("evidence", None)
        if status == STATUS_WHITEBOX:
            fm["evidence"] = ev
            fm["evidence_status"] = STATUS_WHITEBOX
            fm["evidence_tier"] = 2
            fm["evidence_joined_by"] = r.get("joined_by")
            fm["evidence_source"] = ("aeis:vision:%s" % r["source"]
                                     if r.get("source") else None)
            rep["written"] += 1
        else:
            fm["evidence_status"] = STATUS_BLINDSPOT
            fm["evidence_blindspot_reason"] = r.get("reason")
            rep["blindspot_written"] += 1
            rep["written"] += 1
        fm["evidence_doc"] = AUTHORITY_DOC
        fm["evidence_batch"] = batch
        fm["evidence_at"] = time.time()
        cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                       durable=True)
        append_jsonl(_log_path(cg), {
            "action": "vision_evidence", "ts": time.time(), "batch": batch,
            "actor": actor, "entry_id": _entry_id(batch, nid), "node": nid,
            "layer": e.get("layer"), "status": status, "tier": 2
            if status == STATUS_WHITEBOX else 3,
            "evidence": ev, "reason": r.get("reason"),
            "source": r.get("source"), "joined_by": r.get("joined_by")})
        rep["entry_ids"].append(_entry_id(batch, nid))
    if rep["written"]:
        cg.rebuild_index()
        try:
            evolution.record(
                cg, kind=evolution.KIND_GENERAL,
                pattern=("视觉证据面缺口的闭合方式：以只读归档逐部件结构化结果"
                         "（cond_hash 连接）反填节点证据，脱敏为图集编号引用"),
                action="vision_evidence",
                evidence=("batch=%s written=%d whitebox=%d blindspot=%d"
                          % (batch, rep["written"], len(p["items"]),
                             rep["blindspot_written"])),
                source="data/vision（只读，本仓）",
                extra={"batch": batch, "authority_doc": AUTHORITY_DOC})
        except Exception:                                   # noqa: BLE001
            pass                                            # 留痕失败不拖垮批次
    rep["blindspot"] = len(p["blindspot_items"])
    return rep


# 生效条件：x 经 _as_cg 后读 _log_path(cg) 日志，只处理 action=="vision_evidence" 记录；batch 为真值时仅取 batch 相同记录、entry_ids 为真值时仅取 entry_id 在集合内记录、该 entry_id 已出现在 rollback 日志则记 skipped_done；节点缺失或 _read 返回 fm 为 None 记 missing，EVIDENCE_KEYS 一个都不在 fm 中记 skipped_done，否则删除命中键、写盘并追加 rollback 留痕，reverted 非 0 时重建索引后返回 rep。
def rollback(x, batch=None, entry_ids=None, actor=None) -> dict:
    """按留痕反向应用：删除本批次写入的证据键（幂等，防覆盖）。"""
    cg = _as_cg(x)
    want = set(entry_ids) if entry_ids else None
    rep = {"root": cg.root, "action": "vision_evidence_rollback",
           "actor": actor, "batch": batch, "reverted": 0, "missing": 0,
           "skipped_done": 0, "cleared_keys": 0}
    log = list(read_jsonl(_log_path(cg)) or [])
    done = {r.get("entry_id") for r in log
            if r.get("action") == "vision_evidence_rollback"
            and r.get("entry_id")}
    for rec in log:
        if rec.get("action") != "vision_evidence":
            continue
        if batch and rec.get("batch") != batch:
            continue
        eid = rec.get("entry_id")
        if want is not None and eid not in want:
            continue
        if eid in done:
            rep["skipped_done"] += 1
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
        cleared = 0
        for k in EVIDENCE_KEYS:
            if k in fm:
                fm.pop(k, None)
                cleared += 1
        if not cleared:
            rep["skipped_done"] += 1
            continue
        cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                       durable=True)
        append_jsonl(_log_path(cg), {
            "action": "vision_evidence_rollback", "ts": time.time(),
            "actor": actor, "batch": rec.get("batch"), "entry_id": eid,
            "node": nid, "cleared_keys": cleared})
        rep["reverted"] += 1
        rep["cleared_keys"] += cleared
    if rep["reverted"]:
        cg.rebuild_index()
    return rep


# 生效条件：x 经 _as_cg 后逐条读 _log_path(cg)，batch 为真值时才按 rec.get("batch")==batch 过滤；limit 非 None 且 >=0 时执行 recs = recs[-limit:]（limit=0 因 -0 切片退化为全量），limit 为 None 或负数时不截断，返回 {root,total,returned,records}。
def history(x, limit=100, batch=None) -> dict:
    cg = _as_cg(x)
    recs = []
    for rec in read_jsonl(_log_path(cg)) or []:
        if batch and rec.get("batch") != batch:
            continue
        recs.append(rec)
    total = len(recs)
    if limit is not None and limit >= 0:
        recs = recs[-limit:]
    return {"root": cg.root, "total": total, "returned": len(recs),
            "records": recs}


# ---- CLI（真实库预演/执行用；MCP 侧走 maintain action） -------------------

# 生效条件：argv 为 None 时 argparse 取 sys.argv；--prefixes 默认由 ",".join(VISION_PREFIXES) 提供并切出非空前缀；a.rollback 为真调 rollback（entry_ids 切分后为空则传 None）、否则 a.apply 为真调 apply、否则调 plan；--json 为真打印整份 JSON，否则按固定关键字打印并恒返回 0。
def _main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="G5 视觉证据回填（默认只预演）")
    ap.add_argument("root", help="认知图库根")
    ap.add_argument("--aeis-root", default=None, help="AEIS 仓库根（只读证据源）")
    ap.add_argument("--layer", default=None, help="限定层；缺省全层（按前缀）")
    ap.add_argument("--prefixes", default=",".join(VISION_PREFIXES))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch", default=None)
    ap.add_argument("--actor", default="maintain")
    ap.add_argument("--apply", action="store_true", help="真正写盘（默认预演）")
    ap.add_argument("--rollback", action="store_true", help="按批次/定向回滚")
    ap.add_argument("--entry-ids", default=None)
    ap.add_argument("--json", action="store_true", help="输出完整 JSON 报表")
    a = ap.parse_args(argv)
    prefixes = [p for p in (a.prefixes or "").split(",") if p]
    if a.rollback:
        out = rollback(a.root, batch=a.batch,
                       entry_ids=[x for x in (a.entry_ids or "").split(",") if x]
                       or None, actor=a.actor)
    elif a.apply:
        out = apply(a.root, layer=a.layer, prefixes=prefixes, limit=a.limit,
                    batch=a.batch, aeis_root_=a.aeis_root, actor=a.actor)
    else:
        out = plan(a.root, layer=a.layer, prefixes=prefixes, limit=a.limit,
                   aeis_root_=a.aeis_root)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for k in ("root", "aeis_root", "nodes_scanned", "targeted", "blindspot",
                  "blindspot_by_reason", "written", "blindspot_written",
                  "skipped_locked", "skipped_already", "batch", "reverted"):
            if k in out:
                print("%-22s %s" % (k, out[k]))
        for s in out.get("sources") or []:
            print("  source %s image_id=%s parts=%s"
                  % (s["gallery"], s["image_id"], s["parts"]))
        if out.get("items"):
            print("targeted sample:",
                  [(i["id"], i["joined_by"], (i["evidence"] or {}).get("algo"))
                   for i in out["items"][:3]])
    return 0


if __name__ == "__main__":                                  # pragma: no cover
    raise SystemExit(_main())