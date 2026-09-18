# -*- coding: utf-8 -*-
"""倒排发布表构建/查看（S7 候选层）。

用法：
  python -X utf8 -m md_cg.build_postings --root <库根>            # 全量重建（幂等）
  python -X utf8 -m md_cg.build_postings --root <库根> --stats     # 只看现状
  python -X utf8 -m md_cg.build_postings --root <库根> --limit 500 # 抽样构建（冒烟用）

说明：发布表是**派生索引**（<root>/_postings.json + _postings_meta.json），
不修改任何节点内容；节点新增/修改后需重建（v1 不做增量维护）。
"""
import argparse
import json
import sys

from . import postings
from .mdcg import MdCG


# 生效条件：无条件解析参数（root 必填，stats/limit 可选）；stats 为真时只打印统计并返回 0；
# 否则以 MdCG(root) 打开库、调用 postings.build(cg, limit) 并打印 stats JSON，返回 0。
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args(argv)
    if a.stats:
        print(json.dumps(postings.stats(a.root), ensure_ascii=False))
        return 0
    cg = MdCG(a.root)
    st = postings.build(cg, limit=a.limit)
    print(json.dumps(st, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
