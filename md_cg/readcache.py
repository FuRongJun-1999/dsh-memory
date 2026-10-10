#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灵枢 · 检索读缓存（批次 21，issue #31 P2）——MdStore 理论落地认知图检索。

理论早已有之（使用者裁定 2026-09-23 指认）：智慧之书知识层的 `MdStore`
（whitebox_kb/wisdom/md_store.py）把 md 语料**懒装载为内存图常驻**
（`{id: STNode}` + 双向边索引），写方落盘后显式 `reload()` 丢弃快照——
检索读面零磁盘 I/O。认知图检索面（`MdCGOS._read_many` → `_read`）此前
每查询对每个候选 open+read+parse 一遍（567 池实测 572 次 open，~70-86%
耗时，~230µs/节点线性退化）——「理论没有落地」。本模块即落地。

与 `install_read_cache`（eval_common.py，benchmark 专用）的差异：
  1. **写失效哨兵（脏集精确失效，缺陷迭代第 14 轮）**：缓存条目携带
     缓存时的 `write_gen`，新鲜度按 `_DirtyDict.path_gen[path]`（该 path
     最近标脏代际）与 `broad_gen`（tombstone/无 path 可辨变更的整池兜底）
     判定——**写谁失效谁**，单节点写不再使全部条目同时 miss（此前整池
     共用一个全局代际，10k 池写读交替 38.4× 退化、线性于 N）。所有写路径
     必然标脏（flush 依赖 `_dirty`，add/_sync_edge_entry/负记忆化……无一
     例外），标脏即 `_dirty[nid]=entry`（带 path）——簿记在 _DirtyDict
     钩子内自动完成，写面零挂载点，天然覆盖未来新增写路径（不会有
     「漏挂失效」型陈旧读）。对 path-only 无失效的朴素实现能红（外部报告
     实测的陈旧读场景）。
     语义与 MdStore 的「写方落盘后 reload」同构，但**懒清**：检索高频写少，
     写后首次检索只重装被写节点，不必写时同步清。
  2. 缓存**解析产物** `(fm, content)`（benchmark 版只缓存原文，parse 仍逐次），
     **并缓存文档侧检索派生物** `_doc_norm_bigrams`（归一化 bigram——批次 21
     实测本机热点 88% 在此而非 I/O：内容不变则派生物不变，随读缓存常驻；
     Rust `load_docs` 预计算 stripped/db_len 同款理论）与 `_positive_body`
     （剥除不适用条件后的召回键正文——N273，8000 池实测 ~102ms/查询，
     与 bigram 同一 path 键控 + 脏集失效口径，两者恒同步）；
  3. 进程内一致性边界（与 MdStore 相同的诚实边界）：跨进程/外部直接改写
     md 文件不保证可见——认知图的多进程形态（每智能体一进程）各持快照。
  4. **读失败不固化（C-3 / FI-M02 / N134，2026-09-29）**：只接纳「成功」与
     「终态真缺（FileNotFoundError）」两种读结果，**瞬时读失败（独占句柄/
     资源剥夺…）一律不入缓存**——修前任何返回值含 `(None, None)` 都被当正常
     值固化且 `_fresh` 恒真，一次瞬态失败即「节点从检索面永久消失」（cache
     条目字面 `(gen,(None,None))`），而 `cg.get` 直读照常可读 ⇒「get 能读、
     search 搜不到」撕裂。判别是读路径的**单点**（`MdCG._read_status` 第三
     元素，判据函数 `fsutil.classify_read_failure`），本层不看异常类型、不猜
     一遍；失败侧另有模块级计数+有界样本记账（`fsutil.transient_read_stats`），
     不再静默。**为什么不是「带失败标记 + TTL 入缓存」见 `install` 文档串。**

