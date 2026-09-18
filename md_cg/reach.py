# -*- coding: utf-8 -*-
"""reach.py · 检索候选收敛层：大域收敛 → 条件门控 → 图扩散（确定性、零 LLM）。

背景（2026-09-18 A3 基线取证）：`MdCG/MdCGSecure.search` 的 T2 全局阶段对**全部候选**
`_read_many(entries)`（实测 7395/12092 ≈ 0.6116，且 5 条不同查询的 scanned 完全相同）
——触碰量与查询无关，说明它做的是全表/大域扫描，而不是「按查询收敛」。

本层在**读盘之前**把候选收敛到「必要条件成立」的子集，三步各司其职：
  ① 大域收敛：bigram 倒排（query bigrams ∪ 各 term 的 bigrams ∪ 原始查询 bigrams → 并集）。
     口径**精确**：LIKE 命中要求 term 作为子串出现 ⟹ term 的所有 bigram 必在文档
     bigram 集内；词法打分 >0（bigram 重合）要求至少一个 query bigram 命中 ⟹ 倒排并集
     必为「LIKE 命中 ∪ bigram 正分」的**超集**（证明见 test_reach.py 的包含性断言）。
     **例外（已声明）**：_score 的 tag_bonus（标签与原始查询互为子串）可给单字符标签的
     节点 +0.05 分而不共享任何 bigram。这类节点不在收敛集内，但**仍不丢召回**：它只能经
     T3 全量兜底阶段进入结果，而该阶段仅在收敛阶段未返回时运行（收敛阶段失败 → 走原全量
     路径）；收敛阶段成功 ⟺ 原 T2 成功（LIKE 命中集相等），此时两条路径都不含该节点。
  ② 条件门控：只把「被接受的**必要条件**」提前到读盘前——层/角色/会话/分支
     + 可读性（_open_content 返回 None 的节点在构建期即剔除）。**时窗/生命周期/重要度
     密级（clearance）等只影响排序或由调用方与 _readable 负责**，本层不新增门控，避免静默改变结果集。
  ③ 图扩散：按索引内 `edges`（零读盘）做 1..N 跳扩散补召回；只吸收在候选集合内、
     且带 content_hash 的邻居，宁少不误扩散。

回退：任何一步不适用（开关关闭 / 单字符 term / 索引不可写且无缓存 / 收敛集为空）
→ 返回 (None, meta)，调用方继续走原全量阶段，**旧行为不变**。

# 功能名：检索候选收敛层
# 生效条件：MdCG/MdCGSecure.search 在 T2 全局阶段之前调用本层时；进程环境 MDCG_REACH != "0"；库根可写（首建缓存）或缓存已存在；查询各 term 长度 >= 2（bigram 能覆盖子串语义）
# 子功能：bigram 倒排大域收敛（LIKE 与词法打分双路并集，超集精确）；条件门控（只提前「接受的必要条件」：层/角色/会话/分支 + 可读性；时窗/生命周期/密级等仅排序或由调用方负责，不作门控）；edges 图扩散补召回；命中不足或条件不满足时回退全量
# 执行：from md_cg import reach；reach.narrow(cg, entries, terms, qb, context) -> (entries 或 None, meta)；缓存文件 <root>/_reach_index.json（MDCG_REACH_INDEX 可改写落点）；开关 MDCG_REACH=0 关闭
# 验证方式：md_cg/test_reach.py（收敛集必含 LIKE/打分命中集、门控/扩散/回退逐项断言）；_coord/a3_reach.py（A1 全组回归、A2 新旧结果对比、A3 触碰比）
# A3 口径（与文档对齐）：meta.scanned 只计**检索读盘**（_read_many）；索引首建/重建的全库读盘
# 另计于 meta.reach_build_docs，两者不可混淆——报 A3 时须同时给「稳态均值」与「含首建均值」。
# 重建中途失败也如实暴露：meta.reach == "index_unavailable" 时带 meta.reach_build_docs（已读盘量）
# 与 meta.reach_build_docs=**已进入倒排**的节点数、meta.reach_build_reads=**已实际读盘**的节点数（含读失败/解密失败）、meta.reach_build_partial=True；
# 无读盘则这些键均不出现（r7/r8 独立复核取证：旧写法把部分读盘成本藏起来了，且只计入索引数会漏计「读了很多但都不可读」的情形）。
# 新鲜度覆盖边界（如实声明）：键 = content_hash（正文）+ tags + edges。fm.semantic 属**前置元数据且不在索引条目中**，
# 仅改 semantic 标志不会改变键；该情形由 TTL（默认 600s）兜底——**在 TTL 窗口内**改 semantic 标志可能破坏 new 包含 old（窗口上界=TTL）；若需秒级精确，应把 semantic 纳入索引条目后再入键。
# 已知风险（如实声明）：落盘缓存 post 内含**明文 bigram**，目前未按主体/密级隔离——
# 多主体共用同一 root 时，缓存文件本身即构成跨主体词面信息（读盘/内存无越权，但文件级隔离未做）。
# 不适用条件：①查询含单字符 term（bigram 无法表达单字子串）→ 不收敛 ①b库内有节点缺 content_hash 且非本次重建 → 不收敛（宁全量不冒陈旧丢召回）①c图扩散默认关闭（MDCG_REACH_DIFFUSE=1 开启：扩散节点参与 top-k 竞争，召回增加但 A2 的集合包含性不再逐位保证） ②MDCG_REACH=0 ③索引内容过时（content_hash 不符 / 超过 MDCG_REACH_TTL 默认 600s）时先全量重建，重建失败即不收敛 ④只读根且无缓存时：当次仍以内存索引收敛，但**不入进程缓存**（下次调用重新构建）——收敛收益减少但结果不丢，且与声明一致 ⑤首建当次额外读全库（meta.reach_build_docs 如实暴露），A3 稳态值不含该次 ⑤密级（clearance）过滤由调用方与 _readable 负责，本层不新增 ⑥首建当次调用会读全库（meta.reach_build_docs 如实暴露），稳态才享受收敛收益
"""
from __future__ import annotations

