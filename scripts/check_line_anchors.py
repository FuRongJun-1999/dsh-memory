#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_line_anchors —— 「手写行号锚」守卫（防「文件:行号」静默腐化）。

背景（一类缺陷，非孤例）：本仓文档/注释里大量以「路径:行号」形式指路（如
`md_cg/mdcg.py:3183`）。锚是**手写**的、目标件长且多变、且**没有任何管线重算**，
因而随目标件增行而静默漂移——门禁从不检查行号内容（`link_check.py` 只查相对链接
可达性；`cogmap_sync check` 只守 README 与映射表两处标记段）。实证：`scripts/
review_cli.py` 2026-10-07 被薄壳化为 43 行，一次性让 8 处锚越界而无人发现。

判据（**只判机械可判的部分，不追求语义**）：
  锚形态 = `路径:行号` 或 `路径:行号-行号` 或 `路径 L行号`
           （路径须带已知扩展名，避免把 `12:30`、`§1.2:3` 当锚）
  ∧ 该行内**最近的一个**行内代码标识符（`` `foo_bar` `` 形态）=「随行声明的标识符」
  三条机械判据（任一不成立即**报红**）：
    A. 目标件可解析（在库 / basename 唯一）
    B. 行号在目标件内**存在**（1 ≤ N ≤ 总行数；区间两端都要存在）
    C. 目标行**含随行声明的标识符**（全名或末段按子串命中，大小写敏感）

**明确不判**（写入此处以免误以为覆盖）：
  · 不解析 `由 N 行` / `−N 行` / `（N 行；…）` 一类**行数读数**（它们不是锚；本次
    审计里正是这三种写法造成了 3 条假阳性）；
  · 不做「行号虽在文件内但语义已错」的判定（B/C 只在字面层面成立/不成立；描述配对
    属启发式，不入门禁）；
  · 不判 `第N行` / `N行` / `#Lnn` 三种弱形态（误报率高，且本仓实测其假阳性集中）；
  · 目标件**不可解析**（未入库 / 同名多处）→ 记为 UNRESOLVED 单列，不报红（机械层面
    无法确定目标，硬报红会制造假红）。

baseline/allowlist = `scripts/line_anchor_baseline.json`，**两种机制，语义不同、不许混称**：

  · `rules`（**豁免 exempt**）——整类**既往留档面**。判据＝本仓明规「历史留档刻意不改写：
    `docs/eval/` 下既往评测报告…改写即伪造历史」（`docs/eval/归一层缺省翻关_修复记录_v1.0.md:384`）。
    逐条 glob 带理由；`mode:"keep"` 的规则**优先**（用于把现行设计/契约件从 docs/eval 里
    划出来、不予豁免）。豁免项**不是**「问题不存在」，而是「按本仓纪律不得改写」。
  · `anchors`（**基线冻结 frozen**）——HEAD 时点的**存量手写锚债**，逐条 `file:line → target:line`
    登记。它们**不是**「通过」，只是**冻结**：本次审计只把 33 条界到「确凿」，其余（机械
    判据更严，命中量更大）不在本次改动面内。**基线只减不增**——新引入一条漂移锚必然不在
    基线内 → 报红。

用法：
  python scripts/check_line_anchors.py            # 退出码 0=无未豁免/未冻结的红；1=有
  python scripts/check_line_anchors.py --list     # 逐条打印红/绿/豁免/冻结
  python scripts/check_line_anchors.py --json out.json
  python scripts/check_line_anchors.py --root DIR --baseline F  # 沙箱/定点变异自证
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
BASELINE = os.path.join(_HERE, "line_anchor_baseline.json")

SCAN_EXT = (".py", ".rs", ".ts", ".js", ".sh", ".toml", ".yml", ".yaml", ".json", ".md")

# 锚形态：path:NN  /  path:NN-MM  /  path L N   （路径必须带已知扩展名）
_PATH = r"[A-Za-z0-9_./\\\-]*\.(?:py|rs|ts|js|sh|toml|yml|yaml|json|md)"
ANCHOR = re.compile(
    r"(?P<path>" + _PATH + r")\s*:\s*(?P<a>\d+)(?:\s*-\s*(?P<b>\d+))?"
    r"|(?P<path2>" + _PATH + r")\s+L(?P<a2>\d+)"
)
CODE_SPAN = re.compile(r"`([^`\n]+)`")      # 行内代码跨度
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def tracked_files(root: str) -> list[str]:
    """库内相对路径（posix 分隔）的受管件；无 git 时退化为全盘走查（沙箱用）。"""
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z"],
                             capture_output=True, check=True)
        return [f for f in out.stdout.decode("utf-8", "replace").split("\0") if f]
    except Exception:
        got = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for fn in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                got.append(rel.replace(os.sep, "/"))
        return sorted(got)


def read_lines(root: str, rel: str):
    try:
        with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as f:
            return f.read().split("\n")
    except OSError:
        return None


def resolve_target(root: str, raw: str, anchor_rel: str, by_base: dict) -> str | None:
    p = raw.replace("\\", "/").lstrip("./")
    cands = [p]
    if "/" not in p:
        d = os.path.dirname(anchor_rel)
        if d:
            cands.append((d + "/" + p).lstrip("/"))
    for c in cands:
        if os.path.isfile(os.path.join(root, c)):
            return c
    if "/" not in p:
        hit = by_base.get(os.path.basename(p))
        if hit and len(hit) == 1:
            return hit[0]
    return None


