# -*- coding: utf-8 -*-
"""倒排（发布表）候选层：不读遍全库即可取「词法候选」。

为何需要（实测依据：docs/hive/真实库端到端实测_S1b与召回权衡_v0.1.md）：
S1b 桶收敛能少扫 5.5~10.4 倍，但**召回集合会变**（真实库一致率仅 1/4）。要两全，
必须有「廉价高精度候选生成器」——即本模块：把「字符 bigram → 节点」做成发布表，
查询时按 bigram 交集取候选，再用既有 `_like` 精确过滤，从而**召回与全表扫描一致**。

设计要点：
1. 索引对象 = 节点 **content + tags** 的字符 bigram（与打分口径同源：mdcg.bigrams/normalize_en）。
2. 查询侧：对每个查询词 t（len ≥ 2）取 t 的 bigram 集合在发布表中的**交集**；
   这些节点必然包含 t 的全部 bigram（是「包含 t」的超集，可能跨词假阳性）；
   各词取并集 → 候选 ⊇ 真命中集 → 再用 `_like` 精确过滤 → 结果与全表扫描一致。
3. 单字查询词无法用 bigram 表达 → 该查询**回退全量**（安全，记 reason）。
4. 发布表是**快照**：节点被改写后即过期。故 build 记录**快照指纹**（节点数 + 节点目录
   mtime + 索引文件 mtime），查询前先验指纹；过期即**回退全量**（宁可慢，不可丢召回）。
   指纹只用 stat（约等于「目录数」次，本库 1,074 个目录 ≈ 0.03s），不重读节点。
5. 存储：`<root>/_postings.json`（{bigram: [id,...]}）+ `<root>/_postings_meta.json`（版本/规模/指纹）。
6. 位置：只作**候选生成器**（契约 §7 允许的「候选内加速」），不替代认知路径。
7. v1 不接写入路径的增量维护（每次写都 load+save 75MB 不可接受）：**改写后请重建**；
   重建是幂等且无副作用的（不改任何节点内容）。增量（dirty 集）为下一里程碑。
"""
import hashlib
import io
import json
import os
import sys
import time

from .fsutil import publish

SCHEMA = "mdcg-postings-2"


# 生效条件：root 为真值时返回 root 下 postings 数据文件路径，否则返回 "_postings.json"（相对路径）。
def postings_path(root: str) -> str:
    return os.path.join(root or "", "_postings.json")


# 生效条件：root 为真值时返回 root 下 postings 元数据文件路径，否则返回 "_postings_meta.json"。
def meta_path(root: str) -> str:
    return os.path.join(root or "", "_postings_meta.json")


# 生效条件：无条件以 utf-8 惰性引入 mdcg 的 bigrams/normalize_en 并返回；导入失败返回 (None, None)。
def _bigrams_fn():
    try:
        from .mdcg import bigrams, normalize_en
        return bigrams, normalize_en
    except Exception:
        return None, None


# 生效条件：path 可 stat 时返回 st_mtime_ns（int），否则返回 None。
def _mtime_ns(path: str):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


# 生效条件：text 与 tags 均为假值时返回空集合；否则返回二者（tags 以空格拼接）经 normalize_en 后的 bigram 并集；
# bigrams/normalize_en 不可用时返回空集合。
def ngrams(text, tags=None) -> set:
    """节点侧取词：content + tags 的字符 bigram 集合（与打分同源）。"""
    bigrams, normalize_en = _bigrams_fn()
    if bigrams is None:
        return set()
    buf = str(text or "")
    if tags:
        buf += " " + " ".join(str(t) for t in tags)
    if not buf.strip():
        return set()
    return set(bigrams(normalize_en(buf)))


# 生效条件：terms 为假值时返回（[]，'empty_terms'）；任一词的 normalize_en 结果长度 < 2 时返回（[]，'single_char_term'）；
# 否则返回（[每词 bigram 集合]，''），供 candidates 逐词取交集。
def term_ngram_sets(terms):
    """查询侧取词：把每个查询词转成 bigram 集合；含单字词则整体不可用（安全回退）。"""
    bigrams, normalize_en = _bigrams_fn()
    if not terms:
        return [], "empty_terms"
    if bigrams is None or normalize_en is None:
        return [], "no_bigram_fn"
    sets = []
    for t in terms:
        nt = normalize_en(str(t))
        if len(nt) < 2:
            return [], "single_char_term"
        sets.append(set(bigrams(nt)))
    return sets, ""


