"""
lexer.py · 词法分析器 v2.0（生产版）
中文分词 + Token 识别
支持道德经助记符、九章算术结构、中文标点

v2.0 算法（两阶段）：
阶段一（粗分）：逐字符扫描，按"类型"分组
  - 中文串（连续 CJK）
  - 字母串（连续 ASCII 字母/数字/下划线）
  - 数字串（连续数字，含小数点）
  - 标点（单个）
  - 空白（跳过）
  - 字符串（引号包裹）

阶段二（精分）：对每个中文串/字母串做关键字切分
  - 使用正向最大匹配
  - 关键字 → Token
  - 非关键字 → IDENTIFIER
"""

from enum import Enum, auto
from dataclasses import dataclass
from typing import List, Tuple


# =============================================================================
# Token 类型定义
# =============================================================================

class TokenType(Enum):
    """Token 类型枚举"""
    
    # === 道德经助记符（指令集） ===
    DAO = auto()          # 道
    DE = auto()           # 德
    ZIRAN = auto()        # 自然
    WUWEI = auto()        # 无为
    GU = auto()           # 谷
    PIN = auto()           # 牝
    ROU = auto()          # 柔
    PU = auto()           # 朴
    ZHI = auto()          # 止
    ZHIZU = auto()        # 知足
    
    # === 九章算术结构关键字 ===
    WENYUE = auto()       # 问曰
    DAYUE = auto()        # 答曰
    SHUYUE = auto()       # 术曰
    
    # === 条件/逻辑关键字 ===
    RUO = auto()          # 若
    ZE = auto()           # 则
    FOUZE = auto()        # 否则
    YU = auto()           # 于
    WEI = auto()          # 为
    BUWEI = auto()        # 不为
    QIE = auto()          # 且
    HUO = auto()          # 或
    FEI = auto()          # 非
    DENGYU = auto()       # 等于
    DAYU = auto()         # 大于
    XIAOYU = auto()       # 小于
    
    # === 循环关键字（当…执行：白箱循环语法）===
    DANG = auto()         # 当
    ZHIXING = auto()      # 执行
    
    # === 函数关键字（定义…返回：函数抽象）===
    DINGYI = auto()       # 定义
    FANHUI = auto()       # 返回
    
    # === 标识符与常量 ===
    IDENTIFIER = auto()   # 标识符
    NUMBER = auto()        # 数值常量
    STRING = auto()        # 字符串常量
    
    # === 标点符号 ===
    COMMA = auto()        # ，
    PERIOD = auto()       # 。
    SEMICOLON = auto()    # ；
    COLON = auto()        # ：
    LPAREN = auto()       # （
    RPAREN = auto()       # ）
    ARROW = auto()        # →
    QUESTION = auto()     # ？
    EXCLAM = auto()       # ！
    EQUALS = auto()      # = 或 ＝（赋值符号）
    
    # === 算术运算符（循环体/表达式需要）===
    OP_ADD = auto()       # +
    OP_SUB = auto()       # -
    OP_MUL = auto()       # *
    OP_DIV = auto()       # /

    # === 特殊 ===
    COMMENT = auto()      # 注释
    NEWLINE = auto()      # 换行
    EOF = auto()          # 文件结束
    UNKNOWN = auto()      # 未知


# =============================================================================
# Token 数据结构
# =============================================================================

@dataclass
class Token:
    """Token 数据类"""
    type: TokenType
    value: str
    line: int = 1
    column: int = 1
    
# 生效条件：在 Token 实例上调用时读取 self.type.name、self.value、self.line、self.column，str(self.value) 长度超过 30 时取前 30 字符并追加 "..."，否则原样使用。
    def __repr__(self) -> str:
        v = str(self.value)[:30]
        if len(str(self.value)) > 30:
            v += "..."
        return f"Token({self.type.name}, '{v}', L{self.line}:C{self.column})"


# =============================================================================
# 关键字映射表
# =============================================================================

# 所有关键字集合
KEYWORDS = {
    # 道德经
    "道", "德", "自然", "无为", "谷", "牝", "柔", "朴", "止", "知足",
    # 九章算术
    "问曰", "答曰", "术曰",
    # 条件/逻辑
    "若", "则", "否则", "于", "为", "不为", "且", "或", "非",
    "等于", "大于", "小于",
    # 循环（当…执行：白箱循环语法）
    "当", "执行",
    # 函数（定义…返回：函数抽象）
    "定义", "返回",
    # 中文算术词（加/减/乘/除 → 运算符）
    "加", "减", "乘", "除",
}

