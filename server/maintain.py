#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灵枢主库只读自维护（账54 收口）。

生效条件：由 cron 每日调用一次；不传 --apply 时全部为只读（dry_run）。
子功能：scrub.sweep 抽样自净（dry_run） + 把一轮读数追加进 _sustain.jsonl。
执行：import md_cg → 构造 MdCGSecure → scrub.sweep(cg, n=48, dry_run=True, apply_calibration=False)。
验证方式：退出码 0 且 _sustain.jsonl 新增一行 op=heal action=maintain。
不适用条件：不适用于需要真删/真改的场景（那要走 decontaminate(dry_run=False)，
  属不可逆操作，必须人工触发）。
"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.mdcos import MdCGSecure
from md_cg import scrub

ROOT = os.environ.get("MDCG_ROOT", "/home/ubuntu/mdcg-data")
TOKEN = None
try:
    with open(os.path.expanduser("~/.mdcg/run-server.env"), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("export MDCG_TOKEN="):
                TOKEN = line.split("=", 1)[1].strip().strip('"').strip("'")
except OSError:
    pass
if not TOKEN:
    print("拿不到 MDCG_TOKEN", file=sys.stderr); sys.exit(2)

from md_cg.tokens import verify_token
principal = verify_token(TOKEN)

def main():
    t0 = time.time()
    cg = MdCGSecure(ROOT, principal=principal, autoflush=8)
    try:
        rep = scrub.sweep(cg, n=48, dry_run=True, hops=2, strategy="stratified",
                          apply_calibration=False, actor="maintain")
    finally:
        try:
            cg.close()
        except Exception:
            pass
    rec = {
        "t": time.time(), "op": "heal", "action": "maintain",
        "detail": "scrub.sweep(n=48, dry_run=True) 只读自维护",
        "pid": os.getpid(),
        "n_high_medium": rep.get("n_high_medium"),
        "ok": rep.get("ok"),
        "took_ms": int((time.time() - t0) * 1000),
    }
    log = os.path.join(ROOT, "_sustain.jsonl")
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps({k: rec[k] for k in ("n_high_medium", "ok", "took_ms")}, ensure_ascii=False))
    # 摘要：分层问题分布
    for k in ("strata", "calibration"):
        if k in rep:
            print(k, json.dumps(rep[k], ensure_ascii=False)[:300])
    return 0 if rep.get("ok") else 1

if __name__ == "__main__":
    sys.exit(main())