# -*- coding: utf-8 -*-
"""MdCG 既有锁外 `self._dirty` 调用点守卫（#1011 独立补齐）。

覆盖 PR #1012 评审明确拆出、独立落地的既有竞态修复面：
- G1 锁护与锁序验证：`_dirty_entry_superseded` / `rebuild_index` / `_unstage` /
     `_node_disk_path` / `get` 回落 / `_sync_edge_entry` / `update_tags` /
     `set_goal_status` / `_stage` 阈值检查 / `verify._land_fm` 均在 `_dirty_lock`
     内访问 `_dirty`；且 `_unstage -> flush`、`_stage -> _request_flush`、
     `_node_disk_path -> realpath` 均在释放 `_dirty_lock` 后执行（零锁序倒置）。
- G2 `#677 P2` 不在 `_dirty_lock` 内做磁盘 IO：`_dirty_entry_superseded` 的
     `os.stat` 与 `_file_digest` 严格在锁外执行，且并发线程在 `os.stat` 阻塞期间
     可立即获取 `_dirty_lock`。
- G3 静态 AST 审计 + 变异对照（含「故意在锁外 clear」在内的 5 项定点变异，
     逐条证明静态守卫与运行时守卫均有判别力，绝不空过）。
- G4 真线程并发压测：多写者 + `_dirty_entry_superseded` + `_unstage` +
     `rebuild_index` + `get` + `flush` 并发碰撞，零 `RuntimeError`、零死锁、
     零丢清、重开可读回全部存活节点。

跑法：python -X utf8 -m md_cg.test_mdcg_dirty_lock_sites
"""
from __future__ import annotations

import ast
import os
import shutil
import sys
import tempfile
import threading
import time
import types

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from md_cg import mdcg as _mdcg_mod  # noqa: E402
from md_cg.mdcg import MdCG, _DirtyDict  # noqa: E402

_PASS = []
_FAIL = []

_BODY = (
    "# 功能名：%s\n# 生效条件：全时窗\n# 子功能：s\n# 执行：%s\n"
    "# 验证方式：test\n# 不适用条件：无\n"
)

# 明确允许不持 `_dirty_lock` 的只读/构造站点：
# - __init__: 实例发布与后台线程启动前的构造初始化
# - flush_state: PR #1012 独占修改面（为保双向零冲突，本 PR 不触碰）
# - _cache_generation / _realpath_fresh: 热路径只读代际探测
_ALLOWED_UNLOCKED_METHODS = frozenset({
    "MdCG.__init__",
    "MdCG.flush_state",
    "MdCG._cache_generation",
    "MdCG._realpath_fresh",
})


def ok(cond, label, detail=""):
    (_PASS if cond else _FAIL).append(label)
    suffix = ("  <- " + str(detail)[:240]) if (detail and not cond) else ""
    print(("  PASS " if cond else "  FAIL ") + label + suffix)
    return bool(cond)


