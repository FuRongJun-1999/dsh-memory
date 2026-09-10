# -*- coding: utf-8 -*-
"""md_cg · 统一 ref 协议 + 索引水位（增量）+ 漂移/悬空巡检

对照 `docs/认知图_索引与工程规范化_计划_v0.1.md` 的 R3（修 D + 修 F）：

**D 漂移 / 悬空检测（本模块 `check_refs`）**
  扫描带 `code_ref` / `doc_ref` 的节点，回两类问题：
    · `stale`    —— 源文件被改（区间哈希不再匹配）
    · `dangling` —— 源文件被删（索引指向不存在的文件）
  巡检**只读**、**不抛**、**不改源文件**；修复动作是「重跑 index_code / index_doc」，
  因为索引是派生物（对齐 sustain.heal 的既有边界）。

**F 全量重扫 + 静默截断（本模块 `Ledger` + `index_dir`）**
  `<root>/_refindex.json` 是 ref 索引水位（抄 `sources.Ingestor` 的 `_sources.json` 范式），
  以**源文件绝对路径**为键，记每个源文件的 (size, mtime) 与节点区间 + 它所属的**源大域
  root**；`incremental=True` 时未变文件**不再读盘重切**，直接跳过（`skipped_unchanged`）
  ——这就是「不全量重扫」。
  键用绝对路径、且逐文件记 root，是因为一份认知图可以索引多个大域：只按 rel 记会在同名
  文件上互相覆盖，巡检时若拿认知图根去拼路径则会把一切都误判成 dangling。
  截断（`max_files` / `max_items`）由 codeindex / docindex 显式上报，本模块把
  「最近一次索引被截断」写进水位，交给 `sustain.diagnose` 巡检看见（不再静默）。

**为什么回读要收进本模块**
  `op=ref` 的回读与 `check_refs` 的判定**必须共用同一实现**，否则会出现
  「回读说没漂、巡检说有漂」。与 `region_hash` 的教训同源：区间哈希只允许一份实现，
  这里连「怎么判定 ok / stale / dangling」也只允许一份。

零第三方依赖。
"""
from __future__ import annotations

import json
import os
import time

from .fsutil import atomic_write

SCHEMA = 2                # v2：水位以「源文件绝对路径」为键（v1 按 rel 会跨大域撞名）
LEDGER_FILE = "_refindex.json"
REF_KEYS = ("code_ref", "doc_ref")
MAX_CHECK = 2000          # 巡检节点上限（超出报 truncated，不静默截断）
STATUSES = ("ok", "stale", "dangling", "unresolved", "error")


def _src_key(fp: str) -> str:
    """水位的键 = 源文件绝对路径。

    不能用 rel：一份认知图可以索引多个大域（不同 root），只按 rel 记会在
    `alpha.py` 这种同名文件上互相覆盖——水位被静默丢掉，巡检就漏报。
    """
    return os.path.abspath(fp or "")


def _now() -> float:
    """时间戳压到 1 位小数：让 `_refindex.json` 字节数稳定（重跑不涨），
    同时保留足够的「多久以前」信息（float 的最短 repr 保证小数位固定为 1）。"""
    return round(time.time(), 1)


# --------------------------------------------------------------------------
# 提取器注册表（统一调度：调用方只说 kind，不说「用哪个模块」）
# --------------------------------------------------------------------------

def _mod(kind: str):
    from . import codeindex, docindex
    if kind == "code_ref":
        return codeindex
    if kind == "doc_ref":
        return docindex
    raise ValueError(f"未知 ref kind：{kind!r}（支持 {REF_KEYS}）")


def registry() -> dict:
    """后缀 → kind 的注册表（code / doc 各一份提取器）。"""
    from . import codeindex, docindex
    return {
        "code_ref": {"suffixes": tuple(codeindex.SUFFIX)},
        "doc_ref": {"suffixes": tuple(docindex.SUFFIX)},
    }


