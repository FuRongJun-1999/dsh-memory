#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""工作纪律 · 漂移守卫（双向比对：真源 ↔ 各 harness 产物）

正向（真源 → 产物）：每条纪律的 semantic / 动作 / 声明 必须出现在产物中。
反向（产物 → 真源）：产物里出现的每一条「按工作纪律第 N 条」声明，必须能在真源里找到；
                     出现真源没有的声明即判为孤儿（手抄残留 / 旧版本）。

硬失败（与 .github/workflows/discipline-check.yml:4 同源，任一命中即 exit 1）：
  产物缺失 / 孤儿声明 / 工具名未随端标注 / 产物陈化——陈化面含两条：渲染产物**缺**内嵌
  真源指纹（N253：渲染链路写出的件必有模板指纹行，缺了即非渲染产物或被人手改），或
  内嵌指纹 ≠ 当前真源指纹；仅 render:false 的真·手工投影允许无指纹（其漂移由字段级
  逐字比对兜底）。
指针型渲染产物（render 非 false 的 pointer 目标，2026-10-05 裁决① zcode-user）另有
  第四检：extract 文本与重渲染结果逐字一致——手改表行 / 指纹 / 指向 / 任意正文即判漂移。
分发面计数（2026-10-07）另有第五检：手写分发描述（插件清单 / 各端 README）里的
  「N 条工作纪律」计数须等于真源 subgraph.nodes 条数（**期望值从真源现算，不硬编码**）；
  `第 N 条工作纪律` 这类**引用**不在判据内（基底 (?<!\d)(\d+)\s*条工作纪律 ＋「第」前缀排除）。

认知图投影节点腿（A2 使用者裁决 2026-10-05）：本案还有一腿校验「真源 ↔ 认知图
structural/ 下 discipline:N 投影节点」的一致性，它需要显式 root（--cg-root / MDCG_ROOT）：
  未提供 / 提供但不存在 / 存在但非认知图 三态**一律 fail-closed（退出码 2）**——
此前「未提供」即静默 [SKIP] 退 0，判据体在全部自动化面从未执行；skipped 一律不计通过。
四个自动化面（package.json gate / discipline-check.yml / verify_linux.sh / git-hooks）
各自先 `discipline_nodes.py --write --init --cg-root .tmp/discipline-cg` 建最小库再显式传根。

用法：
    python scripts/verify_discipline.py                 # 默认校验 enabled 目标
    python scripts/verify_discipline.py --cg-root <root>  # 投影节点腿的执行面（缺失/无效即退 2）
    python scripts/verify_discipline.py --target codebuddy --allow-missing   # 干跑比对（产物未生成时不报错）
    python scripts/verify_discipline.py --json
退出码：0 全部一致；1 存在漂移或缺失；2 用法错误 / 认知图 root 缺失或无效（fail-closed）。
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_discipline as R  # noqa: E402
import discipline_nodes as DN  # noqa: E402

DECL_RE = re.compile(r"按工作纪律第\s*(\d+)\s*条")

# —— 分发面计数守卫（2026-10-07）——
# 手写的分发描述（插件清单 / 各端 README）长期写死**旧计数 16**，而真源 subgraph.nodes 已
# 是 18 条、渲染产物（SKILL.md / AGENTS.md 等）也自称 18——这些手写面不在渲染/指纹矩阵内，
# 门禁全绿而文案陈旧（与「手写行号必腐化」同构：无守卫的手写计数必然漂移）。
# 期望值**从真源现算**（len(subgraph.nodes)），不硬编码，免得真源再变时守卫自己陈化。
# 判据 = 计数用法「N 条工作纪律」须等于真源条数；**不误伤**「第 N 条工作纪律」这类**引用**。
# 为什么不是字面 (?<!第)(\d+)：定长 lookbehind 挡不住「第 16 条」（第与数字间有空白），
# 且不挡「第16条」从 '6' 起起步（多位数被拆）——实测两者都会误报（16 / 6）。故：
#   ① 基底用 (?<!\d) 防多位数被拆；② 「第…条」引用在 count_claims 里按匹配前缀判尾字「第」排除。
# 扫描面限定「面向接入者的手写分发描述」——插件清单 + README。**不扫 docs/**：那里有历史快照
# 与缺陷审计记录，会**引述**旧计数（写在文字里的历史 N 值），纳入判据即误伤记录本身
# （改记录 = 篡改审计）。渲染产物一侧的陈化由既有指纹腿兜底，本腿只管手写描述。
COUNT_RE = re.compile(r"(?<!\d)(\d+)\s*条工作纪律")
COUNT_SCAN_GLOBS = (
    "README.md",
    "*/README.md",
    "*/*/README.md",
    "**/.claude-plugin/*.json",
    "**/.codex-plugin/*.json",
    "**/.agents/plugins/*.json",
)
COUNT_SCAN_SKIP_DIRS = ("node_modules", ".git", "__pycache__", ".mypy_cache", ".pytest_cache")

