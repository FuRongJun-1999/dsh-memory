# -*- coding: utf-8 -*-
# 功能名：宪章第十五条（复读污染）守卫——注入过滤 / history 去重 / 污染清除
# 生效条件：python -X utf8 -m md_cg.test_repeat_guard_charter15；被测面＝md_cg/repeat_guard.py 的 scan/annotate/dedupe
# 子功能：①长文本重复被判、短指令重复不判（minChars 保护非空转）②minCount 分界 ③dedupe 只留最新一条且幂等 ④annotate/dedupe 不改入参 dict（只改副本）⑤脏数据容错 ⑥text_suffix 确定性
# 执行：纯函数级断言，不依赖真实库与磁盘
# 验证方式：全部 PASS exit 0；每条都写明「怎么让它红」
# 不适用条件：不判模型侧是否真的复读（本模块只判事件窗口内的重复）；不判注入面渲染（接入在 session_recall，另批）
"""宪章第十五条此前**只有条文没有实现**（`src/` 与 `md_cg/` 搜「复读/degenerat」零命中）。

本守卫盯的是实现里的三个易错点：
  ① `minChars` 保护是否空转（短指令「好」「继续」重复属正常对话，不该判污染）；
  ② `dedupe` 是否真的「只留最新一条」且**幂等**；
  ③ `annotate`/`dedupe` 是否**不改入参**（库内正文保真，只改注入副本）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import repeat_guard as rg  # noqa: E402

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


def main():
    LONG = "这是一条足够长的测试消息内容，用于验证重复检测"
    print("== A minChars 保护（防短指令误判）")
    short_evs = [{"role": "user", "text": "好", "t": i} for i in range(5)]
    ok(len(rg.scan(short_evs, min_count=3, min_chars=0)) == 1,
       "A1 minChars=0 时「好」×5 **会**被判（证明该参数真的在起作用）",
       rg.scan(short_evs, min_count=3, min_chars=0))
    ok(len(rg.scan(short_evs, min_count=3, min_chars=12)) == 0,
       "A2 minChars=12 时「好」×5 **不**被判（正确：短指令重复属正常对话）",
       rg.scan(short_evs, min_count=3, min_chars=12))

    print("== B minCount 分界")
    evs = [{"role": "assistant", "text": LONG, "t": i} for i in range(4)]
    ok(len(rg.scan(evs, min_count=3)) == 1, "B1 ×4 且 minCount=3 → 命中")
    ok(len(rg.scan(evs, min_count=5)) == 0,
       "B2 ×4 且 minCount=5 → **不**命中（阈值真的生效，非恒真）")

    print("== C dedupe：只留最新一条 + 幂等")
    seq = [{"role": "assistant", "text": LONG, "t": i, "tag": "v%d" % i} for i in range(5)]
    out = rg.dedupe(seq, min_count=3)
    ok(len(out) == 1, "C1 5 条重复折叠成 1 条", len(out))
    ok(out[0].get("tag") == "v4",
       "C2 **保留的是最新一条**（v4，不是 v0）——去重方向不能搞反", out[0].get("tag"))
    ok((out[0].get("repeat") or {}).get("count") == 5,
       "C3 折叠后的条目带 repeat.count=5（信息不丢）", out[0].get("repeat"))
    ok(len(rg.dedupe(out, min_count=3)) == 1,
       "C4 幂等：对已折叠结果再跑一次，条数不变")

    print("== D 不改入参（库内正文保真）")
    lst = [{"role": "assistant", "text": LONG, "t": i} for i in range(4)]
    ann = rg.annotate(lst, min_count=3)
    ok(all("repeat" not in r for r in lst),
       "D1 annotate **不改入参 dict**（只改返回副本）", [r for r in lst if "repeat" in r][:1])
    ok(any("repeat" in r for r in ann), "D2 返回的副本带 repeat 标注")
    ok(len(ann) == len(lst), "D3 annotate 不改变条数（只标不折）")

    print("== E 容错")
    dirty = [None, 1, "x", {"text": None}, {"role": None, "text": LONG}]
    try:
        h = rg.scan(dirty, min_count=1)
        ok(True, "E1 脏数据（None/数字/字符串/text=None）不抛异常", len(h))
    except Exception as e:  # noqa: BLE001
        ok(False, "E1 脏数据不抛异常", "%s: %s" % (type(e).__name__, e))

    print("== F text_suffix 确定性")
    ok(rg.text_suffix(LONG) == rg.text_suffix(LONG), "F1 同一 text 恒得同一串（可用作判据）")
    ok(rg.text_suffix(LONG) != rg.text_suffix(LONG + "x"), "F2 不同 text 得不同串")
    ok(len(rg.text_suffix("")) == 8, "F3 空串也返回 8 位（不抛）")

    print()
    print("宪章第十五条守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())