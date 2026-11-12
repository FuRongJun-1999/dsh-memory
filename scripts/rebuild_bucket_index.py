# -*- coding: utf-8 -*-
"""重建日桶 / 会话桶索引（bucketindex）。

用法：python scripts/rebuild_bucket_index.py --root <mdcg 根>
默认读环境变量 MDCG_ROOT / MDCG_DATA_ROOT，再回落仓内配置。

何时重建：写入高峰后、或发现桶内条数与 info 的 node_count 明显不符时。
代价：主库 34,218 节点实测约 3–5 秒（只读索引面，不读节点正文）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import bucketindex as bi  # noqa: E402
from md_cg import mdcos  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=(os.environ.get("MDCG_ROOT")
                                      or os.environ.get("MDCG_DATA_ROOT") or ""),
                    help="mdcg 数据根（缺省读环境变量）")
    a = ap.parse_args()
    root = a.root
    if not root or not os.path.isdir(root):
        print("需要 --root 或 MDCG_ROOT 指向 mdcg 数据根", file=sys.stderr)
        return 2
    store = mdcos.MdCGOS(root, actor="bucketindex")
    t0 = time.time()
    stats = bi.build(store, write=True)
    stats["seconds"] = round(time.time() - t0, 2)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())