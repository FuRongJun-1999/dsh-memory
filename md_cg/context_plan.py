# -*- coding: utf-8 -*-
"""上下文规划器（context_plan）——把五步判据链做成可执行建议。

来源：上下文管理研究（三十轮）框架 v4。五步链是：
    ① 判级      按不可逆性 → L1 / L2 / L3 / 灰区
    ② 定形态    该级需要「并列」还是「连续」
    ③ 定声明    L2 起四维条件空间；L3 加逐条不可逆清单
    ④ 拼装      并列→检索拼装+指针；连续→原文优先
    ⑤ 核对      读数比对；不达标三选一，不得静默

**本模块是启发式，不是判级本身。**
判级需要判断「后果可否撤销」，那是语义判断；本模块只做两件机械的事：
    * 扫强制词（不能／不得／必须…）→ 抬到至少 L2
    * 扫不可逆词（覆盖／删除／永久…）→ 抬到 L3
判不出时**按 L2 兜底，不按 L1**——因为误判为低是不可逆损失（研究第六轮）。

诚实边界：
    1. 词表是启发式，会漏（用户可用陈述句表达强制：「我们希望旧文件保留」）；
    2. 判级准确率未知——判级本身属盲区 13；
    3. 输出是**建议**，不是裁决；人可覆盖，但覆盖须留理由（降级留痕，升级不用）；
    4. 不读上下文，只读传入的任务描述。
"""

import re

__all__ = ["plan", "LEVELS", "MANDATORY_RE", "IRREVERSIBLE_RE", "FACT_SEEKING_RE"]

LEVELS = ("L1", "L2", "L3", "灰区")

#: 强制语气词：出现即至少 L2
MANDATORY_RE = re.compile(r"(不能|不得|不许|禁止|必须|务必|一律|绝不|不可|一定要|严禁)")

#: 不可逆词：出现即 L3（后果不可撤销）
IRREVERSIBLE_RE = re.compile(
    r"(覆盖|删除|销毁|永久|不可恢复|不可逆|彻底清除|重写历史|force|drop|truncate)")

#: 查事实型：倾向 L1（并列够用）
FACT_SEEKING_RE = re.compile(r"(是什么|是多少|哪一年|哪个版本|查一下|确认一下|是否等于)")

#: 各层级的策略建议
_PLAYBOOK = {
    "L1": {
        "form": "并列",
        "declaration": "可不声明（或一句话记约束）",
        "strategy": "滑窗／截断均可；检索拼装够用，不追求接缝",
        "check": "不做（错了可重来）",
    },
    "L2": {
        "form": "半连续",
        "declaration": "四维条件空间（观测位置／工具／时间窗／存在约束）",
        "strategy": "分层折叠＋指针；原文下沉但保留可回取",
        "check": "核对关键约束能否从当前上下文推出",
    },
    "L3": {
        "form": "连续",
        "declaration": "四维 ＋ 逐条不可逆清单（清单必须外置，不得留在上下文里）",
        "strategy": "原文优先；必须拼装时用指针，不硬拼",
        "check": "全量核对；推不出必须三选一（回取／报警／显式降级），不得静默",
    },
    "灰区": {
        "form": "按 L3（声明）／按实际（策略）",
        "declaration": "按 L3 声明（清单外置），但策略可用便宜方式",
        "strategy": "声明升 L3、策略按实际能力——灰区解耦（研究第七轮）",
        "check": "核对清单；不可用则显式降级并留理由",
    },
}


def plan(task_text):
    """给定任务描述，返回规划建议。

    返回 dict：
        level         L1 / L2 / L3 / 灰区
        level_reason  判定依据（命中的词或「无命中，按 L2 兜底」）
        mandatory     命中的强制词
        irreversible  命中的不可逆词
        fact_seeking  是否为查事实型
        form / declaration / strategy / check   各步建议
        caveat        必读的边界提示
    """
    text = str(task_text or "")
    mand = sorted(set(MANDATORY_RE.findall(text)))
    irrev = sorted(set(IRREVERSIBLE_RE.findall(text)))
    fact = bool(FACT_SEEKING_RE.search(text))

    if irrev:
        level = "L3"
        reason = "命中不可逆词 %s → 后果不可撤销" % ("、".join(irrev))
    elif mand:
        level = "L2"
        reason = "命中强制词 %s → 至少 L2（含不可逆则升 L3）" % ("、".join(mand))
    elif fact:
        level = "L1"
        reason = "查事实型且无强制/不可逆词 → L1（并列够用）"
    else:
        level = "灰区"
        reason = "无强制/不可逆命中，也未识别为查事实型 → 灰区，声明按 L3、策略按实际"

    pb = _PLAYBOOK[level]
    return {
        "level": level,
        "level_reason": reason,
        "mandatory": mand,
        "irreversible": irrev,
        "fact_seeking": fact,
        "form": pb["form"],
        "declaration": pb["declaration"],
        "strategy": pb["strategy"],
        "check": pb["check"],
        "caveat": "本输出是启发式建议非裁决；词表会漏（陈述句也可表达强制）；"
                  "降级须留理由，升级不用。",
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
        print("用法：python -m md_cg.context_plan \"任务描述\" [--json]")
        return 2
    rep = plan(argv[0])
    if "--json" in argv:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print("层级：%s" % rep["level"])
        print("依据：%s" % rep["level_reason"])
        print("形态：%s" % rep["form"])
        print("声明：%s" % rep["declaration"])
        print("策略：%s" % rep["strategy"])
        print("核对：%s" % rep["check"])
        print("")
        print("注：%s" % rep["caveat"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
