# -*- coding: utf-8 -*-
"""condition_anchor 验收：四类裁决 + 边界（self/cls、kwonly、默认值常量、不可判）。

验收口径：本模块只判「锚点是否存在」，不判语义正确性；不可判必须 BLINDSPOT，不得默认通过。
"""
from __future__ import annotations

from . import condition_anchor as ca

_ok = 0
_bad = []


def _check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("  ok   %s" % name)
    else:
        _bad.append("%s %s" % (name, detail))
        print("  FAIL %s %s" % (name, detail))


SRC_REQ = "def f(root, patterns=None):" + chr(10) + "    return os.walk(root)" + chr(10)
SRC_KW = "def g(a, *, limit, mode=1):" + chr(10) + "    return scan(a, limit, mode)" + chr(10)
SRC_CLS = "class C:" + chr(10) + "    def m(self, x):" + chr(10) + "        return x" + chr(10)
SRC_BARE = "def h():" + chr(10) + "    return 1" + chr(10)
SRC_CONST = "def k(x=1):" + chr(10) + "    return x + LIMIT" + chr(10)
SRC_BROKEN = "def n(:" + chr(10) + "    pass" + chr(10)


def main():
    print("=" * 68)
    print("md_cg condition_anchor 验收（候选生效条件的锚点机械判据）")
    print("=" * 68)
    r = ca.judge("root 为可遍历路径", SRC_REQ)
    _check("A1 锚定必需参数 → ANCHORED 且 ok", r["verdict"] == "ANCHORED" and r["ok"] is True, str(r))
    _check("A2 锚点清单含 root（不含 patterns）",
           r["anchors"] == ["root"] and "patterns" in r["optional"], str(r["anchors"]))
    _check("A3 默认值参数归入 optional", r["optional"] == ["patterns"], str(r["optional"]))
    r = ca.judge("limit 为正整数", SRC_KW)
    _check("A4 kwonly 无默认值算必需参数", r["verdict"] == "ANCHORED" and r["anchors"] == ["limit"], str(r))
    r = ca.judge("x 为整数", SRC_CLS)
    _check("A5 class 内方法：self 被跳过、锚定 x", r["verdict"] == "ANCHORED" and r["anchors"] == ["x"], str(r))
    r = ca.judge("LIMIT 已定义", SRC_CONST)
    _check("A6 体内外部引用（常量）可作锚点", r["verdict"] == "ANCHORED" and r["anchors"] == ["LIMIT"], str(r))
    r = ca.judge("该函数总是正确", SRC_REQ)
    _check("A7 无锚点 → WEAK 且 ok=False（不默认通过）",
           r["verdict"] == "WEAK" and r["ok"] is False, str(r))
    r = ca.judge("源文件存在于本地仓", SRC_REQ)
    _check("A8 索引元条件话术 → REJECT_META", r["verdict"] == "REJECT_META" and r["meta_marks"], str(r))
    r = ca.judge("x 为整数", SRC_BARE)
    _check("A9 无参数且无引用 → BLINDSPOT（不猜测）", r["verdict"] == "BLINDSPOT", str(r))
    r = ca.judge("x 为整数", SRC_BROKEN)
    _check("A10 源码不可解析 → BLINDSPOT", r["verdict"] == "BLINDSPOT", str(r))
    r = ca.judge("root 为可遍历路径", SRC_REQ)
    r2 = ca.judge("root 为可遍历路径", SRC_REQ)
    _check("A11 判定确定性（同输入同结果）", r == r2)
    _check("A12 prefix/suffix 仅回显、不参与判定",
           ca.judge("root 为可遍历路径", SRC_REQ, prefix="【1】")["verdict"] == "ANCHORED")
    b = ca.judge_batch([("a", "root 为可遍历路径", SRC_REQ),
                        ("b", "该函数总是正确", SRC_REQ),
                        ("c", "源文件存在", SRC_REQ)])
    _check("A13 批量统计正确（ANCHORED/WEAK/REJECT_META 各 1）",
           b["stats"].get("ANCHORED") == 1 and b["stats"].get("WEAK") == 1
           and b["stats"].get("REJECT_META") == 1 and b["ok"] == 1, str(b["stats"]))
    _r = ca.judge("tree 为 AST 节点", "class NoInit:" + chr(10) + "    x = 1" + chr(10))
    _check("A14 无 __init__ 的类不崩溃并给出裁决",
           _r["verdict"] in ("ANCHORED", "WEAK", "BLINDSPOT"), str(_r))
    _r = ca.judge("x 为整数", "class C:" + chr(10) + "    def __init__(self, x):" + chr(10) + "        self.x = x" + chr(10))
    _check("A15 有 __init__ 的类按其形参锚定",
           _r["verdict"] == "ANCHORED" and _r["anchors"] == ["x"], str(_r))
    print()
    print("PASS %d / FAIL %d" % (_ok, len(_bad)))
    for x in _bad:
        print("  - " + x)
    return 1 if _bad else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())