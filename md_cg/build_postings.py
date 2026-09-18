# -*- coding: utf-8 -*-
"""倒排发布表构建/查看（S7 候选层）。

用法：
  python -X utf8 -m md_cg.build_postings --root <库根>            # 全量重建（幂等）
  python -X utf8 -m md_cg.build_postings --root <库根> --stats     # 只看现状
  python -X utf8 -m md_cg.build_postings --root <库根> --limit 500 # 抽样构建（冒烟用，永不算新鲜）
  python -X utf8 -m md_cg.build_postings --root <库根> --if-stale  # 过期才重建（守候环用）

说明：发布表是**派生索引**（<root>/_postings.json + _postings_meta.json），
不修改任何节点内容；节点新增/修改后需重建（v1 不做增量维护）。
"""
import argparse
import json
import sys

from . import postings
from .mdcg import MdCG


# 生效条件：无条件解析参数（root 必填；stats/limit/if-stale 可选；if-stale 与 limit 互斥则 argparse 报错并退出 2）；
# stats 为真时打开库打印 stats（含 stale_reason）并返回 0；if-stale 为真且快照新鲜时打印 {"rebuilt": false} 返回 0、
# 过期时重建并打印 stats（附 rebuilt_from=过期原因）；否则一律重建并打印 stats，返回 0。
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--if-stale", action="store_true", dest="if_stale")
    a = ap.parse_args(argv)
    if a.if_stale and a.limit:
        ap.error("--if-stale 与 --limit 互斥（抽样表不可当作新鲜快照）")
    cg = MdCG(a.root)
    nodes = cg.index.get("nodes") or {}
    if a.stats:
        print(json.dumps(postings.stats(a.root, nodes), ensure_ascii=False))
        return 0
    if a.if_stale:
        sr = postings.stale_reason(a.root, nodes)
        if not sr:
            print(json.dumps({"rebuilt": False, "reason": "fresh"}, ensure_ascii=False))
            return 0
        st = postings.build(cg)
        print(json.dumps(dict(st, rebuilt_from=sr), ensure_ascii=False))
        return 0
    st = postings.build(cg, limit=a.limit)
    print(json.dumps(st, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
