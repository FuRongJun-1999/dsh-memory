# -*- coding: utf-8 -*-
"""issue #677（C 根治）：`_flush_batch` 的锁内 IO 从「每条一次 flush」降为「每批一次」。

## 病灶
`_flush_batch` 在 `FileLock(index_path)` 内逐条 `ShardedLog.append`，而 `append` **每条都 flush**
⇒ 锁内 IO 次数 = 脏集条数。大库一批上千条 = 上千次 flush，MCP stdio 串行时后续请求全排队，
客户端 60s 超时（「写成功但没回话」）。

## 修法
`ShardedLog.append_many`：**一次 write + 一次 flush**（批量编码、单次落盘）；
`_flush_batch` 用它，整批仍在同一把 FileLock 内 ⇒ 与 compact 的 read→clear 互斥语义不变。

## 断言
- B1 一批 300 条：`append` 调用 **0** 次、`append_many` 至少 1 次、总条数 300；
- B2 重开库后 300 条都在（日志重放正确）；
- B3 单条 flush 仍工作（走 append_many，条数 1）。

运行：python -X utf8 -m md_cg.test_issue677_flush_batch_io
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import fsutil   # noqa: E402
from md_cg.mdcg import MdCG  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


BODY = "# 功能名：t%d\n# 生效条件：x\n# 子功能：y\n# 执行：z\n# 验证方式：test\n# 不适用条件：无\n\nbody %d"


def main():
    print("=" * 68)
    print("issue #677 C · flush 锁内批量 IO")
    print("=" * 68)
    counts = {"append": 0, "many": 0, "many_n": 0}
    orig_append = fsutil.ShardedLog.append
    orig_many = fsutil.ShardedLog.append_many

    def _a1(self, record):
        counts["append"] += 1
        return orig_append(self, record)

    def _a2(self, records):
        n = orig_many(self, records)
        counts["many"] += 1
        counts["many_n"] += n
        return n

    fsutil.ShardedLog.append = _a1
    fsutil.ShardedLog.append_many = _a2
    tmp = tempfile.mkdtemp(prefix="iss677c_")
    try:
        cg = MdCG(os.path.join(tmp, "r"), autoflush=10 ** 9)
        for i in range(300):
            cg.add("n%03d" % i, BODY % (i, i), layer="contextual")
        cg.flush()
        ok(counts["append"] == 0, "B1a 锁内不再逐条 append", counts)
        ok(counts["many"] >= 1 and counts["many_n"] == 300, "B1b 批量一次写盘、条数 300", counts)
        cg.close()
        cg2 = MdCG(os.path.join(tmp, "r"))
        ok(len(cg2.index.get("nodes") or {}) == 300, "B2 重开后 300 条都在（重放正确）",
           len(cg2.index.get("nodes") or {}))
        cg2.close()
        counts.update({"append": 0, "many": 0, "many_n": 0})
        cg3 = MdCG(os.path.join(tmp, "r2"), autoflush=10 ** 9)
        cg3.add("one", BODY % (0, 0), layer="contextual")
        cg3.flush()
        ok(counts["many_n"] == 1, "B3 单条 flush 仍工作", counts)
        cg3.close()
        # B4（#677 C 复核 P1）：残尾修补——先造「无换行结尾」的半行，再 append_many；
        # 不补换行时新记录会与残尾粘成一行（解析失败、残尾与新记录一起丢）。
        _d = os.path.join(tmp, "shard_torn")
        os.makedirs(_d, exist_ok=True)
        _log = fsutil.ShardedLog(_d)
        with open(_log.path, "a", encoding="utf-8", newline="\n") as _f:
            _f.write('{"id":"torn"')
        _log.append_many([{"id": "good", "e": {"layer": "contextual"}}])
        _log.close()
        _recs = fsutil.read_jsonl(_log.path)
        ok([r.get("id") for r in _recs] == ["good"],
           "B4 残尾修补：新记录不被粘行吞掉", [r.get("id") for r in _recs])
        # B5（#677 C 复核 P2）：失败回填必须保留 superseded 标记——
        # 否则下一轮把「已判陈旧」的记录当新记录写进分片（旧盖新 = 内容错误）。
        cg4 = MdCG(os.path.join(tmp, "r3"), autoflush=10 ** 9)
        cg4.add("s0", BODY % (0, 0), layer="contextual")
        cg4.add("s1", BODY % (1, 1), layer="contextual")
        cg4._dirty.superseded_ids.add("s0")
        _boom = {"on": True}

        def _raise(self, records):
            if _boom["on"]:
                _boom["on"] = False
                raise OSError("disk full (simulated)")
            return orig_many(self, records)

        fsutil.ShardedLog.append_many = _raise
        try:
            cg4.flush()
        except OSError:
            pass
        fsutil.ShardedLog.append_many = _a2
        cg4.flush()
        _ids = []
        for _root, _dn, _fns in os.walk(cg4.index_log_dir):
            for _fn in _fns:
                if _fn.endswith(".log"):
                    _ids += [r.get("id") for r in fsutil.read_jsonl(os.path.join(_root, _fn))]
        ok("s0" not in _ids and "s1" in _ids,
           "B5 失败回填保留 superseded（陈旧记录不落盘）", _ids)
        cg4.close()
    finally:
        fsutil.ShardedLog.append = orig_append
        fsutil.ShardedLog.append_many = orig_many
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("issue #677 C：%d 项失败" % len(FAILS) if FAILS else "issue #677 C：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())