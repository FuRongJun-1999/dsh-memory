"""
debugger.py · 调试器（第六阶段 C4）：VM 单步 + 条件空间状态
基于 ConditionVM 的单步执行：每步显示 ip/指令/栈/符号/信任/条件空间——
白箱可解释原则：执行过程逐步可见。
"""

from .condition_vm import ConditionVM, VMHalt


class VMDebugger:
    """单步调试器：step() 执行一条指令并返回状态快照"""

    def __init__(self, code, symbols=None, trust=0.0, condition_stack=None):
        self.vm = ConditionVM()
        self.code = code
        self.vm.reset(symbols, trust, condition_stack)
        self.ip = 0
        self.trace = []          # 每步状态（调试轨迹）

    def _snapshot(self, halt=None):
        return {"ip": self.ip,
                "op": self._op_name(self.code[self.ip][0]) if self.ip < len(self.code) else "EOF",
                "stack": list(self.vm.stack),
                "symbols": dict(self.vm.symbols),
                "trust": round(self.vm.trust_value, 3),
                "cond": list(self.vm.condition_stack),
                "halt": halt}

    @staticmethod
    def _op_name(op):
        return op.name if hasattr(op, "name") else str(op)

    def step(self):
        """执行一条指令 → 状态快照（止/无为=halt；越界=None）"""
        if self.ip >= len(self.code):
            return None
        op, arg = self.code[self.ip]
        self.ip += 1
        try:
            self.vm._exec(op, arg)
            halt = None
        except VMHalt as h:
            halt = h.kind
        snap = self._snapshot(halt)
        self.trace.append(snap)
        return snap

    def run(self, max_steps=1000):
        """单步直到 halt/结束 → 轨迹（调试输出）"""
        while self.ip < len(self.code) and len(self.trace) < max_steps:
            snap = self.step()
            if snap and snap.get("halt"):
                break
        return self.trace

    def state(self):
        return {"ip": self.ip, "stack": list(self.vm.stack),
                "symbols": dict(self.vm.symbols),
                "trust": round(self.vm.trust_value, 3),
                "cond": list(self.vm.condition_stack),
                "halt": self.trace[-1].get("halt") if self.trace else None}


def debug_pbc(path, symbols=None, trust=0.0, condition_stack=None):
    """.pbc 文件 → 单步调试轨迹"""
    from .pbc import load_pbc
    from .condition_vm import Opcode
    code = [(Opcode[n], a) for n, a in load_pbc(path)]
    return VMDebugger(code, symbols, trust, condition_stack).run()


if __name__ == "__main__":
    print("=== C4：调试器（VM 单步 + 条件空间状态）===\n")
    src = """术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""
    from .compiler import compile_source
    code, r = compile_source(src, strict=False)
    if r["ok"]:
        dbg = VMDebugger(code, symbols={"信任值": 0.5})
        trace = dbg.run()
        for snap in trace:
            print(f"  ip={snap['ip']:2d} {snap['op']:12s} 信任={snap['trust']} "
                  f"条件空间={[c['name'] for c in snap['cond']]} 停止={snap['halt']}")
        ok = dbg.state()["trust"] >= 0.7 and dbg.state()["halt"] == "halt"
        print(f"\n=== 判定 ===\n调试器: "
              f"{'✔ 单步轨迹成立（逐步可见：信任递增/条件空间/止）' if ok else '✘'}")
