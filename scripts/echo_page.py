# -*- coding: utf-8 -*-
"""echo 页生成与检查（工作纪律第 19 条 / issue #663 之一）。

echo 页 = 一页外部解释：<=200 字，强制三问：
  1 它解决什么问题
  2 它凭什么可信      —— 必须指认判据（测试名 / 断言 id / 读数 / gate 名），不接受形容词
  3 我怎么用一次      —— 必须给可复现入口（命令 / 路径 / 工具调用）

用法：
  python scripts/echo_page.py --skeleton <真源文件> [--out <echo 页路径>]
  python scripts/echo_page.py --check <echo 页路径> [--json]

退出码：0 合格；1 不合格（fail-closed）；2 用法错误。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

MAX_CHARS = 200
SECTIONS = ("解决什么问题", "凭什么可信", "怎么用一次")

EVIDENCE_RE = re.compile(
    r"(test_[A-Za-z0-9_]+"
    r"|[A-Za-z0-9_]+\.py:\d+"
    r"|gate_[a-z_]+"
    r"|check_[A-Za-z0-9_]+"
    r"|[A-Za-z0-9_]+\.json"
    r"|#[0-9]{2,4}\b"
    r"|\b\d+(?:\.\d+)?\s*(?:%|ms|s|MB|KB|条|项|处|倍)"
    r"|\bassert_[A-Za-z0-9_]+)"
)
ANCHOR_RE = re.compile(
    r"^\s*版本锚\s*[:：]\s*理论\s*=\s*(\S+)\s*[,，]\s*架构\s*=\s*(\S+)\s*[,，]\s*本投影\s*=\s*(\S+)\s*$",
    re.M)

SKELETON = """# echo 页：{name}

版本锚: 理论=<理论版本>，架构=<架构版本>，本投影=<本投影版本，如 v0.9.13>

## 1 解决什么问题

<一句话：谁在什么情况下会卡住；不写背景铺垫>

## 2 凭什么可信

<必须给可指认判据：测试名 / 断言 id / gate 名 / 读数；不写「稳定」「强大」这类形容词>

## 3 怎么用一次

<一条可复现入口：命令或路径，读者照抄能跑>

---
真源: {src}
"""


def body_of(text):
    """去掉标题行、版本锚行与文末真源行后的正文（字数只算正文）。"""
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("# ") or s.startswith("---") or s.startswith("真源:"):
            continue
        if s.startswith("版本锚"):
            continue
        lines.append(s)
    return "\n".join(lines)


def sections_of(text):
    """按二级标题切出三问正文（标题里含三问关键词即归位）。"""
    out = {}
    cur = None
    for ln in text.splitlines():
        m = re.match(r"^##\s*\d?\s*(.+?)\s*$", ln)
        if m:
            name = m.group(1).strip()
            cur = next((k for k in SECTIONS if k in name), None)
            if cur:
                out.setdefault(cur, [])
            continue
        if cur:
            out[cur].append(ln)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def check(text):
    problems = []
    anchors = ANCHOR_RE.search(text)
    if not anchors:
        problems.append("缺版本锚：须形如「版本锚: 理论=X，架构=Y，本投影=Z」")
    secs = sections_of(text)
    for name in SECTIONS:
        if not secs.get(name):
            problems.append("缺第 %d 问正文：%s" % (SECTIONS.index(name) + 1, name))
    body = body_of(text)
    n = len(body)
    if n > MAX_CHARS:
        problems.append("正文 %d 字 > %d 字上限（写成文档了）" % (n, MAX_CHARS))
    q2 = secs.get("凭什么可信", "")
    if q2 and not EVIDENCE_RE.search(q2):
        problems.append("第二问没有可指认判据（须含测试名/断言 id/gate 名/读数/文件:行）")
    return {
        "ok": not problems,
        "chars": n,
        "max_chars": MAX_CHARS,
        "sections": sorted(secs),
        "anchors": list(anchors.groups()) if anchors else None,
        "evidence": bool(q2 and EVIDENCE_RE.search(q2)),
        "problems": problems,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="echo 页生成与检查（第 19 条）")
    ap.add_argument("--skeleton", metavar="真源", help="生成骨架（打印到 stdout 或 --out）")
    ap.add_argument("--out", help="骨架落盘路径")
    ap.add_argument("--check", metavar="echo页", help="检查一份 echo 页")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.skeleton:
        src = args.skeleton
        name = os.path.splitext(os.path.basename(src))[0]
        text = SKELETON.format(name=name, src=src.replace("\\", "/"))
        if args.out:
            d = os.path.dirname(os.path.abspath(args.out))
            if d:
                os.makedirs(d, exist_ok=True)
            io.open(args.out, "w", encoding="utf-8", newline="").write(text)
            print("骨架已写入: " + args.out)
        else:
            print(text)
        return 0

    if not args.check:
        ap.print_help()
        return 2
    if not os.path.isfile(args.check):
        print("echo 页不存在: " + args.check, file=sys.stderr)
        return 1
    res = check(io.open(args.check, encoding="utf-8").read())
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print("%s %s（正文 %d/%d 字，三问=%d/3，判据=%s）"
              % ("PASS" if res["ok"] else "FAIL", args.check,
                 res["chars"], res["max_chars"], len(res["sections"]),
                 "有" if res["evidence"] else "无"))
        for p in res["problems"]:
            print("  - " + p)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
