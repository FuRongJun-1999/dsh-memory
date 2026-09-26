# -*- coding: utf-8 -*-
"""FI-R04 · S4 自身/对手失效 → 字节翻转：WAL payload 单字节篡改必被捕获。

判据：P11 完整性锚（判据面/证据面不可伪造）+ T12 端到端。注入：纯 Python 按
v0.7.1 签名串（seq|type|from|to|round|ts|payload，与
swarm/rust_runtime/src/swarm.rs:376-386 sign_event 同约定）构造 3 条合法签名
WAL 行（行格式与 Rust 写序一致，swarm.rs:1107），先跑基线验签确认 fixture
正确（all_valid=True），再把第 2 行 payload "hello"→"hellO"（单字节 o→O）
落盘后重验——swarm/rust_swarm.py:101-151 verify_wal_signatures 逐条 HMAC。

理论预期（回归守卫，pass）：篡改必被端到端 HMAC 捕获（bad==1）且
all_valid=False；行级单验可定位到被篡改行；验签器面对畸形行不崩溃
（rust_swarm.py:100/:115 容错解码在案）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

from swarm.rust_swarm import verify_wal_signatures  # noqa: E402

SECRET = "chaos-fi-r04-哑密钥"


def main() -> int:
    case = harness.Case("FI-R04", "WAL payload 字节翻转：HMAC 验签捕获与定位")
    try:
        tmp = case.tmpdir("r04_wal")
        wal = os.path.join(tmp, "events.jsonl")
        lines = harness.make_wal_fixture(wal, SECRET)

        # ── 基线：fixture 必须全绿（否则注入无意义）──
        base = verify_wal_signatures(wal, SECRET)
        case.check("基线验签 3/3 verified（fixture 与 Rust 签名串约定一致）",
                   base == {"total": 3, "verified": 3, "bad": 0,
                            "snapshots": {"verified": 0, "bad": 0},
                            "all_valid": True}
                   or (base["total"] == 3 and base["verified"] == 3
                       and base["bad"] == 0 and base["all_valid"] is True),
                   json.dumps(base, ensure_ascii=False))

        # ── 注入：第 2 行 payload "hello"→"hellO"（单字节翻转）落盘 ──
        case.check("翻转前置：第 2 行含目标 payload",
                   '"msg":"hello"' in lines[1], lines[1][:80])
        flipped = lines[1].replace('"msg":"hello"', '"msg":"hellO"')
        case.check("注入确为单字节差（o→O，其余不动）",
                   len(flipped) == len(lines[1])
                   and sum(a != b for a, b in zip(lines[1], flipped)) == 1,
                   f"差异字节数={sum(a != b for a, b in zip(lines[1], flipped))}")
        with open(wal, "w", encoding="utf-8", newline="") as f:
            f.write(lines[0])
            f.write(flipped)
            f.write(lines[2])

        # ── 端到端重验 ──
        after = verify_wal_signatures(wal, SECRET)
        case.check("翻转后 bad==1（恰好命中被篡改行）",
                   after["bad"] == 1 and after["verified"] == 2,
                   json.dumps(after, ensure_ascii=False))
        case.check("all_valid=False（fail-closed，防线拦截）",
                   after["all_valid"] is False, "")

        # ── 行级定位：单行隔离重验 ──
        loc = []
        for i, ln in enumerate((lines[0], flipped, lines[2]), 1):
            one = os.path.join(tmp, f"line{i}.jsonl")
            with open(one, "w", encoding="utf-8", newline="") as f:
                f.write(ln)
            r = verify_wal_signatures(one, SECRET)
            loc.append(r["bad"])
        case.check("行级定位：bad 恰落在第 2 行（可追溯）",
                   loc == [0, 1, 0], f"逐行 bad={loc}")

        # ── 验签器自身不崩（畸形行容错，rust_swarm.py:100/:115 契约）──
        bad_wal = os.path.join(tmp, "garbage.jsonl")
        with open(bad_wal, "wb") as f:
            f.write(b"\xff\xfe not-json \xe4\xb8\n")  # 非法 UTF-8 + 畸形行
        try:
            g = verify_wal_signatures(bad_wal, SECRET)
            crashed = False
        except Exception as e:  # noqa: BLE001
            g, crashed = str(e), True
        case.check("畸形行不崩验签器（bad 计入，all_valid=False）",
                   crashed is False and g.get("bad") == 1
                   and g["all_valid"] is False,
                   json.dumps(g, ensure_ascii=False) if not crashed else g)

        verdict = "pass" if not case.fails else "fail"
        return case.finish(verdict, expected="pass")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
