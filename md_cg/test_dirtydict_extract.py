# -*- coding: utf-8 -*-
"""T-DD · `_DirtyDict` 搬家守卫（深度重构 2026-11-11·任务 4）。

子功能：DD1 别名同源（`mdcg._DirtyDict is dirtydict.DirtyDict`，不得变成
「两份定义各自演进」）· DD2 写代际单调（任何变更 +1，读取不变）· DD3 精确失效
（带 path 的值记 path_gen，不带 path 的记 broad_gen）· DD4 clear 语义双档
（flush 收尾只推代际；rebuild 收尾推整池代际）· DD5 落盘逐字见证（带 path 且
root 可读时记三元组；tombstone / 无 path 不登记）· DD6 `mdcg._file_digest` 与
`dirtydict.file_digest` 同源且读不到时返回 None。

为什么需要它：本类被搬到独立模块后，`mdcg.py` 只留 re-export 别名。若有人把
别名改回「复制一份类定义」，两个类会各自演进、`_dirty` 的失效代际判据在两侧
分叉而**没有任何测试会红**——本守卫即那根钉子。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import dirtydict as D          # noqa: E402
from md_cg import mdcg as M               # noqa: E402

FAILS = []


def ok(name, cond, detail=None):
    if cond:
        print('  [ok] %s' % name)
    else:
        print('  [FAIL] %s  %r' % (name, detail))
        FAILS.append(name)


# ---- DD1 别名同源 ---------------------------------------------------------
ok('DD1a `mdcg._DirtyDict` 就是 `dirtydict.DirtyDict`（同一对象，非副本）',
   M._DirtyDict is D.DirtyDict, (M._DirtyDict, D.DirtyDict))
ok('DD1b `mdcg._file_digest` 就是 `dirtydict.file_digest`（同一对象）',
   M._file_digest is D.file_digest,
   (M._file_digest, D.file_digest))
ok('DD1c `MdCG.__init__` 用 `dirtydict.DirtyDict` 构造脏集（非普通 dict）',
   'DirtyDict(' in open(os.path.join(os.path.dirname(__file__), 'mdcg.py'),
                        encoding='utf-8').read())

_tmp = tempfile.mkdtemp(prefix='dd_')
try:
    cg = M.MdCG(_tmp)
    ok('DD1d 真 MdCG 的 `_dirty` 是 DirtyDict 实例', isinstance(cg._dirty, D.DirtyDict),
       type(cg._dirty))
finally:
    pass

# ---- DD2 写代际单调 -------------------------------------------------------
dd = D.DirtyDict()
ok('DD2a 新建 write_gen == 0', dd.write_gen == 0, dd.write_gen)
dd['a'] = {'path': 'a.md'}
ok('DD2b setitem 推进一代', dd.write_gen == 1, dd.write_gen)
_ = dd.write_gen
_ = dd.get('a')
ok('DD2c 读不推进代际', dd.write_gen == 1, dd.write_gen)
dd['b'] = None
ok('DD2d 再写推进一代', dd.write_gen == 2, dd.write_gen)
dd.clear()
ok('DD2e clear 推进代际（单调，不回退）', dd.write_gen == 3, dd.write_gen)

# ---- DD3 精确失效 ---------------------------------------------------------
dd = D.DirtyDict()
dd['n1'] = {'path': 'x/y.md'}
ok('DD3a 带 path ⇒ 记 path_gen 当前代', dd.path_gen == {'x/y.md': 1}, dd.path_gen)
ok('DD3b 带 path ⇒ 不动 broad_gen', dd.broad_gen == 0, dd.broad_gen)
dd['n2'] = None
ok('DD3c tombstone(None) ⇒ 记 broad_gen', dd.broad_gen == 2, dd.broad_gen)
ok('DD3d tombstone 不新增 path_gen', dd.path_gen == {'x/y.md': 1}, dd.path_gen)

# ---- DD4 clear 双档 -------------------------------------------------------
dd = D.DirtyDict()
dd['n'] = {'path': 'p.md'}
dd.clear()
ok('DD4a clear() 不推 broad_gen（flush 收尾）', dd.broad_gen == 0, dd.broad_gen)
ok('DD4b clear() 清空内容', dict(dd) == {}, dict(dd))
dd2 = D.DirtyDict()
dd2['n'] = {'path': 'p.md'}
dd2.clear(broad=True)
ok('DD4c clear(broad=True) 推 broad_gen（rebuild 收尾）',
   dd2.broad_gen == dd2.write_gen == 2, (dd2.broad_gen, dd2.write_gen))

# ---- DD5 落盘逐字见证 -----------------------------------------------------
root = tempfile.mkdtemp(prefix='ddw_')
os.makedirs(os.path.join(root, 'sub'))
fp = os.path.join(root, 'sub', 'n.md')
with open(fp, 'w', encoding='utf-8') as f:
    f.write('hello')
dd = D.DirtyDict()
dd.root = root
dd['nid'] = {'path': 'sub/n.md'}
w = dd.staged_stat.get('nid')
ok('DD5a 带 path 且 root 可读 ⇒ 记 (mtime_ns, size, digest) 三元组',
   isinstance(w, tuple) and len(w) == 3 and w[1] == 5 and w[2] == D.file_digest(fp), w)
dd['nid2'] = None
ok('DD5b tombstone ⇒ 不登记见证', 'nid2' not in dd.staged_stat, dd.staged_stat)
dd['nid3'] = {'path': 'sub/missing.md'}
ok('DD5c 盘面缺失 ⇒ 不登记见证（证不出陈旧就不当陈旧）',
   'nid3' not in dd.staged_stat, dd.staged_stat)
dd.root = None
dd['nid4'] = {'path': 'sub/n.md'}
ok('DD5d 未注入 root ⇒ 不登记见证', 'nid4' not in dd.staged_stat, dd.staged_stat)

# ---- DD6 digest -----------------------------------------------------------
ok('DD6a digest 为 16 位十六进制', len(D.file_digest(fp) or '') == 16, D.file_digest(fp))
ok('DD6b 读不到返回 None（不抛）',
   D.file_digest(os.path.join(root, 'nope.md')) is None)

print('=' * 64)
print('T-DD `_DirtyDict` 搬家守卫：%d 通过，%d 失败'
      % (15 + 5 + 4 - len(FAILS), len(FAILS)))
sys.exit(1 if FAILS else 0)
