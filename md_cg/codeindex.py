# -*- coding: utf-8 -*-
"""条件代码图：按注释/接口索引代码，不存完整代码。

设计（2026-09-09；2026-09-10 修订）：
认知图通过「大域」（目录）索引；代码节点存的是**注释与接口**——模块 docstring、
签名、docstring、前置注释；正文一律不复制，用 frontmatter.code_ref 指回源文件。
读取走注释索引，零 LLM，纯 AST（弱提取器除外，见下）。

节点正文必须是 **CCG 6 行**（见 `render`）：非 CCG 正文会被 `judge_qualification`
的第一步（ccg_completeness）直接判 **BLINDSPOT**，节点存进去了也检索不到可用结论。

提取器按后缀注册（`EXTRACTORS`）：
    .py              → AST 提取，precise=True，区间精确到 end_lineno，基底 compiler
    .ts/.tsx/.js/... → 正则弱提取，precise=False，区间为**上界**，基底 other（诚实降级）

区间哈希：每条目带 `hash`（被引用行的 sha1 前 12 位，见 `_region_hash`），
用于后续判断「索引出来的位置是不是已经漂了」——它不是内容寻址，只做变更探测。
"""
from __future__ import annotations

import ast
import hashlib
import os
import re

from . import nodefile

SKIP_DIRS = ("__pycache__", ".git", ".venv", "venv", "node_modules", ".mypy_cache")
MAX_DOC = 400

LANG_COMPILER = "compiler"
LANG_WEAK = "other"

# --------------------------------------------------------------------------
# 渲染契约代际（版本戳）
# --------------------------------------------------------------------------
# 生效条件：`render` 的**产物形态**发生不兼容变化时 +1（形态不变的重构不 +1）；
# 由 refindex 写入 frontmatter.code_ref.render_version（节点侧），由 selfreport
# 随常驻进程自报（进程侧），两侧同取本常量——**同源，无第二处硬编码**。
#
# 用途（第③道防线，防「旧契约静默覆盖重建成果」）：
#   ① 节点侧：`scripts/mdcg_verify_render_meta.py` 据 code_ref.render_version 机械
#      判定「节点由哪一代 render 产出」，不再只靠形态启发式（正文含元条件行）；
#   ② 进程侧：`scripts/mdcg_stale_servers.py` 据自报值判定活进程代际，堵住
#      「进程启动时间晚于源码 mtime 故 stale=False、却持旧 render」的盲区
#      （AGENTS.md §5 运维注记的活体实证：旧契约把全量重建成果刷回 old_synth）。
#
# 代际史：
#   1 = 旧契约（npm 0.4.8 及以前）：合成区产出 `# 生效条件：载体/位置：…`，
#       索引元条件冒用 CCG 字段名（合成即冒充）。
#   2 = 三分区契约（2026-09-19）：源码 CCG 区置首 → 合成 CCG 区（不产出生效
#       条件行）→ 索引元信息区（`# 索引元条件：…` 非 CCG 字段名 + 位置行）。
RENDER_VERSION = 2


# --------------------------------------------------------------------------
# Python：AST 提取（精确）
# --------------------------------------------------------------------------
# 生效条件：node 传入后，取 ast.get_docstring(node, clean=True) 的返回值，若该返回值为假值则回落空串，返回 strip 后截断到模块级 MAX_DOC 的文本；
def _doc_of(node):
    return (ast.get_docstring(node, clean=True) or "").strip()[:MAX_DOC]


# 生效条件：lines 为源码行列表、lineno 为 1-based 定义行时，从 lines[lineno-2] 向上收集连续以 "#" 起始的行，遇空行且已收集到注释即停止，遇空行且未收集到注释则跳过继续，遇非注释非空行停止，返回按物理顺序排列的注释列表；lineno<=1 或初始无匹配时返回空列表；
def _leading_comments(lines, lineno):
    """定义行前的连续注释（# ...）。"""
    out, i = [], lineno - 2
    while i >= 0:
        s = lines[i].strip()
        if s.startswith("#"):
            out.append(s)
            i -= 1
        elif not s and out:
            break
        elif not s:
            i -= 1
        else:
            break
    return list(reversed(out))


