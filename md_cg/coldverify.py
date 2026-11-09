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
from collections import Counter, deque

from .fsutil import FileLock as _FileLock
from .fsutil import atomic_write as _atomic_write
from .fsutil import ends_mid_line as _ends_mid_line
from .fsutil import read_jsonl as _read_jsonl

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
        """从队列文件恢复未处理任务（崩溃恢复）。

        **加载路径与入口同白名单**（2026-09-20 v15-1 姊妹项）：`enqueue()` 用
        `_VALID_ACTIONS` 拒收未知 action，加载路径此前却直接 append——队列文件里
        出现任意字符串都会在 `drain` 时交给 `_process`，落到 `unknown_action`
        分支（或执行任意已知分支）。「入口校验、加载不校验」是不对称的，而这里
        的数据来自磁盘（可能被旧版本或手工编辑写坏）。故按同一白名单拒收并
        计入 `skipped`，不静默放行。

        issue #265：**逐行容错**。此前 `json.loads` 的异常由包住整个循环的
        `except` 捕获 ⇒ 上一个写者被杀死留下的半截行会让**整份队列都不恢复**
        （实测）。改为逐行捕获：坏行只丢它自己，后续行照常恢复。
        """
        if not self._queue_path or not os.path.exists(self._queue_path):
            return
        for task in _read_jsonl(self._queue_path):
            try:
                if task.get("_done"):
                    continue
                if task.get("action") not in _VALID_ACTIONS:
                    self._stats["skipped"] += 1   # 拒收：非法 action 不入队
                    continue
                self._queue.append(task)
            except Exception:                          # noqa: BLE001
                self._stats["skipped"] += 1

    def _append_persisted(self, task):
        """把**一条**任务追加到队列文件（issue #265）。

        此前 `enqueue` 调 `_persist()` 做全量覆写——写盘的是「本实例内存的
        快照」，跨实例没有任何互斥或合并。多实例共用同一 root 时（两个 MCP
        server 进程，或 server + CLI），后落盘者把先落盘者刚写的整段抹掉，
        两边都 rc=0、都报成功、**无痕丢失**（实测：两进程各自入队 →
        `disk_lines=1`）。

        追加在物理上抹不掉别人的条目。半截行（上一个写者被杀在中途）由
        `_ends_mid_line` 补一个换行处理，否则新记录会粘在那行上、两条都解析
        不出来。

        跨进程 FileLock：与 `_drop_persisted` 的读改写互斥——否则「追加」可能
        落在对方的「读」与「写回」之间而被覆盖。strict=False（best-effort）：
        入队在**写路径**上（`writepipe._after_trust` 每次写入都调），锁竞争失败
        时宁可让这次追加无锁落盘，也不能让异常打断写入（调用方已 try/except，
        但静默放行比抛更符合本模块「永不拖垮主进程」的边界）。
        """
        if not self._queue_path:
            return
        line = json.dumps(task, ensure_ascii=False) + "\n"
        try:
            with _FileLock(self._queue_path, strict=False):
                if _ends_mid_line(self._queue_path):
                    line = "\n" + line
                d = os.path.dirname(os.path.abspath(self._queue_path)) or "."
                os.makedirs(d, exist_ok=True)
                fd = os.open(self._queue_path,
                             os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
                try:
                    os.write(fd, line.encode("utf-8"))
                finally:
                    os.close(fd)
        except Exception:                              # noqa: BLE001
            pass  # 持久化失败不影响内存队列

    def _drop_persisted(self, consumed):
        """从队列文件删掉**本实例刚消费**的条目（issue #265）。

        读改写全程持跨进程 `FileLock(strict=True)` 并以 `atomic_write` 落盘
        （整文件替换：读者要么看到旧内容、要么看到新内容，永远看不到半截）。

        **只删自己消费的**：他实例刚追加的条目原样保留——这正是本件的病象
        （全量覆写会把它们抹掉）。匹配键取 `(node_id, action, enqueued_at)`，
        用 Counter 逐条扣减，故同键的重复入队也各删一条、不会多删别人的。

        `strict=True`：消费是**不能丢**的写（删错了等于把别人的任务抹掉，正是
        本件要修的），锁竞争失败时显式抛出让调用方重试，好过静默退化为无锁
        并发。异常由本方法的 `except` 收口——drain 不因落盘失败而崩。
        """
        if not self._queue_path or not consumed:
            return
        want = Counter((t.get("node_id"), t.get("action"), t.get("enqueued_at"))
                       for t in consumed)
        try:
            with _FileLock(self._queue_path, strict=True):
                if not os.path.exists(self._queue_path):
                    return
                kept = []
                for task in _read_jsonl(self._queue_path):
                    k = (task.get("node_id"), task.get("action"),
                         task.get("enqueued_at"))
                    if want.get(k, 0) > 0:
                        want[k] -= 1          # 本实例消费掉的：从盘上摘除
                        continue
                    if task.get("_done"):
                        continue              # 墓碑：已消费，不再入队
                    kept.append(task)
                _atomic_write(self._queue_path, "".join(
                    json.dumps(t, ensure_ascii=False) + "\n" for t in kept))
        except Exception:                              # noqa: BLE001
            pass  # 持久化失败不影响内存队列

    def _persist(self):
        """全量覆写当前队列。**仅供 clear() 的重置语义**（enqueue/drain 不再走它）。

        issue #265：全量覆写正是丢条目的根因，故入队改走 `_append_persisted`
        （追加）、消费改走 `_drop_persisted`（只删自己消费的）。本方法保留给
        `clear()` 的显式重置，并补上跨进程锁 + 原子替换。
        """
        if not self._queue_path:
            return
        try:
            with _FileLock(self._queue_path, strict=True):
                _atomic_write(self._queue_path, "".join(
                    json.dumps(task, ensure_ascii=False) + "\n"
                    for task in self._queue))
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
            # issue #265：追加而非全量覆写（后者会抹掉他实例刚写的条目）
            self._append_persisted(task)
        return task

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
        # issue #265：只从盘上摘除**本批消费掉**的条目——全量覆写会把他实例
        # 刚追加的条目一并抹掉（本件的病象）。
        self._drop_persisted(batch)
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
        """清空队列（测试用）。"""
        with self._lock:
            self._queue.clear()
            self._persist()

    def _requeue_failed(self, task, attempts):
        """把**消费失败**的任务放回队尾（issue #72：失败不得静默蒸发）。

        与 `enqueue` 同款落盘路径（追加 + 跨进程锁），但保留 `attempts` 计数
        （`_process` 不读该键，只透传 node_id/action/kwargs，故不污染执行面）。
        重试用尽由调用方（`controlled_drain`）决定丢弃并计入 dead_letter。
        """
        t = {
            "node_id": task.get("node_id"),
            "action": task.get("action"),
            "enqueued_at": time.time(),
            "kwargs": task.get("kwargs") or {},
            "attempts": int(attempts),
        }
        with self._lock:
            self._queue.append(t)
            self._stats["enqueued"] += 1
            self._append_persisted(t)
        return t


#: issue #72：受控消费的**单批硬上限**（与后台线程批大小同源，不另立第二套数）。
CONTROL_LIMIT_MAX = BATCH_LIMIT
#: issue #72：失败任务重试上限；超过即丢弃并计入 dead_letter（可见、不无限滞留）。
CONTROL_MAX_ATTEMPTS = 3


def controlled_drain(cg, *, limit=BATCH_LIMIT, dry_run=False, principal=None):
    """受控消费入口（issue #72）——权限、限量、审计三闸齐备的**显式**消费。

    背景：#72 报「队列仅可观察、无受控消费入口」（queue_size 119 / processed 0 /
    worker_alive false）。`drain()` 本身是同步消费，但它是库内方法：没有权限门、
    没有单批硬上限、没有审计，任何拿到 cg 的调用方都能全量消费且不留痕。
    本函数是**工具面可接线的单点入口**，不引入常驻线程（opt-in 语义不变）。

    三闸（缺一不可）：
      1. **权限**：调用方须 `can_admin`（显式 principal 优先，否则取 cg.principal）。
         未授权直接 `{"ok": False, "error": "forbidden"}`——**不返回队列内容**
         （连 node_id 都不给），故「未授权不能看到任务正文或触发消费」。
      2. **限量**：`0 <= limit <= CONTROL_LIMIT_MAX`，越界 fail-closed 返回
         `bad_limit`（不静默截断——截断会让调用方以为处理了 N 条）。
      3. **审计**：cg 有 `_audit` 时写一行聚合（dry_run/limit/processed/errors/
         requeued/dead_letter/queue_size/oldest_age_s），绝不记正文（payload-free）。

    失败处置：`ok=False` 的任务重新入队（attempts+1，最多 `CONTROL_MAX_ATTEMPTS`
    次），超过则丢弃并计入 `dead_letter`——「消费失败可见、可重试、不无限滞留」。
    成功的任务已由 drain 从内存与盘上摘除，重复运行不会重复状态迁移。

    返回体（成功）：
      {"ok", "dry_run", "limit", "processed", "errors": [...], "skipped",
       "requeued", "dead_letter", "results", "queue_size", "oldest_age_s",
       "worker_alive", "audit"}
    dry_run=True 时返回 `would_process`（node_id/action/age_s，无正文）且不消费、
    不落盘、不计数、不写审计（预演本身不是管理动作）。

    【功能名】coldverify 受控消费入口
    【生效条件】cg 的 principal.can_admin 为真且 limit 在 [0, CONTROL_LIMIT_MAX]；
      dry_run 亦须过同一权限闸（否则可借预演侧读队列组成）。
    【子功能】单批限量消费 / 预演 / 失败重入队与 dead-letter / 聚合审计。
    【执行】controlled_drain(cg, limit=N, dry_run=False, principal=None)
    【验证方式】md_cg/test_issue72_coldverify_controlled_drain.py（含 --mutate）。
    【不适用条件】不适用于后台常驻消费（那仍是 start_worker 的 opt-in 语义）；
      不改变 drain() 既有契约（本函数在它之上加闸，不改其行为）。
    """
    q = get(cg)
    if q is None:
        return {"ok": False, "error": "no_queue",
                "reason": "cg 未挂冷路径队列（先 coldverify.attach(cg)）"}
    p = principal if principal is not None else getattr(cg, "principal", None)
    if not getattr(p, "can_admin", False):
        return {"ok": False, "error": "forbidden",
                "reason": "受控消费需 can_admin（未授权调用不返回队列内容）"}
    try:
        lim = int(limit)
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad_limit", "reason": "limit 必须是整数"}
    if lim < 0 or lim > CONTROL_LIMIT_MAX:
        return {"ok": False, "error": "bad_limit",
                "reason": "limit 须在 [0, %d]（单批硬上限）" % CONTROL_LIMIT_MAX,
                "limit_max": CONTROL_LIMIT_MAX}
    st = q.status()
    if dry_run:
        # 预演不消费、不落盘、不计数、不审计（issue #72 验收：dry-run 不改队列）。
        return {"ok": True, "dry_run": True, "limit": lim,
                "would_process": q.drain(cg, limit=lim, dry_run=True)["would_process"],
                "queue_size": st["queue_size"],
                "oldest_age_s": st.get("oldest_age_s"),
                "worker_alive": st.get("worker_alive"),
                "audit": False}
    # 取本批原任务快照（失败项要按原 kwargs 重入队）——与 drain 同锁口径。
    with q._lock:
        batch = list(q._queue)[:lim]
    results = q.drain(cg, limit=lim)
    errs, requeued, dead = [], 0, 0
    for i, r in enumerate(results):
        if r.get("ok"):
            continue
        errs.append({"node_id": r.get("node_id"), "action": r.get("action"),
                     "error": r.get("error") or r.get("skipped") or "unknown"})
        src = batch[i] if i < len(batch) else None
        if src is None:
            dead += 1
            continue
        attempts = int(src.get("attempts") or 0) + 1
        if attempts > CONTROL_MAX_ATTEMPTS:
            dead += 1
            continue
        q._requeue_failed(src, attempts)
        requeued += 1
    st = q.status()
    audit_ok = False
    a = getattr(cg, "_audit", None)
    if a is not None:
        try:
            a("coldverify_drain", "", dry_run=False, limit=lim,
              processed=st["stats"].get("processed"), errors=len(errs),
              requeued=requeued, dead_letter=dead,
              queue_size=st["queue_size"], oldest_age_s=st.get("oldest_age_s"))
            audit_ok = True
        except Exception:                              # noqa: BLE001
            audit_ok = False          # 审计失败不阻断消费（best-effort，同 G8）
    return {"ok": True, "dry_run": False, "limit": lim,
            "processed": len(results) - len(errs),
            "errors": errs, "skipped": st["stats"].get("skipped"),
            "requeued": requeued, "dead_letter": dead,
            "results": results, "queue_size": st["queue_size"],
            "oldest_age_s": st.get("oldest_age_s"),
            "worker_alive": st.get("worker_alive"), "audit": audit_ok}


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
