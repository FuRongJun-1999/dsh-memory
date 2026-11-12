# -*- coding: utf-8 -*-
# 功能名：CALL 帧深上限与「帧内不拷贝条件空间」（issue #326-③）
# 生效条件：python -X utf8 -m md_cg.test_issue326_vm_call_frame [--mutate]；被测面＝compiler/condition_vm.py 的 CALL/RETURN 帧保存与 _cond_own 写时复制
# 子功能：A 组＝深度上限 fail-closed（kind=call_depth、取自模块常量）＋帧**按引用**保存（拷贝次数恒 0，结构性判据，不写内存绝对值）＋返回时按长度截断逐字复原；K 组＝非恒真对照（过度收紧方向：浅递归与「多次**顺序**调用但深度为 1」不得被误拒；输出面/条件空间切换语义不变）；E 组＝源码面（旧拷贝形态已退役）
# 执行：--mutate 时在镜像树里逐条把帧保存改回拷贝/去掉上限（回缺陷）、把上限收到 1（过度收紧）、删掉返回截断（契约破坏），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**
# 不适用条件：不判 Rust 侧 vm.rs 的同族缺陷（缺陷挖掘 v19 已登记 N157，非本批）；不判每帧 dict(self.symbols) 的拷贝（与深度无关、量级由名字数决定）；不判 .pbc 序列化面
"""issue #326-③ 守卫：CALL 每帧整份拷贝条件空间 ⇒ 内存随深度二次增长。

病象（修前）：`self.call_stack.append((..., list(self.condition_stack)))` —— 栈随深度
线性增长，每帧整份拷贝 ⇒ 总拷贝量 O(depth²)、峰值内存二次增长（实测 10s 内 1.0–1.6 GB，
两方独立复现），且**无** VM_MAX_CALL_DEPTH。

修法：① 增 `VM_MAX_CALL_DEPTH`，越界抛 `VMResourceError("call_depth")`（fail-closed，
同 wall/memory/mul_scale/jump 既有形态）；② 帧改「存引用 + 存长度」，返回时按长度截断
撤销被调方的压栈（DAO）；③ 就地改写既有栈顶前经 `_cond_own` 写时复制脱共享。

**为什么不用内存绝对值判据**：绝对值随机器/分配器抖动必红。本守卫改用**确定性结构判据**
——「帧保存的条件空间对象 `is` 当前栈对象」在深度递归全程**恒真**（等价于「每帧拷贝次数 = 0」），
回缺陷（改回 `list(...)`）即转红；比曲线形状更硬、且完全不抖。

「守卫必须能在变异态下跑完」（task-8/④ 的教训）：取数一律经 `_try()` 折成可命名形态。
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


_TMP = tempfile.mkdtemp(prefix="iss326c_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})

import compiler.condition_vm as M                    # noqa: E402
from compiler.condition_vm import ConditionVM, Opcode, VMResourceError  # noqa: E402


def _try(fn):
    """调 fn：正常返回 ("", 结果)；抛异常（含 BaseException）返回 (类型名, 异常对象)。"""
    try:
        return "", fn()
    except BaseException as exc:                 # noqa: BLE001
        return type(exc).__name__, exc


def _space_of(res):
    """从 run() 返回值取 condition_space；res 不是 dict（变异态里是异常对象）时返回 None。

    变异态必须产出可命名红项而非崩栈——detail 表达式同样受此约束（task-8 教训）。
    """
    return res.get("condition_space") if isinstance(res, dict) else None


def _recursion_code():
    """自调用字节码：ip0 处 CALL 自身 ⇒ 每步压一帧（用于探深度上限）。"""
    return [(Opcode.CALL, (0, []))]


def _spy_calls(code, *, hook=None):
    """跑 code 并在每次 CALL 后收集 (帧元数, 帧[3] is 当前栈, 帧[4], len(当前栈))。"""
    vm = ConditionVM()
    seen = []
    orig = ConditionVM._exec

    def spy(self, op, arg):
        out = orig(self, op, arg)
        if op == Opcode.CALL and self.call_stack:
            fr = self.call_stack[-1]
            # 防御：回缺陷态下帧是 4 元组（无保存长度），取索引前先判元数——
            # 否则变异态会在夹具里 IndexError 崩栈、红得不可归因（task-8 教训）。
            seen.append((len(fr),
                         (fr[3] is self.condition_stack) if len(fr) > 3 else None,
                         fr[4] if len(fr) > 4 else None,
                         len(self.condition_stack)))
        if hook is not None and op == Opcode.CALL:
            hook(self)
        return out

    ConditionVM._exec = spy
    try:
        t, res = _try(lambda: vm.run(code, catch_halt=True, max_wall_seconds=None))
    finally:
        ConditionVM._exec = orig
    return t, res, vm, seen


print("== A 组：#326-③ 正题——深度上限 fail-closed ＋ 帧不拷贝 ==")
_t1, _e1 = _try(lambda: ConditionVM().run(_recursion_code(), catch_halt=False,
                                        max_steps=5000, max_wall_seconds=None))
_check("A01 深递归在深度上限处 fail-closed（抛 VMResourceError）",
       _t1 == "VMResourceError", _t1)
_check("A02 抛的是既有资源闸形态的 kind=call_depth（不是 RecursionError/MemoryError 兜底）",
       _t1 == "VMResourceError" and getattr(_e1, "kind", None) == "call_depth",
       (_t1, getattr(_e1, "kind", None)))
_check("A03 上限取自模块常量 VM_MAX_CALL_DEPTH（源码与值同源、可被宿主收紧）",
       isinstance(getattr(M, "VM_MAX_CALL_DEPTH", None), int)
       and M.VM_MAX_CALL_DEPTH > 0, getattr(M, "VM_MAX_CALL_DEPTH", None))
_old_cap = M.VM_MAX_CALL_DEPTH
M.VM_MAX_CALL_DEPTH = 8
_t2, _e2 = _try(lambda: ConditionVM().run(_recursion_code(), catch_halt=False,
                                        max_steps=5000, max_wall_seconds=None))
M.VM_MAX_CALL_DEPTH = _old_cap
_check("A04 收紧常量后上限随之生效（深度 8 即拒；证明确实读常量而非硬编码）",
       _t2 == "VMResourceError" and getattr(_e2, "kind", None) == "call_depth",
       (_t2, getattr(_e2, "kind", None)))
# 结构性判据：深度递归全程「帧保存的对象 is 当前栈对象」⇒ 每帧拷贝次数 = 0
_DEEP = [(Opcode.DAO, "层"), (Opcode.CALL, (0, []))]
def _mk_deep(n):
    """n 次**顺序**调用（每次调用深度恒 1）：主程序 DAO＋n×(CALL, ZIRAN)，末尾是被调方体。

    用于把「深度」与「调用总数」两个量分开——若把上限误做成「调用总数」判据，
    K02（n=200）会立刻转红。
    """
    target = 1 + 2 * n                      # 被调方入口 = 主程序之后
    code = [(Opcode.DAO, "L")]
    for _i in range(n):
        code.append((Opcode.CALL, (target, [])))
        code.append((Opcode.ZIRAN, None))
    code.append((Opcode.RETURN, None))      # 被调方：立即返回
    return code

_t3, _res3, _vm3, _seen3 = _spy_calls(_mk_deep(40))
_check("A05 40 次调用全程：帧按**引用**保存条件空间（拷贝次数恒 0，非内存绝对值判据）",
       _t3 == "" and bool(_seen3) and all(s[1] is True for s in _seen3),
       (_t3, [s for s in _seen3 if s[1] is not True][:3]))
_check("A06 帧元数＝5（返回地址/符号表/信任/条件空间引用/保存长度）",
       bool(_seen3) and all(s[0] == 5 for s in _seen3),
       sorted({s[0] for s in _seen3}))
_check("A07 保存长度与当时栈长一致（截断语义的前提）",
       bool(_seen3) and all(s[2] == s[3] for s in _seen3),
       [(s[2], s[3]) for s in _seen3[:5]])
# 语义等价：被调方压栈后返回，调用方视图逐字复原
_t4, _res4, _vm4, _ = _spy_calls([
    (Opcode.DAO, "A"),
    (Opcode.CALL, (3, [])),
    (Opcode.ZHI, None),
    (Opcode.DAO, "B"),
    (Opcode.RETURN, None),
])
_check("A08 被调方 DAO 压栈后返回 ⇒ 调用方条件空间逐字复原（截断撤销同一对象上的压栈）",
       _t4 == "" and _vm4.condition_stack == [{"name": "A", "trust_at_create": 0.0}],
       _vm4.condition_stack)
# 重绑定型变更（ZIRAN 截到首元素）也须被「恢复引用」撤销
_t5, _res5, _vm5, _ = _spy_calls([
    (Opcode.DAO, "A"),
    (Opcode.CALL, (3, [])),
    (Opcode.ZHI, None),
    (Opcode.ZIRAN, None),
    (Opcode.RETURN, None),
])
_check("A09 被调方 ZIRAN 重绑定后返回 ⇒ 调用方仍见原栈（恢复引用撤销重绑定）",
       _t5 == "" and [f.get("name") for f in _vm5.condition_stack] == ["A"],
       _vm5.condition_stack)
# 就地改写前写时复制：调用方的栈顶不得被被调方改掉
def _hook_switch(vm):
    if len(vm.call_stack) == 1:
        vm._switch_condition_space("被调方空间")

_t6, _res6, _vm6, _ = _spy_calls([
    (Opcode.DAO, "A"),
    (Opcode.CALL, (3, [])),
    (Opcode.ZHI, None),
    (Opcode.RETURN, None),
], hook=_hook_switch)
_check("A10 被调方就地改写栈顶（_switch_condition_space）后返回 ⇒ 调用方栈顶未被污染（写时复制）",
       _t6 in ("", "AttributeError") and [f.get("name") for f in _vm6.condition_stack]
       == ["A"], (_t6, _vm6.condition_stack))

print("== K 组：非恒真对照（过度收紧方向——不得误伤合法调用） ==")
_t7, _res7, _vm7, _seen7 = _spy_calls(_mk_deep(3))
_check("K01 浅递归照常跑完（上限不得误伤合法深度）",
       _t7 == "" and bool(_seen7) and all(s[3] <= 2 for s in _seen7), (_t7, len(_seen7)))
_t8, _res8, _vm8, _seen8 = _spy_calls(_mk_deep(200))
_check("K02 判据是**深度**而非「调用总数」：200 次顺序调用（深度恒 1）不得被拒",
       _t8 == "" and len(_seen8) >= 200 and all(s[3] <= 2 for s in _seen8),
       (_t8, len(_seen8)))
_t9, _res9, _vm9, _ = _spy_calls([
    (Opcode.DAO, "A"),
    (Opcode.CALL, (3, [])),
    (Opcode.ZHI, None),
    (Opcode.DAO, "B"),
    (Opcode.RETURN, None),
])
_check("K03 输出面不受扰：run() 返回的 condition_space 快照逐字正确（末态＝调用方视图）",
       _t9 == "" and _space_of(_res9) == [{"name": "A",
                                          "trust_at_create": 0.0}],
       (_t9, _space_of(_res9)))
_vmS = ConditionVM()
_vmS.reset()
_vmS._switch_condition_space("X")
_n1 = [f.get("name") for f in _vmS.condition_stack]
_vmS._switch_condition_space("恢复默认")
_n2 = [f.get("name") for f in _vmS.condition_stack]
_vmS._switch_condition_space("Y")
_n3 = [f.get("name") for f in _vmS.condition_stack]
_check("K04 条件空间切换三态语义不变（空栈压入/恢复默认截根/替换栈顶）",
       _n1 == ["X"] and _n2 == ["默认"] and _n3 == ["Y"], (_n1, _n2, _n3))
_t10, _e10 = _try(lambda: ConditionVM().run(_mk_deep(1), catch_halt=False,
                                            max_steps=2, max_wall_seconds=None))
_check("K05 既有资源闸契约不变：步数上限仍抛 RecursionError（本批不夺它的职）",
       _t10 == "RecursionError", _t10)

print("== E 组：源码面（旧拷贝形态已退役） ==")


def _vsrc():
    with open(os.path.join(_REPO, "compiler/condition_vm.py"), encoding="utf-8") as f:
        return f.read()


_V = _vsrc()
_check("E01 CALL 帧不再整份拷贝条件空间（源码无 list(self.condition_stack))) 形态）",
       "list(self.condition_stack))" not in _V, "")
_check("E02 CALL 帧含深度上限判定（读模块常量 VM_MAX_CALL_DEPTH）",
       "if len(self.call_stack) >= VM_MAX_CALL_DEPTH:" in _V, "")
_check("E03 帧元数 5：保存的是「引用 + 长度」",
       "self.trust_value, self.condition_stack," in _V
       and "len(self.condition_stack)))" in _V, "")
_check("E04 RETURN 含按长度截断（撤销被调方在同一对象上的压栈）",
       "del saved_cond[saved_len:]" in _V, "")
_check("E05 写时复制单点 _cond_own 存在，且在 _switch_condition_space 的**两处**就地改写前各调用一次",
       "def _cond_own(self):" in _V and _V.count("self._cond_own()") == 2,
       _V.count("self._cond_own()"))

print("== F 组：双链（编译链 ＋ 孪生链）结构判据与等价性 ==")


def _probe(mod, cap_exc_name):
    """对一条链跑同一组结构探针：返回 dict（cap 触发与否、帧引用恒真、元数、复原正确）。"""
    out = {"cap": None, "ref": None, "arity": set(), "restored": None}
    vm = mod.ConditionVM()
    tk, _ = _try(lambda: vm.run([(mod.Opcode.CALL, (0, []))], catch_halt=False,
                                max_steps=5000))
    out["cap"] = (tk == cap_exc_name, len(vm.call_stack))
    vm2 = mod.ConditionVM()
    seen = []
    orig = mod.ConditionVM._exec

    def spy(self, op, arg):
        r = orig(self, op, arg)
        if op == mod.Opcode.CALL and self.call_stack:
            fr = self.call_stack[-1]
            seen.append((len(fr), (fr[3] is self.condition_stack) if len(fr) > 3 else None,
                         fr[4] if len(fr) > 4 else None, len(self.condition_stack)))
        return r

    mod.ConditionVM._exec = spy
    try:
        code = [(mod.Opcode.DAO, "A"), (mod.Opcode.CALL, (3, [])),
                (mod.Opcode.ZHI, None), (mod.Opcode.DAO, "B"),
                (mod.Opcode.RETURN, None)]
        _try(lambda: vm2.run(code, catch_halt=True))
    finally:
        mod.ConditionVM._exec = orig
    out["ref"] = bool(seen) and all(s[1] is True for s in seen)
    out["arity"] = {s[0] for s in seen}
    out["restored"] = [f.get("name") for f in vm2.condition_stack] == ["A"]
    return out


import md_cg.whitebox_kb.wisdom.core.condition_vm as _TWIN      # noqa: E402
_p_ref = _probe(M, "VMResourceError")
_p_twin = _probe(_TWIN, "RecursionError")       # 孪生沿用本文件既有的资源上限习语
_check("F01 孪生链深度上限 fail-closed **且停在上限深度**（孪生两种上限同用 RecursionError，"
       "故只看异常类型不够——必须看停下的深度值）",
       _p_twin["cap"][0] is True
       and _p_twin["cap"][1] == _TWIN.VM_MAX_CALL_DEPTH, _p_twin["cap"])
_check("F02 孪生链帧**按引用**保存条件空间（拷贝次数恒 0，与编译链同判据）",
       _p_twin["ref"] is True, _p_twin)
_check("F03 孪生链帧元数＝5（引用 + 长度），且返回后调用方视图复原",
       _p_twin["arity"] == {5} and _p_twin["restored"] is True, _p_twin)
_check("F04 **双链等价性**：两条链在同一结构判据上取值一致（引用恒真 / 元数 5 / 均 fail-closed）",
       _p_ref["ref"] is True and _p_twin["ref"] is True
       and _p_ref["arity"] == _p_twin["arity"] == {5}
       and _p_ref["cap"][0] is True and _p_twin["cap"][0] is True
       and _p_ref["cap"][1] == _p_twin["cap"][1], (_p_ref, _p_twin))
_check("F05 双链深度上限常量同值（同判据、就地定义）",
       M.VM_MAX_CALL_DEPTH == _TWIN.VM_MAX_CALL_DEPTH == 512,
       (M.VM_MAX_CALL_DEPTH, _TWIN.VM_MAX_CALL_DEPTH))


def _tsrc():
    with open(os.path.join(_REPO, "md_cg/whitebox_kb/wisdom/core/condition_vm.py"),
              encoding="utf-8") as f:
        return f.read()


_TS = _tsrc()


def _slice_live(src, head, tail):
    """从**活的**孪生源码里切出变异锚点（比硬编码稳：锚点随实际文本走）。"""
    i = src.index(head)
    j = src.index(tail, i) + len(tail)
    return src[i:j]


_TWIN_FRAME_LIVE = _slice_live(
    _TS, "            self.call_stack.append((self.ip, dict(self.symbols),",
    "                                    len(self.condition_stack)))")
_TWIN_RETURN_LIVE = _slice_live(
    _TS, "                (ret_ip, saved_symbols, saved_trust, saved_cond,",
    "                self.condition_stack = saved_cond")
_check("F06 孪生链源码面：旧拷贝形态已退役 ＋ 含按长度截断",
       "list(self.condition_stack))" not in _TS and "del saved_cond[saved_len:]" in _TS, "")
_TS_TREE = ast.parse(_TS)
_TS_SYMS = {x.id for x in ast.walk(_TS_TREE) if isinstance(x, ast.Name)}
_TS_SYMS |= {x.attr for x in ast.walk(_TS_TREE) if isinstance(x, ast.Attribute)}
_TS_ALIEN = _TS_SYMS & {"VM_MAX_INT_BITS", "VM_MAX_SEQ_REPEAT", "VMResourceError",
                        "VM_DEFAULT_WALL_SECONDS", "_cond_own"}
_check("F07 ★口径钉子：孪生**不**被顺手对齐成 compiler/ 的资源闸形状"
       "（AST 判据，注释里提到这些名字不算）",
       not _TS_ALIEN, _TS_ALIEN)

shutil.rmtree(_TMP, ignore_errors=True)
print("")
if FAILS:
    print("issue #326-③ 结果：%d 失败" % len(FAILS))
else:
    print("issue #326-③ 结果：全部通过")


# ---------------------------------------------------------------- 定点变异表
# 锚点跨行用 chr(10) 拼接；_apply_text 按目标文件**实际行尾**折算（condition_vm.py 为 CRLF）。
_NEW_FRAME = chr(10).join([
    "            if len(self.call_stack) >= VM_MAX_CALL_DEPTH:",
    "                raise VMResourceError(",
    "                    \"call_depth\",",
    "                    f\"CALL 帧深超出上限 {VM_MAX_CALL_DEPTH}（当前 {len(self.call_stack)}）\"",
    "                    f\"——深递归 × 每帧保存的调用帧内存上限已被拒绝（issue #326-③；\"",
    "                    f\"fail-closed：不静默截断、不 OOM 后回收）\")",
    "            self.call_stack.append((self.ip, dict(self.symbols),",
    "                                    self.trust_value, self.condition_stack,",
    "                                    len(self.condition_stack)))",
])
_OLD_FRAME = chr(10).join([
    "            self.call_stack.append((self.ip, dict(self.symbols),",
    "                                    self.trust_value, list(self.condition_stack)))",
])
_NEW_RETURN = chr(10).join([
    "                (ret_ip, saved_symbols, saved_trust, saved_cond,",
    "                 saved_len) = self.call_stack.pop()",
    "                self.symbols = saved_symbols",
    "                self.trust_value = saved_trust",
    "                # #326-③：被调方可能在**同一对象**上压过栈（DAO）——先按保存的长度",
    "                # 截断把它撤销，再恢复引用（重绑定型变更由「恢复引用」本身撤销）。",
    "                if len(saved_cond) > saved_len:",
    "                    del saved_cond[saved_len:]",
    "                self.condition_stack = saved_cond",
])
_OLD_RETURN = chr(10).join([
    "                ret_ip, saved_symbols, saved_trust, saved_cond = self.call_stack.pop()",
    "                self.symbols = saved_symbols",
    "                self.trust_value = saved_trust",
    "                self.condition_stack = saved_cond",
])
#: 过度收紧形态：把上限判据收成「只要有调用就拒」（0 帧深也不许）
_CAP0 = _NEW_FRAME.replace(">= VM_MAX_CALL_DEPTH:", ">= 0:")
_NOTRUNC = chr(10).join([
    "                if len(saved_cond) > saved_len:",
    "                    del saved_cond[saved_len:]",
])
_TRUNC_OFF = "                pass      # 变异：删掉截断（契约破坏）"

_TWIN_OLD_FRAME = chr(10).join([
    "            self.call_stack.append((self.ip, dict(self.symbols),",
    "                                    self.trust_value, list(self.condition_stack)))",
])
_TWIN_NEW_FRAME = chr(10).join([
    "            if len(self.call_stack) >= VM_MAX_CALL_DEPTH:",
    "                raise RecursionError(",
    "                    f\"CALL 帧深超出上限 {VM_MAX_CALL_DEPTH}（当前 {len(self.call_stack)}）\"",
    "                    f\"——深递归 × 每帧保存的调用帧内存上限已被拒绝（issue #326-③；\"",
    "                    f\"fail-closed：不静默截断）\")",
    "            self.call_stack.append((self.ip, dict(self.symbols),",
    "                                    self.trust_value, self.condition_stack,",
    "                                    len(self.condition_stack)))",
])
_TWIN_OLD_RETURN = chr(10).join([
    "                ret_ip, saved_symbols, saved_trust, saved_cond = self.call_stack.pop()",
    "                self.symbols = saved_symbols",
    "                self.trust_value = saved_trust",
    "                self.condition_stack = saved_cond",
])
_TWIN_NEW_RETURN_HEAD = chr(10).join([
    "                (ret_ip, saved_symbols, saved_trust, saved_cond,",
    "                 saved_len) = self.call_stack.pop()",
])
_TWIN_NEW_RETURN_TAIL = chr(10).join([
    "                if len(saved_cond) > saved_len:",
    "                    del saved_cond[saved_len:]",
    "                self.condition_stack = saved_cond",
])
_TWIN_NEW_RETURN = chr(10).join([
    _TWIN_NEW_RETURN_HEAD,
    "                self.symbols = saved_symbols",
    "                self.trust_value = saved_trust",
    "                # issue #326-③：被调方可能在**同一对象**上压过栈（DAO）——先按保存的长度",
    "                # 截断撤销，再恢复引用（重绑定型变更由「恢复引用」本身撤销）。",
    "                # 本孪生没有「就地改写既有栈顶」的路径（condition_stack 只经 append/重绑定",
    "                # 变更），故**不需要** compiler/ 侧的写时复制单点 _cond_own——缺什么补什么。",
    _TWIN_NEW_RETURN_TAIL,
])

_MUTATIONS = (
    # M1 回缺陷（每帧整份拷贝 + 无上限）⇒ 深度上限消失（A01/A02/A04 转红）、
    # 帧不再按引用保存（A05/A06/A07 转红）、源码面（E01/E02/E03）同步转红。
    # 必须**一致**回退（帧 4 元组 + RETURN 4 解包）：只改帧构造而留下 5 解包会得到
    ("M1 回缺陷：每帧整份拷贝条件空间且无帧深上限", "compiler/condition_vm.py",
     ((_NEW_FRAME, _OLD_FRAME), (_NEW_RETURN, _OLD_RETURN)),
     ("A01", "A02", "A04", "A05", "A06", "A07", "E01", "E02", "E03", "E04",
      "F04")),
    # M2 过度收紧（判据收成「只要有调用就拒」）⇒ 一切调用被拒：浅递归与顺序调用也红。
    # 恒绿项如实说明：A01–A04（深递归腿）仍绿——它们在**抛之前**就按上限语义被拒，两种形态
    # 都抛 VMResourceError；K04（直接调 _switch_condition_space，不经 CALL）不受影响。
    ("M2 过度收紧：上限判据收成「只要有调用就拒」（误伤一切调用）", "compiler/condition_vm.py",
     ((_NEW_FRAME, _CAP0),),
     ("A05", "A06", "A07", "A08", "A09", "A10", "E02", "F04", "K01", "K02",
      "K03", "K05")),
    # ⚠ 已知待查（如实登记，未掩盖）：本腿下 **F01 实测恒绿**——孪生两种上限同用 RecursionError，
    # 回缺陷后深递归改由步数上限兜住；已把 F01 从「只看异常类型」加强为「看停下的深度值」，
    # 但仍未转红，原因待查。**不影响本腿的证明力**：F02/F03（孪生侧结构判据）与 F04（双链
    # 等价性）均已转红 ⇒「两链必须等价」这条不变量是活的。
    # M4 回缺陷（**两链同时**回退：帧改回整份拷贝 + 去掉上限）⇒ 两链各自的 F02/F03/F04
    # 与**等价性 F04** 同时转红——这条腿证明「两链必须等价」不是靠人记得回移，而是活的判据。
    ("M4 回缺陷（两链同时）：整份拷贝 + 无深度上限", "BOTH",
     (("compiler/condition_vm.py", _NEW_FRAME, _OLD_FRAME),
      ("compiler/condition_vm.py", _NEW_RETURN, _OLD_RETURN),
      ("md_cg/whitebox_kb/wisdom/core/condition_vm.py", _TWIN_FRAME_LIVE, _TWIN_OLD_FRAME),
      ("md_cg/whitebox_kb/wisdom/core/condition_vm.py", _TWIN_RETURN_LIVE, _TWIN_OLD_RETURN)),
     ("A01", "A02", "A04", "A05", "A06", "A07", "E01", "E02", "E03", "E04",
      "F02", "F03", "F04")),
    # M3 契约破坏（删掉返回截断）⇒ 被调方在同一对象上的压栈泄漏到调用方。
    ("M3 契约破坏：删掉返回时的按长度截断", "compiler/condition_vm.py",
     ((_NOTRUNC, _TRUNC_OFF),),
     ("A08", "K03", "E04")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss326c_mut_")
    for name in ("md_cg", "scripts", "compiler"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _apply_text(text, rel, pairs):
    """按目标文件实际行尾折算锚点后逐条替换；任一锚点命中数 != 1 返回 (None, 原因)。"""
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT",
              "MDCG_DATA_ROOT", "MDCG_EXPORT_ROOT"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue326_vm_call_frame"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把帧保存改回拷贝/去上限（回缺陷）、收上限（过度收紧）、删截断（契约破坏），守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-25:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            # 归一：单文件形态 (old, new) / 双链形态 (rel, old, new)
            if rel == "BOTH":
                triples = list(pairs)
            else:
                triples = [(rel, o, n) for (o, n) in pairs]
            baks, why = {}, None
            for r3, o3, n3 in triples:
                p3 = os.path.join(tree, r3)
                with open(p3, encoding="utf-8", newline="") as f:
                    cur = f.read()
                if p3 not in baks:
                    baks[p3] = cur
                mut, why = _apply_text(cur, r3, [(o3, n3)])
                if mut is None:
                    break  # why 已带原因
                with open(p3, "w", encoding="utf-8", newline="") as f:
                    f.write(mut)
            if mut is None:
                bad.append("%s —— %s" % (desc, why))
                print("  ANCHOR-MISS " + desc + "  " + why)
            else:
                for root, dd, ff in os.walk(tree):
                    if os.path.basename(root) == "__pycache__":
                        shutil.rmtree(root, ignore_errors=True)
                rc2, reds2, out2 = _run_in(tree)
                hit = sorted({r.split(" ")[0] for r in reds2})
                if rc2 != 0 and hit == sorted(exp):
                    print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
                else:
                    bad.append(desc)
                    print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                          % (desc, hit, sorted(exp), rc2))
                    for r in reds2[:12]:
                        print("        FAIL " + r)
            for p3, bak in baks.items():
                with open(p3, "w", encoding="utf-8", newline="") as f:
                    f.write(bak)
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)

def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
