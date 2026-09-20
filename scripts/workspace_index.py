#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作区索引生成器与陈化守卫（工作纪律第 18 条的载体）。

背景（第 4 条取证）：agent 每次「了解工作区」都靠 ls / glob 全盘浏览——成本随仓库规模
线性上升，结论还随会话蒸发、下次重来（本仓追踪面已 1814 件）。第 18 条要求先读工作区
索引；本脚本是该索引的**唯一生成入口**与守卫（手工维护必然陈化：「手写行号必腐化」同构）。

数据源：git 追踪面（`git ls-files -z`，NUL 分隔取原始路径）。为什么用 -z：默认
core.quotepath 会把非 ASCII 路径转义成 `"…"` 形态——实测顶层目录统计因此分叉成
`md_cg`(716) 与 `"md_cg`(372) 两项；NUL 分隔规避该形态。副作用是 gitignored 的语料 /
实验产物 / 构建产物天然不进索引，这正是所需（它们是再生产物，不是工作区结构）。

守卫口径（--check，rebuild == have）四项：
  ①顶层目录集合 == 登记表键集（未登记 / 登记但不存在），②根级文件集合同理，
  ③关键入口文件存在，④正文逐字一致（计数 / HEAD / 日期三处归一后比对）。
  计数**不**参与逐字比对：它随任何文件增删而变，纳入会让守卫对每个改动亮红而退化为
  噪声；结构面（目录集合 / 职责文案 / 关键入口）才是索引价值所在。该边界已在文档内
  显式声明——承诺项与守卫面必须一致，否则等同无承诺。

用法：
    python scripts/workspace_index.py            # 干跑（摘要）
    python scripts/workspace_index.py --print    # 干跑并打印全文
    python scripts/workspace_index.py --write    # 落盘
    python scripts/workspace_index.py --check    # 守卫（陈化即退出 1）
退出码：0 一致或写入成功；1 陈化；2 用法错误。

