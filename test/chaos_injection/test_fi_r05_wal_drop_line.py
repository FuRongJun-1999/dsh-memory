# -*- coding: utf-8 -*-
"""FI-R05 · S1/S8（介质与通道）→ 消息丢失：WAL 整行删除对本验签器不可检。

判据：T2 消息不可信——丢失在允许失效集内；系统承诺的不是「不丢」而是
「丢失可检可裁」（D4 可发现）。注入：与 FI-R04 同一 3 行合法签名 WAL fixture，
物理删除中间行（seq=2）后重验，其余行一字节不动——
swarm/rust_swarm.py:100-151 逐行独立验签，无 seq 连续性/行数判据。

理论预期（已知缺口基线，EXPECTED_GAP）：{total:2, verified:2, bad:0,
all_valid:True}——整行丢失不可检。单条 HMAC 锚完整性不锚存在性（P11 覆盖
篡改不覆盖遗漏）= 当前缺口基线：输入 P0-2 幂等键/seq 连续性判据设计与
v0.3 矩阵「T2/T7 幂等 🟡」格。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

from swarm.rust_swarm import verify_wal_signatures  # noqa: E402

SECRET = "chaos-fi-r05-哑密钥"


def main() -> int:
    case = harness.Case("FI-R05", "WAL 整行删除：验签器丢失不可检")
    try:
        tmp = case.tmpdir("r05_wal")
        wal = os.path.join(tmp, "events.jsonl")
        lines = harness.make_wal_fixture(wal, SECRET)

        base = verify_wal_signatures(wal, SECRET)
        case.check("基线验签 3/3 verified（fixture 正确）",
                   base["total"] == 3 and base["verified"] == 3
                   and base["all_valid"] is True,
                   json.dumps(base, ensure_ascii=False))
        case.check("验签器确无 seq 连续性判据（读码 rust_swarm.py:100-151）",
                   "rec.get(\"seq\", 0)" in harness.src("swarm/rust_swarm.py")
                   and "seq + 1" not in harness.src("swarm/rust_swarm.py")
                   and "连续" not in harness.src("swarm/rust_swarm.py"),
                   "seq 仅入签不参与连续性判定")

        # ── 注入：物理删除中间行（seq=2），其余行一字节不动 ──
        case.check("删除目标确为 seq=2 行", '"seq":2,' in lines[1],
                   lines[1][:60])
        with open(wal, "w", encoding="utf-8", newline="") as f:
            f.write(lines[0])
            f.write(lines[2])

        after = verify_wal_signatures(wal, SECRET)
        case.check("整行删除后验签全绿 {total:2, verified:2, bad:0}（缺口复现）",
                   after == {"total": 2, "verified": 2, "bad": 0,
                             "snapshots": {"verified": 0, "bad": 0},
                             "all_valid": True}
                   or (after["total"] == 2 and after["verified"] == 2
                       and after["bad"] == 0 and after["all_valid"] is True),
                   json.dumps(after, ensure_ascii=False))

        case.note("四可判定（D4）：可发现=False（本轮实测 all_valid=True，零信号）；"
                  "可隔离=False（无行号/序号缺口证据）；可恢复=部分（真源 append-only "
                  "在则可重放，但删除已发生时无从知晓）；可追溯=False（无缺口留痕）。"
                  "缺口=单条 HMAC 锚完整性不锚存在性（P11 覆盖篡改不覆盖遗漏）")
        case.note("输入面：P0-2 幂等键/seq 连续性判据设计 + v0.3 矩阵 T2/T7 幂等🟡格；"
                  "时序语义现由 Rust 重放的水位/快照提交点承担"
                  "（swarm.rs:460 提交点=最后通过验签的快照行），Python 审计面不覆盖")
        verdict = "gap" if not case.fails else "fail"
        return case.finish(verdict, expected="gap")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
