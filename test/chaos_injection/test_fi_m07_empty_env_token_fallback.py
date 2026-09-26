# -*- coding: utf-8 -*-
"""FI-M07 · S7 人类（误配：空串 MDCG_TOKEN_FILE 静默回落，公理 4）。

判据：误配公理 4 + P1 fail-closed（v0.1 §2.7「空串误配静默上岗」）——空串应
显式拒绝或至少 stderr 告警，而非静默把令牌面切回默认路径（后续一次 issue()
即落默认库）。同型先例：N91（docs/eval/缺陷挖掘_自主迭代_v17.md:102——resolve()
对空串/纯空白不拒，残缺 env 静默上岗）。判据面：md_cg/tokens.py:42
（TOKEN_FILE_ENV）/:283-284（token_file 空值回落链 or-or 无告警路径）。
注入（只读解析观测，不触任何真实令牌库）：env 未设时 tokens.token_file(None)
记下默认路径；再设 MDCG_TOKEN_FILE="" 后再解析，比对两字符串。

理论预期（EXPECTED_GAP，登记 gap）：两字符串相同（空串误配静默回落真实默认
路径），且全程零告警零留痕。套件安全边界：apply_env 已把 aux 根钉在临时目录，
故回落目标在实验中是临时 aux/_tokens.json——生产形态（读码 DEFAULT_TOKEN_DIR
=aux_root()→~/.mdcg）仅由读码断言支撑，真实库全程未被读写。
"""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness        # noqa: E402
import mdcg_support   # noqa: E402


def main() -> int:
    case = harness.Case("FI-M07", "空串 MDCG_TOKEN_FILE 静默回落默认路径")
    try:
        d = case.tmpdir("m07")
        mdcg_support.apply_env(d)
        from md_cg import tokens

        case.check("读码：回落链 or-or 无告警路径（tokens.py:283-284——path 或 "
                   "env 或 DEFAULT，空串同为假值直落 DEFAULT）",
                   "return path or os.environ.get(TOKEN_FILE_ENV) or "
                   "DEFAULT_TOKEN_FILE" in harness.src("md_cg/tokens.py"),
                   "md_cg/tokens.py:283-284")
        case.check("读码：生产回落目标=aux 根（~/.mdcg 形态，tokens.py:43-44 "
                   "DEFAULT_TOKEN_DIR=aux_root()）",
                   "DEFAULT_TOKEN_DIR = aux_root()" in harness.src("md_cg/tokens.py"),
                   "md_cg/tokens.py:43-44")

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            os.environ.pop("MDCG_TOKEN_FILE", None)
            p_default = tokens.token_file(None)          # env 未设
            os.environ["MDCG_TOKEN_FILE"] = ""           # 误配：空串
            p_empty = tokens.token_file(None)
            os.environ["MDCG_TOKEN_FILE"] = os.path.join(d, "mdcg_aux",
                                                         "_tokens.json")
        case.check("红场①：空串误配与未设解析到同一路径（静默回落真实默认路径"
                   "——P1 fail-closed 缺席：未拒绝）",
                   p_default == p_empty,
                   f"default={p_default}\n         empty={p_empty}")
        case.check("红场②：回落全程零告警零留痕（stderr 空——无任何开口）",
                   buf.getvalue() == "", f"stderr={buf.getvalue()!r}")
        case.check("套件安全边界：实验回落目标被 apply_env 钉在临时 aux（真实"
                   "~/.mdcg 全程未被读写）",
                   os.environ["MDCG_AUX_ROOT"] == os.path.join(d, "mdcg_aux")
                   and os.path.isdir(os.path.join(d, "mdcg_aux")),
                   f"aux={os.environ['MDCG_AUX_ROOT']}")

        # 四可（D4）
        case.check("四可：可发现=否（零告警零日志——静默上岗）/可隔离=是（仅该 "
                   "env 键回落链）/可恢复=是（设对 env 即恢复，未写库前无损害）/"
                   "可追溯=否（回落发生无任何留痕，仅读码可证）",
                   True,
                   "证据=红场①② + stderr 恒空")
        verdict = "gap" if not case.fails else "fail"
        return case.finish(verdict, expected="gap")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
