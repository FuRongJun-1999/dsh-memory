# -*- coding: utf-8 -*-
"""test_vm_resource_guard.py · N149 回归：VM 资源加固（单步代价/分配/墙钟）

缺陷（N149，2026-09-26 修复）：VM 沙箱唯一防线 max_steps 只限步数不限单步代价
与分配——大数平方循环在防线内实测 90.3 秒挂起；单条 MUL「字符串×大整数」一次
申请 19.5GiB；int64 量级申请 MemoryError 未捕获直接上抛。run docstring 自称
「步数上限防死循环」对恶意 .pbc（serialize 三行即可合成，属本项目分发格式）
实质无效（DoS/OOM 面：pc run/pc debug 或 run_pbc()/debug_pbc() 即触发）。

修复语义（上限为加固参数，合法编译产物——信任小数/小整数/短名串——远触不到）：
  ① MUL 结果规模守卫  ：int 看操作数位数之和（>VM_MAX_INT_BITS 拒）、
                        序列×int 看元素数（>VM_MAX_SEQ_REPEAT 拒）——
                        申请在发生前被拒，抛 VMResourceError("mul_scale")
  ② 墙钟预算          ：run(max_wall_seconds=VM_DEFAULT_WALL_SECONDS)，
                        单步开始前超限抛 VMResourceError("wall")；None/0 关闭
  ③ MemoryError 结构化：单步分配失败转 VMResourceError("memory")，不再裸上抛
  ④ run_pbc 显式携带墙钟预算（步数/MUL/内存守卫由 ConditionVM.run 内置生效）
既有契约不变：步数上限仍抛 RecursionError（test_loop_compile ⑤）；
合法 MUL（小整数/短串/浮点）逐位不变（黄金基线法验证）。
"""
import os
import sys
import time
import tempfile
from unittest import mock

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.condition_vm import (ConditionVM, Opcode, VMResourceError,
                                   VM_MAX_INT_BITS, VM_MAX_SEQ_REPEAT,
                                   VM_DEFAULT_WALL_SECONDS)
from compiler.pbc import serialize, run_pbc

pass_n = fail_n = 0
def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


def _evil_pbc(instrs, prefix):
    """合成恶意 .pbc（攻击者三行即可生成——serialize 是本项目分发格式）"""
    tmp = tempfile.mkdtemp(prefix=prefix)
    path = os.path.join(tmp, "evil.pbc")
    with open(path, "wb") as f:
        f.write(serialize(instrs))
    return path


#: 大数自乘死循环（int64 起点——.pbc 常量即 int64，防线内挂起的原样本形态）
SQUARING = [(Opcode.PUSH_CONST, 9223372036854775807),
            (Opcode.STORE_NAME, "甲"),
            (Opcode.LOAD_NAME, "甲"),
            (Opcode.LOAD_NAME, "甲"),
            (Opcode.MUL, None),
            (Opcode.STORE_NAME, "甲"),
            (Opcode.JUMP, 2)]

# ① MUL 字符串×大整数：EiB 级申请面——须 mul_scale 且申请不发生（毫秒级拒绝）
pbc_a = _evil_pbc([(Opcode.PUSH_CONST, "甲"),
                   (Opcode.PUSH_CONST, 4611686018427387904),  # 2**62 → 4EiB
                   (Opcode.MUL, None), (Opcode.STORE_NAME, "乙"),
                   (Opcode.ZHI, None)], "n149_a_")
t0 = time.monotonic()
try:
    run_pbc(pbc_a)
    check('① 字符串×2^62 拒绝', False, '无守卫直通')
except VMResourceError as e:
    dt = time.monotonic() - t0
    check('① 字符串×2^62 拒绝（mul_scale·申请不发生·毫秒级）',
          e.kind == "mul_scale" and dt < 5.0,
          f'kind={e.kind} {dt*1000:.1f}ms')
except Exception as e:
    check('① 字符串×2^62 拒绝', False, f'{type(e).__name__}: {e}')

# ② 大数平方循环（曾实测 90.3s 挂起面）：.pbc 端到端、run_pbc 纯默认参数
#    须在 MUL 规模守卫处毫秒级结构化拒绝（修复前挂起 >25s 无结构化终止）
pbc_b = _evil_pbc(SQUARING, "n149_b_")
t0 = time.monotonic()
try:
    run_pbc(pbc_b)
    check('② 恶意.pbc 平方循环拒绝', False, '无守卫直通')
