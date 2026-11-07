# -*- coding: utf-8 -*-
"""issue #812：info 必须让「内存索引 vs 落盘索引」的偏差可判定。

本测试不依赖库的懒写时机：直接往临时 root 里写一份 `_index.json`（这正是实现读取的东西），
因此契约（index_mtime / index_node_count / index_stale / stale 只在 full 时出现）可确定性断言。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg.mcp_server import _cg_call  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []
CCG = ("# 功能名：{n}\n# 生效条件：c{n}\n# 子功能：s\n# 执行：e\n"
       "# 验证方式：test\n# 不适用条件：无\n\nbody\n")


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def write_index(root, ids):
    nodes = {i: {"layer": "knowledge"} for i in ids}
    with open(os.path.join(root, "_index.json"), "w", encoding="utf-8") as fh:
        json.dump({"nodes": nodes}, fh)


def main():
    print("=" * 66)
    print("issue #812 · info 暴露内存/落盘索引偏差")
    print("=" * 66)
    root = tempfile.mkdtemp(prefix="mdcg812_")
    os_ = MdCGOS(root, actor="test")
    os_.add("keep1", CCG.format(n="保留1"))
    os_.add("drop1", CCG.format(n="待删1"))

    # A1/A2/A3：落盘索引与内存一致
    write_index(root, ["keep1", "drop1"])
    h1 = _cg_call(os_, {"op": "info", "full": True})
    ok(h1.get("index_mtime") is not None, "A1 info 带 index_mtime", h1.get("index_mtime"))
    ok(h1.get("index_stale") is False, "A2 一致时 index_stale=False", h1.get("index_stale"))
    ok(h1.get("index_node_count") == 2 and h1.get("node_count") == 2,
       "A3 一致时 落盘==内存==2", (h1.get("index_node_count"), h1.get("node_count")))

    # A4/A5/A6：模拟「外部进程删掉 drop1」（落盘少一条，本进程内存仍两条）
    write_index(root, ["keep1"])
    h2 = _cg_call(os_, {"op": "info", "full": True})
    ok(h2.get("index_stale") is True, "A4 落盘少一条 ⇒ index_stale=True", h2.get("index_stale"))
    ok(h2.get("index_node_count") == 1 and h2.get("node_count") == 2,
       "A5 落盘(1) < 内存(2)", (h2.get("index_node_count"), h2.get("node_count")))
    ok(bool(h2.get("index_stale_hint")), "A6 stale 时给 hint（怎么修）", h2.get("index_stale_hint"))

    # A7：快照模式不解析索引（58MB 成本不进快照面）
    h3 = _cg_call(os_, {"op": "info"})
    ok("index_node_count" not in h3 and "index_stale" not in h3,
       "A7 快照模式不返回 index_node_count/index_stale")
    ok(h3.get("index_mtime") is not None, "A8 快照模式仍带 index_mtime（零成本）")
    ok(h3.get("node_count_scope") == "memory_index",
       "A9 node_count 口径显式标注（memory_index）", h3.get("node_count_scope"))
    print()
    print("issue #812：%d 项失败" % len(FAILS) if FAILS else "issue #812：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())