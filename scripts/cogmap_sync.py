"""cogmap_sync.py — README 认知图同步管线（零第三方依赖）。

真源（single source of truth）：md_cg/mcp_server.py
  · 工具名与定义行 —— TOOLS / KERNEL_TOOLS 列表字面量里的 "name" 字段（AST 提取，含行号）
  · cg op 与实现分支行 —— _cg_dispatch 函数体内的 `if op == "..."` 链
  · stg op 与实现分支行 —— _stg_call   函数体内的 `if op == "..."` 链
  · op 实现模块 —— 各 op 分支内的 `from . import X` / `from .X import`（按模块聚合）
  · 仓库远程地址 —— git remote get-url origin（GitHub blob 链接前缀）

投影（generated section）：README.md 的 COGMAP 标记段（段外手写内容零触碰）。
段内所有 op / 工具 / 模块均为可点击链接，直达 GitHub 源码行——行号由本脚本
从真源 AST 自动提取，check 门禁保证永不过期（代码动了行号漂了即红灯，build 一键重挂）。

用法（cwd=仓库根）：
  python scripts/cogmap_sync.py check   # 校验 README 投影与真源一致（CI 门禁，退出码 0/1）
  python scripts/cogmap_sync.py build   # 重新生成标记段并写回 README
  python scripts/cogmap_sync.py print   # 仅打印将生成的标记段（不写文件）

校验范围（check）：
  1. 标记段内容 == 按真源重新生成的文本（数字/链接/行号漂移即红灯）
  2. README 全文引用的 cg/stg op、mdcg_* 工具名都存在于真源
  3. README 仓内相对文件链接目标存在
  4. README 页内锚点链接的锚点目标存在（按 GitHub 锚点算法模拟，含跨文件 md 锚点）
  5. 认知图引用的实现模块必须有对应源文件

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
README = ROOT / "README.md"

# GitHub blob 链接的分支基座（GitHub 页面渲染视角 = 默认分支）
BRANCH = "main"

BEGIN = "<!-- COGMAP:BEGIN (scripts/cogmap_sync.py 自动生成 · 真源 md_cg/mcp_server.py · 勿手改段内) -->"
END = "<!-- COGMAP:END -->"

# 非 MCP 工具但 README 合法引用的名字（带理由，防「引用漂移」误报）
NAME_ALLOWLIST = {
    "mdcg_eval": "rust/ 检索库评测器 CLI 名（rust/README.md），非 mcp_server 工具",
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

    # op 清单 / 分支行号 / 实现模块：一次遍历同源提取。
    # 键为 (tool, op)：cg 与 stg 存在同名 op（如 consistency），按 op 名聚合会撞行。
    op_lines: dict[tuple[str, str], int] = {}  # (tool, op) → `if op ==` 分支行号
    func_lines: dict[str, int] = {}  # 分发函数名 → def 行号
    op_modules: dict[tuple[str, str], set[str]] = {}
    head_re = re.compile(r'if\s+op\s*==\s*"([a-z_]+)"')
    for fn, tool in (("_cg_dispatch", "cg"), ("_stg_call", "stg")):
        span = _func_span(src_lines, tree, fn)
        if span is None:
            continue
        start, body = span
        func_lines[fn] = start
        matches = list(head_re.finditer(body))
        for i, m in enumerate(matches):
            op = m.group(1)
            op_lines[(tool, op)] = start + body[: m.start()].count("\n")
            if (tool, op) not in op_modules:
                block = body[m.start() : matches[i + 1].start() if i + 1 < len(matches) else len(body)]
                mods = set(re.findall(r"from \. import (\w+)", block)) | set(
                    re.findall(r"from \.(\w+) import", block)
                )
                op_modules[(tool, op)] = {x for x in mods if x not in ("tokens",)}

    return {
        "kernel_tools": kernel_tools,
        "mdcg_tools": mdcg_tools,
        "cg_ops": [o for (t, o) in op_lines if t == "cg"],
        "stg_ops": [o for (t, o) in op_lines if t == "stg"],
        "tool_lines": tool_lines,
        "op_lines": op_lines,
        "func_lines": func_lines,
        "op_modules": op_modules,
        "repo_base": _repo_base(),
        "branch": BRANCH,
    }


# ---------------------------------------------------------------- 投影生成

def _blob(e: dict, line: int) -> str:
    """真源文件第 line 行的 GitHub blob 链接（人类点击直达代码行）。"""
    return f"{e['repo_base']}/blob/{e['branch']}/md_cg/mcp_server.py#L{line}"


def _tlink(e: dict, name: str) -> str:
    """工具名 → 定义行链接。"""
    line = e["tool_lines"].get(name)
    return f"[`{name}`]({_blob(e, line)})" if line else f"`{name}`"


def _olink(e: dict, tool: str, op: str) -> str:
    """op → dispatch 实现分支行链接。"""
    line = e["op_lines"].get((tool, op))
    return f"[`{op}`]({_blob(e, line)})" if line else f"`{op}`"


def _mdlink(mod: str) -> str:
    """实现模块 → 仓内源文件相对链接（README 相对路径，GitHub 渲染后可点击）。"""
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


# ---------------------------------------------------------------- README 工具

def _readme_titles(text: str) -> list[str]:
    """收集 README 围栏代码块外的全部标题行。"""
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
    text = README.read_text(encoding="utf-8")

    # 1) 标记段一致性
    m = re.search(re.escape(BEGIN) + r".*?" + re.escape(END), text, re.S)
    if not m:
        errors.append("README 缺少 COGMAP 标记段（应位于「🧰 工具面」）")
    else:
        want, have = render_section(e), m.group(0)
        if want != have:
            for wl, hl in zip(want.splitlines(), have.splitlines()):
                if wl != hl:
                    errors.append(f"标记段与真源不一致：\n  期望: {wl}\n  实际: {hl}")
                    break
            if len(want.splitlines()) != len(have.splitlines()):
                errors.append(f"标记段行数漂移：期望 {len(want.splitlines())} 行，实际 {len(have.splitlines())} 行")

    # 2) op / 工具名引用 ⊆ 真源
    valid_ops = set(e["cg_ops"]) | set(e["stg_ops"])
    for op in sorted(set(_CG_OP_RE.findall(text)) - valid_ops):
        errors.append(f"引用了不存在的 cg op：cg(op={op})")
    for op in sorted(set(_STG_OP_RE.findall(text)) - valid_ops):
        errors.append(f"引用了不存在的 stg op：stg(op={op})")
    valid_names = set(e["mdcg_tools"]) | set(NAME_ALLOWLIST)
    for name in sorted(set(_MDCG_RE.findall(text)) - valid_names):
        errors.append(f"引用了不存在的工具名：{name}（如属合法外部名，请登记 NAME_ALLOWLIST）")

    # 2.5) 认知图引用的实现模块必须有对应源文件（否则投影降级为纯文本，链接链断裂）
    for (tool, op), mods in sorted(e["op_modules"].items()):
        for mod in sorted(mods):
            if not any((ROOT / c).exists() for c in (f"md_cg/{mod}.py", f"md_cg/{mod}/__init__.py")):
                errors.append(f"op {tool}({op}) 引用的实现模块无源文件：md_cg/{mod}.*")

    # 3) 文件链接存在
    anchors = {_gh_anchor(t) for t in _readme_titles(text)}
    for link in _LINK_RE.findall(text):
        if link.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, frag = link.partition("#")
        if path:
            if not (ROOT / path).exists():
                errors.append(f"文件链接不存在：{link}")
                continue
            if frag:  # 跨文件锚点：校验目标文件内的标题锚点
                try:
                    sub = (ROOT / path).read_text(encoding="utf-8")
                except OSError:
                    continue
                if frag and not _md_file_has_anchor(sub, frag):
                    errors.append(f"跨文件锚点不存在：{link}")
        elif frag:  # 页内锚点
            if frag not in anchors:
                errors.append(f"页内锚点不存在：#{frag}")
    return errors


def _md_file_has_anchor(text: str, frag: str) -> bool:
    return frag in {_gh_anchor(t) for t in _readme_titles(text)}


# ---------------------------------------------------------------- 入口

def _load() -> tuple[str, str]:
    """读 README：内容归一为 \\n（与 render_section 对齐），返回 (文本, 原行尾风格)。"""
    raw = README.read_bytes()
    crlf, lf = raw.count(b"\r\n"), raw.count(b"\n") - raw.count(b"\r\n")
    nl = "\r\n" if crlf > lf else "\n"
    return raw.decode("utf-8").replace("\r\n", "\n"), nl


def _save(text: str, nl: str) -> None:
    if nl != "\n":
        text = text.replace("\n", "\r\n")
    README.write_bytes(text.encode("utf-8"))


def build() -> int:
    e = extract()
    text, nl = _load()
    section = render_section(e)
    m = re.search(re.escape(BEGIN) + r".*?" + re.escape(END), text, re.S)
    if not m:
        print("build: README 尚无 COGMAP 标记段——请先在「🧰 工具面」手工放置骨架"
              "（可 `python scripts/cogmap_sync.py print` 取内容），build 只做段内替换")
        return 1
    text = text[: m.start()] + section + text[m.end() :]
    _save(text, nl)
    print(f"build: 标记段已写回 {README.name}（cg {len(e['cg_ops'])} op / stg {len(e['stg_ops'])} op / "
          f"工具 {len(e['kernel_tools']) + len(e['mdcg_tools'])} 个）")
    return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("check", "build", "print"):
        print(__doc__)
        return 2
    e = extract()
    if sys.argv[1] == "print":
        print(render_section(e))
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
          f"mdcg_* {len(e['mdcg_tools'])} / 工具 {len(e['kernel_tools']) + len(e['mdcg_tools'])} 个；"
          f"标记段、op/工具引用、文件链接、锚点全部一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
