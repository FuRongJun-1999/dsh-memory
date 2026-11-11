# -*- coding: utf-8 -*-
"""脏集哨兵：写代际字典 `DirtyDict`（原 `mdcg._DirtyDict` 的权威位置）。

纯搬家（2026-11-11 深度重构·任务 4）：本模块是一个**无外部依赖**的独立模块，
只依赖标准库 `os` / `hashlib`。历史上它内联在 `mdcg.py`（一个 6.8k 行、承载
整个认知图内核的巨型模块）里，但它与 `MdCG` **没有任何耦合**——`MdCG.__init__`
只负责注入 `root`，类本身不反查宿主（见 `DirtyDict.__init__` 的注释）。故它
按「模块边界」自然归属到本模块，`mdcg.py` 保留 re-export shim
（`from .dirtydict import DirtyDict as _DirtyDict`），对外符号名与行为逐位不变。

语义不变量（搬家不改判据，仅集中文档）：

  · `write_gen` **单调自增、永不回退**。为什么不用 `len(self)` 作写代际：
    flush 后脏集清零，新写入会使长度**回到旧值**——代际巧合回退会让读缓存
    误命中陈旧内容（v20 `v20_d4_repro.py` stale=True 实测）。
  · 消费方纪律：flush/rebuild 清空必须走 `.clear()`（保住子类钩子），
    **不得** `self._dirty = {}` 直接换新 dict——那会退化为普通 dict，
    `write_gen` 恒 0、读缓存失效面随之失效。
"""
import os
import hashlib