# 关键字 → TokenType
KEYWORD_MAP = {
    "道": TokenType.DAO,
    "德": TokenType.DE,
    "自然": TokenType.ZIRAN,
    "无为": TokenType.WUWEI,
    "谷": TokenType.GU,
    "牝": TokenType.PIN,
    "柔": TokenType.ROU,
    "朴": TokenType.PU,
    "止": TokenType.ZHI,
    "知足": TokenType.ZHIZU,
    "问曰": TokenType.WENYUE,
    "答曰": TokenType.DAYUE,
    "术曰": TokenType.SHUYUE,
    "若": TokenType.RUO,
    "则": TokenType.ZE,
    "否则": TokenType.FOUZE,
    "于": TokenType.YU,
    "为": TokenType.WEI,
    "不为": TokenType.BUWEI,
    "且": TokenType.QIE,
    "或": TokenType.HUO,
    "非": TokenType.FEI,
    "等于": TokenType.DENGYU,
    "大于": TokenType.DAYU,
    "小于": TokenType.XIAOYU,
    "当": TokenType.DANG,
    "执行": TokenType.ZHIXING,
    "定义": TokenType.DINGYI,
    "返回": TokenType.FANHUI,
    "加": TokenType.OP_ADD,
    "减": TokenType.OP_SUB,
    "乘": TokenType.OP_MUL,
    "除": TokenType.OP_DIV,
}

# 按长度降序排列
SORTED_KW = sorted(KEYWORDS, key=len, reverse=True)

# 中文标点映射
PUNCTUATION_MAP = {
    "，": TokenType.COMMA,    ",": TokenType.COMMA,
    "。": TokenType.PERIOD,    ".": TokenType.PERIOD,
    "；": TokenType.SEMICOLON, ";": TokenType.SEMICOLON,
    "：": TokenType.COLON,    ":": TokenType.COLON,
    "（": TokenType.LPAREN,    "(": TokenType.LPAREN,
    "）": TokenType.RPAREN,    ")": TokenType.RPAREN,
    "→": TokenType.ARROW,
    "？": TokenType.QUESTION, "?": TokenType.QUESTION,
    "！": TokenType.EXCLAM, "!": TokenType.EXCLAM,
    "=": TokenType.EQUALS, "＝": TokenType.EQUALS,
    "+": TokenType.OP_ADD, "＋": TokenType.OP_ADD,
    "-": TokenType.OP_SUB, "－": TokenType.OP_SUB,
    "*": TokenType.OP_MUL, "×": TokenType.OP_MUL,
    "/": TokenType.OP_DIV, "÷": TokenType.OP_DIV,
}


# =============================================================================
# 工具函数
# =============================================================================

# 生效条件：传入单个字符 ch 后取 ord(ch) 得码点，码点落在 0x4E00–0x9FFF（19968–40959）时返回 True，否则返回 False。
def _is_cjk(ch: str) -> bool:
    """是否为 CJK 统一汉字"""
    code = ord(ch)
    return 0x4E00 <= code <= 0x9FFF

# 生效条件：传入字符 ch，当 _is_cjk(ch) 为真、或 ch.isalpha() 为真、或 ch == "_" 时返回 True，三者皆不满足时返回 False。
def _is_cjk_or_alpha(ch: str) -> bool:
    """是否为中文、字母、下划线"""
    return _is_cjk(ch) or ch.isalpha() or ch == "_"


# =============================================================================
# 词法分析器
# =============================================================================

# 生效条件：以 source 为必填实参构造，实例化即置 self.source=source，并将 pos 置 0、line 置 1、column 置 1、tokens 与 errors 置空列表；
class Lexer:
    """
    词法分析器 v2.0
    
    两阶段分词：
    阶段一：粗分（按字符类型分组）
    阶段二：精分（对中文/字母串做关键字切分）
    """
    
# 生效条件：source 原样存入 self.source（不做类型与空值校验），同时把 pos 置 0、line 与 column 置 1、tokens 与 errors 置为空列表。
    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: List[Token] = []
        self.errors: List[str] = []
    
