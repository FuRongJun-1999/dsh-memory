# -*- coding: utf-8 -*-
"""stg 第 3 层：结构索引（装载期内存倒排 + 写路径增量维护）。

设计稿：`docs/plans/stg条件化与结构索引_设计_v0.1.md`（2026-10-03 使用者签收）。
本模块只放**结构与取数**：三张表的构建 / 增删 / 取子集 / 一致性自检。

「何时构建、何时回退、回退怎么上报」的编排在读侧（`stg.py`）；
「何时调增删钩」的编排在写侧（`mdcg._set_index_entry` / `mdcg._remove_index_entry`）。
两处都只经本模块的单点，不另写第二份分类口径。

三张表（**不变量：恒为快照 keys 的划分**，见 `verify`）：

    · `by_session: {sid | None | _UNHASHABLE: [id, ...]}`——`None` = 无会话归属
      （`unassigned` 兜底桶，语义与基线 ``fm.get("session") != sid`` 的等值比较一致）；
    · `by_layer:   {layer | _UNHASHABLE: [id, ...]}`；
    · `by_time:    [(t, id), ...]` 升序——`t` 取**观察轴区间起点**，经既有单点
      `trust.time_window_of`（= `stg._interval` 同一实现，不引入第二套时间解析）；
      无有效时间戳 → `untimed`；非有限值（NaN/±inf）→ `nonfinite`（见下）。
    另加 `pos: {id: 物理位序}`——子集按**索引物理序**回排：基线 `_scan` 的候选序
    就是快照物理序，等价性判据（flag 开/关逐位一致）要求取数面能复现它。

**为什么 nonfinite 单列**（不并入 untimed）：基线里 NaN 时间戳节点并非「无时间」——
`_interval` 对 `(nan, nan)` 判非 None，`time_relation` 落到最后一档 `overlaps`，于是
NaN 节点**会**命中时间窗查询；`±inf` 则分别落 `after`/`before`（永不命中）。故 NaN 必须
进时间窗查询的候选面（`subset` 对 time 维一并带上 nonfinite——保守超集，逐条精确判定
仍在 `_scan` 侧），untimed 才与基线「跳过」语义对齐。

不适用条件：非 stg 读侧（`cg(op=read)` 的候选收敛走 `apply_retrieval_gates`，与
本索引不同维、不共用）；跨进程共享（本索引是**进程内**派生结构，各进程自建）。
"""
from __future__ import annotations

import bisect
import math

from . import trust

#: 不可哈希的 session/layer 值（脏盘面才可能出现的形态）统一归此哨兵键。
#: 任何**具体会话/层**查询都查不到它——与基线 `!=` 等值比较同语义（脏值恒不等）。
_UNHASHABLE = object()

#: 维缺省哨兵（`None` 是**合法取值**：session=None 即 unassigned 桶，不可与「未给该维」混同）。
MISSING = object()


