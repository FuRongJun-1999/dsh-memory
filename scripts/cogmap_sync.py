"""cogmap_sync.py — 认知图文档同步管线（零第三方依赖）。

真源（single source of truth）：
  md_cg/mcp_server.py
    · 工具名与定义行 —— TOOLS / KERNEL_TOOLS 列表字面量里的 "name" 字段（AST 提取，含行号）
    · cg op 与实现分支行 —— _cg_dispatch 函数体内的 `if op == "..."` 链
    · stg op 与实现分支行 —— _stg_call   函数体内的 `if op == "..."` 链
    · op 实现模块 —— 各 op 分支内的 `from . import X` / `from .X import`（按模块聚合）
    · op 中间函数链 —— 分支内调用的 `_xxx_call` 函数（def 行号同源提取）
  md_cg/whitebox.py
    · action 分支行 —— dispatch 内 `if action in (...)` 链（元组首项为规范名）
    · action 实现函数 —— 分支内 return 的本模块函数
  docs/功能调用映射表的中文功能描述 —— 本脚本 FUNC_DESC（文档层真源，check 门禁必须全覆盖）
  仓库远程地址 —— git remote get-url origin（GitHub blob 链接前缀）

投影（generated sections）：
  README.md                  COGMAP 段（工具面认知图）
  docs/功能调用映射表_v0.1.md  FUNCMAP 段 ×3（id=cg / stg / wb：逐 op 行号级映射表）
段内所有 op / 工具 / 模块 / 函数均为可点击链接，直达 GitHub 源码行——行号由本脚本
从真源 AST 自动提取，check 门禁保证永不过期（代码动了行号漂了即红灯，build 一键重挂）。

用法（cwd=仓库根）：
  python scripts/cogmap_sync.py check   # 校验全部投影与真源一致（CI 门禁，退出码 0/1）
  python scripts/cogmap_sync.py build   # 重新生成全部标记段并写回
  python scripts/cogmap_sync.py print   # 仅打印将生成的标记段（不写文件）

校验范围（check）：
  1. 全部标记段内容 == 按真源重新生成的文本（数字/链接/行号漂移即红灯）
  2. 两文档引用的 cg/stg op、mdcg_* 工具名都存在于真源
  3. 两文档的仓内相对文件链接目标存在；页内/跨文件锚点存在
  4. 认知图引用的实现模块必须有对应源文件
  5. FUNC_DESC 必须覆盖全部 op/action（新功能落地漏中文描述即红灯——文档写入纪律）

纪律：行号锚只能由本管线生成（自动提取 + 门禁守卫），禁止手工书写行号锚。
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "md_cg" / "mcp_server.py"
WHITEBOX = ROOT / "md_cg" / "whitebox.py"
README = ROOT / "README.md"
MAPDOC = ROOT / "docs" / "功能调用映射表_v0.1.md"

# GitHub blob 链接的分支基座（GitHub 页面渲染视角 = 默认分支）
BRANCH = "main"

BEGIN = "<!-- COGMAP:BEGIN (scripts/cogmap_sync.py 自动生成 · 真源 md_cg/mcp_server.py · 勿手改段内) -->"
END = "<!-- COGMAP:END -->"


def _funcmap_begin(seg: str) -> str:
    return f"<!-- FUNCMAP:BEGIN id={seg} (scripts/cogmap_sync.py 自动生成 · 勿手改段内) -->"


FUNCMAP_END = "<!-- FUNCMAP:END -->"

# 非 MCP 工具但文档合法引用的名字（带理由，防「引用漂移」误报）
NAME_ALLOWLIST = {
    "mdcg_eval": "rust/ 检索库评测器 CLI 名（rust/README.md），非 mcp_server 工具",
    "mdcg_client": "DSH 插件仓 TS 客户端模块文件名 mdcg_client.ts，非 mcp_server 工具",
}

# 文档链接但外部 clone 后不存在的仓内路径（带理由）：链接语义=「本地会有此文件」。
FILE_LINK_ALLOWLIST = {
    "AGENTS.md": "仓库根纪律投影（.gitignore「本地使用不共享」，外部 clone 无此文件属预期）；"
    "README 指向它是刻意的（CodeBuddy 注入通道说明）",
}

# 中文功能描述（文档层真源）：功能调用映射表「功能」列的内容。
# check 门禁要求覆盖全部 op/action——新功能落地漏登记描述即红灯。
FUNC_DESC: dict[tuple[str, str], str] = {
    ("cg", "theory"): "理论检索（领域理论 / 方法论文）",
    ("cg", "link"): "记忆互链（节点间链接管理）",
    ("cg", "info"): "服务信息 / 健康",
    ("cg", "route"): "路由：意图→知识+建议能力",
    ("cg", "read"): "读取（按 id / 召回 / 预算）",
    ("cg", "write"): "写入（含冲突检测 / 闸门 / 审核）",
    ("cg", "goal"): "目标（写入 / 状态 / 清单）",
    ("cg", "recent"): "最近记忆（事件窗口）",
    ("cg", "verify"): "外部裁决回填（节点证据验证）",
    ("cg", "review"): "审核队列（DEFER / 提案裁决）",
    ("cg", "forget"): "主动遗忘 / 恢复",
    ("cg", "protect"): "保护（不可遗忘）",
    ("cg", "identity"): "身份维度",
    ("cg", "consistency"): "一致性检测",
    ("cg", "metacognition"): "元认知（盲区聚合）",
    ("cg", "self_state"): "自我状态",
    ("cg", "evolution"): "演化（记忆结构演化）",
    ("cg", "sustain"): "飞轮 / 自愈",
    ("cg", "scrub"): "洗脑 / 去污染",
    ("cg", "predict"): "预测 / 因果门",
    ("cg", "causal"): "因果链",
    ("cg", "whitebox"): "白箱能力库（AEIS 能力显式调用）",
    ("cg", "index_code"): "代码索引",
    ("cg", "index_doc"): "文档索引",
    ("cg", "ref"): "引用 / 反向引用",
    ("cg", "session"): "会话管理（多会话归属与过滤）",
    ("cg", "ingest"): "导入落图",
    ("cg", "export"): "导出",
    ("cg", "maintain"): "维护",
    ("cg", "consolidate"): "记忆固化 / 整理",
    ("cg", "insight"): "洞察 / 自主探索（信息差驱动）",
    ("stg", "relation"): "两节点关系",
    ("stg", "timeline"): "时间线",
    ("stg", "anchors"): "锚点检索（时空窗口）",
    ("stg", "consistency"): "时空一致性",
    ("whitebox", "ask"): "白箱问答",
    ("whitebox", "remember"): "白箱编码（知识写入能力库）",
    ("whitebox", "verify_encoding"): "验证编码能力（写入口令→追问命中）",
    ("whitebox", "verify_existing"): "验证已有知识回答能力（探针 route=self）",
    ("whitebox", "ping"): "连通性探测",
    ("whitebox", "report"): "验证报告（self 层留痕汇总）",
}


# ---------------------------------------------------------------- 真源提取

def _dict_name(el: ast.expr) -> str | None:
    """从列表元素（Dict 字面量）里取 "name" 字段的值。"""
    if not isinstance(el, ast.Dict):
        return None
    for k, v in zip(el.keys, el.values):
        if isinstance(k, ast.Constant) and k.value == "name" and isinstance(v, ast.Constant):
            return str(v.value)
    return None


def _func_span(src_lines: list[str], tree: ast.Module, fname: str) -> tuple[int, str] | None:
    """返回 (函数起始行号[1-based], 函数源码文本)。"""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == fname:
            return node.lineno, "".join(src_lines[node.lineno - 1 : node.end_lineno])
    return None


def _repo_base() -> str:
    """git origin → GitHub 仓库基址（https://github.com/Owner/repo）。"""
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except OSError as exc:
        raise SystemExit(f"cogmap_sync 需要 git 读取 origin 远程地址：{exc}") from exc
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?/?$", url)
    if not m:
        raise SystemExit(f"无法从 origin 解析 GitHub 仓库地址：{url!r}")
    return f"https://github.com/{m.group(1)}"


