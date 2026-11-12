#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""whale_corpus_prep —— 鲸娘语料预处理：剥离思考块 + 按身份区分双角色消息。

使用者 2026-10-06 指令：「鲸娘语料，先剥离思考块，然后根据身份区分鲸鱼娘和我的
消息。之后再做世界模型的处理。」本件是**第一步**的固化件：把混合语料拆成

    <out>/<语料名>/我说.md          —— 用户侧消息流（逐块，原序）
    <out>/<语料名>/鲸鱼娘.md        —— 鲸鱼娘（助手侧）正文消息流
    <out>/<语料名>/鲸鱼娘-思考.md    —— 剥离出的思考块（独立存档，**不销毁**）
    <out>/<语料名>/prep_report.json  —— 块数/字符/噪声计数（机器可读）

支持的两种语料形态（自动探测）：
  · A 型（会话转写）：`**我说：**` / `**DeepSeek说：**`（或 `**鲸鱼小姐说：**`）
    分块、`---` 分隔；思考块 = 以 `> ` 起始的整行（沿 v3/v4 探针已复核口径
    「引用块整行剥离」——该语料里 `> ` 块是模型的思考/心声通道，含两类：元层
    规划与**她第一人称的心声**，二者都不属「说出口的话」，故一并剥离进独立档案）。
  · B 型（Hermes 导出）：`## N. <角色>` 分节（我/她/工具/系统）＋ `**思维链**`
    标记段；`[Hermes UI Workspace]...[/Hermes UI Workspace]` 为宿主噪声块
    （剥离并计数，不静默）。

硬纪律：
  · 脚本不内嵌任何本机/语料路径字面量——corpus 与 out 一律 CLI 参数传入；
  · `--out` 必须落在**仓外**（fail-closed 断言；语料与产物为私有数据，绝不入
    公开仓——工作纪律第 9 条）；
  · 纯标准库、零随机零时间戳（同输入 ⇒ 同字节输出）；不碰任何 MDCG_* 环境、
    零记忆库写入。

用法：
  python -X utf8 scripts/whale_corpus_prep.py \
      --corpus <语料文件.md> [--corpus <文件2.md> ...] --out <仓外输出目录>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

#: A 型角色行（冒号形态，兼容全/半角）——角色 → 输出流名
_A_ROLE = re.compile(r"^\*\*(我说|DeepSeek说|鲸鱼小姐说|鲸鱼娘说)[：:]\*\*\s*$")
#: B 型节头：`## N. 角色`（用户侧）或 `### 角色`（助手侧/工具）
_B_HEAD = re.compile(r"^(?:##\s*\d+\.\s*(\S+)|###\s*(\S+))\s*$")
#: B 型角色映射（Hermes 导出器 ROLE_ZH ＋ 人设名）
_B_ROLES = {"我": "我说", "我说": "我说", "她": "鲸鱼娘", "鲸鱼小姐": "鲸鱼娘",
            "鲸鱼娘": "鲸鱼娘", "工具": "工具", "系统": "系统"}
#: B 型工具输出折叠块（`<details>...</details>`）——宿主工具调用记录，剥离并计数。
_DETAILS_OPEN = re.compile(r"^<details>\s*$")
_DETAILS_CLOSE = re.compile(r"^</details>\s*$")
#: 思考块行：`>` 起始（含空 `>`）——整行剥离（v3/v4 复核口径）
_THINK = re.compile(r"^>\s?")
#: 宿主噪声块（B 型）
_WS = re.compile(r"^\[Hermes UI Workspace\]$")
_WS_END = re.compile(r"^\[/Hermes UI Workspace\]$")
_STREAM = {"我说": "我说", "鲸鱼娘": "鲸鱼娘"}


def _stream_of(role: str) -> str:
    """角色行标签 → 输出流名（DeepSeek说/鲸鱼小姐说/她 → 鲸鱼娘；我 → 我说）。"""
    if role in ("我说", "我"):
        return "我说"
    return "鲸鱼娘"


def parse_a(text: str):
    """A 型解析 → (blocks, thinking_runs, note_counts)。

    blocks = [(stream, body_lines), ...]（按出现序）；thinking_runs =
    [(after_block_index, lines), ...]（思考块挂到**其后**的出块索引，落 `思考.md`）。
    """
    lines = text.splitlines()
    heads = []                       # (行号, 角色)
    for i, ln in enumerate(lines):
        m = _A_ROLE.match(ln.strip())
        if m:
            heads.append((i, m.group(1)))
    blocks, think = [], []
    counts = {"thinking_lines": 0}
    if not heads:
        return blocks, think, counts
    for k, (i, role) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        seg = lines[i + 1:end]
        body, th = [], []
        for ln in seg:
            if _THINK.match(ln):
                th.append(ln)
            elif ln.strip() == "---":
                continue
            else:
                body.append(ln)
        while body and not body[-1].strip():
            body.pop()
        while body and not body[0].strip():
            body.pop(0)
        blocks.append((_stream_of(role), body))
        if th:
            # 思考块归属：本段是「我说」而思考块出现在段尾 ⇒ 是**她的**思考
            # （生产该回复的推理通道）；否则随本段角色。
            owner = "鲸鱼娘" if role == "我说" else _stream_of(role)
            think.append((len(blocks) - 1, owner, th))
            counts["thinking_lines"] += len(th)
    return blocks, think, counts