def kind_of_path(path: str) -> str:
    """按后缀判 kind；无提取器返回 ''（由调用方决定是报错还是跳过）。"""
    from . import codeindex, docindex
    ext = os.path.splitext(path or "")[1].lower()
    if not ext:
        return ""
    if ext in codeindex.EXTRACTORS:
        return "code_ref"
    if ext in docindex.SUFFIX:
        return "doc_ref"
    return ""


def extract(source: str, path: str = "", kind: str = ""):
    """统一提取入口：按 kind（或从 path 推断）分发到对应 extractor。"""
    k = kind or kind_of_path(path)
    if not k:
        ext = os.path.splitext(path or "")[1] or "<none>"
        raise ValueError(f"无索引提取器（suffix={ext}）")
    return _mod(k).extract(source, path)


def node_id_of(item: dict, kind: str) -> str:
    return _mod(kind).node_id(item)


def render_of(item: dict, kind: str) -> str:
    return _mod(kind).render(item)


def ref_fields(node) -> dict:
    """节点 → 检索结果要带的两字段（读侧只加字段，不改召回逻辑）。"""
    kind, ref = ref_of(node)
    return {"ref": ref, "ref_kind": kind} if ref else {"ref": None, "ref_kind": ""}


def ref_of(node) -> tuple:
    """从节点 frontmatter 取 ref：返回 (kind, ref) 或 ('', None)。"""
    fm = (node or {}).get("frontmatter") or {}
    for k in REF_KEYS:
        r = fm.get(k)
        if isinstance(r, dict) and r:
            return k, r
    return "", None


# --------------------------------------------------------------------------
# 索引水位（_refindex.json）：增量 + 截断留痕
# --------------------------------------------------------------------------

class Ledger:
    """`<root>/_refindex.json`：每个源文件的 (size, mtime) 水位 + 节点区间。"""

    def __init__(self, root: str):
        self.root = root
        self.path = os.path.join(root, LEDGER_FILE)
        self._d = None

    def load(self) -> dict:
        if self._d is not None:
            return self._d
        d = None
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, dict) and obj.get("schema") == SCHEMA \
                    and isinstance(obj.get("files"), dict):
                d = obj
        except (OSError, ValueError):
            d = None
        self._d = d or {"schema": SCHEMA, "updated_at": 0.0, "files": {}}
        return self._d

    def is_fresh(self, rel: str, fp: str) -> bool:
        """源文件自上次索引后未变（size + mtime 双等）→ 可跳过不重切。"""
        e = self.load()["files"].get(_src_key(fp))
        if not e:
            return False
        try:
            st = os.stat(fp)
        except OSError:
            return False
        if e.get("size") != st.st_size:
            return False
        return abs(float(e.get("mtime") or 0.0) - st.st_mtime) < 1e-6

    def record(self, rel: str, fp: str, kind: str, nodes,
               root: str = None) -> None:
        """记一个源文件的水位（节点区间用于判 stale）。

        `root` 是**源**大域的根（≠ 认知图根）：巡检要拿它拼 `root/rel` 才能
        找到源文件，缺了它就会把「源在别处」误判成 dangling。
        """
        key = _src_key(fp)
        try:
            st = os.stat(fp)
        except OSError:
            return
        self.load()["files"][key] = {
            "root": root if root else os.path.dirname(key),
            "path": rel,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "kind": kind,
            "nodes": [
                {"id": n.get("id"), "lineno": n.get("lineno"),
                 "end": n.get("end"), "hash": n.get("hash")}
                for n in nodes
            ],
        }

    def drop(self, fp: str) -> None:
        self.load()["files"].pop(_src_key(fp), None)

    def reconcile(self, root: str, kind: str, seen) -> int:
        """一次**完整**索引后对账：本 (root, kind) 下没被扫到的旧条目剪掉。

        否则「源文件被删 → 索引悬空 → heal 重建」之后条目还在，巡检就永远报
        dangling，heal 是治不好的。`seen` 是本次真正走过（提取成功或判定未变）
        的源文件键集合。**截断的索引不能对账**——没扫完不等于剩下的都消失了。
        """
        r = os.path.abspath(root)
        files = self.load()["files"]
        dead = [k for k, e in files.items()
                if os.path.abspath(e.get("root") or "") == r
                and e.get("kind") == kind and k not in seen]
        for k in dead:
            files.pop(k, None)
        return len(dead)

    def prune(self) -> int:
        """剪掉「源大域已不存在」的条目（整个目录被搬走/删除）。

        这类条目已不可能再被任何大域索引到，留着只会在巡检里报永不消失的
        dangling；而节点自带的 ref 仍会兜底探测，所以剪掉不会漏报真实悬空。
        """
        files = self.load()["files"]
        dead = [k for k, e in files.items()
                if not os.path.isdir(e.get("root") or os.path.dirname(k))]
        for k in dead:
            files.pop(k, None)
        return len(dead)

    def note_index(self, *, kind: str, root: str, files: int, indexed: int,
                   truncated: bool, reason: str = "") -> None:
        """记「最近一次索引」结果——截断在这里留痕，供 diagnose 看见。"""
        self.load()["last_index"] = {
            "ts": _now(), "kind": kind, "root": root, "files": files,
            "indexed": indexed, "truncated": bool(truncated),
            "truncated_reason": reason or "",
        }

    def save(self) -> None:
        d = self.load()
        d["updated_at"] = _now()
        atomic_write(self.path, json.dumps(d, ensure_ascii=False,
                                           indent=1, sort_keys=True))

    def summary(self) -> dict:
        d = self.load()
        files = d.get("files") or {}
        nodes = sum(len(e.get("nodes") or []) for e in files.values())
        up = float(d.get("updated_at") or 0.0)
        out = {
            "path": self.path,
            "schema": d.get("schema"),
            "files": len(files),
            "nodes": nodes,
            "updated_at": up,
            "age_s": None if not up else max(0.0, time.time() - up),
            "exists": os.path.isfile(self.path),
        }
        if isinstance(d.get("last_index"), dict):
            out["last_index"] = d["last_index"]
        return out


