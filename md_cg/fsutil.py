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


# 生效条件：tmp 与 path 给定后循环至多 _RENAME_TRIES 次调用 os.replace(tmp, path)，成功即返回；仅捕获 PermissionError，非最后一次则 time.sleep(_RENAME_WAIT) 重试，最后一次仍 PermissionError 则抛出。
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


# 生效条件：行为与 _publish 完全一致（直接委派并返回其结果）——公开名，供包内
# 各「tmp + os.replace」原子写点位统一改走带 Windows 短重试的实现。
def publish(tmp: str, path: str):
    """`os.replace` 的公开安全版：目标被 Defender/索引器短暂持锁时短重试。

    2026-09-25 全量回归实测：裸 `os.replace` 在 Windows 上随机抛
    `PermissionError: [WinError 5]`（retr_s7 的 _postings_meta.json 改名中招，
    失败者随机分布）——md_cg 内原子写一律经本函数，不再各写各的裸 replace。
    """
    return _publish(tmp, path)


# 生效条件：path 与 data 给定时取 path 所在目录 d 建目录，用 tempfile.mkstemp 在 d 内建临时文件按 encoding 写入 data，durable 为真才 flush+os.fsync（假值不 fsync），再经 _publish(tmp, path) 替换；任一步失败时 finally 里若 tmp 仍非 None 且 os.path.exists(tmp) 为真则 os.remove（OSError 忽略）。
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


# 生效条件：os.path.isdir(d) 为假时直接返回；否则对 d 下名字以 "." 开头且含 ".tmp-" 的条目，当 now - os.path.getmtime(p) > older_than 时 os.remove(p)（OSError 忽略），其余条目不动。
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


# 生效条件：path 加 ".lock" 后缀作为锁文件，进入时按 timeout 秒内以 poll 间隔轮询获取 OS 级排它锁（IS_WIN 用 msvcrt.locking 锁首字节，否则 fcntl.flock），超时仍未获锁时 strict 为真抛 TimeoutError、否则返回自身放行。
class FileLock:
    """跨进程排它锁（OS 级）。

    Windows 用 msvcrt.locking 锁首字节，Unix 用 fcntl.flock。两者语义不同
    （前者是强制字节范围锁、后者是建议性文件锁），但对「同一把锁文件、所有
    写者都主动获取」这个用法是等价的。

    超时后放弃并放行（best-effort）：写被拒绝的代价大于一次竞态——这与
    deja-vu 对 usage 日志锁的取舍一致（"a racing write beats a lost injection"）。

    strict=True 反转该取舍：超时抛 TimeoutError 而非放行。适用于**不能丢的写**
    （审核队列 inbox/decisions、裁决记录）——锁竞争失败时显式报错让调用方重试，
    好过静默放行后退化为无锁并发（丢一条提案/裁决比让写入者等一下代价大）。
    """

# 生效条件：path 加 ".lock" 后缀存入 self.path，timeout、poll、strict 原样保存，并置 self._f = None、self.acquired = False。
    def __init__(self, path: str, timeout: float = 10.0, poll: float = 0.01,
                 strict: bool = False):
        self.path = path + ".lock"
        self.timeout = timeout
        self.poll = poll
        self.strict = strict
        self._f = None
        self.acquired = False

# 生效条件：先按 self.path 建父目录并 open(self.path, "a+b")，再在 self.timeout 到期前每 self.poll 秒尝试加锁（IS_WIN 用 msvcrt.locking(LK_NBLCK)，否则 fcntl.flock(LOCK_EX|LOCK_NB)）；成功即置 self.acquired=True 并返回 self；OSError 的 errno 不在 (EACCES, EAGAIN, EDEADLK) 时直接 raise，超时后 self.strict 为真抛 TimeoutError、否则返回 self 放行。
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
                    if self.strict:
                        raise TimeoutError(
                            f"FileLock 超时未获锁（strict）：{self.path}")
                    return self          # 放行，不阻断写路径
                time.sleep(self.poll)

# 生效条件：self.acquired 为真时按 IS_WIN 用 msvcrt.locking(LK_UNLCK) 或 fcntl.flock(LOCK_UN) 解锁（OSError 被吞掉）；finally 中只要 self._f 为真就 close，随后 self._f=None、self.acquired=False。
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