# 生效条件：node 具有真值 body 属性时返回 body[0].lineno；否则（body 为 None/假值/缺属性）返回 node.lineno；
def _body_first_line(node):
    """符号体首个语句的行号（1-based）；无体 → 定义行本身（窗口为空）。"""
    body = getattr(node, "body", None) or []
    return body[0].lineno if body else node.lineno


# 生效条件：lines 为 source.split("\n") 得到的行列表、lineno 为 1-based 定义行、body_lineno 为 1-based 体首语句行时，在 end=max(lineno, body_lineno-1) 下扫描 lines[lineno:end]，收集 strip 后以 "#" 起始的行并返回；body_lineno-1 <= lineno 时返回空列表；
def _body_comments(lines, lineno, body_lineno):
    """符号**体内首个语句之前**的连续 `#` 注释（定义行紧下方，声明头区）。

    这是与 `_leading_comments`（定义行**之上**）并列的**第二个窗口**：

    · 既有白箱单元库 104+ 处把 CCG 注释块写在**这里**
      （例：`md_cg/whitebox_kb/wisdom/python_code_units.py` 的模板
      `def tokenize(src):` 下一行即 `    # 生效条件：参数 src 合法`）；
    · 本函数是 body 窗口的**唯一真源**——`whitebox_kb/wisdom/verifier._ccg_block`
      委托此处（历史文档里那句「与 `codeindex._body_comments` 同款语义」曾是
      **悬空引用**：该名当时并不存在）。

    参数：`lines`=源码行列表（`source.split("\\n")`）；`lineno`=定义行（1-based）；
    `body_lineno`=体首个语句行（1-based）。窗口 = `lines[lineno : body_lineno-1]`
    （0-based 切片：定义行之后 → 体首语句之前），只收 `#` 起始行。
    语法上该窗口**结构性地只可能含注释/空行/docstring**——体首语句之前的区域。
    """
    start = lineno                      # 0-based 索引 → 定义行的下一行
    end = max(start, body_lineno - 1)
    out = []
    for ln in lines[start:end]:
        s = ln.strip()
        if s.startswith("#"):
            out.append(s)
    return out


# 生效条件：lines 为源码行列表且 node 含 lineno 时，返回 _leading_comments(lines, node.lineno) 与 _body_comments(lines, node.lineno, _body_first_line(node)) 的拼接结果（leading 在前、body 在后）；
def _symbol_comments(lines, node):
    """符号的「源码 CCG 区」= leading 窗口 + body 窗口，**按物理行序**合并。

    不发明额外优先级：两个窗口在源文件里的物理先后天然确定（leading 在定义行
    之上、body 在其下），而检索侧 `mdcos._ccg_field` 取**首个**匹配——于是
    「靠前者胜出」与「物理序」是同一件事，确定性可复算。
    单窗口文件的行为与改造前逐字一致（只多收 body 窗口）。
    """
    return (_leading_comments(lines, node.lineno)
            + _body_comments(lines, node.lineno, _body_first_line(node)))


# 生效条件：source 与 node 传入后，取 ast.get_source_segment(source, node) 的返回值，若抛 ValueError/TypeError 或返回假值则 seg 为空串，返回 seg.split("\n",1)[0].strip()[:200]；
def _sig(source, node):
    try:
        seg = ast.get_source_segment(source, node) or ""
    except (ValueError, TypeError):
        seg = ""
    return seg.split("\n", 1)[0].strip()[:200]