# --------------------------------------------------------------------------
# 统一 index_dir：调度 + 水位 + 落盘（供 op=index_code / op=index_doc / heal 共用）
# --------------------------------------------------------------------------

def index_dir(root: str, *, kind: str, patterns=None, max_files: int = 500,
              max_items: int = 2000, incremental: bool = False,
              ledger: "Ledger" = None):
    """按 kind 调度 codeindex / docindex 的全量（或增量）索引。

    incremental=True 且给了 ledger 时：未变文件跳过（`skipped_unchanged`）。
    返回 (items, errors, stats)，与底层 index_dir 的返回一致（多一个
    `skipped_unchanged`）。
    """
    mod = _mod(kind)
    fresh = None
    on_file = None
    seen = set()                       # 本次真正走过的源文件（用于对账）
    if ledger is not None:
        if incremental:
            def fresh(rel, fp):                         # noqa: E306
                ok = ledger.is_fresh(rel, fp)
                if ok:
                    seen.add(_src_key(fp))
                return ok

        def on_file(rel, fp, got):                      # noqa: E306
            seen.add(_src_key(fp))
            ledger.record(rel, fp, kind,
                          [{"id": node_id_of(it, kind), "lineno": it.get("lineno"),
                            "end": it.get("end"), "hash": it.get("hash")} for it in got],
                          root=root)

    items, errors, stats = mod.index_dir(
        root, patterns=patterns, max_files=max_files, max_items=max_items,
        fresh=fresh, on_file=on_file,
    )
    if ledger is not None:
        ledger.prune()
        if not stats.get("truncated"):
            # 没扫完就不能对账：截断时「没见到」不等于「源已消失」。
            ledger.reconcile(root, kind, seen)
        ledger.note_index(kind=kind, root=root, files=stats.get("files", 0),
                          indexed=len(items), truncated=bool(stats.get("truncated")),
                          reason=stats.get("truncated_reason") or "")
        ledger.save()
    return items, errors, stats