# 生效条件：以 self.source 与初始 self.pos=0、line=1、column=1 逐字符扫描——换行分支推进 self.line、空白分支推进 self.column、`//` 交 _skip_comment、`"` 或 `“` 交 _read_string、isdigit/`.`/`-` 且 _peek_isdigit 交 _read_number、PUNCTUATION_MAP 中字符与 `=`、`＝` 直接 _emit、CJK/字母/下划线交 _read_and_segment，其余字符追加到 self.errors，循环结束后 _emit(EOF) 并返回 (self.tokens, self.errors)。
    def tokenize(self) -> Tuple[List[Token], List[str]]:
        """执行词法分析"""
        self.tokens = []
        self.errors = []
        self.pos = 0
        self.line = 1
        self.column = 1
        
        while self.pos < len(self.source):
            ch = self.source[self.pos]
            
            # 换行
            if ch == "\n":
                self.line += 1
                self.column = 1
                self.pos += 1
                continue
            
            # 空白
            if ch in (" ", "\t", "\r"):
                self.column += 1
                self.pos += 1
                continue
            
            # 注释 //
            if ch == "/" and self.pos + 1 < len(self.source) and self.source[self.pos + 1] == "/":
                self._skip_comment()
                continue
            
            # 字符串
            if ch == '"' or ch == "\u201c":
                self._read_string()
                continue
            
            # 数字（包括 . 开头的小数）
            if ch.isdigit() or ch == "." or (ch == "-" and self._peek_isdigit()):
                self._read_number()
                continue
            
            # 中文标点
            if ch in PUNCTUATION_MAP:
                self._emit(PUNCTUATION_MAP[ch], ch)
                self.pos += 1
                self.column += 1
                continue

            # 赋值符号 = （ASCII）或 ＝（全角）
            if ch == "=" or ch == "\uFF1D":
                self._emit(TokenType.EQUALS, ch)
                self.pos += 1
                self.column += 1
                continue
            
            # 中文/字母/下划线 → 粗分 + 精分
            if _is_cjk_or_alpha(ch):
                self._read_and_segment()
                continue
            
            # 未知字符
            self.errors.append(f"L{self.line}:C{self.column} 未知字符: '{ch}' (U+{ord(ch):04X})")
            self.pos += 1
            self.column += 1
        
        self._emit(TokenType.EOF, "")
        return self.tokens, self.errors
    
    # ---- 阶段一：粗分 ----
    
# 生效条件：从 self.pos（__init__ 的 source 上的游标）起贪婪吞并 _is_cjk_or_alpha 或 isdigit 的字符（一个都不满足则 text 为空串且游标不动），再以 (text, 起始列) 调用 self._segment。
    def _read_and_segment(self):
        """
        读取连续的中文/字母/数字/下划线，然后做关键字精分
        
        这是核心方法：
        1. 贪婪读取所有"词字符"（中文/字母/数字/下划线）
        2. 对结果做正向最大匹配切分
        """
        start_col = self.column
        start_pos = self.pos
        
        # 贪婪读取
        while self.pos < len(self.source):
            ch = self.source[self.pos]
            if _is_cjk_or_alpha(ch) or ch.isdigit():
                self.pos += 1
            else:
                break
        
        text = self.source[start_pos:self.pos]
        self.column += (self.pos - start_pos)
        
        # 阶段二：精分
        self._segment(text, start_col)
    
    # ---- 阶段二：精分 ----
    
# 生效条件：text 为空串时 while 不执行、不发任何 token；否则从 i 起在 SORTED_KW 中取最长匹配关键字发出 KEYWORD_MAP[kw]，无匹配时 text[i] 为 CJK 则取连续 CJK 整段、否则取到下一个关键字起点前的字符段作为 IDENTIFIER 发出（切出的段为空串则不发出）。
    def _segment(self, text: str, start_col: int):
        """
        正向最大匹配（Forward Maximum Matching）
        
        对 text 中的每个位置，找最长的匹配关键字。
        如果找不到关键字，发出单个字符作为 IDENTIFIER。
        
        关键改进：使用位置指针 i 遍历 text，
        每次从 i 开始找最长关键字。
        找到后 i 跳过该关键字长度。
        找不到时 i 前进 1（发出单个字符）。
        
        标识符规则：连续 CJK 串优先整体为标识符（如「阶乘」含关键词「乘」，
        但整体不是关键词 → 保持为标识符，避免误切分）。
        """
        i = 0
        col = start_col
        
        while i < len(text):
            # 尝试从位置 i 找最长关键字
            matched_kw = None
            matched_len = 0
            
            for kw in SORTED_KW:
                if text.startswith(kw, i):
                    if len(kw) > matched_len:
                        matched_kw = kw
                        matched_len = len(kw)
            
            if matched_kw is not None:
                # 发出关键字 token
                self._emit(KEYWORD_MAP[matched_kw], matched_kw, col)
                i += matched_len
                col += matched_len
            else:
                # 不是关键字 → 收集连续的非关键字字符作为标识符
                # 中文规则：连续 CJK 串优先整体为标识符（如「阶乘」含关键词「乘」，
                # 但整串「阶乘」非关键词 → 保持整体，避免误切分）
                ident_start = i
                ident_col = col
                
                if _is_cjk(text[i]):
                    while i < len(text) and _is_cjk(text[i]):
                        i += 1
                        col += 1
                else:
                    while i < len(text):
                        ch = text[i]
                        has_kw_ahead = any(text.startswith(kw, i) for kw in SORTED_KW)
                        if has_kw_ahead:
                            break
                        i += 1
                        col += 1
                
                ident = text[ident_start:i]
                if ident:
                    self._emit(TokenType.IDENTIFIER, ident, ident_col)
    
    # ---- 数字读取 ----
    