class _TimeBlocks:
    """Sorted time pairs with bounded local moves and inclusive range reads.

    Leaf size follows sqrt(layout population). Rebuild only after a fourfold
    population change; split/merge keeps both leaf moves and directory moves
    O(sqrt(N)) amortized, instead of shifting N pairs for each timed deletion.
    Iteration/indexing retain the old sequence view for diagnostics/guards.
    """
    def __init__(self, bulk=False, lower=None):
        self._blocks, self._maxes = [], []
        self._lower, self._mins = lower, []
        self._size, self._layout, self._leaf = 0, 1, 32
        self._pending = [] if bulk else None

    def __len__(self):
        return self._size

    def __iter__(self):
        if self._pending is not None:
            yield from sorted(self._pending)
        else:
            for block in self._blocks:
                yield from block

    def __getitem__(self, index):
        if isinstance(index, slice):
            return list(self)[index]
        if index < 0:
            index += self._size
        if index < 0 or index >= self._size:
            raise IndexError(index)
        if self._pending is not None:
            return sorted(self._pending)[index]
        for block in self._blocks:
            if index < len(block):
                return block[index]
            index -= len(block)
        raise IndexError(index)

    def __delitem__(self, index):
        self.remove(self[index])

    def insert(self, index, item):
        self.add(item)  # sorted collection: item, rather than ordinal, owns order

    def _reset(self, items):
        self._size = len(items)
        self._layout = max(1, self._size)
        self._leaf = max(32, math.isqrt(self._layout))
        self._blocks = [items[i:i + self._leaf]
                        for i in range(0, len(items), self._leaf)]
        self._maxes = [block[-1] for block in self._blocks]
        if self._lower is not None:
            self._mins = [min(map(self._lower, block)) for block in self._blocks]

    def finish(self):
        if self._pending is not None:
            items = sorted(self._pending)
            self._pending = None
            self._reset(items)

    def _resize(self):
        if self._size > 4 * self._layout or self._size * 4 < self._layout:
            self._reset(list(self))

    def add(self, item):
        if self._pending is not None:
            self._pending.append(item)
            self._size += 1
            return
        if not self._blocks:
            self._blocks, self._maxes = [[item]], [item]
            if self._lower is not None:
                self._mins = [self._lower(item)]
        else:
            i = min(bisect.bisect_left(self._maxes, item), len(self._blocks) - 1)
            block = self._blocks[i]
            bisect.insort(block, item)
            self._maxes[i] = block[-1]
            if self._lower is not None:
                self._mins[i] = min(map(self._lower, block))
            if len(block) > 2 * self._leaf:
                middle = len(block) // 2
                left, right = block[:middle], block[middle:]
                self._blocks[i:i + 1] = [left, right]
                self._maxes[i:i + 1] = [left[-1], right[-1]]
                if self._lower is not None:
                    self._mins[i:i + 1] = [min(map(self._lower, left)), min(map(self._lower, right))]
        self._size += 1
        self._resize()

    def remove(self, item):
        i = bisect.bisect_left(self._maxes, item)
        if i == len(self._blocks):
            raise KeyError(item)
        block = self._blocks[i]
        j = bisect.bisect_left(block, item)
        if j == len(block) or block[j] != item:
            raise KeyError(item)
        del block[j]
        self._size -= 1
        if not block:
            del self._blocks[i]
            del self._maxes[i]
            if self._lower is not None:
                del self._mins[i]
        else:
            self._maxes[i] = block[-1]
            if self._lower is not None:
                self._mins[i] = min(map(self._lower, block))
            if len(block) < self._leaf // 2 and len(self._blocks) > 1:
                a = i - 1 if i else 0
                if len(self._blocks[a]) + len(self._blocks[a + 1]) <= 2 * self._leaf:
                    merged = self._blocks[a] + self._blocks[a + 1]
                    self._blocks[a:a + 2] = [merged]
                    self._maxes[a:a + 2] = [merged[-1]]
                    if self._lower is not None:
                        self._mins[a:a + 2] = [min(map(self._lower, merged))]
        self._resize()

    def range_ids(self, lo, hi):
        if lo > hi:
            return []
        out = []
        i = bisect.bisect_left(self._maxes, (lo,))
        for j in range(i, len(self._blocks)):
            block = self._blocks[j]
            a = bisect.bisect_left(block, (lo,))
            for t, nid in block[a:]:
                if t > hi:
                    return out
                out.append(nid)
        return out

    def crossing_ids(self, lo):
        """End >= lo and start < lo, pruning whole blocks by minimum start."""
        out = []
        i = bisect.bisect_left(self._maxes, (lo,))
        for j in range(i, len(self._blocks)):
            if self._mins[j] >= lo:
                continue
            block = self._blocks[j]
            a = bisect.bisect_left(block, (lo,))
            out.extend(nid for end, nid in block[a:]
                       if self._lower((end, nid)) < lo)
        return out


# 生效条件：value 可 hash 时原样返回，hash 抛 TypeError（list/dict 等）时返回模块级哨兵 _UNHASHABLE。
def _hashable(value):
    try:
        hash(value)
    except TypeError:
        return _UNHASHABLE
    return value