def _domain_of(it: dict) -> str:
    """条目 → 路由域键（供 `tags` 的 `domain:` 显式声明）。

    与 `observation_position` **分开**：position 是给人读的条件文本（「本地
    源码仓（大域=md_cg）」），domain 是给 `routing.route_key` 直取的短键。
    两者混成一个字段就会重演普查里的退化：实例名嵌进条件字段 → 3037 桶 /
    3048 节点（99.9% 单例桶），路由等于失效。

    取 path 首段，与改造前 `normalize_domain(observation_position)` 的产物
    **逐字相同**，故本次加标签不改变任何既有节点的分桶结果。
    """
    path = it.get("path") or ""
    return path.split("/")[0] or "orphan"


def add_items(cg, items, *, kind: str, root: str, layer=None, sensitivity=None,
              layer_of=None):
    """把索引条目写进认知图（code / doc 的落盘细节收在这里，唯一实现）。

    - `layer=None` → 默认 `knowledge`（与代码节点同层，保证进默认召回）。
    - `layer_of(nid)` 可逐节点覆盖 layer（heal 重建时保留原层）。
    - doc 节点：密级走 `docindex.sensitivity_for`（只可能更严）；返回密级分布。
    - `condition_space` 走 `codeindex/docindex.condition_space`，与正文的
      `# 生效条件：` 行**同源**——改造前此处只写 `observation_position` 单槽，
      而单槽不是生效条件，于是 frontmatter 的条件空间形同未声明。
    返回 (ids, sens_counts)。
    """
    from . import codeindex, docindex
    ids, sens = [], {}
    for it in items:
        if kind == "code_ref":
            nid = codeindex.node_id(it)
            cg.add(
                nid, codeindex.render(it),
                layer=(layer_of(nid) if layer_of else None) or layer or "knowledge",
                tags=["code", "code:" + it.get("kind", ""),
                      "domain:" + _domain_of(it)],
                condition_space=codeindex.condition_space(it),
                verification_basis=it.get("basis") or "compiler",
                code_ref=_code_ref(it, root),
            )
        elif kind == "doc_ref":
            nid = docindex.node_id(it)
            level = it.get("level")
            s, _basis = docindex.sensitivity_for(it.get("path") or "", sensitivity)
            sens[s] = sens.get(s, 0) + 1
            cg.add(
                nid, docindex.render(it),
                layer=(layer_of(nid) if layer_of else None) or layer or "knowledge",
                tags=["doc", "doc:md", f"level:{level}",
                      "domain:" + _domain_of(it)],
                condition_space=docindex.condition_space(it),
                verification_basis="data",
                sensitivity=s,
                doc_ref=_doc_ref(it, root),
            )
        else:
            raise ValueError(f"未知 ref kind：{kind!r}")
        ids.append(nid)
    return ids, sens


def _code_ref(it: dict, root: str) -> dict:
    return {
        "path": it.get("path"), "name": it.get("name"),
        "kind": it.get("kind"), "lineno": it.get("lineno"), "end": it.get("end"),
        "lang": it.get("lang"), "precise": bool(it.get("precise", True)),
        "hash": it.get("hash"), "root": root,
    }


def _doc_ref(it: dict, root: str) -> dict:
    return {
        "path": it.get("path"), "heading": it.get("heading"),
        "heading_path": it.get("heading_path"), "level": it.get("level"),
        "lineno": it.get("lineno"), "end": it.get("end"),
        "anchor": it.get("anchor"), "hash": it.get("hash"), "lang": it.get("lang"),
        "precise": bool(it.get("precise", True)), "root": root,
    }


# --------------------------------------------------------------------------
# 回读（唯一实现：op=ref 与 check_refs 共用）
# --------------------------------------------------------------------------

