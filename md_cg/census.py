# -*- coding: utf-8 -*-
"""条件空间分布普查 · md 认知图方案 P0 前置判据（风险1 go/no-go）

回答：condition_space 四元组作为分桶键，在真实库上是否有区分度？
任何新库接入前都应先跑一遍——分桶键是否可用只能由数据决定，不能由设计假设决定。

用法：python -m md_cg.census <sqlite.db>
"""
import sqlite3, json, sys, io, collections, hashlib


def load(db):
    c = sqlite3.connect(db)
    rows = c.execute("select id, layer, condition_space, tags from nodes").fetchall()
    out = []
    for nid, layer, cs, tags in rows:
        try:
            d = json.loads(cs) if cs else {}
        except Exception:
            d = {}
        try:
            t = json.loads(tags) if tags else []
        except Exception:
            t = []
        out.append((nid, layer, d, t))
    return out


def bucket(d, keys):
    return hashlib.sha256(
        json.dumps({k: d.get(k) for k in keys}, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:10]


def report(name, rows, keyfn):
    cnt = collections.Counter(keyfn(d, t) for _, _, d, t in rows)
    n = len(rows)
    nb = len(cnt)
    top = cnt.most_common(5)
    singles = sum(1 for v in cnt.values() if v == 1)
    print(f"\n--- {name} ---")
    print(f"  桶数 {nb} / 节点 {n}  → 平均桶大小 {n / nb:.1f}")
    print(f"  最大桶 {top[0][1]} 节点 = 全库 {top[0][1] / n * 100:.1f}%")
    print(f"  单例桶 {singles} 个 = 桶数 {singles / nb * 100:.1f}% (碎片化指标)")
    print(f"  top5 桶大小: {[v for _, v in top]}")
    # 关键判据：随机情境命中一个桶后，需要扫的节点期望占比
    exp = sum(v * v for v in cnt.values()) / n / n
    print(f"  ★条件路由后期望扫描占比 = {exp * 100:.1f}%  (100%=退化成全量, 越低越有效)")


def by_keys(keys):
    return lambda d, t: hashlib.sha256(
        json.dumps({k: d.get(k) for k in keys}, sort_keys=True,
                   ensure_ascii=False).encode()).hexdigest()[:10]


def main(db):
    rows = load(db)
    print(f"库: {db}")
    print(f"总节点: {len(rows)}")
    print(f"分层: {dict(collections.Counter(l for _, l, _, _ in rows))}")

    # 各维度取值分布
    for k in ("observation_position", "observation_tool", "existence_constraint"):
        c = collections.Counter(str(d.get(k)) for _, _, d, _ in rows)
        print(f"\n[{k}] 不同取值 {len(c)} 种，top5:")
        for v, n in c.most_common(5):
            print(f"    {n:6d} ({n / len(rows) * 100:5.1f}%)  {v[:40]}")

    tw = collections.Counter(str(d.get("time_window")) for _, _, d, _ in rows)
    print(f"\n[time_window] 不同取值 {len(tw)} 种 / {len(rows)} 节点"
          f"  → 唯一率 {len(tw) / len(rows) * 100:.1f}%")

    report("方案A·全四元组（文档原方案，含 time_window）", rows,
           by_keys(["observation_position", "observation_tool",
                    "time_window", "existence_constraint"]))
    report("方案B·三元组（排除 time_window）", rows,
           by_keys(["observation_position", "observation_tool", "existence_constraint"]))
    report("方案C·双元组（position + tool）", rows,
           by_keys(["observation_position", "observation_tool"]))

    # 实际采用的键：归一化域（tags 的 domain: 优先，回退 observation_position 前缀）
    from . import routing
    report("方案D·归一化路由键（★md_cg 采用）", rows,
           lambda d, t: routing.route_key(d, t))


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    main(sys.argv[1] if len(sys.argv) > 1 else "wisdom-book-cloud-new.db")
