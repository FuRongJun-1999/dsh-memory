# -*- coding: utf-8 -*-
"""G2 关系类型分布统计（只读，不改任何东西）。

# 功能名：关系类型分布统计（G2）
# 生效条件：需要核对全库 relation_type 的真实分布/未标注率/孤例时
# 子功能：①分布表 ②未标注率 ③孤例列表 ④白名单外类型列表
# 执行：python -X utf8 scripts/check_relation_types.py [--root <库根>] [--json]
# 验证方式：tests/test_relation_type_whitelist_guard.py 的同名断言
# 不适用条件：不判语义正误；不把空串当违规
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import relations as R  # noqa: E402


def _load_edges(root):
    """从认知图索引取全部边的 relation_type 序列。"""
    from md_cg import MdCG
    cg = MdCG(root)
    try:
        nodes = (cg.index or {}).get("nodes") or {}
        out = []
        for _nid, e in nodes.items():
            for ed in (e.get("edges") or []):
                if isinstance(ed, dict):
                    out.append(ed.get("relation_type") or ed.get("relation") or "")
        return out
    finally:
        try:
            cg.close()
        except Exception:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("MDCG_ROOT") or "")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--gate-mode", default=R.DEFAULT_MODE,
                    help="仅供展示：由调用方传入，本脚本不读环境变量")
    a = ap.parse_args(argv)
    if not a.root:
        print("缺库根：传 --root 或设 MDCG_ROOT", file=sys.stderr)
        return 2
    if not os.path.isdir(a.root):
        print("库根不存在：%s" % a.root, file=sys.stderr)
        return 2

    edges = _load_edges(a.root)
    dist = R.distribution(edges)
    total = sum(dist.values())
    unknown = sorted(k for k in dist if not R.reltype_verdict(k)[0])

    rep = {
        "root": a.root,
        "edges_total": total,
        "types": {k: v for k, v in sorted(dist.items(), key=lambda kv: -kv[1])},
        "unlabeled_rate": round(R.unlabeled_rate(dist), 4),
        "singletons": R.singletons(dist),
        "unknown_types": unknown,
    }
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print("库根：%s" % rep["root"])
        print("边总数：%d ；类型数：%d" % (total, len(dist)))
        print("未标注率：%.1f%%" % (rep["unlabeled_rate"] * 100))
        print("")
        print("分布：")
        for k, v in list(rep["types"].items())[:20]:
            print("   %-20s %6d" % ((k or "(空)")[:20], v))
        print("")
        print("孤例（频次 1）：%s" % (rep["singletons"] or "无"))
        print("白名单外类型：%s" % (unknown or "无"))

    # 退出码：仅当出现「白名单外且非已知孤例」才红
    bad = [k for k in unknown if k not in R.KNOWN_SINGLETONS]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