# 生效条件：entry 为 dict 时以 trust.time_window_of(entry, "observed") 取观察轴两端点，两端均可判定则返回 float(起点)，任一端不可判定（None）或 entry 非 dict 时返回 None；不做第二套解析、不猜测。
def time_of(entry):
    """条目 → 观察轴区间**起点**（epoch 秒）；不可判定 → None。

    与 `stg._interval` **同一解析单点**：有限时间逐位一致；非有限数值只在
    本索引保留为保守候选，不视为合法查询端点。`_scan` 把 `time_window` 平铺进 `condition_space`
    而 `time_window_of` 两种载体都读（见其「兼容两种载体形态」注释），
    `temporal` 优先级与毫秒归一也同一份 `trust.parse_time`。
    """
    if not isinstance(entry, dict):
        return None
    # Preserve the index's conservative NaN/inf bucket. These are not legal
    # query endpoints; the derived candidate superset must retain uncertainty.
    s, e = trust.time_window_of(entry, "observed", _allow_nonfinite=True)
    if s is None or e is None:
        return None
    return float(s)


# 生效条件：index_obj 为含 dict 型 "nodes" 的快照（或顶层就是 dict）时返回按其**物理序**一次性构建的 StgIndex（分类 O(N)，时间对排序 O(N log N)）；"nodes" 缺失或非 dict 时返回 None（调用方据此回退并上报 reason，不静默）。
def build(index_obj):
    """快照 → 三张表（时间对批量排序，其余维线性）；快照形态不可用返回 None。"""
    nodes = index_obj.get("nodes") if isinstance(index_obj, dict) else None
    if not isinstance(nodes, dict):
        return None
    ix = StgIndex(index_obj)
    ix.by_time = _TimeBlocks(bulk=True)
    ix.by_end = _TimeBlocks(bulk=True, lower=ix._interval_start)
    for nid in nodes:                      # 快照物理序（dict 插入序）→ pos 即此序
        ix.add(nid, nodes[nid])
    try:
        ix.by_time.finish()
        ix.by_end.finish()
    except Exception:
        # Bulk sorting postpones comparison errors until after add(). Keep
        # the original fail-closed contract: callers fall back on broken.
        ix.broken = True
    return ix


