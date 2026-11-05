# -*- coding: utf-8 -*-
"""issue #740：`FileLock` 异常路径的 fd 泄漏（进入失败时 `__exit__` 不会被调用）。

## 病灶
`__enter__` 打开 fd 后，两个 raise 路径都不关：
  ① strict 超时 `raise TimeoutError`；② 非重试 errno 的裸 `raise`。
另有两个复核补出的路径：③ `deadline = time.time() + timeout` 抛 TypeError（fd 已开）；
④ `time.sleep` 期间 `KeyboardInterrupt`/`SystemExit`（`except Exception` 接不住）。

## 修法
`try` 紧贴 `open` 之后、`except BaseException` 调 `_close_fd()` 后原样上抛；
`_close_fd` 单点关闭（None 安全、吞 OSError/ValueError、绝不抛）；`__exit__` 复用它；
重复 enter 先清旧句柄；非 strict 放行时显式 `acquired=False`。

## 断言
- L1 strict 超时 ⇒ TimeoutError 且 fd 已关；
- L2 非重试 errno（EIO）⇒ OSError 且 fd 已关；
- L2b sleep 中 KeyboardInterrupt ⇒ 异常原样传播且 fd 已关；
- L3 非 strict 超时 ⇒ 返回自身、acquired=False，退出后 fd 已关；
- L4 双击 `__exit__` 幂等不抛；
- L6 `timeout=None` ⇒ TypeError 且 fd 已关；
- L5（--mutate）把 `_close_fd` 打桩成 no-op ⇒ L1/L2 必须红（证明守卫依赖清理）。

运行：python -X utf8 -m md_cg.test_issue740_filelock_fd_leak [--mutate]
"""
from __future__ import annotations

import builtins
import errno
import os
import shutil
import sys
import tempfile
import time as _time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import fsutil   # noqa: E402

FAILS = []
MAX = 2


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


class FakeMsvcrt:
    LK_NBLCK = 2
    LK_UNLCK = 0

    def __init__(self, err):
        self.err = err

    def locking(self, *_a):
        raise OSError(self.err, "fake lock error")


def _install_lock_stub(err):
    old_win, old_m = fsutil.IS_WIN, getattr(fsutil, "msvcrt", None)
    fsutil.IS_WIN = True
    fsutil.msvcrt = FakeMsvcrt(err)
    return old_win, old_m


def _restore(old_win, old_m):
    fsutil.IS_WIN = old_win
    if old_m is None:
        try:
            del fsutil.msvcrt
        except AttributeError:
            pass
    else:
        fsutil.msvcrt = old_m


def _track_open():
    """包 `builtins.open`：记录返回的文件对象（只记录，不改行为）。"""
    rec = []
    real = builtins.open

    def _o(*a, **k):
        f = real(*a, **k)
        rec.append(f)
        return f

    builtins.open = _o
    return rec, real


def _closed_all(rec):
    return all(getattr(f, "closed", True) for f in rec)


def main():
    print("=" * 68)
    print("issue #740 · FileLock 异常路径 fd 泄漏")
    print("=" * 68)
    mutate = "--mutate" in sys.argv
    if mutate:
        print("!! 变异：把 _close_fd 打桩成 no-op（期望 L1/L2 红）")
    tmp = tempfile.mkdtemp(prefix="iss740_")
    try:
        # L1 strict 超时
        old = _install_lock_stub(errno.EACCES)
        rec, real = _track_open()
        try:
            lock = fsutil.FileLock(os.path.join(tmp, "a"), timeout=0.05, strict=True)
            if mutate:
                lock._close_fd = lambda: None
            raised = False
            try:
                lock.__enter__()
            except TimeoutError:
                raised = True
            ok(raised, "L1 strict 超时抛 TimeoutError")
            ok(lock._f is None, "L1b 失败后不保留句柄", getattr(lock, "_f", "?"))
            ok(_closed_all(rec), "L1c 打开过的 fd 都已关闭", [(f.name, f.closed) for f in rec])
        finally:
            builtins.open = real
            _restore(*old)

        # L2 非重试 errno
        old = _install_lock_stub(errno.EIO)
        rec, real = _track_open()
        try:
            lock2 = fsutil.FileLock(os.path.join(tmp, "b"), timeout=0.05, strict=True)
            if mutate:
                lock2._close_fd = lambda: None
            raised2 = False
            try:
                lock2.__enter__()
            except OSError as e:
                raised2 = e.errno == errno.EIO
            ok(raised2, "L2 非重试 errno 原样抛 OSError(EIO)")
            ok(_closed_all(rec), "L2b 打开过的 fd 都已关闭")
        finally:
            builtins.open = real
            _restore(*old)

        # L2b sleep 中 KeyboardInterrupt
        old = _install_lock_stub(errno.EACCES)
        rec, real = _track_open()
        real_sleep = _time.sleep
        _time.sleep = lambda _s: (_ for _ in ()).throw(KeyboardInterrupt())
        try:
            lock3 = fsutil.FileLock(os.path.join(tmp, "c"), timeout=5.0, strict=True)
            if mutate:
                lock3._close_fd = lambda: None
            raised3 = False
            try:
                lock3.__enter__()
            except KeyboardInterrupt:
                raised3 = True
            ok(raised3, "L2c KeyboardInterrupt 原样传播")
            ok(_closed_all(rec), "L2d 中断路径 fd 也已关闭")
        finally:
            _time.sleep = real_sleep
            builtins.open = real
            _restore(*old)

        # L6 timeout=None ⇒ TypeError 且已关
        old = _install_lock_stub(errno.EACCES)
        rec, real = _track_open()
        try:
            lock4 = fsutil.FileLock(os.path.join(tmp, "d"), timeout=None, strict=True)
            raised4 = False
            try:
                lock4.__enter__()
            except TypeError:
                raised4 = True
            ok(raised4, "L6 timeout=None ⇒ TypeError")
            ok(_closed_all(rec), "L6b 该类 TypeError 路径 fd 也已关闭")
        finally:
            builtins.open = real
            _restore(*old)

        # L3 非 strict 放行
        old = _install_lock_stub(errno.EACCES)
        rec, real = _track_open()
        try:
            lock5 = fsutil.FileLock(os.path.join(tmp, "e"), timeout=0.02, strict=False)
            got = lock5.__enter__()
            ok(got is lock5 and lock5.acquired is False, "L3 非 strict 超时放行且标记未持锁")
            lock5.__exit__(None, None, None)
            ok(lock5._f is None, "L3b 退出后句柄已关")
        finally:
            builtins.open = real
            _restore(*old)

        # L4 双击 exit 幂等
        lock6 = fsutil.FileLock(os.path.join(tmp, "f"), timeout=0.01, strict=False)
        old = _install_lock_stub(errno.EACCES)
        try:
            lock6.__enter__()
            lock6.__exit__(None, None, None)
            lock6.__exit__(None, None, None)
            ok(True, "L4 双击 __exit__ 幂等不抛")
        except Exception as e:   # noqa: BLE001
            ok(False, "L4 双击 __exit__ 幂等不抛", e)
        finally:
            _restore(*old)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("issue #740：%d 项失败" % len(FAILS) if FAILS else "issue #740：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())