def _all_funcs(tree: ast.Module) -> dict[str, int]:
    """模块全部顶层函数名 → def 行号。"""
    return {n.name: n.lineno for n in tree.body if isinstance(n, ast.FunctionDef)}


def extract() -> dict:
    src = SERVER.read_text(encoding="utf-8")
    src_lines = src.splitlines(keepends=True)
    tree = ast.parse(src)

    kernel_tools: list[str] = []
    mdcg_tools: list[str] = []
    tool_lines: dict[str, int] = {}  # 工具名 → 定义行号（"name": 所在 dict 的行）
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.List)):
            continue
        targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
        names = []
        for el in node.value.elts:
            name = _dict_name(el)
            if name:
                names.append(name)
                tool_lines.setdefault(name, el.lineno)
        if "KERNEL_TOOLS" in targets:
            kernel_tools = names
        elif "TOOLS" in targets:
            mdcg_tools = names

    # op 清单 / 分支行号 / 实现模块 / 分支函数链：一次遍历同源提取。
    # 键为 (tool, op)：cg 与 stg 存在同名 op（如 consistency），按 op 名聚合会撞行。
    op_lines: dict[tuple[str, str], int] = {}  # (tool, op) → 分支行号
    func_lines: dict[str, int] = {}  # 分发函数名 → def 行号
    op_modules: dict[tuple[str, str], set[str]] = {}
    branch_funcs: dict[tuple[str, str], list[str]] = {}  # (tool, op) → 中间/实现函数链
    op_head = re.compile(r'if\s+op\s*==\s*"([a-z_]+)"')
    act_head = re.compile(r'if\s+action\s+in\s*\(\s*"([a-z_]+)"')

    # (fkey, 文件, dispatch 函数, tool 名, 分支头正则)；fkey 决定 blob 链接与函数表
    dispatches = (
        ("server", SERVER, "_cg_dispatch", "cg", op_head),
        ("server", SERVER, "_stg_call", "stg", op_head),
        ("whitebox", WHITEBOX, "dispatch", "whitebox", act_head),
    )
    funcs: dict[str, dict[str, int]] = {}
    # 分支数自检数据：tool → (宽松形态计数, 严格提取数)。宽松正则兼容单/双引号与 ==/in
    # 两种写法；严格提取只认规范写法。两数不等 = 有分支被静默漏报（外部审计指出的窗口）。
    branch_counts: dict[str, tuple[int, int]] = {}
    loose_res = {
        "cg": r"if\s+op\s*==\s*['\"]",
        "stg": r"if\s+op\s*==\s*['\"]",
        "whitebox": r"if\s+action\s*(?:==\s*['\"]|in\s*\()",
    }
    for fkey, path, fn, tool, head_re in dispatches:
        psrc = path.read_text(encoding="utf-8")
        ptree = ast.parse(psrc)
        funcs[fkey] = _all_funcs(ptree)
        span = _func_span(psrc.splitlines(keepends=True), ptree, fn)
        if span is None:
            continue
        start, body = span
        func_lines[fn] = start
        matches = list(head_re.finditer(body))
        branch_counts[tool] = (len(re.findall(loose_res[tool], body)), len(matches))
        for i, m in enumerate(matches):
            op = m.group(1)
            op_lines[(tool, op)] = start + body[: m.start()].count("\n")
            block = body[m.start() : matches[i + 1].start() if i + 1 < len(matches) else len(body)]
            if (tool, op) not in op_modules:
                mods = set(re.findall(r"from \. import (\w+)", block)) | set(
                    re.findall(r"from \.(\w+) import", block)
                )
                op_modules[(tool, op)] = {x for x in mods if x not in ("tokens",)}
            if (tool, op) not in branch_funcs:
                if tool in ("cg", "stg"):  # 分支内调用的 _xxx_call 中间函数
                    seen: list[str] = []
                    for name in re.findall(r"\b(_[a-z][a-z_]*_call)\s*\(", block):
                        if name not in seen:
                            seen.append(name)
                else:  # whitebox：分支内 return 的本模块实现函数
                    seen = [
                        f
                        for f in re.findall(r"\breturn\s+([a-z_]+)\s*\(", block)
                        if f in funcs[fkey]
                    ]
                branch_funcs[(tool, op)] = seen

    return {
        "kernel_tools": kernel_tools,
        "mdcg_tools": mdcg_tools,
        "cg_ops": [o for (t, o) in op_lines if t == "cg"],
        "stg_ops": [o for (t, o) in op_lines if t == "stg"],
        "wb_ops": [o for (t, o) in op_lines if t == "whitebox"],
        "tool_lines": tool_lines,
        "op_lines": op_lines,
        "func_lines": func_lines,
        "funcs": funcs,
        "op_modules": op_modules,
        "branch_funcs": branch_funcs,
        "branch_counts": branch_counts,
        "repo_base": _repo_base(),
        "branch": BRANCH,
    }