# 生效条件：tree 为 AST 根节点时，调用嵌套 rec(tree, "") 按 ast.iter_child_nodes 源码顺序递归产出 (定义节点, 所属类名)；ClassDef 自身以当前 parent 产出并对其内部递归改用类名，FunctionDef/AsyncFunctionDef 以当前 parent 产出并保持 parent，其他节点递归保持 parent；
def _walk_defs(tree):
    """按**源码顺序**产出 (定义节点, 所属类名)。

    不用 `ast.walk`：它给出的是广度优先、与源码顺序不一致，且丢掉父级归属。
    父级归属是「子功能」与「不适用条件」两项的判定依据（同名方法必须能区分
    是哪个类的），不能省。
    """
# 生效条件：node 为 AST 节点、parent 为当前所属类名字符串时，按 ast.iter_child_nodes(node) 顺序递归产出 (定义节点, 所属类名)：ClassDef 以 parent 产出并递归改用 child.name，FunctionDef/AsyncFunctionDef 以 parent 产出并递归保持 parent，其他节点递归保持 parent；
    def rec(node, parent):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield child, parent
                yield from rec(child, child.name)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield child, parent
                yield from rec(child, parent)
            else:
                yield from rec(child, parent)
    return rec(tree, "")


# 生效条件：source 可被 ast.parse 成功解析时，返回首项为 module 条目（path、name=os.path.basename(path) or "<module>"、lineno=1、end=len(source.split("\n"))、doc=_doc_of(tree)）后接 _walk_defs(tree) 各定义条目的列表；source 触发 SyntaxError 时抛 ValueError(f"{path}:{exc.lineno}: {exc.msg}")；
def _extract_python(source, path):
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"{path}:{exc.lineno}: {exc.msg}") from exc
    lines = source.split("\n")
    items = [{"path": path, "name": os.path.basename(path) or "<module>",
              "kind": "module", "parent": "", "lineno": 1, "end": len(lines),
              "sig": "", "doc": _doc_of(tree), "comments": []}]
    for node, parent in _walk_defs(tree):
        kind = ("class" if isinstance(node, ast.ClassDef)
                else "async_def" if isinstance(node, ast.AsyncFunctionDef)
                else "def")
        items.append({
            "path": path, "name": node.name, "kind": kind, "parent": parent,
            "lineno": node.lineno, "end": getattr(node, "end_lineno", node.lineno),
            "sig": _sig(source, node), "doc": _doc_of(node),
            "comments": _symbol_comments(lines, node)})
    return items


# --------------------------------------------------------------------------
# TS/JS：正则弱提取（不精确，区间为上界）
# --------------------------------------------------------------------------
_JS_DEF = re.compile(
    r"^(?P<indent>[ \t]*)(?:export\s+)?(?:default\s+)?(?:declare\s+)?"
    r"(?:abstract\s+)?(?:async\s+)?"
    r"(?P<kind>class|interface|enum|type|function|const)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)", re.M)
# 这些关键字只在模块作用域（缩进为空）才算对外接口，否则会把函数内的局部
# const 全捞进来，把索引淹掉。
_JS_MODULE_SCOPE_ONLY = ("const", "type", "enum")


# 生效条件：lines 为源码行列表、lineno 为 1-based 定义行时，从 lines[lineno-2] 向上收集连续以 "//" 开头的行注释，或遇到 strip 后以 "*/" 结尾的行时向上收集到首个 strip 后以 "/*" 开头的行（含该行）作为块注释；lookback 默认 25 限制收集行数，lookback=0 时循环不进入并返回空列表；遇空行且已有收集即停止，空行且未收集则跳过，其他行停止；
def _leading_js_comments(lines, lineno, lookback=25):
    """定义行前的连续行注释块，或紧邻的 /** ... */ 块。"""
    out, i = [], lineno - 2
    while i >= 0 and len(out) < lookback:
        s = lines[i].strip()
        if not s and out:
            break
        if s.endswith("*/"):
            block = []
            j = i
            while j >= 0 and len(out) + len(block) < lookback:
                block.append(lines[j].strip())
                if lines[j].strip().startswith("/*"):
                    break
                j -= 1
            out.extend(block)
            break
        if s.startswith("//"):
            out.append(s)
            i -= 1
            continue
        if not s:
            i -= 1
            continue
        break
    return list(reversed(out))


