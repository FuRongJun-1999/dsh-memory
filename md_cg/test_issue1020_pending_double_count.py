# -*- coding: utf-8 -*-
"""Regression guard for #1020: pending_dirty must never double-count a batch.

The failure path of MdCG._flush_locked refills _dirty under one lock hold and
(until this fix) cleared _flush_inflight in a *second* lock hold inside
finally. Between the two, an observer calling flush_state() sees the same
records in both collections and reports pending_dirty == 2 for one record.

Guard: PD-5 samples pending_dirty at every release of _dirty_lock during a
failing flush and asserts the observed value never exceeds the true number of
pending records.
"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest import mock

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import fsutil  # noqa: E402
from md_cg.mdcg import MdCG  # noqa: E402

PASS = 0
FAIL = 0
FAILS = []

BODY = (
    "# 功能名：{title}\n"
    "# 生效条件：测试\n"
    "# 子功能：s\n"
    "# 执行：{act}\n"
    "# 验证方式：test\n"
    "# 不适用条件：无\n"
)


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:260])
    return bool(cond)


class _LockProbe(object):
    """Transparent proxy for _dirty_lock that samples pending counts on release."""

    def __init__(self, real, cg):
        self._real = real
        self._cg = cg
        self._depth = 0
        self.samples = []

    def acquire(self, *a, **kw):
        got = self._real.acquire(*a, **kw)
        self._depth += 1
        return got

    def release(self):
        self._depth -= 1
        self._real.release()
        self._sample()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False

    def _sample(self):
        if self._depth:
            return
        self._depth += 1
        try:
            self._real.acquire()
            try:
                self.samples.append(len(self._cg._dirty) + len(self._cg._flush_inflight))
            finally:
                self._real.release()
        finally:
            self._depth -= 1


def test_pending_dirty_no_double_count_on_failed_flush():
    print("== PD-5: failing flush must not double-count pending_dirty ==")
    root = tempfile.mkdtemp(prefix="iss1020_pd_")
    cg = MdCG(root, autoflush=1000, async_flush=False)
    cg.add("seed_1020", BODY.format(title="s", act="v1"),
           layer="knowledge", tags=["v1"], importance=0.5,
           verification_basis="test")
    cg.flush()
    check("PD-5a baseline: nothing pending after a clean flush",
          cg.flush_state()["pending_dirty"] == 0,
          cg.flush_state()["pending_dirty"])

    cg.add("seed_1020", BODY.format(title="s", act="v2"),
           layer="knowledge", tags=["v2"], importance=0.6,
           verification_basis="test")
    true_pending = cg.flush_state()["pending_dirty"]
    check("PD-5b exactly one record is pending before the failing flush",
          true_pending == 1, true_pending)

    probe = _LockProbe(cg._dirty_lock, cg)
    cg._dirty_lock = probe
    try:
        with mock.patch.object(fsutil.ShardedLog, "append_many",
                               side_effect=OSError("disk busy")):
            raised = False
            try:
                cg.flush()
            except OSError:
                raised = True
    finally:
        cg._dirty_lock = probe._real

    worst = max(probe.samples) if probe.samples else 0
    check("PD-5c failed flush actually raised", raised, raised)
    check("PD-5d pending_dirty never exceeds the true pending count during flush",
          worst <= true_pending, (worst, true_pending, probe.samples))
    check("PD-5e rollback keeps the record in _dirty and clears _flush_inflight",
          "seed_1020" in cg._dirty and not cg._flush_inflight,
          (list(cg._dirty), cg._flush_inflight))
    check("PD-5f post-failure pending_dirty still reads 1 (no phantom extra)",
          cg.flush_state()["pending_dirty"] == 1, cg.flush_state()["pending_dirty"])
    cg.close()


def main():
    test_pending_dirty_no_double_count_on_failed_flush()
    print("")
    print("== summary: %d pass / %d fail ==" % (PASS, FAIL))
    for f in FAILS:
        print("  FAILED: " + f)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())