class _TrackingRLock:
    """包装真实 RLock，按线程精确记录持锁深度与进入次数。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._tls = threading.local()
        self.entries = 0

    @property
    def depth(self) -> int:
        return getattr(self._tls, "depth", 0)

    def acquire(self, *args, **kwargs):
        got = self._lock.acquire(*args, **kwargs)
        if got:
            self._tls.depth = self.depth + 1
            self.entries += 1
        return got

    def release(self):
        self._tls.depth = max(0, self.depth - 1)
        return self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False


class _ObservingMap(dict):
    """记录 `staged_stat` 访问时 `_dirty_lock` 的持锁深度。"""

    def __init__(self, lock: _TrackingRLock, label: str, log: list, *a, **k):
        super().__init__(*a, **k)
        self._obs_lock = lock
        self._obs_label = label
        self._obs_log = log

    def _note(self, op: str):
        self._obs_log.append((f"{self._obs_label}.{op}", self._obs_lock.depth))

    def get(self, key, default=None):
        self._note("get")
        return super().get(key, default)

    def clear(self):
        self._note("clear")
        return super().clear()

    def __setitem__(self, k, v):
        self._note("__setitem__")
        return super().__setitem__(k, v)


class _ObservingDirtyDict(_DirtyDict):
    """在 `_DirtyDict` 每次关键操作时记录 `_dirty_lock` 持锁深度。"""

    def __init__(self, lock: _TrackingRLock, log: list, src: _DirtyDict):
        super().__init__()
        self._obs_lock = lock
        self._obs_log = log
        self._obs_enabled = False
        self.root = src.root
        self.write_gen = src.write_gen
        self.broad_gen = src.broad_gen
        self.path_gen = dict(src.path_gen)
        self.staged_stat = _ObservingMap(lock, "staged_stat", log, src.staged_stat)
        self.superseded_ids = set(src.superseded_ids)
        dict.update(self, src)
        self._obs_enabled = True

    def _rec(self, op: str):
        if object.__getattribute__(self, "_obs_enabled"):
            lk = object.__getattribute__(self, "_obs_lock")
            lg = object.__getattribute__(self, "_obs_log")
            lg.append((op, lk.depth))

    def __setitem__(self, k, v):
        self._rec("__setitem__")
        return super().__setitem__(k, v)

    def clear(self, broad: bool = False):
        self._rec("clear(broad=%s)" % bool(broad))
        return super().clear(broad=broad)

    def get(self, k, default=None):
        self._rec("get")
        return super().get(k, default)

    def __len__(self):
        self._rec("__len__")
        return super().__len__()

    def __getattribute__(self, name):
        if name == "write_gen":
            if object.__getattribute__(self, "_obs_enabled"):
                lk = object.__getattribute__(self, "_obs_lock")
                lg = object.__getattribute__(self, "_obs_log")
                lg.append(("write_gen", lk.depth))
        return super().__getattribute__(name)


def _attach_observer(cg):
    """给 MdCG 实例挂上 `_TrackingRLock` 与 `_ObservingDirtyDict`。"""
    lock = _TrackingRLock()
    log = []
    cg._dirty_lock = lock
    cg._dirty = _ObservingDirtyDict(lock, log, cg._dirty)
    return lock, log


def _find_unlocked_dirty_sites(src: str) -> list:
    """AST 审计：找出 `MdCG` 中允许表外所有不在 `with self._dirty_lock:` 内的 `self._dirty` 访问。"""
    tree = ast.parse(src)
    violations = []

    class _Visitor(ast.NodeVisitor):
        def __init__(self):
            self.cls = None
            self.fn_stack = []
            self.in_dirty_lock = 0

        def visit_ClassDef(self, node):
            prev = self.cls
            self.cls = node.name
            self.generic_visit(node)
            self.cls = prev

        def visit_FunctionDef(self, node):
            self.fn_stack.append(node.name)
            self.generic_visit(node)
            self.fn_stack.pop()

        def visit_With(self, node):
            is_dl = any("_dirty_lock" in ast.unparse(i.context_expr) for i in node.items)
            if is_dl:
                self.in_dirty_lock += 1
            self.generic_visit(node)
            if is_dl:
                self.in_dirty_lock -= 1

        def visit_Attribute(self, node):
            if (self.cls == "MdCG" and node.attr == "_dirty"
                    and isinstance(node.value, ast.Name) and node.value.id == "self"):
                qual = f"MdCG.{'.'.join(self.fn_stack)}"
                if self.in_dirty_lock == 0 and qual not in _ALLOWED_UNLOCKED_METHODS:
                    violations.append((qual, node.lineno))
            self.generic_visit(node)

    _Visitor().visit(tree)
    return violations


def _exec_mutated_mdcg(mut_src: str, mod_name: str):
    rel = os.path.join("md_cg", "mdcg.py")
    ns = {"__name__": mod_name, "__package__": "md_cg",
          "__file__": os.path.join(_REPO, rel)}
    exec(compile(mut_src, rel, "exec"), ns)  # noqa: S102 —— 变异自证用
    m = types.ModuleType(mod_name)
    m.__dict__.update(ns)
    return m


# ---------------------------------------------------------------- G1
def g1_lock_protection_and_ordering(tmp_root: str):
    print("== G1 各修复点锁护与锁序验证 ==")
    r = os.path.join(tmp_root, "g1")
    cg = MdCG(r, autoflush=1000, async_flush=False)
    try:
        cg.add("n1", _BODY % ("n1", "init"), layer="knowledge", verification_basis="test")
        cg.add("n2", _BODY % ("n2", "init2"), layer="knowledge", verification_basis="test")
        cg.add("g1_goal", _BODY % ("goal", "target"), layer="goals", verification_basis="test")
        lock, log = _attach_observer(cg)

        # G1a: _dirty_entry_superseded
        log.clear()
        res = cg._dirty_entry_superseded("n1")
        st_ops = [d for op, d in log if op == "staged_stat.get"]
        get_ops = [d for op, d in log if op == "get"]
        ok(res is False and st_ops and all(d >= 1 for d in st_ops)
           and get_ops and all(d >= 1 for d in get_ops),
           "G1a _dirty_entry_superseded 在 _dirty_lock 内快照 staged_stat 与 entry",
           {"res": res, "log": log})

        # G1b: rebuild_index (clear(broad=True) under _dirty_lock, after FileLock exit)
        filelock_active = [False]
        orig_fl = _mdcg_mod.FileLock

        class _ObsFileLock:
            def __init__(self, *a, **k):
                self._inner = orig_fl(*a, **k)

            def __enter__(self):
                filelock_active[0] = True
                return self._inner.__enter__()

            def __exit__(self, *exc):
                try:
                    return self._inner.__exit__(*exc)
                finally:
                    filelock_active[0] = False

        clear_under_filelock = []
        orig_clear = cg._dirty.clear

        def _wrapped_clear(broad=False):
            clear_under_filelock.append(filelock_active[0])
            return orig_clear(broad=broad)

        cg._dirty.clear = _wrapped_clear
        _mdcg_mod.FileLock = _ObsFileLock
        log.clear()
        try:
            cg.rebuild_index()
        finally:
            _mdcg_mod.FileLock = orig_fl
            cg._dirty.clear = orig_clear
        clr_ops = [d for op, d in log if op == "clear(broad=True)"]
        ok(clr_ops and all(d >= 1 for d in clr_ops)
           and cg._dirty.broad_gen == cg._dirty.write_gen
           and clear_under_filelock == [False],
           "G1b rebuild_index 在 FileLock 外且 _dirty_lock 内执行 _dirty.clear(broad=True)",
           {"clr_ops": clr_ops, "fl_active": clear_under_filelock,
            "broad": cg._dirty.broad_gen, "gen": cg._dirty.write_gen})

        # G1c: _unstage (tombstone under _dirty_lock, flush() strictly OUTSIDE _dirty_lock)
        flush_entry_depths = []
        orig_flush = cg.flush

        def _obs_flush():
            flush_entry_depths.append(lock.depth)
            return orig_flush()

        cg.flush = _obs_flush
        log.clear()
        try:
            cg._unstage("n2")
        finally:
            cg.flush = orig_flush
        set_ops = [d for op, d in log if op == "__setitem__"]
        ok(set_ops and all(d >= 1 for d in set_ops)
           and flush_entry_depths == [0],
           "G1c _unstage 锁内写 tombstone，释放 _dirty_lock 后再调 flush()（无锁序倒置）",
           {"set_ops": set_ops, "flush_depths": flush_entry_depths})

        # G1d: _node_disk_path (cache miss snapshots write_gen under lock, realpath outside; hit lock-free)
        cg._realpath_cache.clear()
        realpath_depths = []
        orig_realpath = _mdcg_mod.os.path.realpath

        def _obs_realpath(path):
            realpath_depths.append(lock.depth)
            return orig_realpath(path)

        entry_n1 = cg.index["nodes"].get("n1")
        log.clear()
        _mdcg_mod.os.path.realpath = _obs_realpath
        try:
            p1 = cg._node_disk_path(entry_n1)
        finally:
            _mdcg_mod.os.path.realpath = orig_realpath
        gen_ops = [d for op, d in log if op == "write_gen"]
        ok(bool(p1) and gen_ops and all(d >= 1 for d in gen_ops)
           and realpath_depths and all(d == 0 for d in realpath_depths),
           "G1d-1 _node_disk_path 缓存未命中时锁内取 write_gen、锁外做 os.path.realpath",
           {"gen_ops": gen_ops, "realpath_depths": realpath_depths})

        entries_before = lock.entries
        p2 = cg._node_disk_path(entry_n1)
        ok(p2 == p1 and lock.entries == entries_before,
           "G1d-2 _node_disk_path 缓存命中热路径零加锁",
           {"delta_entries": lock.entries - entries_before})

        # G1e: get() fallback under _dirty_lock; normal index hit lock-free
        # First test normal hit (probe=False so reload doesn't touch lock)
        entries_before = lock.entries
        got_hit = cg.get("n1", probe=False)
        ok(got_hit is not None and lock.entries == entries_before,
           "G1e-1 get() 命中 index['nodes'] 热路径零加锁",
           {"delta_entries": lock.entries - entries_before})

        # Now test fallback when absent from index["nodes"] but present in _dirty
        saved_entry = cg.index["nodes"].pop("n1")
        with cg._dirty_lock:
            cg._dirty["n1"] = saved_entry
        log.clear()
        try:
            got_fb = cg.get("n1", probe=False)
        finally:
            cg.index["nodes"]["n1"] = saved_entry
        fb_gets = [d for op, d in log if op == "get"]
        ok(got_fb is not None and fb_gets and all(d >= 1 for d in fb_gets),
           "G1e-2 get() 回落 self._dirty.get(node_id) 在 _dirty_lock 内执行",
           {"got": got_fb is not None, "fb_gets": fb_gets})

        # G1f: _sync_edge_entry, update_tags, set_goal_status, _stage, verify._land_fm
        log.clear()
        cg.append_edge("n1", {"target": "g1_goal", "relation_type": "supports"})
        edge_sets = [d for op, d in log if op == "__setitem__"]
        ok(edge_sets and all(d >= 1 for d in edge_sets),
           "G1f-1 _sync_edge_entry（append_edge）在 _dirty_lock 内标脏", edge_sets)

        log.clear()
        cg.update_tags("n1", add=["t_locked"])
        tag_sets = [d for op, d in log if op == "__setitem__"]
        ok(tag_sets and all(d >= 1 for d in tag_sets),
           "G1f-2 update_tags 在 _dirty_lock 内标脏", tag_sets)

        log.clear()
        cg.set_goal_status("g1_goal", "done")
        goal_sets = [d for op, d in log if op == "__setitem__"]
        ok(goal_sets and all(d >= 1 for d in goal_sets),
           "G1f-3 set_goal_status 在 _dirty_lock 内标脏", goal_sets)

        # _stage autoflush check under lock + _request_flush outside lock
        req_depths = []
        orig_req = cg._request_flush

        def _obs_req():
            req_depths.append(lock.depth)
            return orig_req()

        cg._request_flush = _obs_req
        cg.autoflush = 1
        log.clear()
        try:
            cg.add("n3", _BODY % ("n3", "stage"), layer="knowledge", verification_basis="test")
        finally:
            cg._request_flush = orig_req
            cg.autoflush = 1000
        stage_sets = [d for op, d in log if op == "__setitem__"]
        stage_lens = [d for op, d in log if op == "__len__"]
        ok(stage_sets and all(d >= 1 for d in stage_sets)
           and stage_lens and all(d >= 1 for d in stage_lens)
           and req_depths and all(d == 0 for d in req_depths),
           "G1f-4 _stage 标脏与阈值 len(_dirty) 均在锁内，_request_flush 在锁外",
           {"sets": stage_sets, "lens": stage_lens, "req_depths": req_depths})

        # verify -> _land_fm（先进入 verified 态使尾部 set_verification 走 noop，精确隔离 _land_fm 标脏）
        cg.verify("n1", "seed verify", "confirmed")
        log.clear()
        vrep = cg.verify("n1", "unit check", "confirmed")
        ver_sets = [d for op, d in log if op == "__setitem__"]
        ok(vrep is not None and ver_sets and all(d >= 1 for d in ver_sets),
           "G1f-5 verify._land_fm 在 _dirty_lock 内标脏", ver_sets)
    finally:
        cg.close()


# ---------------------------------------------------------------- G2
def g2_no_io_under_dirty_lock(tmp_root: str):
    print("== G2 #677 P2 纪律：_dirty_entry_superseded 磁盘 IO 严格在锁外 ==")
    r = os.path.join(tmp_root, "g2")
    cg = MdCG(r, autoflush=1000, async_flush=False)
    try:
        cg.add("io1", _BODY % ("io1", "V1"), layer="knowledge", verification_basis="test")
        lock, _log = _attach_observer(cg)
        rel_p = cg.index["nodes"]["io1"]["path"]
        abs_p = os.path.join(r, rel_p)

        # G2a: fast path (mtime/size changed) -> os.stat depth == 0
        stat_depths = []
        orig_stat = _mdcg_mod.os.stat

        def _obs_stat(path, *a, **k):
            if os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(os.path.abspath(abs_p)):
                stat_depths.append(lock.depth)
            return orig_stat(path, *a, **k)

        with open(abs_p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_BODY % ("io1", "V2_LONGER"))
        _mdcg_mod.os.stat = _obs_stat
        try:
            sup_fast = cg._dirty_entry_superseded("io1")
        finally:
            _mdcg_mod.os.stat = orig_stat
        ok(sup_fast is True and stat_depths == [0],
           "G2a 快路径：os.stat 在 _dirty_lock 外执行（depth=0）",
           {"sup": sup_fast, "stat_depths": stat_depths})

        # G2b: slow path (equal-length + mtime restored -> triggers _file_digest)
        cg.add("io2", _BODY % ("io2", "AA"), layer="knowledge", verification_basis="test")
        abs_p2 = os.path.join(r, cg.index["nodes"]["io2"]["path"])
        raw = open(abs_p2, "rb").read()
        mut = raw.replace(b"AA", b"BB")
        st0 = os.stat(abs_p2)
        with open(abs_p2, "wb") as fh:
            fh.write(mut)
        os.utime(abs_p2, ns=(st0.st_atime_ns, st0.st_mtime_ns))

        stat_depths2 = []
        digest_depths2 = []
        orig_digest = _mdcg_mod._file_digest

        def _obs_stat2(path, *a, **k):
            if os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(os.path.abspath(abs_p2)):
                stat_depths2.append(lock.depth)
            return orig_stat(path, *a, **k)

        def _obs_digest2(path):
            digest_depths2.append(lock.depth)
            return orig_digest(path)

        _mdcg_mod.os.stat = _obs_stat2
        _mdcg_mod._file_digest = _obs_digest2
        try:
            sup_slow = cg._dirty_entry_superseded("io2")
        finally:
            _mdcg_mod.os.stat = orig_stat
            _mdcg_mod._file_digest = orig_digest
        ok(sup_slow is True and stat_depths2 == [0] and digest_depths2 == [0],
           "G2b 慢路径（等长+mtime还原）：os.stat 与 _file_digest 均在 _dirty_lock 外执行",
           {"sup": sup_slow, "stat_depths": stat_depths2, "digest_depths": digest_depths2})

        # G2c: live barrier proof — concurrent thread acquires _dirty_lock while os.stat is blocked
        entered_stat = threading.Event()
        release_stat = threading.Event()

        def _blocking_stat(path, *a, **k):
            if os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(os.path.abspath(abs_p2)):
                entered_stat.set()
                release_stat.wait(timeout=5.0)
            return orig_stat(path, *a, **k)

        peer_got_lock = [False]
        t_res = [None]

        def _run_superseded():
            t_res[0] = cg._dirty_entry_superseded("io2")

        _mdcg_mod.os.stat = _blocking_stat
        th = threading.Thread(target=_run_superseded)
        try:
            th.start()
            ok(entered_stat.wait(timeout=3.0), "G2c-前置：已进入阻塞 os.stat 窗口")
            got = lock.acquire(timeout=1.5)
            if got:
                peer_got_lock[0] = True
                lock.release()
        finally:
            release_stat.set()
            th.join(timeout=5.0)
            _mdcg_mod.os.stat = orig_stat
        ok(peer_got_lock[0] is True and t_res[0] is True,
           "G2c 实测阻塞窗口：os.stat 阻塞时对端线程可立即拿到 _dirty_lock",
           {"peer_got_lock": peer_got_lock[0], "res": t_res[0]})
    finally:
        cg.close()


# ---------------------------------------------------------------- G3
def g3_ast_and_mutation_controls(tmp_root: str):
    print("== G3 静态 AST 审计 + 定点变异对照（含「故意在锁外 clear」）==")
    mdcg_path = os.path.join(_REPO, "md_cg", "mdcg.py")
    src = open(mdcg_path, encoding="utf-8").read()

    # G3a: clean AST audit
    violations = _find_unlocked_dirty_sites(src)
    ok(not violations,
       "G3a AST 审计：允许表外零处锁外 self._dirty 访问",
       violations)

    # G3b: 变异对照 #1 —— 故意在锁外 clear（rebuild_index 撤掉 with self._dirty_lock）
    old_rebuild = (
        "        with self._dirty_lock:\n"
        "            self._dirty.clear(broad=True)  # 保住 _DirtyDict 钩子（批次 23 D-4）"
    )
    new_rebuild = "        self._dirty.clear(broad=True)  # 变异：故意在锁外 clear"
    ok(old_rebuild in src, "G3b-锚点：rebuild_index 锁护锚点在位")
    mut_rebuild_src = src.replace(old_rebuild, new_rebuild, 1)
    ast_hit_1 = [q for q, _ln in _find_unlocked_dirty_sites(mut_rebuild_src)]
    mut_mod_1 = _exec_mutated_mdcg(mut_rebuild_src, "md_cg._mut_dlock_rebuild")
    cg1 = mut_mod_1.MdCG(os.path.join(tmp_root, "g3_m1"), autoflush=1000, async_flush=False)
    try:
        cg1.add("m1", _BODY % ("m1", "x"), layer="knowledge", verification_basis="test")
        _lk1, log1 = _attach_observer(cg1)
        log1.clear()
        cg1.rebuild_index()
        rt_unlocked_1 = [op for op, d in log1 if op == "clear(broad=True)" and d == 0]
    finally:
        cg1.close()
    ok("MdCG.rebuild_index" in ast_hit_1 and bool(rt_unlocked_1),
       "G3b 变异对照 #1（故意在锁外 clear）：AST 与运行时双守卫均检出违规",
       {"ast": ast_hit_1, "rt_unlocked": rt_unlocked_1})

    # G3c: 变异对照 #2 —— _dirty_entry_superseded 撤掉 with self._dirty_lock
    old_sup = (
        "        with self._dirty_lock:\n"
        "            st = self._dirty.staged_stat.get(nid)\n"
        "            if st is None:\n"
        "                return False\n"
        "            e = self._dirty.get(nid)\n"
        "            p = e.get(\"path\") if isinstance(e, dict) else None"
    )
    new_sup = (
        "        st = self._dirty.staged_stat.get(nid)\n"
        "        if st is None:\n"
        "            return False\n"
        "        e = self._dirty.get(nid)\n"
        "        p = e.get(\"path\") if isinstance(e, dict) else None"
    )
    ok(old_sup in src, "G3c-锚点：_dirty_entry_superseded 锁护锚点在位")
    mut_sup_src = src.replace(old_sup, new_sup, 1)
    ast_hit_2 = [q for q, _ln in _find_unlocked_dirty_sites(mut_sup_src)]
    mut_mod_2 = _exec_mutated_mdcg(mut_sup_src, "md_cg._mut_dlock_sup")
    cg2 = mut_mod_2.MdCG(os.path.join(tmp_root, "g3_m2"), autoflush=1000, async_flush=False)
    try:
        cg2.add("m2", _BODY % ("m2", "x"), layer="knowledge", verification_basis="test")
        _lk2, log2 = _attach_observer(cg2)
        log2.clear()
        cg2._dirty_entry_superseded("m2")
        rt_unlocked_2 = [op for op, d in log2 if op in ("staged_stat.get", "get") and d == 0]
    finally:
        cg2.close()
    ok("MdCG._dirty_entry_superseded" in ast_hit_2 and len(rt_unlocked_2) >= 2,
       "G3c 变异对照 #2（_dirty_entry_superseded 锁外读）：AST 与运行时双守卫均检出",
       {"ast": ast_hit_2, "rt_unlocked": rt_unlocked_2})

    # G3d: 变异对照 #3 —— _unstage 撤掉 with self._dirty_lock
    old_unst = (
        "        with self._dirty_lock:\n"
        "            self._dirty[node_id] = None  # None = 删除记录，随 flush 落分片日志"
    )
    new_unst = "        self._dirty[node_id] = None  # 变异：锁外写 tombstone"
    ok(old_unst in src, "G3d-锚点：_unstage 锁护锚点在位")
    mut_unst_src = src.replace(old_unst, new_unst, 1)
    ast_hit_3 = [q for q, _ln in _find_unlocked_dirty_sites(mut_unst_src)]
    mut_mod_3 = _exec_mutated_mdcg(mut_unst_src, "md_cg._mut_dlock_unst")
    cg3 = mut_mod_3.MdCG(os.path.join(tmp_root, "g3_m3"), autoflush=1000, async_flush=False)
    try:
        cg3.add("m3", _BODY % ("m3", "x"), layer="knowledge", verification_basis="test")
        _lk3, log3 = _attach_observer(cg3)
        log3.clear()
        cg3._unstage("m3")
        rt_unlocked_3 = [op for op, d in log3 if op == "__setitem__" and d == 0]
    finally:
        cg3.close()
    ok("MdCG._unstage" in ast_hit_3 and bool(rt_unlocked_3),
       "G3d 变异对照 #3（_unstage 锁外写 tombstone）：AST 与运行时双守卫均检出",
       {"ast": ast_hit_3, "rt_unlocked": rt_unlocked_3})

    # G3e: 变异对照 #4 —— 故意把 os.stat 放进 _dirty_lock（违背 #677 P2）
    old_io = (
        "        if not p:\n"
        "            return False\n"
        "        fp = os.path.join(self.root, p)\n"
        "        try:\n"
        "            cur = os.stat(fp)\n"
        "        except OSError:\n"
        "            return True"
    )
    new_io = (
        "        if not p:\n"
        "            return False\n"
        "        fp = os.path.join(self.root, p)\n"
        "        with self._dirty_lock:\n"
        "            try:\n"
        "                cur = os.stat(fp)\n"
        "            except OSError:\n"
        "                return True"
    )
    ok(old_io in src, "G3e-锚点：_dirty_entry_superseded os.stat 锚点在位")
    mut_io_src = src.replace(old_io, new_io, 1)
    mut_mod_4 = _exec_mutated_mdcg(mut_io_src, "md_cg._mut_dlock_io")
    cg4 = mut_mod_4.MdCG(os.path.join(tmp_root, "g3_m4"), autoflush=1000, async_flush=False)
    try:
        cg4.add("m4", _BODY % ("m4", "x"), layer="knowledge", verification_basis="test")
        lk4, _log4 = _attach_observer(cg4)
        abs_p4 = os.path.join(cg4.root, cg4.index["nodes"]["m4"]["path"])
        mut_stat_depths = []
        orig_stat4 = mut_mod_4.os.stat

        def _obs_stat4(path, *a, **k):
            if os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(os.path.abspath(abs_p4)):
                mut_stat_depths.append(lk4.depth)
            return orig_stat4(path, *a, **k)

        mut_mod_4.os.stat = _obs_stat4
        try:
            cg4._dirty_entry_superseded("m4")
        finally:
            mut_mod_4.os.stat = orig_stat4
    finally:
        cg4.close()
    ok(mut_stat_depths and any(d >= 1 for d in mut_stat_depths),
       "G3e 变异对照 #4（os.stat 误入 _dirty_lock）：IO 锁外守卫检出违规（depth>=1）",
       mut_stat_depths)

    # G3f: 变异对照 #5 —— 故意把 self.flush() 放进 _unstage 的 _dirty_lock（锁序倒置）
    old_ord = (
        "        with self._dirty_lock:\n"
        "            self._dirty[node_id] = None  # None = 删除记录，随 flush 落分片日志\n"
        "        self.flush()                     # 删除不可延迟到 autoflush 阈值"
    )
    new_ord = (
        "        with self._dirty_lock:\n"
        "            self._dirty[node_id] = None\n"
        "            self.flush()"
    )
    ok(old_ord in src, "G3f-锚点：_unstage 锁外 flush 锚点在位")
    mut_ord_src = src.replace(old_ord, new_ord, 1)
    mut_mod_5 = _exec_mutated_mdcg(mut_ord_src, "md_cg._mut_dlock_ord")
    cg5 = mut_mod_5.MdCG(os.path.join(tmp_root, "g3_m5"), autoflush=1000, async_flush=False)
    try:
        cg5.add("m5", _BODY % ("m5", "x"), layer="knowledge", verification_basis="test")
        lk5, _log5 = _attach_observer(cg5)
        ord_depths = []
        orig_fl5 = cg5.flush

        def _obs_fl5():
            ord_depths.append(lk5.depth)
            return orig_fl5()

        cg5.flush = _obs_fl5
        try:
            cg5._unstage("m5")
        finally:
            cg5.flush = orig_fl5
    finally:
        cg5.close()
    ok(ord_depths and any(d >= 1 for d in ord_depths),
       "G3f 变异对照 #5（_unstage 锁内调 flush）：锁序守卫检出违规（depth>=1）",
       ord_depths)


# ---------------------------------------------------------------- G4
def g4_multithreaded_stress(tmp_root: str):
    print("== G4 多线程并发碰撞（零 RuntimeError / 零死锁 / 零丢清）==")
    r = os.path.join(tmp_root, "g4")
    cg = MdCG(r, autoflush=1, async_flush=True)
    keep_ids = [f"keep_{i:02d}" for i in range(16)]
    churn_ids = [f"churn_{i:02d}" for i in range(16)]
    try:
        for nid in keep_ids:
            cg.add(nid, _BODY % (nid, "seed"), layer="knowledge", verification_basis="test")
        cg.add("goal_mt", _BODY % ("goal_mt", "active"), layer="goals", verification_basis="test")
        cg.flush()

        stop = threading.Event()
        errors = []
        err_lock = threading.Lock()

        def _record(who, exc):
            with err_lock:
                errors.append((who, type(exc).__name__, str(exc)))

        def _writer_keep():
            try:
                for step in range(24):
                    nid = keep_ids[step % len(keep_ids)]
                    cg.update_tags(nid, add=[f"tag_{step % 4}"])
                    cg.append_edge(nid, {"target": "goal_mt",
                                         "relation_type": f"rel_{step % 3}"})
                    cg.set_goal_status("goal_mt", "done" if step % 2 else "active")
            except Exception as exc:  # noqa: BLE001
                _record("writer_keep", exc)

        def _writer_churn():
            try:
                for step in range(24):
                    nid = churn_ids[step % len(churn_ids)]
                    cg.add(nid, _BODY % (nid, f"v{step}"), layer="knowledge",
                           verification_basis="test")
                    if step % 2 == 1:
                        cg._unstage(nid)
            except Exception as exc:  # noqa: BLE001
                _record("writer_churn", exc)

        def _superseded_reader():
            try:
                i = 0
                while not stop.is_set():
                    nid = keep_ids[i % len(keep_ids)]
                    cg._dirty_entry_superseded(nid)
                    cg.get(nid, probe=False)
                    cid = churn_ids[i % len(churn_ids)]
                    cg._dirty_entry_superseded(cid)
                    cg.get(cid, probe=False)
                    i += 1
            except Exception as exc:  # noqa: BLE001
                _record("superseded_reader", exc)

        def _rebuilder():
            try:
                for _ in range(4):
                    if stop.is_set():
                        break
                    cg.rebuild_index()
                    time.sleep(0.01)
            except Exception as exc:  # noqa: BLE001
                _record("rebuilder", exc)

        def _flusher():
            try:
                while not stop.is_set():
                    cg.flush()
                    time.sleep(0.005)
            except Exception as exc:  # noqa: BLE001
                _record("flusher", exc)

        writers = [
            threading.Thread(target=_writer_keep, name="w_keep"),
            threading.Thread(target=_writer_churn, name="w_churn"),
            threading.Thread(target=_rebuilder, name="rebuilder"),
        ]
        daemons = [
            threading.Thread(target=_superseded_reader, name="reader"),
            threading.Thread(target=_flusher, name="flusher"),
        ]
        for th in daemons + writers:
            th.start()
        for th in writers:
            th.join(timeout=30.0)
        stop.set()
        for th in daemons:
            th.join(timeout=15.0)

        alive = [th.name for th in writers + daemons if th.is_alive()]
        ok(not alive, "G4a 全部并发线程按期退出（零死锁）", alive)
        ok(not errors, "G4b 并发碰撞零异常（零 RuntimeError/Set/Dict 竞态）", errors[:5])

        # 收尾：写完后再次 rebuild_index 必须干净清脏集且推进 broad_gen
        cg.flush()
        cg.rebuild_index()
        with cg._dirty_lock:
            dirty_left = len(cg._dirty)
            gen_ok = cg._dirty.broad_gen == cg._dirty.write_gen
        ok(dirty_left == 0 and gen_ok,
           "G4c 收尾 rebuild_index 干净清空 _dirty 且 broad_gen == write_gen（无丢清）",
           {"dirty_left": dirty_left, "gen_ok": gen_ok})
        ok(cg.flush_state()["last_error"] is None,
           "G4d 后台刷盘零失败（flush_state().last_error 为 None）",
           cg.flush_state())
    finally:
        cg.close()

    reopened = MdCG(r, async_flush=False)
    try:
        missing = [nid for nid in keep_ids if reopened.get(nid, probe=False) is None]
        ok(not missing, "G4e 重开库后全部保留节点可读回", missing[:5])
    finally:
        reopened.close()


def main() -> int:
    tmp_root = tempfile.mkdtemp(prefix="mdcg_dlock_")
    try:
        print("MdCG 既有锁外 `_dirty` 调用点守卫")
        g1_lock_protection_and_ordering(tmp_root)
        g2_no_io_under_dirty_lock(tmp_root)
        g3_ast_and_mutation_controls(tmp_root)
        g4_multithreaded_stress(tmp_root)
        print("\n守卫结果：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
        return 1 if _FAIL else 0
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