# ---------------------------------------------------------------- 投影生成

_BLOB_FILE = {"server": "mcp_server.py", "whitebox": "whitebox.py"}


def _blob(e: dict, line: int, fkey: str = "server") -> str:
    """真源文件第 line 行的 GitHub blob 链接（人类点击直达代码行）。"""
    return f"{e['repo_base']}/blob/{e['branch']}/md_cg/{_BLOB_FILE[fkey]}#L{line}"


def _tlink(e: dict, name: str) -> str:
    """工具名 → 定义行链接。"""
    line = e["tool_lines"].get(name)
    return f"[`{name}`]({_blob(e, line)})" if line else f"`{name}`"


def _olink(e: dict, tool: str, op: str) -> str:
    """op → dispatch 实现分支行链接。"""
    line = e["op_lines"].get((tool, op))
    return f"[`{op}`]({_blob(e, line)})" if line else f"`{op}`"


def _flink(e: dict, fkey: str, fname: str) -> str:
    """函数名 → def 行链接（fkey 文件内）；whitebox 实现函数带模块前缀消歧。"""
    line = e["funcs"].get(fkey, {}).get(fname)
    label = f"whitebox.{fname}" if fkey == "whitebox" else fname
    return f"[`{label}`]({_blob(e, line, fkey)})" if line else f"`{label}`"


