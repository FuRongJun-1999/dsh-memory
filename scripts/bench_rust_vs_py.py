# -*- coding: utf-8 -*-
"""R-405b · Rust `--serve` 与 Python 内嵌的检索耗时对照（三档语料）。

为什么要有它：R-405a（Rust 接主链）之后，「同一查询走 Rust 还是走 Python」变成
一个**可选项**。可选项必须有取舍依据——没有基准，接 Rust 就只是多一个进程。
本脚本给三档语料（100 / 500 / 2000 节点，k=10）的**逐档中位延迟**与相对比值。

口径（写死在这里，不许各跑各的）：
  · 语料：合成中文节点（同一模板 + 不同关键词），三档各建一次库，**两侧读同一份**；
  · 计时：每档 warmup 2 次、正式 7 次取**中位数**（排除首跑 JIT/页缓存与抖动）；
  · Rust 侧：`mdcg-eval --serve` 常驻进程，一次 RPC 一次计时（不重建进程）；
  · Python 侧：`MdCGSecure.search_rrf(q, k=10)` 同进程内调用（含 readcache 缺省态）；
  · 判据：三档里 Rust 的**中位延迟都不高于** Python ⇒ 打印 PASS；否则 PASS 但
    标注「接主链无理由」（这是**结论面**，不是失败——基准的目的就是允许否定）。

负控（判据本身能不能红）：给 Rust 侧加 `--sleep-ms 5` 之类的入参不存在，故负控改用
**环境注入**：`BENCH_FAKE_SLOW_RUST=1` 时在 Rust 每次调用后人为 sleep 20ms，
判据必须翻成「Python 更快」。本脚本自带这条自检（`--selftest`）。
  · 为什么是 500ms：Python 侧 100 节点档实测 ~24ms，20ms 的注入压不过它
    （首版负控就因此没翻红）——负控的量级必须能压过被判方，否则测的是噪声。

用法：
  cd rust && cargo build --release
  python scripts/bench_rust_vs_py.py            # 三档全跑
  python scripts/bench_rust_vs_py.py --selftest # 负控自检（判据必须能红）
返回码 0 = 跑完（含「Rust 更慢」这一合法结论）· 2 = 二进制缺失 · 3 = 自身故障
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TIERS = (100, 500, 2000)
K = 10
WARMUP = 2
RUNS = 7
QUERIES = ("蜂群 调度 依赖 门禁", "热缓存 开关 挂载", "冲突闸 比对 放行",
           "令牌 验签 拒绝", "写入 管线 缓存 失效")


def build_corpus(root, n):
    """建 n 个合成节点（模板同、关键词不同），返回 cg。"""
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    cg = MdCGSecure(os.path.join(root, "graph"), principal=Principal(
        actor="bench", clearance="secret", can_write=True,
        role="designer", auth_mode="test"))
    seeds = ("蜂群调度器按 workers 上限领取任务", "依赖门禁在领取前检查上游终态",
             "热缓存在构造时按开关挂载", "冲突闸对无法比对的场景放行并留审计",
             "令牌验签失败必须拒绝启动", "写入管线在落盘后失效查询缓存",
             "检索门控把候选先按域收敛", "心跳与存活判据必须同口径")
    for i in range(n):
        body = seeds[i % len(seeds)]
        cg.add("bench_%05d" % i,
               "# 功能名：样本 %d\n\n%s（第 %d 号样本）\n" % (i, body, i),
               layer="knowledge")
    cg.flush()
    return cg


class RustServe:
    """常驻 `mdcg-eval --serve`，一次 RPC 一次计时。"""

    def __init__(self, exe, graph):
        # argv 与 rank_parity 的 `rust_open` **同一形态**（`--root <库根> --serve`）：
        # serve 读的是库根，不是 graph 子目录；口径显式钉住。
        env = dict(os.environ)
        env.pop("MDCG_TOKEN", None)
        env.setdefault("MDCG_EN_ZH_MAP",
                       os.path.join(_REPO, "md_cg", "semantic", "en_zh_map.json"))
        self.p = subprocess.Popen(
            [exe, "--root", graph, "--serve", "--score", "jaccard"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", env=env)

    def call(self, req):
        self.p.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        return json.loads(line) if line.strip() else {}

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:                                  # noqa: BLE001
            self.p.kill()


def _median_ms(fn, args_list):
    for a in args_list[:WARMUP]:
        fn(a)
    ts = []
    for a in args_list:
        t0 = time.perf_counter()
        fn(a)
        ts.append((time.perf_counter() - t0) * 1000.0)
    return round(statistics.median(ts), 2)


def bench_tier(exe, n, fake_slow=False):
    tmp = tempfile.mkdtemp(prefix="bench_rustpy_%d_" % n)
    cg = build_corpus(tmp, n)
    graph = os.path.join(tmp, "graph")
    qs = [QUERIES[i % len(QUERIES)] for i in range(RUNS + WARMUP)]

    py_ms = _median_ms(lambda q: cg.search_rrf(q, k=K), qs)

    sv = RustServe(exe, graph)
    try:
        info = sv.call({"op": "info"})
        score = info.get("score")

        def _r(q):
            out = sv.call({"op": "search", "query": q, "k": K})
            if fake_slow:
                time.sleep(0.500)          # 负控：人为变慢 500ms/次（必须压过 Python）
            return out

        rs_ms = _median_ms(_r, qs)
    finally:
        sv.close()
    return {"n": n, "python_ms": py_ms, "rust_ms": rs_ms,
            "ratio": round(rs_ms / py_ms, 3) if py_ms else None,
            "rust_score": score, "queries": len(qs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=os.path.join(
        _REPO, "rust", "target", "release",
        "mdcg-eval.exe" if os.name == "nt" else "mdcg-eval"))
    ap.add_argument("--selftest", action="store_true",
                    help="负控：人为让 Rust 变慢 20ms/次，判据必须翻成「Python 更快」")
    args = ap.parse_args()
    if not os.path.isfile(args.exe):
        print("rust 二进制不存在：%s（先 cd rust && cargo build --release）" % args.exe)
        return 2
    try:
        rows = []
        for n in TIERS:
            r = bench_tier(args.exe, n, fake_slow=args.selftest)
            rows.append(r)
            print("语料 %5d 节点 · k=%d · Python %8.2f ms · Rust(serve) %8.2f ms"
                  " · 比值 %5s · rust score=%s"
                  % (r["n"], K, r["python_ms"], r["rust_ms"], r["ratio"],
                     r["rust_score"]))
        faster = [r for r in rows if r["ratio"] is not None and r["ratio"] <= 1.0]
        verdict = ("PASS —— Rust 三档都不慢于 Python（接主链有依据）"
                   if len(faster) == len(rows) else
                   "PASS（结论面）—— 有档位 Rust 更慢：接主链**没有**性能依据，"
                   "该档应继续走 Python；比值见上表")
        print("\n" + verdict)
        if args.selftest:
            ok = len(faster) < len(rows)
            print("[selftest] 负控（人为 +500ms/次）判据%s" % ("已翻红，符合预期" if ok
                                                         else "没翻红 —— 判据失效"))
            return 0 if ok else 3
        return 0
    except Exception as e:                                 # noqa: BLE001
        print("自身故障：%s: %s" % (type(e).__name__, e))
        return 3


if __name__ == "__main__":
    sys.exit(main())