# 生效条件：os.path.getsize(path) 为 0 时返回 False；否则二进制打开 path 并从 size-1 处读 1 字节，返回 f.read(1) != b"\n"；getsize/open/seek/read 抛 OSError 时返回 False。
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


# 生效条件：record 序列化为 json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"；若 ends_mid_line(path) 为真则在行首再补一个 "\n"；随后建父目录并以 O_CREAT|O_WRONLY|O_APPEND、权限 0o600 打开 path 写入该行 UTF-8 字节后关闭。
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


# 生效条件：os.path.exists(path) 为假时生成器直接结束不产出；否则逐行 strip，空行跳过，json.loads 成功则 yield 该对象，抛 ValueError 的行跳过，其余异常不捕获。
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


# 生效条件：os.path.exists(path) 为假时返回 ([], None)；否则以二进制只读打开并 seek 到 offset 后一次性读到 EOF，按 b"\n" 切行逐段 decode("utf-8","replace") 再 strip，空行跳过，json.loads 成功的收入列表，ValueError 跳过；返回 (对象列表, offset+读到的字节数)——EOF 偏移是真实消费位置（stat 与 read 之间并发 append 的字节已计入），供增量缓存作水位。
def read_jsonl_tail(path: str, offset: int):
    """从字节偏移 offset 起**增量**读 append-only jsonl → `(records, end_offset)`。

    存在理由（issue #32）：propose 等高频对账每次全量重读 inbox/decisions
    是 O(M+D)/条、批量 O(M²)；append-only 契约（写点全部经 append_jsonl，
    无轮转/截断）下「上次扫描到的 size」必为行边界，从该偏移起只解析新增
    字节即可。上一次写入中断在行中间（ends_mid_line 补 \\n 场景）时，残行
    前半已在上一轮装载中被跳过、增量窗口读到的是补写的换行与新行——与
    全量 read_jsonl 的容错结果一致。

    返回值（水位口径，竞态修复）：end_offset 是**实际读到的 EOF 位置**。
    调用方若把「读前 stat 的 size」当水位，stat→read 窗口内的跨进程
    append 会在本轮被并入、而水位偏小——下一轮增量从旧水位重读，同一条
    记录在列表型缓存里重复并入且永不自愈。存本函数返回的 end_offset
    即可精确续读。**读后再 stat 不可取**：re-stat 可能大于已消费位置，
    下轮会跳过未读记录（丢账比重复更糟）。文件不存在返回 (list, None)，
    调用方自行回落。
    """
    if not os.path.exists(path):
        return [], None
    recs = []
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    for b in data.split(b"\n"):
        line = b.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except ValueError:
            continue
    return recs, offset + len(data)


_COUNT_CACHE = {}          # abspath -> (bytes_scanned, mtime_ns, lines)