# 生效条件：fp 为可读文件路径时返回其**整文件字节**的 sha256 十六进制摘要前 16 位；open/read 抛 OSError 时返回 None（读不到即「证不出」，调用方据此走 fail-open 分支）；不缓存、不解析、不看扩展名。
def file_digest(fp: str):
    """节点文件的**整字节身份指纹**（#80）。

    为什么不用 nodefile.content_hash：那只哈希**正文**、按纪律**不含
    frontmatter**（nodefile.py:314-316）——frontmatter 被单独改写时它不变，
    不足以回答「这个文件还是我标脏时那个文件吗」。本判据要的正是**整文件
    逐字身份**，故直接哈希盘面字节。

    为什么截 16 位：与全仓 sha256 系列（nodefile.content_hash 截 12、
    mdcg.py:2571 截 12）同族；本判据只做同/异比较、不做安全承诺，
    16 位（64 bit）的碰撞概率远低于误判代价。

    为什么返回 None 而不抛：调用方两条路径（登记 / 判陈旧）都必须
    fail-open——「证不出陈旧就不当陈旧」是 N230 的既有不变量。
    """
    try:
        with open(fp, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return None


# 生效条件：无独立生效条件（模块级哨兵字典类）；任何变更操作（setitem/delitem/clear/pop/popitem/setdefault/update）都会使 write_gen 自增 1，读取 write_gen 不变更；setitem 的值为含非空 path 字符串的 dict 时把该 path 记入 path_gen（值为当时的 write_gen）且不动 broad_gen，值为其它形态（含 None tombstone）或经 delitem/pop/popitem/setdefault/update 变更时把 broad_gen 置为当时的 write_gen，clear() 缺省（flush 收尾）只使 write_gen 自增、不改写 path_gen/broad_gen，clear(broad=True)（rebuild_index 收尾）同时把 broad_gen 置为当时的 write_gen。
class DirtyDict(dict):
    """写代际哨兵字典（批次 23，issue #31 D-4 / v20 报告）：任何变更使
    `write_gen` **单调自增、永不回退**。

    为什么不用 `len(self._dirty)` 作写代际：flush 后 `_dirty` 清零，新写入
    会使长度**回到旧值**——代际巧合回退会让读缓存误命中陈旧内容（v20
    `v20_d4_repro.py` stale=True 实测）。单调计数器下「任何写都使代际前进」，
    读缓存的失效判定不再依赖长度巧合。

    消费方纪律：flush/rebuild 清空必须走 `.clear()`（保住子类钩子），
    **不得** `self._dirty = {}` 直接换新 dict——那会退化为普通 dict，
    write_gen 恒 0、读缓存失效面随之失效。

    脏集精确失效簿记（缺陷迭代第 14 轮，high：写读交替整池重装）：
    全局单一 write_gen 作读缓存哨兵会让**任意一次单节点写使全部缓存条目
    同时 miss**（10k 池写读交替实测 3rep 中位 1677.6ms vs 稳态 43.7ms，
    38.4× 退化、线性于 N）。所有节点文件写路径在落盘后必以
    `_dirty[nid] = entry`（entry 带 path）标脏——本类据此把失效粒度从
    整代际细化到 path：`path_gen[path]` 记该 path 最近标脏时的 write_gen，
    读缓存按「path 最近标脏代际 ≤ 缓存代际」判新鲜（见 readcache.install）。
    tombstone（值 None，_unstage 删除记录）与其余无 path 可辨的变更形态
    记 `broad_gen`（保守整池失效，与旧整代际口径等价的安全兜底）。
    `clear()`（flush 收尾）**只推进 write_gen**：flush 只落索引
    派生物（_index_log 分片/快照），不改节点文件——文件内容变更已在各
    写路径 `_dirty[nid]=entry` 时按 path 精确失效；且生产写路径每次写后
    `writepipe._commit_visibility→flush`（每次写必 clear），clear 若再整池
    失效会让精确失效在生产写读交替负载下恒不生效。`clear(broad=True)`
    （rebuild_index 收尾）额外推进 broad_gen 整池失效：rebuild 以盘面
    扫描为准，ccgc/crosscheck/backfill 等「直写文件 + rebuild 收尾」的
    写方不经 `_dirty` 标脏，其文件改写对读缓存的可见性靠这一兜底。
    """

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.write_gen = 0
        self.path_gen = {}      # path → 该 path 最近一次标脏时的 write_gen
        self.broad_gen = 0      # 最近一次无 path 可辨变更的 write_gen（整池兜底）
        # N230（2026-10-01）：**落盘逐字见证**——nid → 标脏那一刻节点文件的
        # (st_mtime_ns, st_size)。`MdCG.__init__` 负责注入 `root`（本类不反查
        # 宿主，免得与 MdCG 的构造顺序耦合）。语义与用法见
        # `MdCG._dirty_entry_superseded`。
        self.root = None
        self.staged_stat = {}
        # issue #80 残留面（2026-10-09 DSH 端，C 案：标记而非清除 + flush 侧过滤）：
        # _maybe_reload_index 判某条脏条目已被盘面更新盖过时**跳过重放**（放行盘面），
        # 但原实现把条目**留在脏集** ⇒ 随后的 flush 会把它**无条件 append 进分片日志**，
        # compact 再把它固化进 _index.json ⇒ **索引侧旧盖新，且跨进程/跨重启存活**
        # （仅 rebuild_index 可自愈）。此处按 nid 打标记，flush 侧据此过滤。
        # 标记集**放在本类内**（不挂宿主）——与 dict 同生命周期，使泄漏面收敛到
        # 本类的变更点上（setitem/delitem/pop/popitem/setdefault/update/clear），
        # 而不是靠『记得在四处都写一遍』。
        self.superseded_ids = set()

    def _bump(self):
        self.write_gen += 1

    def _note(self, v):
        """标脏登记：值带 path → 精确记路径代际；否则保守记整池代际。"""
        p = v.get("path") if isinstance(v, dict) else None
        if isinstance(p, str) and p:
            self.path_gen[p] = self.write_gen
        else:
            self.broad_gen = self.write_gen

    # 生效条件：k 为节点 id、v 为 entry；恒 pop 该 k 的旧见证，随后仅当 v 为含非空 path 字符串的 dict 且 self.root 为真、且 os.stat(root/path) 成功时记入 self.staged_stat[k]=(st_mtime_ns, st_size, 整文件 sha256 前 16 位)；内容读不到（OSError）时第三元记 None（显式的「陈旧证不出」标记，判据侧据此放行）；其余情形（None tombstone / 无 path / stat 失败 / 无 root）不登记——不登记即「证不出陈旧」，重放按旧口径放行。
    def _note_witness(self, k, v):
        """落盘逐字见证的登记（N230）。

        为什么记 (mtime_ns, size, sha256)：`_maybe_reload_index` 需要判「本实例
        这条未 flush 的写入，是不是已经被他进程后来写下的**更新**记录盖过」。
        节点文件是唯一真源——标脏时它长什么样，重放时再看一次，不一样就说明
        盘面已被别人改过。

        **#80（2026-10-09）修正**：原判据只记 (mtime_ns, size)，其原注释断言
        「改写内容必然改 mtime_ns；NTFS 粒度 100ns」——**该断言是错的**。
        mtime 可被**还原**：cp -p / rsync -t / tar x / robocopy /DCOPY:T /
        备份还原 / 网盘同步客户端回写原 mtime；粗粒度文件系统（FAT 2s、
        ext3 1s）下同刻度写入更是常态。届时一个**等长**改写会同时满足 size
        相等与 mtime 相等 ⇒ 见证不失配 ⇒ 判据漏判 ⇒ 旧写盖新写并随 flush
        持久化（沙箱实测：撕裂 17/17 轮、持久化 13/13 轮）。
        故补第三元**整文件内容哈希**：mtime/size 失配仍即时判陈旧（零额外
        IO，原语义一字不改），**双双相等时再比内容哈希**——身份最终由字节定，
        不再由时间戳定。

        stat 失败与无 path 一律不登记：**证不出陈旧就不当陈旧**——「本实例未
        落盘写入不因重载从检索面消失」是既有不变量，宁可漏挡也不误杀。
        """
        self.staged_stat.pop(k, None)
        p = v.get("path") if isinstance(v, dict) else None
        if not (isinstance(p, str) and p and self.root):
            return
        fp = os.path.join(self.root, p)
        try:
            st = os.stat(fp)
        except OSError:
            return
        # #80：第三元=整文件内容哈希（mtime/size 可被还原，不足以定身份）。
        self.staged_stat[k] = (st.st_mtime_ns, st.st_size, file_digest(fp))

    def __setitem__(self, k, v):
        self._bump()
        self._note(v)
        self._note_witness(k, v)
        self.superseded_ids.discard(k)      # 新写入不再陈旧（issue #80 残留面）
        super().__setitem__(k, v)

    def __delitem__(self, k):
        self._bump()
        self.staged_stat.pop(k, None)
        self.superseded_ids.discard(k)      # issue #80 残留面
        self.broad_gen = self.write_gen
        super().__delitem__(k)

    def clear(self, broad: bool = False):
        """清空脏集。

        broad=False（flush 收尾）：只推进 write_gen，不整池失效——flush 只
        落索引派生物（_index_log 分片），节点文件的内容变更已在各写路径
        `_dirty[nid]=entry`（带 path）时按 path 精确失效；且生产写路径每次
        写后 `writepipe._commit_visibility→flush`，整池失效会让精确失效在
        生产写读交替负载下恒不生效。
        broad=True（rebuild_index 收尾）：同时推进 broad_gen 整池失效——
        rebuild 以**盘面扫描**为准重建索引，ccgc/crosscheck/backfill 等
        「直写文件 + rebuild 收尾」的写方不经 `_dirty` 标脏，其文件改写对
        读缓存的可见性全靠这一兜底（与 MdStore「写方落盘后显式 reload」
        同构）。
        """
        self._bump()
        if broad:
            self.broad_gen = self.write_gen
        self.staged_stat.clear()
        self.superseded_ids.clear()         # issue #80 残留面：脏集清空 ⇒ 标记一并清
        super().clear()

    def pop(self, k, *d):
        self._bump()
        self.staged_stat.pop(k, None)
        self.superseded_ids.discard(k)      # issue #80 残留面
        self.broad_gen = self.write_gen
        return super().pop(k, *d)

    def popitem(self):
        self._bump()
        self.broad_gen = self.write_gen
        self.staged_stat.clear()      # 摘哪条不确定，保守清空（下一轮按「无见证」放行）
        self.superseded_ids.clear()   # issue #80 残留面：同上，摘哪条不确定 ⇒ 保守清空
        return super().popitem()

    def setdefault(self, k, d=None):
        self._bump()
        self.broad_gen = self.write_gen
        self.staged_stat.pop(k, None)
        self.superseded_ids.discard(k)      # issue #80 残留面
        return super().setdefault(k, d)

    def update(self, *a, **k):
        self._bump()
        self.broad_gen = self.write_gen
        self.superseded_ids.clear()   # issue #80 残留面：批量变更 ⇒ 保守清空
        self.staged_stat.clear()
        super().update(*a, **k)
