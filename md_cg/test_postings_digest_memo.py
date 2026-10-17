# -*- coding: utf-8 -*-
"""test_postings_digest_memo.py · 内容指纹记忆表的**平台语义**守卫（issue #178 补漏）

缺陷现场（本机实跑实证，2026-10-13，win32 / Python 3.12.14）：
    `md_cg/postings.py` 的 `_file_digest_memo` 以 `(st_mtime_ns, st_size,
    st_ctime_ns)` 三元组作内容身份，其 docstring 声明该三元组逐位相等
    「等价于内容未被改动」，故复用**不可能**返回过期 digest。
    但该等价关系**只在 POSIX 成立**：`os.stat().st_ctime` 在 **Windows 上是创建时间**，
    内容改写不使其变化 ⇒ 同长度就地改写 + `os.utime` 只还原 mtime 后，三项逐位相等
    而内容已变 ⇒ 记忆表返回**过期 digest** ⇒ `stale_reason` 不报 `content_changed`
    （#131 的内容层收口被绕开）。

本守卫断言（四组）：
    ① 平台语义：`_CTIME_IS_STATUS_CHANGE` 在 win32 为 False、在 POSIX 为 True；
    ② **过期 digest 不复用**（本件的最小判据，任意平台可跑）：同长度就地改写 +
       还原 mtime 后，`_file_digest_memo(fp, st)` 必须等于**真实内容**的摘要；
    ③ 无缓存路径可用：`st is None` 与平台闸关闭时都退回 `_file_digest`；
    ④ 对照（不误杀）：内容未变时，POSIX 上仍复用缓存（#178 的性能收益不得回退）。

体例与 `md_cg/` 下其它 test_*.py 一致（`check()` + 退出码）。
"""
import sys
import os
import time
import tempfile
import hashlib

sys.stdout.reconfigure(encoding='utf-8')
# 支持两种调用式：`python -m md_cg.test_postings_digest_memo` 与直跑本文件。
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import postings as P  # noqa: E402

pass_n = fail_n = 0


def check(name, ok, detail=''):
    """断言登记：通过/失败计数并打印结果行。"""
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


def _sha16(fp):
    with open(fp, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


# ① 平台语义
print('— ① 平台语义 —')
_expect = sys.platform != 'win32'
check('① _CTIME_IS_STATUS_CHANGE 与平台一致',
      P._CTIME_IS_STATUS_CHANGE == _expect,
      f'platform={sys.platform} 值={P._CTIME_IS_STATUS_CHANGE}')
check('① win32 上必须为 False（ctime 是创建时间）',
      (sys.platform != 'win32') or (P._CTIME_IS_STATUS_CHANGE is False),
      f'platform={sys.platform}')

# ② 最小判据：过期 digest 不得被复用（任意平台可跑）
print('— ② 过期 digest 不复用（本件最小判据）—')
_d = tempfile.mkdtemp(prefix='postings_memo_')
_fp = os.path.join(_d, 'node.md')
with open(_fp, 'w', encoding='utf-8') as fh:
    fh.write('AAAA')
_st1 = os.stat(_fp)
_h1 = _sha16(_fp)
# 先「读一次」进记忆表
_ = P._file_digest_memo(_fp, _st1)

time.sleep(1.1)                                   # 让时间戳可分辨
with open(_fp, 'w', encoding='utf-8') as fh:      # 同长度就地改写
    fh.write('BBBB')
os.utime(_fp, ns=(_st1.st_atime_ns, _st1.st_mtime_ns))   # 只还原 mtime
_st2 = os.stat(_fp)
_h2 = _sha16(_fp)

check('② 前提：改写后三项 stat 身份逐位相等', (
    _st1.st_mtime_ns == _st2.st_mtime_ns
    and _st1.st_size == _st2.st_size
    and _st1.st_ctime_ns == _st2.st_ctime_ns),
    f'mtime {_st1.st_mtime_ns==_st2.st_mtime_ns} size {_st1.st_size==_st2.st_size} '
    f'ctime {_st1.st_ctime_ns==_st2.st_ctime_ns}')
check('② 前提：内容确实变了', _h1 != _h2, f'{_h1} → {_h2}')

_got = P._file_digest_memo(_fp, _st2)
check('② 返回的必须是**真实内容**的摘要（不得复用过期值）',
      _got == _h2, f'得到 {_got}，真实 {_h2}' + ('  ← 复用了过期 digest' if _got == _h1 else ''))

# ③ 无缓存路径
print('— ③ 无缓存路径 —')
check('③ st 为 None 时退回 _file_digest',
      P._file_digest_memo(_fp, None) == _h2, '')
_orig = P._CTIME_IS_STATUS_CHANGE
try:
    P._CTIME_IS_STATUS_CHANGE = False
    check('③ 平台闸关闭时退回 _file_digest（即使记忆表有旧值）',
          P._file_digest_memo(_fp, _st2) == _h2, '')
finally:
    P._CTIME_IS_STATUS_CHANGE = _orig

# ④ 对照：内容未变时应复用（POSIX 的性能收益）
print('— ④ 对照（不误杀）—')
if _expect:
    P._DIGEST_MEMO.pop(_fp, None)
    _a = P._file_digest_memo(_fp, _st2)           # 回填
    check('④ POSIX：内容未变时命中缓存且值正确',
          _a == _h2 and _fp in P._DIGEST_MEMO, f'得到 {_a}')
else:
    P._DIGEST_MEMO.pop(_fp, None)
    _a = P._file_digest_memo(_fp, _st2)
    check('④ win32：平台闸下不落缓存（不引入不可信身份）',
          _a == _h2 and _fp not in P._DIGEST_MEMO, f'得到 {_a}，表内命中={_fp in P._DIGEST_MEMO}')

check('④ 平台闸为常量（防回退成「处处信任 ctime」）',
      'sys.platform' in open(os.path.join(_HERE, 'postings.py'), encoding='utf-8').read(),
      '')

# 清理
try:
    for _n in ('node.md',):
        os.remove(os.path.join(_d, _n))
    os.rmdir(_d)
except OSError:
    pass

print(f'\n=== 内容指纹记忆表平台语义: {pass_n}/{pass_n + fail_n} 通过 ===')
sys.exit(0 if fail_n == 0 else 1)
