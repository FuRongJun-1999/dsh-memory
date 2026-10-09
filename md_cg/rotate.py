# -*- coding: utf-8 -*-
"""分片日志轮转·参数化共享件（有界性的来源）。

背景（第 4 条取证，2026-09-16）：审计日志无上界增长——单文件形态让任何「读它」
的操作随运行时长线性劣化。上一轮把体检读数降为 O(1) 元数据口径（`_log_scale`），
只让「指标与代价错配」不再显形；**有界性的来源是轮转**：单文件 ≤ rotate_bytes、
分片数 ≤ keep_shards ⇒ 单片读取代价与总量都有上界。

本模块是轮转机制**唯一实现点**（A2，2026-10-10 设计者裁定）：`mdcos` 的审计轮转
（`_audit.jsonl`）与 `crypto.audit`（`_crypto.jsonl`）此前各自有无/有一份，现统一
改调 `Rotator`。参数化面：目录 + 基名 + 归档目录 + 索引名 + 阈值 + 保留数 + 探测
节流 + 计数口径（`counter` / `scale_reader`）+ 自述记录形状（`mark_factory`）+ 时钟
（`clock`，取证/守卫用）。

设计边界（诚实面）
------------------
· 分片内容与轮转前**逐行一致**（`publish` = rename，不动一个字节）；
· 并发由 `FileLock` + 「rename 前复检大小 / 失败即返回 None」兜住：抢输者不重复
  切分，也不丢记录；
· 保留策略只淘汰**分片**，淘汰名单写进自述记录（不静默丢证据）；
· 超大历史分片在轮转/体检路径上**只读量级**（`scale_reader`），不付 O(n) 全量解析
  ——「一次调用堵死通道」不在轮转路径上复现。
"""
from __future__ import annotations

import json
import os
import time

from .fsutil import (FileLock, append_jsonl, atomic_write, count_jsonl,
                     publish)


# 生效条件：path 为日志路径、count_max_bytes 为规模阈值、est_sample 为尾部采样字节数、counter 为行数计数器（缺省 count_jsonl）时，先 os.stat；OSError 返回 {'bytes':0,'mtime':None,'events':0,'exact':True}；size 不超过 count_max_bytes 时返回 counter(path) 的精确条数与 exact=True；否则读末尾 est_sample 字节估算 events、exact=False 并附 note（不触发任何全量计数）。
def log_scale(path, count_max_bytes=64 << 20, est_sample=256 << 10,
              counter=None):
    """日志量级读数（O(1)）：以元数据为主，条数只在与规模相称时才精确。"""
    counter = counter or count_jsonl
    try:
        st = os.stat(path)
    except OSError:
        return {"bytes": 0, "mtime": None, "events": 0, "exact": True}
    size = st.st_size
    out = {"bytes": size, "mtime": st.st_mtime}
    if size <= count_max_bytes:
        out.update({"events": counter(path), "exact": True})
        return out
    est = None
    try:
        with open(path, "rb") as f:
            f.seek(max(0, size - est_sample))
            tail = f.read()
        lines = [ln for ln in tail.split(b"\n") if ln.strip()]
        if lines:
            est = int(size / (len(tail) / float(len(lines))))
    except OSError:
        pass
    out.update({
        "events": est, "exact": False,
        "note": ("超过 %.0f MB 不给全量精确计数（O(n) 磁盘 IO 与量级体检不匹配）；"
                 "events 为尾部 %d KB 采样的估算值"
                 % (count_max_bytes / 1048576.0, est_sample >> 10))})
    return out


# 生效条件：注入的 clock 为 None 时用 lambda 延迟解析本模块 time（守卫冻结时钟可 patch）；注入时原样使用。
def _default_clock():
    return lambda: time.time()


# 生效条件：以 root/basename/archive_name 及可选阈值与回调构造实例；active/archive/lock 路径由 root 与基名拼接，_index 缓存与 writes 计数初值为 None/0；不读盘、不建目录、不抛异常。
class Rotator:
    """参数化分片轮转器：一次实现，审计面与 crypto 面共用。

    · `basename`   —— 活动文件基名（`_audit` / `_crypto`）⇒ 活动文件
      `<root>/<basename>.jsonl`、分片 `<archive>/<basename>.<6位序号>.jsonl`。
    · `archive_name` —— 归档目录名（`_audit_archive` / `_crypto_archive`）。
    · `counter`    —— 精确行数计数（默认 `fsutil.count_jsonl`，流式不物化）。
    · `scale_reader` —— 超大分片的量级读数（默认本模块 `log_scale`）；mdcos
      传自身 `_log_scale` 以保持既有读数口径逐位不变。
    · `mark_factory(name, size, events, pruned, reason)` —— 轮转自述记录
      （形状随消费方协议；返回 None 则不留痕，调用方自担）。
    · `clock`      —— 时间源（默认本模块 `time.time`）。
    """

