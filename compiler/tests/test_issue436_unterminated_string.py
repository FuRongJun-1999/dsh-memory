# -*- coding: utf-8 -*-
# 功能名：未闭合字符串不得吞换行、不得压平后续行号（issue #436）
# 生效条件：python -X utf8 -m compiler.tests.test_issue436_unterminated_string [--mutate]；被测面＝compiler/lexer.py 的 Lexer._read_string
# 子功能：A 组＝单/三连未闭合字符串后，后续 token 行号与源码真实行号逐个一致（修前系统性偏小且线性累积）＋每条「字符串未闭合」错误行号指向该串真实起始行；B 组＝EOF 处未闭合必须报错（fail-closed，修前静默接受）；K 组＝非恒真对照（字符串全部闭合时 6 个 token 行号/列号与修前逐位一致、errors=[]；闭合串跨行后下一 token 行号正确；未闭合串本身内容仍产出 STRING token）；E 组＝源码面锚点（换行分支推进 self.line、结束引号仅在真遇 end_quote 时跳过）
# 执行：--mutate 时把 _read_string 换回缺陷形态（\n 分支 break + 无条件 pos+=1、不推进行号），A/B 指定项必须转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下红项集合须与预期逐项相符
# 不适用条件：不判 parser 侧对词法错误的后续处置（错误即早退，既有行为）；不判错误报文的列号语义（本修法把「字符串未闭合」报文的行列改为该串**起始**位置 L2:C1，修前为换行处 L2:C8——属诊断信息改善，不属本 issue 的行号判据）；STRING token 自身的列号保持修前口径（换行后一列 L2:C9，K06 钉死），不引入显示层漂移；不判白箱孪生 lexer（md_cg/whitebox_kb/wisdom/core/lexer.py 不在本单元授权文件内，已 residual 登记）
"""issue #436 守卫：词法器未闭合字符串吞掉换行且不推进行号。

修前实测：源码 L2/L4 各有一个未闭合串时，L3 的 德/0.5 与 L5 的 止/0.2 被报成
L2/L3（错误也把 L4 的串报成 L3）；三连未闭合 '"a\n"b\n"c\n德 0.5' 时第 4 行的
德/0.5 双双报成 L1。失真量随未闭合串个数线性累积，并传导给 parser 的 N4 跨行
判定（以行号为判据）。
修法：`\n` 分支先记错误并 emit 当前 STRING，再消费换行并 self.line += 1、
self.column = 1；「跳过结束引号」仅在真遇 end_quote 时执行；EOF 处未闭合同样报错。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from compiler.lexer import Lexer, TokenType, tokenize

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _toks(src):
    toks, errs = tokenize(src)
    return [(t.type.name, t.value, t.line, t.column) for t in toks], errs


def _line_of(toks, name, value):
    for t in toks:
        if t[0] == name and t[1] == value:
            return t[2]
    return None


print("== A 组：#436 正题——未闭合串之后的行号 ==")
SRC1 = '道 新路径\n"第一个未闭合\n德 0.5\n"第二个未闭合\n止 0.2'
_t1, _e1 = _toks(SRC1)
check("A01 单未闭合×2：德 的行号 = 3（真实 L3；修前 2）",
      _line_of(_t1, "DE", "德") == 3, _line_of(_t1, "DE", "德"))
check("A02 单未闭合×2：0.5 的行号 = 3（修前 2）",
      _line_of(_t1, "NUMBER", "0.5") == 3, _line_of(_t1, "NUMBER", "0.5"))
check("A03 单未闭合×2：止 的行号 = 5（真实 L5；修前 3）",
      _line_of(_t1, "ZHI", "止") == 5, _line_of(_t1, "ZHI", "止"))
check("A04 单未闭合×2：0.2 的行号 = 5（修前 3）",
      _line_of(_t1, "NUMBER", "0.2") == 5, _line_of(_t1, "NUMBER", "0.2"))
check("A05 两条错误分别指向 L2 与 L4（修前 L2/L3）",
      [e.split(" ")[0] for e in _e1] == ["L2:C1", "L4:C1"], _e1)

SRC2 = '"a\n"b\n"c\n德 0.5'
_t2, _e2 = _toks(SRC2)
check("A06 三连未闭合：德 的行号 = 4（真实 L4；修前 1）",
      _line_of(_t2, "DE", "德") == 4, _line_of(_t2, "DE", "德"))
check("A07 三连未闭合：0.5 的行号 = 4（修前 1）",
      _line_of(_t2, "NUMBER", "0.5") == 4, _line_of(_t2, "NUMBER", "0.5"))
check("A08 三条错误分别指向 L1/L2/L3",
      [e.split(" ")[0] for e in _e2] == ["L1:C1", "L2:C1", "L3:C1"], _e2)
check("A09 未闭合串本身仍产出 STRING token（内容不被丢弃）",
      [t[1] for t in _t2 if t[0] == "STRING"] == ["a", "b", "c"],
      [t for t in _t2 if t[0] == "STRING"])

print("== B 组：EOF 处未闭合必须报错（fail-closed） ==")
_t3, _e3 = _toks('德 0.5\n"abc')
check("B01 EOF 未闭合记「字符串未闭合」错误（修前静默接受）",
      len(_e3) == 1 and "字符串未闭合" in _e3[0], _e3)
check("B02 错误行号指向该串起始行 L2",
      _e3 and _e3[0].startswith("L2:"), _e3)
check("B03 该 STRING token 仍在（错误不吞 token）",
      any(t[0] == "STRING" and t[1] == "abc" for t in _t3),
      [t for t in _t3 if t[0] == "STRING"])

print("== K 组：非恒真对照（闭合形态逐位不变） ==")
SRC3 = '道 新路径\n"甲"\n德 0.5\n"乙"\n止 0.2'
_t4, _e4 = _toks(SRC3)
check("K01 全闭合：errors=[]", _e4 == [], _e4)
check("K02 全闭合：6 个 token 行号与源码真实行号一致",
      [(t[0], t[2]) for t in _t4] == [
          ("DAO", 1), ("IDENTIFIER", 1), ("STRING", 2), ("DE", 3),
          ("NUMBER", 3), ("STRING", 4), ("ZHI", 5), ("NUMBER", 5),
          ("EOF", 5)],
      [(t[0], t[2]) for t in _t4])
check("K03 全闭合：列号逐位不变（DAO 1 / ID 3 / DE 1 / 0.5 6 / 止 1）",
      [(t[0], t[3]) for t in _t4 if t[0] in ("DAO", "DE", "ZHI")]
      == [("DAO", 1), ("DE", 1), ("ZHI", 1)], "")
check("K04 闭合串后的 STRING 列号 = 4（跳过起始引号后逐字推进）",
      [t[3] for t in _t4 if t[0] == "STRING"] == [4, 4],
      [t[3] for t in _t4 if t[0] == "STRING"])
_t5, _e5 = _toks('"甲"\n"乙"\n德 0.5')
check("K05 多行全闭合：德 仍在 L3",
      _line_of(_t5, "DE", "德") == 3 and _e5 == [],
      (_line_of(_t5, "DE", "德"), _e5))
# 复核意见 2：未闭合串的 STRING token 列号保持修前口径（换行后一列），
# 不因本修法漂移——只有错误报文改指向串首。
check("K06 未闭合串的 STRING token 列号 = 9（与 HEAD 一致，不漂移）",
      [t[3] for t in _t1 if t[0] == "STRING"] == [9, 9],
      [t[3] for t in _t1 if t[0] == "STRING"])

print("== E 组：源码面锚点 ==")
_lsrc = open(os.path.join(_REPO, "compiler", "lexer.py"),
             encoding="utf-8").read()
check("E01 未闭合换行分支推进行号（self.line += 1）",
      "self.line += 1         # 行号推进（修复前被吞）" in _lsrc, "")
check("E02 结束引号仅在 closed 时跳过（不再无条件 pos+=1）",
      "if closed:" in _lsrc and "self.pos += 1              # 仅在真遇到结束引号时跳过它"
      in _lsrc, "")
check("E03 EOF 未闭合报错在场（else 分支追加错误）",
      "else:\n            # EOF 处未闭合：必须报错" in _lsrc, "")

if "self.line += 1         # 行号推进（修复前被吞）" not in _lsrc:
    print("锚点缺失：修复不在源码里（fail-closed）")
    sys.exit(2)


def _legacy_read_string(self):
    """缺陷形态（修前）：\\n 分支 break，随后无条件 pos+=1 把换行当结束引号吃掉。"""
    quote_char = self.source[self.pos]
    end_quote = '"' if quote_char == '"' else "\u201d"
    self.pos += 1
    self.column += 1
    result = []
    while self.pos < len(self.source) and self.source[self.pos] != end_quote:
        ch = self.source[self.pos]
        if ch == "\n":
            self.errors.append(f"L{self.line}:C{self.column} 字符串未闭合")
            break
        result.append(ch)
        self.pos += 1
        self.column += 1
    if self.pos < len(self.source):
        self.pos += 1
        self.column += 1
    self._emit(TokenType.STRING, "".join(result))


def _legacy_reds():
    reds = []
    t1, _e = _toks(SRC1)
    if _line_of(t1, "DE", "德") != 3 or _line_of(t1, "ZHI", "止") != 5:
        reds.append("A01")
    t2, _e = _toks(SRC2)
    if _line_of(t2, "DE", "德") != 4:
        reds.append("A06")
    _t3, e3 = _toks('德 0.5\n"abc')
    if not e3:
        reds.append("B01")
    return reds


if "--mutate" in sys.argv:
    print("\n!! 定点变异：_read_string 回退为缺陷形态（吞换行、不推进行号）")
    orig = Lexer._read_string
    Lexer._read_string = _legacy_read_string
    try:
        reds = _legacy_reds()
    finally:
        Lexer._read_string = orig
    print("  变异后转红项：", reds)
    ok = set(reds) == {"A01", "A06", "B01"}
    print("定点变异自证：" + ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)

print("\n=== #436 守卫: 失败项 %d ===" % len(FAILS))
sys.exit(0 if not FAILS else 1)
