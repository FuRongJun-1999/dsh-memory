# -*- coding: utf-8 -*-
"""FI-R05 · S1/S8（介质与通道）→ 消息丢失：WAL 整行删除必被 seq 连续性判据捕获。

判据：T2 消息不可信——丢失在允许失效集内；系统承诺的不是「不丢」而是
「丢失可检可裁」（D4 可发现）。注入：与 FI-R04 同一 3 行合法签名 WAL fixture，
物理删除中间行（seq=2）后重验，其余行一字节不动——
swarm/rust_swarm.py verify_wal_signatures 自批次53 起带 P0-2 seq 连续性判据
（v0.3 P0-2 落地）：以首个可解析行的 seq 为基准步进期望 seq，快照行与事件行
同链（Rust swarm.rs:1229 快照行同样 event_seq+=1），缺失（跳号）/重复/乱序
且验签有效 → 该行判 bad 并在 continuity_breaks 报明细（期望 seq/实际 seq）。

理论预期（防线回归守卫，pass）：整行删除后 bad>=1 且 all_valid=False，
continuity_breaks 恰报缺失槽位 {expected:2, actual:3, kind:跳号缺失}；
对照正常 WAL all_valid=True 零误伤；空 WAL/单行 WAL 语义不变；
skip_continuity=True 显式放宽回旧语义（存量非连续历史逃生门）。

历史基线（批次52 实测，已结案）：修复前逐行独立验签整行删除不可检
（{total:2, verified:2, bad:0, all_valid:True}）——单条 HMAC 锚完整性不锚
存在性（P11 覆盖篡改不覆盖遗漏），登记 NEW(P0-2/seq连续性)，本批次修复转绿。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

from swarm.rust_swarm import verify_wal_signatures  # noqa: E402

SECRET = "chaos-fi-r05-哑密钥"


def main() -> int:
    case = harness.Case("FI-R05", "WAL 整行删除：seq 连续性判据捕获丢失")
    try:
        src = harness.src("swarm/rust_swarm.py")
        tmp = case.tmpdir("r05_wal")
        wal = os.path.join(tmp, "events.jsonl")
        lines = harness.make_wal_fixture(wal, SECRET)

        # ── 判据落地在案（读码）：skip_continuity 参数 + continuity_breaks 明细 ──
        case.check("P0-2 判据已在源码（skip_continuity 参数与 continuity_breaks 明细）",
                   "skip_continuity: bool = False" in src
                   and "continuity_breaks" in src
                   and "跳号缺失" in src,
                   "批次53 落地 rust_swarm.py verify_wal_signatures")

        # ── 对照：正常 WAL 零误伤 ──
        base = verify_wal_signatures(wal, SECRET)
        case.check("基线（正常 3 行 seq=1,2,3）验签全绿零误伤",
                   base["total"] == 3 and base["verified"] == 3
                   and base["bad"] == 0 and base["continuity_breaks"] == []
                   and base["all_valid"] is True,
                   json.dumps(base, ensure_ascii=False))

        # ── 向后兼容：空 WAL / 单行 WAL 语义不变 ──
        wal_empty = os.path.join(tmp, "empty.jsonl")
        with open(wal_empty, "w", encoding="utf-8", newline="") as f:
            f.write("")
        ev = verify_wal_signatures(wal_empty, SECRET)
        case.check("空 WAL 语义不变（total=0，all_valid=True）",
                   ev["total"] == 0 and ev["all_valid"] is True
                   and ev["continuity_breaks"] == [],
                   json.dumps(ev, ensure_ascii=False))
        one = os.path.join(tmp, "one.jsonl")
        with open(one, "w", encoding="utf-8", newline="") as f:
            f.write(lines[0])
        eo = verify_wal_signatures(one, SECRET)
        case.check("单行 WAL 语义不变（首行为基准，all_valid=True）",
                   eo["total"] == 1 and eo["verified"] == 1
                   and eo["all_valid"] is True
                   and eo["continuity_breaks"] == [],
                   json.dumps(eo, ensure_ascii=False))

        # ── 注入：物理删除中间行（seq=2），其余行一字节不动 ──
        case.check("删除目标确为 seq=2 行", '"seq":2,' in lines[1],
                   lines[1][:60])
        with open(wal, "w", encoding="utf-8", newline="") as f:
            f.write(lines[0])
            f.write(lines[2])

        after = verify_wal_signatures(wal, SECRET)
        case.check("整行删除后 bad>=1 且 all_valid=False（丢失可检）",
                   after["total"] == 2 and after["bad"] >= 1
                   and after["verified"] < after["total"]
                   and after["all_valid"] is False,
                   json.dumps(after, ensure_ascii=False))
        brk = after["continuity_breaks"]
        case.check("continuity_breaks 明细恰报缺失槽位（期望 2 / 实际 3 / 跳号缺失）",
                   len(brk) == 1 and brk[0]["expected"] == 2
                   and brk[0]["actual"] == 3
                   and brk[0]["kind"] == "跳号缺失",
                   json.dumps(brk, ensure_ascii=False))

        # ── 显式放宽逃生门：skip_continuity=True 回旧语义 ──
        relaxed = verify_wal_signatures(wal, SECRET, skip_continuity=True)
        case.check("skip_continuity=True 显式放宽 → 整行删除回旧语义不可检"
                   "（存量非连续历史逃生门，语义变化声明）",
                   relaxed["total"] == 2 and relaxed["verified"] == 2
                   and relaxed["bad"] == 0 and relaxed["all_valid"] is True
                   and relaxed["continuity_breaks"] == [],
                   json.dumps(relaxed, ensure_ascii=False))

        case.note("四可判定（D4）：可发现=True（bad>=1 + continuity_breaks 明细，"
                  "本轮实测 all_valid=False）；可隔离=True（明细含物理行号/"
                  "期望 seq/实际 seq，缺失槽位=2）；可恢复=部分（真源 append-only "
                  "在则可按缺口定位重放）；可追溯=True（breaks 留痕随验签报告落盘）。"
                  "防线=单条 HMAC 锚（完整性）+ seq 连续性判据（存在性），P0-2 落地")
        case.note("时序语义分工不变：Rust 重放的水位/快照提交点（swarm.rs:460）"
                  "承担运行时序，Python 审计面现补齐「存在性/顺序」审计判据；"
                  "skip_continuity=True 为显式放宽口（缺省严格），向后兼容面="
                  "空 WAL/单行 WAL/连续 WAL 语义不变")
        verdict = "pass" if not case.fails else "fail"
        return case.finish(verdict, expected="pass")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
