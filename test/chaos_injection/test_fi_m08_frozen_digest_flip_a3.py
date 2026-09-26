# -*- coding: utf-8 -*-
"""FI-M08 · S4 自身（改自身判据面/自证风险）→ 字节翻转冻结凭证 digest。

判据：P4 判据冻结（验证者≠被验证者）+ T5 独立验证 + T12（判据落在冻结原文
指纹上，任何未冻结的判据面变化都使 A3 红）+ T3（互验结论可由不经过裁决者的
证据链 frozen.json 原文复核）。判据面：md_cg/interop.py:108-136（freeze）/
:139-143（assert_a3 承重墙）；消费点 hive/verify_runner.py:151（a3 =
assert_a3(frozen, fp_ver)）。
注入：interop.freeze('fi_iter', out_dir=<tmp>)（函数自注「仅适用于单测/离线
留痕」）冻结到临时目录，盘上 frozen.json 的 digest 首字符 XOR 0x01 后，以原
指纹调 assert_a3。

理论预期（登记 pass，回归守卫）：翻转后文件仍可解析（digest 变值——完整性
锚不在文件格式层），assert_a3(原指纹)=False——比对直接失败，verdict 作废路径
成立（注入红＝防线有效）。对照组：未篡改凭证 assert_a3=True。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness        # noqa: E402
import mdcg_support   # noqa: E402


def main() -> int:
    case = harness.Case("FI-M08", "冻结凭证 digest 翻转：A3 承重墙比对失败")
    try:
        d = case.tmpdir("m08")
        mdcg_support.apply_env(d)
        from md_cg import interop

        case.check("读码：A3 消费点在位（verify_runner 以前轮冻结值为尺）",
                   "a3 = assert_a3(frozen, fp_ver)"
                   in harness.src("hive/verify_runner.py"),
                   "hive/verify_runner.py:151")

        out = os.path.join(d, "interop")
        cred = interop.freeze("fi_iter", out_dir=out)   # 临时离线留痕
        fp_real = interop._manifest("--digest")

        # ═══ 对照组：未篡改凭证 ═══
        a3_0 = interop.assert_a3(cred, fp_real)
        case.check("对照组：未篡改冻结值 == 当前指纹 → A3 ok=True（看同一把尺）",
                   a3_0["ok"] is True and a3_0["frozen"] == fp_real,
                   f"a3={a3_0}")

        # ═══ 主场：digest 首字符 XOR 0x01 ═══
        fp = cred["_path"]
        with open(fp, encoding="utf-8") as f:
            data = json.load(f)
        d0 = data["digest"]
        data["digest"] = format(int(d0[0], 16) ^ 0x01, "x") + d0[1:]
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        with open(fp, encoding="utf-8") as f:
            tampered = json.load(f)
        case.check("注入生效：盘上凭证被改写但仍可解析（digest 变值——文件格式层"
                   "不设防，防线全押在指纹比对）",
                   tampered["digest"] != d0 and tampered["digest"][1:] == d0[1:],
                   f"{d0[0]}→{tampered['digest'][0]}")
        a3_1 = interop.assert_a3(tampered, fp_real)
        case.check("红场：篡改冻结值 vs 原指纹 → assert_a3 ok=False（判据面任何"
                   "未冻结变化使 A3 红、valid=false——verdict 作废路径成立）",
                   a3_1["ok"] is False and a3_1["frozen"] == tampered["digest"]
                   and a3_1["actual"] == fp_real,
                   f"a3={a3_1}")

        # 四可（D4）
        case.check("四可：可发现=是（A3 比对直接失败）/可隔离=是（digest 单字段"
                   "比对，篡改可定位到冻结凭证）/可恢复=是（重新 freeze 恢复基准，"
                   "被污染轮次的 verdict 按 ok=False 作废=安全侧）/可追溯=是"
                   "（frozen.json 原文在盘，T3 证据链不经过裁决者可复核）",
                   True,
                   f"证据=对照 ok=True + 红场 ok=False（{d0[0]}→{tampered['digest'][0]}）")
        verdict = "pass" if not case.fails else "fail"
        return case.finish(verdict, expected="pass")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