import json
import math
import os
import time

from .fsutil import FileLock, atomic_write
from . import nodefile


# 生效条件：调用发生在 md_cg.mdcg 完成导入之后（本模块被 mdcg 顶层 import 时**不得**在模块级取用
# mdcg 的符号，否则 mdcg↔reach 循环导入）；返回 (bigrams, normalize_en) 两函数。
def _lex():
    """延迟取词法函数——规避 mdcg ↔ reach 循环导入（模块级 from .mdcg import X 会失败）。"""
    from .mdcg import bigrams as _bg, normalize_en as _ne
    return _bg, _ne


# 生效条件：content 为节点正文、tags 为标签可迭代对象时返回该文档的 token 集合 = bigrams(正体小写) ∪ bigrams(标签小写) ∪ bigrams(normalize_en(正文))；content 为假值时按空串处理。
def _doc_tokens(content, tags):
    bg, ne = _lex()
    body = nodefile.positive_body(content).lower()
    tag_s = " ".join(str(t) for t in (tags or [])).lower()
    # 文档侧 token = 正体小写 ∪ 标签小写 ∪ normalize_en(正文) ∪ normalize_en(正文).lower()
    # 末项是**超集保险**：查询侧与 LIKE 都走小写口径，故索引侧再收一份全小写（r13 复核：
    # 若 LIKE 命中落在正体之外且含大写/全角，仅 ne() 可能不产生对应小写 bigram）
    return bg(body) | bg(tag_s) | bg(ne(content)) | bg(ne(content).lower())

INDEX_NAME = "_reach_index.json"
#: 倒排落盘用 JSON 列表（曾用逗号/单元分隔符拼接：含该字符的路径会被拆碎，r1/r11 复核取证）
SCHEMA_VERSION = 1
#: 扩散触发阈值：收敛集小于该值时才做图扩散（避免大集合上无谓放大）
DIFFUSE_BELOW = 400
#: 未索引/新写入节点的并入上限：超过即整段回退不收敛（不静默截断——截断会破坏超集/A2）
_FRESH_MAX = 500
#: 扩散放大上限：不超过收敛集该倍数（防扩散把 A3 触碰比吃回去）
DIFFUSE_MAX_FACTOR = 3