def nearest_ident(line: str, span: tuple[int, int]) -> str | None:
    """行内离锚最近的行内代码标识符（`` `foo_bar` `` 形态）；无则 None（不判）。"""
    best, bestd = None, None
    for m in CODE_SPAN.finditer(line):
        txt = m.group(1).strip()
        if not IDENT.match(txt) or len(txt) < 4:
            continue
        if m.start() <= span[1] <= m.end() or m.start() <= span[0] <= m.end():
            continue  # 与锚自身重叠
        d = min(abs(m.start() - span[1]), abs(span[0] - m.end()))
        if bestd is None or d < bestd:
            best, bestd = txt, d
    return best


def ident_in_line(ident: str, text: str) -> bool:
    if ident in text:
        return True
    tail = ident.split(".")[-1]
    return len(tail) >= 4 and tail in text


def load_baseline(path: str) -> dict:
    if not path or not os.path.isfile(path):
        return {"rules": [], "anchors": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def classify(anchor_rel: str, key: str, base: dict):
    """返回 ('exempt', reason) | ('frozen', why) | None(未登记 → 报红)。

    顺序：**逐条登记先于整类规则**——`anchors` 里的显式键（含被 keep 规则划出的
    现行设计/契约件存量锚）优先判为 frozen；整类规则只决定「新出现的锚」是否豁免。
    """
    if key in base.get("_frozen_index", {}):
        return ("frozen", base["_frozen_index"][key])
    for r in base.get("rules", []):
        if fnmatch.fnmatch(anchor_rel, r.get("glob", "\0")):
            if r.get("mode", "exempt") == "keep":
                return None          # 显式划出豁免面（现行设计/契约件 → 不豁免）
            return ("exempt", r.get("reason", "整类豁免"))
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=REPO)
    ap.add_argument("--baseline", default=BASELINE)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    files = tracked_files(root)
    # 基线数据文件自身含 `路径:行号` 字符串（是数据不是文档）——排除，避免自指扫描
    scannable = [f for f in files if f.endswith(SCAN_EXT)
                 and os.path.basename(f) != "line_anchor_baseline.json"]
    by_base: dict[str, list[str]] = {}
    for f in scannable:
        by_base.setdefault(os.path.basename(f), []).append(f)

    base = load_baseline(args.baseline)
    # 索引化锚点基线（每条 why 独立）；生成器同时写入扁平 list 供人读
    base["_frozen_index"] = {a["key"]: a.get("why", "基线冻结")
                             for a in base.get("anchors", [])}

    red, green, exempt, frozen, unresolved = [], [], [], [], []
    n_anchors = n_noid = 0

    for rel in scannable:
        lines = read_lines(root, rel)
        if lines is None:
            continue
        for i, line in enumerate(lines, 1):
            for m in ANCHOR.finditer(line):
                raw_path = m.group("path") or m.group("path2")
                a = int(m.group("a") or m.group("a2"))
                b = int(m.group("b")) if m.group("b") else None
                n_anchors += 1
                ident = nearest_ident(line, m.span())
                if ident is None:
                    n_noid += 1
                    continue
                key = "%s:%d -> %s:%d" % (rel, i, raw_path, a)
                tgt = resolve_target(root, raw_path, rel, by_base)
                if tgt is None:
                    unresolved.append({"anchor": key, "ident": ident,
                                       "why": "目标件不可解析（未入库/同名多处）"})
                    continue
                tl = read_lines(root, tgt) or []
                why = None
                if a < 1 or a > len(tl) or (b is not None and b > len(tl)):
                    why = "行号越界（目标件 %d 行，锚称 %d%s）" % (
                        len(tl), a, ("-%d" % b) if b else "")
                elif not ident_in_line(ident, tl[a - 1]):
                    why = "随行标识符 `%s` 不在该行" % ident
                rec = {"anchor": key, "target": "%s:%d" % (tgt, a), "ident": ident,
                       "target_line": (tl[a - 1][:100] if 1 <= a <= len(tl) else None)}
                if why is None:
                    green.append(rec)
                    continue
                rec["why"] = why
                cls = classify(rel, key, base)
                if cls is None:
                    red.append(rec)
                else:
                    kind, reason = cls
                    rec["reason"] = reason
                    (exempt if kind == "exempt" else frozen).append(rec)

    print("check_line_anchors: root=%s" % root)
    print("  扫描件 %d（受管件 %d）" % (len(scannable), len(files)))
    print("  识别锚 %d   其中无随行标识符·不判 %d" % (n_anchors, n_noid))
    print("  绿 %d | 红(未登记) %d | 豁免(留档面) %d | 基线冻结 %d | 无法解析 %d"
          % (len(green), len(red), len(exempt), len(frozen), len(unresolved)))
    if args.list:
        for r in red:
            print("  [RED]      %s   %s" % (r["anchor"], r["why"]))
        for r in frozen:
            print("  [FROZEN]   %s   %s" % (r["anchor"], r["why"]))
        for r in exempt:
            print("  [EXEMPT]   %s   (%s)" % (r["anchor"], r["reason"]))
        for r in unresolved:
            print("  [UNRESOLVED] %s   (%s)" % (r["anchor"], r["why"]))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"red": red, "green": green, "exempt": exempt,
                       "frozen": frozen, "unresolved": unresolved},
                      f, ensure_ascii=False, indent=1)
    if red:
        print("VERDICT: FAIL —— %d 条行号锚未通过且未登记" % len(red))
        return 1
    print("VERDICT: PASS —— 未登记的红为 0（绿 %d + 豁免 %d + 冻结 %d）"
          % (len(green), len(exempt), len(frozen)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