# ---------- N225（2026-09-29）：非对象记录行的可观测记账 ----------
#
# 分片日志的读面必须**容忍**非对象行（`null` / `[]` / `123` / `"abc"` 都是
# 合法 JSON，`read_jsonl` 按「JSON 合法性」收行 ⇒ 它们会进调用方的记录
# 列表），否则排序键 `r.get("_t", 0)` 抛 AttributeError，索引装载 / compact
# 整链断裂（实测：MdCG 构造失败、常驻服务起不来）。但**容忍 ≠ 静默**：
# 跳过必须留下机器可读的痕迹——否则「日志里混进了坏行」与「记录本就不
# 存在」不可区分，索引静默少几条，运维与守卫都看不见。故此处是跳过面的
# 唯一记账点：模块级累计计数 + 有界样本 + stderr 汇总告警（每条分片一行，
# 不逐行刷屏）。
#
# N225 补强（2026-09-29，深度 2 同族面）：同一记账面再收两类**dict 行内**的坏型
# （N225 v1.0 报告 §0「已知缺口」点名的深度 2 复发面，此前不在任何断言面内）：
#   ① 载荷坏型：分片记录 `e` 非 dict 且非 None——判据在重放面（mdcg 的两条重放
#      路径同一实现），经 note_bad_payload_rows 记账；
#   ② 排序键坏型：`_t` / `_s` 非数值（或 NaN）——read_all 的排序键健壮化与记账
#      必须同时发生，经 note_bad_sortkey_rows 记账。
# 三类**合计**进 NONOBJECT_ROW_SKIPS（这就是「同一记账面」的字面口径），各子面
# 另留独立计数与样本，运维据此区分「行根本不是对象」/「行是对象而载荷坏了」/
# 「行的排序键坏了」——三者排查方向不同。kind 名：非对象行 / 载荷坏型 / 排序键坏型。
NONOBJECT_ROW_SKIPS = 0        # 累计跳过的坏记录行数（三类合计，进程内）
NONOBJECT_ROW_SAMPLES = []     # 非对象行样本：(分片路径, 行号, JSON 类型名)
BAD_PAYLOAD_ROW_SKIPS = 0      # 载荷坏型子面：(e 非 dict 且非 None) 条数
BAD_PAYLOAD_ROW_SAMPLES = []   # 载荷坏型样本：(来源标签, 记录 id, 载荷类型名)
BAD_SORTKEY_ROW_SKIPS = 0      # 排序键坏型子面：(_t/_s 非数值或 NaN) 条数
BAD_SORTKEY_ROW_SAMPLES = []   # 排序键坏型样本：(分片路径, 行号, (t 类型名, s 类型名))
_NONOBJECT_SAMPLE_CAP = 32     # 样本上限：记账要有界，不随坏行线性涨


# 生效条件：skips 为 (分片路径, 行号, 值) 三元组序列且非空时，把条数累加进 NONOBJECT_ROW_SKIPS、按 _NONOBJECT_SAMPLE_CAP 上限补样本，并向 sys.stderr 写一行汇总告警（含分片名、本次条数、首条行号与类型名、累计条数）；skips 为空序列或假值时立即返回、不写任何输出。
def note_nonobject_rows(skips):
    """登记一批被跳过的非对象记录行 + stderr 告警（N225 可观测面）。"""
    if not skips:
        return
    global NONOBJECT_ROW_SKIPS
    NONOBJECT_ROW_SKIPS += len(skips)
    for item in skips:
        if len(NONOBJECT_ROW_SAMPLES) >= _NONOBJECT_SAMPLE_CAP:
            break
        NONOBJECT_ROW_SAMPLES.append((item[0], item[1],
                                      type(item[2]).__name__))
    path, lineno, value = skips[0]
    sys.stderr.write(
        "[fsutil] ShardedLog.read_all 跳过 %d 条非对象记录行（分片 %s，"
        "首条 行%d 类型=%s）——坏行不进索引重放；本次后进程内累计 %d 条。"
        "排查方向：该分片被非本协议写入方污染，或发生过截断 / 粘连。\n"
        % (len(skips), os.path.basename(path), lineno,
           type(value).__name__, NONOBJECT_ROW_SKIPS))


# 生效条件：无入参，返回二元组 (累计坏行条数, 非对象行样本元组副本)——累计数为三类合计（非对象行 + 载荷坏型 + 排序键坏型），样本元素为 (分片路径, 行号, JSON 类型名) 且只含非对象行一类，副本只读、调用方改动不影响记账面。
def nonobject_row_stats():
    """读坏行记账合计（只读）：(累计条数, 非对象行样本元组)。

    累计数是**同一记账面**的合计（三类 kind 都计入）；按 kind 的分项见
    bad_payload_row_stats / bad_sortkey_row_stats。
    """
    return NONOBJECT_ROW_SKIPS, tuple(NONOBJECT_ROW_SAMPLES)


