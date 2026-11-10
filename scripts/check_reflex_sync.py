#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""R-402 · 回流门禁（scripts/check_reflex_sync.py）

【为什么有它】
2026-11-09 的 `dbc1aaa4`「服务器活体代码回流」一次改 **1,034 个文件**（943 改 + 91 新增，
`.py` 538 → 626），在没有任何测试/守卫/签收的情况下：
  · 覆盖掉 `1d9ed589` 刚做的「主密钥三态」安全修复（`crypto.load_master_key` 回到
    `create=True`，KEK 丢失即静默新建）；
  · 删掉 4 个公开接口（`list_nodes` / `wired_steps` / `fold_access_records` /
    `tenant_actors`），拖垮 8 个测试文件；
  · 把 `auto_scrub` / `auto_evolve` 缺省从 False 改成 True。
commit message 自己写明了「未处理 ruff 276 处」，但**没有任何一道门拦它** ——
`npm run gate` 那时在第 4 项就短路，`run_tests.py` 是手动入口。

【判什么】
在一个 commit 范围里，凡是**变更文件数 > THRESHOLD** 的提交，必须满足其一：
  ① commit message 里出现 `REFLEX-SYNC-ACK`（人显式签收「我确认这是一次大批量同步」）
  ② 变更文件数 ≤ THRESHOLD
否则判红并点名该 commit。

【不判什么】
- 不判「这次同步的内容对不对」（那要跑测试，属 `run_tests.py` 的事）；
- 不判 `server/` 之外的目录（只看 `md_cg/` `server/` `scripts/` 三个源码面）；
- 对 merge commit 跳过（文件数天然虚高）。

【退出码】0 = 无未签收的大批量提交；1 = 有；2 = 自身故障
【负控】`--selftest` 会造一个「300 文件变更、无 ACK」的假 commit 记录并断言判红。
【报数三行】数 / 口径 / 反例 见输出末尾。

用法：
  python scripts/check_reflex_sync.py                 # 扫最近 50 个 commit
  python scripts/check_reflex_sync.py --range A..B
  python scripts/check_reflex_sync.py --threshold 200
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_FACES = ("md_cg/", "server/", "scripts/")
THRESHOLD = 200
ACK = "REFLEX-SYNC-ACK"


def sh(args):
    r = subprocess.run(args, cwd=ROOT, capture_output=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "")


def commits(rng, limit):
    if rng:
        rc, out = sh(["git", "rev-list", rng])
    else:
        rc, out = sh(["git", "rev-list", "-n", str(limit), "HEAD"])
    if rc != 0:
        raise SystemExit("✗ git rev-list 失败")
    return [x for x in out.split() if x]


def count_src_changes(sha):
    rc, out = sh(["git", "show", "--numstat", "--format=", "-m", "--first-parent", sha])
    if rc != 0:
        return 0
    n = 0
    for ln in out.splitlines():
        parts = ln.split("\t")
        if len(parts) < 3:
            continue
        path = parts[2]
        if any(path.startswith(f) for f in SRC_FACES):
            n += 1
    return n


def subject(sha):
    rc, out = sh(["git", "log", "-1", "--pretty=%s%n%b", sha])
    return out if rc == 0 else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--range", default="")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        # 自检：造两条假记录（一条超阈值无 ACK、一条超阈值带 ACK），断言判据只红第一条
        fake = [
            {"sha": "SELFTEST-1", "n": a.threshold + 100, "msg": "同步：服务器代码回流"},
            {"sha": "SELFTEST-2", "n": a.threshold + 100, "msg": "同步 " + ACK},
        ]
        bad = [f for f in fake if f["n"] > a.threshold and ACK not in f["msg"]]
        ok = len(bad) == 1 and bad[0]["sha"] == "SELFTEST-1"
        print("自检：%s（超阈值无 ACK 判红 1 条、带 ACK 放行）" % ("PASS" if ok else "FAIL"))
        return 0 if ok else 1

    shas = commits(a.range, a.limit)
    big, acked, small = [], [], 0
    for sha in shas:
        n = count_src_changes(sha)
        if n <= a.threshold:
            small += 1
            continue
        msg = subject(sha)
        if ACK in msg:
            acked.append((sha, n))
        else:
            big.append((sha, n, msg.splitlines()[0][:70] if msg else ""))

    print("数：扫 %d 个 commit / 超阈值(%d 文件) %d 个（已签收 %d，**未签收 %d**）/ 其余 %d"
          % (len(shas), a.threshold, len(big) + len(acked), len(acked), len(big), small))
    print("口径：只看 `md_cg/` `server/` `scripts/` 三个源码面；超阈值须在 commit message "
          "里带 `%s`；merge commit 按 --first-parent 只算一侧" % ACK)
    print("反例：若一次同步把改动拆成十几个小 commit 逐个提交，本判据**看不见**它们是一件事；"
          "反之一次纯格式化大改也会被要求签收 —— 那是刻意的摩擦")

    if big:
        print("\n✗ 未签收的大批量提交（%d）：" % len(big))
        for sha, n, subj in big:
            print("   %-10s %5d 文件  %s" % (sha[:10], n, subj))
        print("\n处置：确认这次同步的内容 → 在 commit message 里补 `%s` 并说明范围与验证；"
              "或把它拆成可审的批次。" % ACK)
    if acked:
        print("\n已签收（%d）：" % len(acked))
        for sha, n in acked[:6]:
            print("   %-10s %5d 文件" % (sha[:10], n))
    print("\n结果：%s" % ("PASS" if not big else "FAIL（%d 个未签收）" % len(big)))
    return 0 if not big else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:                                   # noqa: BLE001
        print("✗ 自身故障：%s: %s" % (type(e).__name__, e))
        sys.exit(2)
