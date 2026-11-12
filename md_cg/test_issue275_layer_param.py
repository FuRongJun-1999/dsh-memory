# -*- coding: utf-8 -*-
"""检索 layer 参数的 fail-closed 守卫（issue #275）。

【守什么】
#275 报：非法层名与「合法但空」的层**返回逐字节相同** ⇒ 调用方无法区分
「我传了非法层名」与「那一层确实没有节点」，**不会去查自己的参数**。

同一签名的另两个参数是 fail-closed（view / time_axis 都抛 ValueError），
add(layer=) 也有校验（未知层：…（允许：…））—— 只有 search 侧漏接。

判据：
  L1 非法层名 **报错**（不再是静默空结果）。
  L2 报错文案与 add 侧**同口径**（未知层：…（允许：…））——不发明第二套话术。
  L3 **反向判据**：合法层的**空结果**行为**不得**改变（防把「真空结果」也报成错误）。
  L4 **反向判据**：不传 layer ⇒ **仍须**正常检索。
  L5 **反向判据**：假值（None / 空串）一律视为「未指定」，逐位保留原行为。
  L6 **同签名一致性**：view / time_axis 的非法值同样报错（本条对照的立足点）。
  L7 非法层名**即使查询本可命中**也报错（防「先过滤再看有没有结果」的实现漏网）。
  L8 MCP 面 schema 不约束 layer ⇒ 模型可控输入必须靠本校验兜底（实测 schema 无 enum）。

运行：python -X utf8 -m md_cg.test_issue275_layer_param
      python -X utf8 -m md_cg.test_issue275_layer_param --mutate   # 定点变异自证

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红。

沙箱纪律：库根落守卫临时目录，绝不碰在役库与 ~/.mdcg。
"""
from __future__ import annotations

import io
import os
import sys
import tempfile

from .mdcos import MdCGOS
from .mdcg import LAYERS

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

_PASS: list = []
_FAIL: list = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  -> " + str(extra)) if (extra and not cond) else ""))


def _cg(tag):
    root = tempfile.mkdtemp(prefix="l275_%s_" % tag)
    cg = MdCGOS(root)
    cg.add(content="# 一条知识\n\n内容。", layer="knowledge", node_id="k1",
           importance=0.5, consistency=False, on_conflict="defer")
    return cg


def l1():
    print("== L1 非法层名报错（不再静默空结果）==")
    cg = _cg("l1")
    for bad in ("bogus", "knowledg", "Knowledge", "knowledge ", "锚点"):
        try:
            r = cg.search("知识", layer=bad)
            ok(False, "L1 非法层名 %r 应当报错（实际静默返回 %r）" % (bad, r[1]), r)
        except ValueError:
            ok(True, "L1 非法层名 %r 报 ValueError" % bad)
        except Exception as exc:                              # noqa: BLE001
            ok(False, "L1 非法层名 %r 抛了非 ValueError：%r" % (bad, exc), exc)


def l2():
    print("== L2 报错文案与 add 侧同口径 ==")
    cg = _cg("l2")
    try:
        cg.search("知识", layer="bogus")
        ok(False, "L2 未报错，无法比对文案")
        return
    except ValueError as exc:
        msg = str(exc)
    try:
        cg.add(content="x", layer="bogus", node_id="b1",
               consistency=False, on_conflict="defer")
        ok(False, "L2 add 侧未报错，无法比对")
        return
    except ValueError as exc2:
        msg2 = str(exc2)
    ok(msg == msg2, "L2 search 与 add 报错文案逐字一致", (msg, msg2))
    ok("未知层" in msg and "允许" in msg, "L2 文案含「未知层」「允许」", msg)


def l3():
    print("== L3 反向判据：合法层的空结果行为不变 ==")
    cg = _cg("l3")
    for lay in LAYERS:
        if lay == "knowledge":
            continue
        r = cg.search("知识", layer=lay)
        ok(isinstance(r, tuple) and len(r) == 2 and r[0] == [],
           "L3 合法空层 %r 仍返回空结果（不报错）" % lay, r)
        ok(r[1].get("reason") == "no_candidates",
           "L3 合法空层 %r 的 meta.reason 仍为 no_candidates" % lay, r[1])
    r = cg.search("知识", layer="knowledge")
    ok(len(r[0]) == 1, "L3 有节点的合法层仍正常返回 1 条", len(r[0]))


def l4():
    print("== L4 反向判据：不传 layer 仍正常检索 ==")
    cg = _cg("l4")
    r = cg.search("知识")
    ok(len(r[0]) == 1, "L4 不传 layer 命中 1 条", len(r[0]))


