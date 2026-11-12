# -*- coding: utf-8 -*-
# 功能名：生效条件质量判据守卫（issue #722 / 规范 v0.5）
# 生效条件：python -X utf8 -m md_cg.test_722_condition_quality；被测面＝md_cg/writegate.py 的 cond_is_metadata / check_condition_quality
# 子功能：
#   A. `cond_is_metadata`：四槽合成形态（载体/位置+约束/方法）判为元数据；
#      真实的触发场景（「当他说…时」）**不**误判；混合条件也不误判
#   B. `check_condition_quality`：把 A 包装成写入把关结果（ok/is_metadata/hint），**任何情况下不抛**
#   C. 两处反例：无生效条件行、空内容 → ok=True（无条件是另一类问题）
# 执行：纯函数级断言，不建库、不写盘
# 验证方式：全部 PASS exit 0；每条注明「怎么让它红」
# 不适用条件：不测「库内元数据占比」（那需要读真实库，属实测脚本而非守卫）；不测接线（`add` 尚未接）
"""为什么要这个守卫：

实测（2026-10-31，全库 32842 抽样 120）发现 **76.5% 的生效条件是元数据**——
形如 `载体/位置：本地文档仓（大域=xxx）；时间：全时窗；方法：md…；约束：源文档 a/b.md`，
而**0 条**是「用户会怎么说」。这类条件在检索时几乎不可能被自然问法命中（#722 现象）。

判据经**四次修正**才定稿（详见规范 v0.5 第八节）：
  ① 正向「所有词项都含元数据特征」→ 路径片段（knowledge / x.md）使 all() 恒 False；
  ② 加短词表 → 仍 0 条；
  ③ 反向「不含场景标志词」→ 单字「时」被「全时窗」误触发；
  ④ **结构化槽标签**（本守卫固化）→ 5/5 用例 + 实测 76.5%。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg.writegate import check_condition_quality, cond_is_metadata  # noqa: E402

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


META = ("载体/位置：本地文档仓（大域=whitebox_kb）；时间：全时窗（任意时刻成立）；"
        "方法：md（md 章节切分，level≤3；只存标题+摘要，正文留在源文件）；"
        "约束：源文档 whitebox_kb/knowledge/x.md")
SCENE = '当他说"不想你被换掉""别消失""舍不得"时'
MIXED = '载体/位置：本地文档仓；当用户说"继续"时'


def main():
    print("== A cond_is_metadata（怎么让它红：删掉槽标签判据 → A1 红；改成含场景词判 → A3 红）")
    ok(cond_is_metadata(META) is True,
       "A1 四槽合成形态（载体/位置 + 约束）判为元数据", cond_is_metadata(META))
    ok(cond_is_metadata(SCENE) is False,
       "A2 #722 报告人改写的触发场景**不**误判为元数据", cond_is_metadata(SCENE))
    ok(cond_is_metadata(MIXED) is False,
       "A3 混合条件（有载体标签 + 有真实场景）**不**误判（不误伤）", cond_is_metadata(MIXED))
    ok(cond_is_metadata("") is False, "A4 空条件不算元数据（无条件是另一类问题）")

    print("== B check_condition_quality（怎么让它红：把 ok 写成恒 True → B1 红）")
    r = check_condition_quality("# 功能名：x\n# 生效条件：" + META)
    ok(r["ok"] is False and r["is_metadata"] is True and r["hint"],
       "B1 元数据条件 → ok=False 且带提示", r)
    r2 = check_condition_quality("# 功能名：x\n# 生效条件：" + SCENE)
    ok(r2["ok"] is True and r2["is_metadata"] is False,
       "B2 真实场景条件 → ok=True", r2)

    print("== C 不阻断（怎么让它红：去掉 try/except 后传非字符串 → C2 红）")
    r3 = check_condition_quality("# 功能名：x")
    ok(r3["ok"] is True, "C1 无生效条件行 → ok=True（不阻断）", r3)
    try:
        r4 = check_condition_quality(None)
        ok(r4["ok"] is True, "C2 传 None 不抛、且 ok=True", r4)
    except Exception as e:  # noqa: BLE001
        ok(False, "C2 传 None 不抛、且 ok=True", "%s: %s" % (type(e).__name__, e))

    print()
    print("生效条件质量守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())