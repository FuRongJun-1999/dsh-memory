# -*- coding: utf-8 -*-
"""condgate 自证（正负对照 + 变异自证）。

纪律来源：统一架构 v1.1 §9.1 —— 验收器必须先过正负对照自证，
否则「通过」不构成证据（等同记忆里那条：扫描器不能自证的 0 命中不可信）。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import condgate  # noqa: E402

OK = 0
FAIL = 0


def check(name, cond):
    global OK, FAIL
    if cond:
        OK += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s" % name)


FULL = {"observation_position": "designer", "observation_tool": "manual",
        "time_window": "2026-10-24", "existence_constraint": "local-only"}
PARTIAL = {"observation_position": "designer", "observation_tool": "manual"}

CCG_OK = ("# 功能名：X6 判定单\n"
          "# 生效条件：需要区分操作态与资格态时\n"
          "# 子功能：①四态②证据标签\n"
          "# 执行：略\n")
CCG_NO_WHEN = "# 功能名：只有名字\n# 子功能：缺生效条件\n"

print("[1] 规范化")
n, miss, unk = condgate.normalize_condition_space(FULL)
check("四维齐全 → 无缺失", len(n) == 4 and miss == [])
n2, miss2, _ = condgate.normalize_condition_space(PARTIAL)
check("缺两维 → missing 报出 2 项", len(miss2) == 2 and "time_window" in miss2)
n3, miss3, unk3 = condgate.normalize_condition_space({"observation_position": "x", "extra": "y"})
check("未知键进 unknown 而非丢弃", unk3 == ["extra"] and miss3 == ["observation_tool", "time_window", "existence_constraint"])
check("非 dict 视为空", condgate.normalize_condition_space("oops")[0] == {})
check("空白字符串算缺失", condgate.normalize_condition_space({"observation_position": "   "})[1][0] == "observation_position")

print("[2] 同槽指纹")
k1 = condgate.slot_key(CCG_OK)
k2 = condgate.slot_key(CCG_OK.replace("X6 判定单", "X6 判定单 ").replace("\n", "\n\n"))
check("三要素齐 → 有指纹", isinstance(k1, str) and len(k1) == 16)
check("空白差异不影响指纹（归一化生效）", k1 == k2)
check("缺生效条件 → 无指纹（不猜）", condgate.slot_key(CCG_NO_WHEN) is None)
check("同槽异值 → 指纹不同", k1 != condgate.slot_key(CCG_OK.replace("X6 判定单", "别的功能")))

print("[3] 灰度闸")
def run(mode_value, payload):
    os.environ["MDCG_CONDGATE"] = mode_value
    ctx = {"a": dict(payload), "nid": "n_test", "cg": None}
    return condgate.before_hook()(ctx), ctx

r_off, c_off = run("off", {"content": "x"})
check("off → 放行且不记 ctx", r_off is None and "condspace" not in c_off)

r_obs, c_obs = run("observe", {"content": "x"})
check("observe 缺条件空间 → 仍放行（不阻断）", r_obs is None)
# 供给改造后 time_window 自动用系统时间补，故「完全没有」应记为 partial（缺三维）而非 missing。
check("observe 记录 partial（time_window 已自动补）", c_obs["condspace"]["state"] == "partial")
check("自动补的是 time_window 而不是替作者猜其余三维",
      c_obs["condspace"]["missing"] == ["observation_position", "observation_tool", "existence_constraint"])
check("自动补写回 a，落盘可见", isinstance(c_obs["a"].get("condition_space", {}).get("time_window"), list))

print("[别名] 中文键名归一")
r_alias, c_alias = run("enforce", {"content": "x", "condition_space": {
    "观测位置": "designer", "观测工具": "manual", "存在约束": "local"}})
check("中文三键 + 自动 time_window → 四维齐全放行", r_alias is None)
check("归一后只剩四维英文键", set(c_alias["a"]["condition_space"]) == set(condgate.FOUR_DIMS))
# 注意：run() 返回 (res, ctx)——首版少解包一个变量，r_auto 拿到整个元组而恒为"非 None"，
# 制造了一条假失败。断言处必须解包，且顺带核对 time_window 原值未被自动填充覆盖。
r_auto, c_auto = run("enforce", {"content": "x", "condition_space": {
    "observation_position": "d", "observation_tool": "m", "existence_constraint": "l",
    "time_window": [1.0, 2.0]}})
check("作者显式声明 time_window 时不被覆盖",
      r_auto is None and c_auto["a"]["condition_space"]["time_window"] == [1.0, 2.0])

r_obs2, c_obs2 = run("observe", {"content": "x", "condition_space": FULL})
check("observe 完整 → complete", c_obs2["condspace"]["state"] == "complete")

r_enf, _ = run("enforce", {"content": "x"})
check("enforce 缺失 → 短路 REJECT 打回", isinstance(r_enf, dict) and r_enf["verdict"]["state"] == "REJECT")
check("enforce 打回不入队列", r_enf["committed"] is False and r_enf["moved_to"] == "rejected_condspace")
check("打回体标明责任在作者", r_enf["verdict"]["detail"]["return_to"] == "author")

r_enf2, c_enf2 = run("enforce", {"content": "x", "condition_space": PARTIAL})
check("enforce 不完整 → 也短路", isinstance(r_enf2, dict))

r_enf3, c_enf3 = run("enforce", {"content": "x", "condition_space": FULL})
check("enforce 完整 → 放行", r_enf3 is None)
check("enforce 放行时写回规范化的四维", len(c_enf3["a"]["condition_space"]) == 4)

print("[正文解析] 指南写的「# 条件空间：」行必须生效")
_p = condgate.parse_condition_space_from_content(
    "# 功能名：样例\n# 条件空间：观测位置=设计者视角；观测工具=自证脚本；存在约束=仅副本\n# 执行：略")
check("中文键 + 全角分号 → 解析出三维", _p == {"observation_position": "设计者视角",
                                                "observation_tool": "自证脚本",
                                                "existence_constraint": "仅副本"})
_p2 = condgate.parse_condition_space_from_content("# 条件空间：observation_position=A; observation_tool=B")
check("英文键 + 半角分号 → 解析出两维", len(_p2) == 2)
check("无该行 → 返回空（不猜）", condgate.parse_condition_space_from_content("无提示行") == {})
r_flow, c_flow = run("enforce", {"content": "# 功能名：样本\n# 条件空间：观测位置=A；观测工具=B；存在约束=C\n依据：见文档 3.1 节"})
check("正文写法在 enforce 下可放行（指南承诺兑现）", r_flow is None)
check("来源登记：content_keys 非空", len(c_flow["condspace_source"]["content_keys"]) == 3)

print("[4] 变异自证（判据是否真在起作用）")
import importlib
importlib.reload(condgate)
os.environ["MDCG_CONDGATE"] = "enforce"
_saved = condgate.normalize_condition_space
# 变异：让规范化**恒报完整**（模拟「验收器永远判通过」）——这才是判据失效的正确形态。
# 注意不能只清 missing：空条件空间走的是 not normalized 分支，清 missing 仍会拦截（首版变异即栽在此）。
condgate.normalize_condition_space = lambda cs: (dict(FULL), [], [])
r_mut, _ = run("enforce", {"content": "x"})
check("变异（永不报缺失）后 enforce 不再拦截 → 证明判据承重", r_mut is None)
condgate.normalize_condition_space = _saved
importlib.reload(condgate)
os.environ["MDCG_CONDGATE"] = "enforce"
r_back, _ = run("enforce", {"content": "x"})
check("还原后 enforce 重新拦截 → 变异自证闭合", isinstance(r_back, dict))

print("[5] 档位容错")
os.environ["MDCG_CONDGATE"] = "bogus_value"
check("非法档位回落 observe", condgate.mode() == "observe")
del os.environ["MDCG_CONDGATE"]
check("未设档位默认 observe", condgate.mode() == "observe")

print("")
print(json.dumps({"ok": OK, "fail": FAIL, "verdict": "PASS" if FAIL == 0 else "FAIL"},
                 ensure_ascii=False))
sys.exit(0 if FAIL == 0 else 1)