#: 进程内缓存：root -> (ReachIndex, 载入时的库指纹)
_CACHE = {}


# 生效条件：读取 MDCG_REACH_TTL；值为非正数或不可解析时回落到默认 600.0（**不得**把 TTL=0 解释为关闭新鲜度兜底——semantic 变更依赖它，r11 复核取证）。
def _ttl() -> float:
    try:
        v = float(os.environ.get("MDCG_REACH_TTL") or 600.0)
    except ValueError:
        return 600.0
    # 非有限（inf/nan/1e999）视同非法：否则过期判断永假 → 声明中的 TTL 兜底被静默取消（r12 复核取证）
    if not math.isfinite(v) or v <= 0:
        return 600.0
    return v


# 生效条件：idx 若本次发生了全量重建（built_now）则返回 {"reach_build_docs": built_docs}，否则返回 {}——
# 供**所有**窄化出口（含 hash_incomplete/fresh_overflow 回退）如实暴露首建成本。
def _build_meta(idx) -> dict:
    if getattr(idx, "built_now", False):
        return {"reach_build_docs": getattr(idx, "built_docs", 0),
                "reach_build_reads": getattr(idx, "built_reads", 0)}
    return {}


# 生效条件：环境变量 MDCG_REACH 等于 "0" 时返回 False，其余（含未设置）返回 True。
def enabled() -> bool:
    return os.environ.get("MDCG_REACH", "1") != "0"


# 生效条件：环境变量 MDCG_REACH_DIFFUSE 等于 "1" 时返回 True，其余（含未设置）返回 False。
def diffuse_on() -> bool:
    """图扩散开关（默认关）：扩散节点会与词面命中一起参与 top-k 竞争，
    为使 A2「new ⊇ old」在默认配置下**精确成立**，此能力默认关闭、需显式开启。"""
    return os.environ.get("MDCG_REACH_DIFFUSE", "0") == "1"


# 生效条件：entries 中每个元素都有 path 键且 path 对应库根下的文件时，返回其 (path -> entry) 映射；缺 path 的条目被跳过。
def _by_path(entries):
    out = {}
    for e in entries:
        p = e.get("path")
        if p:
            out[p] = e
    return out


# 生效条件：entry 为索引条目时返回其 edges 的稳定签名（按 target|type 排序后拼接；无 edges 返回空串）。
def _edges_sig(entry) -> str:
    # 用 JSON 列表编码：分隔符若有歧义会导致键碰撞（r11 复核：a;b 与 [a,b] 曾同键）
    items = []
    for ed in (entry or {}).get("edges") or []:
        if isinstance(ed, dict):
            items.append([str(ed.get("target") or ""), str(ed.get("type") or "")])
        else:
            items.append([str(ed)])
    return json.dumps(sorted(items), ensure_ascii=False)


# 生效条件：entry 为索引条目时返回其新鲜度键 = content_hash + chr(31) + edges 签名——内容或**边**任一变化都会使键变化（r7 复核：仅改边也必须触发重建，否则扩散会复用陈旧邻接表）。
def _node_key(entry) -> str:
    # 倒排同时依赖：正文（content_hash）、标签 bigram（tags）、邻接（edges）。
    # 三者任一变化都必须判为不新鲜，否则会复用陈旧倒排（r7 补 edges、r9 补 tags）。
    tags = json.dumps([str(t) for t in ((entry or {}).get("tags") or [])], ensure_ascii=False)
    return json.dumps([str((entry or {}).get("content_hash") or ""), tags, _edges_sig(entry)],
                      ensure_ascii=False)


