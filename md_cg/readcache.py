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
  1. **写失效哨兵**：缓存条目携带 `len(cg._dirty)` 代际——所有写路径必然
     标脏（flush 依赖 `_dirty`，add/_sync_edge_entry/负记忆化……无一例外），
     dirty 代际变化即视为「有写入发生」，该 path 重读一次。对 path-only
     无失效的朴素实现能红（外部报告实测的陈旧读场景）。
     语义与 MdStore 的「写方落盘后 reload」同构，但**懒清**：检索高频写少，
     写后首次检索全量重装一次即再稳定，不必写时同步清（写面零挂载点，
     天然覆盖未来新增写路径——不会有「漏挂失效」型陈旧读）。
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


# 生效条件：cg._read 可调用时以 (path → (dirty 代际, 解析产物)) 常驻字典包装之——命中条件为 path 存在且代际等于当前 len(cg._dirty)；cg._doc_norm_bigrams 亦存在时同款包装其派生物（_score 热点：文档侧归一化 bigram 只依赖 content，随读缓存一并常驻）；包装后 cg._read/_doc_norm_bigrams 为包装函数、cg._read_cache/_norm_bigrams_cache 为缓存字典、cg._read_uncached 为未被包装的原始 _read（direct_read 的真源）；返回缓存字典。
def install(cg):
    """把 `cg._read`（与派生物钩子）包成脏代际校验的常驻缓存。"""
    cache = {}
    # 重复 install（如显式再调）不叠加包装层，_read_uncached 恒指真原始。
    orig = getattr(cg, "_read_uncached", None) or cg._read
    cg._read_uncached = orig

    def _cached(entry):
        p = entry["path"]
        # D-4 修复（批次 23 / v20）：代际改读 _DirtyDict.write_gen（单调、
        # 永不回退）——len(_dirty) 在 flush 清零后可被新写入凑回旧值，代际
        # 巧合回退 → 陈旧读（v20_d4_repro stale=True 实测）。防御回落兼容
        # 非 _DirtyDict 形态。
        gen = getattr(cg._dirty, "write_gen", len(cg._dirty))
        hit = cache.get(p)
        if hit is not None and hit[0] == gen:
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
            if hit is not None and hit[0] == gen:
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