纪律第 15 条：纯 Python 文件读写 + 显式 UTF-8，子进程走 argv 列表不经 shell。
"""
from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
from datetime import datetime

REPO_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC_REL = "WORKSPACE_INDEX.md"
CI_WORKFLOW = ".github/workflows/workspace-index-check.yml"

# —— 职责真源（本脚本即真源；新增顶层目录 / 根级文件必须在此登记，否则 --check 亮红）——
# 值 = (职责一句话, [关键入口，相对本目录；目录名亦可])
DIR_ROLES = {
    "md_cg": ("灵枢大脑——记忆系统本体（纯 md 认知图 + 确定性裁决），即标准 stdio MCP server",
              ["mcp_server.py", "mdcg.py", "mdcos.py"]),
    "rust": ("Rust 检索引擎——只读侧检索内核（零第三方依赖，库内嵌 / --serve / 评测器三形态）",
             ["README.md", "Cargo.toml", "src/lib.rs"]),
    "swarm": ("蜂群运行时——.pbc 确定性实例 + Gossip 拓扑 / 水位信箱 / WAL-HMAC / 信任聚合",
              ["swarm_cli.py", "rust_swarm.py"]),
    "compiler": ("中文（术数）编译器——词法→语法→名实校验→白名单代码生成→验证终裁 + 结构性沙箱",
                 ["api.py", "SEMANTICS.md"]),
    "hive": ("蜂巢并发引擎——worker 池调度（原子领取/心跳/超时强杀/崩溃恢复），文件协议即接口",
             ["README.md", "exec_cmd.py", "exec.py"]),
    "skills": ("灵枢自我认知技能包（管线生成的条件单元投影，随插件分发）",
               ["README.md", "plugin.json"]),
    "src": ("DSH 插件 TypeScript 源码（构建产物落 lib/）",
            ["index.ts", "tools.ts", "bridge.ts"]),
    "dsh": ("DSH profile 配置样例与插件启停脚本",
            ["cordis.yml.example", "dsh-web-start.bat"]),
    "codebuddy": ("CodeBuddy 端纪律注入件（full 变体）与 MCP 配置样例",
                  ["CODEBUDDY.md", "mcp.json"]),
    "zcode": ("ZCode 端纪律注入件（full 变体）", ["AGENTS.md"]),
    "codex": ("Codex CLI 端纪律注入件 + 插件形态（lingshu-memory/）",
              ["AGENTS.md", "lingshu-memory"]),
    "claude": ("Claude Code 端纪律注入件 + 插件形态（lingshu-memory/）",
               ["CLAUDE.md", "lingshu-memory"]),
    "scripts": ("工程管线——纪律渲染/守卫、认知图同步、发布件与常驻进程体检",
                ["render_discipline.py", "verify_discipline.py", "cogmap_sync.py"]),
    "test": ("跨包测试与独立评测脚本（宿主侧 TS 测试 + python 集成）",
             ["mock_mcp.py", "hive_exec_test.py"]),
    "data": ("公开评测数据与裁决留痕",
             ["memory-bench-1000.jsonl", "policy.json"]),
    "docs": ("文档（按工程域分目录，索引见 docs/README.md）",
             ["README.md", "工作纪律_认知图条目_v1.1.json"]),
    ".github": ("CI 门禁（纪律/认知图/蜂巢/conformance/安装/发布件/python 测试）",
                ["workflows"]),
    ".claude-plugin": ("Claude 插件市场清单（/plugin marketplace add 入口）",
                       ["marketplace.json"]),
    ".agents": ("Codex 插件市场清单（codex plugin marketplace add 入口）",
                ["plugins"]),
}

# 根级文件（同上：未登记即亮红）
ROOT_FILES = {
    "README.md": "对外主入口（定位 / 核心亮点 / 平台全景 / 接入 / 评测 / 纪律）",
    "LICENSE": "许可",
    "package.json": "npm 包清单（@furongjun1999/dsh-memory，bin 入口与脚本）",
    "package-lock.json": "npm 锁文件（npm ci 可复现）",
    "tsconfig.json": "TypeScript 编译配置（src/ → lib/）",
    "memory_score.md": "AGI 七维评分说明",
    "discussion-post.md": "对外讨论帖留档",
    ".gitignore": "忽略面（本地数据面 / 实验产物 / 构建产物）",
}

# 定位提示（静态真源，参与逐字校验；只写跨目录的「去哪找」）
HINTS = [
    ("找纪律本体", "`docs/工作纪律_认知图条目_v1.1.json`——唯一手写真源；"
                   "各端产物由 `scripts/render_discipline.py` 渲染、`scripts/verify_discipline.py` 守漂移"),
    ("找记忆能力实现", "`md_cg/mcp_server.py`（cg / stg 工具面）→ `md_cg/mdcg.py`（引擎）→ `md_cg/mdcos.py`（检索）"),
    ("找公开评测口径", "`README.md`（对外数字）→ `data/`（数据集）→ `md_cg/bench_*.py`（复现脚本）"),
    ("找蜂巢派发契约", "`hive/exec_cmd.py`（确定性命令）/ `hive/exec.py`（LLM 委托），spec 进 result 出"),
    ("找本次改动该动哪", "`docs/README.md`（文档归域规则）· 本页第一节（目录职责）"),
]


# ---------------------------------------------------------------- 基础工具

# 生效条件：当 git 可用且 repo 是工作树时返回追踪路径列表（NUL 分隔取原始路径）；git 返回非 0 时抛 RuntimeError。
def tracked(repo):
    """git 追踪面（NUL 分隔取原始路径，规避 core.quotepath 转义）。"""
    p = subprocess.run(["git", "ls-files", "-z"], cwd=repo, shell=False,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONUTF8": "1"})
    if p.returncode != 0:
        raise RuntimeError("git ls-files 失败：%s" % (p.stderr or "").strip())
    return [x for x in (p.stdout or "").split("\0") if x]


# 生效条件：git rev-parse 成功时返回短 HEAD（7+ 位），失败返回 "unknown"。
def head_sha(repo):
    try:
        p = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, shell=False,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**os.environ, "PYTHONUTF8": "1"})
        return (p.stdout or "").strip() or "unknown"
    except OSError:
        return "unknown"


# 生效条件：返回 (files, tops, roots)——files 为全量追踪路径（含本页自身若已被追踪）；tops 为 {顶层目录: 件数}；roots 为根级文件排序列表（恒排除 DOC_REL，故首次生成与已追踪两态一致）。
def scan(repo):
    files = tracked(repo)
    tops, roots = {}, []
    for f in files:
        if f == DOC_REL:
            continue  # 本页自身不计入（首次生成时尚未被追踪，排除后两态自洽）
        if "/" in f:
            tops[f.split("/")[0]] = tops.get(f.split("/")[0], 0) + 1
        else:
            roots.append(f)
    return files, tops, sorted(roots)


# 生效条件：对任意 text 返回把 HEAD 指纹 / 追踪件数 / 生成日期 / 表格计数列四处替换为占位符后的 strip 文本。
def _norm(text):
    text = re.sub(r"HEAD `[0-9a-fA-F]{4,40}`", "HEAD `<sha>`", text)
    text = re.sub(r"追踪 \*{0,2}\d+\*{0,2} 件", "追踪 <n> 件", text)
    text = re.sub(r"生成于 \d{4}-\d{2}-\d{2}", "生成于 <date>", text)
    text = re.sub(r"\| \d+ \|", "| <n> |", text)
    return text.strip()


# 生效条件：对 entries（字符串列表）返回反引号包裹、顿号连接的一行文本。
def _entries(entries):
    return " · ".join("`%s`" % e for e in entries)


# 生效条件：对 files 全集检查 DIR_ROLES 各项的关键入口与 ROOT_FILES 各键是否存在（目录形态以路径前缀判定），返回缺失项排序列表。
def missing_entries(files):
    have = set(files)
    bad = []
    for d, (_role, entries) in DIR_ROLES.items():
        for e in entries:
            rel = "%s/%s" % (d, e)
            if rel in have or any(f.startswith(rel + "/") for f in have):
                continue
            bad.append(rel)
    bad += [f for f in ROOT_FILES if f not in have]
    return sorted(bad)


# ---------------------------------------------------------------- 渲染

# 生效条件：以 repo 的追踪面生成全文；now 为假值时取当前时间。结构面异常（未登记 / 登记但不存在）以标记行显式出现在表内，故「重建 == 磁盘」不掩盖结构变化——结构面由 check() 独立裁决。
def render(repo, now=None):
    now = now or datetime.now()
    files, tops, roots = scan(repo)
    sha = head_sha(repo)
    unreg_dirs = [d for d in sorted(tops) if d not in DIR_ROLES]
    miss_dirs = [d for d in DIR_ROLES if d not in tops]

    L = []
    L.append("<!-- 本文件由 scripts/workspace_index.py 生成；请勿手改，改后跑 "
             "`python scripts/workspace_index.py --write` 重生成 -->")
    L.append("")
    L.append("# 工作区索引（WORKSPACE_INDEX）")
    L.append("")
    L.append("> **为什么有这一页**：查工作区文件前先读本页——按目录职责与关键入口定位，"
             "替代每次重复全盘浏览（**工作纪律第 18 条**）。")
    L.append("> **数据源**：git 追踪面（`git ls-files`，NUL 分隔取原始路径）；"
             "gitignored 的语料 / 实验产物 / 构建产物不在其内。")
    L.append("> **生成 / 守卫**：`python scripts/workspace_index.py --write` ｜ "
             "`--check`（CI：`%s`）。" % CI_WORKFLOW)
    L.append("> **快照**：HEAD `%s` · 追踪 **%d** 件 · 生成于 %s —— "
             "计数与 HEAD 为生成时快照，**不参与守卫校验**；守卫校验的是："
             "①顶层目录集合 ②根级文件集合 ③职责文案与关键入口 ④正文（归一化后）逐字一致。"
             % (sha, len(files), now.strftime("%Y-%m-%d")))
    L.append("")
    L.append("## 一、顶层目录")
    L.append("")
    L.append("| 目录 | 职责 | 追踪件数 | 关键入口 |")
    L.append("|---|---|---|---|")
    for d, (role, entries) in DIR_ROLES.items():
        if d in tops:
            L.append("| `%s/` | %s | %d | %s |" % (d, role, tops[d], _entries(entries)))
        else:
            L.append("| `%s/` | %s | — | **目录缺失**（已登记但仓库内不存在） |" % (d, role))
    for d in unreg_dirs:
        L.append("| `%s/` | **未登记**——请在 `scripts/workspace_index.py` 的 `DIR_ROLES` "
                 "补职责与关键入口后重生成 | %d | — |" % (d, tops[d]))
    L.append("")
    L.append("## 二、根级文件")
    L.append("")
    L.append("| 文件 | 内容 |")
    L.append("|---|---|")
    for f, desc in ROOT_FILES.items():
        mark = "" if f in roots else " **缺失**（已登记但仓库内不存在）"
        L.append("| `%s` | %s%s |" % (f, desc, mark))
    for f in roots:
        if f not in ROOT_FILES:
            L.append("| `%s` | **未登记**——请在 `scripts/workspace_index.py` 的 "
                     "`ROOT_FILES` 补说明后重生成 |" % f)
    L.append("")
    L.append("## 三、定位提示")
    L.append("")
    for k, v in HINTS:
        L.append("- **%s** → %s" % (k, v))
    L.append("")
    L.append("---")
    L.append("")
    L.append("本页由 `scripts/workspace_index.py` 从 git 追踪面机械生成，不在上表计数内。"
             "新增顶层目录或根级文件时，守卫会亮红并点名未登记项——"
             "登记到脚本的真源后重生成即恢复一致（**手工编辑本页会在下一次守卫时被判陈化**）。")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- 守卫

# 生效条件：重建文本与磁盘文本归一后比对，且逐项裁决结构面（未登记目录 / 登记但不存在 / 未登记根文件 / 登记但不存在 / 关键入口缺失），返回 {"ok", "drift":[...], "stats":{...}}。
def check(repo):
    path = os.path.join(repo, DOC_REL)
    files, tops, roots = scan(repo)
    drift = []

    for d in sorted(tops):
        if d not in DIR_ROLES:
            drift.append("未登记目录：`%s/`（%d 件）——请在 DIR_ROLES 登记后重生成" % (d, tops[d]))
    for d in DIR_ROLES:
        if d not in tops:
            drift.append("登记但不存在：`%s/`——目录已删或改名，请更新 DIR_ROLES" % d)
    for f in roots:
        if f not in ROOT_FILES:
            drift.append("未登记根级文件：`%s`——请在 ROOT_FILES 登记后重生成" % f)
    for f in ROOT_FILES:
        if f not in roots:
            drift.append("登记但不存在：`%s`——文件已删或改名，请更新 ROOT_FILES" % f)
    for rel in missing_entries(files):
        drift.append("关键入口缺失：`%s`——请修正 DIR_ROLES / ROOT_FILES 的入口表" % rel)

    if not os.path.isfile(path):
        drift.append("索引缺失：`%s` 不存在——跑 --write 生成" % DOC_REL)
    else:
        with io.open(path, encoding="utf-8") as fh:
            have = fh.read()
        if _norm(have) != _norm(render(repo)):
            drift.append("正文陈化：`%s` 与重建文本不一致（归一化后仍不同）——跑 --write 重生成" % DOC_REL)

    return {"ok": not drift, "drift": drift,
            "stats": {"dirs": len(tops), "tracked": len(files), "entries": len(missing_entries(files))}}


# 生效条件：argv 为 None 时 argparse 从 sys.argv 解析，否则解析给定 argv；--write 落盘并打印摘要返回 0，--check 按 check() 的 ok 返回 0/1，二者皆无时干跑打印摘要（--print 附全文）返回 0。
def main(argv=None):
    ap = argparse.ArgumentParser(description="工作区索引生成器与陈化守卫（工作纪律第 18 条）")
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--write", action="store_true", help="落盘生成 %s" % DOC_REL)
    ap.add_argument("--check", action="store_true", help="守卫：陈化即退出 1")
    ap.add_argument("--print", dest="do_print", action="store_true", help="干跑并打印全文")
    args = ap.parse_args(argv)

    repo = os.path.abspath(args.repo)
    if args.check:
        res = check(repo)
        s = res["stats"]
        if res["ok"]:
            print("[OK  ] 工作区索引与仓库一致（顶层目录 %d · 追踪 %d 件）"
                  % (s["dirs"], s["tracked"]))
        else:
            for d in res["drift"]:
                print("[DRIFT] " + d)
            print("")
            print("结论：陈化 %d 处；修复：python scripts/workspace_index.py --write" % len(res["drift"]))
        return 0 if res["ok"] else 1

    text = render(repo)
    path = os.path.join(repo, DOC_REL)
    if args.write:
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("已写入 %s（%d 字节）" % (DOC_REL, len(text.encode("utf-8"))))
        return 0

    files, tops, _roots = scan(repo)
    print("干跑：顶层目录 %d · 追踪 %d 件 · 渲染 %d 行（目标 %s）"
          % (len(tops), len(files), text.count("\n") + 1, DOC_REL))
    if args.do_print:
        print("")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