# 生效条件：cg 有 index["nodes"] 与 root，且根目录存在时返回「库指纹」字符串（节点数 + 各节点 content_hash 的拼接哈希）；缺字段按空串参与。
def _fingerprint(cg) -> str:
    import hashlib
    h = hashlib.sha1()
    nodes = cg.index.get("nodes") or {}
    h.update(str(len(nodes)).encode())
    for k in sorted(nodes):
        # 指纹含 **path** 与 **edges 签名**：路径交换/重命名、或仅增删改边时都必须判为变更，
        # 否则进程缓存复用会给「旧 path 的倒排」或「旧邻接表」（扩散沿已删边/漏新邻居）
        h.update((str(nodes[k].get("path") or "") + chr(31)).encode())
        h.update(_node_key(nodes[k]).encode())
    return h.hexdigest()


class ReachIndex:
    """bigram 倒排 + 邻接表（edges），落盘于 <root>/_reach_index.json。"""

    # 生效条件：root 给定时记录根目录与缓存路径；构造本身不读盘。
    def __init__(self, root: str):
        self.root = root
        # 缓存落点：默认 <root>/_reach_index.json；环境变量 MDCG_REACH_INDEX 可改到别处
        # （测量/演练时避免在真实记忆库根下落盘）
        self.path = os.environ.get("MDCG_REACH_INDEX") or os.path.join(root, INDEX_NAME)
        self.post = {}      # bigram -> [path, ...]
        self.adj = {}       # path -> [path, ...]
        self.hashes = {}    # path -> content_hash
        self.sem = []       # 语义摘要节点（fm.semantic 为真）——MDCG_SEMANTIC=1 时无条件入池
        self.persist_failed = False  # 落盘失败（只读根）：不跨调用复用
        self.built_fingerprint = ""   # 建库时的库指纹（磁盘新鲜度判据）
        self.built_now = False   # 本次进程缓存是否刚做过全量重建（供审计首建成本）
        self.hash_complete = True   # 库内节点是否都有 content_hash（缺则不复用缓存）
        self.built_docs = 0      # 本次重建**已进入倒排**的节点数
        self.built_reads = 0     # 本次重建**已实际读盘**的节点数（含读失败/解密失败；失败时如实暴露 I/O 成本）
        self.built_at = 0.0

    # 生效条件：缓存文件存在且 JSON 可解析、schema 版本相符时载入 post/adj/hashes 并返回 True；文件缺失/损坏/版本不符返回 False（调用方转入重建）。
    def load(self) -> bool:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return False
        if not isinstance(d, dict) or d.get("v") != SCHEMA_VERSION:
            return False
        self.post = {k: list(v) for k, v in (d.get("post") or {}).items() if v}
        self.adj = d.get("adj") or {}
        self.hashes = d.get("hashes") or {}
        self.sem = list(d.get("sem") or [])
        self.built_at = float(d.get("built_at") or 0.0)
        self.built_fingerprint = str(d.get("fp") or "")
        return True

    # 生效条件：cg 有 index["nodes"] 且可逐条 _read 时，全量重建倒排与邻接：文档 token = bigrams(positive_body 小写) ∪ bigrams(标签小写) ∪ bigrams(normalize_en(content))（前者覆盖 LIKE、后者覆盖词法打分）；邻接取 index 内 edges 的 target，仅保留在索引中的目标。
    def build(self, cg):
        nodes = cg.index.get("nodes") or {}
        id2path = {k: (v.get("path") or "") for k, v in nodes.items()}
        hashes, post, adj, sem = {}, {}, {}, []
        for k in sorted(nodes):
            e = nodes[k]
            p = e.get("path")
            if not p:
                continue
            fm, c = cg._read(e)
            self.built_reads += 1            # 已发生一次读盘：无论该节点是否可读、后续是否报错，都如实计数（r8 复核取证）
            if c is None:
                continue                      # 读不到 → 与检索路径同样跳过
            # 与 _read_many 同口径：密文节点必须解密后再取 token，否则加密节点
            # 只索引到密文 → 收敛集漏掉它们（A2 召回退化，2026-09-18 由 test_p3 取证）
            c = cg._open_content((fm or {}).get("id"), fm, c)
            if c is None:
                continue
            hashes[p] = _node_key(e)
            self.built_docs = len(hashes)    # 渐进计数：中途抛错也能如实暴露已入倒排量（r7 复核取证）
            if (fm or {}).get("semantic"):
                sem.append(p)                 # MDCG_SEMANTIC=1 时该节点无条件入池 → 必须进收敛集
            for b in _doc_tokens(c, (fm or {}).get("tags")):
                post.setdefault(b, []).append(p)
        for k, e in nodes.items():
            p = e.get("path")
            if not p or p not in hashes:
                continue
            nb = []
            for ed in e.get("edges") or []:
                tgt = ed.get("target") if isinstance(ed, dict) else ed
                tp = id2path.get(tgt)
                if tp and tp in hashes:
                    nb.append(tp)
            if nb:
                adj[p] = nb
        self.post, self.adj, self.hashes, self.sem = post, adj, hashes, sem
        self.built_fingerprint = _fingerprint(cg)
        self.built_docs = len(hashes)
        # 覆盖完整性必须看**原始 content_hash**（hashes 里存的是 _node_key，
        # 含分隔符恒为真 → 曾使 hash_complete 恒判 True，r10 复核取证）
        self.hash_complete = all(bool(v.get("content_hash"))
                                 for v in nodes.values() if v.get("path"))
        self.built_at = time.time()
        return self

    # 生效条件：在 FileLock(缓存路径) 内以 atomic_write 写回 post（逗号连接）/adj/hashes/built_at；写失败抛 OSError（调用方按不收敛处理）。
    def save(self):
        d = {"v": SCHEMA_VERSION, "built_at": self.built_at, "fp": self.built_fingerprint,
             "post": {k: list(v) for k, v in self.post.items()},
             "adj": self.adj, "hashes": self.hashes, "sem": self.sem}
        with FileLock(self.path, timeout=5.0):
            atomic_write(self.path, json.dumps(d, ensure_ascii=False))

    # 生效条件：tokens 为可迭代的 bigram 集合时返回倒排并集（path 集合）；空 tokens 返回空集。
    def postings(self, tokens) -> set:
        out = set()
        for b in tokens:
            got = self.post.get(b)
            if got:
                out.update(got)
        return out

    # 生效条件：seeds 为 path 集合时按 adj 做 hops 跳扩散并返回 seeds ∪ 各跳邻居；邻居超出 limit（默认收敛集 DIFFUSE_MAX_FACTOR 倍 + 1）即停止吸收。
    def diffuse(self, seeds, hops: int = 1, limit: int = 0) -> set:
        out = set(seeds)
        if limit <= 0:
            limit = max(len(seeds), 1) * DIFFUSE_MAX_FACTOR + 1
        frontier = list(out)
        for _ in range(max(0, hops)):
            nxt = []
            for p in frontier:
                for q in self.adj.get(p) or []:
                    if q not in out:
                        out.add(q)
                        nxt.append(q)
                        if len(out) >= limit:
                            return out
            frontier = nxt
            if not frontier:
                break
        return out


