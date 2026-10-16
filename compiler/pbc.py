"""
pbc.py · 原生编译产物（第六阶段 C3）：.pbc 字节码文件
中文源码 → 字节码 → .pbc 文件（序列化）→ 独立 VM 加载执行（零 Python 运行时依赖）
格式与白箱单元「字节码-序列化/反序列化」一致（白箱自举产物落地项目）。
  [op: len2B+utf8][arg_tag:1B][arg_data...]
  arg_tag: 0=None, 1=bool, 2=int8B, 3=float8B, 4=str(len2B+utf8), 5=tuple(float8B+int8B),
           6=(int8B + str列表 len2B+各 len2B+utf8)[CALL 签名,v0.4 扩展——向后兼容,旧 tag 不变]
"""

import os
import struct
import tempfile
import time


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
# **输入必须完整（issue #402）**：任一段的剩余字节不足以读出该段（长度前缀 / op 名 / 参数标签 /
# 数值载荷 / str 载荷 / tag6 参数名）时抛 PbcTruncated（ValueError 子类，带 what/need/offset/remain
# 四字段）——截断件**绝不静默**返回更短或更少的指令（此前 :69/:87/:103 的切片会把截断件读成
# 合法但更短的 op 名/字符串，rc=0 执行出错误结果）。
class PbcTruncated(ValueError):
    """pbc 输入被截断：读取某一段时剩余字节不足。"""

    def __init__(self, what, need, offset, remain):
        self.what = what
        self.need = need
        self.offset = offset
        self.remain = remain
        super().__init__("pbc 截断：%s 需要 %d 字节，偏移 %d 处仅剩 %d 字节"
                         % (what, need, offset, remain))


# 生效条件：给定 data、偏移 i、需求长度 n 与段名 what，当 i<0 或 i+n>len(data) 时抛 PbcTruncated；
# 否则返回 None 放行。**截断判据的唯一实现**——deserialize 内每一处 struct.unpack_from /
# data[i] / data[i:i+n] 之前逐点调用（这三类读取此前分别抛 struct.error / IndexError /
# 静默短串，最后者最危险）。新增读取点时同步加调用，否则该点重新落回旧形态。
def _need(data, i, n, what):
    if i < 0 or i + n > len(data):
        raise PbcTruncated(what, n, i, max(0, len(data) - i))


# 生效条件：load_pbc 读到 path 的字节交给 deserialize 抛 ValueError（含 PbcTruncated / 未知标签 /
# utf-8 解码失败）时，以本类重新抛出：仍是 ValueError 子类（既有 except ValueError 调用方不受影响），
# 额外带 path/bytes 两个字段，使 CLI 与调用方能在错误面**点名文件**。
class PbcFormatError(ValueError):
    """pbc 文件不可用（截断或畸形）：不返回半截指令。"""

    def __init__(self, path, nbytes, cause):
        self.path = path
        self.bytes = nbytes
        self.cause = cause
        super().__init__("%s 不是完整可用的 .pbc（%d 字节）：%s"
                         % (path, nbytes, cause))


def deserialize(data):
    """.pbc 字节串 → 指令列表"""
    code, i = [], 0
    while i < len(data):
        _need(data, i, 2, "op 名长度前缀")
        n = struct.unpack_from("H", data, i)[0]
        i += 2
        _need(data, i, n, "op 名")
        op = data[i:i + n].decode("utf-8")
        i += n
        _need(data, i, 1, "参数标签")
        tag = data[i]
        i += 1
        if tag == 0:
            arg = None
        elif tag == 1:
            _need(data, i, 1, "bool 载荷")
            arg = data[i] == 1
            i += 1
        elif tag == 2:
            _need(data, i, 8, "int 载荷")
            arg = struct.unpack_from("q", data, i)[0]
            i += 8
        elif tag == 3:
            _need(data, i, 8, "float 载荷")
            arg = struct.unpack_from("d", data, i)[0]
            i += 8
        elif tag == 4:
            _need(data, i, 2, "str 长度前缀")
            m = struct.unpack_from("H", data, i)[0]
            i += 2
            _need(data, i, m, "str 载荷")
            arg = data[i:i + m].decode("utf-8")
            i += m
        elif tag == 5:
            _need(data, i, 16, "tuple 载荷")
            t = struct.unpack_from("d", data, i)[0]
            a = struct.unpack_from("q", data, i + 8)[0]
            arg = (t, a)
            i += 16
        elif tag == 6:
            _need(data, i, 8, "tag6 入口地址")
            entry = struct.unpack_from("q", data, i)[0]
            i += 8
            _need(data, i, 2, "tag6 参数个数")
            n_params = struct.unpack_from("H", data, i)[0]
            i += 2
            params = []
            for _ in range(n_params):
                _need(data, i, 2, "tag6 参数名长度前缀")
                m = struct.unpack_from("H", data, i)[0]
                i += 2
                _need(data, i, m, "tag6 参数名")
                params.append(data[i:i + m].decode("utf-8"))
                i += m
            arg = (entry, params)
        else:
            raise ValueError(f"未知标签 {tag}")
        code.append((op, arg))
    return code