def l5():
    print("== L5 反向判据：假值一律视为「未指定」 ==")
    cg = _cg("l5")
    for falsy in (None, ""):
        r = cg.search("知识", layer=falsy)
        ok(len(r[0]) == 1, "L5 layer=%r 视为未指定，仍命中 1 条" % (falsy,), len(r[0]))


def l6():
    print("== L6 同签名一致性：view / time_axis 同样报错 ==")
    cg = _cg("l6")
    for kw, name in (({"view": "bogus"}, "view"),
                     ({"time_axis": "bogus"}, "time_axis")):
        try:
            cg.search("知识", **kw)
            ok(False, "L6 %s 非法值应当报错" % name)
        except ValueError:
            ok(True, "L6 %s 非法值报 ValueError（与本条同处置）" % name)
        except Exception as exc:                              # noqa: BLE001
            ok(False, "L6 %s 抛了非 ValueError：%r" % (name, exc), exc)


def l7():
    print("== L7 非法层名即使查询本可命中也报错 ==")
    cg = _cg("l7")
    ok(len(cg.search("知识")[0]) == 1, "L7 前置：该查询在无 layer 时确可命中")
    try:
        cg.search("知识", layer="knowledg")
        ok(False, "L7 拼错层名 + 可命中查询：应当报错（防先过滤后判定）")
    except ValueError:
        ok(True, "L7 拼错层名 + 可命中查询：报 ValueError")


def l8():
    print("== L8 MCP 面 schema 不约束 layer ⇒ 靠本校验兜底 ==")
    p = os.path.join(_REPO, "md_cg", "mcp_server.py")
    with io.open(p, encoding="utf-8", errors="replace") as f:
        text = f.read()
    i = text.find('"name": "mdcg_search"')
    ok(i > 0, "L8 前置：找到 mdcg_search 工具定义", i)
    seg = text[i:i + 900]
    ok('layer=_p("string", "限定层")' in seg,
       "L8 MCP schema 的 layer 无 enum 约束（模型可控输入）", seg[:160])


_GROUPS = (l1, l2, l3, l4, l5, l6, l7, l8)


def _run_groups() -> int:
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                              # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-800:])
    return len(_FAIL)


def main() -> int:
    n = _run_groups()
    print("\nlayer 参数 fail-closed 守卫：%d 通过，%d 失败" % (len(_PASS), n))
    return 1 if n else 0


# --------------------------------------------------------------- 定点变异自证
# 变异在**源码**上做（本守卫的判据是「真跑 search」），故须写盘 + reload，
# 跑完 finally 复原。锚点漂移即判 BAD（不静默跳过）。
_MUTATIONS = (
    ("V1 去掉 layer 校验（退回静默空结果）", "drop_guard"),
    ("V2 把校验放宽为「只在命中为空时才报」（先过滤后判定）", "late_guard"),
)


def _reload():
    import importlib
    from . import mdcg as _m
    from . import mdcos as _o
    importlib.reload(_m)
    importlib.reload(_o)
    globals()["LAYERS"] = _m.LAYERS
    globals()["MdCGOS"] = _o.MdCGOS


def _mutate() -> int:
    bad = []
    src_p = os.path.join(_REPO, "md_cg", "mdcos.py")
    for name, kind in _MUTATIONS:
        with io.open(src_p, encoding="utf-8", newline="") as f:
            orig = f.read()
        NL = "\r\n" if "\r\n" in orig else "\n"
        try:
            if kind == "drop_guard":
                anchor = NL.join([
                    '        if layer and layer not in LAYERS:',
                    '            raise ValueError(f"未知层：{layer}（允许：{LAYERS}）")',
                ])
                repl = ""
            else:
                anchor = NL.join([
                    '        if layer and layer not in LAYERS:',
                    '            raise ValueError(f"未知层：{layer}（允许：{LAYERS}）")',
                ])
                repl = NL.join([
                    '        _bad_layer = bool(layer and layer not in LAYERS)',
                ])
            if anchor not in orig:
                print("  ANCHOR-MISS %s" % name)
                bad.append(name)
                continue
            with io.open(src_p, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(anchor, repl))
            _reload()
            _run_groups()
            reds = list(_FAIL)
            hit = any("L1" in r for r in reds)
            print("  %-4s %-46s 红项=%-3d 命中L1=%s"
                  % ("OK" if hit else "BAD", name, len(reds), "是" if hit else "否"))
            if not hit:
                bad.append(name)
        finally:
            with io.open(src_p, "w", encoding="utf-8", newline="") as f:
                f.write(orig)
            _reload()
    if bad:
        print("\n定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print("\n定点变异自证：PASS（每处判据都被打红）")
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(_mutate())
    sys.exit(main())
