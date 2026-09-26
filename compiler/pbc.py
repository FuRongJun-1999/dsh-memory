"""
pbc.py · 原生编译产物（第六阶段 C3）：.pbc 字节码文件
中文源码 → 字节码 → .pbc 文件（序列化）→ 独立 VM 加载执行（零 Python 运行时依赖）
格式与白箱单元「字节码-序列化/反序列化」一致（白箱自举产物落地项目）。
  [op: len2B+utf8][arg_tag:1B][arg_data...]
  arg_tag: 0=None, 1=bool, 2=int8B, 3=float8B, 4=str(len2B+utf8), 5=tuple(float8B+int8B),
           6=(int8B + str列表 len2B+各 len2B+utf8)[CALL 签名,v0.4 扩展——向后兼容,旧 tag 不变]
"""

import struct


# 生效条件：op 具有 name 属性时返回 op.name，否则返回 str(op)。
def _op_name(op):
    """Opcode 枚举 → 字符串名（compiler.py 生成枚举，白箱单元生成字符串——统一）"""
    return op.name if hasattr(op, "name") else str(op)


# 生效条件：对 code 中每个 (op,arg)，arg 为 None/bool/int/float/str 时分别写标签 0/1/2/3/4（bool 先于 int 命中），arg 为二元组且 arg[1] 是元素全为 str 的 list/tuple 时写标签 6，arg 为其他 tuple 时按 arg[0]、arg[1] 写标签 5，其余类型抛 ValueError，全部编码后返回 bytes(out)。
def serialize(code):
    """指令列表 → .pbc 字节串（op 兼容枚举/字符串）"""
    out = bytearray()
    for op, arg in code:
        b = _op_name(op).encode("utf-8")
        out.extend(struct.pack("H", len(b)))
        out.extend(b)
        if arg is None:
            out.append(0)
        elif isinstance(arg, bool):
            out.append(1)
            out.append(1 if arg else 0)
        elif isinstance(arg, int):
            out.append(2)
            out.extend(struct.pack("q", arg))
        elif isinstance(arg, float):
            out.append(3)
            out.extend(struct.pack("d", arg))
        elif isinstance(arg, str):
            s = arg.encode("utf-8")
            out.append(4)
            out.extend(struct.pack("H", len(s)))
            out.extend(s)
        elif isinstance(arg, tuple) and len(arg) == 2 and isinstance(arg[1], (list, tuple)) \
                and all(isinstance(x, str) for x in arg[1]):
            # v0.4 tag6：CALL 签名 (入口 ip:int, 参数名列表 [str...])
            out.append(6)
            out.extend(struct.pack("q", arg[0]))
            out.extend(struct.pack("H", len(arg[1])))
            for s in arg[1]:
                sb = s.encode("utf-8")
                out.extend(struct.pack("H", len(sb)))
                out.extend(sb)
        elif isinstance(arg, tuple):
            out.append(5)
            out.extend(struct.pack("d", arg[0]))
            out.extend(struct.pack("q", arg[1]))
        else:
            raise ValueError(f"无法序列化参数 {arg!r}")
    return bytes(out)


# 生效条件：i<len(data) 时按 H 长度前缀读 op 名、再按 tag 分支还原 0→None、1→bool、2→int(q)、3→float(d)、4→str、5→(float, int)、6→(入口 int, 参数名 list)，其他 tag 抛 ValueError，逐条 append 后返回 code 列表（data 为空则返回空列表）。
def deserialize(data):
    """.pbc 字节串 → 指令列表"""
    code, i = [], 0
    while i < len(data):
        n = struct.unpack_from("H", data, i)[0]
        i += 2
        op = data[i:i + n].decode("utf-8")
        i += n
        tag = data[i]
        i += 1
        if tag == 0:
            arg = None
        elif tag == 1:
            arg = data[i] == 1
            i += 1
        elif tag == 2:
            arg = struct.unpack_from("q", data, i)[0]
            i += 8
        elif tag == 3:
            arg = struct.unpack_from("d", data, i)[0]
            i += 8
        elif tag == 4:
            m = struct.unpack_from("H", data, i)[0]
            i += 2
            arg = data[i:i + m].decode("utf-8")
            i += m
        elif tag == 5:
            t = struct.unpack_from("d", data, i)[0]
            a = struct.unpack_from("q", data, i + 8)[0]
            arg = (t, a)
            i += 16
        elif tag == 6:
            entry = struct.unpack_from("q", data, i)[0]
            i += 8
            n_params = struct.unpack_from("H", data, i)[0]
            i += 2
            params = []
            for _ in range(n_params):
                m = struct.unpack_from("H", data, i)[0]
                i += 2
                params.append(data[i:i + m].decode("utf-8"))
                i += m
            arg = (entry, params)
        else:
            raise ValueError(f"未知标签 {tag}")
        code.append((op, arg))
    return code


