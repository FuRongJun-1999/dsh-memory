# -*- coding: utf-8 -*-
"""md_cg.context_plan 的守卫测试。

固化的行为契约（2026-10-24，上下文管理研究框架 v4 五步判据链）：
    1. 命中不可逆词 → L3（后果不可撤销，哪怕同时含强制词）
    2. 只命中强制词 → L2
    3. 查事实型且无强制/不可逆 → L1
    4. 都没有 → 灰区（**不按 L1 兜底**）
    5. 灰区的声明按 L3、策略按实际（解耦）
    6. 每层输出都带 caveat（这是建议不是裁决）

第 4 条为什么重要：误判为高损失可逆有界，误判为低损失不可逆无界（研究第六轮）。
所以「判不出」必须落到灰区/L2，绝不能落到 L1。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import context_plan as cp  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILS.append(name)


def main():
    # ① 不可逆 → L3（即使同时有强制词）
    r = cp.plan("导出数据，但不能覆盖旧文件，必须留下校验记录")
    check("不可逆优先于强制 → L3", r["level"] == "L3", r["level_reason"])
    check("L3 声明含外置清单", "外置" in r["declaration"], r["declaration"])
    check("L3 核对不得静默", "不得静默" in r["check"], r["check"])

    # ② 只强制 → L2
    r = cp.plan("提交前必须跑一遍测试")
    check("只强制 → L2", r["level"] == "L2", r["level_reason"])

    # ③ 查事实 → L1
    r = cp.plan("帮我查一下智能论是哪个版本")
    check("查事实 → L1", r["level"] == "L1", r["level_reason"])

    # ④ 判不出 → 灰区，不落 L1
    r = cp.plan("把这份报告整理成三页")
    check("判不出 → 灰区", r["level"] == "灰区", r["level_reason"])
    check("灰区声明按 L3", "按 L3 声明" in r["declaration"], r["declaration"])
    check("灰区策略按实际", "策略按实际" in r["strategy"], r["strategy"])

    # ⑤ 各层形态互不相同（判据链第②步真的分流了）
    forms = {lv: cp.plan(t)["form"] for lv, t in [
        ("L1", "查一下版本号是多少"),
        ("L2", "必须检查一遍"),
        ("L3", "删除旧文件"),
    ]}
    check("三层形态不同", len(set(forms.values())) == 3, forms)

    # ⑥ 每层都带 caveat
    for t in ("查一下版本", "必须检查", "删除文件", "整理成三页"):
        r = cp.plan(t)
        check("caveat 存在(%s)" % r["level"], bool(r["caveat"]))

    # ⑦ 空输入不炸，落灰区
    r = cp.plan("")
    check("空输入 → 灰区", r["level"] == "灰区", r["level"])

    print("")
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), FAILS))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