def probe_ref(ref: dict, *, root: str = None, with_text: bool = False) -> dict:
    """只读探测单个 ref 的状态（不回读整篇，除非 with_text）。"""
    from . import codeindex
    ref = ref or {}
    rel = ref.get("path") or ""
    r = root or ref.get("root") or ""
    base = {"ref": ref, "path": rel, "status": "unresolved", "ok": False}
    if not r:
        return {**base, "error": "ref 未记录 root，请显式传 root 参数"
                                "（索引里存的是相对 root 的 path）"}
    fp = os.path.join(r, rel)
    base["root"] = r
    if not os.path.isfile(fp):
        return {**base, "status": "dangling", "abspath": fp, "stale": True,
                "error": f"源文件不存在（索引已悬空）：{fp}"}
    try:
        with open(fp, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")
    except (OSError, UnicodeDecodeError) as exc:
        return {**base, "status": "error", "abspath": fp,
                "error": f"读取失败：{exc}"}
    total = len(lines)
    lineno = int(ref.get("lineno") or 1)
    end = int(ref.get("end") or lineno)
    got = codeindex.region_hash(lines, lineno, end)
    expect = ref.get("hash")
    match = (got == expect) if expect else None
    out = {
        **base, "abspath": fp, "total_lines": total,
        "hash": got, "hash_expected": expect, "hash_match": match,
        "stale": bool(expect) and not match,
        "ok": expect is None or bool(match),
        "status": "ok" if (expect is None or match) else "stale",
    }
    if with_text:
        lo = max(0, lineno - 1)
        out["text"] = "\n".join(lines[lo:max(lo, end)])
    return out


def read_ref(ref: dict, *, root: str = None, ref_kind: str = "ref") -> dict:
    """按 ref 回读源区间——`op=ref` 与 `check_refs` 的唯一实现。"""
    p = probe_ref(ref, root=root, with_text=True)
    base = {"ref": ref, "ref_kind": ref_kind}
    if p["status"] in ("unresolved", "error", "dangling"):
        out = {**base, "ok": False, "error": p["error"]}
        if p["status"] == "dangling":
            out["stale"] = True
        return out
    return {
        **base, "ok": True, "text": p["text"], "total_lines": p["total_lines"],
        "hash": p["hash"], "hash_expected": p["hash_expected"],
        "hash_match": p["hash_match"], "stale": p["stale"],
        "precise": bool((ref or {}).get("precise", True)),
        "note": "按 ref 区间回读；hash_match=False 说明源已改动，"
                "重跑 index_code / index_doc 重建",
    }


def check_refs(cg, *, ledger: "Ledger" = None, max_nodes: int = MAX_CHECK,
               only_tagged: bool = True) -> dict:
    """漂移 / 悬空巡检（只读、不抛）。

    优先走 ledger 的 (size, mtime) 快路径：未变文件**不读盘**直接判 ok；
    变了的文件读一次、按记录区间重算哈希判 stale。
    ledger 覆盖不到的节点（早期索引 / 未开增量）再回退逐节点探测。

    `only_tagged=True`（默认）只探测带 `code` / `doc` 标签的节点——ref 只由
    `index_code` / `index_doc` 产生，两者都会打这两个标签；这样巡检不必为每条
    记忆节点都读一次盘。需要穷举（含手写 ref）时传 False。
    """
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    stale, dangling, unresolved, errors = [], [], [], []
    covered = set()

    def _probe_one(nid, ref, kind, rel):
        p = probe_ref(ref)
        row = {"node_id": nid, "ref_kind": kind, "path": rel,
               "lineno": ref.get("lineno"), "end": ref.get("end"),
               "error": p.get("error", "")}
        if p["status"] == "dangling":
            dangling.append(row)
        elif p["status"] == "stale":
            row["hash_expected"] = p.get("hash_expected")
            row["hash"] = p.get("hash")
            stale.append(row)
        elif p["status"] == "unresolved":
            unresolved.append(row)
        elif p["status"] == "error":
            errors.append(row)

    # 快路径：ledger 记录的文件（键 = 源文件绝对路径，天然跨大域不撞名）
    if ledger is not None:
        for key, e in sorted((ledger.load().get("files") or {}).items()):
            rec_nodes = [n for n in (e.get("nodes") or [])
                         if n.get("id") in nodes]
            if not rec_nodes:
                continue
            covered.update(n.get("id") for n in rec_nodes)
            rel = e.get("path") or ""
            # 必须用**每个源文件自己的 root**（索引时的源大域），不能用 ledger.root：
            # 后者是认知图根，拿它拼路径会指向不存在的位置、把一切都误判成 dangling。
            src_root = e.get("root") or os.path.dirname(key)
            try:
                st = os.stat(key)
                unchanged = (e.get("size") == st.st_size
                             and abs(float(e.get("mtime") or 0.0) - st.st_mtime) < 1e-6)
            except OSError:
                unchanged = False
            if not unchanged:
                kind = e.get("kind") or kind_of_path(rel)
                for n in rec_nodes:
                    _probe_one(n.get("id"), {**n, "path": rel, "root": src_root},
                               kind, rel)

    # 回退：ledger 未覆盖的索引节点
    def _candidate(nid):
        if not only_tagged:
            return True
        tags = (nodes.get(nid) or {}).get("tags") or []
        return any(t in ("code", "doc") for t in tags)

    todo = [nid for nid in nodes if nid not in covered and _candidate(nid)]
    truncated = len(todo) > max_nodes
    checked = 0
    for nid in todo[:max_nodes]:
        try:
            node = cg.get(nid)
        except Exception:
            continue
        if not node:
            continue
        kind, ref = ref_of(node)
        if not ref:
            continue
        checked += 1
        try:
            _probe_one(nid, ref, kind, ref.get("path") or "")
        except Exception as exc:                      # 巡检不抛
            errors.append({"node_id": nid, "ref_kind": kind, "error": str(exc)})

    return {
        "ok": not (stale or dangling),
        "status": "ok" if not (stale or dangling) else ("dangling" if dangling else "stale"),
        "checked": checked + len(covered),
        "ledger_files": len((ledger.load().get("files") or {})) if ledger else 0,
        "stale": stale, "dangling": dangling,
        "unresolved": unresolved, "errors": errors,
        "truncated": truncated, "max_nodes": max_nodes,
    }


def rebuild(cg, *, ledger: "Ledger" = None, only_roots=None, max_files: int = 500,
            max_items: int = 2000) -> dict:
    """按 ref 记录的 root 重建索引（sustain.heal 的修复动作）。

    只重跑出了问题的 root（`only_roots`），逐节点**保留原 layer**；
    doc 密级用默认策略重算（默认只可能更严，不会放松）。
    """
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    groups = {}
    for nid in nodes:
        try:
            node = cg.get(nid)
        except Exception:
            continue
        kind, ref = ref_of(node)
        if not ref or not ref.get("root"):
            continue
        r = ref["root"]
        if only_roots is not None and r not in only_roots:
            continue
        groups.setdefault((r, kind), 0)
        groups[(r, kind)] += 1

    out = {"ok": True, "roots": sorted({r for r, _ in groups}),
           "groups": len(groups), "indexed": 0, "errors": [], "truncated": False}
    for (root, kind) in sorted(groups):
        try:
            items, errors, stats = index_dir(
                root, kind=kind, max_files=max_files, max_items=max_items,
                incremental=False, ledger=ledger)
            ids, _sens = add_items(
                cg, items, kind=kind, root=root,
                layer_of=lambda nid: (nodes.get(nid) or {}).get("layer"))
            out["indexed"] += len(ids)
            out["errors"].extend(errors)
            out["truncated"] = out["truncated"] or bool(stats.get("truncated"))
        except Exception as exc:                      # 自愈不抛
            out["ok"] = False
            out["errors"].append(f"{root} [{kind}]：{exc}")
    if ledger is not None:
        ledger.save()
    return out
