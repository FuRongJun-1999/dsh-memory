# -*- coding: utf-8 -*-
"""issue #29 端到端 rank 对拍：Python search_rrf vs Rust mdcg-eval --serve。

同一认知图（合成中英混合语料）上，两侧对同批 query 的 top-k 结果做
**逐位比对**（非集合、非 hit@k——那两类守卫看不见路内排序漂移）。
用法：
  先构建 rust 二进制：cargo build --release（rust/ 下）
  再跑：python scripts/rank_parity.py --exe rust/target/release/mdcg-eval
返回码 0 = 逐位一致。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

QUERIES = [
    "慈善跑 心理健康 发声 意识 意义",
    "newuser 探针结论",
    "灵枢 hotcache 设计",
    "The compiler wrote tests",
    "蜂群调度 依赖门禁",
    "数据库 迁移 备份 策略",
    "agent review verdict",
    "检索 门控 收敛",
    "安全 审计 令牌",
    "memory recall pipeline",
]


def build_cogmap(root):
    """合成中英混合语料（覆盖英文归一化与中文 2-gram 两条口径线）。"""
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    cg = MdCGSecure(os.path.join(root, "graph"), principal=Principal(
        actor="parity", clearance="secret", can_write=True,
        role="designer", auth_mode="test"))
    zh = ["蜂群调度器按 workers 上限领取任务", "依赖门禁在领取前检查上游终态",
          "热缓存在构造时按开关挂载", "冲突闸对无法比对的场景放行并留审计",
          "自证拒绝要求验证方与编译方不同主体", "检索门控把候选先按域收敛",
          "令牌验签失败必须拒绝启动", "写入管线在落盘后失效查询缓存",
          "评审队列的判据指纹随提案落盘", "心跳与存活判据必须同口径"]
    en = ["The compiler generates candidates from dialog",
          "Reviewers must be independent from compilers",
          "Hot cache speeds up repeated queries",
          "Dependency gate checks upstream final states",
          "Conflict gate defers unmatched comparisons",
          "Search fusion merges four retrieval paths",
          "Token verification is fail closed on mismatch",
          "Heartbeat freshness guards single instance",
          "Audit records store hashes not payloads",
          "Cold verification enqueues after writes"]
    n = 0
    for i in range(15):
        for kind, corpus in (("zh", zh), ("en", en)):
            body = corpus[(i + len(kind)) % len(corpus)]
            node = f"parity_{kind}_{i:02d}"
            cg.add(node, f"# 功能名：{kind} 样本 {i}\n# 正文：{body} 样本{i}",
                   layer="knowledge")
            n += 1
    cg.flush()
    return n


def python_topk(root, queries, k=5):
    """返回 {query: [(id, score), ...]}。"""
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    cg = MdCGSecure(os.path.join(root, "graph"), principal=Principal(
        actor="parity", clearance="secret", can_write=True,
        role="designer", auth_mode="test"))
    out = {}
    for q in queries:
        results, _meta = cg.search_rrf(q, k=k)
        out[q] = [(_x[0].get("id") or _x[0].get("path") or "", round(_x[1], 6))
                  for _x in results]
    return out


def rust_topk(exe, root, queries, k=5):
    """返回 {query: [(id, score), ...]}。"""
    env = dict(os.environ)
    env.pop("MDCG_TOKEN", None)          # 对拍面与本测试无关，防部署 env 干扰
    p = subprocess.Popen([exe, "--root", root, "--serve"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", env=env)
    out = {}
    try:
        for q in queries:
            req = json.dumps({"op": "search", "query": q, "k": k}) + "\n"
            p.stdin.write(req)
            p.stdin.flush()
            line = p.stdout.readline()
            if not line:
                err = p.stderr.read() if p.stderr else ""
                raise RuntimeError(f"rust serve 输出关闭：{err[:500]}")
            resp = json.loads(line)
            hits = resp.get("hits") or resp.get("results") or []
            pairs = []
            for h in hits:
                if isinstance(h, dict):
                    pairs.append((h.get("id") or h.get("node") or "",
                                  h.get("score")))
                else:
                    pairs.append((str(h), None))
            out[q] = pairs
    finally:
        try:
            p.stdin.close()
            p.wait(timeout=5)
        except Exception:
            p.kill()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "rust", "target", "release", "mdcg-eval.exe"
        if os.name == "nt" else "mdcg-eval"))
    ap.add_argument("--root", default=None, help="复用已建库（缺省新建临时库）")
    args = ap.parse_args()

    if not os.path.isfile(args.exe):
        print(f"rust 二进制不存在：{args.exe}（先 cd rust && cargo build --release）")
        return 2

    if args.root:
        root = args.root
        n = sum(len(files) for _, _, files in os.walk(root))
    else:
        root = tempfile.mkdtemp(prefix="mdcg_parity_")
        n = build_cogmap(root)
    print(f"语料节点 ~{n} · queries={len(QUERIES)} · exe={args.exe}")

    py = python_topk(root, QUERIES)
    rs = rust_topk(args.exe, os.path.join(root, "graph"), QUERIES)

    order_ok = set_ok = top1_ok = total = 0
    for q in QUERIES:
        a = py.get(q) or []
        b = rs.get(q) or []
        ids_a = [x[0] for x in a]
        ids_b = [x[0] for x in b]
        total += 1
        if ids_a[:1] == ids_b[:1]:
            top1_ok += 1
        if set(ids_a) == set(ids_b):
            set_ok += 1
        if ids_a == ids_b:
            order_ok += 1
        else:
            print(f"  [DIFF] {q}")
            print(f"    py  ={a}")
            print(f"    rust={b}")
    print(f"逐位一致 {order_ok}/{total} · 集合一致 {set_ok}/{total} · "
          f"top-1 一致 {top1_ok}/{total}")
    return 0 if order_ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
