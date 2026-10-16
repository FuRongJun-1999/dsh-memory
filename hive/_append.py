# -*- coding: utf-8 -*-
"""hive 侧权威台账的**跨进程安全追加**收口（issue #465）。

形态来源（**收口，不是新发明**）：本文件是 `md_cg/fsutil.py` 中 `FileLock` 那套跨进程锁形态的
**hive 侧收口**——同名要素：`<target>` + `.lock` 锁文件 / `msvcrt.LK_NBLCK` **锁首字节** /
`fcntl.flock(LOCK_EX | LOCK_NB)` / timeout+poll 轮询 / 显式释放。
为何不直接 import：**hive 是纯标准库面，不得反向依赖 md_cg**（本仓已有 hive/exec.py 反向依赖
被挡住的先例）⇒ 复用**形态**而非**模块**。

为何必须双分支：Windows 无 `fcntl.flock`（`msvcrt.locking` 锁的是**字节区间**，故锁首字节）；
POSIX 无 `msvcrt.locking`。两者语义不同（强制字节范围锁 vs 建议性文件锁），不可互相替代。

同族纪律：`scripts/run_tests.py` 记有仓内纪律「五个记账面的 append 必须全在 `with self._lock:`」
（`md_cg/sustain.py` 五处）——差别只在**那处是进程内锁，本处是跨进程版**（多 worker 场景）。

★判据规模（#465 实测，写在这里因为它是判据的一部分）：**规模选择本身是判据的一部分；
小规模全绿不能作为通过依据。** 实测 `os.open(O_APPEND)`+单次 `os.write` 在 8x400 与 16x400
全绿、在 8x2000 崩（768 条半截、丢 9708）⇒ 按 8x400 写的守卫对新旧实现都会绿。
它与「良性变异必须真的转红」同族，但**更隐蔽：红腿自己不知道自己不判别**。

失败语义（两条**不得混**）：
  (i)  **打不开**锁文件/目标文件 ⇒ 降级 stderr，**绝不打断任务**（对齐 exec_cmd.py 既有生效条件）；
  (ii) **锁竞争超时** ⇒ 也**不打断任务**，但**必须留可观测记录**（stderr + 计数），
       **不得静默丢行**——静默超时只是把「丢行」换成「在另一种条件下丢行且没人知道」。
"""
from __future__ import annotations

import errno
import os
import sys
import time

IS_WIN = os.name == "nt"
if IS_WIN:
    import msvcrt
else:
    import fcntl

LOCK_SUFFIX = ".lock"
DEFAULT_TIMEOUT = 10.0
DEFAULT_POLL = 0.01

#: 可观测降级计数（(ii) 的留痕面之一）：键为 tag。
#: 可观测降级计数（留痕面）：**一个观测只对应一个原因**——三个键分别对应三个不同的失败点，
#: 不得压成一个（本会话「SKIP 冒充 PASS」同族：不同原因产出同一信号，读者无法据以处置）。
DEGRADED = {"lock_file_unavailable": {}, "target_unwritable": {}, "lock_timeout": {}}


def _bump(kind: str, tag: str) -> None:
    d = DEGRADED[kind]
    d[tag] = d.get(tag, 0) + 1


# 生效条件：path 加 ".lock" 后缀建锁文件，timeout 秒内每 poll 秒尝试 OS 级排它锁（IS_WIN 用 msvcrt.locking(LK_NBLCK) 锁首字节，否则 fcntl.flock(LOCK_EX|LOCK_NB)）；获锁返回 True，超时返回 False（不抛、由调用方决定语义）。
def _acquire(path: str, timeout: float, poll: float):
    lk = path + LOCK_SUFFIX
    os.makedirs(os.path.dirname(os.path.abspath(lk)) or ".", exist_ok=True)
    f = open(lk, "a+b")
    deadline = time.time() + timeout
    while True:
        try:
            if IS_WIN:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except OSError as e:
            if e.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                f.close()
                raise
            if time.time() > deadline:
                f.close()
                return None
            time.sleep(poll)


# 生效条件：f 为真时按 IS_WIN 用 msvcrt.locking(LK_UNLCK) 或 fcntl.flock(LOCK_UN) 解锁（OSError 被吞掉），随后关闭。
def _release(f) -> None:
    try:
        if IS_WIN:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        try:
            f.close()
        except OSError:
            pass


# 生效条件：path 与 line 传入即成立；获锁后在锁内**单次写整行**（跨进程串行化），返回 True；打不开文件返回 False 并把该行降级写 stderr（情形 i，绝不打断任务）；锁竞争超时返回 False、把该行降级写 stderr 并计 lock_timeout（情形 ii，不打断但必留痕）。
# 生效条件：path 与 line 传入即成立；获锁后在锁内**单次写整行**（跨进程串行化）并返回 True；
# **打不开**锁文件/目标 ⇒ 降级 stderr、计 open_failed、返回 False（情形 i，绝不打断任务）；
# **锁竞争超时** ⇒ 降级 stderr、计 lock_timeout、返回 False（情形 ii，不打断但**必留痕**）。
# ★一个观测只对应一个原因：(i) 与 (ii) 分别计数、分别措辞，**不得共用一个信号**
# （本会话「SKIP 冒充 PASS」同族）。
def append_line(path: str, line: str, *, timeout: float = DEFAULT_TIMEOUT,
                poll: float = DEFAULT_POLL, tag: str = "hive") -> bool:
    '''跨进程安全追加一行；返回 True=落盘（且已获锁），False=已降级（见 stderr 与 DEGRADED）。'''
    cause = None
    try:
        f = _acquire(path, timeout, poll)
    except OSError as e:                                   # (i) 锁文件打不开
        _bump("lock_file_unavailable", tag)
        sys.stderr.write("[hive._append] 锁文件不可用(%s)：%s\n" % (tag, e))
        f, cause = None, "lock_file_unavailable"
    else:
        if f is None:                                      # (ii) 锁竞争超时
            _bump("lock_timeout", tag)
            cause = "lock_timeout"
            sys.stderr.write("[hive._append] 锁竞争超时(%s, %.2fs)，未获锁：%s\n"
                             % (tag, timeout, path))
    try:
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)                                 # 锁内单次写整行
    except (OSError, TypeError) as e:
        _bump("target_unwritable", tag)
        cause = cause or "target_unwritable"
        sys.stderr.write("[hive._append] 目标不可写(%s)：%s\n" % (tag, e))
        if f is not None:
            _release(f)
        return False
    if f is not None:
        _release(f)
    return cause is None