# —— 工具名随端标注守卫（20260916 漂移实例的机械捕获器）——
# 纪律件里出现的 DSH 端基元注册名；宿主内建桥端（memory 以 plugin/ 开头）该名即本端正名，豁免。
TOOLNAME_DSH = ("lingshu_cg", "lingshu_stg")
MCP_CANON = "mdcg"

# —— 逐字比对字段（默认全部 strict；target 可用 verify_fields 把个别字段降为 advisory）——
# 历史缺陷（20260916 第二例）：原实现只比 动作/声明 两栏，而根注入件序言承诺的
# 「编号 / 触发 / 不适用 / 声明出口」四项中，触发与不适用两栏**完全无守卫**——
# 承诺项无守卫即等同无承诺（与「手写行号必腐化」同构）。
# N258（2026-10-05）：本文件 docstring 承诺「每条纪律的 semantic / 动作 / 声明 必须
# 出现在产物中」，但 FIELD_ORDER 只含 trigger/action/negative/declaration——渲染器
# 写出的「N. 语义」标题**零判据**（产物副本里第 3 条标题被替换/删除，check() 仍
# ok=True）。补入 semantic：取值与渲染器 _title 单点同源（去数字前缀后的语义文本；
# 产物里「N. 语义」标题均含该文本，子串判据可覆盖，且不重复钉标题号码格式）。
FIELD_LABEL = {"semantic": "语义", "trigger": "触发", "action": "动作", "negative": "不适用", "declaration": "声明"}
FIELD_ORDER = ("semantic", "trigger", "action", "negative", "declaration")


# 生效条件：n 为纪律节点、key 为 "semantic" 时返回去数字前缀后的 n["semantic"]（缺键回落 n["id"]），key 为 "action"/"declaration" 时返回 str(n 的 execution.how / response.direct，缺键回落 "")，key 为 "trigger"/"negative" 时返回 R._list_or(n 的 conditions.apply / negative.reject，默认文本「（无前置条件，始终适用）」/「（无）」)，key 为其它值时抛 KeyError(key)。
def field_value(n, key):
    """取该条纪律在指定字段上的『渲染口径』文本（与 render_discipline 生成产物同源）。"""
    if key == "semantic":
        # 与渲染器 _title 单点同源：去掉「N. 」数字前缀（产物标题是「N. <语义>」，
        # 子串判据对去前缀形态最稳——标题被替换/删除即判缺失；号码格式不重复钉）
        return R._NUM_PREFIX.sub("", str(n.get("semantic", n["id"])))
    if key == "action":
        return str((n.get("execution") or {}).get("how", ""))
    if key == "declaration":
        return str((n.get("response") or {}).get("direct", ""))
    if key == "trigger":
        return R._list_or((n.get("conditions") or {}).get("apply"), "（无前置条件，始终适用）")
    if key == "negative":
        return R._list_or((n.get("negative") or {}).get("reject"), "（无）")
    raise KeyError(key)


# 生效条件：对任意 s（含非字符串）先 str(s)、再以 re.sub(r"\s+"," ") 折叠空白并 strip() 返回单行文本，s 为空串或纯空白时返回 ""。
def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip()


# 生效条件：target["transport"] == "file" 时按 R.expand(target["path"], repo) 读该文件，路径不是常规文件则返回 (None,"未生成："+path)，是则返回 (全文, path)；transport 非 "file" 时改调 R.read_config_key(target, repo)，其 text 为 None 则返回 (None,"未找到受管块："+R.expand(target["path"], repo))，否则返回 (text, R.expand(target["path"], repo))。
def extract(target, repo):
    """返回 (text, source_desc) 或 (None, 说明)"""
    if target.get("transport") == "file":
        path = R.expand(target["path"], repo)
        if not os.path.isfile(path):
            return None, "未生成：" + path
        with io.open(path, encoding="utf-8") as f:
            return f.read(), path
    text, _eol = R.read_config_key(target, repo)
    if text is None:
        return None, "未找到受管块：" + R.expand(target["path"], repo)
    return text, R.expand(target["path"], repo)


# 生效条件：target 为假值或矩阵未声明 render 键时一律返回 False（按「机器渲染」处理，保守）；仅 render 显式为 False 时返回 True。
def is_manual_target(target) -> bool:
    """该 target 是否为**手工投影**（矩阵声明 `render: false`，渲染链路不写它）。

    单点判据（与 check_injection_matrix 的「含 render:false 手工件」口径同源）；
    缺声明不等于豁免——真值/缺键一律按「机器渲染」处理（N253：只有真·手工件
    才允许无内嵌指纹，详见 check() 的陈化面）。
    """
    return (target or {}).get("render", True) is False


