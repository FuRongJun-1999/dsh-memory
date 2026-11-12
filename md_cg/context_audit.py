# -*- coding: utf-8 -*-
"""上下文审计（context_audit）——一次跑完三种损失的检查。

框架 v5 第⑤步要求「三种损失各查一遍」：
    丢弃 → constraint_watch.check   （约束表述还在不在）
    稀释 → cohesion.signal_ratio     （目标被淹没得多深）
    断裂 → cohesion.seam_ratio       （拼装接缝接不接得上）

本模块把三者合成一次调用，并给出**一个**判定。三点设计立场：

1. **按层级裁剪要求**（框架 v5 第②步）：
   L1 任务不要求接缝（并列够用），L3 才要求连续。所以不是所有损失对
   所有任务都算失败——本模块按 plan 出的层级决定哪些检查生效。

2. **None 不默认通过，也不判坏**：
   任一检查为 None 且有检查为 True 时，判定为 UNKNOWN——
   「没能核对」既不能当通过，也不能当失败。

3. **只报不做**：
   本模块给建议（回取／报警／显式降级），但**不执行**。
   执行要改上下文，那是调用方的事——这条边界与三个底层工具一致。
"""

__all__ = ["audit", "VERDICTS", "LEVEL_REQUIREMENTS"]

from . import context_plan as cp
from . import cohesion as co
from . import constraint_watch as cw

VERDICTS = ("PASS", "FAIL", "UNKNOWN")

#: 各层级需要哪些检查。True=必须过；False=不适用
#: 各层级需要哪些检查。True=必须过；False=不适用
#:
#: **为什么 L2 不强制 broken**（2026-10-24 实测修正）：
#: 框架 v4/v5 第②步说 L2 要「半连续」——**步骤要连、章节可断**。
#: 而 cohesion 测的是块间接缝，对结构化文档（章节并列、靠标题导航）
#: 本来就低（第十八轮实测：17 份结构化文档中 3 份被误判）。
#: 若 L2 强制 broken，会把正常的结构化上下文判为失败。
#: 故 broken 只在 L3（要求连续）与灰区（保守）时强制执行，
#: L2 给出读数但不判失败。
LEVEL_REQUIREMENTS = {
    "L1": {"dropped": True,  "diluted": True,  "broken": False},
    "L2": {"dropped": True,  "diluted": True,  "broken": False},
    "L3": {"dropped": True,  "diluted": False, "broken": True},
    "灰区": {"dropped": True, "diluted": True, "broken": True},
}


def _verdict_of(required, results):
    """把三项结果合成一个判定。

    * 任一 required 项为 False → FAIL（有确凿问题）
    * 否则若有 required 项为 None → UNKNOWN（没能核对）
    * 否则 → PASS
    注意 broken 的语义：cohesion 的 ok 只有 True/False/None 三态。
    """
    failure = []
    unknown = []
    for key, need in required.items():
        if not need:
            continue
        r = results.get(key) or {}
        ok = r.get("ok")
        if ok is False:
            failure.append(key)
        elif ok is None:
            unknown.append(key)
    if failure:
        return "FAIL", failure, unknown
    if unknown:
        return "UNKNOWN", failure, unknown
    return "PASS", failure, unknown


def audit(task_text, blocks=None, checklist=None, target_text=None):
    """跑完三种损失检查并给出一个判定。

    参数：
        task_text   任务描述（用于判级）
        blocks      上下文块列表（用于接缝检查）
        checklist   约束清单文本（用于丢弃检查）
        target_text 目标事实文本（用于稀释检查）；应包含在 blocks 拼起来的文本里

    返回 dict：
        verdict   PASS / FAIL / UNKNOWN
        level     判出的层级
        losses    {dropped, diluted, broken} 各自原始结果
        failed    未通过的检查项
        unknown   无法判定的检查项
        actions   建议动作列表
        note      边界提示
    """
    p = cp.plan(task_text)
    level = p["level"]
    required = LEVEL_REQUIREMENTS.get(level, LEVEL_REQUIREMENTS["灰区"])

    joined = "\n".join([b for b in (blocks or []) if b])
    losses = {}

    # ① 丢弃
    if checklist:
        losses["dropped"] = cw.check(checklist, joined)
    else:
        losses["dropped"] = {"ok": None, "reason": "未提供约束清单，无从核对"}

    # ② 稀释（需要目标文本）
    if target_text and joined:
        losses["diluted"] = co.signal_ratio(target_text, joined)
    else:
        losses["diluted"] = {"ok": None, "reason": "未提供目标文本或上下文为空"}

    # ③ 断裂（需要 ≥2 块）
    if blocks and len([b for b in blocks if b]) >= 2:
        rep = co.check(blocks)
        losses["broken"] = {"ok": rep.get("ok"), "ratio": rep.get("ratio"),
                            "inner_adj": rep.get("inner_adj"),
                            "cross_boundary": rep.get("cross_boundary")}
    else:
        losses["broken"] = {"ok": None, "reason": "块数不足 2，无接缝可言"}

    verdict, failure, unknown = _verdict_of(required, losses)

    actions = []
    dropped = losses["dropped"]
    if dropped.get("ok") is False:
        for m in dropped.get("missing", []):
            actions.append("丢弃·%s %s → %s" % (m.get("id", ""), m.get("text", ""),
                                              m.get("advice", "回取")))
    if losses["diluted"].get("ok") is False:
        actions.append("稀释·目标占比 %s → 提高信噪比（删无关内容），不是单纯缩短"
                       % losses["diluted"].get("ratio"))
    if losses["broken"].get("ok") is False:
        actions.append("断裂·接缝比 %s → 连续任务应保原文或用指针，不硬拼"
                       % losses["broken"].get("ratio"))
    for key in unknown:
        actions.append("%s·无法判定 → 先补材料再判，不得当作通过" % key)
    # 未强制但读出问题的项也提示（不判失败，只提醒）
    for key, need in required.items():
        if need:
            continue
        r = losses.get(key) or {}
        if r.get("ok") is False:
            actions.append("%s·本层不强制，但读数偏低（%s）→ 若该任务实际需要连续上下文，应升层"
                           % (key, r.get("ratio")))

    return {
        "verdict": verdict,
        "level": level,
        "required": required,
        "losses": losses,
        "failed": failure,
        "unknown": unknown,
        "actions": actions,
        "note": "本模块只报不做：actions 是建议，执行（回取/降级）由调用方负责。"
                "UNKNOWN 不等于失败，也不等于通过。",
    }


def main(argv=None):
    import json
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print('用法：python -m md_cg.context_audit "任务描述" [--json]')
        print('（CLI 只做判级与要求裁剪；三种损失需在代码里传材料）')
        return 2
    rep = audit(argv[0])
    if "--json" in argv:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print("判定：%s（层级 %s）" % (rep["verdict"], rep["level"]))
        print("要求：%s" % rep["required"])
        for a in rep["actions"]:
            print("  - %s" % a)
        print("")
        print("注：%s" % rep["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