# 生效条件：调用即把 serialize(code) 原子替换到 path（无类型/存在性校验），随后返回 path。
# 原子写（issue #402）：**临时名唯一 + 同目录 + os.replace**，与 md_cg/fsutil.py 的
# _publish:32 / publish:46 / atomic_write:57 同一语义的另一次实现——本包是 stdlib-only
# 自包含包（__init__.py:6「stdlib only，对齐 md_cg D-005」），不得 import md_cg，故此处
# 用 os/tempfile 自写；Windows 下 os.replace 会被短暂持锁拒绝，故带短重试（同 fsutil._RENAME_TRIES）。
# 改前是裸 open(path,"wb") 直写：写中断/写满即留下**截断件**，而截断件在改前会被静默执行。
_PBC_RENAME_TRIES = 20
_PBC_RENAME_WAIT = 0.005


# 生效条件：tmp 与 path 给定后循环至多 _PBC_RENAME_TRIES 次调用 os.replace(tmp, path)，成功即返回；仅捕获 PermissionError，非最后一次则 time.sleep(_PBC_RENAME_WAIT) 重试，最后一次仍 PermissionError 则抛出。
def _publish(tmp, path):
    for i in range(_PBC_RENAME_TRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == _PBC_RENAME_TRIES - 1:
                raise
            time.sleep(_PBC_RENAME_WAIT)


def save_pbc(code, path):
    """字节码 → .pbc 文件（原子替换：读者只会看到旧件或完整新件）"""
    blob = serialize(code)
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".tmp-", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        _publish(tmp, path)
        tmp = None
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return path


# 生效条件：调用即以 "rb" 打开 path 读取全部字节并交给 deserialize 返回其结果；文件被截断/畸形时
# 把 deserialize 抛出的 PbcTruncated/ValueError 统一转成 PbcFormatError（带 path，仍属 ValueError）
# 抛出，调用方按既有错误面呈现（非零退出码 + 点名），**不静默**返回半截结果。
def load_pbc(path):
    """.pbc 文件 → 字节码（截断/畸形件抛 PbcFormatError，不返回半截结果）"""
    with open(path, "rb") as f:
        data = f.read()
    try:
        return deserialize(data)
    except ValueError as exc:
        raise PbcFormatError(path, len(data), exc) from exc


# 生效条件：调用 compile_source(source, strict=strict)（strict 默认 False，即名实校验仅告警），result["ok"] 为假时返回 (None, result)，为真时 save_pbc(code, path) 后返回 (code, result)。
def compile_to_pbc(source, path, strict=False):
    """中文源码 → .pbc 文件（原生编译入口；strict=False 名实校验为警告）"""
    from .compiler import compile_source
    code, result = compile_source(source, strict=strict)
    if not result["ok"]:
        return None, result
    save_pbc(code, path)
    return code, result


# 生效条件：先 load_pbc(path)（截断/畸形件抛 PbcFormatError，不执行半截指令）并把每条 op 名经 Opcode[name] 转成枚举（未知名抛 KeyError），再以传入的 symbols、trust（默认 0.0，0.0 不回落到别的值）、condition_stack、max_wall_seconds（默认 VM_DEFAULT_WALL_SECONDS=10.0，可传 None/0 关闭）调用 ConditionVM().run 并返回其结果；N149 资源加固自 run 生效（步数上限/MUL 规模守卫/墙钟预算/MemoryError 结构化——恶意 .pbc 得 VMResourceError 而非挂起或裸 MemoryError）。
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