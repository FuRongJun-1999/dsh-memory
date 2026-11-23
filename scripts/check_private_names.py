#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""内容政策 · **私域标识冻结守卫**：公开仓里不得新增私域仓名/私域环境变量名。

# 功能名：check_private_names —— 「私域标识出现面」只准缩、不准涨
# 生效条件：仓库根可解析、git 可用（不可用 ⇒ exit 2 fail-closed）
# 子功能：
#   ① 取 **git 追踪面**（`git ls-files -z`，只认会被公开出去的文件）；
#   ② 对每条 POLICY_DENY 模式逐文件计数（按行记，不只在全文里找一次）；
#   ③ 与显式基线（scripts/private_names_baseline.json）对账：新文件命中 / 计数增长 ⇒ 红；
#   ④ 基线陈旧（文件已不被追踪、或计数下降未收缩基线）⇒ 红，逼着账本跟着代码走。
# 执行：python -X utf8 scripts/check_private_names.py [--json|--mutate|--write-baseline|--root DIR]
# 验证方式：基线态 exit 0（本仓实测）＋ `--mutate` 定点变异（注入一行命中 ⇒ 必红）＋ 自证脚本
#           scripts/test_check_private_names.py（4 组：增长红 / 新文件红 / 陈旧红 / 收缩后转绿）
# 不适用条件：
#   · **不判**「历史里已有的 1218 处要不要清、怎么清」——那是脱敏/改历史的裁量动作，不是本守卫能替人决定的；
#     本守卫只保证「从建立基线这一刻起不再增长」，其余留给 #1015 记录后由人裁决。
#   · 不扫未追踪文件（.tmp/ 试验产物、构建产物）——它们不公开，扫了只会疲于追赶；
#   · 不做语义判断：`AEIS` 出现在「讲这件事为什么不能公开」的文档里也算命中，
#     这是**有意的保守**（宁可让作者显式往基线里加，也不放过一次真泄漏）。

判据（任一条红 ⇒ 退出码 1）
--------------------------
  C1 追踪文件里出现基线之外的新命中文件 ⇒ 红
  C2 基线内某文件命中计数**增长** ⇒ 红
  C3 基线条目陈旧：文件已不被追踪 / 计数下降 ⇒ 红（请收缩基线）
  C4 git 不可用 / 仓库根不可解析 ⇒ exit 2（不静默放过）

口径（先钉口径再报数）
------------------------
  · 扫描面＝`git ls-files` 的并集，排除二进制（前 2KB 含 NUL）、>4MB、以及本守卫自身三件
    （守卫必须能写出被禁的字符串本身，否则没法守）；
  · 计数＝每行**逐次**出现都算（`str.count` 级），不是「文件里有就记 1」；
  · 模式表 POLICY_DENY 只收**私域身份**（仓名/环境变量前缀）；纯公开词不进表。

退出码：0 = 通过；1 = 有判据红；2 = 环境错误（fail-closed）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_BASELINE = os.path.join(_HERE, "private_names_baseline.json")

# 私域标识：私有运行时仓名及其环境变量前缀。写成一段拼装的形式没有必要——
# 本文件在扫描面里被**显式排除**（见 _SELF_EXCLUDE），所以可以直接写明文。
POLICY_DENY = ("AEIS",)

_SELF_EXCLUDE = frozenset({
    "scripts/check_private_names.py",
    "scripts/private_names_baseline.json",
    "scripts/test_check_private_names.py",
})

_MAX_BYTES = 4 * 1024 * 1024


def tracked_files(root: str):
    """git 追踪面（相对路径、正斜杠）。git 不可用 ⇒ 抛 RuntimeError（由调用方转 exit 2）。"""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True,
                             env=dict(os.environ, PYTHONUTF8="1"), timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("git 不可用：%s" % exc)
    if out.returncode != 0:
        raise RuntimeError("git ls-files 失败（rc=%d）：%s"
                           % (out.returncode, out.stderr.decode("utf-8", "replace")[:200]))
    return [p for p in out.stdout.decode("utf-8", "replace").split("\x00") if p]


def count_hits(root: str, rels):
    """{rel: {pattern: count}}——只记非零项。"""
    pats = [(p, re.compile(re.escape(p))) for p in POLICY_DENY]
    seen = {}
    for rel in rels:
        if rel in _SELF_EXCLUDE:
            continue
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            if os.path.getsize(path) > _MAX_BYTES:
                continue
            raw = open(path, "rb").read()
        except OSError:
            continue
        if b"\x00" in raw[:2048]:
            continue
        txt = raw.decode("utf-8", "replace")
        row = {}
        for name, rx in pats:
            n = len(rx.findall(txt))
            if n:
                row[name] = n
        if row:
            seen[rel] = row
    return seen