# 生效条件：root、basename、archive_name 为必填；index_name/lock_name 缺省 "_index.json" 与 basename+".rotate.lock"；rotate_bytes/keep_shards/probe_every/count_max_bytes 缺省 64<<20/8/32/64<<20；counter/scale_reader/mark_factory/clock 缺省见类文档；随后把路径与回调存入实例，_index=None、writes=0。
    def __init__(self, root, basename, archive_name, index_name="_index.json",
                 lock_name=None, rotate_bytes=64 << 20, keep_shards=8,
                 probe_every=32, count_max_bytes=64 << 20,
                 counter=None, scale_reader=None, mark_factory=None,
                 clock=None):
        self.root = root
        self.basename = basename
        self.active = os.path.join(root, basename + ".jsonl")
        self.archive = os.path.join(root, archive_name)
        self.index_name = index_name
        self.lock_path = os.path.join(root, lock_name or
                                      (basename + ".rotate.lock"))
        self.rotate_bytes = rotate_bytes
        self.keep_shards = keep_shards
        self.probe_every = probe_every
        self.count_max_bytes = count_max_bytes
        self._counter = counter
        self._scale_reader = scale_reader
        self._mark = mark_factory
        self._clock = clock if clock is not None else _default_clock()
        self._index = None
        self.writes = 0

# 生效条件：无入参，返回 self._clock() 的结果（默认 time.time()）。
    def _now(self):
        return self._clock()

# 生效条件：archive 可被 os.listdir 列出时返回其中以 "<basename>." 开头且以 ".jsonl" 结尾的名字升序列表；listdir 抛 OSError 时返回 []。
    def shards(self):
        """归档分片名，序号零填充 ⇒ 字典序 == 时间序。"""
        try:
            names = os.listdir(self.archive)
        except OSError:
            return []
        prefix = self.basename + "."
        return sorted(n for n in names
                      if n.startswith(prefix) and n.endswith(".jsonl"))

