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

#: 队列文件名
QUEUE_FILE = "_coldverify.jsonl"
#: 后台线程轮询间隔（秒）
POLL_INTERVAL = 2.0
#: 单次批处理上限
BATCH_LIMIT = 10

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
                       "skipped": 0}
        self._queue_path = (os.path.join(root, QUEUE_FILE)
                             if root else None)
        self._load_persisted()

    def _load_persisted(self):
        """从队列文件恢复未处理任务（崩溃恢复）。"""
        if not self._queue_path or not os.path.exists(self._queue_path):
            return
        try:
            with open(self._queue_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    task = json.loads(line)
                    if not task.get("_done"):
                        self._queue.append(task)
        except Exception:                              # noqa: BLE001
            pass  # 崩溃恢复容错：文件损坏就不恢复

    def _persist(self):
        """持久化当前队列（全量覆写）。"""
        if not self._queue_path:
            return
        try:
            with open(self._queue_path, "w", encoding="utf-8") as f:
                for task in self._queue:
                    f.write(json.dumps(task, ensure_ascii=False) + "\n")
        except Exception:                              # noqa: BLE001
            pass  # 持久化失败不影响内存队列

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
            self._persist()
        return task

    def drain(self, cg, *, limit=BATCH_LIMIT):
        """同步消费队列（用于测试/手动处理）。返回处理结果列表。"""
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
            new_state = old_state
            if kind == "expired" and old_state != "expired":
                new_state = "expired"
                trust.set_state(cg, nid, "expired",
                                 reason="冷路径：时效过期",
                                 actor="coldverify", **kw)
            elif kind == "not_yet":
                new_state = "unverified"
                trust.set_state(cg, nid, "unverified",
                                reason="冷路径：尚未生效",
                                actor="coldverify", **kw)
            return {"node_id": nid, "action": action, "ok": True,
                    "old_state": old_state, "new_state": new_state}

        elif action == "propagate_depth":
            # 多跳深度传播
            r = trust.propagate(cg, apply=True, actor="coldverify",
                                **kw)
            return {"node_id": nid, "action": action, "ok": True,
                    "propagation": r}

        elif action == "patrol_check":
            # 巡检式检查
            rep = trust.patrol(cg, **kw)
            return {"node_id": nid, "action": action, "ok": True,
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
                "queue_file": self._queue_path,
            }

    def clear(self):
        """清空队列（测试用）。"""
        with self._lock:
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
