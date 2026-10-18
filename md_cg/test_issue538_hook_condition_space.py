# -*- coding: utf-8 -*-
"""test_issue538_hook_condition_space · 自动记忆钩子必须构造四槽 condition_space（#538 源码面）

# 功能名：src/hooks.ts 三处 remember() 调用必须带 condition_space，且四槽齐全
# 生效条件：读 src/hooks.ts 源码（不执行 TS —— 行为面需 tsx，本守卫只钉源码结构）
# 子功能：A 三处 remember 各带 condition_space · B condSpace 返回四槽齐全 · C 槽名与 md_cg/nodefile.CONDITION_SLOTS 同源 · D 时间维为小时粒度
# 执行：python -X utf8 -m md_cg.test_issue538_hook_condition_space
# 验证方式：全部 PASS 即通过（退出码 0）
# 不适用条件：不判 consolidate 真能归纳出节点（需 tsx 跑 TS 守卫，单独补测）；不判 condSpace 的运行时取值（时钟相关）；不判 mdcg_client 的 remember 签名（既有）
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "hooks.ts")


def _src():
    with open(SRC, encoding="utf-8") as f:
        return f.read()


def g_a_three_calls():
    s = _src()
    n = len(re.findall(r"condition_space:\s*condSpace\(", s))
    assert n == 3, "应有 3 处 condition_space: condSpace(...)，实得 %d" % n
    print("  PASS A 三处 remember() 各带 condition_space（实得 3）")


def g_b_four_slots():
    s = _src()
    i = s.find("function condSpace(")
    assert i > 0, "condSpace 定义不在"
    body = s[i:i + 1200]
    for slot in ("observation_position", "time_window", "observation_tool", "existence_constraint"):
        assert slot in body, "condSpace 缺槽 %s" % slot
    print("  PASS B condSpace 返回四槽齐全")


def g_c_slots_match_nodefile():
    sys.path.insert(0, ROOT)
    from md_cg import nodefile
    keys = [k for k, _l in nodefile.CONDITION_SLOTS]
    body = _src()[_src().find("function condSpace("):][:1200]
    missing = [k for k in keys if k not in body]
    assert not missing, "condSpace 与 nodefile.CONDITION_SLOTS 不同源，缺：%r" % (missing,)
    assert len(keys) == 4, "CONDITION_SLOTS 应为四槽，实得 %d" % len(keys)
    print("  PASS C 槽名与 md_cg/nodefile.CONDITION_SLOTS 同源（%s）" % ",".join(keys))


def g_d_hour_granularity():
    s = _src()
    body = s[s.find("function condSpace("):][:1200]
    assert "3600000" in body, "时间维应为小时粒度（3600000 ms）"
    assert "Math.floor" in body, "时间维应向下取整到小时"
    print("  PASS D 时间维为小时粒度（3600000ms + Math.floor）")


def g_e_semantic_render():
    """语义面：复刻 condSpace 的产出，喂给 nodefile.condition_space_text(require_full=True)。

    这条补的是「四槽齐全」与「能被唯一合成入口渲染」之间的一步：
    源码面只证明槽名在，语义面证明它们组合起来是合法生效条件。
    """
    sys.path.insert(0, ROOT)
    from md_cg import nodefile
    import time
    hour = float(int(time.time() // 3600))      # 秒为单位的小时序号，与 src/hooks.ts 同一算式
    for role in ("user", "assistant", "tool"):
        cs = {
            "observation_position": "dsh-hook/%s-message" % role,
            "time_window": [hour, hour],
            "observation_tool": "dsh-memory-hook",
            "existence_constraint": "%s-message-minlen1" % role,
        }
        txt = nodefile.condition_space_text(cs, require_full=True)
        assert txt, "%s 的四槽应能渲染成非空条件文本，实得空串" % role
        for k in list(cs):
            partial = dict((kk, vv) for kk, vv in cs.items() if kk != k)
            assert nodefile.condition_space_text(partial, require_full=True) == "", \
                "缺 %s 时不应渲染成功" % k
    print("  PASS E 语义面：四槽齐全 ⇒ 可渲染；缺任一槽 ⇒ 空串（非恒真）")


def main():
    print("=== #538 自动记忆钩子的四槽 condition_space（源码面）===")
    g_a_three_calls()
    g_b_four_slots()
    g_c_slots_match_nodefile()
    g_d_hour_granularity()
    g_e_semantic_render()
    print("===== 全绿 =====")


if __name__ == "__main__":
    main()