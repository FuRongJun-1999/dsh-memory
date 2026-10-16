# -*- coding: utf-8 -*-
"""hive 台账跨进程原子追加单点（issue #465）。

靶面（修前）：hive 的三处权威台账均为 open("a") 逐条写、无跨进程锁——
hive/scoreboard.py 的 _scoreboard.jsonl、hive/orch.py 的 _adjudication.jsonl、
hive/exec_cmd.py 的 log.txt。8 worker 并发追加实测丢 221–279 行 + 撕裂半截行
（Windows CRT 的 O_APPEND 是 lseek(END)+write 两步，非原子），而单 worker /
bulk 一次写完整——「可审计可回放」实为静默丢记录。

本模块是该语义的唯一实现（判据单点）：
  · 池级互斥：复用 md_cg.fsutil.FileLock（<path>.lock；Windows msvcrt / Unix
    flock），strict=True——锁超时显式抛 TimeoutError，不静默退化为无锁并发；
  · 单次写：O_APPEND + 单次 os.write（整行一次落盘），短写抛 OSError——
    不静默接受半行；
  · 失败语义：OSError / TimeoutError 一律上抛，由调用方按台账性质决定
    （权威台账不得静默丢；观测面可降级 stderr）。

边界（如实）：本件只解决「并发丢行 / 撕裂」；每行 seq + 尾部校验（issue #465
修复建议的第二段）未纳入，另案。
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg.fsutil import FileLock  # noqa: E402


# 生效条件：line 为非 str 时 TypeError 上抛（调用方契约错，不猜）；否则补足末尾换行、
# UTF-8 编码、建父目录，在 FileLock(path, strict=True) 内以 O_APPEND + 单次 os.write
# 整行写入；短写抛 OSError；OSError/TimeoutError 一律上抛，返回 None。
def append_line(path: str, line: str, *, lock_timeout: float = 30.0) -> None:
    """把一行文本原子追加到 path：池级互斥 + 单次 write（整行或抛错）。"""
    if not isinstance(line, str):
        raise TypeError("append_line 只接受 str 行，得到 %s" % type(line).__name__)
    if not line.endswith("\n"):
        line += "\n"
    data = line.encode("utf-8")
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with FileLock(path, timeout=lock_timeout, strict=True):
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        try:
            n = os.write(fd, data)
            if n != len(data):
                raise OSError(
                    "短写：%d/%d 字节（不静默接受半行，issue #465）"
                    % (n, len(data)))
        finally:
            os.close(fd)
