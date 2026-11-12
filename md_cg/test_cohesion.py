# -*- coding: utf-8 -*-
"""md_cg.cohesion 的守卫测试。

固化的行为契约（2026-10-24）：
    1. 单块 → ok=None（无接缝可言，**不得**判为断裂）
    2. 连续句流中点切两半 → ok=True（接缝天然连续）
    3. 不相干章节拼装 → ok=False（真断裂）
    4. 过短内容 → ok=None（算不出，不给默认通过）
    5. 标题行不参与重叠（曾导致同章节切分被判 0.0）
    6. seam_ratio 在块数 <2 时返回 None，不返回 0

为什么单独立测：这些边界此前逐个踩过（三次返工），
任何一条回退都会让「拼装断裂」的判据失真。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import cohesion as co  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILS.append(name)


# 构造：一段有明显承接的连续文本
CONT = (
    "信息差是协作行为的不确定性度量。"
    "它由四个维度加权得到。"
    "四维度分别是信任补集、行为偏差、连接偏离与预测误差。"
    "每个维度都有各自的归一化区间。"
    "加权后得到综合度量 D_norm。"
    "D_norm 越大表示不确定性越高。"
)
OTHER = "本章讨论裁决权的归属与监督方式。它规定了优先保护存在。可逆性优先也是其中一条。"


def main():
    # ① 单块：无接缝
    rep = co.check([CONT])
    check("单块 ok=None", rep["ok"] is None, rep)
    check("单块 cross_boundary=None", rep["cross_boundary"] is None, rep)
    check("单块 inner_adj>0", rep["inner_adj"] > 0, rep)

    # ② 连续句流中点切两半：接缝连续
    sents = co.split_sentences(CONT)
    half = len(sents) // 2
    two = ["\n".join(sents[:half]), "\n".join(sents[half:])]
    rep = co.check(two)
    check("连续切两半 ok=True", rep["ok"] is True, rep)
    check("连续切两半 ratio>0", (rep["ratio"] or 0) > 0, rep)

    # ③ 不相干章节：判断裂
    rep = co.check([CONT, OTHER])
    check("不相干拼装 ok=False", rep["ok"] is False, rep)

    # ④ 过短：无法判定
    rep = co.check(["短。", "也短。"])
    check("过短 ok=None", rep["ok"] is None, rep)

    # ⑤ 标题行不参与重叠
    body = co.split_sentences("### 2.7.1 标题\n正文第一句在这里。\n正文第二句也在这里。")
    check("标题被过滤", not any(s.startswith("#") for s in body), body)
    check("正文保留", len(body) >= 1, body)

    # ⑥ seam_ratio 单块返回 None
    ratio, detail = co.seam_ratio([CONT])
    check("seam_ratio 单块=None", ratio is None, detail)

    # ⑦ 空输入不炸
    rep = co.check([])
    check("空输入 ok=None", rep["ok"] is None, rep)

    # ⑧ 信噪比读数（2026-10-24 第三十六轮补，对应「稀释」这一损失）
    TGT = "平均段长是 5.79 句每段，摘要保留率等于 1 除以平均段长。"
    r = co.signal_ratio(TGT, TGT + "无关内容" * 3)
    check("信噪比 clear", r["verdict"] == "clear" and r["ok"] is True, r)
    r = co.signal_ratio(TGT, TGT + "无关内容段落。" * 400)
    check("信噪比 drowned", r["verdict"] == "drowned" and r["ok"] is False, r)
    check("信噪比 drowned 给出比例", (r["ratio"] or 1) < co.SIGNAL_LOW, r)
    # thin 必须返回 None，不得默认通过、也不得判坏
    r = co.signal_ratio(TGT, TGT + "无关内容段落。" * 140)
    check("信噪比 thin ok=None", r["ok"] is None, r)
    check("信噪比 thin 标记为 thin", r["verdict"] == "thin", r)
    r = co.signal_ratio("", "一些上下文")
    check("信噪比空目标 ok=None", r["ok"] is None, r)
    r = co.signal_ratio(TGT, "")
    check("信噪比空上下文 ok=None", r["ok"] is None, r)

    print("")
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), FAILS))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