开关：默认**开**（issue #31 后续——生产检索入口 MdCGOS.search 默认态每查询
全池 open+realpath+parse，3300 池实测中位 ~602ms/查询、O(n) 线性；读缓存
早已实现却默认关，生产恒不装配，故默认翻转）；`MDCG_READ_CACHE=0` 显式
关闭（opt-out 零变更退出阀——跨进程改写 md 文件须本进程立即可见的部署，
或内存受限场景，可一关回到逐次读盘的旧行为）。
"""
import os

# 生效条件：无 required 形参，锚定环境变量名 MDCG_READ_CACHE；未设或值为 "1" 时返回 True（默认开，issue #31 生产 O(n) 全池扫描修复），显式设为其它值（含 "0"）时返回 False。
def enabled() -> bool:
    """读缓存开关（默认开；=0 显式关闭——opt-out 退出阀）。"""
    return os.environ.get("MDCG_READ_CACHE", "1") == "1"


# 生效条件：cg._read_uncached 属性存在时返回其以 entry 调用的结果（穿透读缓存的盘上真值直读），否则返回 cg._read(entry)（未装缓存时两者等价，零变更）。
def direct_read(cg, entry):
    """治理/写前重查专用直读——穿透读缓存，读盘上当前真值。

    读缓存默认开（issue #31 后续）后 `cg._read` 是进程内快照；治理面的
    「写前重查」「回滚比对」语义上要求盘上真值——预演与执行之间节点
    可能被他人/外部进程改写（test_mr_m4 D12「被人改动→不覆盖」形态：
    path-only 命中会让重查读到预演时装入的旧值，漏判 drift）。
    """
    fn = getattr(cg, "_read_uncached", None)
    if fn is None:
        return cg._read(entry)
    return fn(entry)


# 生效条件：cg 提供 _read_status（MdCG/MdCGSecure 恒有）时按其**三态标签**包装：第三元素为 None（成功 / 终态真缺）者照脏集精确失效口径入缓存，第三元素非 None（瞬时读失败，fsutil.READ_FAIL_TRANSIENT）者**一律不入缓存**（C-3：不得把可重试的读失败以「新鲜」身份固化）；cg 无 _read_status（非 MdCG 载体）时回落包装 cg._read，且空结果一律不接纳（无判别面时的保守侧：宁可重读，不可固化可能是瞬时的缺失）；cg._doc_norm_bigrams 存在时同款包装其派生物（_score 热点：文档侧归一化 bigram 只依赖 content，随读缓存一并常驻）；cg._positive_body 存在时同款包装其派生物（_like 热点：剥除不适用条件后的正文只依赖 content，N273 与前者同一 path 键控 + 脏集失效口径）；包装后 cg._read 与 cg._doc_norm_bigrams/cg._positive_body 走缓存、cg._read_cache/_norm_bigrams_cache/_positive_body_cache 为缓存字典、cg._read_uncached 为**穿透缓存的原始二态 _read**（direct_read 的真源，返回形状与 install 前逐位一致）；返回缓存字典。
def install(cg):
    """把 `cg._read`（与派生物钩子）包成**脏集精确失效**的常驻缓存。

    失效口径（缺陷迭代第 14 轮，high）：此前哨兵取全局单调 write_gen——
    整池共用一个代际值，任意一次单节点写使**全部**条目同时 miss，下一条
    查询全池重装（10k 池写读交替 3rep 中位 1677.6ms vs 稳态 43.7ms，
    38.4× 退化、线性于 N；生产暴露面：mcp_server 读 op=read 与写 op=write
    同一常驻实例）。`_DirtyDict` 现簿记 `path_gen`（path → 最近标脏时的
    write_gen）与 `broad_gen`（无 path 可辨变更的整池兜底代际），本包装
    据此按 path 判新鲜：**写谁失效谁**，其余条目原对象复用。写路径不必
    再改一处（标脏即 `_dirty[nid]=entry` 带 path，簿记在 _DirtyDict 钩子
    内自动完成）。

    接纳口径（C-3 / FI-M02 / N134，2026-09-29）：缓存只接纳**成功**与
    **终态真缺**两种读结果；**瞬时读失败不入缓存**。修前任何返回值（含
    `(None, None)`）一律入缓存，且该 path 无写事件时 `_fresh` 判定恒真 ⇒
    一次独占句柄/资源剥夺就被固化成「节点从检索面永久消失直到重启或再写盘」
    （cache 条目字面 `(gen, (None, None))`），而 `cg.get` 直读照常可读 ⇒
    「get 能读、search 搜不到」撕裂。判据是读路径给的**标签**（`_read_status`
    第三元素），本层**不重新判别异常类型**（单点，见 fsutil.classify_read_failure）。

    为什么是「不入缓存」而不是「带失败标记入缓存 + 失效条件」：失败标记要
    生效必须引入时间窗（TTL / 单调钟代际），而本层的失效判据只有 `_fresh`
    一维（write_gen 脏集）；给失败另开一维就是**第二份失效判据**，且 TTL 窗内
    该节点仍处「get 能读、search 搜不到」的撕裂态（只是有界）——与本缺陷要
    消灭的现象同型，仅缩窗。不入缓存则窗口为零：**释放即命中**（FI-M02 实测）。
    代价侧不存在「每次查询都重试」的性能悬崖：
      · 只有**失败的那几个 path** 每查询多一次 `open`（O(1)/path），成功节点
        仍在缓存里（O(1)），不是整池重读——量级退化的最坏情形是「全池都读
        不出来」，那正是修前（缓存恒关面）的既有开销，也不比它更差；
      · 真缺（FileNotFoundError）仍照旧入缓存 ⇒ 缺文件的节点**不会**每查询重试；
      · 失败可观测（fsutil.transient_read_stats 计数+样本），不再静默。
    """
    cache = {}

    def _fresh(p, hit):
        """hit=(缓存时 write_gen, val) 对 path p 是否仍新鲜（不陈旧）。"""
        dirty = cg._dirty
        pg = getattr(dirty, "path_gen", None)
        if pg is None:
            # D-4 修复（批次 23 / v20）：代际改读 _DirtyDict.write_gen（单调、
            # 永不回退）——len(_dirty) 在 flush 清零后可被新写入凑回旧值，代际
            # 巧合回退 → 陈旧读（v20_d4_repro stale=True 实测）。防御回落兼容
            # 非 _DirtyDict 形态（整代际相等，旧口径）。
            return hit[0] == getattr(dirty, "write_gen", len(dirty))
        # 脏集精确失效（第 14 轮）：该 path 最近标脏代际 ≤ 缓存代际即新鲜
        # ——单节点写只失效该节点；broad_gen（tombstone/无 path 可辨变更）
        # 高于缓存代际时整池保守失效（与旧整代际口径等价的安全兜底）。
        # flush 的 clear() 不推进 broad_gen：flush 只落索引派生物，节点
        # 文件变更已在各写路径 _dirty[nid]=entry（带 path）时精确失效，
        # 且生产写路径每次写后 flush（writepipe._commit_visibility）——
        # 整池失效会让精确失效在生产恒不生效；rebuild_index 收尾走
        # clear(broad=True) 推进 broad_gen（盘面重扫口径：直写文件 +
        # rebuild 收尾的写方靠它对读缓存可见）。
        return (pg.get(p, 0) <= hit[0]
                and dirty.broad_gen <= hit[0])

    status_fn = getattr(cg, "_read_status", None)
    if status_fn is not None:
        # 三态面（C-3）：_read_status 是唯一判别点，本层只按标签决定接纳与否。
        # 重复 install（如显式再调）不叠加：_read_status_uncached 恒指真原始。
        orig_status = (getattr(cg, "_read_status_uncached", None)
                       or status_fn)
        cg._read_status_uncached = orig_status
        if getattr(cg, "_read_uncached", None) is None:
            # 穿透缓存的原始二态读（direct_read 真源）：形状同 install 前。
            cg._read_uncached = (lambda entry: orig_status(entry)[:2])

        def _cached_status(entry):
            p = entry["path"]
            gen = getattr(cg._dirty, "write_gen", len(cg._dirty))
            hit = cache.get(p)
            if hit is not None and _fresh(p, hit):
                # 存储面恒为二态（成功/终态）；命中时补回「非失败」标签。
                return hit[1] + (None,)
            val = orig_status(entry)
            if val[2] is not None:
                # C-3：瞬时读失败**不入缓存**（本次即返回，下次查询重试该 path）。
                return val
            cache[p] = (gen, (val[0], val[1]))
            return val

        cg._read_status = _cached_status
    else:
        # 无判别面的载体（非 MdCG）：保守侧——空结果一律不接纳。
        orig_read = getattr(cg, "_read_uncached", None) or cg._read
        cg._read_uncached = orig_read

        def _cached(entry):
            p = entry["path"]
            gen = getattr(cg._dirty, "write_gen", len(cg._dirty))
            hit = cache.get(p)
            if hit is not None and _fresh(p, hit):
                return hit[1]
            val = orig_read(entry)
            if not val or val[0] is None or val[1] is None:
                # 无三态面可判时不得固化空结果（可能是瞬时的缺失）。
                return val
            cache[p] = (gen, val)
            return val

        cg._read = _cached

    cg._read_cache = cache

    nb_cache = {}
    if hasattr(cg, "_doc_norm_bigrams"):
        orig_nb = cg._doc_norm_bigrams

        def _cached_nb(entry, c):
            p = entry["path"]
            gen = getattr(cg._dirty, "write_gen", len(cg._dirty))
            hit = nb_cache.get(p)
            if hit is not None and _fresh(p, hit):
                return hit[1]
            val = orig_nb(entry, c)
            nb_cache[p] = (gen, val)
            return val

        cg._doc_norm_bigrams = _cached_nb
        cg._norm_bigrams_cache = nb_cache

    # N273（第 32 轮性能面）：`_positive_body` 派生物同款缓存层——同 `entry`
    # path 键、同 `_fresh` 脏集判据、同装载/失效时机（与 `_doc_norm_bigrams`
    # 一字不差的同形结构，故两者命中率与失效行为恒同步）。修前 `_like` 每
    # 查询对每个候选节点直调 `nodefile.positive_body`（逐行扫 CCG 声明段），
    # 8000 池实测每次查询 ~102ms（占热态查询 ~47%）——它却是与 bigram 同
    # 性质的纯函数（只依赖 content），缓存不对称在此收口。
    pb_cache = {}
    if hasattr(cg, "_positive_body"):
        orig_pb = cg._positive_body

        def _cached_pb(entry, content):
            p = entry["path"]
            gen = getattr(cg._dirty, "write_gen", len(cg._dirty))
            hit = pb_cache.get(p)
            if hit is not None and _fresh(p, hit):
                return hit[1]
            val = orig_pb(entry, content)
            pb_cache[p] = (gen, val)
            return val

        cg._positive_body = _cached_pb
        cg._positive_body_cache = pb_cache
    return cache


# 生效条件：cg._read_cache、cg._norm_bigrams_cache 与 cg._positive_body_cache 均清空（写侧显式兜底；哨兵之外的强制手段），返回清空的条目总数；无缓存时返回 0。
def clear(cg) -> int:
    """强制清空解析与候选派生物；返回值仍只计原三类读缓存条目。

    外部批量改写文件后可手动调；正常写路径由脏集哨兵失效。
    """
    n = 0
    candidate_index = getattr(cg, "_rrf_candidate_index", None)
    if candidate_index is not None:
        candidate_index.clear()
    bm25_index = getattr(cg, "_bm25_index", None)
    if bm25_index is not None:
        bm25_index.clear()
    cg._bm25_candidate_pool = None
    for attr in ("_read_cache", "_norm_bigrams_cache", "_positive_body_cache"):
        c = getattr(cg, attr, None)
        if c:
            n += len(c)
            c.clear()
    return n
