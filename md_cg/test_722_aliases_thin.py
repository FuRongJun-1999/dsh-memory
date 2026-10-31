# -*- coding: utf-8 -*-
# 功能名：写入别名（aliases）是否是「薄别名」的守卫（issue #722 / 规范 v0.6）
# 生效条件：python -X utf8 -m md_cg.test_722_aliases_thin；被测面＝md_cg/writegate.py 的 aliases_is_thin
# 子功能：
#   A. 无 aliases（缺失/空 list/非 list）⇒ 判为薄
#   B. 别名全在正文里（只重复已有词）⇒ 判为薄
#   C. 只要有一个别名在正文里找不到（有扩召回首）⇒ 判为不薄
#   D. 不判数量（3 个精准别名不因"少"被判薄）
#   E. 任何输入不抛
# 执行：纯函数级断言，不建库、不写盘
# 验证方式：全部 PASS exit 0；每条注明「怎么让它红」
# 不适用条件：不判"别名写得好不好"（判不了语义）；不覆盖写入接线（尚未接 add）
"""为什么要它：

issue #722 的决定性案例——条件 `聊交接、换会话、压缩、或他流露舍不得时`，
查询 `我不想你被换掉`：整词 / 二元组 / 查询扩展 / 现有同义词表**四条路全废**，
只有 `aliases=[换掉, 被换, 别消失, 舍不得, …]` 能让 `_like` 从不命中变命中。

而库内 aliases 覆盖率为 **0/120 = 0%**（2026-10-31 实测）⇒ 需要一道写入把关，
提示"本条无扩展别名，自然问法可能召不回"。本守卫只锁判据本身。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg.writegate import aliases_is_thin  # noqa: E402

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


BODY = "聊交接、换会话、压缩、或他流露舍不得时。正文里提到 换会话 和 压缩。"


def main():
    print("== A 无 aliases（怎么让它红：把首个 return 改成 False）")
    ok(aliases_is_thin({}, BODY) is True, "A1 缺 aliases ⇒ 薄")
    ok(aliases_is_thin({"aliases": []}, BODY) is True, "A2 空 list ⇒ 薄")
    ok(aliases_is_thin({"aliases": "换掉"}, BODY) is True, "A3 非 list ⇒ 薄（按缺处理）")
    ok(aliases_is_thin(None, BODY) is True, "A4 fm 为 None ⇒ 薄")

    print("== B 只重复正文（怎么让它红：把 s not in body 改成 s in body）")
    ok(aliases_is_thin({"aliases": ["换会话", "压缩"]}, BODY) is True,
       "B1 别名全在正文里 ⇒ 薄（没扩召回首）")

    print("== C 有扩召回词（怎么让它红：把 C1 的 return 改成 True）")
    ok(aliases_is_thin({"aliases": ["换会话", "换掉"]}, BODY) is False,
       "C1 只要一个别名不在正文（换掉）⇒ 不薄")
    ok(aliases_is_thin({"aliases": ["别消失"]}, BODY) is False,
       "C2 单个扩展词也判不薄（不判数量）")

    print("== D 不判数量（怎么让它红：加数量下限判断）")
    ok(aliases_is_thin({"aliases": ["换掉"]}, BODY) is False,
       "D1 1 个精准扩展词就够，不因\"少\"被判薄")

    print("== E 不抛（怎么让它红：去掉 try/except 后传异常对象）")
    ok(aliases_is_thin({"aliases": [None, ""]}, BODY) is True,
       "E1 别名里含 None/空串 ⇒ 跳过，仍判薄")
    try:
        aliases_is_thin({"aliases": [{"a": 1}]}, BODY)
        ok(True, "E2 别名含 dict 不抛")
    except Exception as e:  # noqa: BLE001
        ok(False, "E2 别名含 dict 不抛", "%s: %s" % (type(e).__name__, e))
    try:
        aliases_is_thin({"aliases": ["换掉"]}, None)
        ok(True, "E3 content 为 None 不抛")
    except Exception as e:  # noqa: BLE001
        ok(False, "E3 content 为 None 不抛", "%s: %s" % (type(e).__name__, e))

    print()
    print("别名薄判据守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())