# 生效条件：ix 为 StgIndex、nodes 为快照 nodes 映射时，逐项核对「三表恒为快照 keys 的划分」——pos 与快照键集双向相等、pos 序 == 快照物理序、by_session/by_layer 各桶两两不交且并集 == 键集、by_time ∪ nonfinite ∪ untimed 同上、by_time 升序且分类与条目实际 session/layer/时间逐条一致、**四个桶的下标表与桶列表互为逆映射（#157，swap-pop 的正确性判据）**；返回不一致说明列表（空 = 不变量成立）。O(N)，守卫/审计用，不在取数热路径。
def verify(ix, nodes):
    """划分不变量自检：返回不一致说明列表（空 = 完好）。"""
    bad = []
    ends, starts, uncertain = {}, {}, set()
    for nid, entry in nodes.items():
        start, end = trust.time_window_of(entry, "observed", _allow_nonfinite=True)   # 与 _classify 同口径，否则 verify 与 index 的 uncertain 集合分裂
        if start is not None and end is not None and math.isfinite(start):
            if not math.isfinite(end):
                uncertain.add(nid)
            elif end != start:
                ends[nid] = end
                starts[nid] = start
    if list(ix.by_end) != sorted((end, nid) for nid, end in ends.items()):
        bad.append("by_end 与观察区间终点不一致")
    if (ix.interval_ends != ends or ix.uncertain_ends != uncertain
            or ix.interval_starts != starts):
        bad.append("区间终点分类与快照不一致")
    if ix.by_end._mins != [min(ix.interval_starts[nid] for _end, nid in block)
                           for block in ix.by_end._blocks]:
        bad.append("区间块最小起点与内容不一致")
    if ix.broken:
        bad.append("broken：增量维护期已记不一致标记（写钩异常）")
    ids = set(nodes)
    if set(ix.pos) != ids:
        bad.append("pos 键集与快照不等：多 %d / 缺 %d"
                   % (len(set(ix.pos) - ids), len(ids - set(ix.pos))))
    if sorted(ix.pos, key=ix.pos.get) != list(nodes):
        bad.append("pos 序与快照物理序不一致（取数面无法复现基线候选序）")
    if len(ix.pos) != len(nodes):
        bad.append("len(pos)=%d ≠ len(nodes)=%d" % (len(ix.pos), len(nodes)))
    for name, table in (("by_session", ix.by_session), ("by_layer", ix.by_layer)):
        seen = []
        for bucket, lst in table.items():
            seen.extend(lst)
            if len(set(lst)) != len(lst):
                bad.append("%s[%r] 桶内重复 id" % (name, bucket))
        if len(seen) != len(set(seen)):
            bad.append("%s 有 id 落在多个桶（非划分）" % name)
        if set(seen) != ids:
            bad.append("%s 并集与快照键集不等（多 %d / 缺 %d）"
                       % (name, len(set(seen) - ids), len(ids - set(seen))))
    # #157：下标表与桶列表必须**互为逆映射**——swap-pop 的正确性只由这条守住。
    # 删错下标若只错在顺序上，集合级判据（上面那些）未必立刻察觉；这里逐位核。
    for name, table, imaps in (("by_session", ix.by_session, ix.ix_session),
                               ("by_layer", ix.by_layer, ix.ix_layer)):
        if set(imaps) != set(table):
            bad.append("%s 下标表的桶键与列表不同步（多 %d / 缺 %d）"
                       % (name, len(set(imaps) - set(table)),
                          len(set(table) - set(imaps))))
        for bucket, lst in table.items():
            imap = imaps.get(bucket)
            if imap is None or len(imap) != len(lst):
                bad.append("%s[%r] 下标表缺失或长度不符（%s != %d）"
                           % (name, bucket,
                              "None" if imap is None else len(imap), len(lst)))
                continue
            for i, x in enumerate(lst):
                if imap.get(x) != i:
                    bad.append("%s[%r] 下标表与列表不符（%s -> %r，期望 %d）"
                               % (name, bucket, x, imap.get(x), i))
                    break
    for name, lst, imap in (("untimed", ix.untimed, ix.ix_untimed),
                            ("nonfinite", ix.nonfinite, ix.ix_nonfinite)):
        if len(imap) != len(lst):
            bad.append("%s 下标表长度不符（%d != %d）" % (name, len(imap), len(lst)))
        elif any(imap.get(x) != i for i, x in enumerate(lst)):
            bad.append("%s 下标表与列表不符" % name)
    timed = [nid for _t, nid in ix.by_time]
    sess_sets = {k: set(v) for k, v in ix.by_session.items()}
    layer_sets = {k: set(v) for k, v in ix.by_layer.items()}
    union = set(timed) | set(ix.nonfinite) | set(ix.untimed)
    if len(timed) != len(set(timed)) or len(set(ix.nonfinite)) != len(ix.nonfinite) \
            or len(set(ix.untimed)) != len(ix.untimed):
        bad.append("by_time/nonfinite/untimed 有重复 id")
    if union != ids:
        bad.append("by_time ∪ nonfinite ∪ untimed 与快照键集不等（多 %d / 缺 %d）"
                   % (len(union - ids), len(ids - union)))
    if [t for t, _ in ix.by_time] != sorted(t for t, _ in ix.by_time):
        bad.append("by_time 非升序")
    for nid in ids:
        e = nodes.get(nid)
        sid, layer, bucket, _t0 = ix.cls.get(nid, (None, None, None, None))
        if sid != _hashable((e or {}).get("session")):
            bad.append("%s 的 by_session 分类与条目不符" % nid)
        if layer != _hashable((e or {}).get("layer")):
            bad.append("%s 的 by_layer 分类与条目不符" % nid)
        t = time_of(e)
        want = 0 if (t is not None and math.isfinite(t)) else (
            1 if t is not None else 2)
        if bucket != want:
            bad.append("%s 的 by_time 分类与条目不符（t=%r）" % (nid, t))
        # 「划分」不只要求并集相等，还要求 id 落在**其分类键对应的桶**里——
        # 否则分桶键取错字段（如 by_layer 按 session 建）时并集仍相等、静默漏判。
        if nid not in sess_sets.get(sid, ()):
            bad.append("%s 不在其分类对应的 by_session 桶里" % nid)
        if nid not in layer_sets.get(layer, ()):
            bad.append("%s 不在其分类对应的 by_layer 桶里" % nid)
        if bucket == 0 and nid not in timed:
            bad.append("%s 应在 by_time 而不在" % nid)
        if bucket == 1 and nid not in ix.nonfinite:
            bad.append("%s 应在 nonfinite 而不在" % nid)
        if bucket == 2 and nid not in ix.untimed:
            bad.append("%s 应在 untimed 而不在" % nid)
    return bad