# 生效条件：对 source 用 _JS_DEF.finditer 命中项生成条目（首项模块条目 name 为 os.path.basename(path) or "<module>"），跳过 kind 属于 _JS_MODULE_SCOPE_ONLY 且 indent 组非空的命中；其余命中按出现顺序取 lineno、kind、name、sig，end 为下一命中行号减一或 len(source.split("\n")) 且不小于 lineno，comments 由 _leading_js_comments(lines, lineno) 生成。
def _extract_weak(source, path):
    """正则弱提取：返回条目，`end` 为**上界**（到下一个定义之前），不保证精确。"""
    lines = source.split("\n")
    items = [{"path": path, "name": os.path.basename(path) or "<module>",
              "kind": "module", "parent": "", "lineno": 1, "end": len(lines),
              "sig": "", "doc": "", "comments": []}]
    hits = []
    for m in _JS_DEF.finditer(source):
        kind, name = m.group("kind"), m.group("name")
        if kind in _JS_MODULE_SCOPE_ONLY and m.group("indent"):
            continue
        lineno = source.count("\n", 0, m.start()) + 1
        hits.append((lineno, kind, name, m.group(0).strip()))
    for idx, (lineno, kind, name, sig) in enumerate(hits):
        end = (hits[idx + 1][0] - 1) if idx + 1 < len(hits) else len(lines)
        items.append({
            "path": path, "name": name, "kind": kind, "parent": "",
            "lineno": lineno, "end": max(lineno, end), "sig": sig[:200],
            "doc": "", "comments": _leading_js_comments(lines, lineno)})
    return items


# --------------------------------------------------------------------------
# 提取器注册表
# --------------------------------------------------------------------------
EXTRACTORS = {
    ".py": ("py", _extract_python, True, LANG_COMPILER),
    ".ts": ("ts", _extract_weak, False, LANG_WEAK),
    ".tsx": ("tsx", _extract_weak, False, LANG_WEAK),
    ".js": ("js", _extract_weak, False, LANG_WEAK),
    ".mjs": ("js", _extract_weak, False, LANG_WEAK),
    ".cjs": ("js", _extract_weak, False, LANG_WEAK),
}
SUFFIX = tuple(sorted(EXTRACTORS))


# 生效条件：lines 为行列表、lineno 与 end 为 1-based 行号时，对 "\n".join(lines[max(0, lineno-1):max(0, end)]) 的 UTF-8 字节求 sha1，返回其十六进制前 12 位；
def region_hash(lines, lineno, end):
    """被引用行的 sha1 前 12 位（变更探测用，非内容寻址）。

    必须是**唯一**定义：索引侧与回读侧（`op=ref`）共用同一个函数。
    两侧各写一份哈希算法，漂移检测就会悄悄失效（永远 hash_match=True）。
    """
    seg = "\n".join(lines[max(0, lineno - 1):max(0, end)])
    return hashlib.sha1(seg.encode("utf-8")).hexdigest()[:12]