# 生效条件：root 下缓存与当前库指纹一致时返回进程缓存/磁盘缓存实例；指纹不符或缓存缺失时重建并尝试落盘（落盘失败仍返回内存实例）；重建抛异常时返回 None（调用方不收敛）。缓存键含缓存路径（MDCG_REACH_INDEX 改写时互不串味）。
# 生效条件：调用 _index() 需同时拿到「本次重建失败且已部分读盘」的成本时，返回 (idx, fail_meta)；fail_meta 在成功/无读盘时为 {}。
# 为何用调用方提供的容器而不是模块级状态：模块级可变状态无锁，跨线程/跨调用都会串味
# （r8 独立复核取证）；而「失败信息与本次调用的绑定」必须显式。idx 仍按原契约返回，其它调用方无需改动。
def _index_with_meta(cg, force: bool = False):
    fail = {}
    idx = _index(cg, force=force, _fail=fail)
    return idx, fail


def _index(cg, force: bool = False, _fail=None) -> "ReachIndex | None":
    root = cg.root
    fp = _fingerprint(cg)
    idx0 = ReachIndex(root)
    key = idx0.path
    hit = _CACHE.get(key)
    ttl0 = _ttl()
    if (not force and hit and hit[1] == fp
            and not (ttl0 > 0 and (time.time() - hit[0].built_at) > ttl0)):
        hit[0].built_now = False          # 复用：本次未重建（勿把上一轮的首建标记留在 meta 里）
        return hit[0]
    idx = idx0
    ttl = _ttl()
    expired = False
    if not force and idx.load():
        expired = ttl > 0 and (time.time() - idx.built_at) > ttl
    # hash 覆盖不完整（有节点无 content_hash）→ 无法判「未变」，缓存复用会给陈旧倒排，
    # 故一律重建；重建失败则由 narrow 走 hash_incomplete 回退（T3-r5 复核取证）
    idx.hash_complete = _hash_complete(cg)
    if not force and not expired and idx.post and _disk_fresh(idx, cg):
        idx.built_now = False
        _CACHE[key] = (idx, fp)
        return idx
    try:
        idx.build(cg)
        idx.built_now = True
        try:
            idx.save()
            idx.persist_failed = False
        except OSError:
            # 只读根：当次内存索引仍可用，但**不得跨调用复用**（模块头声明「下次调用重新构建」，
            # r13 复核指出旧写法会让 _CACHE 跨调用复用，与声明不符）
            idx.persist_failed = True
    except Exception:
        # 重建中途失败：已读盘的量也必须如实暴露（不许把成本藏起来）——r7 独立复核取证
        reads = getattr(idx, "built_reads", 0)
        docs = getattr(idx, "built_docs", 0)
        if _fail is not None and (reads or docs):
            _fail["reach_build_docs"] = docs
            _fail["reach_build_reads"] = reads
            _fail["reach_build_partial"] = True
        return None
    if getattr(idx, "persist_failed", False):
        _CACHE.pop(key, None)
    else:
        _CACHE[key] = (idx, fp)
    return idx