# 生效条件：调用即以 "wb" 打开 path 写入 serialize(code)（无类型/存在性校验），随后返回 path。
def save_pbc(code, path):
    """字节码 → .pbc 文件"""
    with open(path, "wb") as f:
        f.write(serialize(code))
    return path


# 生效条件：调用即以 "rb" 打开 path 读取全部字节并交给 deserialize，直接返回其结果。
def load_pbc(path):
    """.pbc 文件 → 字节码"""
    with open(path, "rb") as f:
        return deserialize(f.read())


# 生效条件：调用 compile_source(source, strict=strict)（strict 默认 False，即名实校验仅告警），result["ok"] 为假时返回 (None, result)，为真时 save_pbc(code, path) 后返回 (code, result)。
def compile_to_pbc(source, path, strict=False):
    """中文源码 → .pbc 文件（原生编译入口；strict=False 名实校验为警告）"""
    from .compiler import compile_source
    code, result = compile_source(source, strict=strict)
    if not result["ok"]:
        return None, result
    save_pbc(code, path)
    return code, result


# 生效条件：先 load_pbc(path) 并把每条 op 名经 Opcode[name] 转成枚举（未知名抛 KeyError），再以传入的 symbols、trust（默认 0.0，0.0 不回落到别的值）、condition_stack、max_wall_seconds（默认 VM_DEFAULT_WALL_SECONDS=10.0，可传 None/0 关闭）调用 ConditionVM().run 并返回其结果；N149 资源加固自 run 生效（步数上限/MUL 规模守卫/墙钟预算/MemoryError 结构化——恶意 .pbc 得 VMResourceError 而非挂起或裸 MemoryError）。
def run_pbc(path, symbols=None, trust=0.0, condition_stack=None,
            max_wall_seconds=None):
    """.pbc 文件 → VM 执行（独立运行时入口；N149：显式携带墙钟预算，
    步数/MUL 规模/内存守卫在 ConditionVM.run 内置生效）"""
    from .condition_vm import ConditionVM, Opcode, VM_DEFAULT_WALL_SECONDS
    code = load_pbc(path)
    # 字符串 op → Opcode 枚举（VM _exec 期望枚举）
    code = [(Opcode[name], arg) for name, arg in code]
    return ConditionVM().run(code, symbols=symbols, trust=trust,
                             condition_stack=condition_stack,
                             max_wall_seconds=VM_DEFAULT_WALL_SECONDS
                             if max_wall_seconds is None else max_wall_seconds)


if __name__ == "__main__":
    print("=== C3：原生编译（中文源码 → .pbc → 独立执行）===\n")
    import os, tempfile
    src = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""
    tmp = tempfile.mkdtemp(prefix="pbc_")
    pbc = os.path.join(tmp, "out.pbc")
    code, r = compile_to_pbc(src, pbc)
    if r["ok"]:
        size = os.path.getsize(pbc)
        print(f"① 编译 → {pbc}（{size} 字节 .pbc 原生产物）")
        state = run_pbc(pbc, symbols={"信任值": 0.5})
        print(f"② 独立执行: 信任={state['trust']} 条件空间={state['condition_space']} "
              f"停止={state['halt']}")
        ok = state["trust"] >= 0.7 and state["condition_space"] and state["halt"] == "halt"
        print(f"\n=== 判定 ===\n原生编译: "
              f"{'✔ .pbc 文件独立执行（零 Python 运行时依赖）' if ok else '✘'}")
    else:
        print("编译错误:", r["errors"][:3])