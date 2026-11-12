# -*- coding: utf-8 -*-
# 功能名：.pbc 反序列化长度判据——截断件不得被静默执行成半截错值（issue #402）
# 生效条件：python -X utf8 -m compiler.tests.test_issue402_pbc_truncation [--mutate]；被测面＝compiler/pbc.py 的 deserialize（_need 长度判据单点 + 非 UTF-8 结构化）与 save_pbc（原子写）
# 子功能：A 组＝报告点（cut=23/26/29/32）与全部**非指令边界**截断点一律结构化 ValueError、无裸 IndexError/struct.error/UnicodeDecodeError；B 组＝run_pbc 对非边界截断件不得返回结果、坏 UTF-8 结构化拒；K 组＝非恒真对照（完整件往返逐位一致、空程序合法、tag 0-6 全形态往返、原子写内容与 serialize 逐字节相同且不残留临时件）；E 组＝源码面锚点（_need 判据、每处读取前调用、os.replace）；R 组＝**登记不判别档**：指令边界处的截断（raw 格式无长度信息，物理上不可判）静默点集合必须**恰好等于**合法边界集合，不得多一个
# 执行：--mutate 时把 _need 换成恒真（回缺陷形态），A/B 组指定项必须转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下红项集合须与预期逐项相符
# 不适用条件：不判「指令边界截断」这一类（R 组显式登记为不判别档——裸格式无长度/校验信息，任何实现都无法区分「截断的短程序」与「合法短程序」；彻底关闭需格式版本化容器头，牵动 Rust 运行时与白箱孪生，已 NEED_FILE 上报）；不判 CLI cmd_run 退出码文本（compiler/cli/__init__.py 不在本单元授权文件内）；不判 Rust 侧 pbc.rs
"""issue #402 守卫：deserialize 无长度判据 ⇒ 截断 .pbc 被静默执行成错结果。

修前实测（176 字节）：177 个截断点里 19 个**静默**返回更短结果，其中 7 个是
**非指令边界**（cut=23/26/29/32/…：长度前缀串被 `data[i:i+n]` 切片静默截短，
如 cut=26 → [('ENTER_SHUYUE',None),('DAO','新')]，run_pbc 给 trust=0.0/条件空间='新'，
rc=0 且无错误信号）；另有 141 个截断点抛裸 IndexError/struct.error/UnicodeDecodeError。
修法：_need 长度判据单点（每处读取前调用）＋非 UTF-8 转结构化 ValueError；
save_pbc 改临时文件 + fsync + os.replace 原子写，杜绝中断产出截断件。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import tempfile

import compiler.pbc as P
from compiler.compiler import compile_source
from compiler.pbc import deserialize, load_pbc, run_pbc, save_pbc, serialize

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


SRC = ("问曰：如何验证信任？\n答曰：信任值大于0.7。\n术曰：\n"
       "1。道 新信任路径；\n2。德 0.3；\n"
       "3。若 信任值 大于 0.2，则 德 0.5；\n4。止。\n")
_code, _r = compile_source(SRC)
assert _r["ok"], _r
# op 名归一：compile 产出 Opcode 枚举，deserialize 还原为字符串名（pbc 契约）
_CODE = [(getattr(op, "name", op), arg) for op, arg in _code]
RAW = serialize(_code)
BOUNDS, _acc = {0}, 0
for _op, _arg in _code:
    _acc += len(serialize([(_op, _arg)]))
    BOUNDS.add(_acc)
_TMP = tempfile.mkdtemp(prefix="u08_402_")


def _write(name, data):
    p = os.path.join(_TMP, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


print("== A 组：#402 正题——全部非指令边界截断点 ==")
silent, naked, nonboundary_ok = [], [], 0
for cut in range(0, len(RAW) + 1):
    try:
        got = deserialize(RAW[:cut])
    except ValueError:
        if cut not in BOUNDS:
            nonboundary_ok += 1
        continue
    except BaseException as exc:                              # noqa: BLE001
        naked.append((cut, type(exc).__name__))
        continue
    if got != _CODE:
        silent.append(cut)
check("A01 无裸异常（IndexError/struct.error/UnicodeDecodeError）",
      not naked, naked[:4])
check("A02 非指令边界截断点全部结构化拒（半截串不再出现）",
      nonboundary_ok == len(set(range(0, len(RAW) + 1)) - BOUNDS),
      (nonboundary_ok, len(set(range(0, len(RAW) + 1)) - BOUNDS)))
check("A03 静默更短结果**只**出现在合法指令边界（R 组登记的不判别档）",
      set(silent) <= BOUNDS, [c for c in silent if c not in BOUNDS][:5])

for tag, cut in [("A04", 23), ("A05", 26), ("A06", 29), ("A07", 32),
                 ("A08", len(RAW) - 1)]:
    try:
        deserialize(RAW[:cut])
        ok, detail = False, "静默接受"
    except ValueError as exc:
        ok, detail = "pbc 截断" in str(exc), str(exc)[:80]
    except BaseException as exc:                              # noqa: BLE001
        ok, detail = False, type(exc).__name__
    check(f"{tag} 报告点 cut={cut} 结构化拒绝且报文点名截断", ok, detail)

print("== B 组：独立运行时入口 ==")
st_full = run_pbc(_write("full.pbc", RAW))
check("B01 完整件仍正常执行（trust=0.8 / halt='halt' / 条件空间正确）",
      st_full["trust"] == 0.8 and st_full["halt"] == "halt"
      and st_full["condition_space_name"] == "新信任路径", st_full["trust"])
for tag, cut in [("B02", 26), ("B03", 23)]:
    try:
        st = run_pbc(_write("cut.pbc", RAW[:cut]))
        check(f"{tag} cut={cut} run_pbc 不得给出结果", False, st["trust"])
    except ValueError as exc:
        check(f"{tag} cut={cut} run_pbc 抛结构化 ValueError（不再 rc=0 错值）",
              "pbc 截断" in str(exc), str(exc)[:80])
    except BaseException as exc:                              # noqa: BLE001
        check(f"{tag} cut={cut} run_pbc 抛结构化 ValueError（不再 rc=0 错值）",
              False, f"裸异常 {type(exc).__name__}")

for tag, blob in [("B04", b"\x02\x00\xff\xfe\x00"),
                  ("B05", b"\x04\x00\xe6\x96\xb0\xff\x00")]:
    try:
        deserialize(blob)
        check(f"{tag} 非 UTF-8 结构化拒", False, "静默接受")
    except ValueError as exc:
        check(f"{tag} 非 UTF-8 结构化拒", "pbc" in str(exc), str(exc)[:80])
    except BaseException as exc:                              # noqa: BLE001
        check(f"{tag} 非 UTF-8 结构化拒", False, type(exc).__name__)

print("== K 组：非恒真对照（合法件不误伤） ==")
check("K01 完整件 deserialize 往返逐位一致", deserialize(RAW) == _CODE, "")
check("K02 load_pbc 与 deserialize 一致", load_pbc(_write("f2.pbc", RAW)) == _CODE,
      "")
check("K03 空程序（0 字节）仍是合法空列表", deserialize(b"") == [], "")
_ALL_TAGS = [("DAO", None), ("PUSH", True), ("PUSH", False), ("PUSH", 7),
             ("DE", 0.5), ("DAO", "新路径"), ("ZHIZU", (0.7, 5)),
             ("CALL", (3, ["甲", "乙"]))]
check("K04 tag 0-6 全形态往返逐位一致",
      deserialize(serialize(_ALL_TAGS)) == _ALL_TAGS,
      deserialize(serialize(_ALL_TAGS)))
p_rt = os.path.join(_TMP, "rt.pbc")
save_pbc(_ALL_TAGS, p_rt)
check("K05 save_pbc 落盘内容与 serialize 逐字节相同（原子写不改格式）",
      open(p_rt, "rb").read() == serialize(_ALL_TAGS), "")
check("K06 save_pbc 不残留临时件",
      not [n for n in os.listdir(_TMP) if n.startswith(".pbc-")],
      os.listdir(_TMP))

print("== R 组：登记不判别档（指令边界截断——raw 格式物理不可判） ==")
check("R01 不判别档的静默点集合 == 合法边界集合（无额外静默面）",
      set(silent) <= BOUNDS and set(c for c in silent if c in BOUNDS)
      == set(c for c in BOUNDS if c < len(RAW)),
      sorted(set(c for c in BOUNDS if c < len(RAW)) ^ set(silent)))
print("  登记：边界截断点 %d 个（如 cut=15 → 单条 ENTER_SHUYUE 短程序，"
      "rc=0）——裸指令流无长度/校验信息，与「合法短程序」信息上不可区分。"
      % len([c for c in BOUNDS if 0 < c < len(RAW)]))

print("== E 组：源码面锚点 ==")
_psrc = open(os.path.join(_REPO, "compiler", "pbc.py"),
             encoding="utf-8").read()
check("E01 长度判据单点 _need 存在", "def _need(data, i, n, what):" in _psrc, "")
check("E02 每个读取点前调用 _need（≥9 处）",
      _psrc.count("_need(data, i,") >= 9, _psrc.count("_need(data, i,"))
check("E03 save_pbc 走 os.replace 原子写", "os.replace(tmp, path)" in _psrc, "")

if "def _need(data, i, n, what):" not in _psrc:
    print("锚点缺失：修复不在源码里（fail-closed）")
    sys.exit(2)


def _mutate_off():
    orig = P._need
    P._need = lambda data, i, n, what: None
    return lambda: setattr(P, "_need", orig)


if "--mutate" in sys.argv:
    print("\n!! 定点变异：_need 换成恒真（回缺陷形态）")
    restore = _mutate_off()
    try:
        silent2, naked2 = [], []
        for cut in range(0, len(RAW) + 1):
            try:
                got = deserialize(RAW[:cut])
            except BaseException:                             # noqa: BLE001
                naked2.append(cut)
                continue
            if got != _CODE:
                silent2.append(cut)
        try:
            run_pbc(_write("m.pbc", RAW[:26]))
            b02 = True
        except BaseException:                                 # noqa: BLE001
            b02 = False
    finally:
        restore()
    extra = [c for c in silent2 if c not in BOUNDS]
    reds = []
    if extra:
        reds.append("A03")
    if naked2:
        reds.append("A01")
    if b02:
        reds.append("B02")
    print("  变异后转红项：", reds,
          "（非边界静默 %d 个 / 裸异常 %d 个 / run_pbc 返回结果=%s）"
          % (len(extra), len(naked2), b02))
    ok = set(reds) == {"A01", "A03", "B02"}
    print("定点变异自证：" + ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)

print("\n=== #402 守卫: 失败项 %d ===" % len(FAILS))
sys.exit(0 if not FAILS else 1)
