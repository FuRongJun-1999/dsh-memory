# -*- coding: utf-8 -*-
"""FI-R08 · S8 平台默认值 → 静默改写：缺省密钥 fail-closed（原「公开缺省密钥伪造
合法签名 WAL」缺口结案）。

判据：P7（平台承诺须实测后采信）+ P11 的前提声明——HMAC 防线的判别力完全依赖
密钥保密性；密钥=公开常量时防线对持常量者零判别力。

原缺口（EXPECTED_GAP=N143）：`swarm/rust_swarm.py` 的 `make_swarm_config` 缺省
回落源码内公开常量 `DEFAULT_SECRET="蜂群默认密钥"`——任何读过源码者即可持该常量
自签伪造整条群史并通过 `verify_wal_signatures`（all_valid=True）。

**缺口结案（issue #81，2026-10-09 设计者裁定 A：fail-closed，提交 303f3b9a）**：
`make_swarm_config` 对缺/空 `shared_secret` 一律抛 `ValueError`（不再回落公开常量）。
⇒「用公开缺省密钥伪造」这一注入面已不存在；本 case 转为**修复面确认断言**（同
FI-M02/FI-M03 的「由 EXPECTED_GAP 转 pass 作回归守卫」形态）：
  · 缺省 / 空串密钥建配置 → 必被拒（fail-closed）；
  · 显式密钥 → 正常建（合法用法未被误伤）；
  · `DEFAULT_SECRET` 常量文本保留（供显式引用与历史对照），但不再是缺省；
  · 空串验签面仍拒（N143 最小修复未回退）；
  · 对照：错密钥仍被拒（防线本体 fail-closed 正常）。

回归守卫语义：`make_swarm_config` 若再回落公开常量 ⇒ 本条断言转红 ⇒ 观测 verdict
转 gap ⇒ run_all 与登记（pass）不一致 ⇒ 套件亮红。

不适用条件：
  · 不适用于「DEFAULT_SECRET 常量已删除」——常量文本有意保留（供显式引用/
    历史对照），只是不再作缺省；本 case 不断言其删除。
  · 不适用于「三入口密钥口径已完全统一」——CLI 侧缺省值等全量语义专项仍
    deferred；本 case 只覆盖 `make_swarm_config` 与 `verify_wal_signatures`
    两个入口的 fail-closed 面。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

from swarm.rust_swarm import (DEFAULT_SECRET, make_swarm_config,  # noqa: E402
                              verify_wal_signatures)


def _raises_value_error(fn) -> tuple:
    """调用 fn，返回 (是否 ValueError, 消息 或 异常描述)。"""
    try:
        fn()
    except ValueError as e:
        return True, str(e)
    except Exception as e:  # noqa: BLE001 —— 拒了但崩法不对也算红
        return False, "%s: %s" % (type(e).__name__, e)
    return False, "未抛异常（fail-open 回归！）"


def main() -> int:
    case = harness.Case("FI-R08", "缺省密钥 fail-closed（原公开缺省密钥伪造缺口结案）")
    try:
        # ① 缺省密钥 → 拒（fail-closed；修前回落公开常量 DEFAULT_SECRET）
        ok1, msg1 = _raises_value_error(lambda: make_swarm_config([{"id": "q"}]))
        case.check("#81 缺省 shared_secret → 抛 ValueError（fail-closed，不再回落公开常量）",
                   ok1 and "shared_secret" in msg1, "err=%r" % (msg1,))

        # ② 空串密钥 → 同拒（与缺省同口径）
        ok2, msg2 = _raises_value_error(
            lambda: make_swarm_config([{"id": "q"}], shared_secret=""))
        case.check("#81 空串 shared_secret → 抛 ValueError（与缺省同口径）",
                   ok2, "err=%r" % (msg2,))

        # ③ 显式密钥 → 正常建（合法用法未被误伤）
        cfg = make_swarm_config([{"id": "q"}], shared_secret="k-123456")
        case.check("显式 shared_secret → 正常建配置（合法用法未被误伤）",
                   cfg.get("shared_secret") == "k-123456" and cfg.get("instances"),
                   json.dumps(cfg, ensure_ascii=False)[:120])

        # ④ DEFAULT_SECRET 常量文本仍在（供显式引用；只是不再作缺省）
        case.check("DEFAULT_SECRET 常量文本仍保留（供显式引用，不再是缺省）",
                   DEFAULT_SECRET == "蜂群默认密钥"
                   and 'DEFAULT_SECRET = "蜂群默认密钥"'
                   in harness.src("swarm/rust_swarm.py"), "")

        tmp = case.tmpdir("r08_wal")
        wal = os.path.join(tmp, "events.jsonl")

        # ⑤ 空串验签面仍拒（N143 最小修复面确认，未回退）
        with open(wal, "w", encoding="utf-8", newline="") as f:
            f.write(harness.wal_line("", 1, 1758888800000, "queen", "w1",
                                     "任务", 1, {"task": "空串密钥行"}))
        ok5, msg5 = _raises_value_error(lambda: verify_wal_signatures(wal, ""))
        case.check("空串密钥验签面拒绝（N143 修复面确认，未回退）",
                   ok5 and "密钥不得为空" in msg5, "err=%r" % (msg5,))

        # ⑥ 对照：错密钥仍被拒（防线本体 fail-closed 正常）
        with open(wal, "w", encoding="utf-8", newline="") as f:
            f.write(harness.wal_line("真密钥", 1, 1758888800000, "queen", "w1",
                                     "任务", 1, {"task": "x"}))
        wrong = verify_wal_signatures(wal, "不是这个密钥")
        case.check("对照：错密钥被拒 bad=1（防线本体 fail-closed 正常）",
                   wrong["bad"] == 1 and wrong["all_valid"] is False,
                   json.dumps(wrong, ensure_ascii=False))

        case.note("四可判定（D4，结案后）：对缺省密钥——可发现=是（显式 ValueError，"
                  "非静默）/可隔离=是（单点拒绝，不累及其它调用）/可恢复=是"
                  "（显式传密钥即可建）/可追溯=是（消息点名 shared_secret + issue #81）；"
                  "防线判别力仍完全依赖密钥保密性——P11 前提声明在案")
        case.note("留档：N143（空串验签面，2026-09-26 闭合）+ issue #81（缺省密钥 "
                  "fail-closed，2026-10-09 提交 303f3b9a）——本格由 EXPECTED_GAP 转 "
                  "pass，此后作回归守卫（回落到公开常量 ⇒ 转 gap ⇒ 套件亮红）")
        verdict = "pass" if not case.fails else "fail"
        return case.finish(verdict, expected="pass")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