class StgIndex:
    """快照的结构倒排（三张表 + 物理位序 + 每节点分类记录）。

    维护纪律：增删只经 `add` / `remove`（写侧单点），取数只经 `subset`（读侧单点）。
    #157 的 session/layer/untimed/nonfinite 桶继续使用下标表与 swap-pop。
    时间对改为平方根有序块：局部挪移与块目录挪移均有界，消除逐次整表
    删除的 O(N²) 批量代价；区间双端包含与物理序回排保持。
    `cls[nid] = (sid, layer, bucket, t)` 是**增量摘除**的依据（不必回扫桶猜分类）；
    任一步异常 ⇒ `broken = True`（读侧据此回退全量并重建，绝不带着半张表取数）。
    """

    def __init__(self, index_obj):
        self.index_obj = index_obj      # 强引用：读侧按 `is` 判代际（防 id 复用）
        self.by_session = {}
        self.by_layer = {}
        self.by_time = _TimeBlocks()
        # Only non-point intervals need the second endpoint. Point-only stores
        # keep their existing range lookup; long intervals cannot be reduced to
        # their start timestamp when the reader asks for overlap/containment.
        self.interval_starts = {}
        self.by_end = _TimeBlocks(lower=self._interval_start)
        self.interval_ends = {}
        self.uncertain_ends = set()
        self.untimed = []
        self.nonfinite = []
        self.pos = {}
        self.cls = {}
        # #157：桶内**下标表**（与四个桶列表一一对应）——使 _unclassify 的摘除
        # 从 list.remove 的 O(桶长) 降到 swap-pop 的 O(1)。代价：swap-pop 会打乱
        # 桶内顺序（原先恰好是物理序），故 subset 出口统一按 pos 回排，把既有
        # 「索引物理序」契约在读侧**单点**保住（见 subset 的出口注释）。
        self.ix_session = {}        # sid   -> {nid: 桶内下标}
        self.ix_layer = {}          # layer -> {nid: 桶内下标}
        self.ix_untimed = {}        # nid   -> untimed 内下标
        self.ix_nonfinite = {}      # nid   -> nonfinite 内下标
        self.broken = False
        self._next_pos = 0

    # 生效条件：nid 已在 pos 中时先摘旧分类（**位序不变**——与 dict 原地覆写保序同语义），否则分配下一个位序；随后按 entry 的 session/layer/时间重新分类一次（同键即幂等）；任一步异常置 broken=True（读侧回退重建）。
    def add(self, nid, entry):
        """增量增/改：与 `dict.__setitem__` 同序语义（已有键保位序、新键落尾）。"""
        try:
            if nid in self.pos:
                self._unclassify(nid)       # 位序保留（dict 覆写不移动）
            else:
                self.pos[nid] = self._next_pos
                self._next_pos += 1
            self._classify(nid, entry)
        except Exception:                   # noqa: BLE001  一致性存疑即标记，读侧回退
            self.broken = True

    # 生效条件：nid 不在 pos 中时无操作；在则摘分类并 pop 位序（位序**不回收**——后续新键恒得更大位序，与 dict 删后新增落尾一致）；任一步异常置 broken=True。
    def remove(self, nid):
        """增量删（不回收位序：新键恒落尾，与 dict 删除/追加语义同构）。"""
        try:
            if nid not in self.pos:
                return
            self._unclassify(nid)
            self.pos.pop(nid, None)
        except Exception:                   # noqa: BLE001
            self.broken = True

    # 生效条件：lst 为桶列表、imap 为「nid -> 桶内下标」表、nid 不在 lst 中；恒把 nid 追加到尾部并登记其下标（len-1），返回 None。
    @staticmethod
    def _push(lst, imap, nid):
        lst.append(nid)
        imap[nid] = len(lst) - 1

    # 生效条件：lst 为桶列表、imap 为对应下标表、nid 必在 imap 中；以 swap-pop 摘除该 nid——nid 不在末位时把末位元素搬进空洞并改其下标，在末位时直接 pop；恒返回 None。（O(1)：只动一个元素 + 两次字典写。）
    @staticmethod
    def _swap_pop(lst, imap, nid):
        i = imap.pop(nid)
        last = lst[-1]
        if last != nid:                 # 不在末位：末位搬进空洞、改其下标
            lst[i] = last
            imap[last] = i
        lst.pop()

    def _classify(self, nid, entry):
        e = entry if isinstance(entry, dict) else {}
        sid, layer = _hashable(e.get("session")), _hashable(e.get("layer"))
        t = time_of(e)
        self._push(self.by_session.setdefault(sid, []),
                   self.ix_session.setdefault(sid, {}), nid)
        self._push(self.by_layer.setdefault(layer, []),
                   self.ix_layer.setdefault(layer, {}), nid)
        if t is None:
            bucket = 2
            self._push(self.untimed, self.ix_untimed, nid)
        elif math.isfinite(t):
            bucket = 0
            self.by_time.add((t, nid))
            _s, end = trust.time_window_of(e, "observed", _allow_nonfinite=True)   # v0.9.0：与 :216 同口径，nan/inf 终点进 uncertain_ends
            if not math.isfinite(end):
                self.uncertain_ends.add(nid)
            elif end != t:
                self.interval_ends[nid] = end
                self.interval_starts[nid] = t
                self.by_end.add((end, nid))
        else:
            bucket = 1                  # NaN/±inf：见模块 docstring「为什么单列」
            self._push(self.nonfinite, self.ix_nonfinite, nid)
        self.cls[nid] = (sid, layer, bucket, t)

    # 生效条件：nid 必在 cls 中；按分类把 nid 从其所在桶以 swap-pop（O(1)）摘除并同步下标表——桶空则连桶键一并删除；bucket==0 走有序块精确键删除（局部搬移，规模变化时摊还压实）；任一步异常抛给上层置 broken；恒返回 None。
    def _unclassify(self, nid):
        sid, layer, bucket, t = self.cls.pop(nid)
        end = self.interval_ends.pop(nid, None)
        if end is not None:
            self.by_end.remove((end, nid))
            self.interval_starts.pop(nid, None)
        self.uncertain_ends.discard(nid)
        self._swap_pop(self.by_session[sid], self.ix_session[sid], nid)
        if not self.by_session[sid]:    # 空桶不保留（表规模读数如实）
            self.by_session.pop(sid, None)
            self.ix_session.pop(sid, None)
        self._swap_pop(self.by_layer[layer], self.ix_layer[layer], nid)
        if not self.by_layer[layer]:
            self.by_layer.pop(layer, None)
            self.ix_layer.pop(layer, None)
        if bucket == 0:
            # 精确键删除；不存在即抛错并使上层标记 broken。
            # 只挪动当前块，空块/小块合并与规模压实由时间容器维护。
            self.by_time.remove((t, nid))
        elif bucket == 1:
            self._swap_pop(self.nonfinite, self.ix_nonfinite, nid)
        else:
            self._swap_pop(self.untimed, self.ix_untimed, nid)

    # 生效条件：lo <= hi 时返回 t ∈ [lo, hi] 的 id 列表（**时间序**，调用方按 pos 回排）；lo > hi 返回空列表（区间为空——调用方在 inverted 查询上先回退，见 stg 侧）。
    def range_ids(self, lo, hi):
        """`by_time` 区间截取（二分）；返回时间序 id 列表。"""
        return self.by_time.range_ids(lo, hi)

    def _interval_start(self, pair):
        return self.interval_starts[pair[1]]

    def overlap_ids(self, lo, hi):
        """Conservative interval-overlap candidates, never just start-in-window.

        Starts inside [lo, hi] are already served by by_time. An additional hit
        must start before lo and end at/after lo. Non-finite endpoints remain a
        conservative superset for stg.time_relation's existing exact decision.
        """
        if lo > hi:
            return []
        ids = set(self.range_ids(lo, hi))
        if self.interval_ends:
            ids.update(self.by_end.crossing_ids(lo))
        ids.update(self.uncertain_ends)
        return list(ids)

    # 生效条件：session/layer 为 MISSING 表示该维不参与（**注意 None 是合法维值**，不表示缺省），time_range 为 None 表示时间维不参与、否则为 (lo, hi)；无任何参与维时返回 (None, ())；否则返回 (候选 id 列表（**索引物理序**）, 实际服务的维名元组)——任一维在表中无键即得空列表（与基线等值比较同语义，非回退）。
    # 生效条件：ids 为可迭代 nid（每个 nid 均应在 self.pos 中，否则 KeyError 抛给上层置 broken）；返回按**物理位序**（pos）升序的**新列表**。为什么出口统一回排（#157）：桶表改为 swap-pop 后不再是物理序，而 subset 的对外契约仍是「索引物理序」——该契约在**读侧单点**（此处）承担 O(k log k)，写侧换来 O(1) 摘除。
    def _in_pos_order(self, ids):
        return sorted(ids, key=self.pos.__getitem__)

    def subset(self, session=MISSING, layer=MISSING, time_range=None):
        """按维直取子集；返回 (ids | None, dims)。"""
        dims, srcs = [], []
        if session is not MISSING:
            dims.append("session")
            srcs.append(self.by_session.get(session, []))
        if layer is not MISSING:
            dims.append("layer")
            srcs.append(self.by_layer.get(layer, []))
        if time_range is not None:
            dims.append("time")
            lo, hi = time_range
            # nonfinite 是保守超集（NaN 在基线上会命中时间窗，见模块 docstring）
            srcs.append(self.overlap_ids(lo, hi) + list(self.nonfinite))
        if not dims:
            return None, ()
        if len(srcs) > 1:
            # 交集：以**最短表**驱动（成员判定用集合，不看序），结果统一回排。
            k = min(range(len(srcs)), key=lambda i: len(srcs[i]))
            driver = srcs[k]
            others = [set(srcs[i]) for i in range(len(srcs)) if i != k]
            out = [nid for nid in driver if all(nid in o for o in others)]
            return self._in_pos_order(out), tuple(dims)
        return self._in_pos_order(srcs[0]), tuple(dims)

    # 生效条件：恒返回表规模读数 dict——nodes=pos 条数、sessions/layers=两张表的**非空桶**数、timed=by_time 条数、untimed/nonfinite=两表条数；只读、无副作用。
    def size(self):
        """表规模读数（meta 用）。"""
        return {"nodes": len(self.pos), "sessions": len(self.by_session),
                "layers": len(self.by_layer), "timed": len(self.by_time),
                "untimed": len(self.untimed), "nonfinite": len(self.nonfinite)}