# 生效条件：skips 为 (来源标签, 记录 id, 载荷值) 三元组序列且非空时，把 len(skips) 同时累加进 NONOBJECT_ROW_SKIPS（同一记账面）与 BAD_PAYLOAD_ROW_SKIPS（子面），按 _NONOBJECT_SAMPLE_CAP 上限补 BAD_PAYLOAD_ROW_SAMPLES（元素为 (来源标签, str(记录 id), 载荷类型名)），并向 sys.stderr 写一行载荷坏型汇总告警（含来源基名、本次条数、首条 id 与类型名、进程内累计条数）；skips 为空序列或假值时立即返回——不写输出、不动任何计数。
def note_bad_payload_rows(skips):
    """登记一批被跳过的**载荷坏型**记录（`e` 非 dict 且非 None）+ stderr 告警。

    与 note_nonobject_rows 同一个记账面（合计进 NONOBJECT_ROW_SKIPS），但样本
    与告警文案分开：运维据此区分「行本身不是对象」与「行是对象而载荷坏了」。
    记录**不落进索引**由调用方（重放路径）负责，本函数只记账。计数只在这里加，
    调用方不得另立计数器（`_count_buckets` 那条下游不做类型检查，正是靠这里
    把坏载荷挡在 `nodes` 之外）。
    """
    if not skips:
        return
    global NONOBJECT_ROW_SKIPS, BAD_PAYLOAD_ROW_SKIPS
    NONOBJECT_ROW_SKIPS += len(skips)
    BAD_PAYLOAD_ROW_SKIPS += len(skips)
    for item in skips:
        if len(BAD_PAYLOAD_ROW_SAMPLES) >= _NONOBJECT_SAMPLE_CAP:
            break
        BAD_PAYLOAD_ROW_SAMPLES.append((item[0], str(item[1]),
                                        type(item[2]).__name__))
    source, nid, value = skips[0]
    sys.stderr.write(
        "[fsutil] 分片重放跳过 %d 条载荷坏型记录（e 非 dict 且非 None，来源 %s，"
        "首条 id=%s 载荷类型=%s）——坏载荷不进索引节点；本次后进程内累计 %d 条"
        "（含非对象行）。排查方向：该分片被按别的协议写入，或载荷被外部改写。\n"
        % (len(skips), os.path.basename(str(source)), nid,
           type(value).__name__, NONOBJECT_ROW_SKIPS))


# 生效条件：无入参，返回二元组 (载荷坏型累计条数, 样本元组副本)——样本元素为 (来源标签, 记录 id, 载荷类型名)，副本只读、调用方改动不影响记账面。
def bad_payload_row_stats():
    """读载荷坏型子面（只读）：(累计条数, 样本元组)。"""
    return BAD_PAYLOAD_ROW_SKIPS, tuple(BAD_PAYLOAD_ROW_SAMPLES)


# 生效条件：skips 为 (分片路径, 行号, (t 值, s 值)) 三元组序列且非空时，把 len(skips) 同时累加进 NONOBJECT_ROW_SKIPS（同一记账面）与 BAD_SORTKEY_ROW_SKIPS（子面），按 _NONOBJECT_SAMPLE_CAP 上限补 BAD_SORTKEY_ROW_SAMPLES（元素为 (分片路径, 行号, (t 类型名, s 类型名))），并向 sys.stderr 写一行排序键坏型汇总告警（含分片基名、本次条数、首条行号与两个类型名、进程内累计条数）；skips 为空序列或假值时立即返回——不写输出、不动任何计数。
def note_bad_sortkey_rows(skips):
    """登记一批**排序键坏型**记录（`_t` / `_s` 非数值或 NaN）+ stderr 告警。

    与 note_nonobject_rows 同一记账面。**记录本身不丢**（仍是 dict，照常回放，
    只在排序键上按「缺键取 0」的既有口径归一）——故本函数只记账、不改记录：
    丢掉一条合法 dict 记录是比重排它更糟的事。
    """
    if not skips:
        return
    global NONOBJECT_ROW_SKIPS, BAD_SORTKEY_ROW_SKIPS
    NONOBJECT_ROW_SKIPS += len(skips)
    BAD_SORTKEY_ROW_SKIPS += len(skips)
    for item in skips:
        if len(BAD_SORTKEY_ROW_SAMPLES) >= _NONOBJECT_SAMPLE_CAP:
            break
        raw = item[2]
        BAD_SORTKEY_ROW_SAMPLES.append(
            (item[0], item[1], (type(raw[0]).__name__, type(raw[1]).__name__)))
    path, lineno, raw = skips[0]
    sys.stderr.write(
        "[fsutil] ShardedLog.read_all 排序键坏型 %d 条（分片 %s，首条 行%d "
        "_t=%s _s=%s）——坏型槽记 0 参与排序（记录不丢）；本次后进程内累计 %d 条"
        "（含非对象行）。排查方向：该分片被非本协议写入方污染。\n"
        % (len(skips), os.path.basename(path), lineno,
           type(raw[0]).__name__, type(raw[1]).__name__, NONOBJECT_ROW_SKIPS))


