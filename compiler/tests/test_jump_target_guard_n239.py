# -*- coding: utf-8 -*-
"""test_jump_target_guard_n239.py · VM 跳转目标地址范围校验（N239）

缺陷（本会话实跑复现）：
  写入 self.ip 的跳转目标全无范围判定——
    · 负目标被 Python 的 `code[负索引]` **静默**回绕：`[(JUMP,-1),(PUSH_CONST,42),
      (STORE_NAME,'标记'),(ZHI,None)]` → halt='halt'、symbols={}——中间两条指令
      被静默跳过，实际执行的是 code[-1]=ZHI；
    · `target > len(code)` 让 `while self.ip < len(code)` 直接为假、程序静默结束
      （`[(PUSH_CONST,1),(STORE_NAME,'甲'),(JUMP,999),(ZHI,None)]` → halt=None）。
  经 `.pbc` 可达（`compiler/pbc.py` deserialize 以 struct.unpack_from('q') 承载
  任意 int64）。

修复：`ConditionVM._jump(target)` 单点校验（JUMP / JUMP_IF_FALSE / ZHIZU /
  CALL 入口 / RETURN 返回地址 五处写入 self.ip 一律经它），越界抛结构化
  `VMResourceError("jump")`——负值不回绕、超界不静默结束。
  **上界是 `<= len(code)` 而非 `<`**：`== len(code)` 是「跳到程序末尾」的既有
  语义，编译器自身就产出该目标（知足标签与末尾 若/则 的 end 标签 `_place` 在
  len(code)，见 compiler.py:74-76、:137-139），`test_defect_regression` ④a 亦
  钉死「知足达标 → 其后 止 被跳过（halt=None）」。实测把上界收紧成 `<` 会让
  `test_defect_regression` 抛 `VMResourceError: 跳转目标越界：5（合法地址 0..5）`
  ——合法产物被打红，故取 `<=`。

本文件把语义钉死：越界即拒（结构化错，非静默错走/静默结束），合法面一字不动。
纯行为断言，不做源码文本匹配。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.condition_vm import ConditionVM, Opcode, VMResourceError
from compiler.compiler import compile_source
from compiler.pbc import serialize, deserialize, save_pbc, run_pbc

pass_n = fail_n = 0


# 生效条件：调用须传 name 与 ok，ok 为真时全局 pass_n 加 1、为假时 fail_n 加 1；detail 为真值时追加 ' — ' + detail。
def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print('[%s] %s%s' % ('OK ' if ok else 'FAIL', name, ' — ' + detail if detail else ''))


# 生效条件：以 code 调 ConditionVM().run，返回 ("ok", state) 或 ("err", (kind, msg)) 或 ("exc", (类型名, msg))。
def run_probe(code, **kw):
    try:
        return "ok", ConditionVM().run(code, **kw)
    except VMResourceError as e:
        return "err", (e.kind, str(e))
    except Exception as e:  # noqa: BLE001
        return "exc", (type(e).__name__, str(e))


def expect_jump_error(tag, code):
    """越界目标必须得 VMResourceError('jump')——不是静默 halt/结束，也不是 TypeError。"""
    kind, payload = run_probe(code)
    check("%s → VMResourceError('jump')" % tag,
          kind == "err" and payload[0] == "jump",
          "得到 %s：%s" % (kind, payload))


print('--- (1) 负目标不得回绕（修复前：跳 code[-1]、中间指令静默跳过）---')

# 例1 形态：负 JUMP 回绕到 code[-1]=ZHI（修复前 halt='halt'、symbols={}）
expect_jump_error("①a JUMP -1（修复前回绕执行 code[-1]）",
                  [(Opcode.JUMP, -1), (Opcode.PUSH_CONST, 42),
                   (Opcode.STORE_NAME, '标记'), (Opcode.ZHI, None)])
expect_jump_error("①b JUMP_IF_FALSE -1（取假分支）",
                  [(Opcode.PUSH_CONST, 0), (Opcode.JUMP_IF_FALSE, -1),
                   (Opcode.ZHI, None)])
expect_jump_error("①c ZHIZU (0.0,-1)（达标跳负地址）",
                  [(Opcode.ZHIZU, (0.0, -1)), (Opcode.PUSH_CONST, 9),
                   (Opcode.ZHI, None)])
expect_jump_error("①d CALL 入口 -1",
                  [(Opcode.PUSH_CONST, 1), (Opcode.CALL, (-1, ['a'])),
                   (Opcode.ZHI, None)])


print('--- (2) 超界目标不得静默结束（修复前：while ip<len 直接为假、ZHI 被跳过）---')

expect_jump_error("②a JUMP 999（len=4）",
                  [(Opcode.PUSH_CONST, 1), (Opcode.STORE_NAME, '甲'),
                   (Opcode.JUMP, 999), (Opcode.ZHI, None)])
expect_jump_error("②b JUMP_IF_FALSE len+1（取假分支）",
                  [(Opcode.PUSH_CONST, 0), (Opcode.JUMP_IF_FALSE, 99),
                   (Opcode.ZHI, None)])
expect_jump_error("②c ZHIZU 超界地址",
                  [(Opcode.ZHIZU, (0.0, 99)), (Opcode.ZHI, None)])
expect_jump_error("②d CALL 入口超界",
                  [(Opcode.PUSH_CONST, 1), (Opcode.CALL, (99, ['a'])),
                   (Opcode.ZHI, None)])


print('--- (3) 边界精确性：len(code) 合法（跳到末尾），len+1 拒 ---')

code_end = [(Opcode.PUSH_CONST, 1), (Opcode.STORE_NAME, '甲'),
            (Opcode.JUMP, 4), (Opcode.ZHI, None)]      # len=4，目标 4 == len
st_kind, st = run_probe(code_end)
check("③a JUMP 到 len(code) 合法（跳到末尾，halt=None）",
      st_kind == "ok" and st["halt"] is None and st["symbols"].get("甲") == 1.0,
      "%s：%s" % (st_kind, st))
code_over = [(Opcode.PUSH_CONST, 1), (Opcode.STORE_NAME, '甲'),
             (Opcode.JUMP, 5), (Opcode.ZHI, None)]     # 目标 5 == len+1
expect_jump_error("③b JUMP 到 len(code)+1 拒", code_over)


print('--- (4) .pbc 通路同样受控（不可再借 deserialize 携带越界地址）---')

d = tempfile.mkdtemp()
p = os.path.join(d, "bad.pbc")
save_pbc([("JUMP", -1), ("PUSH_CONST", 42), ("STORE_NAME", '标记'), ("ZHI", None)], p)
try:
    run_pbc(p)
    check("④.pbc 载入 JUMP -1 → VMResourceError('jump')", False, "VM 竟静默执行了")
except VMResourceError as e:
    check("④.pbc 载入 JUMP -1 → VMResourceError('jump')", e.kind == "jump", str(e))
except Exception as e:  # noqa: BLE001
    check("④.pbc 载入 JUMP -1 → VMResourceError('jump')", False,
          "%s: %s" % (type(e).__name__, e))
check("④b deserialize 往返保留负地址（可达性自证）",
      deserialize(serialize([("JUMP", -1)]))[0][1] == -1,
      "round-trip=%r" % (deserialize(serialize([("JUMP", -1)])),))


print('--- (5) 非整数目标亦拒（修复前 float 索引裸穿 TypeError）---')

expect_jump_error("⑤a JUMP 2.0（float 地址）",
                  [(Opcode.JUMP, 2.0), (Opcode.PUSH_CONST, 1), (Opcode.ZHI, None)])


print('--- (6) 回归对照：合法跳转/编译器产物一字不动 ---')

# ⑥a 自环 JUMP 0 → 仍由步数上限拦（既有 RecursionError 契约，非新错误）
k6, p6 = run_probe([(Opcode.JUMP, 0), (Opcode.ZHI, None)], max_steps=5)
check("⑥a JUMP 0 自环仍 RecursionError（步数上限契约不变）",
      k6 == "exc" and p6[0] == "RecursionError", "%s：%s" % (k6, p6))

# ⑥b 编译器旗舰样例（知足→跳到 len(code)；止 被跳过=halt None）
src = ("问曰：如何验证信任？\n答曰：信任值大于0.7。\n术曰：\n"
       "1。道 新信任路径；\n2。若 信任值 大于 0.3，则 德 0.5；\n"
       "3。知足 0.7；\n4。止。\n")
code_c2, r_c2 = compile_source(src, strict=False)
if r_c2["ok"]:
    k, s = run_probe(code_c2, trust=0.4)
    check("⑥b 旗舰样例（知足早退）仍可执行：trust=0.9/halt=None",
          k == "ok" and s["trust"] == 0.9 and s["halt"] is None,
          "%s：%s" % (k, s))
else:
    check("⑥b 旗舰样例编译成功", False, str(r_c2["errors"])[:60])

# ⑥c 末尾 若/则（end 标签 place 在 len(code)）仍可执行
code_if, r_if = compile_source("甲 = 1。\n若 甲 大于 0，则 德 0.5。\n", strict=False)
if r_if["ok"]:
    k, s = run_probe(code_if)
    check("⑥c 末尾若则（跳 len(code)）仍可执行：trust=0.5",
          k == "ok" and s["trust"] == 0.5, "%s：%s" % (k, s))
else:
    check("⑥c 末尾若则编译成功", False, str(r_if["errors"])[:60])

# ⑥d 递归 + 前向调用（CALL/RETURN 地址全合法）仍正确
code_rec, r_rec = compile_source(
    "定义 阶乘（n）：若 n 小于 2，则 返回 1，否则 返回 n 乘 阶乘（n 减 1）。\n"
    "结果 = 阶乘（4）。\n止。", strict=False)
if r_rec["ok"]:
    k, s = run_probe(code_rec)
    check("⑥d 递归 阶乘(4)=24 仍正确",
          k == "ok" and s["symbols"].get("结果") == 24.0,
          "%s：结果=%s" % (k, s.get("symbols", {}).get("结果")))
else:
    check("⑥d 递归样例编译成功", False, str(r_rec["errors"])[:60])


print('\n=== N239 VM 跳转目标范围守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
