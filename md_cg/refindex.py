# -*- coding: utf-8 -*-
"""md_cg · 统一 ref 协议 + 索引水位（增量）+ 漂移/悬空巡检

对照 `docs/mdcg/认知图_索引与工程规范化_计划_v0.1.md` 的 R3（修 D + 修 F）：

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


# 生效条件：给定 fp 时返回 os.path.abspath(fp or '')（fp 为空/None 则返回当前目录的绝对路径），作为水位键以绝对路径保证不同 root 下同名文件不互相覆盖。
def _src_key(fp: str) -> str:
    """水位的键 = 源文件绝对路径。

    不能用 rel：一份认知图可以索引多个大域（不同 root），只按 rel 记会在
    `alpha.py` 这种同名文件上互相覆盖——水位被静默丢掉，巡检就漏报。
    """
    return os.path.abspath(fp or "")


# 生效条件：无 required 形参，任何调用都返回 round(time.time(), 1)，把时间戳压到 1 位小数以稳定 `_refindex.json` 字节数。
def _now() -> float:
    """时间戳压到 1 位小数：让 `_refindex.json` 字节数稳定（重跑不涨），
    同时保留足够的「多久以前」信息（float 的最短 repr 保证小数位固定为 1）。"""
    return round(time.time(), 1)


# --------------------------------------------------------------------------
# 提取器注册表（统一调度：调用方只说 kind，不说「用哪个模块」）
# --------------------------------------------------------------------------

# 生效条件：kind == 'code_ref' 返回 codeindex、kind == 'doc_ref' 返回 docindex，其他 kind 抛 ValueError（提示支持 REF_KEYS）。
def _mod(kind: str):
    from . import codeindex, docindex
    if kind == "code_ref":
        return codeindex
    if kind == "doc_ref":
        return docindex
    raise ValueError(f"未知 ref kind：{kind!r}（支持 {REF_KEYS}）")


# 生效条件：无 required 形参，调用即返回 {'code_ref': {'suffixes': tuple(codeindex.SUFFIX)}, 'doc_ref': {'suffixes': tuple(docindex.SUFFIX)}}。
def registry() -> dict:
    """后缀 → kind 的注册表（code / doc 各一份提取器）。"""
    from . import codeindex, docindex
    return {
        "code_ref": {"suffixes": tuple(codeindex.SUFFIX)},
        "doc_ref": {"suffixes": tuple(docindex.SUFFIX)},
    }


# 生效条件：path 的小写后缀在 codeindex.EXTRACTORS 中返回 'code_ref'，在 docindex.SUFFIX 中返回 'doc_ref'，无后缀或均不匹配返回 ''。
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


# 生效条件：source 为待提取文本，kind 非空或 path 后缀能推出 kind 时返回 _mod(k).extract(source, path)，推不出 kind 时抛 ValueError。
def extract(source: str, path: str = "", kind: str = ""):
    """统一提取入口：按 kind（或从 path 推断）分发到对应 extractor。"""
    k = kind or kind_of_path(path)
    if not k:
        ext = os.path.splitext(path or "")[1] or "<none>"
        raise ValueError(f"无索引提取器（suffix={ext}）")
    return _mod(k).extract(source, path)


# 生效条件：kind 为 'code_ref'/'doc_ref' 时返回 _mod(kind).node_id(item)，其他 kind 由 _mod 抛 ValueError。
def node_id_of(item: dict, kind: str) -> str:
    return _mod(kind).node_id(item)


# 生效条件：kind 为 'code_ref'/'doc_ref' 时返回 _mod(kind).render(item)，其他 kind 由 _mod 抛 ValueError。
def render_of(item: dict, kind: str) -> str:
    return _mod(kind).render(item)


# 生效条件：node 的 frontmatter 中 REF_KEYS 命中且值为非空 dict 时返回 {'ref': ref, 'ref_kind': kind}，否则返回 {'ref': None, 'ref_kind': ''}。
def ref_fields(node) -> dict:
    """节点 → 检索结果要带的两字段（读侧只加字段，不改召回逻辑）。"""
    kind, ref = ref_of(node)
    return {"ref": ref, "ref_kind": kind} if ref else {"ref": None, "ref_kind": ""}


# 生效条件：node 的 frontmatter 按 REF_KEYS 顺序取到第一个非空 dict 时返回 (k, r)，否则返回 ('', None)。
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

# 生效条件：以 root 为必填实参构造，实例化即置 self.root=root、self.path=os.path.join(root, LEDGER_FILE)、self._d=None；
class Ledger:
    """`<root>/_refindex.json`：每个源文件的 (size, mtime) 水位 + 节点区间。"""

# 生效条件：当传入 root 时，self.root 取该 root，self.path 为 os.path.join(root, LEDGER_FILE)，self._d 置为 None；
    def __init__(self, root: str):
        self.root = root
        self.path = os.path.join(root, LEDGER_FILE)
        self._d = None

# 生效条件：当 self._d is not None 时直接返回 self._d；否则读取 self.path 的 JSON，仅当 obj 是 dict 且 obj.get("schema") == SCHEMA 且 obj.get("files") 是 dict 时用 obj，否则（含 OSError/ValueError、结构不符）回落为 {"schema": SCHEMA, "updated_at": 0.0, "files": {}} 并缓存返回；
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

# 生效条件：传入 rel、fp 时，若 self.load()["files"].get(_src_key(fp)) 缺失或为假值、或 os.stat(fp) 抛 OSError、或条目 e.get("size") != st.st_size，则返回 False；否则返回 abs(float(e.get("mtime") or 0.0) - st.st_mtime) < 1e-6（mtime 缺失或假值时按 0.0）；
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

# 生效条件：当 rel、fp、kind、nodes 传入且 os.stat(fp) 成功时，向 self.load()["files"][_src_key(fp)] 写条目，其中 root 为 root if root else os.path.dirname(key)、path 为 rel、kind 为 kind、size/mtime 取 st、nodes 为每项 n.get("id")/n.get("lineno")/n.get("end")/n.get("hash")；os.stat(fp) 抛 OSError 时不写入；
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

# 生效条件：当传入 fp 时，self.load()["files"].pop(_src_key(fp), None)，即删除对应键（不存在也静默）；
    def drop(self, fp: str) -> None:
        self.load()["files"].pop(_src_key(fp), None)

# 生效条件：当传入 root、kind、seen 时，对 self.load()["files"] 中满足 os.path.abspath(e.get("root") or "") == os.path.abspath(root) 且 e.get("kind") == kind 且键 k 不在 seen 的条目删除，返回删除数量；
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

# 生效条件：对 load()["files"] 中「条目 root（为假值时用 os.path.dirname(键) 兜底）不是目录」的条目逐一 pop 并返回删除条数，无匹配时返回 0。
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

# 生效条件：当 kind、root、files、indexed、truncated 传入时，self.load()["last_index"] 被设为含 ts=_now()、kind、root、files、indexed、truncated=bool(truncated)、truncated_reason=reason or "" 的字典；reason 为假值（默认 ""/None）时 truncated_reason 回落 ""；
    def note_index(self, *, kind: str, root: str, files: int, indexed: int,
                   truncated: bool, reason: str = "") -> None:
        """记「最近一次索引」结果——截断在这里留痕，供 diagnose 看见。"""
        self.load()["last_index"] = {
            "ts": _now(), "kind": kind, "root": root, "files": files,
            "indexed": indexed, "truncated": bool(truncated),
            "truncated_reason": reason or "",
        }

# 生效条件：无参数调用即生效，取 self.load() 结果把 updated_at 置为 _now()，再以 atomic_write 把 json.dumps(..., ensure_ascii=False, indent=1, sort_keys=True) 写入 self.path，无返回值。
    def save(self) -> None:
        d = self.load()
        d["updated_at"] = _now()
        atomic_write(self.path, json.dumps(d, ensure_ascii=False,
                                           indent=1, sort_keys=True))

# 生效条件：无参数调用即生效，返回含 path、schema、load()["files"] 条目数、nodes 总数（各条目 nodes 列表长度之和）、updated_at、exists=os.path.isfile(self.path) 的 out；age_s 在 updated_at 为假值（0.0）时为 None，否则为 max(0.0, time.time()-up)；仅当 load() 的 last_index 为 dict 时才并入 out["last_index"]。
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

# 生效条件：root 为源大域根、kind 为 'code_ref'/'doc_ref' 时经 _mod(kind) 调度底层 index_dir 并返回 (items, errors, stats)；ledger 非空时逐文件 record，incremental 为真时跳过 ledger.is_fresh 为真的文件，且 stats 未截断时执行 reconcile。
def index_dir(root: str, *, kind: str, patterns=None, max_files: int = 500,
              max_items: int = 2000, incremental: bool = False,
              ledger: "Ledger" = None, skip_dirs=None):
    """按 kind 调度 codeindex / docindex 的全量（或增量）索引。

    incremental=True 且给了 ledger 时：未变文件跳过（`skipped_unchanged`）。
    返回 (items, errors, stats)，与底层 index_dir 的返回一致（多一个
    `skipped_unchanged`）。

    `skip_dirs` 透传给底层：**追加**排除、只增不减（内置 `.git`/`.venv`/
    `node_modules` 等不可被关闭），见 `codeindex.skip_matcher`。实际排掉了哪些目录
    由 `stats["skipped_dirs"]` 回报，仍不静默。
    """
    mod = _mod(kind)
    fresh = None
    on_file = None
    seen = set()                       # 本次真正走过的源文件（用于对账）
    if ledger is not None:
        if incremental:
# 生效条件：当 rel、fp 传入时，ok = ledger.is_fresh(rel, fp)；若 ok 为真则将 _src_key(fp) 加入 seen 并返回 ok，若 ok 为假则直接返回 False；
            def fresh(rel, fp):                         # noqa: E306
                ok = ledger.is_fresh(rel, fp)
                if ok:
                    seen.add(_src_key(fp))
                return ok

# 生效条件：当 rel、fp、got 传入时，将 _src_key(fp) 加入 seen，并以 root=root 调用 ledger.record(rel, fp, kind, [{"id": node_id_of(it, kind), "lineno": it.get("lineno"), "end": it.get("end"), "hash": it.get("hash")} for it in got])；
        def on_file(rel, fp, got):                      # noqa: E306
            seen.add(_src_key(fp))
            ledger.record(rel, fp, kind,
                          [{"id": node_id_of(it, kind), "lineno": it.get("lineno"),
                            "end": it.get("end"), "hash": it.get("hash")} for it in got],
                          root=root)

    items, errors, stats = mod.index_dir(
        root, patterns=patterns, max_files=max_files, max_items=max_items,
        fresh=fresh, on_file=on_file, skip_dirs=skip_dirs,
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


# 生效条件：it['path'] 非空时返回其首段 path.split('/')[0] 作为 domain 键，path 为空返回 'orphan'。
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


# 生效条件：kind == 'code_ref' 时按 codeindex.node_id/render 写入 cg（tags 含 'code'、code_ref=_code_ref(it, root)），kind == 'doc_ref' 时按 docindex 写入（tags 含 'doc'、doc_ref=_doc_ref(it, root)、密级取自 docindex.sensitivity_for(it['path'], sensitivity)），其他 kind 抛 ValueError，返回 (ids, sens)。
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


# 生效条件：把入参 root 原样写入返回 dict 的 'root'，path/name/kind/lineno/end/lang/hash 按 it.get 取值（缺省 None），precise 取 bool(it.get('precise', True))，render_version 取传入值（传入 None 时延迟 import codeindex 取 codeindex.RENDER_VERSION，保证与 render 契约**同源**、无第二处硬编码）。
def _code_ref(it: dict, root: str, render_version=None) -> dict:
    if render_version is None:            # 直接调用点的兜底：与 render 产物同源
        from . import codeindex
        render_version = codeindex.RENDER_VERSION
    return {
        "path": it.get("path"), "name": it.get("name"),
        "kind": it.get("kind"), "lineno": it.get("lineno"), "end": it.get("end"),
        "lang": it.get("lang"), "precise": bool(it.get("precise", True)),
        "hash": it.get("hash"), "root": root,
        "render_version": render_version,
    }


# 生效条件：把入参 root 原样写入返回 dict 的 'root'，path/heading/heading_path/level/lineno/end/anchor/hash/lang 按 it.get 取值（缺省 None），precise 取 bool(it.get('precise', True))。
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

# 生效条件：传入 ref 为假值（如 None/{}）时按 {} 处理，rel 取 ref.get("path") or ""；root 与 ref.get("root") 均为假值时返回含 ref/path/status:"unresolved"/ok:False/error:"ref 未记录 root..." 的 out；否则用 root or ref.get("root") 与 rel 拼 fp，os.path.isfile(fp) 为假时返回 status:"dangling"、stale:True，读取抛 OSError/UnicodeDecodeError 时返回 status:"error"；读取成功时 lineno 取 int(ref.get("lineno") or 1)（假值回落 1）、end 取 int(ref.get("end") or lineno)（假值回落 lineno），ref.get("hash") 为 None 时 match=None、ok=True、status:"ok"，ref.get("hash") 为真值且等于 region_hash 时 ok=True/status:"ok"、不等时 ok=False/status:"stale"，ref.get("hash") 为假值但非 None（如 ""/0/False）时 ok=False/status:"stale"；with_text 为真时 out["text"] 取 lines[max(0,lineno-1):max(max(0,lineno-1),end)] 的 join；
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


# 生效条件：ref 经 probe_ref(root=root, with_text=True) 后 status 为 'ok'/'stale' 时返回 ok=True 及 text/total_lines/hash/hash_match/stale/precise，status 为 'unresolved'/'error'/'dangling' 时返回 ok=False 与 error。
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


# 生效条件：cg 的 index['nodes'] 非空时汇总 stale/dangling/unresolved/errors 并返回 ok =（无 stale 且无 dangling）；only_tagged 为真时只探测 tags 含 'code'/'doc' 的节点，ledger 非空时先走 (size, mtime) 快路径。
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

# 生效条件：当 nid、ref、kind、rel 传入时，p = probe_ref(ref) 后按 p["status"] 分派：为 "dangling" 时把含 node_id/ref_kind/path/lineno/end/error 的 row 加入 dangling，为 "stale" 时补 hash_expected/hash 加入 stale，为 "unresolved" 时加入 unresolved，为 "error" 时加入 errors；其他状态不加入；
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
# 生效条件：当 nid 传入时，若 only_tagged 为假值立即返回 True；否则取 (nodes.get(nid) or {}).get("tags") or []，仅当其中存在 "code" 或 "doc" 返回 True，否则返回 False；
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


# --------------------------------------------------------------------------
# 节点级对账：孤儿清退 + 悬空清退
#
# 水位层的 `Ledger.reconcile` 只剪**水位条目**、`prune` 只剪「源大域已消失」
# 的条目，两者都不碰**节点**。于是节点层的两类残留无人处置：
#   · 孤儿（同一文档的过期代）——标题路径一变 id 全量重算，旧代与新代并存；
#   · 悬空（源文件已删）——回读必然失败，巡检永远报 dangling。
# 本节的唯一实现同时供 `op=index_code / index_doc`（孤儿）与
# `op=ref action=prune`（悬空）使用，避免两处各写一套口径。
# --------------------------------------------------------------------------

# 生效条件：返回 os.path.normcase(os.path.abspath(str(p or '')))，即 p 为 None/空串时返回当前目录的归一绝对路径。
def _norm_root(p) -> str:
    """root 归一：同一目录的大小写/分隔符差异不得影响「同一大域」判定。"""
    return os.path.normcase(os.path.abspath(str(p or "")))


# 生效条件：a 与 b 都非空且 _norm_root(a) == _norm_root(b) 时返回 True，否则（含 TypeError/ValueError）返回 False。
def _same_root(a, b) -> bool:
    try:
        return bool(a) and bool(b) and _norm_root(a) == _norm_root(b)
    except (TypeError, ValueError):
        return False


# 生效条件：返回 str(p or '').replace('\\', '/').lstrip('./')，即 p 为 None/空串时返回 ''。
def _norm_rel(p) -> str:
    return str(p or "").replace("\\", "/").lstrip("./")


# 生效条件：cg 具备可调用的 forget 方法时对 plan 中每个 nid 调 cg.forget(nid, why)，返回 (成功 id 列表, 被拦下/失败的 {node_id, error} 列表)；cg 无 forget 时返回 ([], plan 中每 nid 一条错误)。
def _forget_many(cg, plan, why: str) -> tuple:
    """逐条软删（进 trash/、写删除清单、可 restore）；受保护节点拦下不删。

    `forget` 属 **MdCGOS 层**能力（保护裁决 + 回收站 + 删除清单），基础层
    `MdCG` 没有任何删除原语。缺能力时**明确报错、不静默跳过**——否则
    「清退了 N 条」看着成功、实际一条没删（P27 §10 实测过这个坑）。
    """
    fn = getattr(cg, "forget", None)
    if not callable(fn):
        err = (f"{type(cg).__name__} 无 forget 能力（对账须能删除节点）；"
               f"生产路径是 MdCGOS，测试请用 MdCGOS")
        return [], [{"node_id": nid, "error": err} for nid in sorted(plan)]
    done, blocked = [], []
    for nid in sorted(plan):
        try:
            res = fn(nid, why) or {}
        except Exception as exc:            # ProtectionError 等 → 拦下，不越权
            blocked.append({"node_id": nid, "error": str(exc)[:120]})
            continue
        if res.get("ok"):
            done.append(nid)
        else:
            blocked.append({"node_id": nid, "error": str(res.get("error"))[:120]})
    return done, blocked


# 生效条件：cg 具备可调用的 _unstage 时对 ghosts 逐个调用并收集成功 id（单条异常跳过），cg 无该能力时返回 []（不假装成功）。
def _drop_ghosts(cg, ghosts) -> list:
    """摘除幽灵条目的索引记录（节点文件已不存在，没有可软删的实体）。

    走 `MdCG._unstage`：它顺带落删除记录，保证幽灵不会再次从分片日志里复活。
    基础层没有该能力时如实返回空列表（不假装成功）。
    """
    drop = getattr(cg, "_unstage", None)
    if not callable(drop):
        return []
    out = []
    for nid in ghosts:
        try:
            drop(nid)
            out.append(nid)
        except Exception:                 # 单条失败不拖垮整批
            continue
    return out


# 生效条件：items 中同 kind 的节点若其 ref['path'] 命中本次 items 的文件、id 不在本次产出内且 ref['root'] 与入参 root 同一（_same_root），则列入清退计划；dry_run 为真只返回计划，否则经 _forget_many 软删；items 为空时返回 count 0。
def prune_orphans(cg, *, kind: str, root: str, items, dry_run: bool = False,
                  reason: str = "") -> dict:
    """清退「同 root + 同 path，但已不在本次产出里」的**过期代**节点。

    为什么必须有：`node_id = sha1(相对path + "#" + heading_path)`，而
    `add_items` 只做**同 id 幂等 upsert**——文档标题结构一变，整篇 id 全量
    重算，旧代节点无人清退，与新代并存（同一文档召回两份，且旧代引用的区间
    已失效）。截断的索引由调用方负责不调用本函数（没扫完 ≠ 剩下的都过期）。

    范围**只限本次真正重切过的文件**（`items` 的 path）：增量索引跳过的未变
    文件不在 items 里，其节点不进判定——否则会把完好的节点整片误删。
    """
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    touched: dict = {}
    for it in items or []:
        rel = _norm_rel(it.get("path"))
        if rel:
            touched.setdefault(rel, set()).add(node_id_of(it, kind))
    base = {"scanned": len(nodes), "touched_files": len(touched),
            "dry_run": bool(dry_run)}
    if not touched:
        return {**base, "ok": True, "count": 0, "pruned": [],
                "skipped_protected": []}

    # ⚠ ref 只存在于**节点 frontmatter**里；`cg.index['nodes']` 是元数据快照
    # （path/layer/tags/…，见 mdcg._scan_nodes），**不含 ref**。因此必须
    # `cg.get(nid)` 取回节点再 ref_of —— 否则 ref_of 恒返回 ('', None)、
    # 整个对账静默失效（P27 §10 实测过这个坑）。标签预筛与 check_refs 同口径，
    # 免得为全库每条记忆都读一次盘。
    tag = "doc" if kind == "doc_ref" else "code"
    plan = []
    for nid, e in nodes.items():
        if tag not in ((e or {}).get("tags") or []):
            continue
        try:
            node = cg.get(nid)
        except Exception:
            continue
        if not node:
            continue
        k, ref = ref_of(node)
        if k != kind or not isinstance(ref, dict):
            continue
        keep = touched.get(_norm_rel(ref.get("path")))
        if keep is None or nid in keep or not _same_root(ref.get("root"), root):
            continue
        plan.append(nid)

    why = reason or ("索引重建：本节点已不在同文档新代产出中（标题路径变更致 "
                     "node_id 重算），清退过期代以消除重复召回")
    if dry_run:
        return {**base, "ok": True, "count": len(plan), "pruned": sorted(plan)[:50],
                "skipped_protected": [], "reason": why}
    done, blocked = _forget_many(cg, plan, why)
    return {**base, "ok": True, "count": len(done), "pruned": done[:50],
            "skipped_protected": blocked[:20], "reason": why}


# 生效条件：cg 中带 'code'/'doc' 标签且 ref 带 root 的节点经 probe_ref 判为 'dangling' 时列入清退计划；only_roots 为空时另收集 cg.root 下取不到对应节点 .md 的幽灵条目经 _drop_ghosts 摘除；dry_run 为真只返回计划。
def prune_dangling(cg, *, only_roots=None, dry_run: bool = False,
                   max_nodes: int = MAX_CHECK, reason: str = "") -> dict:
    """清退**悬空**节点：ref 指向的源文件已删除，回读必然失败。

    `check_refs` 只报告不处置（其原话是「悬空需人工处置」），本函数就是那个
    出口——已删脚本、被搬走的文档留下的残留节点一次清掉，而不是逐条手工
    `forget`。判定与巡检共用 `probe_ref` 的唯一实现，口径不会打架。

    另清**幽灵条目**（ghosts）：索引有条目、节点文件却不存在。它们是历史
    「删除只摘内存索引、不落盘」的遗留——`cg.get` 取不回 → 悬空清退够不着它，
    而 `check_refs` 走 ledger 会一直报 → dangling 永不归零。判据只用唯一真源
    （节点 .md 不存在即脏索引），与「索引是派生物」的宣言一致；`only_roots`
    非空时跳过（幽灵条目无 ref，无法归因到某个源大域）。
    """
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    ghosts = []
    if not only_roots:
        for nid, e in list(nodes.items()):
            tags = (e or {}).get("tags") or []
            if not any(t in ("code", "doc") for t in tags):
                continue
            path = (e or {}).get("path") or ""
            if path and not os.path.exists(os.path.join(cg.root, path)):
                ghosts.append(nid)
    # 同 prune_orphans：ref 只在节点 frontmatter 里，索引条目里没有，
    # 必须 cg.get 取回节点再 ref_of（否则恒空、静默不删）。
    todo = []
    for nid, e in nodes.items():
        tags = (e or {}).get("tags") or []
        if not any(t in ("code", "doc") for t in tags):
            continue
        try:
            node = cg.get(nid)
        except Exception:
            continue
        if not node:
            continue
        _k, ref = ref_of(node)
        if not ref or not ref.get("root"):
            continue
        if only_roots and not any(_same_root(ref.get("root"), r) for r in only_roots):
            continue
        todo.append((nid, ref))
    truncated = len(todo) > max_nodes or len(ghosts) > max_nodes
    plan = []
    for nid, ref in todo[:max_nodes]:
        try:
            if probe_ref(ref).get("status") == "dangling":
                plan.append(nid)
        except Exception:                   # 探测失败不算悬空（宁可不删）
            continue

    why = reason or ("源文件已删除，索引节点悬空（回读必然失败），"
                     "清退以消除永不消失的 dangling")
    ghost_plan = sorted(ghosts)[:max_nodes]
    base = {"scanned": len(nodes), "candidates": len(plan),
            "ghosts": len(ghost_plan),
            "dry_run": bool(dry_run), "truncated": truncated,
            "max_nodes": max_nodes}
    if dry_run:
        return {**base, "ok": True, "count": len(plan), "pruned": sorted(plan)[:50],
                "ghost_pruned": ghost_plan[:50],
                "skipped_protected": [], "reason": why}
    done, blocked = _forget_many(cg, plan, why)
    dropped = _drop_ghosts(cg, ghost_plan)
    return {**base, "ok": True, "count": len(done), "pruned": done[:50],
            "ghost_pruned": dropped[:50],
            "skipped_protected": blocked[:20], "reason": why}


# 生效条件：cg 节点按 ref['root'] 与 kind 分组后逐组以 index_dir(incremental=False, ledger=ledger) 重切、再以 add_items(layer_of=原 layer) 重建，返回 {'ok','roots','groups','indexed','errors','truncated'}；only_roots 非 None 时只处理其中列出的 root。
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