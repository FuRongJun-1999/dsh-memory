# -*- coding: utf-8 -*-
"""收据（receipt）机制：把「完成」变成**可复现的命令输出**。

用法（读数一律 python -u）：
  python -u scripts/receipt.py --write <name> --cmd '["python","-u","-c","print(1)"]'
  python -u scripts/receipt.py --check <name>
  python -u scripts/receipt.py --list

**「可复现」的定义（本条的核心）＝重跑得到同一结果**：rc 相同 ∧ digest 相同。

**存放策略：收据是「关于某次运行的证据」，属运行期产物 ⇒ 不入库**（`.gitignore` 有 `/receipts/*.json`，
仅保留 `receipts/.gitkeep`）。理由：入库会（a）**陈化**、（b）被误当「**现在绿**」—— 正是 C4 里 (a) 之弊。
**发布证据**（如某次全量门禁的绿）应落在 CI / 发布产物 / 日志，**不是仓内文件**。

设计要点（都来自本会话实测教训）：
  · **不许截断**：digest 覆盖 stdout **全文**（`stdout_tail` 只用于展示，不参与判定）；
    理由：本会话四次「证据被截断 ⇒ 断言全域出错」，其中一次是发任务方自己。
  · **异常与判否分开**：跑不起来（OSError/超时）与 rc≠0（判否）**各自留痕、不共用一个信号**
    （一个观测只对应一个原因 —— 本会话「SKIP 冒充 PASS」同族）。
  · **判据规模**：收据只证明「该命令此刻可复现」，**不证明**它覆盖了要断言的全域。
    哪条腿不判别：本机制**不判**「命令选得对不对」——选错命令的收据同样可复现。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECEIPTS = os.path.join(_REPO, "receipts")
TAIL_LINES = 30


# 生效条件：argv 为非空字符串列表、cwd 存在即成立；spawn 捕获 stdout/stderr（text=True, encoding=utf-8, errors=replace, PYTHONUTF8=1）；
# 返回 (rc, out, err, exc)：正常结束 rc 为整数、out/err 为文本、exc=None；跑不起来时 rc=None、exc 为异常字符串（**与 rc≠0 分开**）。
def run_cmd(argv, cwd=None, timeout=600):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    try:
        pr = subprocess.run(list(argv), cwd=cwd or _REPO, capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            env=env, timeout=timeout, shell=False)
        return pr.returncode, pr.stdout or "", pr.stderr or "", None
    except Exception as e:                                   # noqa: BLE001
        return None, "", "", "%s: %s" % (type(e).__name__, e)


# 生效条件：text 为字符串即成立；返回 sha256(utf-8 bytes) 十六进制摘要（**覆盖全文**，不截断）。
def digest_of(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _tail(text):
    ls = text.splitlines()
    if len(ls) <= TAIL_LINES:
        return text
    return "\n".join(["...[前 %d 行省略；digest 覆盖全文]" % (len(ls) - TAIL_LINES)] + ls[-TAIL_LINES:])


# 生效条件：name 非空；跑 argv 后把 rc/digest(全文)/stdout_tail/cwd/ts/exception 写 receipts/<name>.json，返回该 dict。
def write_receipt(name, argv, cwd=None):
    rc, out, err, exc = run_cmd(argv, cwd=cwd)
    rec = {"name": name, "cmd": list(argv), "cwd": cwd or _REPO,
           "rc": rc, "digest": digest_of(out), "stdout_bytes": len(out.encode("utf-8")),
           "stdout_tail": _tail(out), "stderr_tail": _tail(err),
           "exception": exc, "ts": int(time.time())}
    os.makedirs(RECEIPTS, exist_ok=True)
    p = os.path.join(RECEIPTS, name + ".json")
    io.open(p, "w", encoding="utf-8", newline="\n").write(
        json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    return rec


# 生效条件：path 指向一份 json 收据即成立；**重跑其 cmd**，返回 (ok, detail)：rc 与 digest 均相同才 ok；
# 跑不起来（exception）与判否（rc/digest 不符）**在 detail 里分开记**，不共用一个信号。
def check_receipt(path):
    rec = json.loads(io.open(path, encoding="utf-8").read())
    rc, out, err, exc = run_cmd(rec["cmd"], cwd=rec.get("cwd"))
    dg = digest_of(out)
    d = {"rc": rc, "rc_expect": rec["rc"], "digest": dg[:12],
         "digest_expect": rec["digest"][:12], "exception": exc}
    if exc is not None:
        return False, dict(d, reason="跑不起来（异常，与判否分开）")
    if rc != rec["rc"]:
        return False, dict(d, reason="rc 不符")
    if dg != rec["digest"]:
        return False, dict(d, reason="digest 不符（输出不可复现）")
    return True, d


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--write")
    ap.add_argument("--check")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--cmd", help="argv 列表 JSON")
    a = ap.parse_args(argv)
    if a.write:
        if not a.cmd:
            print("--write 需要 --cmd（argv 列表 JSON）"); return 2
        rec = write_receipt(a.write, json.loads(a.cmd))
        print(json.dumps({k: rec[k] for k in ("name", "rc", "digest", "exception")},
                         ensure_ascii=False))
        return 0 if rec["exception"] is None else 1
    if a.check:
        p = os.path.join(RECEIPTS, a.check + ".json")
        if not os.path.exists(p):
            print("未找到收据: %s" % p); return 2
        ok, d = check_receipt(p)
        print("%s %s %s" % ("OK  " if ok else "FAIL", a.check, json.dumps(d, ensure_ascii=False)))
        return 0 if ok else 1
    if a.list:
        if not os.path.isdir(RECEIPTS):
            print("(无 receipts/ 目录)"); return 0
        names = sorted(f for f in os.listdir(RECEIPTS) if f.endswith(".json"))
        print("收据 %d 份：" % len(names))
        for f in names:
            r = json.loads(io.open(os.path.join(RECEIPTS, f), encoding="utf-8").read())
            print("  %-28s rc=%-5s digest=%s ts=%s" % (f[:-5], r["rc"], r["digest"][:12], r["ts"]))
        return 0
    ap.print_help(); return 0


if __name__ == "__main__":
    sys.exit(main())