# 生效条件：self.pos + 1 小于 len(self.source) 且 self.source[self.pos + 1].isdigit() 为真时返回 True，否则（越界或非数字）返回 False。
    def _peek_isdigit(self) -> bool:
        return self.pos + 1 < len(self.source) and self.source[self.pos + 1].isdigit()
    
# 生效条件：从 self.source[self.pos] 起按可选 '-'、整数位、可选 '.' 加小数位拼成字符串，float() 成功即发出 NUMBER，抛 ValueError 时先追加一条「非法数值」到 self.errors 但仍发出同一个 NUMBER token。
    def _read_number(self):
        """读取数值（支持整数、小数、负数）"""
        start_col = self.column
        result = []
        
        # 负号
        if self.source[self.pos] == "-":
            result.append("-")
            self.pos += 1
            self.column += 1
        
        # 整数部分
        while self.pos < len(self.source) and self.source[self.pos].isdigit():
            result.append(self.source[self.pos])
            self.pos += 1
            self.column += 1
        
        # 小数部分
        if self.pos < len(self.source) and self.source[self.pos] == ".":
            result.append(".")
            self.pos += 1
            self.column += 1
            while self.pos < len(self.source) and self.source[self.pos].isdigit():
                result.append(self.source[self.pos])
                self.pos += 1
                self.column += 1
        
        num_str = "".join(result)
        try:
            float(num_str)
            self._emit(TokenType.NUMBER, num_str)
        except ValueError:
            self.errors.append(f"L{self.line}:C{start_col} 非法数值: '{num_str}'")
            self._emit(TokenType.NUMBER, num_str)
    
    # ---- 字符串读取 ----
    
# 生效条件：self.source[self.pos] 为 `"` 时 end_quote 取 `"`、为 `“` 时取 `”`，随后逐字符累积进 result 直到遇 end_quote；遇 `\n` 时向 self.errors 记 "字符串未闭合" 并 break（此时 self.pos 仍在串长内，仍会 pos+=1、column+=1 跳过该换行），最后 _emit(TokenType.STRING, 累积内容)。
    def _read_string(self):
        """读取字符串"""
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
            self.pos += 1  # 跳过结束引号
            self.column += 1
        
        self._emit(TokenType.STRING, "".join(result))
    
    # ---- 注释跳过 ----
    
# 生效条件：从 self.pos 起自增扫描，直到 self.pos >= len(self.source) 或 self.source[self.pos] == "\n" 时停止；只推进 self.pos，不改 self.line、self.column，也不追加 token。
    def _skip_comment(self):
        while self.pos < len(self.source) and self.source[self.pos] != "\n":
            self.pos += 1
    
    # ---- Token 输出 ----
    
# 生效条件：col 不为 None（含 0）时用 col、col 为 None 时才回落 self.column，向 self.tokens 追加 Token(token_type, value, self.line, 该列)。
    def _emit(self, token_type: TokenType, value: str, col: int = None):
        """输出一个 Token"""
        c = col if col is not None else self.column
        self.tokens.append(Token(token_type, value, self.line, c))


# =============================================================================
# 便捷函数
# =============================================================================

# 生效条件：source 交给新建的 Lexer(source)，返回其 tokenize() 给出的 (tokens, errors) 二元组。
def tokenize(source: str) -> Tuple[List[Token], List[str]]:
    """便捷函数"""
    lexer = Lexer(source)
    return lexer.tokenize()


# =============================================================================
# 测试
# =============================================================================

if __name__ == "__main__":
    test_code = """若条件空间为伴侣，则止情感权重于0.15。
道 新信任路径
问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：1。德 累积信任值；2。自然 恢复默认。"""
    
    print("=" * 60)
    print("词法分析器 v2.0 测试")
    print("=" * 60)
    print(f"源代码：\n{test_code}\n")
    
    tokens, errors = tokenize(test_code)
    
    print("Token 序列：")
    for t in tokens:
        if t.type != TokenType.EOF:
            print(f"  {t}")
    
    if errors:
        print(f"\n错误：")
        for e in errors:
            print(f"  ❌ {e}")
    
    valid = len([t for t in tokens if t.type != TokenType.EOF])
    print(f"\n总计：{valid} 个 Token，{len(errors)} 个错误")