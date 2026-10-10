"""Controlled CCG parser timing with retrieval/consistency parity.

python -X utf8 -m md_cg.bench_ccg_heading --nodes 1000 --rounds 11

Uses synthetic data only. Alternates the previous policy-regex implementation
and the current parser in one process, with the same memory/cache state.
Reports timing rather than enforcing hardware-dependent speed thresholds.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics
import tempfile
import time
from unittest import mock

from . import nodefile
from .mdcos import MdCGOS


# 生效条件：line 与 mark 遵循标题解析接口时执行优化前的策略正则，命中返回字段后余文，否则返回 None；仅用于基准对照。
def reference_heading(line, mark):
    match = re.match(r"^#\s*" + re.escape(mark), line or "")
    return (line or "")[match.end():] if match else None


# 生效条件：i 为整数时生成一条合成六要素记忆；奇数使用裸标题，偶数使用行内冒号，端口与重试次数由 i 决定。
def card(i):
    fields = (("功能名", "网关心跳参数 " + str(i)),
              ("生效条件", "网关在线且心跳已启用"), ("子功能", "端口取值与退避次数"),
              ("执行", "监听端口 %d，失败后重试 %d 次" % (9000 + i % 100, 1 + i % 7)),
              ("验证方式", "读取网关配置并连接端口"), ("不适用条件", "网关离线"))
    sep = "\n" if i % 2 else "："
    return "\n".join("# " + k + sep + v for k, v in fields) + "\n客户端使用长连接轮询。\n超时触发重连。\n"


# 生效条件：value 可被 JSON 序列化时返回按键排序的 UTF-8 JSON 的 SHA256，用于核对结果一致性。
def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


# 生效条件：nodes 与 rounds 都大于零时构建临时合成库，交替对照旧/新解析函数，比较解析、检索和一致性结果并返回中位耗时与摘要；结果不同抛 AssertionError；无真实记忆读写，finally 关闭库。
def benchmark(nodes=1000, rounds=11):
    if nodes < 1 or rounds < 1:
        raise ValueError("nodes and rounds must be positive")
    docs = [card(i) for i in range(nodes)]
    optimized = nodefile._ccg_heading_rest
    variants = (("reference", reference_heading), ("optimized", optimized))
    with tempfile.TemporaryDirectory(prefix="ccg_heading_bench_") as tmp:
        cg = MdCGOS(tmp)
        try:
            for i, doc in enumerate(docs):
                cg.add("bench_%04d" % i, doc, layer="knowledge")
            cg.flush()

            # 生效条件：闭包 docs 已构建时返回每条文档的六要素齐全度、字段值、正向正文与去要素正文。
            def parse():
                return [(nodefile.ccg_completeness(d),
                         tuple(nodefile.ccg_field_value(d, m) for m in nodefile.CCG_MARKS),
                         nodefile.positive_body(d), nodefile._strip_ccg_segments(d)) for d in docs]

            # 生效条件：临时 cg 已填充时执行三种查询各两种检索入口，record=False 不记录访问，返回原始结果与元数据。
            def retrieve():
                return [method(q, k=10, record=False)
                        for q in ("网关心跳端口", "失败后重试", "客户端超时重连")
                        for method in (cg.search, cg.search_rrf)]

            # 生效条件：临时 cg 已填充时对一条合成记忆做一致性检查，不建工单、不落日志；剥除运行时 t 后返回结果。
            def consistency():
                result = cg.check_consistency(card(nodes + 1), layer="knowledge",
                                              auto_flywheel=False, log_write=False)
                return {k: v for k, v in result.items() if k != "t"}

            report = {"nodes": nodes, "rounds": rounds, "workloads": {}}
            for workload, fn in (("parser", parse), ("retrieval_six_queries", retrieve),
                                 ("consistency", consistency)):
                samples = {label: [] for label, _ in variants}
                outputs = {}
                for _, heading in variants:
                    with mock.patch.object(nodefile, "_ccg_heading_rest", heading):
                        for _ in range(3):
                            fn()
                for i in range(rounds):
                    for label, heading in variants[::(-1 if i % 2 else 1)]:
                        with mock.patch.object(nodefile, "_ccg_heading_rest", heading):
                            start = time.perf_counter()
                            outputs[label] = fn()
                            samples[label].append((time.perf_counter() - start) * 1000)
                if outputs["reference"] != outputs["optimized"]:
                    raise AssertionError(workload + " outputs differ")
                before, after = (statistics.median(samples[label]) for label, _ in variants)
                report["workloads"][workload] = {
                    "reference_median_ms": before, "optimized_median_ms": after,
                    "speedup": before / after, "samples_ms": samples,
                    "identical": True, "sha256": digest(outputs["optimized"])}
            return report
        finally:
            cg.close()


# 生效条件：CLI 参数可解析时执行受控基准，打印 JSON；传 --output 时另以 UTF-8 保存报告。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=1000)
    parser.add_argument("--rounds", type=int, default=11)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = benchmark(args.nodes, args.rounds)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
