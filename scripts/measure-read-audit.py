# -*- coding: utf-8 -*-
"""读侧审计写放大测量（G1 守卫的量具）。

在 `_read_many` 边界量：一次批量读水合 N 个密文节点，往 `_crypto.jsonl` 追加多少行。
生产实测（2026-10-21，在役库 10 013 节点 / 网关主体）每次检索 5 910 行 / 1.35 MB
——审计变成写放大，真异常被埋掉。聚合后应为 O(1)：每次批量读至多 1 行。

用法：
  python scripts/measure-read-audit.py            # 默认 N=200
  python scripts/measure-read-audit.py --n 500    # 自定义规模
输出一行 JSON：{"n":…, "decrypted":…, "delta":…, "ops":{…}}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import crypto                      # noqa: E402
from md_cg.mdcos import MdCGSecure            # noqa: E402
from md_cg.security import Principal          # noqa: E402


def _lines(root):
    p = os.path.join(root, "_crypto.jsonl")
    if not os.path.exists(p):
        return 0
    with open(p, encoding="utf-8") as f:
        return sum(1 for _ in f)


def _ops(root):
    out = {}
    for rec in crypto.audit_records(root):
        out[rec.get("op")] = out.get(rec.get("op"), 0) + 1
    return out


def measure(n=200, sharing=False):
    os.environ["MDCG_TENANT_DEK_SHARING"] = "1" if sharing else "0"
    tmp = tempfile.mkdtemp(prefix="read_audit_")
    kek = os.urandom(32)
    w = MdCGSecure(tmp, principal=Principal(
        tenant="t1", actor="alice", clearance="private",
        can_write=True, can_admin=True), master_key=kek)
    for i in range(n):
        w.add("n%d" % i, "# 功能名：条目%d\n# 执行：测试\n\n银行卡尾号 8888 第 %d 条\n"
              % (i, i), sensitivity="private")
    w.close()
    # 读方拿不到 KEK（＝生产网关缺 MDCG_MASTER_KEY 的形态）⇒ dek 为空
    crypto.load_master_key = lambda *a, **k: None
    r = MdCGSecure(tmp, principal=Principal(
        tenant="t1", actor="bob", clearance="secret",
        can_write=True, can_admin=True))
    entries = [dict(e, id=nid) for nid, e in r.index["nodes"].items()]
    before = _lines(tmp)
    docs = r._read_many(entries, {"scanned": 0})
    after = _lines(tmp)
    return {"n": n, "sharing": sharing, "decrypted": len(docs),
            "delta": after - before, "ops": _ops(tmp)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--sharing", action="store_true")
    a = ap.parse_args()
    print(json.dumps(measure(a.n, a.sharing), ensure_ascii=False))
