# -*- coding: utf-8 -*-
r"""守卫 · coldverify 队列的跨实例合并（多实例共用 _coldverify.jsonl 不互相抹掉）。

# 功能名：冷路径队列落盘的跨实例合并
# 生效条件：两个及以上 ColdVerifyQueue 指向同一 root（attach() 每个 cg 实例
#           各建一个；同机多进程/多 MdCGOS 实例共用一个记忆库根时必然发生）
# 子功能：① enqueue 追加落盘（不改写/不截断，抹不掉他人条目）+ drain 读改写合并
#         ② 消费落 _done 墓碑（他实例内存里的同一份不再被写回）
#         ③ clear 真清空（盘上条目一并落墓碑）
#         ④ 落盘走 FileLock(strict=True) + atomic_write（无锁不写、不留半截）
#         ⑤ 解析单点 _read_disk 供恢复与合并共用（非法 action 只计一次 skipped）
#         ⑥ 锁拿不到时 fail-closed：enqueue 不抛、盘上逐字节不变、条目留内存待下次补落
#         ⑦ 墓碑按 TTL/上限收敛：过期墓碑不再挡恢复（宁可重放，不静默丢）
#         ⑧ 解析口径对照：坏行容忍与 fsutil.read_jsonl 同口径，非法 action 为有意加严
# 执行：python -X utf8 -m md_cg.test_coldverify_queue_merge [--mutate=clobber|ignore_tombstones|no_leading_newline|no_prune|append_swallow]
# 验证方式：真跑临时库（进程内两实例 + 两个活进程并发屏障），逐条断言盘上内容
# 不适用条件：无（不依赖网络、不依赖 rust 工具链、不依赖本地白箱库）

病灶（改前实测）：_persist() 用 open(path,"w") 全量覆写，且每个实例各持内存队列
⇒ 后写者抹掉先写者刚落的条目，两边 rc=0 都报成功。改前读数：
  进程内两实例：disk_lines=1 node_ids=['nodeB']（nodeA 无痕丢失）
  两个活进程：  disk_lines=1 node_ids=['liveA']（liveB 无痕丢失）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
SKIP = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def skip(name, why=""):
    """不适用/无法构造时显式跳过——**不冒充通过**（改前实现缺件时用）。"""
    global SKIP
    SKIP += 1
    print("[SKIP] %s  · %s" % (name, why))


def disk_tasks(root, mod):
    """盘上的**未消费**任务（墓碑行不计）。"""
    path = os.path.join(root, mod.QUEUE_FILE)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if isinstance(rec, dict) and not rec.get("_done"):
                out.append(rec)
    return out


def ids(root, mod):
    return sorted(t.get("node_id") for t in disk_tasks(root, mod))


def disk_tombstones(root, mod):
    path = os.path.join(root, mod.QUEUE_FILE)
    if not os.path.exists(path):
        return 0
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if isinstance(rec, dict) and rec.get("_done"):
                n += 1
    return n


def legacy_persist(self):
    """改前实现：全量覆写（定点变异 clobber 用）。"""
    if not self._queue_path:
        return
    try:
        with open(self._queue_path, "w", encoding="utf-8") as f:
            for task in self._queue:
                f.write(json.dumps(task, ensure_ascii=False) + "\n")
    except Exception:                                  # noqa: BLE001
        pass


def run(mutate=""):
    from md_cg import coldverify as cv

    def legacy_append(self, task):
        """改前实现：入队即全量覆写（定点变异 clobber 用）。"""
        legacy_persist(self)

    restore = []
    if mutate == "clobber":
        restore.append((cv.ColdVerifyQueue, "_persist",
                        cv.ColdVerifyQueue._persist))
        restore.append((cv.ColdVerifyQueue, "_append_task",
                        cv.ColdVerifyQueue._append_task))
        cv.ColdVerifyQueue._persist = legacy_persist
        cv.ColdVerifyQueue._append_task = legacy_append
    elif mutate == "no_leading_newline":
        def _no_nl(self, task):
            """变异：追加不带前置换行（改前 append_jsonl 之外的自造实现）。"""
            import json as _j
            line = (_j.dumps(task, ensure_ascii=False,
                             separators=(",", ":")) + "\n")
            with cv.FileLock(self._queue_path, strict=True):
                fd = os.open(self._queue_path,
                             os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
                try:
                    os.write(fd, line.encode("utf-8"))
                finally:
                    os.close(fd)
        restore.append((cv.ColdVerifyQueue, "_append_task",
                        cv.ColdVerifyQueue._append_task))
        cv.ColdVerifyQueue._append_task = _no_nl
    elif mutate == "ignore_tombstones":
        orig = cv.ColdVerifyQueue._read_disk

        def _blind(self, count_skipped=True):
            tasks, _ = orig(self, count_skipped=count_skipped)
            return tasks, {}

        restore.append((cv.ColdVerifyQueue, "_read_disk", orig))
        cv.ColdVerifyQueue._read_disk = _blind
    elif mutate == "no_prune":
        def _no_prune(self, tombs, now=None):
            """变异：墓碑不按 TTL/上限收敛（过期墓碑永久挡住恢复）。"""
            return dict(tombs or {})

        restore.append((cv.ColdVerifyQueue, "_prune_tombstones",
                        cv.ColdVerifyQueue._prune_tombstones))
        cv.ColdVerifyQueue._prune_tombstones = _no_prune
    elif mutate == "append_swallow":
        def _swallow(self, task):
            """变异：锁拿不到也照写（不做 fail-closed；其余形态不变）。"""
            import json as _j
            line = ("\n" + _j.dumps(task, ensure_ascii=False,
                                    separators=(",", ":")) + "\n")

            def _write():
                d = os.path.dirname(os.path.abspath(self._queue_path)) or "."
                os.makedirs(d, exist_ok=True)
                fd = os.open(self._queue_path,
                             os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
                try:
                    os.write(fd, line.encode("utf-8"))
                finally:
                    os.close(fd)

            try:
                with cv.FileLock(self._queue_path, strict=True):
                    _write()
            except Exception:                      # noqa: BLE001
                _write()

        restore.append((cv.ColdVerifyQueue, "_append_task",
                        cv.ColdVerifyQueue._append_task))
        cv.ColdVerifyQueue._append_task = _swallow

    try:
        _cases(cv)
    finally:
        for obj, name, val in restore:
            setattr(obj, name, val)


def _cases(cv):
    # ---------------------------------------------------------------- ① 进程内两实例
    root = tempfile.mkdtemp(prefix="cvq_")
    q1 = cv.ColdVerifyQueue(root=root)
    q2 = cv.ColdVerifyQueue(root=root)          # 两实例都在对方落盘前建好
    q1.enqueue("nodeA", action="reverify")
    q2.enqueue("nodeB", action="reverify")
    check("① 进程内两实例：两条都在盘上（后写者不抹掉先写者）",
          ids(root, cv) == ["nodeA", "nodeB"], "ids=%r" % (ids(root, cv),))
    check("① 两实例内存各自只见自己的条目（内存视图不被合并污染）",
          len(q1._queue) == 1 and len(q2._queue) == 1,
          "q1=%d q2=%d" % (len(q1._queue), len(q2._queue)))

    # ---------------------------------------------------------------- ② 两个活进程
    root2 = tempfile.mkdtemp(prefix="cvq2_")
    child = ("import sys;sys.path.insert(0,%r);from md_cg import coldverify as cv;"
             "q=cv.ColdVerifyQueue(root=%r);print('ready',flush=True);"
             "sys.stdin.readline();q.enqueue(%r,action='reverify');"
             "print('enqueued',len(q._queue),flush=True)")
    procs = []
    for nid in ("liveA", "liveB"):
        p = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-c", child % (REPO, root2, nid)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace")
        procs.append((nid, p))
    ready = []
    for nid, p in procs:
        ready.append(p.stdout.readline().strip())
    for _nid, p in procs:                       # 屏障：两边都加载完再各自入队
        p.stdin.write("go\n")
        p.stdin.flush()
    rc = []
    for _nid, p in procs:
        p.stdout.readline()
        rc.append(p.wait(timeout=30))
    check("② 两个活进程并发入队：两条都在盘上（生产形态）",
          ids(root2, cv) == ["liveA", "liveB"],
          "ids=%r ready=%r rc=%r" % (ids(root2, cv), ready, rc))

    # ---------------------------------------------------------------- ③ 墓碑防重放
    root3 = tempfile.mkdtemp(prefix="cvq3_")
    a = cv.ColdVerifyQueue(root=root3)
    a.enqueue("taskX", action="reverify")
    b = cv.ColdVerifyQueue(root=root3)          # b 内存里持有 taskX
    res = a.drain(_cg(root3), limit=1)
    check("③ 前件：A 已消费 taskX（processed=1）",
          len(res) == 1 and a.status()["stats"]["processed"] == 1,
          "res=%d" % (len(res),))
    b.enqueue("taskY", action="reverify")       # b 追加快路径（不改写盘）
    check("③ 追加快路径不重放已消费任务（taskX 不因 b 入队而回盘）",
          ids(root3, cv) == ["taskY"], "ids=%r" % (ids(root3, cv),))
    b.drain(_cg(root3), limit=0)                # 触发合并（压实）
    check("③ 合并时墓碑仍挡住 taskX（不重放）",
          ids(root3, cv) == ["taskY"], "ids=%r" % (ids(root3, cv),))
    check("③ 墓碑留在盘上（供后续实例跳过）",
          disk_tombstones(root3, cv) >= 1, "tombs=%d" % (disk_tombstones(root3, cv),))
    check("③ 他实例内存里的已消费条目在合并时就地丢弃（自愈）",
          all(t.get("node_id") != "taskX" for t in b._queue),
          "b_ids=%r" % ([t.get("node_id") for t in b._queue],))

    # ---------------------------------------------------------------- ④ clear 真清空
    root4 = tempfile.mkdtemp(prefix="cvq4_")
    a4 = cv.ColdVerifyQueue(root=root4)
    a4.enqueue("taskP", action="reverify")
    b4 = cv.ColdVerifyQueue(root=root4)         # b4 内存里持有 taskP
    a4.clear()
    check("④ clear 后盘上无未消费条目", ids(root4, cv) == [], "ids=%r" % (ids(root4, cv),))
    b4.enqueue("taskQ", action="reverify")
    check("④ clear 不被他实例合并写回（taskP 不复活）",
          ids(root4, cv) == ["taskQ"], "ids=%r" % (ids(root4, cv),))

    # ---------------------------------------------------------------- ⑤ 解析单点与落盘闸
    root5 = tempfile.mkdtemp(prefix="cvq5_")
    q5 = cv.ColdVerifyQueue(root=root5)
    path5 = os.path.join(root5, cv.QUEUE_FILE)
    with open(path5, "w", encoding="utf-8") as f:
        f.write(json.dumps({"node_id": "bad", "action": "rm_rf"}) + "\n")
    q6 = cv.ColdVerifyQueue(root=root5)
    sk_after_load = q6.status()["stats"]["skipped"]
    q6.enqueue("good", action="reverify")       # 追加快路径
    q6.drain(_cg(root5), limit=0)               # 触发一次写前合并（压实）
    check("⑤ 非法 action 只被计一次 skipped（合并读不复计）",
          sk_after_load == 1 and q6.status()["stats"]["skipped"] == 1,
          "load=%d after=%d" % (sk_after_load, q6.status()["stats"]["skipped"]))
    check("⑤ 非法行不进盘（合并只写合法任务 + 墓碑）",
          ids(root5, cv) == ["good"], "ids=%r" % (ids(root5, cv),))
    check("⑤ atomic_write：不留半截临时文件",
          [n for n in os.listdir(root5) if ".tmp-" in n] == [],
          "tmp=%r" % ([n for n in os.listdir(root5) if ".tmp-" in n],))

    locked = []
    real_lock = getattr(cv, "FileLock", None)

    class _Rec(object):
        def __init__(self, path, *a, **kw):
            locked.append(bool(kw.get("strict")))
            self._inner = real_lock(path, *a, **kw)

        def __enter__(self):
            return self._inner.__enter__()

        def __exit__(self, *exc):
            return self._inner.__exit__(*exc)

    if real_lock is None:
        # 改前实现没有落盘闸：本条必须**点名**失败，不能让守卫自己 AttributeError 崩掉
        check("⑤ 落盘确实在 FileLock(strict=True) 下进行（无锁不写，宁可晚一拍）",
              False, "模块未导入 FileLock（改前实现：裸 open(path,'w') 覆写）")
    else:
        cv.FileLock = _Rec
        try:
            q7 = cv.ColdVerifyQueue(root=tempfile.mkdtemp(prefix="cvq7_"))
            q7.enqueue("locked", action="reverify")
        finally:
            cv.FileLock = real_lock
        check("⑤ 落盘确实在 FileLock(strict=True) 下进行（无锁不写，宁可晚一拍）",
              locked == [True], "strict_flags=%r" % (locked,))

    # ---------------------------------------------------------------- ⑦ 半截行自愈
    root11 = tempfile.mkdtemp(prefix="cvq11_")
    p11 = os.path.join(root11, cv.QUEUE_FILE)
    q11 = cv.ColdVerifyQueue(root=root11)
    with open(p11, "a", encoding="utf-8") as f:
        f.write('{"node_id": "torn", "action": "reve')      # 被杀在中途的半截行
    q11.enqueue("after_torn", action="reverify")
    q12 = cv.ColdVerifyQueue(root=root11)
    check("⑦ 半截行自愈：残行不吞掉其后写入的记录（新实例仍能恢复）",
          "after_torn" in [t.get("node_id") for t in q12._queue],
          "loaded=%r" % ([t.get("node_id") for t in q12._queue],))
    check("⑦ 半截行被跳过并计数（容忍 ≠ 静默）",
          q12.status()["stats"]["skipped"] >= 1,
          "skipped=%d" % (q12.status()["stats"]["skipped"],))

    # ---------------------------------------------------------------- ⑧ 锁拿不到时 fail-closed
    root12 = tempfile.mkdtemp(prefix="cvq12_")
    q13 = cv.ColdVerifyQueue(root=root12)
    q13.enqueue("pre_lock", action="reverify")
    p12 = os.path.join(root12, cv.QUEUE_FILE)
    with open(p12, "rb") as fh:
        before_bytes = fh.read()
    real_lock12 = getattr(cv, "FileLock", None)
    if real_lock12 is None:
        check("⑧ 锁拿不到时 fail-closed（无锁不写、条目留内存）",
              False, "改前实现无 FileLock：_persist 裸 open(path,'w') 全量覆写")
        skip("⑧ 锁超时下盘上逐字节不变 / 锁恢复后合并补落",
             "改前无落盘闸，构造不出「锁超时」")
    else:
        class _Boom(object):
            """FileLock 替身：拿锁必超时（strict=True 语义）。"""

            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                raise TimeoutError("模拟 FileLock 超时（strict=True）")

            def __exit__(self, *exc):
                return False

        cv.FileLock = _Boom
        raised = None
        try:
            q13.enqueue("lock_timeout", action="reverify")
        except Exception as exc:                   # noqa: BLE001
            raised = exc
        finally:
            cv.FileLock = real_lock12
        check("⑧ 锁拿不到时 enqueue 不抛（写入路径不能因锁故障炸给调用方）",
              raised is None, "raised=%r" % (raised,))
        check("⑧ 锁拿不到时条目仍在内存队列（不静默丢）",
              "lock_timeout" in [t.get("node_id") for t in q13._queue],
              "mem=%r" % ([t.get("node_id") for t in q13._queue],))
        with open(p12, "rb") as fh:
            after_bytes = fh.read()
        check("⑧ 锁拿不到时不改写盘（逐字节不变：宁可晚一拍，也不无锁读改写）",
              after_bytes == before_bytes,
              "before=%dB after=%dB" % (len(before_bytes), len(after_bytes)))
        q13.drain(_cg(root12), limit=0)            # 锁恢复 → 走合并补落
        check("⑧ 锁恢复后合并补落：内存里那条晚一拍也落到盘上",
              "lock_timeout" in ids(root12, cv), "ids=%r" % (ids(root12, cv),))

    # ---------------------------------------------------------------- ⑨ 墓碑 TTL / 上限
    root13 = tempfile.mkdtemp(prefix="cvq13_")
    p13 = os.path.join(root13, cv.QUEUE_FILE)
    frozen = {"node_id": "ttlA", "action": "reverify",
              "enqueued_at": 1700000000.0, "kwargs": {}}
    _key_fn = getattr(cv.ColdVerifyQueue, "_task_key", None)
    if _key_fn is None:
        # 改前实现没有 _task_key：用同一规范化公式构造墓碑键
        # （只用于造夹具，不改变被断言的行为）
        def _key_fn(t):
            return json.dumps(t, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"))

    key13 = _key_fn(frozen)
    # 改前实现没有 TOMBSTONE_TTL：用同一个数值构造夹具，让「未过期墓碑必须挡住
    # 恢复」这条断言在改前也能真跑（否则会 AttributeError 把整份守卫打断）
    ttl13 = getattr(cv, "TOMBSTONE_TTL", 3600.0)
    now13 = time.time()

    def _write_ttl_file(ts):
        with open(p13, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(frozen, ensure_ascii=False) + "\n")
            fh.write(json.dumps({"_done": True, "key": key13, "_t": ts},
                                ensure_ascii=False) + "\n")

    _write_ttl_file(now13 - ttl13 - 10.0)                 # 过期墓碑
    q14 = cv.ColdVerifyQueue(root=root13)
    check("⑨ 过期墓碑（超 TTL）不再挡恢复：任务被恢复而不是静默丢",
          "ttlA" in [t.get("node_id") for t in q14._queue],
          "loaded=%r tombstones=%d" % ([t.get("node_id") for t in q14._queue],
                                       len(getattr(q14, "_tombstones", {}))))
    if hasattr(q14, "_tombstones"):
        check("⑨ 过期墓碑在加载期即被收敛掉（不越积越多）",
              len(q14._tombstones) == 0,
              "tombstones=%d" % (len(q14._tombstones),))
    else:
        check("⑨ 过期墓碑在加载期即被收敛掉（不越积越多）",
              False, "改前无墓碑表（_done 分支无人写入）")

    _write_ttl_file(now13)                                # 未过期墓碑
    q15 = cv.ColdVerifyQueue(root=root13)
    check("⑨ 未过期墓碑仍挡住恢复（消费过的任务不重放）",
          [t.get("node_id") for t in q15._queue] == [],
          "loaded=%r" % ([t.get("node_id") for t in q15._queue],))

    if hasattr(q15, "_prune_tombstones") and hasattr(cv, "TOMBSTONE_MAX"):
        # 全部落在 TTL 窗口内（间隔 1ms），否则先被 TTL 过滤、条数上限永远不触发
        tombs = dict(("k%05d" % i, now13 - i * 0.001)
                     for i in range(cv.TOMBSTONE_MAX + 50))
        pruned = q15._prune_tombstones(tombs)
        check("⑨ 墓碑条数超上限时收敛到 TOMBSTONE_MAX 且保留最新",
              len(pruned) == cv.TOMBSTONE_MAX and "k00000" in pruned
              and ("k%05d" % (cv.TOMBSTONE_MAX + 49)) not in pruned,
              "len=%d" % (len(pruned),))
    else:
        check("⑨ 墓碑条数超上限时收敛到 TOMBSTONE_MAX 且保留最新",
              False, "改前无 _prune_tombstones / TOMBSTONE_MAX")

    # ---------------------------------------------------------------- ⑩ 解析口径对照
    from md_cg import fsutil as fs10
    root14 = tempfile.mkdtemp(prefix="cvq14_")
    p14 = os.path.join(root14, cv.QUEUE_FILE)
    ok_line = json.dumps({"node_id": "ok1", "action": "reverify",
                          "enqueued_at": 1700000000.0, "kwargs": {}},
                         ensure_ascii=False)
    badact_line = json.dumps({"node_id": "badact", "action": "rm_rf",
                              "enqueued_at": 1700000000.0, "kwargs": {}},
                             ensure_ascii=False)
    with open(p14, "w", encoding="utf-8") as fh:
        fh.write(ok_line + "\n")
        fh.write('{"node_id": "torn", "action": "reve\n')     # 半截行
        fh.write(badact_line + "\n")
    raw_ids = [r.get("node_id") for r in fs10.read_jsonl(p14)]
    q16 = cv.ColdVerifyQueue(root=root14)
    check("⑩ 坏行容忍口径一致：fsutil.read_jsonl 也不因半截行中断",
          raw_ids == ["ok1", "badact"], "raw_ids=%r" % (raw_ids,))
    check("⑩ 我的解析点同样跳过坏行、只留合法任务",
          [t.get("node_id") for t in q16._queue] == ["ok1"],
          "mine=%r" % ([t.get("node_id") for t in q16._queue],))
    check("⑩ 差异是有意加严：read_jsonl 不做语义校验，我按白名单拒收非法 action 并计数",
          q16.status()["stats"]["skipped"] == 2,
          "skipped=%d" % (q16.status()["stats"]["skipped"],))

    # ---------------------------------------------------------------- ⑥ 阴性对照
    root8 = tempfile.mkdtemp(prefix="cvq8_")
    root9 = tempfile.mkdtemp(prefix="cvq9_")
    cv.ColdVerifyQueue(root=root8).enqueue("only8", action="reverify")
    check("⑥ 阴性对照：不同 root 互不影响",
          ids(root8, cv) == ["only8"] and ids(root9, cv) == [],
          "r8=%r r9=%r" % (ids(root8, cv), ids(root9, cv)))
    root10 = tempfile.mkdtemp(prefix="cvq10_")
    cv.ColdVerifyQueue(root=root10).enqueue("solo", action="reverify")
    q10 = cv.ColdVerifyQueue(root=root10)
    check("⑥ 单实例语义不变：新实例仍能恢复未处理任务",
          q10.status()["queue_size"] == 1
          and q10._queue[0].get("node_id") == "solo",
          "size=%d" % (q10.status()["queue_size"],))


def _cg(root):
    """真 cg 实例（drain 的 _process 需要它做 reverify）。"""
    from md_cg.mdcos import MdCGSecure
    return MdCGSecure(root, principal=None)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mutate = ""
    for a in argv:
        if a.startswith("--mutate="):
            mutate = a.split("=", 1)[1]
    if mutate and mutate not in ("clobber", "ignore_tombstones",
                                 "no_leading_newline", "no_prune",
                                 "append_swallow"):
        print("未知变异：%s（可用：clobber / ignore_tombstones / "
              "no_leading_newline / no_prune / append_swallow）" % mutate)
        return 2
    print("== coldverify 队列跨实例合并守卫（mutate=%r）" % mutate)
    run(mutate)
    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d%s" % (PASS, FAIL,
                                    (" ／ 跳过 %d" % SKIP) if SKIP else ""))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
