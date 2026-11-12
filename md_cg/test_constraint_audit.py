# -*- coding: utf-8 -*-
"""md_cg.constraint_audit 的守卫测试。

固化的行为契约（2026-10-24 第四十七轮）：
    1. 约束能在日志里找到对应记录 → checked
    2. 找不到 → unchecked，且**不等于没违反**（I6）
    3. 编造的约束必须落 unchecked（不能因为日志里有别的词就误判）
    4. 无清单 / 空日志 → ok=None（无法判定，不默认通过）
    5. 返回必带 note，声明「有记录/无记录 ≠ 遵守/违反」

为什么单独立测：这是 H7 唯一的可行验证路径（第四十六轮），
若它把「没找到」当成「没违反」，结论会反向。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import constraint_audit as cau  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILS.append(name)


LOG = """abc1234 feat(cohesion): 拼装接缝检测
def5678 feat(constraint-watch): 约束巡检模块
ghi9012 docs: 补适用边界
"""


def main():
    items = cau.parse_constraints("C1 约束巡检\nC2 拼装接缝检测\n")

    # ① 能找到
    rep = cau.cross_check(items, LOG)
    check("全部能找到 ok=True", rep["ok"] is True, rep["counts"])
    check("checked 有证据", all(c.get("evidence") for c in rep["checked"]), rep["checked"])

    # ② 编造的找不到
    rep = cau.cross_check("C9 不得把火星数据写入木星表\n", LOG)
    check("编造约束 unchecked", rep["ok"] is False, rep["counts"])
    check("编造约束 cover 低",
          rep["unchecked"][0]["cover"] < cau.MATCH_THRESHOLD, rep["unchecked"])

    # ③ 空输入 → None
    check("无清单 ok=None", cau.cross_check("", LOG)["ok"] is None)
    check("空日志 ok=None", cau.cross_check(items, "")["ok"] is None)

    # ④ 必带 I6 提示
    rep = cau.cross_check(items, LOG)
    check("note 含 I6 提示", "不等于" in rep["note"], rep["note"][:50])

    # ⑤ 部分命中
    rep = cau.cross_check("C1 约束巡检\nC9 火星木星\n", LOG)
    check("部分命中 checked=1", rep["counts"]["checked"] == 1, rep["counts"])
    check("部分命中 unchecked=1", rep["counts"]["unchecked"] == 1, rep["counts"])

    print("")
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), FAILS))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