# 生效条件：self._index 为 None 时尝试读取 archive 中 index_name 并过滤 value 为 dict，读取失败或数据非 dict 时为空字典，随后缓存并返回；非 None 时不重读直接返回。
    def load_index(self) -> dict:
        if self._index is None:
            idx = {}
            try:
                with open(os.path.join(self.archive, self.index_name),
                          "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    idx = {k: v for k, v in data.items() if isinstance(v, dict)}
            except (OSError, ValueError):
                idx = {}                       # 索引缺失/损坏 → 空起步，自愈补数
            self._index = idx
        return self._index

# 生效条件：idx 传入时尝试创建 archive 并把 idx 的 JSON（ensure_ascii=False, indent=1, sort_keys=True）原子写入 index_name；OSError 被吞掉；最后把 self._index 设为 idx。
    def save_index(self, idx: dict):
        try:
            os.makedirs(self.archive, exist_ok=True)
            atomic_write(os.path.join(self.archive, self.index_name),
                         json.dumps(idx, ensure_ascii=False, indent=1,
                                    sort_keys=True))
        except OSError:
            pass
        self._index = idx

# 生效条件：path 与 size 传入时，size 为 None 则先 getsize（OSError 返回 bytes/events 0 exact True）；size <= count_max_bytes 时返回 _counter(path) 精确条数 exact True；超过时返回 _scale_reader(path) 的事件数 exact False。
    def count_shard(self, path, size: int = None) -> dict:
        """分片条数读数：有界分片给精确值，超大历史分片只给量级。"""
        if size is None:
            try:
                size = os.path.getsize(path)
            except OSError:
                return {"bytes": 0, "events": 0, "exact": True}
        if size <= self.count_max_bytes:
            return {"bytes": size,
                    "events": (self._counter or count_jsonl)(path),
                    "exact": True}
        s = self._scale(path)
        return {"bytes": size, "events": s["events"], "exact": False}

# 生效条件：无入参，按 self._scale_reader（缺省本模块 log_scale，count_max_bytes 透传）读 path 的量级，返回其 dict。
    def _scale(self, path):
        if self._scale_reader is not None:
            return self._scale_reader(path)
        return log_scale(path, count_max_bytes=self.count_max_bytes,
                         counter=self._counter)

# 生效条件：在已用 root 构造的实例上遍历 shards()，对 "<basename>.<n>.jsonl" 中 int(n) 成功者取最大值 top（解析失败 continue、无可解析项 top=0），返回 top+1。
    def next_seq(self) -> int:
        top = 0
        n_from = len(self.basename) + 1
        for n in self.shards():
            try:
                top = max(top, int(n[n_from:-len(".jsonl")]))
            except ValueError:
                continue
        return top + 1

# 生效条件：keep_shards > 0 且分片数超过该值时，gone=shards[:-keep] 逐个尝试 os.remove、成功则从索引 pop（OSError continue），有 gone 才保存索引并返回 gone；keep<=0 或 gone 为空时返回 []。
    def prune(self):
        """保留最近 keep_shards 个分片、淘汰更旧的（≤0 表示不淘汰）。"""
        keep = self.keep_shards
        if keep <= 0:
            return []
        shards = self.shards()
        gone = shards[:-keep] if len(shards) > keep else []
        if not gone:
            return []
        idx = self.load_index()
        for n in gone:
            try:
                os.remove(os.path.join(self.archive, n))
            except OSError:
                continue                       # 删不掉就留着：不假装已淘汰
            idx.pop(n, None)
        self.save_index(idx)
        return gone

# 生效条件：rotate_bytes>0 且 self.writes 自增后能被 probe_every 整除，且 active 的 getsize 不小于 rotate_bytes 时调用 rotate() 并返回其结果；rotate_bytes<=0、未到探测间隔、getsize 不足或 OSError 时返回 None。
    def maybe_rotate(self):
        """写前闸门：活动日志达阈值即切分（把 stat 摊到 1/probe_every）。"""
        if self.rotate_bytes <= 0:
            return None
        self.writes = (self.writes or 0) + 1
        if self.writes % self.probe_every:
            return None
        try:
            if os.path.getsize(self.active) < self.rotate_bytes:
                return None
        except OSError:
            return None
        return self.rotate()

# 生效条件：reason（默认 "size"）传入时，在 FileLock(lock_path) 下若 active 的 size >= rotate_bytes 则 publish 为 "<basename>.<6位序号>.jsonl" 归档并更新索引/剪枝/自述留痕后返回 {"shard","bytes","events","pruned"}；size 不足、getsize OSError 或 publish 失败时返回 None；成功后 writes 归 0。
    def rotate(self, reason: str = "size"):
        """把活动日志切分为归档分片（publish = rename 原子，不重写一个字节）。"""
        with FileLock(self.lock_path, timeout=5.0):
            try:
                size = os.path.getsize(self.active)
            except OSError:
                return None
            if size < self.rotate_bytes:
                return None                    # 已被并发写者轮转
            os.makedirs(self.archive, exist_ok=True)
            name = "%s.%06d.jsonl" % (self.basename, self.next_seq())
            dst = os.path.join(self.archive, name)
            try:
                publish(self.active, dst)      # Windows 短重试：AV 短锁不误判抢输
            except OSError:
                return None                    # 抢输（文件已被移走）→ 让位，不报错
            scale = self.count_shard(dst, size)   # 分档：有界扫描 / 只读量级
            events = scale["events"]
            idx = self.load_index()
            idx[name] = {"bytes": size, "events": events, "exact": scale["exact"],
                         "t": round(self._now(), 3), "reason": reason}
            self.save_index(idx)
            pruned = self.prune()
            self.writes = 0
            try:                               # 自述留痕：轮转本身可审计
                mark = (self._mark(name, size, events, pruned, reason)
                        if self._mark is not None else None)
                if mark is not None:
                    append_jsonl(self.active, mark)
            except OSError:
                pass
            return {"shard": name, "bytes": size, "events": events,
                    "pruned": pruned}

# 生效条件：以 _scale(active) 取活动读数为 active，对磁盘现有分片 present 中未登记者按 count_shard 采纳进 idx（OSError continue，有采纳才写回索引），返回 active 并附 shards/shard_bytes/shard_events（均只统计 k in present）/oversized（非 exact 分片数）/total_bytes/total_events（active["events"] 为 None 时取 None）/total_exact/rotate_bytes/keep_shards。
    def scale(self) -> dict:
        """日志面量级读数（O(1) 稳态）：活动文件实时读数 + 归档分片索引缓存。"""
        active = self._scale(self.active)
        present = self.shards()
        idx = self.load_index()
        healed = False
        for n in present:
            if n in idx:
                continue
            p = os.path.join(self.archive, n)
            try:
                sc = self.count_shard(p)       # 分档：有界扫描 / 只读量级
                idx[n] = {"bytes": sc["bytes"], "events": sc["events"],
                          "exact": sc["exact"], "t": round(self._now(), 3),
                          "reason": "adopted"}
                healed = True
            except OSError:
                continue
        if healed:
            self.save_index(idx)
        shard_bytes = sum(int(v.get("bytes") or 0)
                          for k, v in idx.items() if k in present)
        shard_events = sum(int(v.get("events") or 0)
                           for k, v in idx.items() if k in present)
        oversized = sum(1 for n in present
                        if not idx.get(n, {}).get("exact", True))
        out = dict(active)
        out.update({
            "shards": len(present),
            "shard_bytes": shard_bytes,
            "shard_events": shard_events,
            "oversized": oversized,        # 非精确分片数（历史遗留超大文件）
            "total_bytes": active["bytes"] + shard_bytes,
            "total_events": (active["events"] + shard_events
                             if active["events"] is not None else None),
            "total_exact": bool(active["exact"]) and oversized == 0,
            "rotate_bytes": self.rotate_bytes,
            "keep_shards": self.keep_shards,
        })
        return out