# 生效条件：cg.index["nodes"] 中每个节点都有非空 content_hash 时返回 True，否则 False（意味着无法用 content_hash 判新鲜）。
def _hash_complete(cg) -> bool:
    # 口径与 build() 的覆盖集合一致：只按有 path 的条目判定（无 path 的条目 build 不收录，
    # 不应因此禁用缓存复用——r12 复核指出旧写法会让稳态每次全库重建）
    nodes = cg.index.get("nodes") or {}
    return all(bool(v.get("content_hash")) for v in nodes.values() if v.get("path"))


# 生效条件：磁盘缓存 hashes 与库内节点 path/content_hash 一一对应（数量相同且逐条相等）时返回 True，否则返回 False（触发重建）。
def _disk_fresh(idx: ReachIndex, cg) -> bool:
    """磁盘缓存是否新鲜：**建库时指纹 == 当前指纹**（含节点数/path/键=hash+tags+edges）。

    为什么用指纹而不是「逐条缓存条目复核」：build 会跳过不可读/解密失败的节点（它们不进 hashes），
    若要求「索引里有 path 的节点数 == 缓存条目数」，库内含任一不可读节点时永不新鲜 → 跨进程每次
    全库重建（r17 复核取证）；而只复核缓存条目又会**漏掉新增节点**（r17 修正版实测）。
    指纹同时覆盖：节点增删/改名/正文 hash/标签/邻接，且与可读性无关。
    """
    if not idx.hashes:
        return False
    return bool(idx.built_fingerprint) and idx.built_fingerprint == _fingerprint(cg)