# 生效条件：source 与 path 传入后，ext=suffix or os.path.splitext(path)[1].lower()；当 ext 存在于模块级 EXTRACTORS 时，用对应 fn(source, path) 抽取并给每个条目补 lang/precise/basis/hash（hash 由 region_hash(lines, it["lineno"], it["end"]) 算）后返回；ext 不在 EXTRACTORS 时抛 ValueError(f"无提取器（suffix={ext or '<none>'}）")；
def extract(source, path="", suffix=None):
    """抽取一个文件的条目；按后缀分派提取器。语法错误抛 ValueError。

    产出条目带 `lang` / `precise` / `hash`，供 `render` 与 frontmatter.code_ref 使用。
    """
    ext = suffix or os.path.splitext(path)[1].lower()
    if ext not in EXTRACTORS:
        # 不静默降级成 Python 解析：那会把「没有提取器」伪装成「语法错误」，
        # 让调用方误以为是源码的问题。直接报缺提取器，由 index_dir 收进 errors。
        raise ValueError(f"无提取器（suffix={ext or '<none>'}）")
    lang, fn, precise, basis = EXTRACTORS[ext]
    lines = source.split("\n")
    items = fn(source, path)
    for it in items:
        it["lang"] = lang
        it["precise"] = precise
        it["basis"] = basis
        it["hash"] = region_hash(lines, it["lineno"], it["end"])
    return items


# 生效条件：item 为条目字典时，path=item.get("path") or ""、top=path.split("/")[0] or "."，按 item.get("precise", True)（缺键默认 True，键存在假值走弱提取）选择 LANG_COMPILER 或 LANG_WEAK 方法文本，返回 observation_position 用 top、time_window 用 nodefile.FULL_TIME_WINDOW_MIN 与 nodefile.FULL_TIME_WINDOW_MAX、observation_tool 用方法文本、existence_constraint 含 path 的四槽字典；
def condition_space(item):
    """条目 → 条件空间四槽（纯函数，**唯一来源**）。

    为什么必须与 `render` 同源：正文的 `# 索引元条件：` 行与 frontmatter 的
    `condition_space` 一旦各写一套，就会出现「正文有声明、条件空间是空的」
    ——`nodefile.condition_space_text(require_full=True)` 只看 frontmatter，
    于是节点**存得进、判得了，条件空间却没声明**。改造前正是这样：正文写
    「大域=X；检索…时」（第三种方言），frontmatter 只写 `observation_position`
    **单槽**。单槽不是生效条件（见 nodefile.CONDITION_SLOTS_REQUIRED），
    该四槽在正文里由「索引元条件」行承载（**不再**占用「生效条件」字段——
    Phase 0 契约裁决，见 nodefile.INDEX_META_MARK），
    故本函数按四槽齐备产出，供 `render` 与 `refindex.add_items` 共用。

    时间槽用**全时窗哨兵**而非 `mdcg.add` 缺省补的「写入时刻锚定 1 小时窗」：
    代码条目声明的是「源文件里存在这个符号」，其真值不随写入时刻衰减，
    写成 1 小时观测窗是把写入副作用伪装成条件。
    """
    path = item.get("path") or ""
    top = path.split("/")[0] or "."
    if item.get("precise", True):
        method = f"{LANG_COMPILER}（AST 精确提取，区间精确到 end_lineno）"
    else:
        method = (f"{LANG_WEAK}（正则弱提取，未过编译器；"
                  f"区间为**上界**，以 op=ref 回读为准）")
    return {
        "observation_position": f"本地源码仓（大域={top}）",
        "time_window": [nodefile.FULL_TIME_WINDOW_MIN,
                        nodefile.FULL_TIME_WINDOW_MAX],
        "observation_tool": method,
        "existence_constraint": f"源文件 {path} 存在于本地仓且可读",
    }


