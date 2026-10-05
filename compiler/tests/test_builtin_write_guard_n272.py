# -*- coding: utf-8 -*-
"""test_builtin_write_guard_n272.py · 内建名写面闸（编译期只读保护 + 运行期结构化拒）（N272）

缺陷（2026-10-05 本会话实跑复现；编号续 N269）：
  ① 信任阈值写静默遮蔽：『信任阈值 = 0.9／若 信任值 大于 信任阈值，则 止。』
     编译过审；运行期写入落 symbols 遮蔽内建读取（实测
     symbols={'信任阈值': 0.9}）——两台 VM 皆漏（Rust 同：state
     symbols={'信任阈值': 0.9}）。
  ② 空间名可写：『伴侣 = 1.0』编译过审、运行期 symbols={'伴侣': 1.0}
     遮蔽内建字符串「伴侣」（比较判定被改写）。
  ③ 写类型闸两 VM 分歧：『信任值 = "0.9"』Python 裸 TypeError（Rust 结构化拒）；
     『条件空间 = 0.9』Python 数字成空间名（Rust 结构化拒）；信任分量
     写字符串 Python 无闸（Rust 拒）。

修复（N272，以 SEMANTICS.md §1 表为准绳）：
  ① 编译期：name_checker 保护面扩展——写面标「—」的集（信任阈值、
     伴侣/工作/默认/恢复默认/default）赋值 → 编译期 error（两入口一致）。
  ② 运行期：STORE_NAME 对只读内建名写入 → 结构化拒（Python 单点
     VMBuiltinError；Rust 同步 VmError::Error）——两 VM 同判。
  ③ 写类型闸对齐：信任值/信任分量须数值、条件空间须字符串（结构化错，
     不裸异常）。

对照断言：只读集写入→编译期拒（双入口）；运行期同拒（结构化）；
写面合法集（信任值/信任分量/条件空间）不误伤；内建读取语义不回归。
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.api import compile_source as api_compile
from compiler.compiler import compile_source as vm_compile
from compiler.condition_vm import ConditionVM, Opcode
from compiler import condition_vm as vmm
from compiler import name_checker as nck

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print('[%s] %s%s' % ('OK ' if ok else 'FAIL', name, ' — ' + detail if detail else ''))


def api_no_crash(src):
    try:
        return api_compile(src), None
    except Exception as e:  # noqa: BLE001
        return None, '%s: %s' % (type(e).__name__, e)


def rejected_pair(src, name, needle='只读'):
    r, e = api_no_crash(src)
    ok_a = (e is None and r is not None and r.success is False
            and any(needle in x for x in r.errors))
    check('%s api 拒绝（%s）' % (name, needle), ok_a,
          e or 'success=%s errors=%s' % (getattr(r, 'success', None),
                                         [str(x)[:70] for x in getattr(r, 'errors', [])[:1]]))
    try:
        code, rr = vm_compile(src, strict=True)
        ok_v = (rr.get('ok') is False and any(needle in str(x) for x in rr.get('errors', [])))
        check('%s compiler 同拒' % name, ok_v,
              'ok=%s errors=%s' % (rr.get('ok'), [str(x)[:70] for x in rr.get('errors', [])[:1]]))
    except Exception as e2:  # noqa: BLE001
        check('%s compiler 同拒' % name, False, '%s: %s' % (type(e2).__name__, e2))


def legal_pair(src, name):
    r, e = api_no_crash(src)
    ok_a = e is None and r is not None and r.success is True
    check('%s api 仍成功' % name, ok_a,
          e or 'success=%s errors=%s' % (getattr(r, 'success', None),
                                         [str(x)[:70] for x in getattr(r, 'errors', [])[:1]]))
    try:
        code, rr = vm_compile(src, strict=True)
        check('%s compiler 仍成功' % name, rr.get('ok') is True,
              'ok=%s errors=%s' % (rr.get('ok'), [str(x)[:70] for x in rr.get('errors', [])[:1]]))
    except Exception as e2:  # noqa: BLE001
        check('%s compiler 仍成功' % name, False, '%s: %s' % (type(e2).__name__, e2))


print('--- (1) 编译期只读保护：SEMANTICS §1 写面「—」的集（修复前过审）---')

# 防漂移：编译期（name_checker）与运行期（condition_vm）的只读集必须同集
check('①0 两处只读集一致（name_checker == condition_vm）',
      nck.READONLY_BUILTIN_NAMES == vmm.READONLY_BUILTIN_NAMES
      and len(nck.READONLY_BUILTIN_NAMES) == 6,
      'nck=%s vm=%s' % (sorted(nck.READONLY_BUILTIN_NAMES),
                        sorted(vmm.READONLY_BUILTIN_NAMES)))

rejected_pair('信任阈值 = 0.9\n止。', '①a 信任阈值写入')
rejected_pair('伴侣 = 1.0\n止。', '①b 伴侣（空间名）写入')
rejected_pair('工作 = 1.0\n止。', '①c 工作（空间名）写入')
rejected_pair('默认 = 1.0\n止。', '①d 默认（空间名）写入')
rejected_pair('恢复默认 = 1.0\n止。', '①e 恢复默认写入')
rejected_pair('default = 1.0\n止。', '①f default 写入')
rejected_pair('信任阈值 ＝ 0.9。', '①g 全角等号形态同拒')

print('--- (2) 写面合法集不误伤（信任值/信任分量/条件空间）---')

legal_pair('信任值 = 0.9\n止。', '②a 信任值写数值（合法写面）')
legal_pair('P_trust = 0.5\n止。', '②b 信任分量写数值')
legal_pair('情感权重 = 0.1\n止。', '②c 情感权重（中文别名）写数值')
legal_pair('条件空间 = 伴侣\n止。', '②d 条件空间切换（合法写面）')
legal_pair('条件空间 = 恢复默认\n止。', '②e 恢复默认切换')

print('--- (3) 运行期结构化拒（Python VM 单点闸；Rust 面由 swarm 守卫交叉）---')


def store(name, value):
    return ConditionVM().run([(Opcode.PUSH_CONST, value),
                              (Opcode.STORE_NAME, name), (Opcode.ZHI, None)])


for tag, name, value in [
        ('③a', '信任阈值', 0.9),
        ('③b', '伴侣', 1.0),
        ('③c', '工作', 1.0)]:
    try:
        st = store(name, value)
        check('%s 只读内建名 %s 写入结构化拒' % (tag, name), False,
              '未拒 symbols=%s' % st['symbols'])
    except vmm.VMBuiltinError as e:
        check('%s 只读内建名 %s 写入结构化拒' % (tag, name),
              (getattr(e, 'kind', None) == 'readonly') or ('只读' in str(e)),
              'kind=%s %s' % (getattr(e, 'kind', None), str(e)[:60]))
    except Exception as e:  # noqa: BLE001
        check('%s 只读内建名 %s 写入结构化拒' % (tag, name), False,
              '裸异常 %s: %s' % (type(e).__name__, e))

for tag, name, value, needle in [
        ('③d', '信任值', '0.9', '只能写数值'),
        ('③e', 'P_trust', 'x', '只能写数值'),
        ('③f', '条件空间', 0.9, '只能写空间名')]:
    try:
        store(name, value)
        check('%s %s 类型闸结构化拒' % (tag, name), False, '未拒')
    except vmm.VMBuiltinError as e:
        check('%s %s 类型闸结构化拒' % (tag, name), needle in str(e), str(e)[:80])
    except Exception as e:  # noqa: BLE001
        check('%s %s 类型闸结构化拒' % (tag, name), False,
              '裸异常 %s: %s' % (type(e).__name__, e))

print('--- (4) 合法写入与内建读取语义不回归 ---')

st4 = store('信任值', 0.9)
check('④a 信任值写数值落寄存器', st4['trust'] == 0.9, str(st4['trust']))
st5 = store('条件空间', '伴侣')
check('④b 条件空间写字符串切换生效', st5['condition_space_name'] == '伴侣',
      str(st5['condition_space_name']))

# 信任阈值读取语义（0.7 默认）不因写面闸漂移——trust=0.8 > 0.7 → 德执行
code6, r6 = vm_compile('若 信任值 大于 信任阈值，则 德 0.5。\n止。', strict=True)
if r6.get('ok'):
    st6 = ConditionVM().run(code6, trust=0.8)
    st7 = ConditionVM().run(code6, trust=0.6)
    check('④c 信任阈值读取=0.7（0.8 过 → 德执行；0.6 不过）',
          st6['trust'] == 1.3 and st7['trust'] == 0.6,
          'trust(0.8)=%s trust(0.6)=%s' % (st6['trust'], st7['trust']))
else:
    check('④c 信任阈值读取=0.7（0.8 过 → 德执行；0.6 不过）', False,
          'ok=%s errors=%s' % (r6.get('ok'), [str(x)[:60] for x in r6.get('errors', [])[:1]]))

print('\n=== N272 内建名写面闸守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