except VMResourceError as e:
    dt = time.monotonic() - t0
    check('② 恶意.pbc 平方循环拒绝（默认参数·mul_scale·毫秒级）',
          e.kind == "mul_scale" and dt < 5.0,
          f'kind={e.kind} {dt*1000:.1f}ms')
except Exception as e:
    check('② 恶意.pbc 平方循环拒绝', False, f'{type(e).__name__}: {e}')

# ③ MemoryError → 结构化错（注入 _exec 验证转换，不真耗内存）
code_c = [(Opcode.PUSH_CONST, 1), (Opcode.STORE_NAME, "甲"), (Opcode.ZHI, None)]
real_exec = ConditionVM._exec
try:
    with mock.patch.object(ConditionVM, "_exec",
                           side_effect=MemoryError("模拟分配失败")):
        ConditionVM().run(code_c)
    check('③ MemoryError 转结构化', False, '未转换（裸上抛不存在？）')
except VMResourceError as e:
    check('③ MemoryError 转结构化（kind=memory）', e.kind == "memory",
          f'kind={e.kind}')
except MemoryError as e:
    check('③ MemoryError 转结构化', False, f'仍裸上抛: {e}')
finally:
    ConditionVM._exec = real_exec

# ④ 墙钟预算：自跳死循环 + 0.3s 预算——步数不限单步代价的兜底面
t0 = time.monotonic()
try:
    ConditionVM().run([(Opcode.JUMP, 0)], max_steps=10 ** 9,
                      max_wall_seconds=0.3)
    check('④ 墙钟预算拦截', False, '无守卫直通')
except VMResourceError as e:
    dt = time.monotonic() - t0
    check('④ 墙钟预算拦截（wall·预算内终止）',
          e.kind == "wall" and 0.3 <= dt < 10.0,
          f'kind={e.kind} {dt:.2f}s')
except Exception as e:
    check('④ 墙钟预算拦截', False, f'{type(e).__name__}: {e}')

# ⑤ 合法 MUL 逐位不受影响（加固上限远触不到——黄金基线锚）
code_legal = [(Opcode.PUSH_CONST, 123), (Opcode.PUSH_CONST, 456),
              (Opcode.MUL, None),
              (Opcode.PUSH_CONST, "甲"), (Opcode.PUSH_CONST, 3),
              (Opcode.MUL, None),
              (Opcode.PUSH_CONST, 2.5), (Opcode.PUSH_CONST, 4.0),
              (Opcode.MUL, None)]
st_legal = ConditionVM().run(code_legal)
check('⑤ 合法 MUL 逐位不变（123×456/短串×3/浮点）',
      st_legal["stack"] == [56088, "甲甲甲", 10.0], f'{st_legal["stack"]}')

# ⑥ 加固参数落在声明位置（防上限被误改到合法可达量级）
check('⑥ 加固参数上限量级（int 位数≥2^15、序列≥2^23、墙钟≥5s）',
      VM_MAX_INT_BITS >= 1 << 15 and VM_MAX_SEQ_REPEAT >= 1 << 23
      and VM_DEFAULT_WALL_SECONDS >= 5.0,
      f'{VM_MAX_INT_BITS}/{VM_MAX_SEQ_REPEAT}/{VM_DEFAULT_WALL_SECONDS}')

# ⑦ 步数上限既有契约不变（RecursionError——与 N149 新增三面并存）
try:
    ConditionVM().run(SQUARING, max_steps=7)     # 7 步内即回跳一圈后越限
    check('⑦ 步数上限契约不变', False, '未拦截')
except RecursionError as e:
    check('⑦ 步数上限契约不变（RecursionError）', '循环未终止' in str(e),
          str(e)[:40])
except Exception as e:
    check('⑦ 步数上限契约不变', False, f'{type(e).__name__}: {e}')

print(f'\n=== N149 VM 资源加固测试: {pass_n}/{pass_n + fail_n} 通过 ===')
sys.exit(0 if fail_n == 0 else 1)
