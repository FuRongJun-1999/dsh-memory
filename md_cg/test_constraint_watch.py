# -*- coding: utf-8 -*-
"""md_cg.constraint_watch 的守卫测试。

固化的行为契约（2026-10-24，上下文管理研究第二十二、二十三轮）：
    1. 全部在场 → ok=True
    2. 部分/全部缺失 → ok=False，且缺的逐条列出
    3. 覆盖率 0 < c < 阈值 → 建议「回取」（有痕迹但不够）
    4. 覆盖率 0 → 建议「报警」（连痕迹都没有）
    5. 空文本 / 无约束 → ok=None（无法判定，**不得**默认通过）
    6. 清单解析只认带编号短行，说明文字不算约束

为什么这些边界要立测：漏报就是静默丢约束（第三轮、第十二轮、第二十二轮
三次同型失败都指向「没有强制就不做」），所以「报不出」比「误报」危险得多。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import constraint_watch as cw  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILS.append(name)


LIST = (
    "# 约束清单\n"
    "C1 不得覆盖旧文件\n"
    "C2 必须留下校验记录\n"
    "C3 不得删除中间产物\n"
)
FULL = "导出必须留下校验记录。不得覆盖旧文件，不得删除中间产物。"
PARTIAL = "本次操作会覆盖一些临时内容。"
EMPTY = "今天天气不错。"


def main():
    # ① 全部在场
    rep = cw.check(LIST, FULL)
    check("全部在场 ok=True", rep["ok"] is True, rep.get("counts"))
    check("全部在场 missing=0", len(rep["missing"]) == 0, rep["missing"])

    # ② 部分缺失：逐条列出
    rep = cw.check(LIST, PARTIAL)
    check("部分缺失 ok=False", rep["ok"] is False, rep.get("counts"))
    check("部分缺失 有回取建议", any(m["advice"] == "回取" for m in rep["missing"]),
          rep["missing"])

    # ③ 全部缺失 → 报警
    rep = cw.check(LIST, EMPTY)
    check("全部缺失 ok=False", rep["ok"] is False, rep.get("counts"))
    check("全部缺失 全为报警", all(m["advice"] == "报警" for m in rep["missing"]),
          rep["missing"])

    # ④ 空文本 / 无约束 → None（不默认通过）
    check("空文本 ok=None", cw.check(LIST, "")["ok"] is None)
    check("无约束 ok=None", cw.check("没有编号条目", FULL)["ok"] is None)
    check("空清单 ok=None", cw.check("", FULL)["ok"] is None)

    # ⑤ 解析只认带编号短行
    items = cw.parse_constraints(LIST)
    check("解析出 3 条", len(items) == 3, items)
    check("编号规范化", [i["id"] for i in items] == ["C1", "C2", "C3"], items)
    long_line = "C9 " + "这是一条很长的说明文字" * 8
    check("超长行不算约束", len(cw.parse_constraints(long_line)) == 0)

    # ⑥ 覆盖率单调性
    c_hi = cw.coverage("不得覆盖旧文件", FULL)
    c_lo = cw.coverage("不得覆盖旧文件", EMPTY)
    check("在场覆盖高于缺失", c_hi > c_lo, (c_hi, c_lo))

    # ⑦ 回取三态（2026-10-24 第三十三轮补）
    r = cw.retrieve_for("不得覆盖旧文件", None)
    check("回取未接入 ok=None", r["ok"] is None, r)
    r = cw.retrieve_for("", None)
    check("回取空文本 ok=None", r["ok"] is None, r)

    class FakeCG:
        def __init__(self, hits):
            self._hits = hits
        def search(self, q, k=3):
            return (self._hits, {})
    r = cw.retrieve_for("不得覆盖旧文件", FakeCG([]))
    check("回取无候选 ok=False", r["ok"] is False, r)
    check("无候选提示含 I6", "不等于" in r["note"], r["note"])
    r = cw.retrieve_for("不得覆盖旧文件",
                        FakeCG([{"id": "n1", "content": "候选内容"}]))
    check("回取有候选 ok=True", r["ok"] is True, r)
    check("有候选仍需人判断", "需判断" in r["note"], r["note"])

    print("")
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), FAILS))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