# 生效条件：item 为含 "name"、"kind"、"path"、"lineno"、"end" 键的条目字典时（缺这些必需键会 KeyError），返回由 item.get("comments") 的源码 CCG 区、合成 CCG 区、索引元信息区依次拼接的正文；parent/doc/comments/sig 按 item.get 缺键或假值回落，precise 缺键默认 True、键存在假值走弱提取，item["lineno"]/item["end"] 用于 basis 与位置行；
def render(item):
    """条目 → 正文三分区：源码 CCG 区（人工优先）→ 合成 CCG 区 → 索引元信息区。

    **必须渲染成 CCG 格式**，这是本模块最容易踩的坑：
    `judge_qualification` 第一步就查 `ccg_completeness` 的 5 要素
    （功能名 / 子功能 / 执行 / 验证方式 / 不适用条件），缺任一即**直接判
    BLINDSPOT**，后面的「verification_basis 缺失才 DEFER」根本走不到——
    即便 frontmatter 已正确填了 verification_basis。改造前本函数只产
    `# path::name` / `# sig` / `# doc:` 这类非 CCG 行，于是**所有代码节点
    恒定 BLINDSPOT**：存得进、判不了、检索不到（与「目标节点的 CCG 渲染」
    是同一策略，见 mdcg.py 的对应注释）。

    Phase 0 修复（行序压制 + 字段语义分家；契约见
    docs/mdcg/代码评审与条件化注释_契约_v0.1.md）：
      ① **源码 CCG 区置首**——mdcos._ccg_field 取**首个**匹配，置首即
         「人工优先」的确定性序：人工声明的生效条件不再被合成行压制；
      ② 合成区**不再产出生效条件行**——索引元条件不是功能前置条件
         （裁定见 nodefile.INDEX_META_MARK）。故源码未声明的条目会**诚实地
         缺该要素（BLINDSPOT）**，而不是被元条件冒充成 DEFER；
      ③ 索引元信息区改用非 CCG 字段名（索引元条件行 + 位置行），两个语义
         不再挤同一个字段名（可机械判：nodefile.is_ccg_mark）。
    """
    name = item["name"]
    kind = item["kind"]
    path = item["path"]
    parent = item.get("parent") or ""
    doc = (item.get("doc") or "").replace("\n", " ").strip()
    comments = [c.lstrip("#").strip() for c in (item.get("comments") or [])]
    sub = doc or (comments[0] if comments else "") or f"{kind} 定义在 {path}，无注释"
    sig = (item.get("sig") or "").strip() or "（模块级，无签名）"
    if item.get("precise", True):
        basis = (f"{LANG_COMPILER}（AST 已解析，区间精确："
                 f"{path} L{item['lineno']}-L{item['end']}）")
    else:
        basis = (f"{LANG_WEAK}（正则弱提取，未过编译器；区间为**上界**，"
                 f"以 op=ref 回读为准：{path} L{item['lineno']}-L{item['end']}）")
    # ---- 三分区组装（顺序即语义，不许随手改）------------------------------
    #   ① 源码 CCG 区：人工/源码声明逐字保留，**置首**取得「首个匹配」优先权
    #   ② 合成 CCG 区：机械补齐 5 要素，保证 ccg_completeness 不因缺行整体失效
    #   ③ 索引元信息区：非 CCG 字段名 + 位置行（与 CCG_MARKS 零重名）
    lines = ["# " + c for c in comments]
    lines += [
        f"# 功能名：{name}（{kind}）",
        f"# 子功能：{parent + '.' if parent else ''}{sub[:MAX_DOC]}",
        f"# 执行：{sig}",
        f"# 验证方式：{basis}",
        "# 不适用条件：其它大域的**同名**符号（同名不同域时以 path 区分；"
        f"本条目属于 {path}）",
        # 索引元条件**不占用**生效条件字段：它是「条目在何处/何时可被观测」，
        # 不是「这段代码在何种输入下正确」。合成即冒充（nodefile.INDEX_META_MARK）。
        f"# {nodefile.INDEX_META_MARK}："
        + nodefile.condition_space_text(condition_space(item),
                                        require_full=False),
        f"# 位置：{path}:{item['lineno']}-{item['end']}"
        f"（{item.get('lang')}，precise={bool(item.get('precise', True))}）",
    ]
    return "\n".join(lines)


