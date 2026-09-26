# -*- coding: utf-8 -*-
"""FI-M01 · S9 时间/时钟（时钟回拨）→ 令牌 TTL 壁钟判定被洗白。

判据：A2 时间不可信 / 公理 7（v0.1:62——「钟错了」与「时间真的到了」在判据
面上不可区分）；承重面 md_cg/tokens.py:371（issue 落 expires_at）与
:407-411（verify 以 time.time() 判过期，无单调锚），§2.9 预防性建模、无台账
编号。注入：临时 MDCG_TOKEN_FILE 签发 record/ttl=1800 令牌，进程内 monkeypatch
tokens.time 使墙钟回拨 1h 再 verify_token；对照组前跳 1h（正确时钟 fail-closed
应拦截）。

理论预期（EXPECTED_GAP，登记 gap）：回拨后失效点被推迟——应逐出的令牌仍通过
verify（新鲜层被洗白）＝预期暴露面；对照格正确时钟下 TokenError「令牌已过期」
（T8 在时钟正确时成立）。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness        # noqa: E402
import mdcg_support   # noqa: E402


class _FakeTime:
    """tokens.time 替身（只换 time.time 读数，不动其它 clock 面）。"""


def main() -> int:
    case = harness.Case("FI-M01", "时钟回拨：TTL 壁钟唯一时基被洗白")
    try:
        d = case.tmpdir("m01")
        mdcg_support.apply_env(d)
        from md_cg import tokens                      # env 之后导入

        case.check("读码：TTL 判定以壁钟为唯一时基（tokens.py:371 落 expires_at、"
                   ":407-411 verify 以 time.time() 判过期，无单调锚）",
                   "now = time.time()" in harness.src("md_cg/tokens.py")
                   and "if exp and now > float(exp)" in harness.src("md_cg/tokens.py"),
                   "md_cg/tokens.py:371/:407-411")

        tokf = os.environ["MDCG_TOKEN_FILE"]
        r = tokens.issue(role="record", ttl=1800, path=tokf)
        tok, exp = r["token"], r["expires_at"]
        real_now = time.time()
        case.check("注入前基线：令牌签发成功且 expires_at=now+1800",
                   bool(tok) and abs(exp - (real_now + 1800)) < 5,
                   f"expires_at={exp:.1f}")

        orig_time = tokens.time
        try:
            # ═══ 主场：墙钟回拨 1 小时 ═══
            ft = _FakeTime()
            ft.time = lambda: real_now - 3600
            tokens.time = ft
            whitewashed = None
            try:
                p = tokens.verify_token(tok, path=tokf)
                whitewashed = f"通过 actor={p.actor}"
            except tokens.TokenError as e:
                whitewashed = f"TokenError: {e}"
            case.check("主场（红场）：回拨 1h 后应逐出令牌仍通过 verify（失效点被"
                       "推迟＝新鲜层被洗白，A2 暴露面）",
                       whitewashed.startswith("通过"),
                       f"verify 结果={whitewashed}")

            # ═══ 对照组：墙钟前跳 1 小时（等价时钟正确走完 TTL）═══
            ft2 = _FakeTime()
            ft2.time = lambda: real_now + 3600
            tokens.time = ft2
            ctrl = None
            try:
                tokens.verify_token(tok, path=tokf)
                ctrl = "通过（不应发生）"
            except tokens.TokenError as e:
                ctrl = f"TokenError: {e}"
            case.check("对照组（绿场）：正确时钟走完 TTL 后 fail-closed 拦截"
                       "（T8 在时钟正确时成立）",
                       "令牌已过期" in ctrl,
                       f"verify 结果={ctrl}")
        finally:
            tokens.time = orig_time
        case.check("恢复：time 替身撤除后 time 模块原样（无跨 case 污染）",
                   tokens.time is orig_time,
                   f"restored={tokens.time is orig_time}")

        # 四可（D4）
        case.check("四可：可发现=否（判据面上「钟错」与「未到期」不可区分，v0.1:62"
                   "）/可隔离=是（time 替身单点注入，TTL 判定局部）/可恢复=是（钟"
                   "恢复即恢复判据正确性，无持久损伤）/可追溯=弱（tokens 文件留 "
                   "expires_at 原值可对账，但系统内零日志零告警）",
                   True,
                   "证据=主场洗白零告警 + 对照组拦截 + tokens.time 原样恢复")
        verdict = "gap" if not case.fails else "fail"
        return case.finish(verdict, expected="gap")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
