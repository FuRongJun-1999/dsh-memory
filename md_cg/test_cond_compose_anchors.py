# -*- coding: utf-8 -*-
"""cond_compose 行为锚点（在途 WIP 并集解）探针：脚本式，exit code 定成败。

背景：2026-09-19 收口两线时，工作区残留一处 stash-pop 冲突（md_cg/cond_compose.py）：
  ours(HEAD)=compose 的「生效条件」注释；theirs(stash)=新增 behavior_anchors()。
两侧新增互不重叠 → 并集解（本分支）。该函数当前**全库无调用**，故本探针只把
「冲突解正确 + 函数行为与文档一致」钉住，配线与否由使用者裁决。

用法：python -X utf8 -m md_cg.test_cond_compose_anchors
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import cond_compose as cc  # noqa: E402

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + detail)


def main():
    # 1) 并集完整性：冲突两侧的东西都在，且文件里没有冲突标记
    src = open(cc.__file__, encoding="utf-8").read()
    check("并集：compose 与 behavior_anchors 同时在",
          hasattr(cc, "compose") and hasattr(cc, "behavior_anchors"))
    check("并集：无冲突标记", "<<<<<<<" not in src and ">>>>>>>" not in src)
    check("并集：compose 的生效条件注释未丢", "调用 compose 时必须提供 rec" in src)

    # 2) behavior_anchors 行为（按实现口径逐条断言）
    rec = {"name": "f", "doc_head": "  计算 a 的摘要  ",
           "guards": [{"early": True, "cond": "a"},
                      {"early": False, "cond": "a"},
                      {"early": True, "cond": "a and b"}],
           "returns": ["a.strip()", "LIMIT + 1", "local_only"]}
    doc, guards, rets = cc.behavior_anchors(rec, {"a"})
    check("doc 取 doc_head 并去空白", doc == "计算 a 的摘要", repr(doc))
    # explained_guards 的两道筛：early 必须为真；cond 内标识符必须全在 allowed∪BUILTINS∪self/cls
    # （故 "a" 入选、"a and b" 因 b 不在 allowed 被剔、"a is None" 会因 is 不是 builtins 被剔）
    check("guards 只留 early 且标识符合规者（走 explained_guards）",
          [g.get("cond") for g in guards] == ["a"], str(guards))
    check("returns 只留含 allowed 标识符者", rets == ["a.strip()"], str(rets))
    _d2, _g2, rets2 = cc.behavior_anchors(rec, {"a", "LIMIT"})
    check("allowed 含模块常量时其返回表达式入选（调用方负责传 入参∪常量）",
          rets2 == ["a.strip()", "LIMIT + 1"], str(rets2))

    # 3) 「只有形参清单、无任何行为锚点」→ 三元组全空（调用方据此可判 BLINDSPOT）
    empty = cc.behavior_anchors({"name": "g", "guards": [], "returns": []}, {"x"})
    check("无形为锚点时返回空三元组", empty == ("", [], []), str(empty))
    check("缺失 doc_head/returns 键不抛异常",
          cc.behavior_anchors({"name": "h"}, {"x"}) == ("", [], []))

    # 4) 未回归：compose 仍能产出以「。」结尾的条件串
    s = cc.compose({"name": "f", "required": ["a"], "optional": [], "externals": [],
                    "guards": [], "returns": ["a.strip()"], "doc_head": "摘要"})
    check("compose 未回归（非空且以「。」结尾）",
          isinstance(s, str) and s.endswith("。") and len(s) > 4, s[:60])

    print("\ntest_cond_compose_anchors: %d 通过 / %d 失败" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