# 生效条件：每次调用累计 kind + "_unclosed" 与 unclosed_dropped_lines，并向 stderr
# 写一行含 kind 与被吞行数的警告；不抛异常、不猜内容边界。
def _warn_unclosed(counts, kind, swallowed):
    """未闭合噪声块的可观测信号（issue #171 问题三）。

    病象：`[Hermes UI Workspace]` 或 `<details>` 只见开标记、不见闭标记时，parse_b
    把其后**直到文末**的一切都当噪声剥掉——正文被静默吞掉，产物里毫无痕迹。
    处置：文末仍在块内 ⇒ 计数（kind + "_unclosed" / unclosed_dropped_lines）并把
    被吞行数写进 stderr 警告。剥除语义不变（不猜边界），只让「吞了多少」可观测。
    """
    counts[kind + "_unclosed"] = counts.get(kind + "_unclosed", 0) + 1
    counts["unclosed_dropped_lines"] = (counts.get("unclosed_dropped_lines", 0)
                                        + int(swallowed))
    sys.stderr.write("[whale_corpus_prep] 警告：%s 噪声块未闭合——其后 %d 行按噪声块"
                     "剥除（该节正文可能被整段丢掉）；请核对语料闭合标记。\n"
                     % (kind, int(swallowed)))


def parse_b(text: str):
    """B 型（Hermes 导出）解析：`## N. 我` / `### 角色` 分节；`**思维链**` 标记后的
    `> ` 段为思考；`[Hermes UI Workspace]` 与 `<details>` 块为宿主噪声（剥离计数）。"""
    lines = text.splitlines()
    heads = []
    for i, ln in enumerate(lines):
        m = _B_HEAD.match(ln)
        if m:
            heads.append((i, m.group(1) or m.group(2)))
    blocks, think = [], []
    counts = {"thinking_lines": 0, "workspace_blocks": 0, "detail_blocks": 0}
    in_ws = False
    in_details = False
    # issue #171（问题三）：未闭合噪声块的可观测信号——*_swallow 计「自最近一次
    # 闭块起被当噪声剥掉的行数」，闭块即清零；文末仍在块内 ⇒ 警告 + 计数。
    ws_swallow = 0
    det_swallow = 0
    for k, (i, role) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        seg = lines[i + 1:end]
        body, th = [], []
        for ln in seg:
            if _DETAILS_OPEN.match(ln):
                in_details = True
                counts["detail_blocks"] += 1
                continue
            if _DETAILS_CLOSE.match(ln):
                in_details = False
                det_swallow = 0
                continue
            if in_details:
                det_swallow += 1
                continue
            if _WS.match(ln):
                in_ws = True
                counts["workspace_blocks"] += 1
                continue
            if _WS_END.match(ln):
                in_ws = False
                ws_swallow = 0
                continue
            if in_ws:
                ws_swallow += 1
                continue
            if ln.strip() == "**思维链**":
                continue
            if _THINK.match(ln):
                th.append(ln)
            elif ln.strip() == "---":
                continue
            else:
                body.append(ln)
        while body and not body[-1].strip():
            body.pop()
        stream = _B_ROLES.get(role, role)
        blocks.append((stream, body))
        if th:
            think.append((len(blocks) - 1, "鲸鱼娘" if stream == "我说" else stream, th))
            counts["thinking_lines"] += len(th)
    if in_ws:
        _warn_unclosed(counts, "workspace", ws_swallow)
    if in_details:
        _warn_unclosed(counts, "details", det_swallow)
    return blocks, think, counts


def detect_format(text: str):
    """语料形态探测 → ('B'|'A'|'unknown', 理由)。

    「认不出」与「处理完了」必须分开（B104）：以前只看有没有 `## N.` 就二选一，
    两边都解析不出块时照样写三个空 .md 并打 PREP DONE，调用方拿到全零读数却当成功。
    """
    if re.search(r"^##\s*\d+\.\s", text, flags=re.M):
        return "B", "found '## N. <role>' section heads"
    if _A_ROLE.search(text) or any(_A_ROLE.match(ln.strip()) for ln in text.splitlines()):
        return "A", "found '**我说：**' style role lines"
    return "unknown", "no A-type role line and no B-type section head"