# 生效条件：str(target 的 memory or "") 以 "plugin/" 开头时直接返回 []（memory 缺失或为假值经 or 归一为 ""，不豁免）；否则逐行扫 text，含 TOOLNAME_DSH 任一名称且不含 MCP_CANON 的行按 1 起行号与 strip 后前 100 字符记入返回列表，无命中返回 []。
def check_tool_alignment(text, target):
    """工具名随端标注守卫：MCP 端件里出现的 DSH 端注册名，必须与 MCP 端正名同行。

    历史缺陷（20260916）：根注入件 AGENTS.md 手工维护、长期不在渲染/校验矩阵内，把 DSH 端的
    `lingshu_cg` 写死为「工具全名」并加「非 cg」的反向否决，本端 agent 因此对工具名产生疑惑。
    根因与「手写行号必腐化」同构——无守卫的手工件必然漂移。
    判据：该端 memory 声明为宿主内建桥（plugin/…）时，`lingshu_cg` 就是本端注册名，无标注义务。
    """
    if str(target.get("memory") or "").startswith("plugin/"):
        return []
    bad = []
    for ln, line in enumerate(text.splitlines(), 1):
        if any(t in line for t in TOOLNAME_DSH) and MCP_CANON not in line:
            bad.append({"line": ln, "text": line.strip()[:100]})
    return bad


# 生效条件：out["ok"] 仅当 names 中各 target 经 R.expand 归一化后的路径键无重复（path_dups 为空）且仓根槽位件未遮蔽 root_allow 中本地件（root_shadow 为空）时为 True；probe_chain 为假值时第三段祖先链发现整段跳过（probed 仍为 0），为真时对每个 file target 采集 dedup/wt_dups/hits。
def check_injection_matrix(mx, repo, names, probe_chain=True):
    """Pi⑦⑤ 注入面发现 + 防重复（矩阵 injection: 段声明，本函数裁决）。

    硬失败（本仓自身的问题，机械可裁决 —— 计入 bad）：
      path_dup    两个 target 归一化后指向同一物理文件（或同一 config 键）
                  → 后渲染者静默覆盖前者；若其一是 render:false 的手工件则更严重（手改被覆盖）
      root_shadow 仓根出现会**遮蔽本地私有件**的槽位件（宿主按声明的择优顺序读取）
                  → 本地纪律注入在该宿主下不生效（本文件 §5 明文那条纪律的机械化）

    发现面（只报告，不判失败）：每条 file target 的**祖先链**上的同槽位件。
      宿主从启动目录逐级上溯读同名件，仓外命中（用户 home / 父目录的 AGENTS.md 等）是宿主侧
      事实——本仓无权裁决，但**必须被看见**（Pi⑦⑤ 的原始动机就是「假定不存在」导致重复注入）。
      worktree / junction / 别名下同一**物理目录**在链上出现两次时，按物理身份折叠（dedup），
      不把同一份件误报两份；同仓但物理不同的份（各 worktree 各自 checkout）只标注不折叠。
    """
    conf = R.injection_conf(mx)
    slots = conf.get("slots") or {}
    root_allow = [str(x) for x in (conf.get("root_allow") or [])]
    targets = mx.get("targets", {})
    out = {"ok": True, "path_dups": [], "root_shadow": [],
           "chains": [], "dedup": [], "wt_dups": [], "probed": 0}

    # ① 同一物理文件被两个 target 写：键 = 归一化路径（+ config 键的 entry_id）
    by_key = {}
    for name in names:
        t = targets.get(name) or {}
        try:
            tpath = R.expand(t["path"], repo)
        except (KeyError, TypeError):
            continue
        key = R.norm_path(tpath)
        if t.get("transport") != "file":
            key += "#" + str(t.get("entry_id") or "")
        by_key.setdefault(key, []).append(name)
    for key, group in sorted(by_key.items()):
        if len(group) > 1:
            manual = [n for n in group if (targets.get(n) or {}).get("render", True) is False]
            out["path_dups"].append({"key": key, "targets": sorted(group),
                                     "manual": sorted(manual)})

    # ② 仓根遮蔽：仓根存在槽位件 F，且声明顺序里 F 排在本地私有件 L 之前，且 L 也在仓根
    for slot, files in (slots or {}).items():
        files = [str(x) for x in (files or [])]
        present = [fn for fn in files if os.path.isfile(os.path.join(repo, fn))]
        for fn in present:
            for allow in root_allow:
                if fn == allow or allow not in files or allow not in present:
                    continue
                if files.index(fn) < files.index(allow):
                    out["root_shadow"].append({
                        "slot": slot, "winner": fn, "loser": allow,
                        "path": os.path.join(repo, fn)})

    # ③ 祖先链发现（报告面）：逐 file target 走祖先目录，收集同槽位竞争件
    for name in names:
        t = targets.get(name) or {}
        if not probe_chain:
            continue
        t = dict(t, _name=name)
        chain = R.discover_injection_chain(t, repo, mx)
        if not chain.get("slot"):
            continue
        out["probed"] += 1
        for kind in ("dedup", "wt_dups"):
            for d in chain.get(kind) or []:
                out[kind].append(dict(d, target=name))
        if chain["hits"]:
            out["chains"].append(dict(chain, target=name,
                                      shadowed=[h["path"] for h in chain["hits"]
                                                if h["rank"] < h["self_rank"]]))

    out["ok"] = not out["path_dups"] and not out["root_shadow"]
    return out