def load_baseline(path=_BASELINE):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    files = data.get("files") or {}
    return {k: {p: int(v) for p, v in (row or {}).items()} for k, row in files.items()}, data


def diff(seen, baseline):
    """返回 (新增, 增长, 陈旧) 三组，均为可读字符串列表。"""
    added, grown, stale = [], [], []
    for rel, row in sorted(seen.items()):
        base = baseline.get(rel)
        if base is None:
            added.append("%s  命中 %s" % (rel, json.dumps(row, ensure_ascii=False)))
            continue
        for pat, n in sorted(row.items()):
            was = base.get(pat, 0)
            if n > was:
                grown.append("%s  %s：%d → %d" % (rel, pat, was, n))
    for rel in sorted(baseline):
        if rel not in seen:
            stale.append("%s  已不再命中（文件被删/被改/不再追踪）" % rel)
            continue
        for pat, was in sorted(baseline[rel].items()):
            now = seen[rel].get(pat, 0)
            if now < was:
                stale.append("%s  %s：%d → %d（请收缩基线）" % (rel, pat, was, now))
    return added, grown, stale


def write_baseline(seen, root=""):
    files = {rel: dict(sorted(row.items())) for rel, row in sorted(seen.items())}
    totals = {}
    for row in files.values():
        for pat, n in row.items():
            totals[pat] = totals.get(pat, 0) + n
    payload = {
        "_doc": "私域标识基线：只准缩不准涨。改代码后跑 --write-baseline 重生成，并在提交信息里说明增减原因。",
        "_policy_deny": list(POLICY_DENY),
        "_scan_surface": "git ls-files（排除本守卫三件）",
        "totals": dict(sorted(totals.items())),
        "files": files,
    }
    with open(_BASELINE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=False)
        f.write("\n")
    return payload


def _mutate_red(root):
    """变异自证：往扫描面里塞一个合成文件（不落盘），判定器必须报红。"""
    rels = tracked_files(root) + ["ZZ_mutate_probe.txt"]
    seen = count_hits(root, rels)
    probe = count_hits(root, ["ZZ_mutate_probe.txt"])
    if probe:
        print("[mutate] 合成文件被真文件遮挡：%r" % probe)
        return 1
    baseline, _ = load_baseline()
    fake = dict(seen)
    fake["ZZ_mutate_probe.txt"] = {POLICY_DENY[0]: 1}
    added, grown, stale = diff(fake, baseline)
    ok = any("ZZ_mutate_probe" in a for a in added)
    print("[mutate] %s  新增项=%d 增长项=%d 陈旧项=%d"
          % ("检测到合成命中（判别力在）" if ok else "**未检测到合成命中（守卫空转）**",
             len(added), len(grown), len(stale)))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="私域标识冻结守卫")
    ap.add_argument("--root", default=_REPO)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--write-baseline", action="store_true")
    a = ap.parse_args(argv)

    try:
        rels = tracked_files(a.root)
    except RuntimeError as exc:
        print("[E] %s" % exc, file=sys.stderr)
        return 2
    seen = count_hits(a.root, rels)
    if a.write_baseline:
        payload = write_baseline(seen) if not a.root else write_baseline(seen)
        print("[OK] 基线已写：%d 文件，总计 %s"
              % (len(payload["files"]), json.dumps(payload["totals"], ensure_ascii=False)))
        return 0
    if a.mutate:
        return _mutate_red(a.root)
    try:
        baseline, raw = load_baseline()
    except (OSError, ValueError) as exc:
        print("[E] 基线不可读（%s）——先跑 --write-baseline" % exc, file=sys.stderr)
        return 2
    added, grown, stale = diff(seen, baseline)
    totals = {}
    for row in seen.values():
        for pat, n in row.items():
            totals[pat] = totals.get(pat, 0) + n
    if a.json:
        print(json.dumps({"totals": totals, "files": seen, "added": added,
                          "grown": grown, "stale": stale},
                         ensure_ascii=False, indent=1))
        return 0 if not (added or grown or stale) else 1
    print("私域标识冻结守卫：追踪文件 %d，命中文件 %d，总计 %s"
          % (len(rels), len(seen), json.dumps(totals, ensure_ascii=False)))
    for label, rows in (("C1 新增命中文件", added), ("C2 计数增长", grown),
                        ("C3 基线陈旧", stale)):
        for r in rows:
            print("  [RED] %s  %s" % (label, r))
    if added or grown or stale:
        print("结论：红（%d 新增 / %d 增长 / %d 陈旧）——新增必须挪走私域标识，"
              "确属必要（如「为什么不能公开」的说明文）才 `--write-baseline` 并写明理由。"
              % (len(added), len(grown), len(stale)))
        return 1
    print("结论：绿（基线与追踪面一致，无私域标识增长）")
    return 0


if __name__ == "__main__":
    sys.exit(main())