# 生效条件：无入参，返回二元组 (排序键坏型累计条数, 样本元组副本)——样本元素为 (分片路径, 行号, (t 类型名, s 类型名))，副本只读、调用方改动不影响记账面。
def bad_sortkey_row_stats():
    """读排序键坏型子面（只读）：(累计条数, 样本元组)。"""
    return BAD_SORTKEY_ROW_SKIPS, tuple(BAD_SORTKEY_ROW_SAMPLES)


# 生效条件：无入参，把三类累计条数（NONOBJECT_ROW_SKIPS / BAD_PAYLOAD_ROW_SKIPS / BAD_SORTKEY_ROW_SKIPS）全置 0 并把三个样本列表原地清空（del [:]，不换对象）；守卫与运维建立观测基线时用，生产读路径不调用。
def reset_nonobject_row_stats():
    """清空整个坏行记账面（含两类子面；守卫 / 运维的观测基线用）。"""
    global NONOBJECT_ROW_SKIPS, BAD_PAYLOAD_ROW_SKIPS, BAD_SORTKEY_ROW_SKIPS
    NONOBJECT_ROW_SKIPS = 0
    BAD_PAYLOAD_ROW_SKIPS = 0
    BAD_SORTKEY_ROW_SKIPS = 0
    del NONOBJECT_ROW_SAMPLES[:]
    del BAD_PAYLOAD_ROW_SAMPLES[:]
    del BAD_SORTKEY_ROW_SAMPLES[:]


# 生效条件：os.stat(os.path.abspath(path or "")) 抛 OSError 时返回 0；缓存命中且已扫字节数与 mtime_ns 均与 stat 一致时直接返回缓存计数；若缓存已扫字节 < 当前 size 且 mtime_ns 不同则从该偏移起按 chunk 分块累计 b"\n" 个数并加上缓存值；读文件抛 OSError 时返回 total or 0（已累计值为假则返回 0）。
def count_jsonl(path: str, chunk: int = 1 << 20) -> int:
    """数 append-only 日志的行数——**流式计数、不物化**（内存 O(1)）。

    存在的唯一理由：`len(list(read_jsonl(p)))` 是**危险的默认写法**。它把整份
    日志解析成对象列表，日志一长就是灾难——本机实测（2026-09-16）：审计日志
    4.3 GB，一次 health/盘点调用解析速率 ~1 MB/s、RSS 涨到 5 GB+ 仍在涨、
    数十分钟不返回；调用方超时重试又在别的进程里再排一次队，最终把整条 MCP
    通道堵死（一个只读的「体检」把服务打死，代价与收益完全不成比例）。
    这里只数字节里的换行：不解析、不驻留，速度只受磁盘限制；进程内按
    (已扫字节数, mtime) 缓存，文件只增长时只扫新增字节（O(增量)）。

    语义边界（诚实声明）：数的是**换行符**，不是 JSON 记录——
      ① 完整写入的日志（`append_jsonl` 每条尾带 `\\n`）换行数 == 记录数，与
         `len(list(read_jsonl(p)))` 逐位相等（test_health_scale ⑦ 守卫）；
      ② 末尾**未终止的半截行**不计入（下界，最多差 1 行；见 append_jsonl 的
         ends_mid_line 修补分支——并发交错被杀的进程会留下这种尾巴）；
      ③ 非法 JSON 行计入行数而 `read_jsonl` 会跳过——健康度是量级指标，不做
         逐行校验，逐行解析正是上面那场事故的根因。
    """
    key = os.path.abspath(path or "")
    try:
        st = os.stat(key)
    except OSError:
        return 0
    start, total = 0, 0
    prev = _COUNT_CACHE.get(key)
    if prev:
        p_scan, p_mtime, p_count = prev
        if p_scan == st.st_size and p_mtime == st.st_mtime_ns:
            return p_count                      # 完全未变：零 IO
        if p_scan < st.st_size and p_mtime != st.st_mtime_ns:
            start, total = p_scan, p_count      # 只增长：扫增量
    scanned, lines = start, 0
    try:
        with open(key, "rb") as f:
            if start:
                f.seek(start)
            while True:
                buf = f.read(chunk)
                if not buf:
                    break
                scanned += len(buf)
                lines += buf.count(b"\n")
    except OSError:
        return total or 0
    total += lines
    _COUNT_CACHE[key] = (scanned, st.st_mtime_ns, total)
    return total


