# -*- coding: utf-8 -*-
"""md 认知图 · 文件系统原语（原子写 / 跨进程锁 / append-only 日志）

纯标准库（D-005）。三个原语都直接对应竞品踩过的坑：

1. 原子写：临时名必须唯一。deja-vu 的 atomicfile 记录了固定临时名的后果——
   两个写者共享同一临时文件，第二个截断第一个还在写的内容，第一个把半截文件
   rename 到位（18049 次读里 180 次读到不可解析的记录）。
2. Windows rename：另一个进程持有打开句柄时 os.replace 会被拒绝。deja-vu 在
   windows CI 上实测「四个并发写者有三个被拒」，解法是短重试。
3. 跨进程锁：threading.Lock 只管本进程；灵枢是多进程共享库，必须用 OS 级锁。
"""
import os
import sys
import time
import uuid
import errno
import json
import tempfile

IS_WIN = sys.platform == "win32"
if IS_WIN:
    import msvcrt
else:
    import fcntl

_RENAME_TRIES = 20
_RENAME_WAIT = 0.005


def _publish(tmp: str, path: str):
    """把临时文件 rename 到位，Windows 上短重试。"""
    for i in range(_RENAME_TRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == _RENAME_TRIES - 1:
                raise
            time.sleep(_RENAME_WAIT)


def atomic_write(path: str, data: str, encoding: str = "utf-8", durable: bool = False):
    """整文件替换。临时文件与目标同目录（保证同一文件系统，rename 才原子），
    临时名唯一（并发写者不共享），失败即清理而不是留在可能刚写满的磁盘上。

    durable=False（默认）：不做 fsync。
      崩溃一致性由「临时文件 + rename」保证——读者要么看到旧内容、要么看到
      新内容，永远看不到半截文件；fsync 多保证的只是"断电后新内容不丢"。
      实测每次 fsync 让写入从 ~2000 节点/秒掉到 17 节点/秒（3048 节点迁移
      要 3 分钟），而节点 .md 丢失的代价只是丢那一个节点，且索引可重建。
      deja-vu 的 atomicfile 同样只做 Close + Rename，不 fsync。
    durable=True：留给确实需要断电存活的调用方。
    """
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".tmp-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as f:
            f.write(data)
            if durable:
                f.flush()
                os.fsync(f.fileno())
        _publish(tmp, path)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def sweep_stale_temps(d: str, older_than: float = 3600):
    """清理被杀死的进程留下的唯一命名临时文件（它们不会被下一个写者复用清掉）。"""
    if not os.path.isdir(d):
        return
    now = time.time()
    for name in os.listdir(d):
        if ".tmp-" not in name or not name.startswith("."):
            continue
        p = os.path.join(d, name)
        try:
            if now - os.path.getmtime(p) > older_than:
                os.remove(p)
        except OSError:
            pass


class FileLock:
    """跨进程排它锁（OS 级）。

    Windows 用 msvcrt.locking 锁首字节，Unix 用 fcntl.flock。两者语义不同
    （前者是强制字节范围锁、后者是建议性文件锁），但对「同一把锁文件、所有
    写者都主动获取」这个用法是等价的。

    超时后放弃并放行（best-effort）：写被拒绝的代价大于一次竞态——这与
    deja-vu 对 usage 日志锁的取舍一致（"a racing write beats a lost injection"）。
    """

    def __init__(self, path: str, timeout: float = 10.0, poll: float = 0.01):
        self.path = path + ".lock"
        self.timeout = timeout
        self.poll = poll
        self._f = None
        self.acquired = False

    def __enter__(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        self._f = open(self.path, "a+b")
        deadline = time.time() + self.timeout
        while True:
            try:
                if IS_WIN:
                    self._f.seek(0)
                    msvcrt.locking(self._f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(self._f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.acquired = True
                return self
            except OSError as e:
                if e.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.time() > deadline:
                    return self          # 放行，不阻断写路径
                time.sleep(self.poll)

    def __exit__(self, *exc):
        try:
            if self.acquired:
                if IS_WIN:
                    self._f.seek(0)
                    msvcrt.locking(self._f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            if self._f:
                self._f.close()
            self._f = None
            self.acquired = False


def ends_mid_line(path: str) -> bool:
    """行式日志的最后一字节是否不是换行——即上一个写者被杀死留下的半截记录。
    追加者若不先补一个换行，新记录会粘在这行上，两条都解析不出来。"""
    try:
        size = os.path.getsize(path)
        if size == 0:
            return False
        with open(path, "rb") as f:
            f.seek(size - 1)
            return f.read(1) != b"\n"
    except OSError:
        return False


def append_jsonl(path: str, record: dict):
    """向 append-only 日志追加一条记录（best-effort 语义）。

    注意 O_APPEND 的原子性是**平台相关**的：POSIX 保证「定位到末尾 + 写入」是
    一个原子操作，Windows CRT 的 _O_APPEND 则是 lseek(END) + write 两步，并发下
    会偶发交错丢记录（实测 6 进程 × 40 条，每轮丢 ~1 条）。

    因此本函数只用于**丢一条无所谓**的簿记（访问计数）。任何不能丢的东西
    （比如索引增量）必须用 ShardedLog——每个写者独占一个分片，不共享写入点。
    """
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    if ends_mid_line(path):
        line = "\n" + line
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def read_jsonl(path: str):
    """读 append-only 日志，跳过被截断/粘连的坏行（不因自身簿记而失败）。"""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


class ShardedLog:
    """每写者独占一个分片的 append-only 日志——不能丢记录时用它。

    单文件 append 要靠 O_APPEND 的原子性，而那在 Windows 上不成立。分片则连
    「共享写入点」都没有：进程 A 写 A 的文件，进程 B 写 B 的文件，物理上无从冲突。
    代价是读取要合并 N 个分片，靠记录里的单调序号 (t, seq) 恢复全局写入顺序。
    """

    def __init__(self, directory: str):
        self.dir = os.path.abspath(directory)
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(
            self.dir, f"{os.getpid()}-{uuid.uuid4().hex[:8]}.log")
        self._seq = 0
        self._fh = None

    def append(self, record: dict):
        self._seq += 1
        record = dict(record, _t=time.time(), _s=self._seq)
        if self._fh is None:
            self._fh = open(self.path, "a", encoding="utf-8", newline="\n")
        self._fh.write(json.dumps(record, ensure_ascii=False,
                                  separators=(",", ":")) + "\n")
        self._fh.flush()

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None

    @staticmethod
    def read_all(directory: str):
        """按全局写入顺序回放所有分片。"""
        if not os.path.isdir(directory):
            return []
        recs = []
        for fn in sorted(os.listdir(directory)):
            if not fn.endswith(".log"):
                continue
            recs.extend(read_jsonl(os.path.join(directory, fn)))
        recs.sort(key=lambda r: (r.get("_t", 0), r.get("_s", 0)))
        return recs

    @staticmethod
    def clear(directory: str, keep: str = None):
        """合并进快照后清理分片。keep 用于保留当前进程正在写的那个。"""
        if not os.path.isdir(directory):
            return
        for fn in os.listdir(directory):
            p = os.path.join(directory, fn)
            if not fn.endswith(".log") or (keep and os.path.abspath(p) == keep):
                continue
            try:
                os.remove(p)
            except OSError:
                pass
