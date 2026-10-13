# -*- coding: utf-8 -*-
"""md_cg · 冷路径异步深度验证队列

【为什么】写入路径中的一跳同步传播（_after_trust → mark_dependents）
只做「标记存疑」——它不验证下游是否真的被影响。真正的深度验证
需要：(1) 重跑 judge_qualification 看条件是否仍命中；
(2) 检查依赖链上的验证态是否级联失效。

这些操作可重可慢，不该阻塞写入路径。故异步入队，后台消费。

【设计】
  - enqueue(node_id, action, **kw)：入队异步验证任务
  - 后台线程消费队列，调 trust.set_state + judge_ranking
  - 队列落盘 _coldverify.jsonl（崩溃恢复）
  - 默认不启动后台线程（opt-in：start_worker()）
  - 也可同步消费（drain()，用于测试）
  - enqueue 走**追加**快路径（FileLock + append_jsonl）：追加不改写、不截断，
    物理上抹不掉别人已落的条目；drain/clear 走**读改写合并**（FileLock +
    atomic_write）并落 `_done` 墓碑 —— 多实例共用同一个 _coldverify.jsonl
    （attach() 每个 cg 实例各建一个）时不再互相抹掉条目（见 _persist 说明）

【边界】
  - 不阻塞写入路径（_after_trust 只 enqueue 不等结果）
  - 后台线程异常只记日志不抛（永不拖垮主进程）
  - 队列文件可选（无文件时纯内存，适合测试）

零第三方依赖（D-005）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque

from .fsutil import FileLock, atomic_write

#: 队列文件名
QUEUE_FILE = "_coldverify.jsonl"
#: 后台线程轮询间隔（秒）
POLL_INTERVAL = 2.0
#: 单次批处理上限
BATCH_LIMIT = 10
#: 消费墓碑保留期（秒）——墓碑只需覆盖「他实例内存里仍持有该任务」的窗口
TOMBSTONE_TTL = 3600.0
#: 消费墓碑条数上限（超出按最新保留），避免队列文件被墓碑撑大
TOMBSTONE_MAX = 4096

_VALID_ACTIONS = {"reverify", "propagate_depth", "patrol_check"}


class ColdVerifyQueue:
    """冷路径异步深度验证队列。

    线程安全：enqueue/drain/status 可跨线程调用。
    """

    def __init__(self, root=None):
        self._root = root
        self._queue: deque = deque()
        self._lock = threading.Lock()
        self._worker = None
        self._stop = threading.Event()
        self._stats = {"enqueued": 0, "processed": 0, "errors": 0,
                       "skipped": 0,
                       #: 落盘失败 / 被 fail-closed 跳过的次数：追加与压实失败
                       #: 此前是纯静默（except 直接 pass），运维看不到「内存里
                       #: 有、盘上没有」的窗口。见 _append_task/_persist。
                       "persist_failed": 0}
        self._queue_path = (os.path.join(root, QUEUE_FILE)
                             if root else None)
        #: 已消费任务的墓碑（任务键 → 落碑时刻）。用于阻止**另一实例**内存里
        #: 仍持有的同一条任务在它下次 _persist 时被写回盘上（重放）。
        self._tombstones: dict = {}
        #: 上一次 _read_disk 是否**读到一半失败**（拿到的只是残缺集合）。
        #: _persist 据此跳过本次落盘（fail-closed）：用残缺集合合并再覆写，
        #: 会抹掉「没读到」的那些条目。
        self._read_incomplete = False
        self._load_persisted()

    @staticmethod
    def _task_key(task) -> str:
        """任务身份键：整条任务的正则化 JSON（同一任务在任何实例上同键）。"""
        return json.dumps(task, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))

    def _read_disk(self, *, count_skipped=True):
        """读盘上队列文件，返回 (tasks, tombstones)。

        **加载路径与入口同白名单**（2026-09-20 v15-1 姊妹项）：`enqueue()` 用
        `_VALID_ACTIONS` 拒收未知 action，加载路径此前却直接 append——队列文件里
        出现任意字符串都会在 `drain` 时交给 `_process`，落到 `unknown_action`
        分支（或执行任意已知分支）。「入口校验、加载不校验」是不对称的，而这里
        的数据来自磁盘（可能被旧版本或手工编辑写坏）。故按同一白名单拒收并
        计入 `skipped`，不静默放行。

        本函数是**唯一**的解析点：`_load_persisted()`（构造期恢复）与
        `_persist()`（写前合并）都走它，避免「恢复一套口径、合并另一套口径」。
        `count_skipped=False` 供 _persist 用：写前合并不是一次新的加载，
        同一批非法行不该被反复计入。
        """
        tasks, tombs = [], {}
        self._read_incomplete = False
        if not self._queue_path or not os.path.exists(self._queue_path):
            return tasks, tombs
        try:
            # errors="replace"：与 fsutil.read_jsonl:216 同口径，**不能省**。
            # 追加写点被杀在多字节字符中间时，严格解码会在迭代中抛
            # UnicodeDecodeError（它不是 json.loads 的 ValueError，内层
            # except 抓不到），冒泡到下面的外层 except 后只返回坏字节之前的
            # 任务；随后 _persist 拿这份残缺集合合并再 atomic_write，坏字节
            # 之后的**好条目被永久抹掉**——不只是「丢掉那一行」。replace 把
            # 坏字节换成 U+FFFD，该行退化成一条普通坏行，只丢它自己。
            with open(self._queue_path, "r", encoding="utf-8",
                      errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        task = json.loads(line)
                    except ValueError:
                        # 逐行容错（与 fsutil.read_jsonl 同口径）：追加写点被杀
                        # 在中途会留下半截行，此前一个坏行会让整份队列「不恢复」
                        # （下面的 except 整体吞掉）——那等于丢掉全部未消费任务。
                        if count_skipped:
                            self._stats["skipped"] += 1
                        continue
                    if not isinstance(task, dict):
                        if count_skipped:
                            self._stats["skipped"] += 1
                        continue
                    if task.get("_done"):
                        # 墓碑行：`_load_persisted` 早就按 `_done` 跳过，但
                        # 此前**无人写墓碑**（该分支是死代码）——消费过的任务
                        # 于是会被他实例内存里的副本写回。见 _persist。
                        k = task.get("key")
                        if k:
                            try:
                                ts = float(task.get("_t") or 0.0)
                            except (TypeError, ValueError):
                                ts = 0.0
                            tombs[str(k)] = ts
                        continue
                    if task.get("action") not in _VALID_ACTIONS:
                        if count_skipped:
                            self._stats["skipped"] += 1   # 拒收：非法 action 不入队
                        continue
                    tasks.append(task)
        except Exception:                              # noqa: BLE001
            # 崩溃恢复容错：文件损坏就不恢复。但「读到一半失败」时已读到的
            # 部分只是残缺集合，写路径必须据此 fail-closed（见 _persist）。
            self._read_incomplete = True
        return tasks, tombs

    def _prune_tombstones(self, tombs, now=None) -> dict:
        """按 TTL 与条数上限收敛墓碑（超出窗口的墓碑不再有用）。"""
        now = time.time() if now is None else now
        keep = {k: t for k, t in (tombs or {}).items()
                if (now - float(t or 0.0)) <= TOMBSTONE_TTL}
        if len(keep) > TOMBSTONE_MAX:
            keep = dict(sorted(keep.items(), key=lambda kv: kv[1],
                               reverse=True)[:TOMBSTONE_MAX])
        return keep

    def _load_persisted(self):
        """从队列文件恢复未处理任务（崩溃恢复）。"""
        tasks, tombs = self._read_disk()
        self._tombstones = self._prune_tombstones(tombs)
        for task in tasks:
            if self._task_key(task) in self._tombstones:
                continue                      # 已消费：不恢复
            self._queue.append(task)

    def _persist(self):
        """持久化当前队列——**读改写合并**，不是全量覆写。

        病灶（本件修复）：原实现 `open(path, "w")` 直接覆写整个文件，而每个
        cg 实例（`attach()` 各建一个 ColdVerifyQueue）都持有自己的内存队列、
        都指向同一个 `_coldverify.jsonl` ⇒ 后写者的 _persist 把先写者刚落的
        条目整段抹掉，两边 rc=0、各自都报成功（实测两进程各入队一条，盘上
        只剩后者的那条，另一条无痕丢失）。

        修法：在 `FileLock` 下「读盘 → 合并（盘上未消费任务 ∪ 本实例内存）→
        `atomic_write` 落盘」，并对已消费任务落 `_done` 墓碑——否则他实例
        内存里那份已消费任务会被它自己的 _persist 写回（重放）。锁拿不到时
        `strict=True` 抛错即跳过本次落盘：宁可晚一拍（条目仍在内存里，下次
        再试），也不做无锁读改写把别人的条目覆盖掉。
        """
        if not self._queue_path:
            return
        try:
            with FileLock(self._queue_path, strict=True):
                disk_tasks, disk_tombs = self._read_disk(count_skipped=False)
                if self._read_incomplete:
                    # fail-closed：盘上内容没读全，合并后的集合会缺条目，
                    # 此刻覆写 = 把没读到的条目永久抹掉。宁可晚一拍（条目仍
                    # 在内存里，下次再试）。
                    self._stats["persist_failed"] += 1
                    return
                tombs = dict(disk_tombs)
                tombs.update(self._tombstones)
                self._tombstones = self._prune_tombstones(tombs)
                merged = {}
                for task in disk_tasks:
                    k = self._task_key(task)
                    if k not in self._tombstones:
                        merged[k] = task
                live = []
                for task in self._queue:
                    k = self._task_key(task)
                    if k in self._tombstones:
                        continue     # 他实例已消费：本实例内存这份也丢弃
                    merged[k] = task
                    live.append(task)
                if len(live) != len(self._queue):
                    self._queue = deque(live)
                lines = [json.dumps(t, ensure_ascii=False)
                         for t in merged.values()]
                lines += [json.dumps({"_done": True, "key": k, "_t": ts},
                                     ensure_ascii=False)
                          for k, ts in self._tombstones.items()]
                atomic_write(self._queue_path,
                             "".join(x + "\n" for x in lines))
        except Exception:                              # noqa: BLE001
            self._stats["persist_failed"] += 1  # 不静默：落盘失败可观测
            # 持久化失败不影响内存队列（条目仍在内存，下次 drain/clear 再试）

    def enqueue(self, node_id: str, action: str = "reverify", **kw):
        """入队异步验证任务。返回 task dict。"""
        if action not in _VALID_ACTIONS:
            raise ValueError(f"未知 action: {action}，合法: {_VALID_ACTIONS}")
        task = {
            "node_id": node_id,
            "action": action,
            "enqueued_at": time.time(),
            "kwargs": kw,
        }
        with self._lock:
            self._queue.append(task)
            self._stats["enqueued"] += 1
            self._append_task(task)
        return task

    def _append_task(self, task):
        """把一条任务**追加**到盘上（不改写、不截断）。

        追加而非全量覆写是本件修法的关键：追加物理上不可能抹掉别人已落的条目
        （改前实测两实例/两进程各入队一条，盘上只剩后者的那条）。O_APPEND 在
        Windows 上「定位 + 写入」非原子（fsutil.append_jsonl 的实测注释：
        6 进程 × 40 条每轮丢 ~1 条），故追加在 FileLock 下串行化；合并/压实
        仍走 _persist（drain/clear）。锁拿不到时跳过本次追加（条目仍在内存，
        下次 _persist 会补落），不做无锁追加。
        """
        if not self._queue_path:
            return
        # **每条记录前置一个换行**：上一个写者被杀在中途留下的半截行因此总被
        # 下一条记录的换行终止，不会被粘成「两条都解析不出来」的一行。这条
        # 写侧不变量替代了 fsutil.append_jsonl 的 ends_mid_line（后者要再
        # open/seek/read/close 一次文件；本机实测 1.9–6.8ms/次，读侧那 3 个
        # 系统调用实测 ~10ms/次，写入路径上的 enqueue 付不起）。空行由读侧跳过。
        line = ("\n" + json.dumps(task, ensure_ascii=False,
                                  separators=(",", ":")) + "\n")
        try:
            with FileLock(self._queue_path, strict=True):
                d = os.path.dirname(os.path.abspath(self._queue_path)) or "."
                os.makedirs(d, exist_ok=True)
                fd = os.open(self._queue_path,
                             os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
                try:
                    os.write(fd, line.encode("utf-8"))   # O_APPEND：写必在末尾
                finally:
                    os.close(fd)
        except Exception:                              # noqa: BLE001
            self._stats["persist_failed"] += 1  # 不静默：追加失败可观测
            # 追加失败不影响内存队列（条目仍在内存，下次 _persist 合并补落）

    def drain(self, cg, *, limit=BATCH_LIMIT, dry_run=False):
        """同步消费队列（用于测试/手动处理）。返回处理结果列表。

        issue #72（2026-10-09 DSH 端）：dry_run=True 时**只预演不消费**——
        不 popleft、不 _process、不落盘、不计数，只列出**将消费**的条目及其积压龄。
        注意本方法本就**不启常驻线程**（opt-in 语义见 :15），dry_run 只是把
        「想看看会发生什么」这条路也显式化。"""
        if dry_run:
            with self._lock:
                preview = list(self._queue)[:max(0, int(limit))]
            now = time.time()
            return {"dry_run": True,
                    "would_process": [
                        {"node_id": x.get("node_id"),
                         "action": x.get("action"),
                         "enqueued_at": x.get("enqueued_at"),
                         "age_s": round(now - float(x.get("enqueued_at") or 0), 1)}
                        for x in preview],
                    "queue_size": len(self._queue),
                    "limit": int(limit)}
        results = []
        with self._lock:
            batch = []
            for _ in range(min(limit, len(self._queue))):
                batch.append(self._queue.popleft())
        for task in batch:
            try:
                r = self._process(cg, task)
                results.append(r)
                self._stats["processed"] += 1
            except Exception as exc:                    # noqa: BLE001
                self._stats["errors"] += 1
                results.append({"node_id": task["node_id"],
                                 "action": task["action"],
                                 "error": str(exc),
                                 "ok": False})
        with self._lock:
            # 消费即落墓碑：本实例内存里已 pop，但他实例内存里可能还有同一份
            for task in batch:
                self._tombstones[self._task_key(task)] = time.time()
            self._persist()
        return results

    def _process(self, cg, task):
        """执行单个验证任务。"""
        from . import trust
        nid = task["node_id"]
        action = task["action"]
        kw = task.get("kwargs", {})

        if action == "reverify":
            # 重新验证单节点：重跑 judge_qualification
            node = cg.get(nid)
            if not node:
                self._stats["skipped"] += 1
                return {"node_id": nid, "action": action, "ok": True,
                        "skipped": "node_not_found"}
            fm = node.get("frontmatter") or {}
            old_state = trust.state_of(fm)
            # 只对非 unverified 节点做深度验证
            if old_state == "unverified":
                self._stats["skipped"] += 1
                return {"node_id": nid, "action": action, "ok": True,
                        "skipped": "unverified_no_action"}
            # 检查时效
            kind, _, _ = trust.validity(fm)
            want, why = None, ""
            if kind == "expired" and old_state != "expired":
                want, why = "expired", "冷路径：时效过期"
            elif kind == "not_yet":
                want, why = "unverified", "冷路径：尚未生效"
            if want is None:
                return {"node_id": nid, "action": action, "ok": True,
                        "old_state": old_state, "new_state": old_state,
                        "changed": False}
            # 迁移结果**必须检查**（2026-09-20 v14 缺陷 D 修复）：`trust.set_state`
            # 对非法迁移返回 ok=False（负路由不抛异常），旧实现丢弃返回值后一律
            # 上报 `ok=True + new_state=<请求值>` —— 恰好在本队列最该说话的两条
            # 迁移上（doubted→expired / verified→unverified，均为 TRANSITIONS
            # 明令拒绝的跳级）**说了假话**，且 stats.errors 恒 0 把它盖住。
            # trust 层做对了（拒绝非法迁移），队列层不得把它翻译成成功。
            r = trust.set_state(cg, nid, want, reason=why,
                                actor="coldverify", **kw)
            if not r.get("ok"):
                self._stats["errors"] += 1
                return {"node_id": nid, "action": action, "ok": False,
                        "old_state": old_state, "requested_state": want,
                        "error": "transition_rejected:%s" % r.get("error"),
                        "reason": r.get("reason") or "",
                        "detail": "非法迁移被 trust.TRANSITIONS 拒绝，状态未变"}
            return {"node_id": nid, "action": action, "ok": True,
                    "old_state": old_state, "new_state": want,
                    "changed": bool(r.get("changed"))}

        elif action == "propagate_depth":
            # 多跳深度传播
            r = trust.propagate(cg, apply=True, actor="coldverify",
                                **kw)
            # `ok` 由**内层结论**决定，不得硬编码（2026-09-20 v15-1 修复）：
            # `trust.propagate` 有失败态（异常路径返回 `ok=False, degraded=True`），
            # 旧写法一律上报 True。当前内层成功路径恒 ok=True，故本分支行为不变
            # ——但判据应由内层决定，而不是由「当前恰好没失败」决定。
            ok = bool(r.get("ok"))
            if not ok:
                self._stats["errors"] += 1
            return {"node_id": nid, "action": action, "ok": ok,
                    "propagation": r}

        elif action == "patrol_check":
            # 巡检式检查
            rep = trust.patrol(cg, **kw)
            # `ok` 由**内层结论**决定（2026-09-20 v15-1 修复，同 v14 缺陷 D 病类）：
            # `trust.patrol` 的返回是 `{"ok": not dangling, ...}`——**有真实失败态**
            # （存在悬空依赖即 ok=False）。旧写法 `{"ok": True, ...}` 把内层失败
            # 翻译成成功、`stats.errors` 恒 0，正是「队列层替内层说假话」。D 只修了
            # `reverify` 一支，本支与 `propagate_depth` 是同函数内的兄弟分支。
            ok = bool(rep.get("ok"))
            if not ok:
                self._stats["errors"] += 1
            return {"node_id": nid, "action": action, "ok": ok,
                    "patrol": rep}

        return {"node_id": nid, "action": action, "ok": False,
                "error": "unknown_action"}

    def start_worker(self, cg, *, poll_interval=POLL_INTERVAL):
        """启动后台消费线程。"""
        if self._worker and self._worker.is_alive():
            return self._worker
        self._stop.clear()

        def _run():
            while not self._stop.is_set():
                try:
                    if self._queue:
                        self.drain(cg, limit=BATCH_LIMIT)
                except Exception:                      # noqa: BLE001
                    self._stats["errors"] += 1
                self._stop.wait(poll_interval)

        self._worker = threading.Thread(target=_run, daemon=True,
                                        name="coldverify-worker")
        self._worker.start()
        return self._worker

    def stop_worker(self, timeout=5.0):
        """停止后台线程。"""
        self._stop.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=timeout)
        self._worker = None

    def status(self):
        """返回队列状态。"""
        with self._lock:
            return {
                "queue_size": len(self._queue),
                "stats": dict(self._stats),
                "worker_alive": (self._worker is not None
                                  and self._worker.is_alive()),
                # issue #72：积压龄（最久未消费条目的秒数）——让「积压无人管」
                # 不再是隐性状态；空队列为 None。
                "oldest_age_s": (
                    round(time.time() - min(float(x.get("enqueued_at") or 0)
                                            for x in self._queue), 1)
                    if self._queue else None),
                "queue_file": self._queue_path,
            }

    def clear(self):
        """清空队列（测试用）。盘上条目一并落墓碑，否则他实例下次 _persist
        合并时会把它们当「未消费」写回（清空只清本实例内存 = 假清空）。

        **边界（不宣称全局清空）**：只覆盖「本实例内存 ∪ 盘上可观察条目」。
        另一实例内存里因追加失败（见 @persist_failed@ 计数）尚未落盘的任务，
        在它自己后续 _persist 合并时仍会出现——那条任务确实已 enqueue 且未被
        消费，从它那一侧看写回是对的。要全局清空请在无其它活实例时执行；
        本方法主要给测试与单实例运维用。"""
        with self._lock:
            disk_tasks, _ = self._read_disk(count_skipped=False)
            now = time.time()
            for task in list(self._queue) + list(disk_tasks):
                self._tombstones[self._task_key(task)] = now
            self._queue.clear()
            self._persist()


#: 进程级默认实例
_DEFAULT = None


def default_queue(root=None):
    """进程级默认冷路径队列单例。"""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ColdVerifyQueue(root=root)
    return _DEFAULT


def attach(cg):
    """给 cg 实例挂冷路径队列（幂等）。"""
    if not hasattr(cg, "_coldverify") or cg._coldverify is None:
        cg._coldverify = ColdVerifyQueue(root=cg.root)
    return cg._coldverify


def get(cg):
    """取 cg 实例的冷路径队列（未挂返回 None）。"""
    return getattr(cg, "_coldverify", None)


def enqueue(cg, node_id: str, action: str = "reverify", **kw):
    """快捷入口：挂队列 + 入队。"""
    q = attach(cg)
    return q.enqueue(node_id, action, **kw)
