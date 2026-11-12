# -*- coding: utf-8 -*-
"""test_issue546_ledger_concurrency · 审计台账独立写入点（#546）

# 功能名：fsutil.append_jsonl_ledger / read_jsonl_ledger —— 每进程独占分片 + 读面合并
# 生效条件：多写者并发写同一审计台账（_identity / _insight / _self_state）
# 子功能：A 分片路径含 pid · B 同进程内追加落分片而非旧单文件 · C 读面合并旧单文件+分片 · D 源码钉子（三个模块均接线）
# 执行：python -X utf8 -m md_cg.test_issue546_ledger_concurrency
# 验证方式：全部 PASS 即通过（退出码 0）；并发读数见 issue #546（6 写者 × 400 行：22.4% -> 0.0%）
# 不适用条件：不做多进程压测（那是探针，见 issue #546 的脚本）；不判 ShardedLog（它是 nodes 面的另一套）；不判同进程多线程
"""
import inspect
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import fsutil


def g_a_shard_path_has_pid():
    base = os.path.join(tempfile.mkdtemp(), "_ledger.jsonl")
    sp = fsutil.ledger_shard_path(base, pid=4242)
    assert sp.endswith(".4242.jsonl"), "分片名应含 pid：%r" % sp
    assert os.path.splitext(base)[0] in sp
    assert fsutil.ledger_shard_path(base).endswith(".%d.jsonl" % os.getpid())
    print("  PASS A 分片路径含 pid（显式与默认两种）")


def g_b_append_goes_to_shard():
    d = tempfile.mkdtemp()
    base = os.path.join(d, "_ledger.jsonl")
    ok = fsutil.append_jsonl_ledger(base, {"k": 1})
    assert ok is not False, "写应成功"
    assert not os.path.exists(base), "旧单文件不应被创建（写入必须落分片）"
    shard = fsutil.ledger_shard_path(base)
    assert os.path.exists(shard), "分片应存在：%r" % shard
    print("  PASS B 追加落分片而非旧单文件")


def g_c_read_merges_legacy_and_shards():
    d = tempfile.mkdtemp()
    base = os.path.join(d, "_ledger.jsonl")
    # 旧单文件（历史）
    with open(base, "w", encoding="utf-8") as f:
        f.write('{"legacy": true}\n')
    # 本进程分片
    fsutil.append_jsonl_ledger(base, {"new": True})
    # 另一个 pid 的分片（模拟历史进程）
    with open(fsutil.ledger_shard_path(base, pid=99999), "w", encoding="utf-8") as f:
        f.write('{"other": true}\n')
    recs = fsutil.read_jsonl_ledger(base)
    kinds = [("legacy" if r.get("legacy") else "new" if r.get("new") else "other" if r.get("other") else "?") for r in recs]
    for k in ("legacy", "new", "other"):
        assert k in kinds, "读面应合并 %s，实得 %r" % (k, kinds)
    print("  PASS C 读面合并旧单文件 + 全部 pid 分片（%d 条）" % len(recs))


def g_d_source_nail():
    s = inspect.getsource(fsutil)
    assert "def append_jsonl_ledger(" in s
    assert "def read_jsonl_ledger(" in s
    assert "def ledger_shard_path(" in s
    for mod, fn in (("identity", "log"), ("insight", "_append"), ("self_state", "_append_log")):
        m = __import__("md_cg." + mod, fromlist=["x"])
        body = inspect.getsource(getattr(m, fn))
        assert "append_jsonl_ledger" in body, "%s.%s 未接线到 ledger" % (mod, fn)
    print("  PASS D 源码钉子：三个模块的写点均接线到 append_jsonl_ledger")


def main():
    print("=== #546 审计台账独立写入点 ===")
    g_a_shard_path_has_pid()
    g_b_append_goes_to_shard()
    g_c_read_merges_legacy_and_shards()
    g_d_source_nail()
    print("===== 全绿 =====")


if __name__ == "__main__":
    main()