# 生效条件：directory 经 abspath 后作为分片目录并 makedirs(exist_ok=True)，实例分片文件名由 os.getpid() 与 uuid.uuid4().hex[:8] 拼成 "{pid}-{hex8}.log"，append 时各写者只写自己这一分片，从而不共享写入点。
class ShardedLog:
    """每写者独占一个分片的 append-only 日志——不能丢记录时用它。

    单文件 append 要靠 O_APPEND 的原子性，而那在 Windows 上不成立。分片则连
    「共享写入点」都没有：进程 A 写 A 的文件，进程 B 写 B 的文件，物理上无从冲突。
    代价是读取要合并 N 个分片，靠记录里的单调序号 (t, seq) 恢复全局写入顺序。
    """

# 生效条件：directory 经 abspath 存入 self.dir 并 makedirs(exist_ok=True)，self.path 为 self.dir 下 "{os.getpid()}-{uuid.uuid4().hex[:8]}.log"，并置 self._seq = 0、self._fh = None。
    def __init__(self, directory: str):
        self.dir = os.path.abspath(directory)
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(
            self.dir, f"{os.getpid()}-{uuid.uuid4().hex[:8]}.log")
        self._seq = 0
        self._fh = None

# 生效条件：self._seq 先自增 1，record 被 dict(record, _t=time.time(), _s=self._seq) 复制；self._fh 为 None 时以 "a"、encoding="utf-8"、newline="\n" 打开 self.path，随后写入 json.dumps(ensure_ascii=False, separators=(",", ":")) + "\n" 并 flush。
    def append(self, record: dict):
        self._seq += 1
        record = dict(record, _t=time.time(), _s=self._seq)
        if self._fh is None:
            self._fh = open(self.path, "a", encoding="utf-8", newline="\n")
        self._fh.write(json.dumps(record, ensure_ascii=False,
                                  separators=(",", ":")) + "\n")
        self._fh.flush()

# 生效条件：幂等；self._fh 为真值时 flush 并关闭句柄、再把 self._fh 置 None，为 None 时直接返回不报错；
    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None

    @staticmethod