# 生效条件：item 为含 "path" 与 "name" 键的字典时（缺任一键会 KeyError），返回 "code_" 加 (item["path"] + "::" + item["name"]).encode("utf-8") 的 sha1 十六进制前 12 位；
def node_id(item):
    """稳定 id：path::name 的短哈希（重复索引幂等）。"""
    key = (item["path"] + "::" + item["name"]).encode("utf-8")
    return "code_" + hashlib.sha1(key).hexdigest()[:12]


# 生效条件：skip_dirs 传入后，遍历 (skip_dirs or ()) 把每项 str(raw).strip().replace("\\","/").strip("/")，空串跳过；含 "/" 的加入 paths，不含 "/" 的加入 names；若归一化后无规则返回 (None, [])，否则返回 (hit, rules)，其中 hit(rel_dir, base) 在 base 命中 names 或 rel_dir 等于/前缀匹配 paths 中某条加 "/" 时为 True；
def skip_matcher(skip_dirs):
    """把调用方的 `skip_dirs` 编译成「该子目录是否排除」的判定 `hit(rel_dir, base)`。

    与 `SKIP_DIRS` 在**同一处**生效，且**只增不减**：调用方只能追加排除，不能拿掉
    `.git`/`.venv` 这类内置保护——否则一次参数写错就能把版本库元数据索引进认知图。
    规则口径（两类可混用）：
      · 含 `/` → 按**相对 root 的路径**匹配（`docs/experiments` 只排这一处）；
      · 不含 `/` → 按**目录名**匹配（`experiments` 排任意层级的同名目录）。
    反斜杠与首尾斜杠一律归一，避免「规则传了却不生效」这类静默失配。

    返回 `(hit, rules)`；`rules` 为空时 `hit is None` → 调用方走原路径，
    保证**默认行为与改造前逐字一致**（与 `fresh`/`on_file` 同一纪律）。
    排除的**理由**：`.gitignore` 整目录忽略的实验产物物理仍在盘上，会把
    `max_files` 撑爆并让「索引不全」变成常态；用「显式排除 + 回报」比「调大上限」
    诚实。`docindex` 复用本函数（唯一实现，避免两处口径漂移）。
    """
    rules, names, paths = [], set(), []
    for raw in (skip_dirs or ()):
        s = str(raw).strip().replace("\\", "/").strip("/")
        if not s:
            continue
        rules.append(s)
        if "/" in s:
            paths.append(s)
        else:
            names.add(s)
    if not rules:
        return None, []

# 生效条件：在 skip_matcher 返回的闭包中，rel_dir 与 base 传入后，若 base 命中由 skip_dirs 归一化出的不含 "/" 的目录名集合 names 则返回 True；否则若 rel_dir 等于或以其某个含 "/" 的路径规则 paths 加 "/" 为前缀则返回 True；两者都不满足返回 False；
    def hit(rel_dir, base):
        if base in names:
            return True
        return any(rel_dir == p or rel_dir.startswith(p + "/") for p in paths)

    return hit, rules