# 生效条件：text 给定，返回 [{"line":行号,"n":整数,"text":折叠空白后前120字}]——按 COUNT_RE 逐行
# 找「N 条工作纪律」计数用法；匹配前缀去空白后以「第」收尾的（即「第 N 条工作纪律」这类**引用**）
# 一律跳过（不误伤）。本函数不做数值判断。
def count_claims(text):
    out = []
    for ln, line in enumerate(text.splitlines(), 1):
        for m in COUNT_RE.finditer(line):
            if line[:m.start()].rstrip().endswith("第"):
                continue
            out.append({"line": ln, "n": int(m.group(1)), "text": norm(line)[:120]})
    return out


# 生效条件：repo 给定，按 COUNT_SCAN_GLOBS 逐模式 glob（相对仓根拼接），保留命中
# **git 追踪面**的普通文件（非追踪件不入面），去重后返回排序的绝对路径列表。
def count_scan_files(repo):
    """分发面计数扫描面 = 文件系统 glob ∩ **git 追踪面**。

    判据面锚在**追踪面**而非文件系统面：本地 gitignore 产物（`.tmp/` 草稿、
    `node_modules/` 等）不在 CI 干净克隆里，纳入即「本地红 / CI 绿」分裂。
    按「是否被 git 追踪」这个**性质**判，**不**逐个硬编码排除目录——`.tmp` 曾以
    「硬编码跳过目录名」绕过（正是本类要消灭的写法），现改由追踪面判据覆盖。
    （实测：`.tmp` 等点开头目录本就不被 glob 的 `*`/`**` 匹配，故该口径对本仓是
    等价收紧；本机以 `*/*/README.md` 命中的 `node_modules/*` 为例，改后同样被
    追踪面挡住。）
    降级（明示，非静默改语义）：git 不可用/非仓 ⇒ 退回原「按目录名跳过」口径并
    打印 `[降级]` 一行，读数须按降级看待。
    """
    tracked = _tracked_rels(repo)
    if tracked is None:
        # 走 **stderr**：本脚本有 `--json`（stdout 须是纯 JSON，供 test_discipline_*
        # 等消费方 json.loads）。若把 [降级] 打到 stdout，`--repo <非 git 临时仓>`
        # 场景下 JSON 前多一行、json.loads 直接崩（N253 守卫 S2–S6 首现该形态）。
        print("[降级] git 不可用：分发面计数扫描面退化为文件系统 glob 走查"
              "（可能与 CI 干净克隆不一致）", file=sys.stderr)
    seen, out = set(), []
    for pat in COUNT_SCAN_GLOBS:
        for path in glob.glob(os.path.join(repo, *pat.split("/")), recursive=True):
            rp = os.path.relpath(path, repo).replace(os.sep, "/")
            if tracked is None:
                if any(seg in COUNT_SCAN_SKIP_DIRS for seg in rp.split("/")):
                    continue
            elif rp not in tracked:
                continue                    # 非追踪件不入判据面
            if os.path.isfile(path) and path not in seen:
                seen.add(path)
                out.append(path)
    return sorted(out)


# 生效条件：repo 给定，执行 git ls-files -z，成功 ⇒ 返回仓根相对（posix 分隔）的追踪面集合；git 不可用/非仓（非零退出或 OSError）⇒ 返回 None（调用方明示降级）。
def _tracked_rels(repo):
    """git 追踪面（仓根相对 · posix 分隔）集合；git 不可用/非仓 ⇒ None（调用方降级）。"""
    try:
        proc = subprocess.run(["git", "-C", repo, "ls-files", "-z"],
                              capture_output=True, check=True)
    except Exception:                                  # noqa: BLE001 —— 兜底见上
        return None
    return {p.replace("\\", "/") for p in
            proc.stdout.decode("utf-8", "replace").split("\0") if p}


