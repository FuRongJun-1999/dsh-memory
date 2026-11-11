# -*- coding: utf-8 -*-
"""R-405c · HTTP→Rust `--serve` 桥的守卫（2026-11-10）。

缺陷面（审计 P2 外围 3）：`/health` 的 `backend` 字段写死 `"lingshu"`，仓库里
没有任何把 HTTP 请求喂给 Rust serve 的桥——「Rust 接主链」只做到评测器，
服务面仍是纯 Python。

修法：`server/rust_bridge.py`（常驻 serve 的薄客户端，只读 search/info）+
`server/mdcg_http.py` 的 `MDCG_BACKEND=lingshu|rust` 与 `POST /search`；
**切到 rust 而桥不通 ⇒ 503 + degraded**，不静默回落。

契约（本文件即其守卫）：

  【1】桥能起来且自报口径 == 钉住值（`jaccard`），`status()` 非 degraded。
  【2】同一查询，桥的 top-k **id 序列**与 Python `search_rrf` 一致（同库同 k）。
  【3】二进制缺失 ⇒ `start()` 返回 False、`degraded=True` 且**带原因**，
      `search()` 抛错（调用方据此报 503），绝不静默回落到 Python。
  【4】`mdcg_http` 的接线在源码级可钉死：`MDCG_BACKEND` 选择器、`/health` 的
      `backend`/`bridge` 字段、`/search` 路由、degraded 分支都在。

运行：python -X utf8 server/test_rust_bridge.py
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

PASSED = FAILED = 0


def ok(cond, name):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("  [PASS] " + name)
    else:
        FAILED += 1
        print("  [FAIL] " + name)


def main():
    from server import rust_bridge as RB
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal

    exe = RB.DEFAULT_EXE
    if not os.path.isfile(exe):
        print("  [SKIP] rust 二进制不存在（先 cd rust && cargo build --release）")
        print("\ntest_rust_bridge: 0 通过 / 0 失败（SKIP）")
        return 0

    tmp = tempfile.mkdtemp(prefix="rustbr_")
    try:
        root = os.path.join(tmp, "graph")
        cg = MdCGSecure(root, principal=Principal(
            actor="b", clearance="secret", can_write=True, role="designer",
            auth_mode="test"))
        for i in range(40):
            cg.add("rb_%03d" % i,
                   "# 功能名：样本 %d\n\n蜂群调度与依赖门禁的第 %d 号样本。\n" % (i, i),
                   layer="knowledge")
        cg.flush()

        print("[1] 桥启动与口径回读")
        br = RB.RustBridge(root)
        ok(br.start() is True, "G1a start() 成功")
        st = br.status()
        ok(st["score"] == RB.SCORE and st["alive"] is True, "G1b 自报口径 == 钉住值")
        ok(st["degraded"] is False and st["error"] is None, "G1c 非 degraded")

        print("[2] 与 Python 同查询同 k 的 id 序列一致")
        q = "蜂群 调度 依赖 门禁"
        rs = br.search(q, 10)
        py, _m = cg.search_rrf(q, k=10)
        # `search_rrf` 的元素是 `(节点字典, 分数)` 对；取节点 id。
        def _nid(h):
            node = h[0] if isinstance(h, (list, tuple)) else h
            return node.get("id") if isinstance(node, dict) else str(node)
        py_ids = [_nid(h) for h in (py or [])]
        rs_ids = [i for i, _s in rs]
        ok(bool(rs_ids) and rs_ids == py_ids,
           "G2a top-10 id 序列一致（py=%s… rust=%s…）"
           % (py_ids[:3], rs_ids[:3]))
        ok(all(isinstance(s, float) for _i, s in rs), "G2b 分数为浮点（可比较）")

        print("[3] 桥不可用 ⇒ degraded 且不静默回落")
        bad = RB.RustBridge(root, exe=os.path.join(tmp, "no_such_binary"))
        ok(bad.start() is False, "G3a 缺二进制 ⇒ start() 返回 False")
        ok(bad.status()["degraded"] is True
           and "不存在" in (bad.status()["error"] or ""),
           "G3b degraded=True 且带原因（%s）" % (bad.status()["error"],))
        try:
            bad.search(q, 5)
            raised = False
        except RuntimeError:
            raised = True
        ok(raised, "G3c search() 抛错（调用方据此报 503，不回落到 Python）")
        br.close()

        print("[4] HTTP 面接线（源码级钉子）")
        src = io.open(os.path.join(HERE, "mdcg_http.py"), encoding="utf-8").read()
        ok('MDCG_BACKEND' in src and '"rust"' in src, "G4a 有 MDCG_BACKEND 选择器")
        ok("'backend': BACKEND" in src and '"bridge": _bstat' in src,
           "G4b /health 带 backend 与 bridge 段")
        ok("'/search'" in src and "_do_search" in src, "G4c 有 POST /search 路由")
        ok("degraded" in src and "503" in src, "G4d degraded 分支走 503")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\ntest_rust_bridge: %d 通过 / %d 失败" % (PASSED, FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