# 生效条件：fp 为可读文件路径时返回其**整文件字节**的 sha256 十六进制前 16 位；open/read 抛 OSError 时返回 None（读不到即「证不出」，调用方按内容层判据收口）；不缓存、不解析、不看扩展名。
def _file_digest(fp: str):
    """节点文件的**整字节身份指纹**（#131；口径与 `mdcg._file_digest` /
    `refindex._sha256_file` 同源——身份由字节定，不由时间戳定）。

    为什么必须与目录 mtime 并置：目录 mtime 只在**直接子项增删**时变化，
    **同目录内容级改写**（就地追写、备份还原、同步盘回写、人手编辑）不动它。
    实测（issue #131）：就地给节点正文追加一个词后目录 mtime 逐位不变
    （1791742330453756100 → 1791742330453756100），而**文件** mtime 与 size
    都变了；旧判据只 stat 目录 ⇒ `stale_reason` 判「新鲜」，S7 放心用旧表
    收窄、把只在新正文里出现的真命中**整条剔掉**（静默丢召回）。

    为什么还要第三元 sha256（而不是只比文件的 mtime_ns + size）：**mtime 可被
    还原**——cp -p / rsync -t / tar x / robocopy /DCOPY:T / 备份还原 / 网盘同步
    客户端回写原 mtime；粗粒度文件系统（FAT 2s、ext3 1s）下同刻度写入更是常态。
    届时一次**等长**改写同时满足 size 相等与 mtime 相等 ⇒ 身份失配判不出来。
    故 (mtime_ns, size) 失配即判陈旧（零额外 IO），**双双相等时再比内容哈希**
    ——与 `mdcg._note_witness`（#80）同一范式、同一口径。

    截 16 位：与全仓 sha256 系列（`mdcg._file_digest` 截 16、`refindex`
    截 64）同族；本判据只做同/异比较、不做安全承诺。
    """
    try:
        with open(fp, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return None


# ---- issue #178：内容指纹按 stat 身份记忆化（把整文件读盘从检索热路径上摘掉）----
# 键 = 节点文件绝对路径；值 = (st_mtime_ns, st_size, st_ctime_ns, digest)。
_DIGEST_MEMO = {}
#: 记忆表条目上界（越界即整表 clear()，避免进程内无界增长）。
_DIGEST_MEMO_MAX = 4096

#: `st_ctime` 是否等价于「inode 状态变更时间」（**记忆表命中判据的前提**）。
#:
#: ★平台差异（本笔修正的根因）：`os.stat().st_ctime` 的**含义随平台而异**——
#:   · POSIX（Linux/macOS）：**最近一次元数据变更时间**，内容改写必使其变化
#:     ⇒ (mtime_ns, size, ctime_ns) 三元组可作内容身份。
#:   · **Windows：文件创建时间**，内容改写**不**使其变化
#:     ⇒ 三元组退化为 (mtime_ns, size)，而二者都可被还原/打平
#:     （`cp -p` / `rsync -t` / 备份还原 / 粗粒度文件系统）⇒ **会返回过期 digest**。
#:
#: 实测（win32 / Python 3.12.14）：同长度就地改写 + `os.utime` 只还原 mtime 后，
#: 三项逐位相等而两次 sha256 不同（`63c1dd95…` → `4a8d8134…`）⇒ 记忆表命中并
#: 复用旧指纹 ⇒ `stale_reason` 不报 `content_changed`，`#131` 的内容层收口被绕开。
#: 故非 POSIX 平台**禁用**该记忆表（退回逐次读盘的既有语义，宁可慢、不可给陈旧结论）。
_CTIME_IS_STATUS_CHANGE = sys.platform != "win32"


# 生效条件：st 为真值且 (st_mtime_ns, st_size, st_ctime_ns) 与记忆中的三元组逐位相等时返回记忆的 digest（不读盘）；
# 否则调用既有 _file_digest(fp) 重算，结果非 None 时回填（越界先 clear()）并返回；st 为 None 或 digest 为 None 时直接返回重算结果；
# **非 POSIX 平台（`_CTIME_IS_STATUS_CHANGE` 为假）一律退回无缓存路径**。
def _file_digest_memo(fp: str, st):
    """带「按 stat 身份记忆化」的内容指纹（issue #178；判据语义与 _file_digest 逐位一致）。

    动机：`stale_reason` 的内容层原先**每次调用都逐节点整文件读盘 + sha256**，而它
    落在**检索热路径**上（`MdCG.search` → `_pd.stale_reason`；实测 800 节点 116ms
    ≈ 146µs/节点）。而每个节点在进本层之前的快路径里已确认 (mtime_ns, size) 与快照
    逐位相等——此时内容几乎总是没变，重复读盘纯属浪费。

    为什么命中判据要加平台闸：见 `_CTIME_IS_STATUS_CHANGE` 的注释。**在 POSIX 上**
    `st_ctime_ns` 是 inode 状态变更时间，用户态无法用 `utime` / `utimensat` /
    `cp -p` / `rsync -t` 伪造（那些只还原 mtime）⇒ 三元组逐位相等等价于「内容自
    上次读取以来未被改动」⇒ 复用不可能返回过期 digest。**在 Windows 上 `st_ctime`
    是创建时间**，该等价关系**不成立**（已实测复现过期 digest），故禁用记忆表。

    失败不落缓存：`_file_digest` 返回 None（OSError）时不回填，避免把一次瞬时读失败
    固化成长期结论——下次调用仍会重试读盘。
    """
    if st is None or not _CTIME_IS_STATUS_CHANGE:
        return _file_digest(fp)           # 无可用 stat 身份 ⇒ 退回无缓存路径
    hit = _DIGEST_MEMO.get(fp)
    if (hit is not None and hit[0] == st.st_mtime_ns
            and hit[1] == st.st_size and hit[2] == st.st_ctime_ns):
        return hit[3]
    digest = _file_digest(fp)
    if digest is not None:
        if len(_DIGEST_MEMO) >= _DIGEST_MEMO_MAX:
            _DIGEST_MEMO.clear()
        _DIGEST_MEMO[fp] = (st.st_mtime_ns, st.st_size, st.st_ctime_ns, digest)
    return digest


# 生效条件：index_nodes 为 dict 时返回 {"nodes": 节点数, "dir_mtimes": {相对目录: mtime_ns}, "file_mtimes": {根级相对文件: mtime_ns}, "node_files": {相对路径: [mtime_ns, size, sha256 前16位]}, "index_mtime": 索引文件 mtime_ns}；
# 假值时返回 {"nodes": 0, "dir_mtimes": {}, "file_mtimes": {}, "node_files": {}, "index_mtime": None}。
def snapshot(root: str, index_nodes) -> dict:
    """快照指纹：节点数 + 各节点目录 mtime + 根级文件 mtime + **逐节点文件内容身份** + 索引文件 mtime。

    为何用目录 mtime（第一层，廉价）：节点写入走 fsutil.atomic_write（temp +
    os.replace），目录 mtime 必然变化，故「目录 mtime + 节点数」能以 O(目录数)
    次 stat 发现「发布表已过期」，无需重读/重哈希任何节点文件。

    为何还要 node_files（第二层，内容同源；#131）：上述断言**只对走
    atomic_write 的合作写者成立**。非合作写者（就地追写/备份还原/同步盘回写）
    不动目录 mtime ⇒ 第一层判不出来。本层逐节点记 (mtime_ns, size, sha256)，
    与 `mdcg._note_witness` 同款口径，使判据与**被判对象（节点正文）同源**。
    """
    dirs, files, node_files = set(), {}, {}
    for e in (index_nodes or {}).values():
        p = (e or {}).get("path") or ""
        if not p:
            continue
        d = os.path.dirname(p)
        if d:
            dirs.add(d)
        else:
            # 根级节点（path 无目录）不能靠「根目录 mtime」判定：我们自己写的
            # _postings.json / _postings_meta.json 就在根目录，会把根目录 mtime 改掉
            # → 快照刚建就自判过期（独立复核 2026-09-19 指出）。改为逐文件记 mtime。
            files[p] = None          # [#154②] 由同趟 node_files 的 stat 回填（原为再 stat 一次）
        fp = os.path.join(root or "", p)
        try:
            st = os.stat(fp)
        except OSError:
            node_files[p] = [None, None, None]     # 读不到即「证不出」，判据侧据此判陈旧
        else:
            node_files[p] = [st.st_mtime_ns, st.st_size, _file_digest(fp)]
            if p in files:
                files[p] = st.st_mtime_ns
    return {"nodes": len(index_nodes or {}),
            "dir_mtimes": {d: _mtime_ns(os.path.join(root or "", d)) for d in dirs},
            "file_mtimes": files,
            "node_files": node_files,
            "index_mtime": _mtime_ns(os.path.join(root or "", "_index.json"))}


# 生效条件：meta 非 dict 或 schema 不符 → 'no_meta'（无数据文件时 'no_index'）；无 snapshot → 'no_snapshot'；
# 节点数 / 目录集合 / 目录 mtime / 根级文件集合 / 根级文件 mtime / 索引 mtime 任一不一致 → 对应 reason；
# 旧快照无 node_files（内容层）→ 'no_content_snapshot'；节点文件集合变化 → 'node_files_changed'；
# 逐节点 stat 失败 → 'node_file_missing'；文件 (mtime_ns, size) 或整文件 sha256 与快照不符 → 'content_changed'；
# 全部一致 → ''（空串，代表新鲜可用）。index_nodes 为假值时返回 'no_index'。
def stale_reason(root: str, index_nodes, meta=None) -> str:
    """返回 '' 表示快照仍与当前索引一致；否则返回过期原因（调用方必须回退全量）。

    判据与**被判对象同源**（#131）：`_postings.json` 索引的是**节点正文 + tags**
    的字符 bigram，故新鲜度判据的最后一层必须落到**节点文件的内容身份**上。
    前几层（节点数 / 目录 mtime / 根级文件 mtime / `_index.json` mtime）只覆盖
    「合作写者」（走 atomic_write ⇒ 目录 mtime 必变）与跨进程写（`_index.json`
    mtime 变化）；**同进程内的就地改写**两层都漏（实测：目录 mtime 逐位不变、
    `_index.json` 不变 ⇒ 旧判据返回 ''），故补 `node_files` 内容层收口。

    #178（热路径去 IO）：内容层原先在**每次调用**里逐节点整文件读盘 + sha256，而它
    落在检索热路径上（`MdCG.search` → `_pd.stale_reason`；实测 800 节点 116ms ≈
    146µs/节点）。现改为经 `_file_digest_memo(fp, st)` 取指纹：按 (mtime_ns, size,
    **ctime_ns**) 三项 stat 身份在**进程内**记忆化，命中即复用、**不读盘**；未命中
    才读盘算 digest。判据语义、返回串、快照 schema（3 元组）**逐位不变**。

    为什么不削弱 #131：**在 POSIX 上** `st_ctime_ns` 是 **inode 状态变更时间**，用户态
    **无法**用 `utime` / `utimensat` / `cp -p` / `rsync -t` 伪造——那些只还原 mtime。
    故「三项 stat 身份逐位相等」等价于「内容自上次读取以来未被改动」，复用**不可能**
    返回过期 digest；mtime 被还原、size 不变的就地改写 ⇒ **ctime 必变** ⇒ 未命中 ⇒
    重算 ⇒ 与快照不符 ⇒ 仍判 `content_changed`。

    ★平台闸（本笔修正）：该等价关系**只在 POSIX 成立**——**Windows 上 `st_ctime`
    是创建时间**，内容改写不使其变化。实测（win32 / Python 3.12.14）同长度就地改写
    + `os.utime` 只还原 mtime 后三项逐位相等而两次 sha256 不同 ⇒ 记忆表会返回过期
    digest ⇒ 本层不报 `content_changed`（即 #131 的内容层收口被绕开）。故
    `_CTIME_IS_STATUS_CHANGE` 为假时 `_file_digest_memo` **退回无缓存路径**，
    本层语义回到「逐次读盘算 digest」的既有保证（只损失 #178 的性能收益）。
    """
    if not index_nodes:
        return "no_index"
    if meta is None:
        meta = load_meta(root)
    if not isinstance(meta, dict) or meta.get("schema") != SCHEMA:
        return "no_meta" if os.path.exists(postings_path(root)) else "no_index"
    snap = meta.get("snapshot")
    if not isinstance(snap, dict):
        return "no_snapshot"
    if snap.get("nodes") != len(index_nodes):
        return "node_count_changed"
    want = snap.get("dir_mtimes") or {}
    # [#154①] 三趟「按 index_nodes 派生集合」（目录 / 根级文件 / 节点路径）收成一趟：
    # 原实现每节点算两次 os.path.dirname；本趟内 os.stat 亦记忆化——根级文件在
    # file_mtimes 层与内容层会在同一次调用里各 stat 一次。判据与返回串逐位不变。
    _stat_cache = {}
    def _stat_of(_p):
        if _p not in _stat_cache:
            try:
                _stat_cache[_p] = os.stat(_p)
            except OSError:
                _stat_cache[_p] = None
        return _stat_cache[_p]
    dirs_now = set()
    files_now = set()
    paths_now = set()
    for e in index_nodes.values():
        _p = (e or {}).get("path") or ""
        d = os.path.dirname(_p)
        if _p:
            paths_now.add(_p)
            if not d:
                files_now.add(_p)
        if d:
            dirs_now.add(d)          # 根级路径（无目录）由 file_mtimes 记账，见下
    if set(want.keys()) != dirs_now:
        return "dirs_changed"
    for d, mt in want.items():
        _st = _stat_of(os.path.join(root or "", d))
        if (_st.st_mtime_ns if _st is not None else None) != mt:
            return "dir_touched"
    want_files = snap.get("file_mtimes") or {}
    if set(want_files.keys()) != files_now:
        return "root_files_changed"
    for p, mt in want_files.items():
        _st = _stat_of(os.path.join(root or "", p))
        if (_st.st_mtime_ns if _st is not None else None) != mt:
            return "root_file_touched"
    if snap.get("index_mtime") != _mtime_ns(os.path.join(root or "", "_index.json")):
        return "index_touched"
    # ---- 内容层（#131）：逐节点文件身份 = (mtime_ns, size) 快路径 → sha256 定身份 ----
    want_nf = snap.get("node_files")
    if not isinstance(want_nf, dict):
        # 旧快照（本层引入前构建）无法证明「表与正文同源」——按「宁可慢，不可
        # 丢召回」的既有承诺 fail-closed：判过期、回退全量（重建一次即补上本层）。
        return "no_content_snapshot"
    if set(want_nf.keys()) != paths_now:
        return "node_files_changed"
    for p, rec in want_nf.items():
        fp = os.path.join(root or "", p)
        st = _stat_of(fp)
        if st is None:
            return "node_file_missing"       # 快照里有、盘上没了 ⇒ 表必过期
        if not isinstance(rec, (list, tuple)) or len(rec) < 2:
            return "no_content_snapshot"
        if (st.st_mtime_ns, st.st_size) != (rec[0], rec[1]):
            return "content_changed"         # ① 快路径：时间戳/长度任一变化即陈旧
        # ② 双双相等**不足以定身份**——mtime 可被还原（cp -p / rsync -t / 备份
        #    还原 / 粗粒度文件系统），等长改写会同时满足两式 ⇒ 比内容哈希。
        if rec[2] is None or _file_digest_memo(fp, st) != rec[2]:
            return "content_changed"
    return ""


# 生效条件：无条件读 root/_postings_meta.json 并返回 dict（缺文件/解析失败/非 dict 一律返回 {}）。
def load_meta(root: str) -> dict:
    try:
        with io.open(meta_path(root), encoding="utf-8") as f:
            m = json.load(f)
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


# 生效条件：无条件以 utf-8 原子写 path（tmp + publish，即带 Windows 短重试的 os.replace），写入的字符串为 obj 的 JSON 序列化。
def _atomic_json(path: str, obj, indent=None) -> None:
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline=chr(10)) as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":"))
    publish(tmp, path)


