# -*- coding: utf-8 -*-
"""md_cg.context_audit 的守卫测试。

固化的行为契约（2026-10-24，框架 v5 第⑤步「三种损失各查一遍」）：
    1. 三种损失各由一个读数覆盖：dropped / diluted / broken
    2. 判定按层级裁剪——同一份上下文，L2 可 PASS 而 L3 必须 FAIL
    3. 任一 required 项 False → FAIL
    4. 无 False 但有 None → UNKNOWN（**不默认通过，也不判坏**）
    5. L1/L2 不强制 broken，但读数偏低时给出「可升层」提示
    6. 缺材料 → UNKNOWN 而非 PASS

第 2、5 条是实测修正的结果：L2 是「半连续」（步骤要连、章节可断），
若强制接缝，会把正常的结构化上下文判为失败。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import context_audit as ca  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILS.append(name)


# 两块内容不同、但都含目标词的段落（避免依赖外部文件）
A = ("第一段讨论摘要压缩的机制。摘要保留率等于 1 除以平均段长。"
     "这一结论由位置效应推出，段首存活 93.2%。" * 3)
B = ("第二段讨论上下文稀释。上下文稀释达 36.7 倍。"
     "稀释不单调，因为同主题重复会抬高词频。" * 3)
LIST = "C1 摘要保留率等于 1 除以平均段长\nC2 上下文稀释达 36.7 倍\n"
TGT = "摘要保留率等于 1 除以平均段长，上下文稀释达 36.7 倍。"


def main():
    # ① 三种损失都有读数
    r = ca.audit("分析影响，必须给出可核对读数", blocks=[A, B], checklist=LIST, target_text=TGT)
    check("三种损失都有读数",
          set(r["losses"].keys()) == {"dropped", "diluted", "broken"}, r["losses"].keys())

    # ② 层级裁剪：同一上下文 L2 与 L3 判定可不同
    l2 = ca.audit("分析影响，必须给出可核对读数", blocks=[A, B], checklist=LIST, target_text=TGT)
    l3 = ca.audit("导出数据，但不能覆盖旧文件", blocks=[A, B], checklist=LIST, target_text=TGT)
    check("L2 判为 L2", l2["level"] == "L2", l2["level"])
    check("L3 判为 L3", l3["level"] == "L3", l3["level"])
    check("L2 不强制 broken", l2["required"]["broken"] is False, l2["required"])
    check("L3 强制 broken", l3["required"]["broken"] is True, l3["required"])

    # ③ 缺材料 → UNKNOWN（不默认通过）
    r = ca.audit("导出数据，但不能覆盖旧文件")
    check("缺材料 UNKNOWN", r["verdict"] == "UNKNOWN", r["verdict"])
    check("缺材料 无 PASS", r["verdict"] != "PASS", r)

    # ④ 约束缺失 → FAIL
    bad = LIST + "C9 不得把火星数据写入木星表\n"
    r = ca.audit("导出数据，但不能覆盖旧文件", blocks=[A, B], checklist=bad, target_text=TGT)
    check("约束缺失 FAIL", r["verdict"] == "FAIL", r["verdict"])
    check("约束缺失 列出 dropped", "dropped" in r["failed"], r["failed"])

    # ⑤ L1 连 diluted 之外的 broken 也不要求
    r = ca.audit("帮我查一下是哪个版本", blocks=[A, B], checklist=LIST, target_text=TGT)
    check("L1 不强制 broken", r["required"]["broken"] is False, r["required"])

    # ⑥ 只报不做：必带 note
    r = ca.audit("分析影响", blocks=[A, B], checklist=LIST, target_text=TGT)
    check("必带 note", bool(r["note"]) and "只报不做" in r["note"], r["note"][:40])

    print("")
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), FAILS))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
