# -*- coding: utf-8 -*-
"""FI-R08 · S8 平台默认值 → 静默改写：用公开缺省密钥伪造合法签名 WAL。

判据：P7（平台承诺须实测后采信）+ P11 的前提声明——HMAC 防线的判别力完全
依赖密钥保密性；密钥=公开常量时防线对持常量者零判别力。注入：以
swarm/rust_swarm.py:24 DEFAULT_SECRET="蜂群默认密钥"（公开常量，:38
make_swarm_config 缺省即用）为密钥按 v0.7.1 签名串伪造一条「queen→w1 任务」
WAL 行落盘，再以同一公开常量调 verify_wal_signatures。

理论预期（已知缺口基线，EXPECTED_GAP=N143）：伪造整条通过验签
（all_valid=True）——攻击者可整条伪造群史；两口径分叉（API 缺省=公开常量/
CLI 缺省=空串，swarm_cli.py:93，N143）属误配公理 4 面。输入 P1-9 fail-closed
落点清单（无密钥时应拒跑而非回落缺省——T8）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

from swarm.rust_swarm import (DEFAULT_SECRET, make_swarm_config,  # noqa: E402
                              verify_wal_signatures)


def main() -> int:
    case = harness.Case("FI-R08", "公开缺省密钥伪造合法签名 WAL")
    try:
        tmp = case.tmpdir("r08_wal")
        wal = os.path.join(tmp, "events.jsonl")

        # 缺省密钥即公开常量（攻击者只需读过源码）
        case.check("make_swarm_config 缺省 shared_secret == DEFAULT_SECRET"
                   "（rust_swarm.py:38 公开常量缺省）",
                   make_swarm_config([{"id": "q"}])["shared_secret"]
                   == DEFAULT_SECRET,
                   f"DEFAULT_SECRET={DEFAULT_SECRET!r}")
        case.check("DEFAULT_SECRET 硬编码在源码公开面（rust_swarm.py:24）",
                   'DEFAULT_SECRET = "蜂群默认密钥"'
                   in harness.src("swarm/rust_swarm.py"), "")

        # ── 注入：以公开常量为密钥伪造「queen→w1 任务」行 ──
        line = harness.wal_line(DEFAULT_SECRET, 1, 1758888800000, "queen", "w1",
                                "任务", 1, {"task": "伪造任务-CHAOS-FI-R08"})
        with open(wal, "w", encoding="utf-8", newline="") as f:
            f.write(line)
        forged = verify_wal_signatures(wal, DEFAULT_SECRET)
        case.check("伪造行整条通过验签 {verified:1, bad:0, all_valid:True}"
                   "（缺口复现——对持常量者零判别力）",
                   forged["total"] == 1 and forged["verified"] == 1
                   and forged["bad"] == 0 and forged["all_valid"] is True,
                   json.dumps(forged, ensure_ascii=False))

        # 端到端伪造群史：3 行全伪造同样全绿
        wal3 = os.path.join(tmp, "forged_history.jsonl")
        with open(wal3, "w", encoding="utf-8", newline="") as f:
            for i in range(1, 4):
                f.write(harness.wal_line(DEFAULT_SECRET, i, 1758888800000 + i,
                                         "queen", "w1", "任务", 1,
                                         {"task": f"伪造任务-{i}"}))
        hist = verify_wal_signatures(wal3, DEFAULT_SECRET)
        case.check("整条伪造群史（3/3 全绿）——审计签名面被击穿",
                   hist["verified"] == 3 and hist["all_valid"] is True,
                   json.dumps(hist, ensure_ascii=False))

        # 两口径分叉（N143）：CLI 缺省=空串（swarm_cli.py:93）照签照过
        case.check("两口径分叉：CLI 侧 cfg_in.get('shared_secret','') 缺省空串"
                   "（swarm_cli.py:93，读码）",
                   'cfg_in.get("shared_secret", "")'
                   in harness.src("swarm/swarm_cli.py"),
                   "API 缺省=公开常量 / CLI 缺省=空串")
        wal_empty = os.path.join(tmp, "empty_secret.jsonl")
        with open(wal_empty, "w", encoding="utf-8", newline="") as f:
            f.write(harness.wal_line("", 1, 1758888800000, "queen", "w1",
                                     "任务", 1, {"task": "空串密钥行"}))
        es = verify_wal_signatures(wal_empty, "")
        case.check("空串密钥照签照过（实测 verified=1）",
                   es["verified"] == 1 and es["all_valid"] is True,
                   json.dumps(es, ensure_ascii=False))
        # 对照：错密钥正常被拒（防线本体完好，缺口仅在缺省密钥面——N143 口径）
        wrong = verify_wal_signatures(wal, "不是这个密钥")
        case.check("对照：错密钥被拒 bad=1（防线本体 fail-closed 正常）",
                   wrong["bad"] == 1 and wrong["all_valid"] is False,
                   json.dumps(wrong, ensure_ascii=False))

        case.note("四可判定（D4）：对持公开常量者——可发现=False（验签全绿零"
                  "信号）/可隔离=False/可追溯=False（伪造行与真行不可区分）；"
                  "可恢复=False（审计证据面已可被整条替换）。防线判别力完全"
                  "依赖密钥保密性——P11 前提声明在案")
        case.note("留档对应：N143（v17.md:85 留档，owner=rust，涉「缺省密钥从何"
                  "而来」配置语义决策 deferred：fail-closed 拒启动 vs 首启随机"
                  "生成落盘）；输入 P1-9 fail-closed 落点清单（无密钥应拒跑"
                  "而非回落缺省——T8）")
        verdict = "gap" if not case.fails else "fail"
        return case.finish(verdict, expected="gap")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