# 生效条件：directory 是目录时，按 sorted(os.listdir(directory)) 顺序对每个以 ".log" 结尾的文件读取汇总（单分片 PermissionError 时以 5ms×8 短重试等 Windows delete-pending 窗口过去、窗口后 FileNotFoundError 视为已被 compact 并入快照清走而跳过、重试耗尽照常 raise），逐行只收 dict 记录——非对象行（null/[]/123/"abc" 等合法 JSON）跳过并经 note_nonobject_rows 记账 + stderr 告警（不得静默）；随后按排序键 (_norm(r.get("_t", 0)), _norm(r.get("_s", 0))) 排序，其中 _norm 只把「数值（int/float，含 bool）且非 NaN」原样透传、其余槽（str/list/dict/None/NaN）一律记 0——坏型槽经 note_bad_sortkey_rows 记账 + stderr 告警（不得静默），记录本身不丢；合法记录（_t/_s 均数值，缺键按默认值 0）的排序键逐位等于旧键 (r.get("_t", 0), r.get("_s", 0))，故其相对次序与改前逐位一致；directory 不是目录时直接返回 []。
    def read_all(directory: str):
        """按全局写入顺序回放所有分片。

        N170（2026-09-27）：并发 compact 的 delete-pending 窗口容忍。他进程
        close→compact_index 的 ShardedLog.clear（mdcg.py:1137，锁内「先并快照
        再删分片」）与本读方的 listdir→open 交错时，Windows 上 open 命中
        「已 remove、名未消」的 delete-pending 态 → PermissionError [Errno 13]
        （test_review_conformance【9】4 decide worker 同根并发实测复现：
        worker 在 MdCGOS.__init__ 崩溃、stdout 空，父进程 json.loads("")
        二次崩成 JSONDecodeError）。短重试等窗口过去：窗口过后文件要么可读、
        要么已真删。已真删（FileNotFoundError）跳过是**安全**的——clear 的
        契约是分片记录先并入快照再删（mdcg.py:1136-1137 顺序），本读方的
        快照基底的陈旧读界与既有「他进程未 flush 写入不可见」边界同格，
        由 _index_signature 指纹机制在下次重载收敛；重试耗尽的 PermissionError
        照常上抛，真权限问题不掩盖。

        N225（2026-09-29）：**非对象行容忍 + 可观测**。`read_jsonl` 按 JSON
        合法性收行，`null` / `[]` / `123` / `"abc"` 都会原样产出；直接进
        `recs` 会让下面的 `r.get("_t", 0)` 抛 AttributeError（实测：MdCG
        构造 + compact_index 双崩）。此处逐行分流：dict 进回放列表，非对象行
        进记账面（note_nonobject_rows → 模块级计数 + 样本 + stderr 告警）。
        分流必须在本层做——`read_jsonl` 的通用契约（其它消费面）不在本次
        范围，不得改。整片读成功才记账：半途重试不重复计数。

        N225 补强（2026-09-29，**排序键健壮化**）：行是 dict 不等于键可排序
        ——`_t` / `_s` 被外部写成 `"abc"` / `[]` / `null` 时，旧键
        `(r.get("_t", 0), r.get("_s", 0))` 在 sort 里抛 TypeError
        （`'<' not supported between instances of 'str' and 'float'`），
        而 except 面只有 ValueError/OSError ⇒ 与 N225 原始缺陷同一条断链，
        只是深度 2（N225 v1.0 报告 §0 已点名的缺口）。现按**单槽归一**处理：
        数值（int/float，含 bool）原样，其余槽记 0——与「缺键取 0」同一口径，
        不新造第二套默认值。归一化真的发生时（归一结果 ≠ 原值对）进
        note_bad_sortkey_rows 记账（**容忍 ≠ 静默**，记录不丢）。
        次序不变性：合法记录的排序键逐位等于旧键 ⇒ 同一稳定排序算法在同一
        输入序列上产出同一次序，故相对次序与改前逐位一致（守卫 F2 用真实
        分片记录与旧键 oracle 逐条对照）。
        """
        if not os.path.isdir(directory):
            return []

        # 生效条件：v 为 int/float（含 bool）且 v == v（非 NaN）时原样返回 v，其余取值（str/list/dict/None/NaN）一律返回 0——排序键单槽归一，NaN 必须排除（`nan == nan` 为假、与任何数比较恒假：它不抛但让次序不确定）。
        def _norm(v):
            return v if (isinstance(v, (int, float)) and v == v) else 0

        recs = []
        for fn in sorted(os.listdir(directory)):
            if not fn.endswith(".log"):
                continue
            p = os.path.join(directory, fn)
            for _attempt in range(8):
                try:
                    batch, skips, badkeys = [], [], []
                    for lineno, rec in enumerate(read_jsonl(p), 1):
                        if not isinstance(rec, dict):
                            skips.append((p, lineno, rec))
                            continue
                        batch.append(rec)
                        raw = (rec.get("_t", 0), rec.get("_s", 0))
                        if (_norm(raw[0]), _norm(raw[1])) != raw:
                            badkeys.append((p, lineno, raw))
                    recs.extend(batch)
                    note_nonobject_rows(skips)
                    note_bad_sortkey_rows(badkeys)
                    break
                except FileNotFoundError:
                    break          # 已被 compact 清走（记录已并入快照）
                except PermissionError:
                    if _attempt == 7:
                        raise
                    time.sleep(0.005)
        recs.sort(key=lambda r: (_norm(r.get("_t", 0)), _norm(r.get("_s", 0))))
        return recs

    @staticmethod
# 生效条件：directory 是目录时，遍历 os.listdir(directory)，对以 ".log" 结尾且不满足「keep 为真值且 os.path.abspath(p) == keep」的条目调用 os.remove（keep 为 None/空串等假值时该排除条件恒不成立，所有 ".log" 条目都会被删），删除时的 OSError 被忽略；directory 不是目录时直接返回。
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