# 生效条件：无条件读 root/_postings.json 并返回 dict（缺文件/解析失败返回 {}；内容非 dict 亦返回 {}）。
def load(root: str) -> dict:
    p = postings_path(root)
    try:
        with io.open(p, encoding="utf-8") as f:
            t = json.load(f)
        return t if isinstance(t, dict) else {}
    except Exception:
        return {}


_CACHE = {}


# 生效条件：root/postings 为假值返回 {}；否则按 (路径, mtime, size) 缓存命中则返回缓存表，未命中则 load 后写入缓存并返回。
def load_cached(root: str) -> dict:
    p = postings_path(root)
    try:
        st = os.stat(p)
    except OSError:
        return {}
    key = (p, st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(p)
    if hit and hit[0] == key:
        return hit[1]
    t = load(root)
    _CACHE[p] = (key, t)
    return t


# 生效条件：level 经 crypto.is_encrypted_level 判为加密档时返回 True；crypto 不可用时返回 False（与 _encrypted_levels 空集同口径）。
def _crypto_is_encrypted_level(level) -> bool:
    try:
        from . import crypto
    except Exception:
        return False
    return crypto.is_encrypted_level(level)


# 生效条件：无条件惰性导入 crypto 并返回其 ENCRYPTED_LEVELS 的小写集合；crypto 不可用/无该常量时返回空集（空集=不启用密封面判据，退回旧行为）。
def _encrypted_levels() -> set:
    try:
        from . import crypto
        return {crypto.normalize_sensitivity(x)
                for x in getattr(crypto, "ENCRYPTED_LEVELS", ())} - {None}
    except Exception:
        return set()


# 生效条件：cg 同时具备 kek 与 dek 两个属性（即 MdCGSecure 一类挂了密钥面的实例）时返回 True，否则 False；
# 鸭子类型判定——不 import mdcos，避免 postings ← mdcg ← mdcos 的循环导入。
def _is_sealed_instance(cg) -> bool:
    return hasattr(cg, "kek") and hasattr(cg, "dek")


# 生效条件：nodes 为 dict 时返回其中 entry["sensitivity"] 属加密级的 id 列表（只读索引元数据，不解密、不读正文）；
# nodes 为假值、crypto 不可用或加密级集合为空时返回 []。
def _sealed_node_ids(nodes) -> list:
    lv = _encrypted_levels()
    if not lv or not nodes:
        return []
    return [nid for nid, e in (nodes or {}).items()
            if _crypto_is_encrypted_level((e or {}).get("sensitivity"))]


# 生效条件：cg 为假值或取不到 index["nodes"] 时返回 {"nodes":0,"terms":0,"postings":0,"rebuilt":False}；
# **密封面 fail-closed（#152①）**：索引中存在加密级节点、或本实例挂密钥面且当前可解密（dek 为真）时，
# 一律**不写任何文件**并返回 {"schema":…,"rebuilt":False,"refused":<原因>,"sealed_nodes":N,"reason":…}——
# 密文节点的明文 bigram 不得落进 <root>/_postings.json；
# 否则遍历 index 逐节点取 content+tags 的 bigram、按 id 去重累积，先写数据表、再取快照指纹并写元数据，
# 返回含 nodes/terms/postings/rebuild=True/snapshot 的 stats。limit 为真值时最多处理 limit 个节点。
def build(cg, limit: int = None) -> dict:
    """全量重建发布表（幂等、不改节点内容）。

    #152①（2026-10-12）：**密文库拒绝构建（fail-closed）**。本函数经 `cg.get()` 取到的
    是**解密后**的 content，其明文 bigram 一旦写进 `<root>/_postings.json` 就不再随
    `lock()` 收回——节点正文加密而词项索引不加密，等于把主题词表留在盘上。
    故：只要待索引面里存在加密级节点（或本实例正持密钥可解密），**不写任何文件**直接拒绝；
    调用方据返回值的 `refused` 字段判因（`sealed_nodes` / `sealed_instance_unlocked`）。
    """
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    if not nodes:
        return {"nodes": 0, "terms": 0, "postings": 0, "rebuilt": False}
    sealed_ids = _sealed_node_ids(nodes)
    if sealed_ids:
        return {"schema": SCHEMA, "nodes": 0, "terms": 0, "postings": 0,
                "rebuilt": False, "refused": "sealed_nodes",
                "sealed_nodes": len(sealed_ids),
                "reason": "密封面 fail-closed（#152①）：密文节点的明文 bigram 不得落进 _postings.json"}
    if _is_sealed_instance(cg) and getattr(cg, "dek", None):
        return {"schema": SCHEMA, "nodes": 0, "terms": 0, "postings": 0,
                "rebuilt": False, "refused": "sealed_instance_unlocked", "sealed_nodes": 0,
                "reason": "密封面 fail-closed（#152①）：实例持密钥可解密，明文 bigram 不得落进 _postings.json"}
    table = {}
    n = 0
    for nid, e in list(nodes.items()):
        if limit and n >= limit:
            break
        got = cg.get(nid)
        if not got:
            continue
        gs = ngrams(got.get("content"), got.get("frontmatter", {}).get("tags"))
        if not gs:
            continue
        for g in gs:
            table.setdefault(g, []).append(nid)
        n += 1
    stats = {"schema": SCHEMA, "built_at": int(time.time()), "nodes": n,
             "terms": len(table), "postings": sum(len(v) for v in table.values())}
    _atomic_json(postings_path(cg.root), table)
    if limit:
        # 抽样构建（冒烟用）只索引了部分节点 —— **绝不能**留下看似新鲜的快照，
        # 否则未索引的节点会被静默漏召回。无 snapshot → stale_reason 判 'no_snapshot'。
        stats["partial"] = True
    else:
        # 快照指纹必须在写完数据文件之后取：否则 root 目录自身的 mtime 会被本次写入改掉。
        stats["snapshot"] = snapshot(cg.root, nodes)
    _atomic_json(meta_path(cg.root), stats, indent=1)
    return dict(stats, rebuilt=True)


# 生效条件：无条件把 node_id 追加进 table 中每个 bigram 的列表（bigram 不存在则新建列表），返回追加的 bigram 个数。
def add_to_table(table: dict, node_id, text, tags=None) -> int:
    """增量维护：把某节点的 bigram 追加进表（调用方负责持久化）。v1 未接入写入路径。"""
    gs = ngrams(text, tags)
    for g in gs:
        table.setdefault(g, []).append(node_id)
    return len(gs)


# 生效条件：无条件把 node_id 从 table 各列表中移除（不存在则无操作并原样返回 table），返回剩余 bigram 数。
def remove_from_table(table: dict, node_id) -> int:
    for g in list(table.keys()):
        lst = table.get(g)
        if not lst:
            continue
        try:
            table[g] = [x for x in lst if x != node_id]
        except Exception:
            continue
        if not table[g]:
            table.pop(g, None)
    return len(table)


# 生效条件：terms 为假值或任一词为单字（或 bigram 函数不可用）时返回 (None, reason)；发布表为空时返回 (None,'no_index')；
# 否则逐词以「该词的全部 bigram 发布列表交集」取候选、各词取并集，返回 (候选 id 集合, '')。
def candidates(root: str, terms):
    """返回 (candidate_ids | None, reason)。None 表示「不可用，调用方应回退全量」。"""
    sets, reason = term_ngram_sets(terms)
    if not sets:
        return None, reason or "unusable_terms"
    table = load_cached(root)
    if not table:
        return None, "no_index"
    out = set()
    for gs in sets:
        lists = [table.get(g) for g in gs]
        if any(x is None for x in lists):
            continue                     # 该词有 bigram 不在表里 → 该词无候选（并集里不贡献）
        inter = set(lists[0])
        for x in lists[1:]:
            inter &= set(x)
            if not inter:
                break
        out |= inter
    return out, ""


# 生效条件：无条件统计 root 下发布表规模并返回 {"terms": 词项数, "postings": 倒排条目数, "meta": 元数据 dict 或 None}；
# index_nodes 为真值时附带 "stale_reason"（'' 表示新鲜），否则该项为 None。
def stats(root: str, index_nodes=None) -> dict:
    t = load_cached(root)
    meta = load_meta(root) or None
    return {"terms": len(t), "postings": sum(len(v) for v in t.values()), "meta": meta,
            "stale_reason": (stale_reason(root, index_nodes, meta) if index_nodes is not None else None)}
