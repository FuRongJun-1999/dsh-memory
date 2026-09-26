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
     Rust `load_docs` 预计算 stripped/db_len 同款理论）；
  3. 进程内一致性边界（与 MdStore 相同的诚实边界）：跨进程/外部直接改写
     md 文件不保证可见——认知图的多进程形态（每智能体一进程）各持快照。

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


# 生效条件：cg._read 可调用时以 (path → (缓存时 write_gen, 解析产物)) 常驻字典包装之——_dirty 带 path_gen 簿记（_DirtyDict 形态）时命中条件为「该 path 最近标脏代际(path_gen)与 broad_gen 均 ≤ 缓存时 write_gen」（脏集精确失效：单节点写只失效该节点），否则回落整代际相等校验（旧口径，非 _DirtyDict 防御）；cg._doc_norm_bigrams 亦存在时同款包装其派生物（_score 热点：文档侧归一化 bigram 只依赖 content，随读缓存一并常驻）；包装后 cg._read/_doc_norm_bigrams 为包装函数、cg._read_cache/_norm_bigrams_cache 为缓存字典、cg._read_uncached 为未被包装的原始 _read（direct_read 的真源）；返回缓存字典。
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
    """
    cache = {}
    # 重复 install（如显式再调）不叠加包装层，_read_uncached 恒指真原始。
    orig = getattr(cg, "_read_uncached", None) or cg._read
    cg._read_uncached = orig

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

    def _cached(entry):
        p = entry["path"]
        gen = getattr(cg._dirty, "write_gen", len(cg._dirty))
        hit = cache.get(p)
        if hit is not None and _fresh(p, hit):
            return hit[1]
        val = orig(entry)
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
    return cache


# 生效条件：cg._read_cache 与 cg._norm_bigrams_cache 均清空（写侧显式兜底；哨兵之外的强制手段），返回清空的条目总数；无缓存时返回 0。
def clear(cg) -> int:
    """强制清空（外部批量改写文件后可手动调；正常写路径无需——哨兵自动失效）。"""
    n = 0
    for attr in ("_read_cache", "_norm_bigrams_cache"):
        c = getattr(cg, attr, None)
        if c:
            n += len(c)
            c.clear()
    return n