def _join(blocks, stream):
    out = []
    for s, body in blocks:
        if s != stream:
            continue
        txt = "\n".join(body).strip()
        if txt:
            out.append(txt)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="鲸娘语料预处理（剥离思考块＋身份区分）")
    ap.add_argument("--corpus", action="append", required=True,
                    help="语料文件（可多次；md）")
    ap.add_argument("--out", required=True, help="输出目录（**必须仓外**）")
    a = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_root = os.path.abspath(a.out)
    if os.path.commonpath([repo, out_root]) == repo:
        print("FAIL-CLOSED：--out 落在仓内——私有语料产物不得入公开仓（纪律 9）")
        return 2

    os.makedirs(out_root, exist_ok=True)
    overall = []
    unrecognized = []
    for src in a.corpus:
        text = open(src, encoding="utf-8").read()
        fmt, why = detect_format(text)
        is_b = fmt == "B"
        blocks, think, counts = (parse_b(text) if is_b else parse_a(text)) if fmt != "unknown" else ([], [], {})
        name = os.path.splitext(os.path.basename(src))[0]
        d = os.path.join(out_root, name)
        # 三态：ok（解析出块）/ empty_valid（源文件本来就空）/ unrecognized（有内容但认不出）
        if blocks:
            status = "ok"
        elif not text.strip():
            status = "empty_valid"
        else:
            status = "unrecognized"
        if status == "unrecognized":
            unrecognized.append(os.path.basename(src))
            rep = {"corpus": os.path.basename(src), "status": status, "reason": why,
                   "format": "unknown", "blocks_total": 0}
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "prep_report.json"), "w", encoding="utf-8",
                      newline="\n") as f:
                json.dump(rep, f, ensure_ascii=False, indent=2)
            overall.append(rep)
            print(json.dumps(rep, ensure_ascii=False))
            print("UNRECOGNIZED：%s —— %s（不写空产物，不计入成功）" % (os.path.basename(src), why))
            continue
        os.makedirs(d, exist_ok=True)

        me = _join(blocks, "我说")
        her = _join(blocks, "鲸鱼娘")
        other = sorted({s for s, _b in blocks} - {"我说", "鲸鱼娘"})
        with open(os.path.join(d, "我说.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n\n---\n\n".join(me) + ("\n" if me else ""))
        with open(os.path.join(d, "鲸鱼娘.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n\n---\n\n".join(her) + ("\n" if her else ""))
        th_lines = []
        for idx, owner, lines in think:
            th_lines.append("<!-- 块 %d · 归属：%s -->" % (idx + 1, owner))
            th_lines.extend(lines)
            th_lines.append("")
        with open(os.path.join(d, "鲸鱼娘-思考.md"), "w", encoding="utf-8",
                  newline="\n") as f:
            f.write("\n".join(th_lines) + ("\n" if th_lines else ""))

        rep = {
            "corpus": os.path.basename(src),
            "status": status,
            "format": "B(hermes-export)" if is_b else "A(transcript)",
            "blocks_total": len(blocks),
            "blocks_我说": sum(1 for s, _b in blocks if s == "我说"),
            "blocks_鲸鱼娘": sum(1 for s, _b in blocks if s == "鲸鱼娘"),
            "other_streams": other,
            "thinking_runs": len(think),
            "thinking_lines": counts.get("thinking_lines", 0),
            "workspace_blocks": counts.get("workspace_blocks", 0),
            "detail_blocks": counts.get("detail_blocks", 0),
            # issue #171 问题三：未闭合噪声块的机器可读信号（0 = 正常）
            "workspace_unclosed": counts.get("workspace_unclosed", 0),
            "details_unclosed": counts.get("details_unclosed", 0),
            "unclosed_dropped_lines": counts.get("unclosed_dropped_lines", 0),
            "chars_我说": sum(len(x) for x in me),
            "chars_鲸鱼娘": sum(len(x) for x in her),
            "sha256_我说": hashlib.sha256("\n\n---\n\n".join(me).encode("utf-8")).hexdigest()[:16],
            "sha256_鲸鱼娘": hashlib.sha256("\n\n---\n\n".join(her).encode("utf-8")).hexdigest()[:16],
        }
        with open(os.path.join(d, "prep_report.json"), "w", encoding="utf-8",
                  newline="\n") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        overall.append(rep)
        print(json.dumps(rep, ensure_ascii=False))
    print()
    ok_n = sum(1 for r in overall if r.get("status") in ("ok", "empty_valid"))
    if unrecognized:
        # 退出码表达「有语料没认出」：全零产物 + PREP DONE 退出 0 会让调用方当成功（B104）。
        print("PREP INCOMPLETE：%d 份成功 / %d 份认不出（%s）→ %s"
              % (ok_n, len(unrecognized), "、".join(unrecognized), out_root))
        return 3
    print("PREP DONE：%d 份语料 → %s" % (ok_n, out_root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