def _mdlink(mod: str) -> str:
    """实现模块 → 仓内源文件相对链接（相对路径，GitHub 渲染后可点击）。"""
    for cand in (f"md_cg/{mod}.py", f"md_cg/{mod}/__init__.py"):
        if (ROOT / cand).exists():
            return f"[`{mod}`]({cand})"
    return f"`{mod}`"


def _mod_table(e: dict) -> str:
    """op → 实现模块（按工具分组、按模块聚合，减少表行数；全链接化）。"""
    lines = ["| op（点击直达实现分支） | 实现模块（点击直达源码） |", "|---|---|"]
    for tool, fn in (("cg", "_cg_dispatch"), ("stg", "_stg_call")):
        by_mod: dict[str, list[str]] = {}
        ops = e["cg_ops"] if tool == "cg" else e["stg_ops"]
        for op in ops:
            mods = sorted(e["op_modules"].get((tool, op), set()))
            if mods:
                key = ", ".join(_mdlink(m) for m in mods)
            else:
                fl = e["func_lines"].get(fn)
                key = f"[`{fn}` 内联]({_blob(e, fl)})" if fl else f"（`{fn}` 内联）"
            by_mod.setdefault(key, []).append(_olink(e, tool, op))
        for mods, oplist in sorted(by_mod.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            lines.append(f"| {' '.join(oplist)} | {mods} |")
    return "\n".join(lines)


def _map_rows(e: dict, tool: str, call_fmt: str) -> list[str]:
    """逐 op 映射表行：功能（中文）| 显式调用 | 代码位置（分支→函数链→模块，全链接）。"""
    fkey = "server" if tool != "whitebox" else "whitebox"
    rows = []
    ops = {"cg": e["cg_ops"], "stg": e["stg_ops"], "whitebox": e["wb_ops"]}[tool]
    for op in ops:
        desc = FUNC_DESC.get((tool, op), "")
        parts = [_olink(e, tool, op)]  # 链头：实现分支行
        for fname in e["branch_funcs"].get((tool, op), []):  # 中间/实现函数链
            parts.append(_flink(e, fkey, fname))
        mods = sorted(e["op_modules"].get((tool, op), set()))
        for m in mods:
            parts.append(_mdlink(m))
        chain = " → ".join(parts) if len(parts) > 1 else parts[0]
        label = desc or f"`{op}`"
        rows.append(f"| {label} | {call_fmt.format(op=op)} | {chain} |")
    return rows


def render_section(e: dict) -> str:
    cg_n, stg_n = len(e["cg_ops"]), len(e["stg_ops"])
    cg_list = " ".join(_olink(e, "cg", o) for o in e["cg_ops"])
    stg_list = " ".join(_olink(e, "stg", o) for o in e["stg_ops"])
    mdcg_n = len(e["mdcg_tools"])
    total_tools = len(e["kernel_tools"]) + mdcg_n
    mdcg_links = " ".join(_tlink(e, n) for n in e["mdcg_tools"])
    return "\n".join(
        [
            BEGIN,
            "",
            f"**两个认知基元 · {cg_n + stg_n} 个 op**（`kernel` 面）——下列 op 清单、实现模块与"
            f"全部链接行号由 [cogmap_sync](scripts/cogmap_sync.py) 从真源自动提取，"
            f"`check` 门禁守卫漂移；**点击任意名字直达源码对应行**：",
            "",
            "| 基元 | op 数 | op 清单（点击直达实现分支） |",
            "|---|---|---|",
            f"| **{_tlink(e, 'cg')}** 认知图统一入口 | {cg_n} | {cg_list} |",
            f"| **{_tlink(e, 'stg')}** 语义时空图入口 | {stg_n} | {stg_list} |",
            "",
            "**op → 实现模块**（认知图投影：功能在哪段代码，一眼可达）：",
            "",
            _mod_table(e),
            "",
            f"**细粒度面**（`MDCG_MCP_SURFACE=full`，插件运行时使用）：{_tlink(e, 'cg')} + "
            f"{_tlink(e, 'stg')} + **{mdcg_n} 个 `mdcg_*`** = **{total_tools} 个工具**：",
            "",
            mdcg_links,
            "",
            "逐个 op 的「功能 → 代码 → op」行号级映射另见[功能调用映射表](docs/功能调用映射表_v0.1.md)。",
            "",
            END,
        ]
    )


# ---------------------------------------------------------------- 映射表投影

_MAP_HEAD = "| 功能 | 显式调用 | 代码位置（点击直达源码行） |", "|---|---|---|"


def _map_section(e: dict, seg: str) -> str:
    """映射表单段：FUNCMAP 标记包裹的一张逐 op 表。"""
    if seg == "cg":
        rows = _map_rows(e, "cg", "`cg(op={op})`")
        title = f"**认知基元 `cg` · {len(e['cg_ops'])} 个 op**（行号由本管线从真源自动提取，`check` 门禁守卫漂移）："
    elif seg == "stg":
        rows = _map_rows(e, "stg", "`stg(op={op})`")
        title = f"**语义时空基元 `stg` · {len(e['stg_ops'])} 个 op**："
    else:
        rows = _map_rows(
            e, "whitebox", "`cg(op=whitebox, action={op})`"
        )
        title = "**白箱能力库 `whitebox`（AEIS 能力库唯一显式入口）· action 分发**："
    return "\n".join([_funcmap_begin(seg), "", title, "", *_MAP_HEAD, *rows, "", FUNCMAP_END])


def render_mapdoc(e: dict) -> list[tuple[str, str]]:
    """[(seg, 段内容)]：映射表文档的全部 FUNCMAP 段。"""
    return [(seg, _map_section(e, seg)) for seg in ("cg", "stg", "wb")]


# ---------------------------------------------------------------- 段替换通用

def _splice(text: str, begin: str, end: str, repl: str) -> tuple[str, bool]:
    """替换 text 中首个 begin..end 段为 repl；无段时返回原文并标记未找到。"""
    m = re.search(re.escape(begin) + r".*?" + re.escape(end), text, re.S)
    if not m:
        return text, False
    return text[: m.start()] + repl + text[m.end() :], True


# ---------------------------------------------------------------- README 工具

def _md_titles(text: str) -> list[str]:
    """收集 md 文档围栏代码块外的全部标题行（页内锚点校验用，不限 README）。"""
    titles, fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if not fence and re.match(r" {0,3}#{1,6} ", line):
            titles.append(re.sub(r"^ {0,3}#{1,6} ", "", line).strip())
    return titles


def _gh_anchor(title: str) -> str:
    """GitHub 锚点算法近似：lower → 非 \\w- 字符删除（中文/字母数字/下划线保留）→ 空格转 '-'。"""
    out = []
    for ch in title.strip().lower():
        if ch.isspace():
            out.append("-")
        elif ch.isalnum() or ch == "_" or ch == "-":
            out.append(ch)
    return "".join(out)


_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
_CG_OP_RE = re.compile(r"cg\(op=([a-z_]+)\)")
_STG_OP_RE = re.compile(r"stg\(op=([a-z_]+)\)")
_MDCG_RE = re.compile(r"\bmdcg_[a-z_]+\b")


def check(e: dict) -> list[str]:
    errors: list[str] = []

    # 0) FUNC_DESC 必须覆盖全部 op/action（文档写入纪律：新功能漏中文描述即红灯）
    for (tool, op) in sorted(e["op_lines"]):
        if (tool, op) not in FUNC_DESC:
            errors.append(f"FUNC_DESC 缺中文功能描述：{tool}({op})——功能调用映射表「功能」列将退化为英文名")

    # 0.5) 分支数自检：宽松形态计数（含单/双引号、==/in）必须 == 严格提取数。
    # 不等 = 代码里有分支写法超出规范形态被静默漏报（如单引号 op），先修提取再谈门禁。
    loose_loc = {"cg": SERVER, "stg": SERVER, "whitebox": WHITEBOX}
    for tool, (loose, strict) in sorted(e["branch_counts"].items()):
        if loose != strict:
            errors.append(
                f"{tool} 分支数自检失败：{loose_loc[tool].name} 中宽松形态 {loose} 处 vs 规范提取 {strict} 处"
                "——存在非规范写法的分支被静默漏报（如单引号/别名形态），请统一写法或扩展提取正则"
            )

    readme_secs = [(BEGIN, END, render_section(e))]
    map_secs = [(_funcmap_begin(seg), FUNCMAP_END, body) for seg, body in render_mapdoc(e)]
    docs = (("README", README, readme_secs), ("功能调用映射表", MAPDOC, map_secs))
    for dname, dpath, secs in docs:
        if not dpath.exists():
            errors.append(f"{dname} 不存在：{dpath}")
            continue
        text = dpath.read_text(encoding="utf-8")
        errors.extend(_check_doc(e, dname, text, secs))
    return errors


def _check_doc(e: dict, dname: str, text: str, sections: list[tuple[str, str, str]]) -> list[str]:
    """单文档校验：段一致性 / op·工具引用 ⊆ 真源 / 文件链接与锚点存在。"""
    errors: list[str] = []

    # 1) 标记段一致性
    for begin, end, want in sections:
        label = "COGMAP" if begin == BEGIN else begin.split("id=")[1].split(" ")[0]
        label = f"FUNCMAP:{label}" if begin != BEGIN else label
        m = re.search(re.escape(begin) + r".*?" + re.escape(end), text, re.S)
        if not m:
            errors.append(f"{dname} 缺少 {label} 标记段")
            continue
        have = m.group(0)
        if want != have:
            for wl, hl in zip(want.splitlines(), have.splitlines()):
                if wl != hl:
                    errors.append(f"{dname} {label} 段与真源不一致：\n  期望: {wl}\n  实际: {hl}")
                    break
            if len(want.splitlines()) != len(have.splitlines()):
                errors.append(
                    f"{dname} {label} 段行数漂移：期望 {len(want.splitlines())} 行，实际 {len(have.splitlines())} 行"
                )

    # 2) op / 工具名引用 ⊆ 真源
    valid_ops = set(e["cg_ops"]) | set(e["stg_ops"])
    for op in sorted(set(_CG_OP_RE.findall(text)) - valid_ops):
        errors.append(f"{dname} 引用了不存在的 cg op：cg(op={op})")
    for op in sorted(set(_STG_OP_RE.findall(text)) - valid_ops):
        errors.append(f"{dname} 引用了不存在的 stg op：stg(op={op})")
    valid_names = set(e["mdcg_tools"]) | set(NAME_ALLOWLIST)
    for name in sorted(set(_MDCG_RE.findall(text)) - valid_names):
        errors.append(f"{dname} 引用了不存在的工具名：{name}（如属合法外部名，请登记 NAME_ALLOWLIST）")

    # 2.5) 认知图引用的实现模块必须有对应源文件（否则投影降级为纯文本，链接链断裂）
    for (tool, op), mods in sorted(e["op_modules"].items()):
        for mod in sorted(mods):
            if not any((ROOT / c).exists() for c in (f"md_cg/{mod}.py", f"md_cg/{mod}/__init__.py")):
                errors.append(f"op {tool}({op}) 引用的实现模块无源文件：md_cg/{mod}.*")

    # 3) 文件链接存在 + 锚点存在
    anchors = {_gh_anchor(t) for t in _md_titles(text)}
    for link in _LINK_RE.findall(text):
        if link.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, frag = link.partition("#")
        if path:
            if path in FILE_LINK_ALLOWLIST:
                continue
            if not (ROOT / path).exists():
                errors.append(f"{dname} 文件链接不存在：{link}")
                continue
            if frag:  # 跨文件锚点：校验目标文件内的标题锚点
                try:
                    sub = (ROOT / path).read_text(encoding="utf-8")
                except OSError:
                    continue
                if not _md_file_has_anchor(sub, frag):
                    errors.append(f"{dname} 跨文件锚点不存在：{link}")
        elif frag:  # 页内锚点
            if frag not in anchors:
                errors.append(f"{dname} 页内锚点不存在：#{frag}")

    # 4) 手写行号锚禁令：段外出现 md_cg/*.py:行号 形态即违规（行号只能由管线生成）
    stripped = _strip_sections(text)
    for m in re.finditer(r"[\w/\\]+\.(?:py|ts)\s*[:：]\s*\d+", stripped):
        errors.append(f"{dname} 手写区残留行号锚（须删行号或交由管线生成）：{m.group(0)}")
    return errors


def _strip_sections(text: str) -> str:
    """剥掉全部生成段——手写纪律只约束段外内容。"""
    pats = [re.escape(BEGIN) + r".*?" + re.escape(END)]
    pats += [re.escape(_funcmap_begin(s)) + r".*?" + re.escape(FUNCMAP_END) for s in ("cg", "stg", "wb")]
    out = text
    for p in pats:
        out = re.sub(p, "", out, flags=re.S)
    return out


def _md_file_has_anchor(text: str, frag: str) -> bool:
    return frag in {_gh_anchor(t) for t in _md_titles(text)}


# ---------------------------------------------------------------- 入口

def _load(path: Path) -> tuple[str, str]:
    """读文档：内容归一为换行（与渲染对齐），返回 (文本, 原行尾风格)。"""
    raw = path.read_bytes()
    crlf, lf = raw.count(b"\r\n"), raw.count(b"\n") - raw.count(b"\r\n")
    nl = "\r\n" if crlf > lf else "\n"
    return raw.decode("utf-8").replace("\r\n", "\n"), nl


def _save(path: Path, text: str, nl: str) -> None:
    if nl != "\n":
        text = text.replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def _targets(e: dict) -> list[tuple[str, Path, list[tuple[str, str, str]]]]:
    """全部投影目标：[(文档名, 路径, [(begin, end, 渲染内容)])]。"""
    readme_secs = [(BEGIN, END, render_section(e))]
    map_secs = [(_funcmap_begin(seg), FUNCMAP_END, body) for seg, body in render_mapdoc(e)]
    return [("README", README, readme_secs), ("功能调用映射表", MAPDOC, map_secs)]


def build() -> int:
    e = extract()
    ok = True
    for dname, dpath, sections in _targets(e):
        text, nl = _load(dpath)
        missing = []
        for begin, end, repl in sections:
            text, found = _splice(text, begin, end, repl)
            if not found:
                missing.append(begin)
        if missing:
            print(f"build: {dname} 缺少标记段 {' / '.join(missing)}——请先手工放置骨架"
                  "（可 `python scripts/cogmap_sync.py print` 取内容），build 只做段内替换")
            ok = False
            continue
        _save(dpath, text, nl)
        print(f"build: {dname} 标记段已写回（{len(sections)} 段）")
    if ok:
        print(f"  真源口径：cg {len(e['cg_ops'])} op / stg {len(e['stg_ops'])} op / "
              f"whitebox {len(e['wb_ops'])} action / mdcg_* {len(e['mdcg_tools'])} 个")
    return 0 if ok else 1


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("check", "build", "print"):
        print(__doc__)
        return 2
    e = extract()
    if sys.argv[1] == "print":
        for dname, _, sections in _targets(e):
            print(f"===== {dname} =====")
            for _, _, repl in sections:
                print(repl)
                print()
        return 0
    if sys.argv[1] == "build":
        return build()
    errors = check(e)
    if errors:
        print(f"cogmap check: {len(errors)} 个问题")
        for err in errors:
            print(" -", err)
        return 1
    print(f"cogmap check: 通过（cg {len(e['cg_ops'])} op / stg {len(e['stg_ops'])} op / "
          f"whitebox {len(e['wb_ops'])} action / mdcg_* {len(e['mdcg_tools'])} 个；"
          f"双文档标记段、op/工具引用、文件链接、锚点、FUNC_DESC 覆盖全部一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