def narrow(cg, entries, terms, qb, context=None, hops: int = 1, q: str = ""):
    meta = {"reach": "on"}
    if not enabled():
        return None, {"reach": "off"}
    terms = list(terms or [])
    if any(len(t or "") < 2 for t in terms):
        return None, {"reach": "short_term"}      # 单字符 term 的 bigram 无法覆盖子串语义
    idx, _fail = _index_with_meta(cg)
    if idx is None:
        return None, dict({"reach": "index_unavailable"}, **_fail)
    _bmeta = _build_meta(idx)          # 回退分支同样要如实暴露本次首建/重建成本（r18 复核取证）
    if not getattr(idx, "hash_complete", True):
        # 库内有节点缺 content_hash：无法证明倒排未过期 → 一律不收敛（走全量），不冒丢召回风险。
        # 注意：**不论是否本次重建**都必须回退——否则「每次重建 + 每次收敛」会把全库读盘
        # 混进稳态 scanned，并与模块头声明不符（r15 复核取证）
        return None, dict({"reach": "hash_incomplete"}, **_bmeta)
    bg, _ne = _lex()
    toks = set(qb or ())
    # 原始查询与其中文/小写形态：覆盖 _score 的 tag_bonus 路径
    # （str(tag) in q 或 q in str(tag) 会给「标签与原始查询互为子串」的节点 +0.05 分，
    #   该路径与 LIKE/词法分无关，故 token 集必须含原始查询的 bigram）
    toks |= bg(q or "")
    toks |= bg((q or "").lower())
    for t in terms:
        toks |= bg(t)
        toks |= bg((t or "").lower())
        # 与文档侧 ne() 口径对齐（terms 此前只做小写）——同样是超集方向，宁多读不漏召回
        toks |= bg(_ne(t or ""))
        toks |= bg(_ne(t or "").lower())
    toks = {b for b in toks if len(b) >= 2}
    if not toks:
        return None, dict({"reach": "no_tokens"}, **_bmeta)
    paths = idx.postings(toks)
    try:
        from .mdcg import semantic_on
        if semantic_on() and idx.sem:
            paths |= set(idx.sem)             # 语义摘要节点无条件入池（否则收敛会误丢）
    except Exception:
        pass
    by_path = _by_path(entries)
    got = [by_path[p] for p in paths if p in by_path]
    if not got:
        return None, dict({"reach": "empty_converge"}, **_bmeta)
    pre = len(got)
    diffused = []
    if diffuse_on() and len(got) < DIFFUSE_BELOW:
        # 扩散种子先按 entries 过滤（否则会从未授权/越层的索引节点拉邻居，放大读盘与内存）
        seed_paths = {p for p in paths if p in by_path}
        spread = idx.diffuse(seed_paths, hops=hops)
        got = [by_path[p] for p in spread if p in by_path]
        diffused = [e for e in got if e.get("path") not in seed_paths]
    meta.update({"reach_seed": pre, "reach": "converged", "reach_diffused": len(diffused),
                 "reach_hops": hops,
                 # 结果层要据此放行「图扩散补召回」的节点（它们没有 LIKE/词法命中，
                 # 若只按 _like 过滤就会被丢掉 → 扩散形同虚设，T3-r3 复核取证）
                 "reach_diffused_paths": [e["path"] for e in diffused]})
    # 新节点并入：索引建好之后写入的节点（created_at 晚于 built_at）可能是新命中，直接并入候选，
    # 避免「陈旧索引漏召回」窗口（文件被原地改动的情形由 TTL 兜底）
    fresh_paths = []
    for e in entries:
        pth = e.get("path")
        if pth is None or pth in paths:
            continue
        ca = e.get("created_at")
        if pth not in idx.hashes or (ca and float(ca) > idx.built_at):
            fresh_paths.append(e)        # 未索引（新写入）或索引建成后写入 → 一律并入候选
    if len(fresh_paths) > _FRESH_MAX:
        # 未索引节点过多（索引覆盖不完整/权限不完整）：既不能静默截断（截断掉的可能是 LIKE 命中，
        # 而收敛集另有命中时会提前 return，兜底不跑 → 破坏超集与 A2），也不能无限放大读盘
        # → 整段回退：不收敛，走原全量路径（r8 复核取证）
        return None, dict({"reach": "fresh_overflow", "reach_fresh_nodes": len(fresh_paths)}, **_bmeta)
    if fresh_paths:
        got = got + fresh_paths
    meta["reach_fresh_nodes"] = len(fresh_paths)
    meta.update(_build_meta(idx))          # 首建成本（若有）如实暴露
    return got, meta