# 生效条件：repo 给定，期望 = len(R.nodes_of(R.load_source(repo)))**（真源现算，不硬编码）**；
# 扫描 count_scan_files(repo) 命中的每个仓内文本，凡 count_claims 出的 N != 期望即记一条 drift；
# 扫描面为空（一个文件都没命中）按「判据体未执行」判失败（fail-closed，防守卫塌陷为恒绿）。
# 返回 {"ok","expected","scanned","claims","drift","reason"}。
def check_discipline_count(repo):
    """分发面计数守卫：手写描述里的「N 条工作纪律」须等于真源条数。"""
    expected = len(R.nodes_of(R.load_source(repo)))
    drift, scanned, claims = [], 0, 0
    for path in count_scan_files(repo):
        try:
            with io.open(path, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        rel = os.path.relpath(path, repo).replace(os.sep, "/")
        for c in count_claims(text):
            claims += 1
            if c["n"] != expected:
                drift.append({"file": rel, "line": c["line"], "n": c["n"], "text": c["text"]})
    return {"ok": (not drift and scanned > 0), "expected": expected, "scanned": scanned,
            "claims": claims, "drift": drift,
            "reason": ("分发面扫描面为空（COUNT_SCAN_GLOBS 未命中任何文件）——判据体未执行"
                       if scanned == 0 else None)}


# 生效条件：extract(target, repo) 取不到文本时 res["skipped"]=True、res["ok"]=bool(allow_missing) 并立即返回；取到文本时 res["ok"] 仅当 missing、orphans、toolname、stale 均为空/假时为 True，其中 target 的 verify_fields 中值为 "advisory" 的字段记入 advisory 而非 missing，且空串或已出现在 norm(text) 中的字段值不参与比对。
def check(target, src, repo, allow_missing):
    nodes = R.nodes_of(src)
    text, where = extract(target, repo)
    res = {"target": target.get("_name"), "variant": target.get("variant"),
           "transport": target.get("transport"), "artifact": where,
           "missing": [], "advisory": [], "orphans": [], "ok": True, "skipped": False}
    if text is None:
        res["skipped"] = True
        res["ok"] = bool(allow_missing)
        return res

    # 指针型产物（target.pointer 为真，2026-09-28 登记 zcode-user）：本件**不含条款正文**
    # （只指向纪律本体文件 + 执行公约摘要）⇒ 字段级 strict 比对在此物理上不适用（会报满屏
    # 「缺失」而掩盖真问题）。判据换成四条检查：
    #   ①指向面：须给出纪律本体的仓内路径（zcode/AGENTS.md）——路径写错/删掉即硬失败；
    #   ②陈化面：内嵌真源指纹须等于当前真源指纹——改真源未更新指针即硬失败（与渲染产物同判据）；
    #   ③工具名随端：复用既有 check_tool_alignment（同一判据函数，不另立一套）。
    # ④全文一致（2026-10-05 使用者裁决①）：本件已由手写指针升级为**渲染产物**
    #   （render: true + variant zcode-user），手改表行 / 指纹 / 指向 / 任意正文必须判漂移——
    #   判据 = extract 文本与 R.render(target, src, repo) 逐字比对。两侧仅归一**末尾**空白/
    #   换行（extract 走 universal newlines，EOL 已归一到 "\n"）；逐字比较不得放水，否则
    #   「用户级注入面与模板各说各话」而两边都判绿。仅对**非 render:false** 的 pointer 目标
    #   成立：真·手工指针（render:false）没有渲染基准可比，不设此检（其漂移靠 ①②③）。
    # 为什么不是「render:false 就不查」：无守卫的手工件必然漂移（20260916 codebuddy-local 实例
    # 的教训），指针件同样需要一个机械守卫，只是判据面不同。
    if target.get("pointer"):
        body_ptr = norm(text)
        # 单据单一事实源：指向的纪律本体路径由矩阵声明（pointer_body），不在判据里写死
        tgt_body = target.get("pointer_body") or "zcode/AGENTS.md"
        ptr_ok = tgt_body in body_ptr
        m_ptr = re.search(r"前16位[）：:]*\s*([0-9a-f]{16})", text)
        res["artifact_sha"] = m_ptr.group(1) if m_ptr else None
        res["source_sha"] = R.source_sha(repo)
        res["stale"] = bool(m_ptr) and res["artifact_sha"] != res["source_sha"]
        res["toolname"] = check_tool_alignment(text, target)
        res["pointer_checks"] = {"body_path": ptr_ok,
                                 "fingerprint": res["artifact_sha"],
                                 "source": res["source_sha"]}
        if not ptr_ok:
            res["missing"].append({"no": 0, "field": "指向", "key": "pointer_target",
                                   "id": "-", "text": "指针未指向 " + tgt_body})
        if not m_ptr:
            res["missing"].append({"no": 0, "field": "指纹", "key": "pointer_sha",
                                   "id": "-",
                                   "text": "指针未内嵌真源指纹（形如「前16位）：<16 hex>」）"
                                           "——无指纹即无法判陈化"})
        # ④全文与重渲染逐字一致（见上方判据注释；仅非 render:false 的 pointer 目标）
        if not is_manual_target(target):
            rendered = R.render(target, src, repo)
            render_match = rendered.rstrip() == text.rstrip()
            res["pointer_checks"]["render_match"] = render_match
            if not render_match:
                res["missing"].append({
                    "no": 0, "field": "全文", "key": "render_match", "id": "-",
                    "text": "本件为渲染产物（variant=%s）：全文与重渲染结果逐字不一致——手改"
                            "表行 / 指纹 / 指向 / 任意正文均判漂移；请重跑 "
                            "`python scripts/render_discipline.py --target %s --write`"
                            % (target.get("variant"), target.get("_name") or "?")})
        res["ok"] = (not res["missing"] and not res["toolname"] and not res["stale"])
        return res

    # 字段级判据：默认 strict；target 的 verify_fields 可把某字段降为 advisory
    # （降级只对「清单/摘要形态的手工件」成立，且差异仍全量打印——不静默）。
    vf = target.get("verify_fields") or {}
    advisory_keys = {k for k, v in vf.items() if str(v).lower() == "advisory"}

    body = norm(text)
    for i, n in enumerate(nodes, 1):
        for key in FIELD_ORDER:
            val = field_value(n, key)
            if not val or norm(val) in body:
                continue
            rec = {"no": i, "field": FIELD_LABEL[key], "key": key,
                   "id": n["id"], "text": norm(val)[:80]}
            (res["advisory"] if key in advisory_keys else res["missing"]).append(rec)

    known = set()
    for n in nodes:
        d = norm((n.get("response", {}) or {}).get("direct", ""))
        m = DECL_RE.search(d)
        if m:
            known.add(int(m.group(1)))
    found = set(int(m.group(1)) for m in DECL_RE.finditer(body))
    unknown = sorted(found - known)
    if unknown:
        res["orphans"] = unknown
        for no in unknown:
            snippet = ""
            for line in text.splitlines():
                if DECL_RE.search(line) and ("第 %d 条" % no) in line or ("第%d条" % no) in line:
                    snippet = line.strip()[:100]
                    break
            res["orphans"] = res.get("orphans")
        res["orphan_detail"] = [{"no": no} for no in unknown]

    # 陈化检查：产物内嵌的真源指纹 vs 当前真源指纹（改真源未重渲染）
    m = re.search(r"前16位[）：:]*\s*([0-9a-f]{16})", text)
    res["artifact_sha"] = m.group(1) if m else None
    res["source_sha"] = R.source_sha(repo)
    res["stale"] = bool(m) and res["artifact_sha"] != res["source_sha"]

    # N253（2026-10-05，high）：**机器渲染目标缺内嵌指纹 = 硬失败**（与指针分支 :207-211 同判据）。
    # 修前「无指纹 ⇒ m 为空 ⇒ stale=False ⇒ ok=True」：陈化这一项（discipline-check.yml:4 自陈的
    # 四项硬失败之一）可被四种形态静默绕过——删行 / 大写（或混合大小写）十六进制 / 空白插在
    # 「前16位」与「）：」之间（半角或全角）/ 16 位 hex 内含空白；实测四类皆为 sha=None、
    # missing=0、ok=True（同一条件下指针型 zcode-user 判 sha=None、missing=1、ok=False——
    # 同库两套口径）。而渲染型产物是**由本仓渲染链路写出的**，其指纹行是模板固定行
    # （full.md.tmpl:5 / rules.mdc.tmpl:12 / compact.txt.tmpl:18 / skill.md.tmpl:23），
    # 缺了就说明它没走过渲染链路或被人手改——两种情形都不得放行。
    # 只有真·手工投影（矩阵 render:false）才允许无指纹静默：它不在渲染链路内，其漂移由上面
    # 的字段级逐字比对兜底（无指纹仍不能判陈化，但字段面已判）。
    if m is None and not is_manual_target(target):
        res["missing"].append({"no": 0, "field": "指纹", "key": "artifact_sha",
                               "id": "-",
                               "text": "渲染产物未内嵌真源指纹（模板固定行，形如"
                                       "「真源指纹（SHA256 前16位）：<16 位小写 hex>」）"
                                       "——无指纹即无法判陈化"})

    res["toolname"] = check_tool_alignment(text, target)

    # 陈化（产物内嵌指纹 ≠ 当前真源指纹）与缺失/孤儿/工具名漂移**同为硬失败**：
    # 改真源未重渲染的产物，会把旧纪律继续注入各端——静默放行等于门禁形同虚设。
    res["ok"] = (not res["missing"] and not res["orphans"]
                 and not res["toolname"] and not res["stale"])
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="工作纪律漂移守卫")
    ap.add_argument("--repo", default=R.REPO_DEFAULT)
    ap.add_argument("--target", action="append", default=[])
    ap.add_argument("--all-targets", action="store_true", help="含 enabled=false 的目标（干跑比对）")
    ap.add_argument("--allow-missing", action="store_true", help="产物不存在时不计为失败")
    ap.add_argument("--cg-root", default=None,
                    help="认知图 root：校验 structural/ 投影节点一致性（缺省读环境变量 MDCG_ROOT）。"
                         "A2 裁决：未提供/不存在/非认知图三态一律 fail-closed（退出码 2）")
    ap.add_argument("--no-chain", action="store_true",
                    help="跳过祖先链发现（Pi⑦⑤ 报告面）；硬判据（path_dup / root_shadow）不受影响")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    repo = os.path.abspath(args.repo)
    mx = R.load_matrix(repo)
    src = R.load_source(repo)
    targets = mx.get("targets", {})
    names = args.target or [n for n, t in targets.items() if t.get("enabled") or args.all_targets]

    results = []
    for name in names:
        t = dict(targets.get(name) or {})
        t["_name"] = name
        results.append(check(t, src, repo, args.allow_missing))

    # 认知图投影节点守卫（2026-09-16；A2 使用者裁决 2026-10-05 改口径）：纪律在灵枢认知图
    # structural/ 下还有一份投影（tags 含 discipline:N），此前是手工快照、无守卫 → 改真源
    # 必然陈化。此处纳入同一守卫。
    # A2 裁决：root 缺失/无效**一律 fail-closed**——此前「未提供」即静默 [SKIP] 退 0，
    # 判据体在全部自动化面从未执行；「提供但不存在」与「未提供」同分支。故取根走
    # DN.require_root（三态文案单点），非 0 退出（退出码 2）；四个自动化面各自显式提供 root。
    cg_res = DN.check_cg_nodes(repo, DN.require_root(args.cg_root))

    # Pi⑦⑤ 注入面发现 + 防重复（矩阵 injection: 段；未声明则整体静默跳过）
    inj_res = (check_injection_matrix(mx, repo, names, probe_chain=not args.no_chain)
               if R.injection_conf(mx) else None)

    # 分发面计数守卫（2026-10-07）：手写描述（插件清单 / 各端 README）里的「N 条工作纪律」
    # 须等于真源条数——真源现算，非硬编码；「第 N 条工作纪律」这类引用按前缀判「第」排除，不误伤。
    cnt_res = check_discipline_count(repo)

    bad = [r for r in results if not r["ok"]]
    # A2：skipped 不得计入通过——check_cg_nodes 在 root 缺失时已返回 ok=False，这里再显式
    # 兜一层（任何 skipped 一律进 bad），免得日后有人只改一侧又把它变回静默绿。
    if cg_res.get("skipped") or not cg_res["ok"]:
        bad = bad + [{"target": "cg-projection-nodes"}]
    if inj_res is not None and not inj_res["ok"]:
        bad = bad + [{"target": "injection-surface"}]
    if not cnt_res["ok"]:
        bad = bad + [{"target": "discipline-count"}]
    if args.json:
        print(json.dumps({"ok": not bad, "results": results,
                          "cg_projection_nodes": cg_res,
                          "injection_surface": inj_res,
                          "discipline_count": cnt_res}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            mark = "SKIP" if r["skipped"] else ("OK  " if r["ok"] else "DRIFT")
            print("[%s] %-10s variant=%-7s -> %s" % (mark, r["target"], str(r["variant"]), r["artifact"]))
            for m in r["missing"]:
                print("        缺失 第%d条 %s: %s" % (m["no"], m["field"], m["text"]))
            if r.get("advisory"):
                print("        摘要差异 %d 处（该目标声明 verify_fields=advisory：清单形态需转义半角 "
                      "'|' 且刻意摘要化，故不判失败；差异全量列出供人工复核）"
                      % len(r["advisory"]))
                for m in r["advisory"]:
                    print("          ~ 第%d条 %s: %s" % (m["no"], m["field"], m["text"]))
            if r["orphans"]:
                print("        孤儿声明（真源无此条）：第 %s 条" % ", ".join(str(x) for x in r["orphans"]))
            for m in r.get("toolname") or []:
                print("        工具名未随端标注（DSH 端注册名未与本端正名同行）第%d行: %s"
                      % (m["line"], m["text"]))
            if r.get("stale"):
                print("        陈化：产物指纹 %s ≠ 当前真源 %s（改真源后未重渲染）"
                      % (r.get("artifact_sha"), r.get("source_sha")))
        if cg_res.get("skipped"):
            # A2：skipped = 判据体没执行 ⇒ 不是通过态，显式升为失败（fail-closed）。
            print("[FAIL] %-10s %s" % ("cg-nodes", cg_res["reason"]))
        else:
            cg_mark = "OK  " if cg_res["ok"] else "DRIFT"
            print("[%s] %-10s variant=%-7s -> 认知图投影节点 %d/%d 一致（真源指纹 %s）"
                  % (cg_mark, "cg-nodes", "-", cg_res["nodes"] - len({d["no"] for d in cg_res["drift"]}),
                     cg_res["nodes"], cg_res.get("source_sha")))
            for d in cg_res["drift"]:
                print("        漂移 第%d条 %s: %s" % (d["no"], d["kind"], d["detail"]))
        if inj_res is not None:
            hits = sum(len(c["hits"]) for c in inj_res["chains"])
            inside = sum(1 for c in inj_res["chains"] for h in c["hits"] if h["tier"] == "repo")
            print("[%s] %-10s variant=%-7s -> 注入面：%d 条链，同槽位命中 %d（仓内 %d / 仓外 %d）"
                  "，别名折叠 %d，同仓 worktree 重复源 %d"
                  % ("OK  " if inj_res["ok"] else "DRIFT", "injection", "-",
                     inj_res["probed"], hits, inside, hits - inside,
                     len(inj_res["dedup"]), len(inj_res["wt_dups"])))
            for d in inj_res["path_dups"]:
                print("        同一物理文件被多个 target 写：%s ← %s%s"
                      % (d["key"], ", ".join(d["targets"]),
                         "；含 render:false 手工件（%s），渲染会覆盖手改"
                         % ", ".join(d["manual"]) if d["manual"] else ""))
            for s in inj_res["root_shadow"]:
                print("        仓根遮蔽：槽位 %s 声明顺序中 %s 优先于本地私有件 %s "
                      "→ 后者在该宿主下不生效（%s）"
                      % (s["slot"], s["winner"], s["loser"], s["path"]))
            for c in inj_res["chains"]:
                print("        祖先链 %s（槽位 %s）" % (c["target"], c["slot"]))
                for h in c["hits"]:
                    print("          ← %s（%s）"
                          % (h["path"], " · ".join((
                              "仓内" if h["tier"] == "repo" else "仓外",
                              "同名" if h["same_name"] else "异名",
                              "声明顺序下自身被遮蔽" if h["rank"] < h["self_rank"]
                              else "声明顺序下自身优先",
                              "指纹 " + str(h["sha"]) if h["sha"] else "未标注指纹"))))
            for d in inj_res["dedup"]:
                print("        别名折叠（同一物理目录经别名在链上出现两次，只查一次）：%s ≡ %s"
                      % (d["dir"], d["alias_of"]))
            for d in inj_res["wt_dups"]:
                print("        同仓 worktree 另一份（物理不同，两份都可能被读到）：%s ∥ %s"
                      % (d["path"], d["alias_of"]))
            if any(h["tier"] == "outside" for c in inj_res["chains"] for h in c["hits"]):
                print("        注：仓外命中是宿主侧事实（宿主从启动目录逐级上溯会读到），本仓不裁决——"
                      "列出以保证「重复注入」不被假定为不存在。")
        if cnt_res["ok"]:
            print("[OK  ] %-10s variant=%-7s -> 分发面计数：%d 个手写描述文件，%d 处「N 条工作纪律」"
                  "全部 = 真源 %d 条" % ("count", "-", cnt_res["scanned"], cnt_res["claims"],
                                       cnt_res["expected"]))
        else:
            print("[DRIFT] %-10s variant=%-7s -> 分发面计数漂移（期望真源 %d 条）"
                  % ("count", "-", cnt_res["expected"]))
            if cnt_res.get("reason"):
                print("        %s" % cnt_res["reason"])
            for d in cnt_res["drift"]:
                print("        %s:%d → 实际 %d，期望 %d | %s"
                      % (d["file"], d["line"], d["n"], cnt_res["expected"], d["text"]))
        print("")
        print("结论：%d/%d 目标一致%s" % (len(results) - len([r for r in results if not r["ok"]]), len(results),
                                        "" if not bad else "；漂移目标：" + ", ".join(r["target"] for r in bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
