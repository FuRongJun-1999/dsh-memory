"""cogmap_sync.py — README 认知图同步管线（零第三方依赖）。

真源（single source of truth）：md_cg/mcp_server.py
  · 工具名  —— TOOLS / KERNEL_TOOLS 两个列表字面量里的 "name" 字段（AST 提取）
  · cg op   —— _cg_dispatch 函数体内的 `if op == "..."` 链
  · stg op  —— _stg_call   函数体内的 `if op == "..."` 链
  · op 实现模块 —— 各 op 分支内的 `from . import X` / `from .X import`（按模块聚合）

投影（generated section）：README.md 的 COGMAP 标记段（段外手写内容零触碰）。

用法（cwd=仓库根）：
  python scripts/cogmap_sync.py check   # 校验 README 投影与真源一致（CI 门禁，退出码 0/1）
  python scripts/cogmap_sync.py build   # 重新生成标记段并写回 README
  python scripts/cogmap_sync.py print   # 仅打印将生成的标记段（不写文件）

校验范围（check）：
  1. 标记段内容 == 按真源重新生成的文本（数字漂移即红灯）
  2. README 全文引用的 cg/stg op、mdcg_* 工具名都存在于真源
  3. README 仓内相对文件链接目标存在
  4. README 页内锚点链接的锚点目标存在（按 GitHub 锚点算法模拟，含跨文件 md 锚点）

纪律：锚点一律「文件路径 + 符号名/章节名」，禁止行号锚（行号随代码漂移）。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "md_cg" / "mcp_server.py"
README = ROOT / "README.md"

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


def _func_source(src_lines: list[str], tree: ast.Module, fname: str) -> str:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == fname:
            return "".join(src_lines[node.lineno - 1 : node.end_lineno])
    return ""


def extract() -> dict:
    src = SERVER.read_text(encoding="utf-8")
    src_lines = src.splitlines(keepends=True)
    tree = ast.parse(src)

    kernel_tools: list[str] = []
    mdcg_tools: list[str] = []
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.List)):
            continue
        targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
        names = [n for n in (_dict_name(el) for el in node.value.elts) if n]
        if "KERNEL_TOOLS" in targets:
            kernel_tools = names
        elif "TOOLS" in targets:
            mdcg_tools = names

    def _ops(fn: str) -> list[str]:
        body = _func_source(src_lines, tree, fn)
        seen: list[str] = []
        for m in re.finditer(r'op\s*==\s*"([a-z_]+)"', body):
            if m.group(1) not in seen:
                seen.append(m.group(1))
        return seen

    cg_ops = _ops("_cg_dispatch")
    stg_ops = _ops("_stg_call")

    # op → 实现模块：把 _cg_dispatch / _stg_call 按 `if op ==` 切块，块内抓 from . import。
    # 键为 (tool, op)：cg 与 stg 存在同名 op（如 consistency），按 op 名聚合会撞行。
    op_modules: dict[tuple[str, str], set[str]] = {}
    for fn, tool in (("_cg_dispatch", "cg"), ("_stg_call", "stg")):
        body = _func_source(src_lines, tree, fn)
        blocks = re.split(r'if\s+op\s*==\s*"[a-z_]+"', body)
        heads = re.findall(r'if\s+op\s*==\s*"([a-z_]+)"', body)
        for op, block in zip(heads, blocks[1:]):
            mods = set(re.findall(r"from \. import (\w+)", block)) | set(
                re.findall(r"from \.(\w+) import", block)
            )
            op_modules.setdefault((tool, op), set()).update(m for m in mods if m not in ("tokens",))

    return {
        "kernel_tools": kernel_tools,
        "mdcg_tools": mdcg_tools,
        "cg_ops": cg_ops,
        "stg_ops": stg_ops,
        "op_modules": op_modules,
    }


# ---------------------------------------------------------------- 投影生成

def _mod_table(e: dict) -> str:
    """op → 实现模块（按工具分组、按模块聚合，减少表行数）。"""
    lines = ["| op | 实现模块 |", "|---|---|"]
    for tool, inline in (("cg", "（`_cg_dispatch` 内联）"), ("stg", "（`_stg_call` 内联）")):
        by_mod: dict[str, list[str]] = {}
        ops = e["cg_ops"] if tool == "cg" else e["stg_ops"]
        for op in ops:
            mods = sorted(e["op_modules"].get((tool, op), set()))
            key = ", ".join(f"`{m}`" for m in mods) if mods else inline
            by_mod.setdefault(key, []).append(f"`{op}`")
        for mods, oplist in sorted(by_mod.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            lines.append(f"| {' '.join(oplist)} | {mods} |")
    return "\n".join(lines)


def render_section(e: dict) -> str:
    cg_n, stg_n = len(e["cg_ops"]), len(e["stg_ops"])
    cg_list = " ".join(f"`{o}`" for o in e["cg_ops"])
    stg_list = " ".join(f"`{o}`" for o in e["stg_ops"])
    mdcg_n = len(e["mdcg_tools"])
    total_tools = len(e["kernel_tools"]) + mdcg_n
    return "\n".join(
        [
            BEGIN,
            "",
            f"**两个认知基元 · {cg_n + stg_n} 个 op**（`kernel` 面）——下列 op 清单与实现模块由 "
            f"[cogmap_sync](scripts/cogmap_sync.py) 从真源自动提取，`check` 门禁守卫漂移：",
            "",
            "| 基元 | op 数 | op 清单 |",
            "|---|---|---|",
            f"| **`cg`** 认知图统一入口 | {cg_n} | {cg_list} |",
            f"| **`stg`** 语义时空图入口 | {stg_n} | {stg_list} |",
            "",
            "**op → 实现模块**（认知图投影：功能在哪段代码，一眼可达）：",
            "",
            _mod_table(e),
            "",
            f"**细粒度面**（`MDCG_MCP_SURFACE=full`，插件运行时使用）：`cg` + `stg` + "
            f"**{mdcg_n} 个 `mdcg_*`** = **{total_tools} 个工具**；逐个 op 的「功能 → 代码 → op」"
            f"行号级映射见[功能调用映射表](docs/功能调用映射表_v0.1.md)。",
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
