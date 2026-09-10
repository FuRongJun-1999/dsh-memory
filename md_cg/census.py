# -*- coding: utf-8 -*-
"""条件空间分布普查 · md 认知图方案 P0 前置判据（风险1 go/no-go）

回答：condition_space 四元组作为分桶键，在真实库上是否有区分度？
任何新库接入前都应先跑一遍——分桶键是否可用只能由数据决定，不能由设计假设决定。

被测对象是 **md 文档记忆库**：直接遍历根目录下的节点 .md，解析 frontmatter。
（旧版读 sqlite `nodes` 表；本仓库按「用新的 md 文档记忆库做验证」改为 md 原生，
不再依赖任何外部数据库。）

用法：python -m md_cg.census [md_root]      # 默认 data/mdcg
"""
import os
import sys
import json
import hashlib
import collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import nodefile, routing

DEFAULT_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "mdcg")


def load(root):
    """遍历 md 记忆库根，返回 [(node_id, layer, condition_space, tags), ...]。

    只认能被 nodefile.loads 解析出 frontmatter 的 .md —— 解析不出说明不是节点文件
    （例如随手放进来的说明文档），直接跳过而不是塞进空条件桶污染统计。
    """
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                with open(p, encoding="utf-8") as f:
                    fm, _content = nodefile.loads(f.read())
            except OSError:
                continue
            if not fm:
                continue
            nid = fm.get("id") or fn[:-3]
            layer = fm.get("layer") or os.path.basename(dirpath)
            out.append((nid, layer, fm.get("condition_space") or {},
                        fm.get("tags") or []))
    return out


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


def main(root):
    rows = load(root)
    print(f"md 记忆库: {root}")
    print(f"总节点: {len(rows)}")
    if not rows:
        print("\n该根下没有可解析的节点 .md，无法普查。")
        print("  · 空库：先跑 python -m md_cg.test_p0 生成自建语料，再执行")
        print("    python -m md_cg.census _md_cg_p0")
        print("  · 真实库：python -m md_cg.census data/mdcg（需已灌入节点）")
        return 2
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
    report("方案D·归一化路由键（★md_cg 采用）", rows,
           lambda d, t: routing.route_key(d, t))
    return 0


if __name__ == "__main__":
    # 用 reconfigure 而非「包一层 TextIOWrapper」：后者在 stdout 重定向到文件时
    # 会在解释器退出阶段丢缓冲（实测只落盘 444 字节），CI 里会看不到失败原因。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROOT))