# 生效条件：当 root 为可 os.walk 的目录时返回 (items, errors, stats)；patterns 为 None 时按模块常量 SUFFIX 取后缀，命中 max_files 或 max_items 上限则在 stats['truncated'] 上报截断，fresh 为 None 时逐文件读盘。
def index_dir(root, patterns=None, max_files=500, max_items=2000,
              fresh=None, on_file=None, skip_dirs=None):
    """按大域（目录）遍历代码，产出 `(items, errors, stats)`。零 LLM。

    `stats["truncated"]` 必须显式上报——截断**不再是静默的**：改造前达到上限
    直接 `return`，调用方只看到 `indexed`/`error_count`，**索引不全却不告警**，
    于是「不完整」被当成「完整」用。同时上报 `skipped_suffixes`：扫到但没被
    索引的后缀要能看见，否则「不漏召回」这句话无法审计。

    `fresh(rel, fp)` / `on_file(rel, fp, items)` 是给 `refindex.Ledger` 留的
    增量钩子（默认 None → 行为与改造前逐字一致）：
      · `fresh` 返回 True → 该文件自上次索引后未变，**不读盘**直接跳过，
        计入 `skipped_unchanged`（仍计入 `files`，故截断语义不变）；
      · `on_file` 在成功提取后回调，用于记录水位。

    `skip_dirs` 是**追加**排除（见 `skip_matcher`）：命中的目录整棵剪掉、不计入
    `files`；实际排掉了哪些目录写进 `stats["skipped_dirs"]`——**排除与截断一样不许
    静默**，否则「节点数变少」会被误读成「源文件真的少了」。
    """
    pats = tuple(patterns or SUFFIX)
    hit_skip, skip_rules = skip_matcher(skip_dirs)
    items, errors, files = [], [], 0
    hit_files = 0
    seen_suffix = set()
    stats = {"root": root, "patterns": list(pats), "files": 0, "truncated": False,
             "truncated_reason": "", "max_files": max_files, "max_items": max_items,
             "skipped_suffixes": [], "skipped_unchanged": 0,
             "skip_dirs": list(skip_rules), "skipped_dirs": [],
             # 截断**可复算**：命中（后缀匹配）文件数与本轮已产出条目数。
             # 与 truncated_reason 一起读，调用方才能核对「差多少」而不是只看到"被截断了"。
             "hit_files": 0, "indexed_items": 0}

# 生效条件：无参闭包，只在本次扫库作用域内可调用；把 files / hit_files / indexed_items / skipped_suffixes / skipped_dirs 一次性落进 stats，三处 return 共用同一口径；
    def _snap():
        """把「截断相关」计数一次性落进 stats（三处 return 共用，避免各处口径漂移）。"""
        stats["files"] = files
        stats["hit_files"] = hit_files
        stats["indexed_items"] = len(items)
        stats["skipped_suffixes"] = sorted(
            s for s in seen_suffix if s and s not in pats)[:12]

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        keep = []
        for d in dirnames:
            if d in SKIP_DIRS:
                continue
            child = f"{rel_dir}/{d}" if rel_dir else d
            if hit_skip is not None and hit_skip(child, d):
                # 就地追加、不依赖末尾汇总：截断提前 return 时也带得走（同 skipped_suffixes）。
                stats["skipped_dirs"].append(child)
                continue
            keep.append(d)
        # 目录序**必须确定性**：os.walk 给出的 dirnames 顺序由文件系统决定，
        # 同一次输入两次运行可能不同 → 索引结果不可复算。排序后 walk 顺序唯一。
        dirnames[:] = sorted(keep)
        for fn in sorted(filenames):
            ext = os.path.splitext(fn)[1].lower()
            seen_suffix.add(ext)
            if not fn.lower().endswith(pats):
                continue
            hit_files += 1
            if files >= max_files or len(items) >= max_items:
                stats["truncated"] = True
                stats["truncated_reason"] = (
                    f"files={files}>=max_files={max_files}"
                    if files >= max_files else
                    f"items={len(items)}>=max_items={max_items}")
                _snap()
                return items, errors, stats
            files += 1
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, root).replace("\\", "/")
            if fresh is not None and fresh(rel, fp):
                stats["skipped_unchanged"] += 1
                continue
            try:
                with open(fp, encoding="utf-8") as f:
                    src = f.read()
                got = extract(src, rel)
                items.extend(got)
                if on_file is not None:
                    on_file(rel, fp, got)
                if len(items) >= max_items:
                    # 单文件就可能越限：越限即记截断并立刻停，不装看不见、
                    # 也不继续往下扫（继续扫只会让「截断」这件事更不明显）。
                    stats["truncated"] = True
                    stats["truncated_reason"] = (
                        f"items={len(items)}>=max_items={max_items}")
                    _snap()
                    return items, errors, stats
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                errors.append(f"{rel}: {exc}")
    _snap()
    return items, errors, stats