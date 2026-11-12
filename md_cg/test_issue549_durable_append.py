# -*- coding: utf-8 -*-
"""issue #549 守卫：多进程并发追加下，**不可丢**的账本必须一行不丢。

背景（缺陷）：`fsutil.append_jsonl` 缺省走 `O_CREAT|O_WRONLY|O_APPEND`，
而 Windows CRT 的 `_O_APPEND` 是 `lseek(END) + write` **两步**（非原子），
多写者共享同一写入点时并发交错 ⇒ 静默丢行。实测（6 进程 × 20 条，三轮）
丢 29.2% / 36.7% / 39.2%，且 `add` 仍返回成功、worker 零报错。

`_audit.jsonl` 是**审计账本**（被 `admission` 等消费做状态推断），属不可丢面，
却走了该缺省路径。本守卫钉住：

  ① `durable=False`（缺省，访问计数类）：**允许**丢——不误伤既有 best-effort 语义；
  ② `durable=True`（审计账本类）：6 进程 × N 条并发 ⇒ **一行不丢**（核心判据）；
  ③ 写出的每一行都是合法 JSON（不得出现「粘连坏行」）；
  ④ 修复不得把缺省路径变成加锁路径（`durable=False` 不应创建 `.lock`）。

跑法（任意 cwd）：
    python -X utf8 -m md_cg.test_issue549_durable_append
退出码：全部通过 0，存在失败 1。

注：本守卫用**真实多进程**（子进程各自 append），不是同进程多线程——
症状只在跨进程共享写入点时出现。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_PASS = 0
_FAIL = 0

_N_PROC = 6
_N_EACH = 20

#: 子进程脚本：各自 append N 条，durable 由 argv 决定。
_CHILD = r'''
import os, sys
sys.path.insert(0, r"{repo}")
from md_cg.fsutil import append_jsonl
path, tag, durable = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
for i in range({n}):
    append_jsonl(path, {{"t": i, "op": "add", "id": "%s_%d" % (tag, i),
                        "actor": tag}}, durable=durable)
'''


def ok(cond, label, detail=None):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print("  [PASS] %s" % label)
    else:
        _FAIL += 1
        print("  [FAIL] %s%s" % (label, ("  <- " + repr(detail)) if detail is not None else ""))


def _run_concurrent(workdir: str, durable: bool):
    """起 _N_PROC 个子进程并发 append，返回 (valid_json_lines, expected)。"""
    target = os.path.join(workdir, "_log.jsonl")
    child = os.path.join(workdir, "child.py")
    with open(child, "w", encoding="utf-8") as fh:
        fh.write(_CHILD.format(repo=_REPO, n=_N_EACH))
    env = dict(os.environ)
    env["PYTHONPATH"] = _REPO
    env["PYTHONUTF8"] = "1"
    procs = [subprocess.Popen(
        [sys.executable, "-X", "utf8", "-B", child, target, "w%d" % k,
         "1" if durable else "0"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for k in range(_N_PROC)]
    for p in procs:
        p.wait()
    expected = _N_PROC * _N_EACH
    valid = 0
    if os.path.isfile(target):
        for line in open(target, encoding="utf-8", errors="replace").read().splitlines():
            if not line.strip():
                continue
            try:
                json.loads(line)
                valid += 1
            except ValueError:
                pass
    return valid, expected, target


def main() -> int:
    sandbox = tempfile.mkdtemp(prefix="issue549_")
    try:
        print("== G1 durable=True：多进程并发 ⇒ 一行不丢（核心判据）==")
        d1 = os.path.join(sandbox, "g1")
        os.makedirs(d1, exist_ok=True)
        valid1, exp1, tgt1 = _run_concurrent(d1, durable=True)
        ok(valid1 == exp1,
           "G1a durable=True：%d/%d 行合法 JSON（零丢失）" % (valid1, exp1),
           (valid1, exp1))
        ok(os.path.isfile(tgt1) and valid1 > 0, "G1b 目标文件确有内容", tgt1)

        print("== G2 durable=False：既有 best-effort 语义不被改变（不误伤）==")
        d2 = os.path.join(sandbox, "g2")
        os.makedirs(d2, exist_ok=True)
        valid2, exp2, _ = _run_concurrent(d2, durable=False)
        # 不作「必须丢」的断言（POSIX 上可能不丢）；只断言函数仍可用且不抛。
        ok(valid2 > 0, "G2a 缺省路径仍能写出记录（best-effort 保留）", valid2)

        print("== G3 durable=False 不得引入锁文件（缺省路径不变重）==")
        lock2 = os.path.join(d2, "_log.jsonl.lock")
        ok(not os.path.exists(lock2),
           "G3 缺省路径未创建 .lock（未把 best-effort 变成加锁路径）", lock2)
        lock1 = os.path.join(d1, "_log.jsonl.lock")
        ok(os.path.exists(lock1),
           "G3b durable=True 路径使用了 FileLock（.lock 存在）", lock1)

        print("== G4 写出的行必须都是合法 JSON（不得粘连坏行）==")
        raw1 = open(tgt1, encoding="utf-8").read() if os.path.isfile(tgt1) else ""
        lines1 = [l for l in raw1.splitlines() if l.strip()]
        bad = 0
        for l in lines1:
            try:
                json.loads(l)
            except ValueError:
                bad += 1
        ok(bad == 0, "G4 durable=True 无粘连坏行（%d 行全合法）" % len(lines1), bad)

        print("=" * 64)
        print("通过 %d / 失败 %d" % (_PASS, _FAIL))
        print("=" * 64)
        return 1 if _FAIL else 0
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
